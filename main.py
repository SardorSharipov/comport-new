import logging
from logging.handlers import RotatingFileHandler
import os
import time
from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusIOException
from telegram import Bot
from telegram.error import TelegramError
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

load_dotenv('config.env')
log_file = 'data.log'
if os.path.exists(log_file):
    os.remove(log_file)
log = logging.getLogger()
log.setLevel(logging.INFO)
handler = RotatingFileHandler(log_file, maxBytes=10240, backupCount=1)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
log.addHandler(handler)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
SLAVE_IDS = [s.strip() for s in os.getenv('SLAVE_IDS').split(',') if s.strip() != '']
PORT_NAMES = [s.strip() for s in os.getenv('PORT_NAMES').split(',') if s.strip() != '']
POSTGRES_TABLE = os.getenv('POSTGRES_TABLE')
POSTGRES_USERNAME = os.getenv('POSTGRES_USERNAME')
POSTGRES_DATABASE = os.getenv('POSTGRES_DATABASE')
POSTGRES_PORT = os.getenv('POSTGRES_PORT')
POSTGRES_HOST = os.getenv('POSTGRES_HOST')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD')
TIMER_SECONDS = int(os.getenv('TIMER_SECONDS'))
DAILY_HOUR = int(os.getenv('DAILY_HOUR'))
DAILY_MINUTE = int(os.getenv('DAILY_MINUTE'))
IP_ADDRESS = os.getenv('IP_ADDRESS')

bot = Bot(token=TELEGRAM_TOKEN)
port_slaves = {}
slaves_port = {}
for i in range(len(SLAVE_IDS)):
    port_slaves[PORT_NAMES[i]] = int(SLAVE_IDS[i])
    slaves_port[int(SLAVE_IDS[i])] = PORT_NAMES[i]

db_params = {
    'dbname': POSTGRES_DATABASE,
    'user': POSTGRES_USERNAME,
    'password': POSTGRES_PASSWORD,
    'host': POSTGRES_HOST,
    'port': POSTGRES_PORT
}


def check_com_port(port: str):
    client = ModbusSerialClient(
        method='rtu',
        port=port,
        baudrate=9600,
        timeout=1,
        parity='N',
        stopbits=1,
        bytesize=8
    )

    connection = client.connect()
    if not connection:
        return False

    try:
        rr = client.read_holding_registers(address=port_slaves[port], count=0, unit=2)
        if isinstance(rr, ModbusIOException):
            return False
        else:
            rr = [rr.registers[0] >> 8, rr.registers[0], rr.registers[1] >> 8, rr.registers[1]]
            int_value = (rr[0] << 24) | (rr[1] << 16) | (rr[2] << 8) | rr[3]
            return int_value
    except Exception as e:
        log.error(f'Ошибка чтения с {port}: {e}')
        return False
    finally:
        client.close()


def send_telegram_message(message):
    try:
        bot.send_message(chat_id=CHAT_ID, text=message)
    except TelegramError as e:
        log.error(f'Не удалось отправить сообщение в телеграм: {e}')


def get_last_value(slave_id):
    conn = None
    try:
        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()
        query_check = sql.SQL(f'''
            SELECT 
                indate, 
                weight 
            FROM {POSTGRES_TABLE} 
            WHERE address = {slave_id}
            ORDER BY indate DESC
            LIMIT 1
        ''')
        cursor.execute(query_check, )
        last_value = cursor.fetchone()
        cursor.close()
        return last_value
    except Exception as e:
        log.error(f'Ошибка чтения с базы данных: {e}')
    finally:
        if conn:
            conn.close()


def daily_check():
    message = f'Ежедневная проверка портов по IP: {IP_ADDRESS}\n'
    for port_name, slave_id in port_slaves.items():
        status = check_com_port(port_name)
        last_value = get_last_value(slave_id)
        if status is not False:
            message += f'Порт под salve_id={slave_id} не работает.\n'
        else:
            message += f'Порт под salve_id={slave_id} работает.'
        if last_value:
            message += f'Последняя запись=[indate={last_value[0]}, weight={last_value[1]}].\n'
    send_telegram_message(message)


def write_to_db(port, value):
    conn = None
    try:
        last_value = get_last_value(port_slaves[port])
        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()
        if last_value is None or last_value[0] != value:
            query_insert = sql.SQL(f'''
                INSERT INTO {POSTGRES_TABLE} (address, weight, indate)
                VALUES ({port_slaves[port]}::SMALLINT, {value}::FLOAT, CURRENT_TIMESTAMP)
            ''')
            cursor.execute(query_insert, (port, value, datetime.now()))
            conn.commit()
            log.info(f'Новая запись для {port}={value}')
        else:
            log.info(f'Нет новой записи для {port}, последняя запись[indate={last_value[0]}, weight={last_value[1]}]')
        cursor.close()
    except Exception as e:
        log.error(f'Ошибка чтения с базы данных: {e}')
    finally:
        if conn:
            conn.close()


def scheduled_read():
    for port in port_slaves:
        value = check_com_port(port)
        if value is not False:
            log.info(f'Успешно прочли данные с порта={port} slave_id={port_slaves[port]}, значение={value}')
            write_to_db(port, value)
        else:
            log.error(f'Ошибка чтения порта={port}, slave_id={port_slaves[port]}')


scheduler = BackgroundScheduler()
scheduler.add_job(daily_check, 'cron', hour=DAILY_HOUR, minute=DAILY_MINUTE)
scheduler.add_job(scheduled_read, 'interval', seconds=TIMER_SECONDS)

scheduler.start()

try:
    while True:
        time.sleep(1)
except (KeyboardInterrupt, SystemExit):
    scheduler.shutdown()
    log.info('Приложение остановлено.')
except Exception as ex:
    log.error('Ошибка в приложение, %s', ex)

import asyncio
import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

import psycopg2
import serial
import serial.tools.list_ports
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from psycopg2 import sql
from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusIOException
from telegram import Bot
from telegram.error import TelegramError

load_dotenv('config.env')
log_file = 'data.log'
if os.path.exists(log_file):
    os.remove(log_file)
log = logging.getLogger()
log.setLevel(logging.INFO)
handler = TimedRotatingFileHandler(filename=log_file, interval=3, backupCount=3)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
log.addHandler(handler)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

DESCRIPTIONS = [s.strip() for s in os.getenv('DESCRIPTIONS').split(',') if s.strip() != '']
PROTOCOLS = [s.strip() for s in os.getenv('PROTOCOLS').split(',') if s.strip() != '']
SLAVE_IDS = [s.strip() for s in os.getenv('SLAVE_IDS').split(',') if s.strip() != '']
VIDS = [int(s.strip()) for s in os.getenv('VIDS').split(',') if s.strip() != '']
PIDS = [int(s.strip()) for s in os.getenv('PIDS').split(',') if s.strip() != '']

SENDING_INTER_COUNT = int(os.getenv('SENDING_ITERATION_COUNT'))
POSTGRES_TABLE = os.getenv('POSTGRES_TABLE')
POSTGRES_USERNAME = os.getenv('POSTGRES_USERNAME')
POSTGRES_DATABASE = os.getenv('POSTGRES_DATABASE')
POSTGRES_PORT = os.getenv('POSTGRES_PORT')
POSTGRES_HOST = os.getenv('POSTGRES_HOST')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD')
TIMER_SECONDS = int(os.getenv('TIMER_SECONDS'))
DAILY_HOUR = int(os.getenv('DAILY_HOUR'))
DAILY_MINUTE = int(os.getenv('DAILY_MINUTE'))
DAILY_INTERVAL = int(os.getenv('DAILY_INTERVAL'))
IP_ADDRESS = os.getenv('IP_ADDRESS')

port_slaves = {}
slaves_port = {}
port_protocol = {}
port_description = {}
PORT_NAMES = []
ports = serial.tools.list_ports.comports()

for i in range(len(SLAVE_IDS)):
    name = ''
    for p in ports:
        if p.vid == VIDS[i] and p.pid == PIDS[i]:
            name = p.device
    if '/dev/ttyUSB' in name:
        PORT_NAMES.append(name)
        port_slaves[PORT_NAMES[i]] = int(SLAVE_IDS[i])
        slaves_port[int(SLAVE_IDS[i])] = PORT_NAMES[i]
        port_protocol[PORT_NAMES[i]] = PROTOCOLS[i]
        port_description[PORT_NAMES[i]] = DESCRIPTIONS[i]

log.info('PORTS: %s', PORT_NAMES)
db_params = {
    'dbname': POSTGRES_DATABASE,
    'user': POSTGRES_USERNAME,
    'password': POSTGRES_PASSWORD,
    'host': POSTGRES_HOST,
    'port': POSTGRES_PORT
}


def check_com_port(port: str):
    if port_protocol[port] == 'modbus':
        client = ModbusSerialClient(
            method='rtu',
            port=port,
            baudrate=19200,
            timeout=1,
            parity='N',
            stopbits=1,
            bytesize=8
        )

        connection = client.connect()
        if not connection:
            log.warning('Ошибка подключения')
            return False
        try:
            rr = client.read_holding_registers(address=0, slave=port_slaves[port], count=2)
            if isinstance(rr, ModbusIOException):
                log.warning(f'Ошибка чтения read_holding_registers {rr.message}')
                return False
            else:
                rr = [(rr.registers[0] >> 8) % 256, rr.registers[0] % 256, (rr.registers[1] >> 8) % 256, rr.registers[1] % 256]
                int_value = (rr[3] << 24) | (rr[2] << 16) | (rr[1] << 8) | rr[0]
                return int_value
        except Exception as e:
            log.warning(f'Ошибка чтения с {port}: {e}')
            return False
        finally:
            client.close()
    elif port_protocol[port] == 'sending':
        ser = serial.Serial(
            port=port,
            baudrate=19200,
            timeout=1,
            parity=serial.PARITY_NONE,
            stopbits=1,
            bytesize=8
        )
        try:
            if not ser.is_open:
                ser.open()
            data = ''
            for _ in range(SENDING_INTER_COUNT):
                data = ser.readline()
                data = ''.join(s for s in data.decode() if s in '0123456789ABCDEF')
                if len(data) == 64:
                    break
            if len(data) == 64:
                target_hex = data[46:54]
                numeric_value = int(target_hex, 16)
                logging.info(f'Sending value: {numeric_value}')
                return numeric_value
            else:
                logging.warning(f'Не удалось считать данные с порта, неправильный формат data={data}')
        except Exception as exs:
            logging.warning(f'Исключение на открытие порта, ex={exs}')
        finally:
            ser.close()
        return False
    else:
        logging.warning(f'Не удалось считать данные с порта, неправильный отправляемого типа={port_protocol[port]}')
        return False


async def send_telegram_message(message):
    bot = Bot(token=TELEGRAM_TOKEN)
    for _ in range(10):
        try:
            await bot.initialize()
            await asyncio.sleep(10)
            await bot.send_message(chat_id=CHAT_ID, text=message, write_timeout=30, connect_timeout=10)
            return
        except TelegramError as e:
            log.warning(f'Не удалось отправить сообщение в телеграм: {e}')
        finally:
            await bot.shutdown()


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

        query_day = sql.SQL(f'''
            SELECT 
                weight
            FROM {POSTGRES_TABLE} 
            WHERE address = {slave_id} AND indate >= CURRENT_TIMESTAMP - INTERVAL '1 DAY'
            ORDER BY indate ASC
            LIMIT 1
        ''')

        query_hour = sql.SQL(f'''
            SELECT 
                weight 
            FROM {POSTGRES_TABLE} 
            WHERE address = {slave_id} AND indate >= CURRENT_TIMESTAMP - INTERVAL '1 HOUR'
            ORDER BY indate ASC
            LIMIT 1
        ''')

        cursor.execute(query_check, )
        last_value = cursor.fetchone()

        cursor.execute(query_day, )
        last_day = cursor.fetchone()

        cursor.execute(query_hour, )
        last_hour = cursor.fetchone()

        cursor.close()
        return last_value, last_day, last_hour
    except Exception as e:
        log.warning(f'Ошибка чтения с базы данных: {e}')
    finally:
        if conn:
            conn.close()


def write_to_db(port, value):
    conn = None
    try:
        last_value, _, _ = get_last_value(port_slaves[port])
        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()
        coefficient = 10.0 if port_protocol[port] == 'modbus' else 100.0
        if last_value is None or int(last_value[1] * coefficient) != value:
            query_insert = sql.SQL(f'''
                INSERT INTO {POSTGRES_TABLE} (address, weight, indate)
                VALUES ({port_slaves[port]}::SMALLINT, {value / coefficient}::FLOAT, CURRENT_TIMESTAMP)
            ''')
            cursor.execute(query_insert, (port, value, datetime.now()))
            conn.commit()
            log.info(f'Новая запись для {port}={value}')
        else:
            log.info(f'Нет новой записи для {port}, последняя запись[indate={last_value[0]}, weight={last_value[1]}]')
        cursor.close()
    except Exception as e:
        log.warning(f'Ошибка чтения с базы данных: {e}')
    finally:
        if conn:
            conn.close()


async def daily_check():
    message = ''
    for port_name, slave_id in port_slaves.items():
        status = check_com_port(port_name)
        last_value, last_day, last_hour = get_last_value(slave_id)
        if status is False:
            message += f'\"{port_description[port_name]}\" №{slave_id} НЕ РАБОТАЕТ\n'
        else:
            message += f'\"{port_description[port_name]}\" №{slave_id}\n'
        if last_value:
            print(last_hour)
            print(last_value)
            last_day_diff = int(last_value[1] - last_day[0]) if last_day else 0
            last_hour_diff = int(last_value[1] - last_hour[0]) if last_hour else 0
            message += f'Всего={last_value[1]}\nДень={last_day_diff}\nЧас={last_hour_diff}\n'
            message += f'L={last_value[0].strftime("%Y-%m-%d: %H-%M-%S")}\n'
        else:
            message += 'последней записи еще нет!\n'
        message += '-' * 30 + '\n'
    await send_telegram_message(message)


def scheduled_read():
    for port in port_slaves:
        value = check_com_port(port)
        coefficient = 10.0 if port_protocol[port] == 'modbus' else 100.0
        if value is not False:
            log.info(f'Успешно прочли данные с порта={port} slave_id={port_slaves[port]}, значение={value / coefficient}')
            write_to_db(port, value)
        else:
            log.warning(f'Ошибка чтения порта={port}, slave_id={port_slaves[port]}')


scheduler = AsyncIOScheduler()
scheduler.add_job(daily_check, 'cron', hour=DAILY_HOUR, minute=DAILY_MINUTE)
if DAILY_INTERVAL > 0:
    scheduler.add_job(daily_check, 'interval', minutes=DAILY_INTERVAL, next_run_time=datetime.now())
scheduler.add_job(scheduled_read, 'interval', seconds=TIMER_SECONDS, next_run_time=datetime.now())
try:
    scheduler.start()
    asyncio.get_event_loop().run_forever()
except (KeyboardInterrupt, SystemExit):
    scheduler.shutdown()
    log.info('Приложение остановлено.')
except Exception as ex:
    log.warning(f'Ошибка в приложение, {ex}')

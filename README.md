# Считыватель весов

## Как запустить приложение?
**СНАЧАЛА НУЖНО POSTGRES ЗАПУСТИТЬ**
```bash
python3 ports.py
```
Выводится сообщения типа:
`COMPORT: ... VID:PID=1111:2222`
`COMPORT: ... VID:PID=3333:4444`
Вводим в файл `config.env` (можно через)
```bash
sudo nano config.env
```
Вводим `VID, PID, SLAVE_ID, PROTOCOL`
```dotenv
PROTOCOLS=sending,modbus,
VIDS=1111,3333,
PIDS=2222,4444,
SLAVE_IDS=59,64,
```
Потом можем запустить
```bash
python3 main.py
```

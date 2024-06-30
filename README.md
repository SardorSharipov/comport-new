# Считыватель весов
## Загрузка репозитория
```bash
git clone https://github.com/SardorSharipov/comport-new
```
## Установка python
```bash
sudo apt-get install python3 python-pip
```
## Установка зависимостей python
```bash
pip install -r requirements.txt
```
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
## Путь crontab
```crontab
@reboot root cd; cd comport-new; /usr/bin/python3 main.py
```
## Что обновить приложение с репозитория
```bash
git stash
git pull
git stash pop
```
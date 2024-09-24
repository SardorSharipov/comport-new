import serial.tools.list_ports

ports = serial.tools.list_ports.comports()

for port in sorted(ports):
    if '/dev/ttyUSB' in port.device:
        print(f'COMPORT: NAME={port.device}, LOCATION={port.location}, VID:PID={port.vid}:{port.pid}')
        print(port, port.serial_number, port.hwid)
    else:
        print(f'OTHER: NAME={port.device}, LOCATION={port.location}, VID:PID={port.vid}:{port.pid}')

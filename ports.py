import serial.tools.list_ports

ports = serial.tools.list_ports.comports()

for port in sorted(ports):
    if '/dev/ttyUSB' in port.device:
        print(port)
    else:
        print('ALL:', port)

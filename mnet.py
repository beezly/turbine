import serial
import struct
import time
from crc import CrcCalculator, Crc16


class Mnet:
    SOH = b'\x01'
    EOT = b'\x04'
    MAX_PACKET_SIZE = 300
    REQ_MULTIPLE_DATA = b'\x0c\x2a'
    REQ_DATA = b'\x0c\x28'

    class MnetPacket:
        def __init__(self, destination, source, packet_type, data_len, data, crc):
            self.destination = destination
            self.source = source
            self.packet_type = packet_type
            self.data_len = data_len
            self.data = data
            self.crc = crc

        def __str__(self):
            return 'sot:01 dst:{:02x} src:{:02x} type:{:04x} len:{:02x} data:{:s} crc:{:04x} eot:04'.format(self.destination, self.source, self.packet_type, self.data_len, self.data.hex(), self.crc)

    def __init__(self, device, id=b'\x01'):
        self.device = serial.Serial(port=device, baudrate=38400, timeout=2)
        self.id = id
        self.crc_calculator = CrcCalculator(Crc16.CCITT)

    def create_packet(self, destination, packet_type, data):
        dataff = data.replace(b'\xff', b'\xff\xff')
        packet = destination+self.id+packet_type + \
            len(data).to_bytes(1, byteorder='big')+dataff
        crc = self.crc_calculator.calculate_checksum(
            packet).to_bytes(2, byteorder='big')
        return self.SOH+packet+crc+self.EOT

    def send_packet(self, destination, packet_type, data):
        packet = self.create_packet(destination, packet_type, data)
        self.device.write(packet)
        return self.read_packet()

    def read_packet(self):
        header = self.device.read(6)
        (soh, destination, source, packet_type,
         data_len) = struct.unpack('!BBBHB', header)
        if data_len > 0:
            data = self.device.read(data_len)
        else:
            data = b''
        tail = self.device.read(3)
        (crc, eot) = struct.unpack('!HB', tail)
        packet = Mnet.MnetPacket(destination, source,
                                 packet_type, data_len, data, crc)
        return packet



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


DEST = b'\x02'

test = Mnet('/dev/ttyUSB0')
# test.send_packet(b'\x02', b'\xea\xe5', b'\x02')
# z = test.send_packet(DEST, b'\x00\x01', b'')
# if hex(z.packet_type) != '0x1390':
#    print(hex(z.packet_type))

# for x in range(65536):
#    bx = x.to_bytes(2, byteorder="big", signed=False)
#    z = test.send_packet(DEST, bx, b'')
#        print('sent: {:s} returned: {:s}, {:s}'.format(
#    if hex(z.packet_type) != '0x1390':
#            bx.hex(), hex(z.packet_type), str(z)))

#z = test.send_packet(DEST, b'\xea\xe5', b'')
# print(z)
# print(test.send_packet(DEST, b'\x0c\x2e',b'')) # SOME SORT OF LOGIN?
#print(test.send_packet(DEST, Mnet.REQ_DATA,b'\x01\x9c\x47\x00\x00'))
# LOGIN PACKET?
print('login')
print(test.send_packet(DEST, b'\x13\xa1', b'\x09\x7b\x13\xc1\xbe\x49\x97\xf1\x74\xfe\xbe\x7a\x11\xd2\x1f\x16\x39\xe5\x50\xdf\x09\x7a\x10\xdf\x40\x18\xd9\x55\x12\x40\x18\xd9\x55\x12\x40\x18\xd9\x55\x12\x40\x4f\x8d\x56\x12\x40\xd3\x63\x50\x12\x40\x18\xd9'))
# MODDED LOGIN
#print(test.send_packet(DEST, b'\x13\xa1',b'\x09\x7b\x13\xc1\xbe\x49\x97\xf1\x74\xfe\xbe\x7a\x11\xd2\x1f\x16\x39\xe5\x50\xdf\x09\x7a\x10\xdf\x40\x00\x00\x00\x00\x40\x00\x00\x00\x00\x40\x00\x00\x00\x00\x00\x00\x00\x00\x00\x40\x00\x00\x00\x00\x40\x00\x00'))
# VERY MODDED LOGIN
#print(test.send_packet(DEST, b'\x13\xa1', b'\x09\x7b\x13\xc1\xbe\x49\x97\xf1\x74\xfe\xbe\x7a\x11\xd2\x1f\x16\x39\xe5\x50\xdf\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'))
print(test.send_packet(DEST, b'\x0c\x28', b'\x00\x04\x00\x00'))
#print(test.send_packet(DEST, b'\x0c\x28',b'\x00\x04\x00\x00'))
#print(test.send_packet(DEST, b'\x0c\x2e',b''))
#print(test.send_packet(DEST, b'\xea\xe5', b'\x04'))

while True:
    #print('0c28 single 04')
    #print(test.send_packet(DEST, b'\x0c\x28',b'\x00\x04\x00\x00'))
    #print('0c28 single 01')
    #print(test.send_packet(DEST, b'\x0c\x28',b'\x00\x01\x00\x00'))

    #print('brake ops')
    # print(test.send_packet(DEST, Mnet.REQ_MULTIPLE_DATA,b'\x01\x7d\x0a\x00\x00')) # brake operation count
    # print(test.send_packet(DEST, Mnet.REQ_MULTIPLE_DATA,b'\x01\x80\xea\x00\x65')) # g1 production - produced
    #print('g1 prod multiple')
    #print('g1 prod single')
    # print(test.send_packet(DEST, Mnet.REQ_DATA,b'\x80\xea\x00\x65')) # g1 prod?
    #print('stopped time')
    # print(test.send_packet(DEST, Mnet.REQ_DATA, b'\x7d\x05\x00\x00')) # stopped time
    # print(test.send_packet(DEST, Mnet.REQ_DATA, b'\x7d\x06\x00\x00')) # g1 operation time
    #print('yaw 2 temp')
    #print(test.send_packet(DEST, Mnet.REQ_DATA, b'\xf2\x30\x00\x01'))

    #print('controller time')
    # print(test.send_packet(DEST, Mnet.REQ_DATA,b'\x4e\x26\x00\x00')) # controller time
    print('rotor revolutions')
    print(test.send_packet(DEST, Mnet.REQ_MULTIPLE_DATA,
          b'\x02\x9c\x46\x00\x00\x9c\x47\x00\x00'))
    print(test.send_packet(DEST, Mnet.REQ_DATA,              b'\x9c\x46\x00\x00'))
    print(test.send_packet(DEST, Mnet.REQ_DATA,              b'\x9c\x47\x00\x00'))
    time.sleep(1)
#print(test.send_packet(DEST, Mnet.REQ_DATA,b'\x01\xc3\x53\x00\x00'))
#print(test.send_packet(DEST, Mnet.REQ_DATA,b'\x01\xc3\x53\x00\x00'))
#print(test.send_packet(DEST, Mnet.REQ_DATA,b'\x01\xc3\x53\x00\x00'))
#print(test.send_packet(DEST, Mnet.REQ_DATA,b'\x01\xc3\x53\x00\x00'))
#print(test.send_packet(DEST, Mnet.REQ_DATA,b'\x01\xc3\x53\x00\x00'))

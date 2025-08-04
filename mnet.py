import struct
import sys
import datetime
from crc import Calculator, Crc16


class Mnet:
    SOH = b'\x01'
    EOT = b'\x04'
    MAX_PACKET_SIZE = 300
    REQ_MULTIPLE_DATA = b'\x0c\x2a'
    REQ_DATA = b'\x0c\x28'
    REQ_COMMAND = b'\x0c\x32'
    REQ_SERIAL_NUMBER = b'\x0c\x2e'
    LOGIN_131_GAIA_WIND = b'\x31\x33\x31\x20\x66\x6b\x59\x75\x29\x29\x31\x32\x32\x32\x31\x51\x51\x61\x61\x00'
    LOGIN_PACKET_ID = 0x7b

    DATA_ID_WIND_SPEED = b'\x9c\x43'
    DATA_ID_GEN_REVS = b'\x9c\x47'
    DATA_ID_ROTOR_REVS = b'\x9c\x46'
    DATA_ID_L1V = b'\x9c\xa5'
    DATA_ID_L2V = b'\x9c\xa6'
    DATA_ID_L3V = b'\x9c\xa7'
    DATA_ID_L1A = b'\x9c\xa9'
    DATA_ID_L2A = b'\x9c\xaa'
    DATA_ID_L3A = b'\x9c\xab'

    DATA_ID_SYSTEM_PRODUCTION = b'\x80\xe9'
    DATA_ID_G1_PRODUCTION = b'\x80\xea'
    DATA_ID_CONTROLLER_TIME = b'\xc3\x53'

    DATA_ID_GRID_POWER = b'\x9c\xac'
    DATA_ID_GRID_CURRENT = b'\x9c\xa8'
    DATA_ID_GRID_VOLTAGE = b'\x9c\xa4'

    DATA_ID_GRID_VAR = b'\x9c\xad'

    DATA_ID_CURRENT_STATUS_CODE = b'\x00\x0c'
    DATA_ID_EVENT_STACK_STATUS_CODE = b'\x00\x0b'

    DATA_ID_EMPTY = b'\x00\x00'
    DATA_ID_START = b'\x00\x01'
    DATA_ID_STOP = b'\x00\x02'
    DATA_ID_RESET = b'\x00\x03'

    class MnetPacket:
        SOH = b'\x01'
        EOT = b'\x04'

        def __init__(self, destination, source, packet_type, data_len, data, crc=None):
            self.crc_calculator = Calculator(Crc16.XMODEM)
            self.destination = destination
            self.source = source
            self.packet_type = packet_type
            self.data_len = data_len
            self.data = data

            self.real_data = self.data.replace(b'\xff', b'\xff\xff')
            self.packet = self.destination+self.source+self.packet_type + \
                len(self.real_data).to_bytes(1, byteorder='big')+self.real_data
            self.calculated_crc = self.crc_calculator.checksum(
                self.packet)
            if crc is None:
                self.crc = self.calculated_crc
            else:
                self.crc = crc

        def __str__(self):
            return 'sot:01 dst:0x{:02s} src:0x{:02s} type:0x{:04s} len:{:d} data:{:s} crc:{:04x} eot:04'.format(
                self.destination.hex(),
                self.source.hex(),
                self.packet_type.hex(),
                self.data_len,
                self.data.hex(),
                self.crc)

        def __bytes__(self):
            return self.SOH+self.packet+self.crc.to_bytes(2, byteorder='big')+self.EOT

    def __init__(self, device, id=b'\x01'):
        self.device = device
        self.id = id
        self.crc_calculator = Calculator(Crc16.XMODEM)
        self.serial = None
        self.encoded_serial = None

    def create_packet(self, destination, packet_type, data):
        return Mnet.MnetPacket(destination, self.id, packet_type, len(data), data)

    def send_packet(self, destination, packet_type, data):
        packet = self.create_packet(destination, packet_type, data)
        self.device.write(bytes(packet))
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
        packet = Mnet.MnetPacket(destination.to_bytes(1, byteorder='big'), source.to_bytes(1, byteorder='big'),
                                 packet_type.to_bytes(2, byteorder='big'), data_len, data, crc)
        return packet

    def get_serial_number(self, destination):
        res = self.send_packet(destination, self.REQ_SERIAL_NUMBER, b'')
        (serial,) = struct.unpack('!L', res.data)
        return (serial, res.data)

    def encode_serial(self, serial_bytes):
        (p0, p1, p2, p3) = struct.unpack('!BBBB', serial_bytes)
        res = bytearray(5)
        res[0] = ((p2 & p1) - p2) % 256
        res[1] = (p1 + p0 + p3) % 256
        res[2] = (p3 + p0 ^ p1) % 256
        res[3] = ((p3 & p1) + p2) % 256
        res[4] = ((p3 | p2) - p3) % 256
        return res

    def encode(self, data, enc_serial):
        CONST = 0x34
        ba = bytearray(data)
        out = [0]*len(data)

        previous_byte = 0
        for i in range(len(ba)):
            byte = ba[i]
            out[i] = ((enc_serial[i % 5] - previous_byte ^ byte) + CONST) % 256
            previous_byte = byte
        return bytes(out)

    def decode(self, data, enc_serial):
        CONST = 0x34
        ba = bytearray(data)
        out = [0]*len(data)

        tmp = 0

        for i in range(len(ba)):
            tmp = (ba[i] - CONST ^ enc_serial[i % 5] - tmp) % 256
            out[i] = tmp
        return bytes(out)

    def decode_data(self, data_in):
        header = data_in[0:5]
        (type, conversion_type, conversion_value,
         length) = struct.unpack('!BBHB', header)
        #print(type, conversion_type, conversion_value, length)
        # print(data_in)
        match type:
            case 0x0:
                raw_data = None
            case 0x1, 0xa:
                (raw_data,) = struct.unpack_from('!b', data_in, 5)
            case 0x2:
                (raw_data,) = struct.unpack_from('!b', data_in, 5)
            case 0x3:
                (raw_data,) = struct.unpack_from('!h', data_in, 5)
            case 0x4:
                (raw_data,) = struct.unpack_from('!H', data_in, 5)
            case 0x5:
                (raw_data,) = struct.unpack_from('!l', data_in, 5)
            case 0x6:
                (raw_data,) = struct.unpack_from('!L', data_in, 5)
            case 0x7:
                (raw_data,) = struct.unpack_from('!L', data_in, 5)
            case 0x9:
                (raw_data,) = struct.unpack_from(
                    f'!{length}s', data_in, 5)
                raw_data = raw_data.decode('ascii').rstrip('\x00')

        # print(raw_data)
        match conversion_type:
            case 0x0:
                value = raw_data
            case 0x1 | 0x5:
                value = float(raw_data)/pow(10, conversion_value)
            case 0x2:
                if conversion_value != 0:
                    value = float(raw_data)/conversion_value
                else:
                    value = float(raw_data)
            case 0x3:
                if conversion_value != 0:
                    value = float(raw_data)*conversion_value
                else:
                    value = float(raw_data)
            case 0x4:
                value = float(raw_data)*pow(10, conversion_value)
        return (type, value)

    def decode_multiple_data(self, data_in):
        # print(data_in)
        num = data_in[0]  # first byte is number of elements
        pos = 1
        res = []
        for i in range(num):  # iterate through x elements
            next_header = data_in[pos:pos+9]
            # print(next_header)
            (mainid, subid, _, _, _, length) = struct.unpack(
                "!HHBBHB", next_header)
            next_data = data_in[pos+4:pos+9+length]
            d = (mainid, subid, self.decode_data(next_data))
            res.append(d)
            pos += 9+length
        return res

    def create_login_packet_data(self):
        return struct.pack('=20sBBBBBBBBBBBB',
                           self.LOGIN_131_GAIA_WIND,
                           0xff,
                           0xff,
                           self.LOGIN_PACKET_ID >> 0x18,
                           self.LOGIN_PACKET_ID >> 0x10,
                           self.LOGIN_PACKET_ID >> 8,
                           self.LOGIN_PACKET_ID,
                           5,
                           0,
                           0,
                           0,
                           0,
                           0
                           )

    def send_command(self, destination, command_id):
        if self.serial is None:
            (self.serial, serial_bytes) = self.get_serial_number(destination)
            self.encoded_serial = self.encode_serial(serial_bytes)
        response = self.send_packet(
            destination, self.REQ_COMMAND, command_id)
        return response

    def request_data(self, destination, data_id, sub_id=0):
        if self.serial is None:
            (self.serial, serial_bytes) = self.get_serial_number(destination)
            self.encoded_serial = self.encode_serial(serial_bytes)
        response = self.send_packet(
            destination, self.REQ_DATA, data_id+sub_id.to_bytes(2, byteorder='big'))
        # print(response)
        # print(self.encoded_serial)
        data = self.decode(response.data, self.encoded_serial)
        (datatype, value) = self.decode_data(data)
        return value

    def request_multiple_data(self, destination, datasubids, include_ids=False):
        if self.serial is None:
            (self.serial, serial_bytes) = self.get_serial_number(destination)
            self.encoded_serial = self.encode_serial(serial_bytes)
        id_bytes = bytearray(len(datasubids).to_bytes(1, byteorder='big'))
        for (m, s) in datasubids:
            a = m+s.to_bytes(2, byteorder='big')
            id_bytes += a
        response = self.send_packet(
            destination, self.REQ_MULTIPLE_DATA, id_bytes)
        #print('id:', id_bytes)
        data = self.decode(response.data, self.encoded_serial)
        #print('data:', data)
        decoded_data = self.decode_multiple_data(data)
        #print('d:', decoded_data)
        ret_data = []
        for (main_id, sub_id, (datatype, value)) in decoded_data:
            if include_ids:
                ret_data += [(main_id.to_bytes(2, byteorder='big'),
                              sub_id, value)]
            else:
                ret_data += [value]
        return ret_data

    def timestamp_to_datetime(self, seconds):
        EPOCH = datetime.datetime(1980, 1, 1)
        return EPOCH+datetime.timedelta(seconds=seconds)

    def event_log(self, start=0, end=65):
        DATA_ID_EVENT_STACK_STATUS_CODE

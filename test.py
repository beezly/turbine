import mnet

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

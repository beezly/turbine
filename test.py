import mnet
import time
import bitstring
import paho.mqtt.client as mqtt
import json

TOPIC_PREFIX = 'turbine/'

next_command = None

def convert_to_bits(data):
    return bitstring.Bits(data).bin


def bits_string(data):
    return ' '.join([data[i:i+8] for i in range(0, len(data), 8)])

def handle_command_message(client, userdata, message):
    print('handling command')
    global next_command
    (mnet_client, DEST)=userdata
    command_payload=message.payload.decode('utf-8')
    print (f"message recevied: {message.topic}: {command_payload}")

    match command_payload:
        case "start":
            print ("setting next_command to start")
            next_command = mnet.Mnet.DATA_ID_START
        case "stop":
            print ("setting next_command to stop")
            next_command = mnet.Mnet.DATA_ID_STOP
        case "reset":
            print ("setting next_command to reset")
            next_command = mnet.Mnet.DATA_ID_RESET
        case _:
            print (f"Unknown Command {command_payload}")

    return

DEST = b'\x02'

test = mnet.Mnet('/dev/ttyUSB0')
lastbits = ''
counter = 0
mqtt = mqtt.Client(client_id='turbine_mqtt',userdata=(test, DEST))
mqtt.connect('mqtt.lan')
mqtt.loop_start()

(serial, serial_bytes) = test.get_serial_number(DEST)
encoded_serial = test.encode_serial(serial_bytes)
print(f'got serial: {serial}')

command_topic = TOPIC_PREFIX+str(serial)+'/command'
print(command_topic)
mqtt.message_callback_add(command_topic,handle_command_message)
mqtt.subscribe(command_topic)

while True:
    try:
        data = test.encode(test.create_login_packet_data(), encoded_serial)
        login = test.send_packet(DEST, b'\x13\xa1', data)
        # print("login packet:", login)
        # print("result1: ", test.send_packet(DEST, b'\x13\xa1', data))
        # controller_time = test.request_data(
        #    DEST, mnet.Mnet.DATA_ID_CONTROLLER_TIME)
        # print('controller_time:', controller_time)

        # print(next_command)
        if next_command != None:
            print(f"sending command: {next_command}")
            try: 
                r=test.send_command(DEST, next_command)
                print(r)
            finally:
                next_command = None

        gen_revs = test.request_data(DEST, mnet.Mnet.DATA_ID_GEN_REVS)
        rotor_revs = test.request_data(DEST, mnet.Mnet.DATA_ID_ROTOR_REVS)
        wind = test.request_data(DEST, mnet.Mnet.DATA_ID_WIND_SPEED)

        l1v = test.request_data(DEST, mnet.Mnet.DATA_ID_L1V)
        l2v = test.request_data(DEST, mnet.Mnet.DATA_ID_L2V)
        l3v = test.request_data(DEST, mnet.Mnet.DATA_ID_L3V)
        # l1a = test.request_data(DEST, mnet.Mnet.DATA_ID_L1A)
        # l2a = test.request_data(DEST, mnet.Mnet.DATA_ID_L2A)
        # l3a = test.request_data(DEST, mnet.Mnet.DATA_ID_L3A)
        # l1p = l1v*l1a
        # l2p = l2v*l2a
        # l3p = l3v*l3a
        # total_power = l1p+l2p+l3p

        # print(
        #    f'wind: {wind:.0f}m/s',
        #    f'rotor: {rotor_revs:.0f}rpm',
        # f'ph1: ( {l1v:.0f}v {l1a:.2f}a {l1p:.0f}W )',
        # f'ph2: ( {l2v:.0f}v {l2a:.2f}a {l2p:.0f}W )',
        ##    f'gen: {gen_revs:.0f}rpm'
        #    # f'ph3: ( {l3v:.0f}v {l3a:.2f}a {l3p:.0f}W )',
        # f'total_power: {total_power:.0f}W'
        # )

        # test_1 = test.request_data(DEST, mnet.Mnet.DATA_ID_TEST_1)
        # test_2 = test.request_data(DEST, mnet.Mnet.DATA_ID_TEST_2)
        # print(test_1, test_2, test_3)
        # test_3 = test.request_data(DEST, mnet.Mnet.DATA_ID_TEST_3)
        # print(test.request_data(DEST, b'\x9c\xac'))
        # print(test.request_data(DEST, b'\x9c\xa8'))
        power = test.request_data(DEST, mnet.Mnet.DATA_ID_GRID_POWER)
        #print('power: ', power)
        # for i in [1, 2, 3, 11, 12, 13, 14, 15, 16, 21, 22, 23, 24, 26, 27, 31, 32, 33, 34, 35, 36, 37, 41, 42, 43, 44, 45, 51, 52, 53, 54, 55, 56, 57, 61, 62, 63, 64]:
        #    b = i*100
        #    for y in range(31):
        # for i in [1123, 1124, 1224, 4101, 4102, 10001, 101, 102, 201, 202]:
        #    print('test_prod_g1: ', i, test.request_data(DEST,
        #                                                 mnet.Mnet.DATA_ID_G1_PRODUCTION, i))
        #    print('test_prod_sys: ', i, test.request_data(DEST,
        #                                                  mnet.Mnet.DATA_ID_SYSTEM_PRODUCTION, i))
        # print('multi: ', test.request_multiple_data(DEST, [
        #      (mnet.Mnet.DATA_ID_GRID_VOLTAGE, 101), (mnet.Mnet.DATA_ID_GRID_VOLTAGE, 102)]))
        #print('var: ', test.request_data(DEST, mnet.Mnet.DATA_ID_GRID_VAR, 101))
        #print('gv: ', test.request_data(DEST, mnet.Mnet.DATA_ID_GRID_VOLTAGE, 101))
        #print('system_production', test.request_data(
        #    DEST, mnet.Mnet.DATA_ID_SYSTEM_PRODUCTION, 101))
        # print('g1_production', test.request_data(
        #    DEST, mnet.Mnet.DATA_ID_G1_PRODUCTION, 100))
        # print('current_status_code', test.request_data(
        #    DEST, mnet.Mnet.DATA_ID_CURRENT_STATUS_CODE, 1))
        #print(test.request_data(DEST, mnet.Mnet.DATA_ID_CURRENT_STATUS_CODE, 101))
        # for i in range(10):
        #    data_list = [
        #        (mnet.Mnet.DATA_ID_EVENT_STACK_STATUS_CODE, i*100),
        #        (mnet.Mnet.DATA_ID_EVENT_STACK_STATUS_CODE, i*100+1),
        #        (mnet.Mnet.DATA_ID_EVENT_STACK_STATUS_CODE, i*100+2)]
        #    status_line = test.request_multiple_data(DEST, data_list)
        #    [status_code, ts, message] = status_line
        #    print('status: ',
        #          test.timestamp_to_datetime(ts),
        #          message,
        #          status_code
        #          )
        latest_status_message = test.request_data(
            DEST, mnet.Mnet.DATA_ID_EVENT_STACK_STATUS_CODE, 2).strip()
        mqtt_data = {
            'wind_speed_mps': wind,
            'rotor_rpm': rotor_revs,
            'generator_rpm': gen_revs,
            'power_W': power,
            'status_message': latest_status_message,
            'l1v': l1v,
            'l2v': l2v,
            'l3v': l3v
        }
        print(mqtt_data)
        pub_data = mqtt.publish(TOPIC_PREFIX+str(serial), json.dumps(mqtt_data))
        pub_data.wait_for_publish()
        # print(pub_data.is_published)

        time.sleep(1)
    except Exception as ex:
        print("EXCEPTION")
        print(type(ex))
        print(ex.args)
        print(ex)
        time.sleep(10)

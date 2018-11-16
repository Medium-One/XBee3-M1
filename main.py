import ujson as json
import time, machine
import os
import socket, network, xbee
import ustruct as struct
from machine import UART, unique_id, ADC, Pin, PWM
from m1mqtt import MQTTClient

# specify m1 filename
creds_fn = 'devicecreds.json'
regis_fn = 'registration.json'
verbose_console = False


def create_event(data):
    global api_user
    global api_password
    global registration
    print("Sending Event @ " + str(time.localtime(time.time())))
    all_data = {"event_data": data}
    data = json.dumps(all_data)
    print(data)
    pub_topic = '0/' + registration["project_id"] + '/' + api_user + '/' + imei_number
    mqtt.pub(pub_topic, data)


def callback(topic, msg):
    global api_user
    global api_password
    global registration
    global reset_flag
    global DOUT
    global last_time
    reg_sub_topic = '5/' + registration["project_id"] + '/' + imei_number
    if topic == bytearray(reg_sub_topic):
        json_obj = json.loads(str(msg, 'utf-8'))
        api_user = json_obj['mqtt_id']
        api_password = json_obj['password']

    sub_topic = '1/' + registration["project_id"] + '/' + api_user + '/' + imei_number + '/event'
    if topic == bytearray(sub_topic):
        m = str(msg, 'utf-8')
        if m == 'sensor_refresh' or m == 'relay_1_on' or m == 'relay_1_off':
            if m == 'relay_1_on':
                DOUT.value(True)
            if m == 'relay_1_off':
                DOUT.value(False)

            dout_val = DOUT.value()
            data_to_upload = {"ADC0": adc_value_0, "ADC1": adc_value_1, "ADC2": adc_value_2, "DIN": din_val,
                              "DOUT": dout_val}
            if sensor:
                data_to_upload["x_accel"] = {"max": round(xmax, 4), "min": round(xmin, 4)}
                data_to_upload["y_accel"] = {"max": round(ymax, 4), "min": round(ymin, 4)}
                data_to_upload["z_accel"] = {"max": round(zmax, 4), "min": round(zmin, 4)}
                data_to_upload["TEMP_degC"] = TEMP_degC

            print('Requested sensor data')
            create_event(data_to_upload)
            last_time = time.time()
            reset_flag = True


def register_device():
    global api_user, api_password, imei_number
    global registration
    print('Logging in as Registration User')
    api_user, api_password = '', ''
    reg_mqtt = MQTTClient(imei_number,
                          registration["host"],
                          port=registration["port"],
                          user=registration["project_id"] + '/' + registration["reg_mqtt_id"],
                          password=registration["api_key"] + '/' + registration["reg_password"])
    reg_mqtt.disconnect()
    reg_mqtt.connect()
    reg_mqtt.cb = callback
    reg_sub_topic = '5/' + registration["project_id"] + '/' + imei_number
    reg_pub_topic = '4/' + registration["project_id"] + '/' + imei_number
    reg_mqtt.sub(reg_sub_topic)
    reg_mqtt.pub(reg_pub_topic, '{}')

    while not api_user or not api_password:
        time.sleep(1)
        reg_mqtt.check_msg()
    reg_mqtt.disconnect()
    # save credentials #
    credsfile = open(creds_fn, 'w')
    credsfile.write(json.dumps({"api_user": api_user, "api_password": api_password}))
    credsfile.close()


def process_axis(high, low, min, max, count, reset):
    sumall = (high[0] << 8) + low[0]
    if sumall > 32767:
        sumall = sumall - 65536
    value = sumall / 16384
    if (reset == True):
        count = 1
        min = value
        max = value
    else:
        count = count + 1
        if value < min:
            min = value
        if value > max:
            max = value
    return min, max, count


api_user, api_password = '', ''
xmin, xmax, count, ymin, ymax, zmin, zmax = 0, 0, 0, 0, 0, 0, 0
reconnect = True
reset_flag = True
sensor = False
sensor_refresh = False
last_time = time.time()

pwm0 = PWM(Pin('P0'))
pwm0.duty(767)
adc0 = ADC("D0")
adc1 = ADC("D1")
adc2 = ADC("D2")

# The default vale of input pin is 0 here. Can change to 1 like DIN = Pin(Pin.board.D3, mode=Pin.IN, pull=Pin.PULL_UP).
DIN = Pin(Pin.board.D3, mode=Pin.IN)
# The default vale of output pin is 0 here. Can change to 1 by changing XCTU setting to Digital_Output_High.
DOUT = Pin(Pin.board.D5, mode=Pin.OUT)

### Load registration file ###
registration_loaded = False
if regis_fn not in os.listdir():
    print("Error, no registration file found in the filesystem: " + regis_fn)
else:
    regisfile = open(regis_fn, 'r')
    regisfile_content = regisfile.read()
    regisfile.close()
    registration = json.loads(regisfile_content)
    # check if contents in file are there
    if ("project_id" not in registration.keys()) or ("api_key" not in registration.keys()) or (
            "reg_mqtt_id" not in registration.keys()) or ("reg_password" not in registration.keys()) or (
            "host" not in registration.keys()) or ("port" not in registration.keys()):
        print("Error, Registration file missing necessary keys")
    else:
        print("Successfully loaded registration file: " + regis_fn)
        if verbose_console:
            print(registration)
        registration_loaded = True

try:
    print('Scanning sensors...')
    i2c = machine.I2C(1)
    i2c.scan()
    WHO_AM_I = i2c.readfrom_mem(104, 0, 1)
    TEMP_DIS = i2c.readfrom_mem(12, 3, 1)
    i2c.writeto_mem(104, 6, b'\x01')
    sensor = True
except:
    print('Sensor is not available')

while registration_loaded:
    try:
        if reconnect:
            x = xbee.XBee()
            x.atcmd('NR')  # will experiment with this later
            c = network.Cellular()
            c.active()
            networkcount = 0
            while not c.isconnected():
                time.sleep(10)
                networkcount = networkcount + 1
                print('Waiting for cellular network.. ' + str(networkcount))

            print('Connected to network')
            imei_number = c.config('imei')
            print('IMEI: ' + str(imei_number))

            # start load creds
            if creds_fn not in os.listdir():
                print("No device credentials file found: " + creds_fn)
                register_device()
            else:
                credsfile = open(creds_fn, 'r')
                credsfile_content = credsfile.read()
                credsfile.close()
                try:
                    creds = json.loads(credsfile_content)
                    if verbose_console:
                        print(creds)
                    if "api_user" in creds.keys():
                        api_user = creds["api_user"]
                        if "api_password" in creds.keys():
                            api_password = creds["api_password"]
                            connected = False
                            while not connected:
                                mqtt = MQTTClient(imei_number,
                                                  registration["host"],
                                                  port=registration["port"],
                                                  user=registration["project_id"] + '/' + api_user,
                                                  password=registration["api_key"] + '/' + api_password)
                                mqtt.disconnect()
                                try:
                                    print('Mqtt Connect Attempt')
                                    mqtt.connect()
                                    connected = True
                                except:
                                    print('Mqtt Connect FAILED')
                                    register_device()
                                    continue

                            print('MQTT Connected')
                            mqtt.cb = callback
                            sub_topic = '1/' + registration[
                                "project_id"] + '/' + api_user + '/' + imei_number + '/event'
                            mqtt.sub(sub_topic)
                            create_event({"event_data": {"connected": True}})
                            reconnect = False
                        else:
                            print("Missing password in " + creds_fn)
                            register_device()
                    else:
                        print("Missing user in " + creds_fn)
                        register_device()
                except:
                    print("Error loading file: " + creds_fn)
                    register_device()

    except:
        reset_in_seconds = 10
        print("Error Should not get here... resetting after " + str(reset_in_seconds) + " secs")
        time.sleep(reset_in_seconds)
        machine.reset()
        continue

    try:
        adc_value_0 = adc0.read()
        adc_value_1 = adc1.read()
        adc_value_2 = adc2.read()
        din_val = DIN.value()
        dout_val = DOUT.value()
        time.sleep(0.1)
        data_to_upload = {"ADC0": adc_value_0, "ADC1": adc_value_1, "ADC2": adc_value_2,
                          "DIN": din_val, "DOUT": dout_val}
        if sensor:
            ACCEL_XOUT_H = i2c.readfrom_mem(104, 45, 1)
            ACCEL_XOUT_L = i2c.readfrom_mem(104, 46, 1)
            xmin, xmax, temp = process_axis(ACCEL_XOUT_H, ACCEL_XOUT_L, xmin, xmax, count, reset_flag)
            ACCEL_YOUT_H = i2c.readfrom_mem(104, 47, 1)
            ACCEL_YOUT_L = i2c.readfrom_mem(104, 48, 1)
            ymin, ymax, temp = process_axis(ACCEL_YOUT_H, ACCEL_YOUT_L, ymin, ymax, count, reset_flag)
            ACCEL_ZOUT_H = i2c.readfrom_mem(104, 49, 1)
            ACCEL_ZOUT_L = i2c.readfrom_mem(104, 50, 1)
            zmin, zmax, count = process_axis(ACCEL_ZOUT_H, ACCEL_ZOUT_L, zmin, zmax, count, reset_flag)
            reset_flag = False
            TEMP_OUT_H = i2c.readfrom_mem(104, 57, 1)  # read temp high value
            TEMP_OUT_L = i2c.readfrom_mem(104, 58, 1)  # read temp low value
            TEMP_degC = ((((TEMP_OUT_H[0] << 8) + TEMP_OUT_L[0]) - 21) / 333.87) + 21
            data_to_upload["x_accel"] = {"max": round(xmax, 4), "min": round(xmin, 4)}
            data_to_upload["y_accel"] = {"max": round(ymax, 4), "min": round(ymin, 4)}
            data_to_upload["z_accel"] = {"max": round(zmax, 4), "min": round(zmin, 4)}
            data_to_upload["TEMP_degC"] = TEMP_degC
            time.sleep(0.1)

        if ((time.time() - last_time) > 900):
            create_event(data_to_upload)
            last_time = time.time()
            reset_flag = True
        else:
            mqtt.check_msg()

    except:
        reset_in_seconds = 10
        print("Error during sampling sensor data... resetting after " + str(reset_in_seconds) + " secs")
        time.sleep(reset_in_seconds)
        machine.reset()
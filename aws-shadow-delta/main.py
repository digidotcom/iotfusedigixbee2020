"""
Copyright (c) 2020, Digi International, Inc.
Sample code released under MIT License.

Instructions:

 - Ensure that the umqtt/simple.py module is in the /flash/lib directory
   on the XBee Filesystem.
 - Name your thing after your IMEI exactly for this example. If your IMEI
   is "0123456789012345" then that should be the name of your thing.
 - The policy attached to the SSL certificates must allow for
   publishing, subscribing, connecting, and receiving.
 - The host and region need to be filled in to create a valid
   AWS endpoint to connect to.
 - "ssl_params" shows which ssl parameters are required, and gives
   examples for referencing the files.
 - Be sure to replace the file paths to match the certificates you're using
 - Connection errors are most commonly associated with bad
   TLS certificates or a policy permissions issue.

"""

from umqtt.simple import MQTTClient
from time import time, sleep
import ujson
from network import Cellular
from struct import pack, unpack
from digi import ble
from machine import Pin
from sys import print_exception

# The service and characteristic UUIDs
io_service_uuid = 0x1815
io_characteristic_uuid = 0x2A56

env_service_uuid = 0x181a
lumens_characteristic_uuid = 'c8546913-bfd9-45eb-8dde-9f8754f4a32e'

# AWS endpoint parameters
host = b'FILL_ME_IN'  # ex: b'a1p3gcs127hy79'
region = b'FILL_ME_IN'  # ex: b'us-east-2'
if host == "FILL_ME_IN":
    print("Connection parameters not set. You must fill them in.")
    exit(-1)

aws_endpoint = b'%s.iot.%s.amazonaws.com' % (host, region)
ssl_params = {'keyfile': "cert/aws.key",
              'certfile': "cert/aws.crt",
              'ca_certs': "cert/aws.ca"}  # ssl certs

ble.active(True)
cell_conn = Cellular()
print("Waiting for network...")
while not cell_conn.isconnected():
    sleep(1)
print("connected")
imei = cell_conn.config('imei')
print("imei: ", imei)

UPDATE_NONE, UPDATE_CLOUD = 0, 1
bulbs = None


class BLESmartSwitch:
    @staticmethod
    def _find_thunderboard():
        scanner = ble.gap_scan(200, interval_us=2500, window_us=2500)
        for adv in scanner:
            if b"Thunder Sense" in adv['payload']:
                return adv['address']
        return None

    def __init__(self):
        self.address = None
        self.conn = None
        self.lumens = 100
        self.leds_characteristic = None
        self.lumens_characteristic = None
        self.light_state = [0, 0]

    def get_characteristics_from_uuids(self, service_uuid, characteristic_uuid):
        services = list(self.conn.gattc_services(service_uuid))
        if len(services):
            # Assume that there is only one service per UUID, take the first one
            my_service = services[0]
            characteristics = list(self.conn.gattc_characteristics(my_service, characteristic_uuid))
            return characteristics
        # Couldn't find specified characteristic, return an empy list
        return []

    def is_connected(self):
        return self.conn is not None

    def connect(self):
        if self.address is None:
            self.address = self._find_thunderboard()
            if self.address:
                print("Found thunderboard : {}".format(self.address))
        if self.conn is None:
            if self.address is not None:
                try:
                    print("Attempting connection to: {}".format(self.address))
                    self.conn = ble.gap_connect(ble.ADDR_TYPE_PUBLIC, self.address)
                    self.leds_characteristic = self.get_characteristics_from_uuids(io_service_uuid,
                                                                                   io_characteristic_uuid)[1]
                    self.lumens_characteristic = self.get_characteristics_from_uuids(env_service_uuid,
                                                                                     lumens_characteristic_uuid)[0]
                    print("connected")
                except OSError:
                    self.conn = None

    def get_lumens(self):
        return self.lumens

    def get_light(self):
        return self.light_state[0]

    def get_night_light(self):
        return self.light_state[1]

    def set_light(self, value):
        self.light_state[0] = value

    def update_nightlight(self):
        prev_light_state = self.light_state[1]
        if self.lumens < 20:
            self.light_state[1] = True
        if self.lumens > 40:
            self.light_state[1] = False
        return prev_light_state != self.light_state[1]

    def update(self):
        if self.conn is not None:
            try:
                led_value = pack("b", self.light_state[0] | (self.light_state[1] << 2))
                self.conn.gattc_write_characteristic(self.leds_characteristic, led_value)
                self.lumens = self.conn.gattc_read_characteristic(self.lumens_characteristic)
                self.lumens = int(unpack('<I', self.lumens)[0]/100)
            except OSError:
                self.conn = None


def check_cellular():
    return cell_conn.isconnected()


def delta_callback(topic, msg):
    global bulbs, update_state
    print("Topic: \"{topic}\", Message: \"{message}\"".format(topic=topic, message=msg))
    delta = ujson.loads(msg.decode('utf-8'))
    print(delta)
    try:
        state = delta['state']
        if state['light_state'] in ['on', 'off']:
            bulbs.set_light(state['light_state'] == 'on')
            update_state = UPDATE_CLOUD
            print("updated light to %s" % (bulbs.get_light()))
    except KeyError as e:
        print_exception(e)


class AWSShadow:
    def __init__(self, client_id=imei, hostname=aws_endpoint, sslp=ssl_params):
        self.client = MQTTClient(client_id, hostname, ssl=True, ssl_params=sslp)
        self.client.set_callback(delta_callback)
        self.shadowpath = "$aws/things/{}/shadow/".format(imei)
        print(self.shadowpath)
        self.connected = False

    def is_connected(self):
        return self.connected

    def connect(self):
        try:
            print("trying MQTT")
            self.client.connect()
            self.connected = True
            self.client.subscribe(self.shadowpath + "update/delta")
            print("subscribed to {}".format(self.shadowpath + "update/delta"))
            print("connected to MQTT")
        except OSError as e:
            print_exception(e)
            self.connected = False

    @staticmethod
    def _get_on_off(value):
        if value:
            return 'on'
        else:
            return 'off'

    def update(self, light, nightlight, lumens):
        try:
            print("updating shadow")
            telemetry = {"lumens": lumens}
            state = {"state": {"reported": {"light_state": self._get_on_off(light),
                                            "night_light_state": self._get_on_off(nightlight)}, "desired": None}}
            telemetry_path = "smartswitch/{}/lumens/".format(imei)
            shadow_path = "$aws/things/{}/shadow/".format(imei)
            print(shadow_path)
            self.client.publish(telemetry_path, ujson.dumps(telemetry))
            print("updated {}".format(telemetry_path))
            self.client.publish(shadow_path + "update", ujson.dumps(state))
            print("updated {}".format(shadow_path))
            return True
        except OSError:
            self.connected = False

    def check(self):
        self.client.check_msg()


def update_cloud(aws_client):
    global bulbs
    print("update cloud")
    if check_cellular():
        if not aws_client.is_connected():
            aws_client.connect()
        if aws_client.is_connected():
            aws_client.update(bulbs.get_light(), bulbs.get_night_light(), bulbs.get_lumens())
            return True
    return False


class Button:
    global bulbs

    def __init__(self):
        self.button = Pin.board.D1
        self.button.mode(Pin.IN)
        self.button.pull(Pin.PULL_UP)
        self.state = [1, 1]

    def check_button(self):
        # set the previous state
        self.state[0] = self.state[1]
        # read the current button state
        self.state[1] = self.button.value()
        # detected button release
        if self.state == [0, 1]:
            print('button press detected:', self.state, bulbs.get_light(), bulbs.get_night_light())
            print(self.state, bulbs.get_light(), bulbs.get_night_light())
            bulbs.set_light(not bulbs.get_light())
            return True
        return False


def __main():
    global bulbs, update_state
    button = Button()
    aws_client = AWSShadow()
    aws_client.connect()
    lasttime = time()
    print("Entering loop")
    while True:
        try:
            if not bulbs.is_connected():
                bulbs.connect()
            if button.check_button():
                update_state = UPDATE_CLOUD
            if bulbs.update_nightlight():
                update_state = UPDATE_CLOUD

            # Wait until at least 1 second has elapsed before updating
            if time() - lasttime > 1:
                lasttime = time()
                # Update the light and cloud if an update is needed
                if bulbs.is_connected():
                    # Refresh the state of the sensors readings
                    bulbs.update()

                # Refresh the state of the sensors readings
                if update_state == UPDATE_CLOUD:
                    if update_cloud(aws_client):
                        update_state = UPDATE_NONE
            if check_cellular():
                if aws_client.is_connected():
                    # check for shadow updates via callback
                    aws_client.check()
                else:
                    aws_client.connect()

        except OSError as e:
            # provide debug info, but keep going
            print_exception(e)


bulbs = BLESmartSwitch()
update_state = UPDATE_NONE
__main()

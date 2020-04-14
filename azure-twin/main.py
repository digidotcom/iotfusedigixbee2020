"""
Copyright (c) 2020, Digi International, Inc.
Sample code released under MIT License.

Instructions:

 - Ensure that the umqtt/simple.py and urllib/parse.py modules are in
   the /flash/lib directory on the XBee Filesystem
 - Create an account on the Microsoft Azure plaform, note that
   if you have a corporate account you will need to get permission from your
   administrator or may create your own account.
 - Create your IoT Hub and IoT device on the Microsoft Azure platform
 - Get your IoT device "Primary Connection String" and "Device ID" from
   the link to your IoT device (under IoT devices once you've created it).
   and fill in the code below (search for "Azure connection parameters")
 - Push the reset or button left of the USB connector on the Silicon Labs
   Thundersense 2 to send advertisements for 30 seconds so the program
   can scan for and connect to the sensor services.
 - To see telemetry messages showing up in the Azure Console you will
   need to issue two commands. The first one you only need to do once
   to enable the azure-iot extension (stays added until you explicitly
   remove it):

     az extension add --name azure-iot
     az iot hub monitor-events --output table --hub-name {YourIoTHubName}
 - Use the Send Message facility under IoT Devices to send your device a
   command to turn the light off or on as follows:
   {"light_state":"on"}
   OR
   {"light_state":"off"}
 - Use the Device Twin to simulate the actions of a back-end application
   to set the "desired" values for the device. For this program,
   you can add the name "light_state" to value "on", "off" or null.
 - Similarly modify the Device Twin also in your device instance under
   IoT Devices on the portal and then save it to see the state propagate.

"""

from hashlib import sha256
from umqtt.simple import MQTTClient, MQTTException
import ujson
from time import time, sleep
from ubinascii import a2b_base64 as b64decode, b2a_base64 as b64encode
from network import Cellular
from struct import pack, unpack
from digi import ble
from machine import Pin
from urllib.parse import quote_plus, urlencode
from sys import print_exception

# The service and characteristic UUIDs
io_service_uuid = 0x1815
io_characteristic_uuid = 0x2A56

env_service_uuid = 0x181a
lumens_characteristic_uuid = 'c8546913-bfd9-45eb-8dde-9f8754f4a32e'

# Azure connection parameters
IoTHubConnectionString = "FILL_ME_IN"
IoTDeviceId = "FILL_ME_IN"
if IoTHubConnectionString == "FILL_ME_IN":
    print("Connection parameters not set. You must fill them in.")
    exit(-1)

ble.active(True)
cell_conn = Cellular()

UPDATE_NONE, UPDATE_CLOUD = 0, 1
update_state = UPDATE_NONE
version = 0
bulbs = None


def _default_call_back(topic, msg):
    global version, bulbs, update_state
    print("Topic: \"{topic}\", Message: \"{message}\"".format(topic=topic, message=msg))
    if len(msg):
        state = ujson.loads(msg.decode('utf-8'))

        try:
            if topic.startswith("$iothub/twin/res/200"):
                # We will match the desired state, otherwise this is a PATCH and the whole body is the desired state
                state = state['desired']
            elif not topic.startswith("$iothub/twin/PATCH/properties/desired"):
                print("Unhandled topic: ", topic)
                return

            print("state: ", state)
            if state['$version'] < version:
                print("Already handled version {}, at version {}".format(state['$version'], version))
                return
            version = state['$version']

            # same code to handle event or device twin updates
            if state['light_state'] in ['on', 'off']:
                bulbs.set_light(state['light_state'] == 'on')
                update_state = UPDATE_CLOUD
                print("updated light to {}".format(bulbs.get_light()))
        except KeyError as e:
            print_exception(e)


class AzureMQTT:
    def __init__(self, connection_string: str, policy_name=None, expiry: int = 36000):
        print("AzureMQTT init")
        self.params = dict(field.split('=', 1) for field in connection_string.split(';'))
        required_keys = ["HostName", "DeviceId", "SharedAccessKey"]
        if any(k not in self.params for k in required_keys):
            raise ValueError("connection_string is invalid, should be in the following format:",
                             "HostName=foo.bar;DeviceId=Fo0B4r;SharedAccessKey=Base64FooBar")
        self.sas_token = generate_sas_token(self.params["HostName"], self.params["SharedAccessKey"],
                                            policy_name=policy_name, expiry=expiry)
        self.username = "{host_name}/{device_id}/?api-version=2018-06-30".format(host_name=self.params["HostName"],
                                                                                 device_id=self.params["DeviceId"])
        self.password = self.sas_token

        self.mqtt_client = MQTTClient(client_id=self.params["DeviceId"], server=self.params["HostName"],
                                      user=self.username, password=self.password, ssl=True)
        self._subscription_list = [
            "devices/{device_id}/messages/devicebound/#".format(device_id=self.params["DeviceId"]),
            "$iothub/twin/res/#",
            "$iothub/twin/PATCH/properties/desired/#"]
        # counter for matching requests
        self._requestid = 1

    def _default_subscribe(self):
        for s in self._subscription_list:
            print("subscribing to: ", s)
            self.mqtt_client.subscribe(s)

    def setup(self, callback=_default_call_back, subscribe_string: str = "default"):
        """
        An easy way to connect, set the callback, and subscribe to messages.
        :return:
        """
        print("mqtt setup connect")
        self._connect()
        print("mqtt set cb")
        self.mqtt_client.set_callback(callback)
        self._default_subscribe()
        if subscribe_string != "default":
            self.mqtt_client.subscribe(subscribe_string)

    def _connect(self):
        """
        A relay to self.mqtt_client.connect(), but with errors that return usable info that doesn't require the spec
        sheet to figure out what's going on.
        :return:
        """
        try:
            print("mqtt _connect")
            self.mqtt_client.connect()
        except MQTTException as e:
            print_exception(e)
            error_num = int(e.args[0])
            if error_num == 1:
                raise MQTTException("1: Server does not support level of MQTT protocol requested by the client.")
            elif error_num == 2:
                raise MQTTException("2: The Client identifier is correct UTF-8 but not allowed by the Server.")
            elif error_num == 3:
                raise MQTTException("3: The Network Connection has been made but the MQTT service is unavailable.")
            elif error_num == 4:
                raise MQTTException("4: The data in the user name or password is malformed.")
            elif error_num == 5:
                raise MQTTException("5: The client is not authorized to connect.")
            elif error_num >= 6:
                raise MQTTException(str(error_num) + ":",
                                    "The server reported an error not specified in the MQTT spec as of v3.1.1")

    def send(self, prop: dict, payload: str):
        properties = "%s=%s" % (prop['name'], prop['value'])
        topic_string = "devices/{device_id}/messages/events/{p}".format(device_id=self.params["DeviceId"], p=properties)
        print(topic_string)
        self.mqtt_client.publish(topic=topic_string, msg=payload)

    def request_twin(self):
        print("request twin")
        topic = b"$iothub/twin/GET/?$rid={{{}}}".format(self._requestid)
        self.mqtt_client.publish(topic, b"")

    def update_twin(self, payload):
        topic = b"$iothub/twin/PATCH/properties/reported/?$rid={{{}}}".format(self._requestid)
        self.mqtt_client.publish(topic, payload)

    def wait_msg(self):
        print("wait msg")
        self.mqtt_client.wait_msg()

    def check_msg(self):
        self.mqtt_client.check_msg()

    def print(self):
        print("Host Name:        ", self.params["HostName"])
        print("Device ID:        ", self.params["DeviceId"])
        print("Shared Access Key:", self.params["SharedAccessKey"])
        print("SAS Token:        ", self.sas_token)
        print("Username:         ", self.username)
        print("Password:         ", self.password)


def generate_sas_token(uri: str, key: str, policy_name=None, expiry: int = 36000) -> str:
    """
    Create an Azure SAS token.
    :param uri: URI/URL/Host Name to connect to with the token.
    :param key: The key.
    :param policy_name: Not sure what it is right now, defaults to None.
    :param expiry: How long until the token expires. defaults to one hour.
    :return: An SAS token to be used with Azure.
    """
    ttl = time() + expiry + 946684800
    sign_key = "{uri}\n{ttl}".format(uri=quote_plus(uri), ttl=int(ttl))
    signature = b64encode(hmac_digest(b64decode(key), sign_key.encode())).rstrip(b'\n')

    rawtoken = {
        'sr': uri,
        'sig': signature,
        'se': str(int(ttl))
    }

    if policy_name is not None:
        rawtoken['skn'] = policy_name

    return 'SharedAccessSignature ' + urlencode(rawtoken)


def hmac_digest(key: bytes, message: bytes) -> bytes:
    """
    A MicroPython implementation of HMAC.digest(), because HMAC isn't accessible yet.
    :param key: key for the keyed hash object.
    :param message: input for the digest.
    :return: digest of the message passed in.
    """
    trans_5C = bytes((x ^ 0x5C) for x in range(256))
    trans_36 = bytes((x ^ 0x36) for x in range(256))
    inner = sha256()
    outer = sha256()
    blocksize = 64
    if len(key) > blocksize:
        key = sha256(key).digest()
    key = key + b'\x00' * (blocksize - len(key))
    inner.update(bytes_translate(key, trans_36))
    outer.update(bytes_translate(key, trans_5C))
    inner.update(message)
    outer.update(inner.digest())
    return outer.digest()


def bytes_translate(input_bytes: bytes, input_table: bytes):
    """
    A MicroPython implementation of bytes.translate, because that doesn't actually exist at minimum on the XBee.
    Essentially bytes.translate without using bytes.translate.
    :param input_bytes: Bytes to be run through the table.
    :param input_table: 256 byte table.
    :return: Input_Bytes, but run through the table.
    """
    if len(input_table) != 256:
        raise ValueError("Input table must be 256 bytes long.")
    output_bytes = []
    for byte in input_bytes:
        output_bytes.append(input_table[int(byte)])
    return bytes(output_bytes)


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


class AzureCloud:
    def __init__(self, connectionstring=IoTHubConnectionString, deviceid=IoTDeviceId):
        self.client = AzureMQTT(connectionstring)
        self.connected = False
        self.iotdeviceid = deviceid

    def is_connected(self):
        return self.connected

    def connect(self):
        try:
            print("calling setup")
            self.client.setup()
            print("called setup")
            self.connected = True
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
            print("updating IoT Device")
            state = {"light_state": self._get_on_off(light),
                     "night_light_state": self._get_on_off(nightlight)}
            # property for route filtering
            prop = {"name": "level", "value": "storage"}

            # update the device twin
            self.client.update_twin(ujson.dumps(state))
            state["lumens"] = lumens
            # update normal telemetry
            self.client.send(prop, ujson.dumps(state))
            print("updated {}".format(ujson.dumps(state)))
            return True
        except OSError:
            self.connected = False

    def request_twin(self):
        try:
            if self.connected:
                self.client.request_twin()
        except OSError:
            self.connected = False

    def check_message(self):
        try:
            if self.connected:
                self.client.check_msg()
        except OSError:
            self.connected = False


def update_cloud(client):
    print("update cloud")
    if check_cellular():
        if not client.is_connected():
            client.connect()
            client.request_twin()
        if client.is_connected():
            client.update(bulbs.get_light(), bulbs.get_night_light(), bulbs.get_lumens())
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
            print(self.state, bulbs.get_light(), bulbs.get_night_light())
            bulbs.set_light(not bulbs.get_light())
            return True
        return False


def __main():
    global bulbs, update_state
    button = Button()
    azure_client = AzureCloud()
    print("Waiting for network..")
    while not check_cellular():
        sleep(1)
    azure_client.connect()
    azure_client.request_twin()
    print("Entering loop")
    lasttime = time()
    while True:
        try:
            if not bulbs.is_connected():
                bulbs.connect()
            # Has any state changed requiring an update
            if button.check_button():
                update_state = UPDATE_CLOUD
            if bulbs.update_nightlight():
                update_state = UPDATE_CLOUD
            # Invoke callback
            azure_client.check_message()

            # Wait until at least 1 second has elapsed before updating
            if time() - lasttime > 1:
                lasttime = time()
                if bulbs.is_connected():
                    # Refresh the state of the sensors readings
                    bulbs.update()

                # Light state has changed or cloud updated needed
                if update_state == UPDATE_CLOUD:
                    # attempt to send an update
                    if update_cloud(azure_client):
                        # update successful, no more until change detected
                        update_state = UPDATE_NONE

        except OSError as e:
            # provide debug info, but keep going
            print_exception(e)


bulbs = BLESmartSwitch()
update_state = UPDATE_NONE
__main()

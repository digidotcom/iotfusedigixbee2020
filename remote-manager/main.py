"""
Copyright (c) 2020, Digi International, Inc.
Sample code released under MIT License.

Instructions:

 - Ensure that the umqtt/simple.py module is in the /flash/lib directory
   on the XBee Filesystem
 - Push the reset or button left of the USB connector on the Silicon Labs
   Thundersense 2 to send advertisements for 30 seconds.
 - Make sure your XBee has been added to your Digi Remote Manager
   account.

"""

from time import time
from network import Cellular
from digi import cloud
from struct import pack, unpack
from digi import ble
from machine import Pin
import xbee
from sys import print_exception

# The service and characteristic UUIDs
io_service_uuid = 0x1815
io_characteristic_uuid = 0x2A56

env_service_uuid = 0x181a
lumens_characteristic_uuid = 'c8546913-bfd9-45eb-8dde-9f8754f4a32e'

ble.active(True)
cell_conn = Cellular()


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


class DigiCloud:
    def __init__(self):
        # connect to Digi Remote Manager over TCP
        xbee.atcmd("DO", 1)
        xbee.atcmd("MO", 7)
        self.data = None
        self.body = b""
        self.connected = True

    def is_connected(self):
        return self.connected

    def connect(self):
        try:
            self.connected = True
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
        print("update")
        print(self.data)
        if self.data is None:
            try:
                print("Sending data points")
                self.data = cloud.DataPoints()
                print("posting states: ", self._get_on_off(light), self._get_on_off(nightlight), lumens)
                self.data.add("light_state", self._get_on_off(light))
                self.data.add("night_light_state", self._get_on_off(nightlight))
                self.data.add("lumens", lumens)
                self.data.send()
                if self.data.status() == cloud.SUCCESS:
                    print("Send successful")
                    self.data = None
                    return True
                # error try again next time
                elif self.data.status() < 0:
                    print("Send failed")
                    self.data = None
            # Handles if lose connectivity or our connection
            except OSError as e:
                print_exception(e)
                self.data = None
        return False

    def check_update(self):
        # do we already have a pending request
        device_request = cloud.device_request_receive()
        if device_request is not None:
            print("got device request")
            self.body = device_request.read().strip()
            if self.body == b"on" or self.body == b"off":
                response = "OK"
            else:
                response = "ERROR"
            print("request status: {}".format(response))
            device_request.write(response)
            device_request.close()
            return True
        return False

    def get_value(self):
        return self.body


def update_cloud(remote_mgr, bulbs):
    print("update cloud")
    if check_cellular():
        return remote_mgr.update(bulbs.get_light(), bulbs.get_night_light(), bulbs.get_lumens())
    return False


class Button:
    def __init__(self):
        self.button = Pin.board.D1
        self.button.mode(Pin.IN)
        self.button.pull(Pin.PULL_UP)
        self.state = [1, 1]

    def check_button(self, bulbs):
        # set the previous state
        self.state[0] = self.state[1]
        # read the current button state
        self.state[1] = self.button.value()
        # detected button release
        if self.state == [0, 1]:
            print('button press detected:', self.state, bulbs.get_light(), bulbs.get_night_light())
            bulbs.set_light(not bulbs.get_light())
            return True
        return False


def __main():
    button = Button()
    bulbs = BLESmartSwitch()
    digirm_client = DigiCloud()
    lasttime = time()
    UPDATE_NONE, UPDATE_CLOUD = 0, 1
    update_state = UPDATE_NONE
    while True:
        try:
            if not bulbs.is_connected():
                bulbs.connect()
            if button.check_button(bulbs):
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

                if update_state == UPDATE_CLOUD:
                    if update_cloud(digirm_client, bulbs):
                        update_state = UPDATE_NONE
                if digirm_client.check_update():
                    bulbs.set_light(digirm_client.get_value() == b'on')

        except OSError as e:
            # provide debug info, but keep going
            print_exception(e)


__main()

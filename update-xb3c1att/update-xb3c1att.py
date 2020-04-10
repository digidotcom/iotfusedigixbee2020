# Copyright 2020 Digi International
# MIT License
#
# You need to install the necessary python packages and use python 3
#
# pip install pyserial
# pip install xmodem
import getpass

import serial
import time
import base64
from http import client
import argparse
import logging
import os
import sys
import time
from xmodem import XMODEM

UPLOAD = b'1'
RUN = b'2'

username = ""
password = ""
imei = ""
starttime = time.time()


def update_xbee(port, filename=None,
         force=False, debug=False, wait_for_modem_status_at_baud=0):

    ser = serial.Serial(port, 115200, timeout=5)

    if debug:
        # python upload_gbl.py com60
        print("debug info")
        ser.write(b'\r')
        print(ser.read(1000))
        return 0
    elif force:
        # python upload_gbl.py com60 force

        # NOTE: Somehow the act of closing and reopening the port
        # causes the bootloader menu to come out automatically
        # if we're still sitting in the bootloader at this point.
        # Maybe it's the read call that does it, or toggling the I/O lines.
        ser.close()
        # rtscts=False so we can control it manually. It's weird...
        ser = serial.Serial(port, 115200, timeout=7, rtscts=False, dsrdtr=True)

        try:
            ser.setBreak(True)
            ser.setRTS(False)
            ser.setDTR(True)
        except AttributeError:
            ser.break_condition = True
            ser.rts = False
            ser.dtr = True
        print("Wait for reset...")
        # 82 is the exact length of the cellular bootloader menu output
        COUNT = 82
        out = ser.read(COUNT)

        assert b"Gecko Bootloader" in out, repr(out)
        print("Got some response: %r" % out)
        return 0

    filesize = os.path.getsize(filename)

    ser.write(UPLOAD)
    begin = b'\r\nbegin upload\r\n\x00'
    response = ser.read(len(begin))
    assert response == begin, "Cannot begin upload? %r" % response

    def getc(size, timeout=1):
        return ser.read(size) or None
    def putc(data, timeout=1):
        return ser.write(data)

    # Suppress log messages for each block.
    logging.getLogger('xmodem.XMODEM').setLevel(logging.INFO)

    modem = XMODEM(getc, putc)
    print("Xmodem opened")
    with open(filename, 'rb') as firmware:
        print("Streaming")
        modem.send(firmware)

    good = b'\r\nSerial upload complete\r\n\x00\r\nGecko Bootloader'
    response = ser.read(len(good))
    assert response == good, "Unsuccessful? %r" % response

    # Flush the rest of the header and menu to ensure wait_for_modem_status can work.
    print("Upload complete. Flushing input...")
    extra = ser.read(100)
    assert extra.endswith(b'BL > \x00'), "Didn't get prompt? %r" % extra

    print("Running...")
    ser.write(RUN)

    if wait_for_modem_status_at_baud:
        ser.apply_settings({"baudrate":wait_for_modem_status_at_baud,
                            "timeout":60})
        started_waiting = time.time()
        status = ser.read(6)
        finished = time.time()
        print("After {:.0f} seconds, got {:.0f} bytes: {!r}".format(
            finished - started_waiting, len(status), status))

    return 0


def send_FOTA_request(payload):
    # create HTTP basic authentication string, this consists of 
    # "username:password" base64 encoded 
    auth = base64.b64encode("{}:{}".format(username,password).encode())
    deviceId = "00010000-00000000-0{}-{}".format(imei[:7], imei[7:])

    payload64 = base64.b64encode(payload)

    # message to send to server
    message = """<sci_request version="1.0">
      <data_service>
        <targets>
          <device id="{devid}"/>
        </targets>
        <requests>
          <device_request target_name="FTP_OTA" format="base64"> 
            {payld}
          </device_request>
        </requests>
      </data_service>
    </sci_request>
    """.format(devid=deviceId,payld=payload64.decode())

    print("Sending update request to Digi Remote Manager.")

    webservice = client.HTTPSConnection("remotemanager.digi.com")

    # to what URL to send the request with a given HTTP method
    webservice.putrequest("POST", "/ws/sci")

    # add the authorization string into the HTTP header
    webservice.putheader("Authorization", "Basic {}".format(auth.decode()))

    webservice.putheader("Content-type", "text/xml")
    webservice.putheader("Content-length", "{}".format(len(message)))
    webservice.putheader("Accept", "text/xml");
    webservice.endheaders()
    webservice.send(message.encode())

    # get the response
    print("Waiting for response..")
    response = webservice.getresponse()
    print("Got response:")
    statuscode = response.status
    statusmessage = response.reason
    response_body = response.read()
    # print the output to standard out
    print (statuscode, statusmessage)


stages = [b"ftp1.digi.com\x0021\x00anonymous\x00iotfuse@digi.com\x00support/telit\x0023.00.303.2__23.00.304-B301__LE866A1-NA.ua",
          b"ftp1.digi.com\x0021\x00anonymous\x00iotfuse@digi.com\x00support/telit\x0023.00.303.3__23.00.304-B301__LE866A1-NA.ua",
          b"ftp1.digi.com\x0021\x00anonymous\x00iotfuse@digi.com\x00support/telit\x0023.00.304-B301__23.00.306__LE866A1-NA.ua"
]


def checkmv(ser):
    module_vers = b''
    if cmdmode(ser):
        while True:
            cmdmode(ser)
            ser.write(b'ATMV\r\n')
            module_vers = ser.read(32)
            logging.debug(module_vers)
            if module_vers.startswith(b'23'):
                break
            print("Module version not ready sleeping 20 seconds...")
            time.sleep(20)

        if module_vers.startswith(b'23.00.306'):
            print("Module up to date. Nothing to perform.")
            exit(0)
        if module_vers.startswith(b'23.00.303'):
            cmdmode(ser)
            ser.write(b'ATMU\r\n')
            subvers = ser.read(4)
            logging.debug("subvers is {}".format(subvers))
            if subvers.startswith(b'3'):
                return 1
            else:
                return 0

        # must be
        if module_vers.startswith(b'23.00.304'):
            return 2
    else:
        print("No response from modem")
        exit(-1)
        

def checkok(ser):
    x = ser.read(4)
    logging.debug(x)
    return x.startswith(b'OK')


def cmdmode(ser):
    time.sleep(1)
    ser.write(b"+++")
    time.sleep(1)
    return checkok(ser)


def enable_remotemanager(ser):
    print("Enabling remote manager")
    if cmdmode(ser):
        ser.write(b'ATDO1\r\n')
        checkok(ser)
        ser.write(b'ATMO7\r\n')
        checkok(ser)
        ser.write(b'ATWR\r\n')
        checkok(ser)
        ser.write(b'ATAC\r\n')
        checkok(ser)
    else:
        print("Failed to enter AT command mode.")
        exit(-1)

def waitfornetwork(ser):
    ai = b'ff'
    while not ai.startswith(b'0'):
        if cmdmode(ser):
            ser.write(b'atai\r\n')
            ai = ser.read(4)
            logging.debug(ai)

def waitforremotemanager(ser):
    ai = b'2'
    while not int(ai) in [0,5,6]:
        if cmdmode(ser):
            ser.write(b'atdi\r\n')
            ai = ser.read(4)
            logging.debug(ai)
     
def waitforfirmwareupdate(ser):
    if cmdmode(ser):
        ser.write(b'atfi\r\n')
        response = ser.read(4)
        logging.debug('FI is {}'.format(response))
        while response.upper().startswith(b'F'):
            cmdmode(ser)
            time.sleep(5)
            ser.write(b'ATFI\r\n')
            response = ser.read(4)
            print(".", end='')
            logging.debug('FI is {}'.format(response))
    if response.startswith(b'0'):
        print("Success")
    if response.startswith(b'1'):
        print("FTP transfer failed. Moving on to next image.")
    if response.startswith(b'2'):
        print("Image rejection detected (don't panic). Moving on to next image.")
    if response.startswith(b'10'):
        print("Error: Update request issue. Moving on to next image.")
    if response.startswith(b'11'):
        print("Error: XBee sleep detected. Turn off sleep and try again.")
        exit(-1)

def update_cell(port):
    global starttime
    baud = 9600
    ser = serial.Serial(port, baud, timeout=1)
    try:
        if not cmdmode(ser):
            print("Check serial parameters. COM port and 9600/8/1/N")
            exit(-1)

        enable_remotemanager(ser)
        for attempts in range(2):
            print("{:.0f} seconds have elapsed.".format(time.time() - starttime))
            print("Waiting for cell network....")
            waitfornetwork(ser)
            print("Network connection OK.")
            print("Waiting for remote manager....")
            waitforremotemanager(ser)
            print("Remote manager connection OK....")
            stage = checkmv(ser)
            print("Attempting update stage {}...".format(stage))
            send_FOTA_request(stages[stage])
            print("{:.0f} seconds have elapsed.".format(time.time() - starttime))
            print("Waiting for update to complete.")
            waitforfirmwareupdate(ser)
        ser.close()
    except Exception as e:
        ser.close()
        raise e

def check_module_version(port, filename):
    baud = 9600
    ser = serial.Serial(port, baud, timeout=1)
    try:
        if not cmdmode(ser):
            print("Check serial parameters. COM port and 9600/8/1/N")
            exit(-1)
        ser.write(b'ATVR\r\n')
        xbvers = ser.read(10)
        ser.close()
        if not xbvers.startswith(b'31'):
            print("This script is only for XBee 3 Cellular Cat 1 AT&T")
            exit(-1)
        elif int(xbvers) == 31015:
            return True
        return False
    except Exception as e:
        ser.close()
        raise e


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser("IoT Fuse 2020 Digi XBee 3 CAT 1 AT&T update script")
    parser.add_argument('port', help='COM port of XBee, example: COM60')
    parser.add_argument('imei', help='IMEI of Digi XBee 3 Cellular Cat 1 AT&T')
    parser.add_argument('username', help='username for Digi Remote Manager')
    parser.add_argument('password', help='password for Digi Remote Manager')
    parser.add_argument('-w', '--wait', required=False, type=int, default=9600,
                        dest='wait_for_modem_status',
                        help='Baud rate at which to wait for a modem status (6 bytes)')

    args = parser.parse_args()
    args.filename = 'XBXC-31015.gbl'
    debug = not args.filename
    username = args.username
    password = args.password
    imei = args.imei
    starttime = time.time()

    if len(imei) != 15:
        print("IMEI must be 15 characters")
        exit(-1)
    print("The process will take approximately 15 minutes or more (~900 seconds). Please be patient.")
    print("{:.0f} seconds have elapsed.".format(time.time() - starttime))
    if not check_module_version(args.port, args.filename):
        print("Updating XBee firmware...")
        update_xbee(
            args.port, args.filename, debug=debug, force=True,
            wait_for_modem_status_at_baud=args.wait_for_modem_status)
        print("{:.0f} seconds have elapsed.".format(time.time() - starttime))
        update_xbee(
            args.port, args.filename, debug=debug, force=False,
            wait_for_modem_status_at_baud=args.wait_for_modem_status)
        print("XBee firmware update complete")
        print("{:.0f} seconds have elapsed.".format(time.time() - starttime))
        print("Waiting for XBee to reboot")
        time.sleep(5)
    else:
        print("Latest XBee firmware detected skipping..")
    update_cell(args.port)
    print("Completed at {:.0f} seconds")
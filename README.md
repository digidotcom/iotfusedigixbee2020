# IoT Fuse 2020 Digi XBee® Workshops Repository

This repository contains the programs that we will be going over in the
workshops at IoT Fuse 2020:

Building IoT Applications with MicroPython and Digi XBee 3 Cellular
Building IoT Applications with MicroPython and AWS or Azure

Keep an eye on this repository for those attending the workshops
as I will make updates here and also be posting code here for
the workshop.

If you have questions about the following prior to the workshops,
you can reach me at:

eugene.fodor@digi.com

## Getting Started and Prerequisites

You will need to acquire the following kits:

A Windows 10 laptop computer (or equivalent) with a USB 3.0 port. USB 2.0 may 
not supply sufficient current. Mac/Linux should also work, but I did not test 
everything on those platforms.

Digi XBee® 3 Cellular LTE Cat-1 Development Kit (available through Digi-Key: 
https://www.digikey.com/product-detail/en/digi/XK3-C-A1-UT-U/602-2212-ND/8109034
Silicon Labs Thunderboard Sense 2 IoT Kit (available through Digi-Key: 
https://www.digikey.com/product-detail/en/silicon-labs/SLTB004A/336-4166-ND/7689215
Murata Electronics CR2032 Battery (optional – available through Digi-Key: 
https://www.digikey.com/product-detail/en/murata-electronics/CR2032/490-18646-%20ND/9558425


It is recommended that you have Python 3 installed to run the update script for
the XBee 3 Cellular.

https://www.python.org/downloads/

You will want to install the following programs on your computer if you want to
follow along:

Both workshops:

XCTU Latest XBee Configuration Utility version 6.5.0+

https://www.digi.com/products/embedded-systems/digi-xbee/digi-xbee-tools/xctu

Pycharm version 2019.3.x (2019.3.4). Do not install the latest version 2020 
as it is incompatible with the Pycharm plugin.

https://www.jetbrains.com/pycharm/download/other.html

Digi XBee 3 Cellular MicroPython Pycharm Plugin

https://plugins.jetbrains.com/plugin/12445-xbee-%20micropython

Git (recommended)

https://www.git.org/downloads/

Create the following accounts:

Digi Remote Manager Free Developer Account for 5 Devices
https://myacct.digi.com

Workshop 2 only: 
https://aws.amazon.com/free/
https://azure.microsoft.com/en-us/free/
Note that if you have a corporate account, you may need to use a different 
personal e-mail (e.g. gmail) to sign up for a free account.

Please update your XBee to the latest firmware as described in the next section.

### Updating your Digi XBee 3 Cellular CAT 1 AT&T

Upgrade your Digi XBee 3 Cellular Cat 1 AT&T to the 
latest firmware 31015 it is not already on it. 
If you are using a different Digi XBee 3 Cellular module 
follow the manual for that module.

1. Follow setup for your XBee 3 Cellular device and get it on the cellular network 
   and add the device to your Digi Remote Manager account. You can skip the firmware 
   upgrade steps as the script in step 2 will do that. 
2. Start a cmd or shell script and change to the directory of the update script
   iotfusedigixbee2020/update-xb3c1att
3. The script takes about 15-20 minutes to run assuming no errors. Run the python 
   script from the update-xb3c1att.py directly from the update-xb3c1att directory 
   as follows:

   ```
   python update-xb3c1att.py port imei username password
   ```
   
   For example, on Windows run as:
   
   ```
   python update-xb3c1att.py COM28 123456789012345 jdoe password
   ```
   
   or on Mac/Linux as:
   
   ```
   python update-xb3c1att.py /dev/ttyS27 123456789012345 jdoe password
   ```
   
   If you get an error you can rerun the script without issue. It will attempt to pick
   up where it left off.
   
   Troubleshooting Tips:
   Make sure your cellular signal is strong? Move the device
   closer to a window if needed to get better line-of-sight.
   Did you run the script for the correct directory?
   Did you install the required packages (xmodem, pyserial)?
   Did you add your Digi XBee 3 Cellular to your Digi Remote Manager account?
   
   
## Authors

* **Eugene Fodor** - *Initial work* - [iotfusedigixbee2020](https://github.com/DigiEntmgmt/iotfusedigixbee2020)

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md)
file for details

## Acknowledgments

* Thanks to all of my team members Matthew Beaudoin, Chris Evans, Kurt Erickson,
  Scott Kilau, Travis Lubbers, and Mike Wadsten for their contributions 
  and support.


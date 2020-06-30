#!/usr/bin/python3
# ------------------------------------------------------------------------------
"""@package find_new_xdevices.py

Finds the available Xiaomi sensor devices
"""
# ------------------------------------------------------------------------------
#                  Kris Dunning ippie52@gmail.com 2020.
# ------------------------------------------------------------------------------
from bluetooth.ble import DiscoveryService
from argparse import ArgumentParser
from json import dumps
import sys

DEFAULT_DURATION_S = 5

parser = ArgumentParser()
parser.add_argument('-d', '--duration', type=int, default=DEFAULT_DURATION_S,
    help='Provides the scan duration in whole seconds.')
parser.add_argument('-e', '--existing', type=str, nargs='+', default=[],
    help='Provides the existing device addresses.')

args = parser.parse_args()

def debug_print(*message):
    """
    Prints in colour
    """
    GREEN = '\033[92m'
    NORMAL = '\u001b[0m'
    print(GREEN, *message, NORMAL, file=sys.stderr)

TEMP_HUM_DEV_ADDR_START = "A4:C1:38"
TEMP_HUM_DEV_NAME       = "LYWSD03MMC"

try:
    service = DiscoveryService()
    debug_print('Ingnoring:', args.existing)
    debug_print(f"Scanning for {args.duration} seconds...")
    devices = service.discover(args.duration)
    debug_print(f"{len(devices)} devices found.")
    x_devices = {}
    next_index = len(args.existing) + 1

    for addr, name in devices.items():
        if addr[:len(TEMP_HUM_DEV_ADDR_START)] == TEMP_HUM_DEV_ADDR_START or \
            name == TEMP_HUM_DEV_NAME:
            if addr not in args.existing:
                debug_print(addr, 'not in', args.existing)
                device = {
                    'dev_name': name,
                    'addr': addr,
                    'sensor_name': "Sensor %02d" % next_index,
                    'history_file': f'sensor_{addr.replace(":", "")}_history.json',
                    'active': True,
                    'last_reading': None
                }
                next_index += 1
                debug_print(f"New device found: {name}: {addr}")
                x_devices[addr] = device
            else:
                debug_print(addr, 'already known')
    if len(x_devices):
        debug_print(f"{len(x_devices)} found during this scan.")
    else:
        debug_print("No new Xiaomi devices found.")
    print(dumps(x_devices, indent=2))
except KeyboardInterrupt:
    debug_print('User interrupted')
    sys.exit(1)
except Exception as e:
    debug_print('Unknown error:', e)
    raise e

sys.exit(0)

#!/usr/bin/python3
# ------------------------------------------------------------------------------
"""@package get_sensor_data.py

Gets the sensor data as a JSON formatted dictionary.
"""
# ------------------------------------------------------------------------------
#                  Kris Dunning ippie52@gmail.com 2020.
# ------------------------------------------------------------------------------

from json import dumps
from bluepy.btle import BTLEDisconnectError
from lywsd02 import Lywsd02Client
from sys import stderr, argv, exit
from datetime import datetime

class ExitCodes:
    OK = 0
    INVALID_ARGS = 1
    USER_CANCELLED = 2
    TIMED_OUT = 3
    DATA_NOT_SENT = 4
    UNKNOWN_ERROR = 5

def error(*message):
    """
    """
    RED = '\033[91m'
    NORMAL = '\u001b[0m'
    print(RED, *message, NORMAL, file=stderr)

if __name__ == '__main__':

    if len(argv) < 2:
        error("Address of the Xiaomi sensor device is required")
        exit(1)

    try:
        client = Lywsd02Client(argv[1])
        reading = {
            'timestamp': datetime.now().isoformat(),
            'temperature': client.temperature,
            'humidity': client.humidity,
            'battery': client.battery
        }
        print(dumps(reading, indent=2))
        exit(ExitCodes.OK)

    except KeyboardInterrupt:
        error("User cancelled scan.")
        exit(ExitCodes.USER_CANCELLED)

    except TimeoutError:
        error(f"Data wasn't sent ({attempts}/{max_attempts})")
        exit(ExitCodes.TIMED_OUT)

    except BTLEDisconnectError:
        error(f"Data wasn't sent.")
        exit(ExitCodes.DATA_NOT_SENT)

    except Exception as e:
        error(f"Unknown exception triggered:", e)
        exit(ExitCodes.UNKNOWN_ERROR)
    exit(ExitCodes.UNKNOWN_ERROR)

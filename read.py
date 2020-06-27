#!/usr/bin/python3
from bluetooth.ble import DiscoveryService, GATTRequester
from time import sleep
from struct import unpack
from lywsd02 import Lywsd02Client
from datetime import datetime, timedelta
from json import dumps, loads
from os import path
from bluepy.btle import BTLEDisconnectError

class Uuid:
    BASE_UUID = "00000000-0000-1000-8000-00805F9B34FB"

    def __init__(self, uuid_str):
        chars = len(uuid_str)
        if chars != 4 and chars != len(Uuid.BASE_UUID):
            raise Exception("UUID provided is invalid: " + uuid_str)
        self.uuid_16 = None if chars != 4 else uuid_str
        if chars == len(Uuid.BASE_UUID):
            self.uuid_128 = uuid_str
        else:
            self.uuid_128 = Uuid.BASE_UUID[:4] + uuid_str + Uuid.BASE_UUID[8:]

    def uuid16(self):
        return self.uuid_16

    def uuid128(self):
        return self.uuid_128

    def __eq__(self, other):
        if isinstance(other, Uuid):
            return self.uuid128() == other.uuid128()
        return False

class Characteristic:
    def __init__(self, uuid_str):
        self.uuid = Uuid(uuid_str)
        self.descs = {}

    def __getitem__(self, key):
        if key in self.descs:
            return self.descs[key]
        return None

    def has_desc(self, uuid):
        return uuid in self.descs

class Service:
    def __init__(self, uuid_str):
        self.uuid = Uuid(uuid_str)
        self.chars = {}

    def __getitem__(self, key):
        if key in self.chars:
            return self.chars[key]
        return None

    def has_char(self, uuid):
        return uuid in self.chars

class XiaomiRequester(GATTRequester):
    def __init__(self, *args):
        GATTRequester.__init__(self, *args)

    def on_notification(self, handle, data):
        GATTRequester.on_notification(self, handle, data)
        if handle == 0x36:
            # print(type(data))
            # print(len(data))
            h1, h2, b3, humidity, temp = unpack("<HHBBH", data)
            temp = temp / 100
            print(f"{temp}*C and {humidity}% ({h1}, {h2}, {b3})")
            # print(h1, b1, b2, b3, humidity, temp)




class Reader:

    def __init__(self, addr):
        self.addr = addr
        self.req = XiaomiRequester(addr, False)
        print(dir(self.req))
        self.services = {}
        self.connect()
        self.request_data()

    def connect(self, scan_gatt=True):
        print(f"Connecting to {self.addr}")
        self.req.connect(True)
        print("Connected.")
        if scan_gatt:
            self.scan_gatt()

    def scan_gatt(self):
        services = self.req.discover_primary()
        for s in services:
            print(s)

    def request_data(self):
        pass

    def disconnect(self):
        self.req.disconnect()

# service = DiscoveryService()
# devices = service.discover(3)

TEMP_HUM_DEV_ADDR_START = "A4:C1:38"
TEMP_HUM_DEV_NAME       = "LYWSD03MMC"
SETTINGS_FILENAME       = "settings.json"

def save_settings(settings, filename):
    """
    Saves the current settings to file
    """
    if isinstance(settings, dict):
        settings['save id'] += 1
        settings = dumps(settings, sort_keys=True, indent=4)
    else:
        raise Exception("Settings must be provided as a dictionary.")
    with open(filename, 'w') as f:
        f.write(settings)


def load_settings(filename):
    """
    Loads the configuration settings for scanning and gathering
    """
    # Create some defaults
    settings = {
        'interval': {
            'mins': 2, 'secs': 30
        },
        'sensor file': 'sensors.json',
        'save id': 0,
        'scan seconds': 5,
        'max attempts': 3,
        'next scan': datetime.now().isoformat()
    }
    loaded = False
    if path.isfile(filename):
        try:
            with open(filename, 'r') as f:
                settings_json = f.read()
                settings = loads(settings_json)
                print(f"Loaded settings: {settings_json}")
                loaded = True
        except:
            pass
    if not loaded:
        save_settings(settings, filename)
    return settings


def find_new_xiaomi_devices(existing, duration):
    """
    Finds all new xiaomi devices by name and address.
    Assigns a new name to the device in the form:
    Sensor xx, where xx is the next available index
    """
    next_index = len(existing) + 1
    x_devices = {}
    service = DiscoveryService()
    devices = service.discover(duration)
    print(f"Scanning found {len(devices)} devices.")
    for addr, name in devices.items():
        if addr[:len(TEMP_HUM_DEV_ADDR_START)] == TEMP_HUM_DEV_ADDR_START or \
            name == TEMP_HUM_DEV_NAME:
            if addr not in existing:
                device = {
                    'dev_name': name,
                    'addr': addr,
                    'sensor_name': "Sensor %02d" % next_index,
                    'history_file': f'sensor_{addr.replace(":", "")}_history.json',
                    'active': True,
                    'last_reading': None
                }
                next_index += 1
                print(f"Found new device: {name}: {addr}")
                x_devices[addr] = device
    if len(x_devices):
        print(f"Only {len(x_devices)} were new")
    else:
        print("None were new")
    return x_devices

def load_devices_from_persistent(filename):
    """
    Loads existing device info from JSON file
    """
    devices ={}
    if path.isfile(filename):
        try:
            with open(filename, 'r') as f:
                devices_json = f.read()
                devices = loads(devices_json)
                print(f"Found devices: {devices_json}")
        except Exception as e:
            print(f"Failed to open {filename}")
            raise e
            pass
    return devices

def save_devices_to_persistent(devices, filename):
    """
    Saves the device settings to the given file name
    """
    if isinstance(devices, dict):
        devices = dumps(devices, sort_keys=True, indent=4)
    else:
        raise Exception("Device information must be a dictionary")
    with open(filename, 'w') as f:
        f.write(devices)

def update_histories(device, new_reading):
    """
    Updates the history file for the given device
    """
    history_json = ""
    history = {}
    if path.isfile(device['history_file']):
        try:
            with open(device['history_file'], 'r') as f:
                history_json = f.read()
                history = loads(history_json) if len(history_json) else {}
        except Exception as e:
            print("Failed to open history file.")
            raise e

    history[new_reading['timestamp']] = new_reading
    with open(device['history_file'], 'w') as f:
        f.write(dumps(history, sort_keys=True, indent=4))


def gather_readings(devices, max_attempts):
    """
    Connects to each device and gathers the readings
    """
    keys = devices.keys()

    for addr in keys:
        device = devices[addr]
        attempts = 0
        readings_complete = False
        while attempts < max_attempts and not readings_complete:
            try:
                attempts += 1
                print(f"Attempting to read from sensor {device['sensor_name']}...")
                client = Lywsd02Client(device['addr'])
                reading = {
                    'timestamp': datetime.now().isoformat(),
                    'temperature': client.temperature,
                    'humidity': client.humidity,
                    'battery': client.battery
                }
                devices[addr]['last reading'] = reading
                update_histories(devices[addr], reading)
                print(f"Device {device['sensor_name']} ({device['addr']}) -> {dumps(reading, sort_keys=True, indent=4)}")
                readings_complete = True
            except KeyboardInterrupt:
                print("User cancelled scan.")
                readings_complete = True

            except TimeoutError:
                print(f"Data wasn't sent ({attempts}/{max_attempts})")

            except BTLEDisconnectError:
                print(f"Failed to connect. Perhaps the device is busy elsewhere.")
                # Force an early end to the loop - Waiting for a connection is time consuming
                attempts = max_attempts

            except Exception as e:
                # print(e)
                # print(f"Failed to gather readings for {device['addr']}. Trying again...")
                raise e
    return devices

# Load default or saves settings
settings = load_settings(SETTINGS_FILENAME)

# Load existing devices from json
x_devices = load_devices_from_persistent(settings['sensor file'])
print(f"Devices from storage: {x_devices}")

# Set the scanning intervals
interval = timedelta(
    minutes=settings['interval']['mins'],
    seconds=settings['interval']['secs'])
print(f"DEBUG: Interval: {interval}")
next_scan = datetime.fromisoformat(settings['next scan'])

while True:
    if datetime.now() > next_scan:
        print("Scanning for new devices...")

        # Load any newly discovered devices
        new_x_devices = find_new_xiaomi_devices(x_devices, settings['scan seconds'])
        if len(new_x_devices):
            x_devices = { **x_devices, **new_x_devices }
            print(f"Newly discovered devices: {new_x_devices}")
            save_devices_to_persistent(x_devices, settings['sensor file'])

        print("Finished scanning, go get readings...")
        x_devices = gather_readings(x_devices, settings['max attempts'])
        # Save the updated readings
        save_devices_to_persistent(x_devices, settings['sensor file'])
        next_scan = next_scan + interval
        settings['next scan'] = next_scan.isoformat()
        save_settings(settings, SETTINGS_FILENAME)
        print("Done for now.")
    else:
        sleep(1)

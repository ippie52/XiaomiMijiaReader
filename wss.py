#!/usr/bin/python3
# ------------------------------------------------------------------------------
"""@package wss.py

WebSocket server for providing access and control over the Xiaomi temperature
and humidity sensors.
"""
# ------------------------------------------------------------------------------
#                  Kris Dunning ippie52@gmail.com 2020.
# ------------------------------------------------------------------------------
from threading import Lock
from bluetooth.ble import DiscoveryService, GATTRequester
from datetime import datetime, timedelta
from os import path
from json import loads, dumps
from bluepy.btle import BTLEDisconnectError
from time import sleep
from lywsd02 import Lywsd02Client
from get_sensor_data import ExitCodes
import asyncio
import websockets
import sys

class Constants:
    """
    Class to provide constant values
    """
    ADDR                    = ''
    PORT                    = 9042
    SETTINGS_FILENAME       = "wss_settings.json"
    TEMP_HUM_DEV_ADDR_START = "A4:C1:38"
    TEMP_HUM_DEV_NAME       = "LYWSD03MMC"

class SensorServer:
    """
    SensorServer class - Provides the server methods
    """

    def __init__(self, addr, port, settings_filename, loop):
        """
        Constructs the server
        """
        self._addr = addr
        self._port = port
        self._loop = loop
        self._queue = asyncio.Queue()
        self._settings_filename = settings_filename
        self._receiving = True
        self._gathering = True
        self._sensor_lock = Lock()
        self._client_lock = Lock()
        self._settings_lock = Lock()
        self._clients = {}
        self._client_count = 0

        # Load saved settings
        self._settings = SensorServer.load_settings(self._settings_filename)

        # Load saved device information
        self._devices = SensorServer.load_devices(self._settings['sensor_file'])

        self._loop.create_task(self.gather_readings())
        # self._loop.create_task(self.receive_messages())
        self._server = websockets.serve(self.new_client, self._addr, self._port)

    async def receive_messages(self):
        """
        Handles incoming messages
        """
        # sys.exit(1)
        count = 0
        print("Starting receive_messages()")
        while self._receiving:
            count += 1
            print("Heartbeat", count)
            await asyncio.sleep(1)
            # message = await self._queue.get()
            # print(f"Message received: {message}")

    async def gather_readings(self):
        """
        Runs forever gathering sensor data
        """
        # Prevent checking again too soon, but don't create a backlog
        print("Starting gather_readings()")
        self._settings_lock.acquire(True)
        next_scan = datetime.fromisoformat(self._settings['next_scan'])
        self._settings_lock.release()

        if datetime.now() > next_scan:
            next_scan = datetime.now()

        while self._gathering:
            if datetime.now() > next_scan:
                # Prepare the settings values to prevent
                # locking them up while scanning
                self._settings_lock.acquire(True)
                scan_seconds = self._settings['scan_seconds']
                sensor_file = self._settings['sensor_file']
                max_attempts = self._settings['max_attempts']
                interval = timedelta(
                    minutes=self._settings['interval']['mins'],
                    seconds=self._settings['interval']['secs']
                )
                self._settings_lock.release()
                print("Scanning for new devices...")

                # Load any newly discovered devices
                new_x_devices = await SensorServer.find_new_xiaomi_devices(
                    self._devices,
                    scan_seconds
                )
                if len(new_x_devices):
                    self._sensor_lock.acquire(True)
                    self._devices = { **self._devices, **new_x_devices }
                    print(f"Newly discovered devices: {new_x_devices}")
                    SensorServer.save_devices(
                        self._devices,
                        sensor_file
                    )
                    self._sensor_lock.release()

                print("Finished scanning, go get readings...")
                devices = await SensorServer.gather_sensor_readings(
                    self._devices,
                    max_attempts
                )
                self._sensor_lock.acquire(True)
                self._devices = devices
                # Save the updated readings
                SensorServer.save_devices(
                    self._devices,
                    sensor_file
                )
                self._sensor_lock.release()
                await self.broadcast_sensors()

                next_scan = next_scan + interval
                # Quickly check we're not running massively over with
                # the scanning time - start the next scan to try and
                # keep up with the interval, but don't make up for lost
                # scans
                if datetime.now() > next_scan:
                    next_scan = datetime.now()

                self._settings_lock.acquire(True)
                self._settings['next_scan'] = next_scan.isoformat()
                settings = self._settings
                self._settings_lock.release()

                SensorServer.save_settings(
                    settings,
                    self._settings_filename
                )
                print("Done for now.")
            else:
                await asyncio.sleep(1)

    async def broadcast_message(self, message_json, client_id=None):
        """
        Broadcasts a message to all or the selected client ID
        """
        # Assume we want to iterate through several messages
        if not isinstance(message_json, list):
            message_json = [message_json]

        keys = None
        if client_id is None:
            self._client_lock.acquire(True)
            keys = self._clients.keys()
            self._client_lock.release()
        else:
            if isinstance(client_id, list):
                keys = client_id
            else:
                keys = [client_id]

        for key in keys:
            try:
                self._client_lock.acquire(True)
                client = self._clients[key]
                self._client_lock.release()
                for msg in message_json:
                    # print(f"Sending {msg} to {key}")
                    await client.send(msg)
            except Exception as e:
                print("Failed to send message to client:", key)
                raise e

    async def broadcast_settings(self, client_id=None):
        """
        Broadcasts the current settings to the clients
        """
        self._settings_lock.acquire(True)
        message = {
            'cmd': 'settings',
            'data': self._settings
        }
        self._settings_lock.release()
        await self.broadcast_message(dumps(message), client_id)

    async def broadcast_sensors(self, client_id=None):
        """
        Broadcasts the latest sensor information to the clients
        """
        self._sensor_lock.acquire(True)
        message = {
            'cmd': 'sensors',
            'data': self._devices
        }
        self._sensor_lock.release()
        await self.broadcast_message(dumps(message), client_id)

    async def handle_message(self, message):
        """
        Handles incoming message and returns a response to be
        sent to the client
        """
        cmd = message['cmd']
        data = message['data']
        if cmd == 'settings':
            # The client wants to update the current settings
            print("Updating settings")
            self._settings_lock.acquire(True)
            self._settings = data
            self._settings_lock.release()
            print("Settings updated -> broadcasting")
            self.broadcast_settings()

        elif cmd  == 'sensors':
            # The client has made changes to all sensors
            print("Updating sensors")
            self._sensor_lock.acquire(True)
            self._devices = data
            self._sensor_lock.release()
            print("Sensors updated -> broadcasting")
            self.broadcast_sensors()

        elif cmd == 'single_sensor':
            # The client has made changes to one sensor
            addr = data['index']
            sensor_data = data['sensor']
            self._sensor_lock.acquire(True)
            if addr in self._sensors:
                self._sensors[addr]['sensor_name'] = sensor_data['sensor_name']
                self._sensors[addr]['active'] = sensor_data['active']
            self._sensor_lock.release()


        else:
            print("Unknown command:", cmd)

    async def new_client(self, client, path):
        """
        Handles incoming new client connections
        """
        self._client_lock.acquire(True)
        client_id = self._client_count
        self._client_count += 1
        self._clients[client_id] = client
        print(f"New client {client_id}: {client.remote_address}")
        self._client_lock.release()

        try:
            await self.broadcast_settings(client_id)
            await self.broadcast_sensors(client_id)
            # await self.broadcast_settings()
            # await self.broadcast_whatever()

            while True:
                json_str = ""
                try:
                    # pass
                    json_str = await client.recv()
                    json_data = None
                    try:
                        json_data = loads(json_str)
                    except:
                        print("Error parsing:", json_str)

                    if json_data is not None:
                        await self.handle_message(json_data)

                    # print(json_str)
                    # await client.send(json_str * 2)

                    # json_data = loads(json_str)
                    # Do something to obtain the message command and data

                    # if msg.cmd == whatever:
                    #     do the thing
                    # elif msg.cmd == some other:
                    #     do another thing
                    # else:
                    #     raise NotImplementedError(
                    #         f"Unknown command: {msg.cmd}")
                except Exception as e:
                    print("Failed to process incoming message:", json_str)
                    print(e)
                    raise e
        except websockets.exceptions.ConnectionClosedOK:
            print(f'Client {client_id} closed the connection')
            self.remove_client(client_id)
            print(f'Client {client_id} removed.')
        except websockets.exceptions.ConnectionClosedError:
            print(f'Client {client_id} closed the connection (error)')
            self.remove_client(client_id)
            print(f'Client {client_id} removed.')
        except KeyboardInterrupt:
            print('Keyboard interrupt hit')
            self.remove_client(client_id)
        except Exception as e:
            print('Unknown error encountered')
            print(e)
            self.remove_client(client_id)
            raise e

    def remove_client(self, client_id):
        """
        Removes a disconnected client
        """
        self._client_lock.acquire(True)
        del self._clients[client_id]
        self._client_lock.release()

    @staticmethod
    def save_settings(settings, filename):
        """
        Saves the current settings to file
        """
        if isinstance(settings, dict):
            settings['save_id'] += 1
            settings_json = dumps(settings, sort_keys=True, indent=4)
        else:
            raise Exception("Settings must be provided as a dictionary.")
        with open(filename, 'w') as f:
            f.write(settings_json)
            print(f"Settings saved with index {settings['save_id']}")

    @staticmethod
    async def find_new_xiaomi_devices(existing, duration):
        """
        Finds all new xiaomi devices by name and address.
        Assigns a new name to the device in the form:
        Sensor xx, where xx is the next available index

        Note: We use another script via subprocess, as it
        would otherwise block and prevent asyncio from running.
        Why this happens, I don't know!
        """
        x_devices = {}
        args = ['./find_new_xdevices.py', '-d', str(duration)]
        if len(existing):
            args += ['-e'] + list(existing.keys())
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE
        )
        try:
            data = await asyncio.wait_for(
                proc.communicate(),
                timeout=180
            )
        except asyncio.TimeoutError:
            print("Finding devices timed out")

        if proc.returncode == 0:
            x_devices = loads(data[0])

        print('--------------------------')
        print(x_devices)
        print('--------------------------')
        return x_devices


    @staticmethod
    def save_devices(devices, filename):
        """
        Saves the device settings to the given file name
        """
        if isinstance(devices, dict):
            devices = dumps(devices, sort_keys=True, indent=4)
        else:
            print("We got dis: ", devices)
            raise Exception("Device information must be a dictionary")
        with open(filename, 'w') as f:
            f.write(devices)

    @staticmethod
    def load_settings(filename):
        """
        Loads the configuration settings for scanning and gathering
        """
        # Create some defaults
        settings = {
            'interval': {
                'mins': 2, 'secs': 30
            },
            'sensor_file': 'wss_sensors.json',
            'save_id': 0,
            'scan_seconds': 5,
            'max_attempts': 3,
            'next_scan': datetime.now().isoformat()
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
            print("Not loaded, using default")
            SensorServer.save_settings(settings, filename)
        return settings

    @staticmethod
    def load_devices(filename):
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

    @staticmethod
    async def gather_sensor_readings(devices, max_attempts):
        """
        Connects to each device and gathers the readings
        """
        keys = devices.keys()

        for addr in keys:
            device = devices[addr]
            attempts = 0
            readings_complete = False
            while attempts < max_attempts and not readings_complete:
                attempts += 1
                result = ExitCodes.OK
                try:
                    print(f"Attempting to read from sensor {device['sensor_name']}...")
                    proc = await asyncio.create_subprocess_exec(
                        './get_sensor_data.py',
                        device['addr'],
                        stdout=asyncio.subprocess.PIPE
                    )
                    reading = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=180
                    )
                except concurrent.futures._base.TimeoutError:
                    result = ExitCodes.USER_CANCELLED
                except KeyboardInterrupt:
                    result = ExitCodes.USER_CANCELLED
                except TimeoutError:
                    result = ExitCodes.TIMED_OUT
                except Exception as e:
                    raise e

                if proc.returncode == ExitCodes.OK:
                    print('Data -> ', reading)
                    reading = loads(reading[0])
                    print('Return code -> ', proc.returncode)
                    devices[addr]['last_reading'] = reading
                    SensorServer.update_histories(devices[addr], reading)
                    print(f"Device {device['sensor_name']} ({device['addr']}) -> {dumps(reading, sort_keys=True, indent=4)}")
                    readings_complete = True
                elif proc.returncode == ExitCodes.INVALID_ARGS:
                    raise RuntimeError('The script requires an address!')
                elif proc.returncode == ExitCodes.USER_CANCELLED:
                    print("User cancelled scan.")
                    readings_complete = True
                elif proc.returncode == ExitCodes.TIMED_OUT:
                    print(f"Data wasn't sent ({attempts}/{max_attempts})")
                elif proc.returncode == ExitCodes.DISCONNECTED:
                    print(f"Failed to connect. Perhaps the device is busy elsewhere.")
                    attempts = max_attempts
                else:
                    print("Unknown exception.")
                    attempts = max_attempts




                # client = Lywsd02Client(device['addr'])
                # reading = {
                #     'timestamp': datetime.now().isoformat(),
                #     'temperature': client.temperature,
                #     'humidity': client.humidity,
                #     'battery': client.battery
                # }

                # except KeyboardInterrupt:


                # except TimeoutError:


                # except BTLEDisconnectError:

                #     # Force an early end to the loop - Waiting for a connection is time consuming


                # except Exception as e:
                #     # print(e)
                #     # print(f"Failed to gather readings for {device['addr']}. Trying again...")
                #     raise e
        return devices

    @staticmethod
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


if __name__ == '__main__':
    print(f"Starting server: {Constants.ADDR}:{Constants.PORT}")
    main_loop = asyncio.get_event_loop()
    server = SensorServer(
        Constants.ADDR,
        Constants.PORT,
        Constants.SETTINGS_FILENAME,
        main_loop
    )
    main_loop.run_until_complete(server._server)
    main_loop.run_forever()

#!/usr/bin/python3
# ------------------------------------------------------------------------------
"""@package history_to_csv.py

Converts Xiaomi Temperature/Humidity data history to CSV
"""
# ------------------------------------------------------------------------------
#                  Kris Dunning ippie52@gmail.com 2020.
# ------------------------------------------------------------------------------

from json import loads
from argparse import ArgumentParser
from os import path
from datetime import datetime

def to_excel_ts(ts):
    """
    Converts a datetime timestamp into Excel format date time
    """
    EPOCH = datetime(1899, 12, 30)
    delta = ts - EPOCH
    return float(delta.days) + (float(delta.seconds) / 86400)

parser = ArgumentParser()
parser.add_argument('-f', '--file', help='The input file name', required=True)
parser.add_argument('-o', '--output', help='The output file name', default=None)

args = parser.parse_args()

history_json = ""
if path.isfile(args.file):
    with open(args.file, 'r') as f:
        history_json = f.read()

history_data = {}
if len(history_json):
    history_data = loads(history_json)
    print(
        "Timestamp",
        "Temperature (*C)",
        "Humidity (%)",
        "Battery (%)",
        sep=", "
    )
    for ts, data in history_data.items():
        timestamp = datetime.fromisoformat(ts)

        print(
            to_excel_ts(timestamp),
            data['temperature'],
            data['humidity'],
            data['battery'],
            sep=", "
        )


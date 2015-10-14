#!/usr/bin/env python
#
# ChaseTracker 2.0 No GUI Version
#
# Copyright 2015 Mark Jessop <vk5qi@rfhead.net>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import urllib2, json, ConfigParser, sys, time, serial
from threading import Thread
from base64 import b64encode
from hashlib import sha256
from datetime import datetime
from socket import *


# Attempt to read in config file
config = ConfigParser.RawConfigParser()
config.read("chasetracker.conf")

callsign = config.get("General","callsign")
update_rate = int(config.get("General","update_rate"))
serial_port = config.get("GPS","serial_port")
serial_baud = int(config.get("GPS","serial_baud"))
speed_cap = int(config.get("GPS","speed_cap"))


# Position Variables
position_valid = False
lat = -34.0
lon = 138.0
alt = 0
speed = 0 # m/s


def updateTerminal():
    positionText = "Lat/Long: %.5f, %.5f \tSpeed: %d kph \tAlt: %d m" % (lat,lon,speed*3.6,alt)
    print positionText

# Courtesy of https://github.com/Knio/pynmea2/
import re
def dm_to_sd(dm):
    '''
    Converts a geographic coordiante given in "degres/minutes" dddmm.mmmm
    format (ie, "12319.943281" = 123 degrees, 19.953281 minutes) to a signed
    decimal (python float) format
    '''
    # '12319.943281'
    if not dm or dm == '0':
        return 0.
    d, m = re.match(r'^(\d+)(\d\d\.\d+)$', dm).groups()
    return float(d) + float(m) / 60

# We currently only recognise GPGGA and GPRMC
def parseNMEA(data):
    global lat,lon,speed,alt,position_valid
    if "$GPRMC" in data:
        gprmc = data.split(",")
        gprmc_lat = dm_to_sd(gprmc[3])
        gprmc_latns = gprmc[4]
        gprmc_lon = dm_to_sd(gprmc[5])
        gprmc_lonew = gprmc[6]
        gprmc_speed = float(gprmc[7])

        if gprmc_latns == "S":
            lat = gprmc_lat*-1.0
        else:
            lat = gprmc_lat

        if gprmc_lon == "W":
            lon = gprmc_lon*-1.0
        else:
            lon = gprmc_lon

        speed = min(110*0.27778, gprmc_speed*0.51444)
        updateTerminal()

    if "$GPGGA" in data:
        gpgga = data.split(",")
        gpgga_lat = dm_to_sd(gpgga[2])
        gpgga_latns = gpgga[3]
        gpgga_lon = dm_to_sd(gpgga[4])
        gpgga_lonew = gpgga[5]
        gpgga_fixstatus = gpgga[6]
        alt = float(gpgga[9])


        if gpgga_latns == "S":
            lat = gpgga_lat*-1.0
        else:
            lat = gpgga_lat

        if gpgga_lon == "W":
            lon = gpgga_lon*-1.0
        else:
            lon = gpgga_lon 

        if gpgga_fixstatus == 0:
            position_valid = False
        else:
            position_valid = True


# Habitat Upload Stuff, from https://raw.githubusercontent.com/rossengeorgiev/hab-tools/master/spot2habitat_chase.py
callsign_init = False
url_habitat_uuids = "http://habitat.habhub.org/_uuids?count=%d"
url_habitat_db = "http://habitat.habhub.org/habitat/"
uuids = []

def ISOStringNow():
    return "%sZ" % datetime.utcnow().isoformat()


def postData(doc):
    # do we have at least one uuid, if not go get more
    if len(uuids) < 1:
        fetch_uuids()

    # add uuid and uploade time
    doc['_id'] = uuids.pop()
    doc['time_uploaded'] = ISOStringNow()

    data = json.dumps(doc)
    headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'Referer': url_habitat_db,
            }

    print("Posting doc to habitat\n%s" % json.dumps(doc, indent=2))

    req = urllib2.Request(url_habitat_db, data, headers)
    return urllib2.urlopen(req).read()

def fetch_uuids():
    while True:
        try:
            resp = urllib2.urlopen(url_habitat_uuids % 10).read()
            data = json.loads(resp)
        except urllib2.HTTPError, e:
            print("Unable to fetch uuids. Retrying in 10 seconds...");
            time.sleep(10)
            continue

        print("Received a set of uuids.")
        uuids.extend(data['uuids'])
        break;


def init_callsign():
    doc = {
            'type': 'listener_information',
            'time_created' : ISOStringNow(),
            'data': { 'callsign': callsign }
            }

    while True:
        try:
            resp = postData(doc)
            print("Callsign initialized.")
            break;
        except urllib2.HTTPError, e:
            print("Unable initialize callsign. Retrying in 10 seconds...");
            time.sleep(10)
            continue

def uploadPosition():
    # initialize call sign (one time only)
    global callsign_init
    if not callsign_init:
        init_callsign()
        callsign_init = True

    doc = {
        'type': 'listener_telemetry',
        'time_created': ISOStringNow(),
        'data': {
            'callsign': callsign,
            'chase': True,
            'latitude': lat,
            'longitude': lon,
            'altitude': alt,
            'speed': speed,
        }
    }

    # post position to habitat
    try:
        postData(doc)
    except urllib2.HTTPError, e:
        print("Unable to upload data!")
        return

    print("Uploaded Data at: %s" % ISOStringNow())


def uploadNow():
    if position_valid:
        try:
            uploadPosition()
        except:
            pass

# Start UDP Listener Thread
serial_running = True

lastUploadTime = time.time()



## Start Qt event loop unless running in interactive mode or using pyside.
if __name__ == '__main__':

    try:
        ser = serial.Serial(port=serial_port,baudrate=serial_baud,timeout=5)
    except Exception as e:
        print("Serial Port Error: %s" % e)
        sys.exit(1)

    while serial_running:
        data = ser.readline()
        try:
            parseNMEA(data)
        except Exception as e:
            print str(e)
            print "Failed to Parse NMEA: " + data

        if (time.time() - lastUploadTime)>update_rate:
            uploadNow()
            lastUploadTime = time.time()

    ser.close()

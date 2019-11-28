#!/usr/bin/env python2

import json
import optparse
import os
import sys
import time
import urllib2
# import xml.etree.ElementTree as ET

VERSION = "0.1"

OK = 0
WARNING = 1
CRITICAL = 2
UNKNOWN = 3

GREEN = '#2A9A3D'
RED = '#FF0000'
ORANGE = '#f57700'
GRAY = '#f57700'

parser = optparse.OptionParser("%prog [options]", version="%prog " + VERSION)
parser.add_option('-H', '--hostname', dest="hostname", help='Hostname to connect to')
parser.add_option('-p', '--port', dest="port", type="int", default=80, help='Flemzerd port (default: 80)')
parser.add_option('-S', '--use-ssl', dest="https", type="int", default=0,  help='Use SSL')
parser.add_option('-t', '--token', dest="token", default="",  help='Plex token')

perfdata = []
output = ""

def add_perfdata(name, value, min="", max="", warning="", critical=""):
    global perfdata
    perfdata.append("\"%s\"=%s;%s;%s;%s;%s" % (name.replace(" ", "_"), value, min, max, warning, critical))

def exit(status, exit_label=""):
    global perfdata
    global output

    label = exit_label
    color = GRAY

    if status == OK:
        if not label:
            label = "OK"
        color = GREEN
    elif status == WARNING:
        if not label:
            label = "WARNING"
        color = ORANGE
    elif status == CRITICAL:
        if not label:
            label = "CRITICAL"
        color = RED
    else:
        if not label:
            label = "UNKNOWN"
        color = GRAY

    print "<span style=\"color:%s;font-weight: bold;\">[%s]</span> %s | %s" % (color, label, output, " ".join(perfdata))
    sys.exit(status)


def api_call(hostname, port, https, token, path):
    global output

    if https == 1:
        host = "https://%s:%d" % (hostname, port)
    else:
        host = "http://%s:%d" % (hostname, port)

    url = "%s%s" % (host, "%s" % (path))

    try:
        start = time.time()
        # req = urllib2.urlopen(url)
        req = urllib2.urlopen(urllib2.Request(url=url, headers = {
            'Accept': 'application/json',
            'X-Plex-Token': token,
            }))
        end = time.time()

        data = req.read()
        return end - start, data
    except urllib2.URLError as e:
        output += "Could not contact plex: %s" % e
        exit(CRITICAL)

def get_section(hostname, port, https, token, section_id):
    resp_time, data = api_call(hostname, port, https, token, "/library/sections/%s/all" % section_id)
    return json.loads(data)

def get_sections(hostname, port, https, token):
    resp_time, data = api_call(hostname, port, https, token, "/library/sections")
    sections = json.loads(data)
    libraries = {
            "movie": [],
            "show": [],
            }
    for lib in sections.get("MediaContainer").get("Directory"):
        if lib.get("type") == "movie":
            libraries["movie"].append(lib)
        if lib.get("type") == "show":
            libraries["show"].append(lib)

    return libraries

def get_sessions(hostname, port, https, token):
    resp_time, data = api_call(hostname, port, https, token, "/status/sessions")
    sessions = json.loads(data)
    return sessions.get("MediaContainer").get("Metadata")

def get_duration_by_user(stats):
    users = stats.get("MediaContainer").get("Account")
    if not users:
        return None

    plays_by_user = [{
        "user": user,
        "all_plays": filter(lambda elt: elt.get("accountID") == user.get("id"), [e for e in stats.get("MediaContainer").get("StatisticsMedia")])
        } for user in users]

    durations = []
    for item in plays_by_user:
        durations.append({
            "user": item.get("user"),
            "duration": sum([e.get("duration") for e in item.get("all_plays")])
            })

    return durations

def get_duration_by_device(stats):
    devices = stats.get("MediaContainer").get("Device")
    if not devices:
        return None

    plays_by_device = [{
        "device": device,
        "all_plays": filter(lambda elt: elt.get("deviceID") == device.get("id"), [e for e in stats.get("MediaContainer").get("StatisticsMedia")])
        } for device in devices]

    durations = []
    for item in plays_by_device:
        durations.append({
            "device": item.get("device"),
            "duration": sum([e.get("duration") for e in item.get("all_plays")])
            })

    return durations

def get_duration_by_platform(stats):
    durations = get_duration_by_device(stats)
    if not durations:
        return None

    durations_by_platform = {}
    for d in durations:
        platform = d.get("device").get("platform")
        if not durations_by_platform.get(platform):
            durations_by_platform[platform] = 0

        durations_by_platform[platform] += d.get("duration")

    return durations_by_platform

def get_play_stats(hostname, port, https, token, timestamp):
    resp_time, data = api_call(hostname, port, https, token, "/statistics/media?at>=%d" % timestamp)
    stats = json.loads(data)

    play_durations_by_users = get_duration_by_user(stats)
    play_durations_by_device = get_duration_by_device(stats)
    play_durations_by_platform = get_duration_by_platform(stats)

    return play_durations_by_users, play_durations_by_device, play_durations_by_platform

def add_stats_perfdata(hostname, port, https, token, label, timestamp):
    by_user, by_device, by_platform = get_play_stats(hostname, port, https, token, timestamp)
    if by_user:
        for s in by_user:
            user = s.get("user").get("name").split("@")[0]
            add_perfdata("play_by_user_%s_%s" % (label, user), s.get("duration"))

    if by_device:
        for d in by_device:
            device = d.get("device").get("name")
            add_perfdata("play_by_device_%s_%s" % (label, device), d.get("duration"))

    if by_platform:
        for p in by_platform:
            add_perfdata("play_by_platform_%s_%s" % (label, p), by_platform[p])

def get_stats(hostname, port, https, token):
    global output

    resp_time, _ = api_call(hostname, port, https, token, "/")
    sections = get_sections(hostname, port, https, token)
    add_perfdata("libraries", len(sections["movie"]) + len(sections["show"]))

    show_count = 0
    episodes_count = 0
    movie_count = 0

    for s in sections["movie"]:
        section = get_section(hostname, port, https, token, s.get("key"))
        movie_count += len(section.get("MediaContainer").get("Metadata"))
    add_perfdata("movies", movie_count)

    for s in sections["show"]:
        section = get_section(hostname, port, https, token, s.get("key"))
        show_count += len(section.get("MediaContainer").get("Metadata"))
        episodes = [x.get("leafCount") for x in section.get("MediaContainer").get("Metadata")]
        episodes_count += sum(episodes)
    add_perfdata("shows", show_count)
    add_perfdata("episodes", episodes_count)

    sessions = get_sessions(hostname, port, https, token)
    inactive_sessions_counter = 0
    active_sessions_counter = 0
    transcode_sessions = 0
    directplay_sessions = 0

    if sessions:
        for session in sessions:
            if session.get("Player"):
                if session.get("Player").get("state") == "playing":
                    active_sessions_counter += 1
                else:
                    inactive_sessions_counter += 1
            if session.get("TranscodeSession"):
                if session.get("TranscodeSession").get("videoDecision") == "transcode":
                    transcode_sessions += 1
                else:
                    directplay_sessions += 1

    add_perfdata("session_total", active_sessions_counter + inactive_sessions_counter)
    add_perfdata("session_active", active_sessions_counter)
    add_perfdata("session_inactive", inactive_sessions_counter)
    add_perfdata("transcode_sessions", transcode_sessions)
    add_perfdata("directplay_sessions", directplay_sessions)

    add_perfdata("response_time", resp_time)


    # Play stats for last hour
    add_stats_perfdata(hostname, port, https, token, "hour", int(time.time()) - 60*60)
    # Play stats for today
    add_stats_perfdata(hostname, port, https, token, "today", int(time.time()) - 60*60*24)
    # Play stats for the last week
    add_stats_perfdata(hostname, port, https, token, "week", int(time.time()) - 60*60*24*7)
    # Play stats for the all time
    add_stats_perfdata(hostname, port, https, token, "all_time", 0)

    output = "Plex stats collected"
    exit(OK)

if __name__ == '__main__':
    # Ok first job : parse args
    opts, args = parser.parse_args()
    if args:
        parser.error("Does not accept any argument.")

    port = opts.port
    hostname = opts.hostname
    token = opts.token
    if not hostname:
        # print "<span style=\"color:#A9A9A9;font-weight: bold;\">[ERROR]</span> Hostname parameter (-H) is mandatory"
        output = "Hostname parameter (-H) is mandatory"
        exit(CRITICAL, "ERROR")

    if not token:
        # print "<span style=\"color:#A9A9A9;font-weight: bold;\">[ERROR]</span> Hostname parameter (-H) is mandatory"
        output = "Token parameter (-t) is mandatory"
        exit(CRITICAL, "ERROR")

    get_stats(hostname, port, opts.https, token)

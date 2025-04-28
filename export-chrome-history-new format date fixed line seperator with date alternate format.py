#!/usr/bin/env python

# export-chrome-history
#
# A script to convert Google Chrome's history file to the standard HTML-ish
# bookmarks file format.
#
# Copyright (c) 2011, 2017-2018 Benjamin D. Esham. This program is released under the
# ISC license, which you can find in the file LICENSE.md.

from __future__ import print_function
import argparse
from os import environ
from os.path import expanduser, join
from platform import system
from shutil import copy, rmtree
import sqlite3
from sys import argv, stderr
from tempfile import mkdtemp
import json
from jinja2 import Template
from datetime import datetime, timedelta, timezone

script_version = "2.0.2"

html_escape_table = {
    "&": "&amp;",
    '"': "&quot;",
    "'": "&#39;",
    ">": "&gt;",
    "<": "&lt;",
}

def html_escape(text):
    return ''.join(html_escape_table.get(c, c) for c in text)

def sanitize(string):
    res = ''
    string = html_escape(string)

    for i in range(len(string)):
        if ord(string[i]) > 127:
            res += '&#x{:x};'.format(ord(string[i]))
        else:
            res += string[i]

    return res

def convert_timestamp(microseconds):
    # Chrome's timestamp starts from January 1, 1601
    start_date = datetime(1601, 1, 1, tzinfo=timezone.utc)
    # Convert microseconds to a timedelta
    delta = timedelta(microseconds=microseconds)
    # Add the timedelta to the start date
    utc_time = start_date + delta
    # Convert UTC time to local time
    local_time = utc_time.astimezone()
    return local_time.strftime('%Y-%m-%d %H:%M:%S %Z')

def get_date(microseconds):
    start_date = datetime(1601, 1, 1, tzinfo=timezone.utc)
    delta = timedelta(microseconds=microseconds)
    utc_time = start_date + delta
    local_time = utc_time.astimezone()
    return local_time.strftime('%B %d %Y')

# HTML template content
template_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Bookmarks</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #f4f4f4;
            color: #333;
            margin: 0;
            padding: 20px;
        }

        h1 {
            color: #333;
            margin-top: 0;
            padding-bottom: 20px;
            border-bottom: 1px solid #ccc;
        }

        .date-separator {
            font-size: 24px;
            margin: 20px 0;
            padding: 10px;
            background-color: #e0e0e0;
            border-radius: 5px;
            text-align: center;
        }

        .bookmark {
            margin-bottom: 20px;
            padding: 10px;
            background-color: #fff;
            border-radius: 5px;
            box-shadow: 0 0 5px rgba(0,0,0,0.1);
        }

        .bookmark h3 {
            font-size: 18px;
            margin-bottom: 5px;
            color: #333;
        }

        .bookmark p {
            font-size: 14px;
            margin-bottom: 10px;
            color: #666;
        }

        .bookmark .url a {
            font-size: 12px;
            color: #C5E0C0;  /* Change URL color */
            text-decoration: none;
        }

        .bookmark .url a:hover {
            text-decoration: underline;
        }

        .bookmark .time, .bookmark .counts {
            font-size: 12px;
            color: #999999;
        }
    </style>
</head>
<body>
    <h1>Bookmarks</h1>
    {% for date, bookmarks in grouped_bookmarks.items() %}
        <div class="date-separator">{{ date }}</div>
        {% for bookmark in bookmarks %}
            <div class="bookmark">
                <h3>{{ bookmark.title|safe }}</h3>
                <p class="url"><a href="{{ bookmark.url }}" target="_blank">{{ bookmark.url }}</a></p>
                <p class="time">Last Visit: {{ bookmark.lastVisitTime }} (Timestamp: {{ bookmark.lastVisitTimeTimestamp }})</p>
                <p class="counts">Typed Count: {{ bookmark.typedCount }}, Visit Count: {{ bookmark.visitCount }}</p>
            </div>
        {% endfor %}
    {% endfor %}
</body>
</html>
"""

# Parse the command-line arguments
parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
    description="Convert Google Chrome's history file to the standard HTML-based format.",
    epilog="(c) 2011, 2017-2018 Benjamin D. Esham\nhttps://github.com/bdesham/chrome-export")
parser.add_argument("input_file", nargs="?",
    help="The location of the Chrome history file to read. If this is omitted then the script will look for the file in Chrome's default location.")
parser.add_argument("output_file", type=argparse.FileType('w'),
    help="The location where the HTML bookmarks file will be written.")
parser.add_argument("-v", "--version", action="version",
    version="export-chrome-history {}".format(script_version))

args = parser.parse_args()

# Determine where the input file is
if args.input_file:
    input_filename = args.input_file
else:
    if system() == "Darwin":
        input_filename = expanduser("~/Library/Application Support/Google/Chrome/Default/History")
    elif system() == "Linux":
        input_filename = expanduser("~/.config/google-chrome/Default/History")
    elif system() == "Windows":
        input_filename = environ["LOCALAPPDATA"] + r"\Google\Chrome\User Data\Default\History"
    else:
        print('Your system ("{}") is not recognized. Please specify the input file manually.'.format(system()))
        exit(1)

    try:
        input_file = open(input_filename, 'r')
    except IOError as e:
        if e.errno == 2:
            print("The history file could not be found in its default location ({}). ".format(e.filename) +
                  "Please specify the input file manually.")
            exit(1)
    else:
        input_file.close()

# Make a copy of the database, open it, process its contents, and write the
# output file
temp_dir = mkdtemp(prefix='export-chrome-history-')
copied_file = join(temp_dir, 'History')
copy(input_filename, copied_file)

try:
    connection = sqlite3.connect(copied_file)
except sqlite3.OperationalError:
    print('The file "{}" could not be opened for reading.'.format(input_filename))
    rmtree(temp_dir)
    exit(1)

curs = connection.cursor()

try:
    curs.execute("SELECT id, last_visit_time, title, url, typed_count, visit_count FROM urls ORDER BY last_visit_time DESC")
except sqlite3.OperationalError:
    print('There was an error reading data from the file "{}".'.format(args.input_file))
    rmtree(temp_dir)
    exit(1)

bookmarks = []
for row in curs:
    if len(row[2]) > 0:  # Ensure title is not empty
        bookmark = {
            'id': row[0],
            'title': f'<a href="{sanitize(row[3])}" target="_blank">{sanitize(row[2])}</a>',
            'url': sanitize(row[3]),
            'lastVisitTime': convert_timestamp(row[1]),
            'lastVisitTimeTimestamp': row[1],
            'typedCount': row[4],
            'visitCount': row[5]
        }
        bookmarks.append(bookmark)

connection.close()
rmtree(temp_dir)

# Group bookmarks by date
grouped_bookmarks = {}
for bookmark in bookmarks:
    date = get_date(bookmark['lastVisitTimeTimestamp'])
    if date not in grouped_bookmarks:
        grouped_bookmarks[date] = []
    grouped_bookmarks[date].append(bookmark)

# Create a Jinja2 template object
template = Template(template_content)

# Render the template with the grouped bookmark data
rendered_html = template.render(grouped_bookmarks=grouped_bookmarks)

# Write the rendered HTML to the output file
args.output_file.write(rendered_html)
args.output_file.close()

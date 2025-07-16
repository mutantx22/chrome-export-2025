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
    return local_time.strftime('%Y-%m-%d') + '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;' + local_time.strftime('%H:%M:%S')

def get_date(microseconds):
    start_date = datetime(1601, 1, 1, tzinfo=timezone.utc)
    delta = timedelta(microseconds=microseconds)
    utc_time = start_date + delta
    local_time = utc_time.astimezone()
    return local_time.strftime('%B %d %Y')

# HTML template content
template_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Firefox History</title>
    <style>
	
        a.title-link {
            text-decoration: none;
            color: inherit;
        }
	
        td.url {
            word-break: break-all;
            white-space: pre-wrap;
            max-width: 500px;        /* Optional: limit column width */
        }
		
		h2 {
            margin: 0;
            padding: 6px;
            background: #eee;
            border-top: 2px solid #ccc;
            font-size: 2.1em;
			color:  #ff5733 
        }
    </style>
</head>
<body>
    <h1>Firefox History Report</h1>
    <table border="1" cellspacing="0" cellpadding="5">
        <thead>
            <tr>
                <th>Title</th>
                <th>URL</th>
                <th>Time</th>
            </tr>
        </thead>
        <tbody>
            {% for row in rows %}
                {% if row.date_separator is defined %}
                    <tr><td colspan="3"><h2>{{ row.date_separator }}</h2></td></tr>
                {% else %}
                    <tr>
                        <td class="url"><a href="{{ row.url }}" class="title-link">{{ row.title }}</a></td>
                        <td class="url"><a href="{{ row.url }}">{{ row.url }}</a></td>
                        <td>{{ row.time }}</td>
                    </tr>
                {% endif %}
            {% endfor %}
        </tbody>
    </table>
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
            'title': sanitize(row[2]),
            'url': sanitize(row[3]),
            'lastVisitTime': convert_timestamp(row[1]),
            'lastVisitTimeTimestamp': row[1],
            'typedCount': row[4],
            'visitCount': row[5]
        }
        bookmarks.append(bookmark)



rows = []
previous_date = None

for bookmark in bookmarks:
    date_str = get_date(bookmark['lastVisitTimeTimestamp'])  # already in microseconds
    if date_str != previous_date:
        rows.append({"date_separator": date_str})
        previous_date = date_str

    rows.append({
        "title": bookmark['title'],
        "url": bookmark['url'],
        "time": bookmark['lastVisitTime']
    })



# Create a Jinja2 template object
template = Template(template_content)

# Render the template with the grouped bookmark data
template = Template(template_content)
rendered_html = template.render(rows=rows)

# Write the rendered HTML to the output file
args.output_file.write(rendered_html)
args.output_file.close()


connection.close()
rmtree(temp_dir)
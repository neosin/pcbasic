#!/usr/bin/env python
""" PC-BASIC test diagnostics

(c) 2019 Rob Hagemans
This file is released under the GNU GPL version 3 or later.
"""

from __future__ import print_function

import os
import sys
import subprocess
import difflib

try:
    from colorama import init
    init()
except ImportError:
    # only needed on Windows
    # without it we still work but look a bit garbled
    pass


HERE = os.path.dirname(os.path.abspath(__file__))
TESTNAME = sys.argv[1]

if TESTNAME.endswith('/'):
    TESTNAME = TESTNAME[:-1]

# e.g. basic/gwbasic/TestName
try:
    DIR, TESTNAME = os.path.split(TESTNAME)
    _, PRESET = os.path.split(DIR)
except ValueError:
    PRESET = 'gwbasic'

PATH = os.path.join(HERE, 'basic', PRESET, TESTNAME)
MODEL = os.path.join(PATH, 'model')
OUTPUT = os.path.join(PATH, 'output')


def count_diff(file1, file2):
    lines1 = open(file1, 'rb').readlines()
    lines2 = open(file2, 'rb').readlines()
    n = len(lines1)
    count = 0
    for one, two in zip(lines1, lines2):
        if one != two:
            count += 1
    return n, count

for failname in os.listdir(MODEL):
    try:
        n, count = count_diff(
            os.path.join(OUTPUT, failname), os.path.join(MODEL, failname)
        )
        pct = 100.*count/float(n) if n != 0 else 0
        print('    %s: %d lines, %d differences (%3.2f %%)' % (failname, n, count, pct))
    except EnvironmentError as e:
        print('    %s: %s' % (failname, e))

for name in os.listdir(MODEL):
    print()
    print(name, '-'*80)
    with open(os.path.join(OUTPUT, name)) as output:
        outlines = output.readlines()
    with open(os.path.join(MODEL, name)) as model:
        modlines = model.readlines()
    for line in difflib.unified_diff(outlines, modlines, 'output', 'model', n=10):
        if line.startswith('+'):
            print('\033[0;32m', end='')
        elif line.startswith('-'):
            print('\033[0;31m', end='')
        elif not line.startswith('@'):
            print('\033[0;36m', end='')
        print(line.encode('unicode_escape').decode('ascii'), end='')
        print('\033[0m')

#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Runs every tests/test_*.py headless (SDL_VIDEODRIVER=dummy), one process each,
prints pass/fail + time per test and a summary; the last lines of a failing
test's output are shown. Exit code 1 if any failed.

.venv/bin/python tests/run_all.py [name-filter ...]
e.g.  tests/run_all.py            all
      tests/run_all.py kiez lasten  only tests whose file name contains one of them
"""

import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TIMEOUT_SECONDS = 900

filters = sys.argv[1:]
tests = sorted(glob.glob(os.path.join(HERE, "test_*.py")))
if filters:
    tests = [t for t in tests if any(f in os.path.basename(t) for f in filters)]
env = dict(os.environ, SDL_VIDEODRIVER="dummy")

failed = []
start = time.time()
for i, path in enumerate(tests, 1):
    name = os.path.basename(path)
    t0 = time.time()
    try:
        proc = subprocess.run([sys.executable, path], cwd=REPO, env=env, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
        ok, output = proc.returncode == 0, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as e:
        ok, output = False, f"{e.stdout or ''}{e.stderr or ''}\nTIMEOUT after {TIMEOUT_SECONDS} s"
    print(f"[{i}/{len(tests)}] {'ok  ' if ok else 'FAIL'} {name} ({time.time() - t0:.0f} s)", flush=True)
    if not ok:
        failed.append(name)
        print("    " + "\n    ".join(output.strip().splitlines()[-15:]), flush=True)

print(f"\n{len(tests) - len(failed)}/{len(tests)} passed in {time.time() - start:.0f} s" + (f", FAILED: {', '.join(failed)}" if failed else ""), flush=True)
sys.exit(1 if failed else 0)

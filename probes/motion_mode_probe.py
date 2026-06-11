#!/usr/bin/env python3
"""Read-only: print the robot's current motion mode (MotionSwitcher.CheckMode).

This reveals the mode name that the remote's "walk-run" activates, which the
portal must SelectMode() to enable walking/gestures from the web. Safe; reads only.

    ~/miniconda3/envs/tv/bin/python motion_mode_probe.py eth0

Run it twice and compare:
  (a) now (whatever state the robot is in)
  (b) AFTER switching to walk-run on the remote controller
The result['name'] in (b) is the mode the web needs to select.
"""
import sys

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient

iface = sys.argv[1] if len(sys.argv) > 1 else "eth0"
ChannelFactoryInitialize(0, iface)

msc = MotionSwitcherClient()
msc.SetTimeout(5.0)
msc.Init()

code, result = msc.CheckMode()
print(f"[probe] CheckMode code={code} result={result}")
print("[probe] result['name'] is the active motion mode; empty means none/debug.")

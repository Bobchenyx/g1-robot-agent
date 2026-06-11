#!/usr/bin/env python3
"""Read-only snapshot of the G1's full control state, to learn what the remote's
'walk-run' actually sets so the portal can reproduce it. Safe; reads only.

    ~/miniconda3/envs/tv/bin/python full_state_probe.py eth0

Run it in two states and compare:
  (a) damp / idle
  (b) AFTER switching to walk-run (the one that can WALK) on the remote
The difference (fsm_id / fsm_mode / balance_mode / form) is what to reproduce.
"""
import json
import sys

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient

GET_FSM_ID = 7001
GET_FSM_MODE = 7002
GET_BALANCE_MODE = 7003
GET_STAND_HEIGHT = 7005

iface = sys.argv[1] if len(sys.argv) > 1 else "eth0"
ChannelFactoryInitialize(0, iface)

msc = MotionSwitcherClient(); msc.SetTimeout(5.0); msc.Init()
loco = LocoClient(); loco.SetTimeout(5.0); loco.Init()


def call(api):
    code, data = loco._Call(api, "")
    try:
        return code, json.loads(data).get("data")
    except Exception:
        return code, data


print("[probe] motion mode :", msc.CheckMode())
print("[probe] fsm_id       :", call(GET_FSM_ID))
print("[probe] fsm_mode     :", call(GET_FSM_MODE))
print("[probe] balance_mode :", call(GET_BALANCE_MODE))
print("[probe] stand_height :", call(GET_STAND_HEIGHT))

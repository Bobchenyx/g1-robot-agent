#!/usr/bin/env python3
"""Diagnostic: can the SDK actually drive the G1 loco FSM?

Reads the real loco FSM id (GET_FSM_ID api 7001) before/after SetFsmId, instead
of the unrelated low-level mode_machine. ROBOT MUST BE SUSPENDED on a gantry.

    ~/miniconda3/envs/tv/bin/python loco_probe.py eth0
"""
import json
import sys
import time

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
from unitree_sdk2py.g1.loco.g1_loco_api import ROBOT_API_ID_LOCO_GET_FSM_ID, ROBOT_API_ID_LOCO_GET_FSM_MODE

iface = sys.argv[1] if len(sys.argv) > 1 else "eth0"
ChannelFactoryInitialize(0, iface)

st = {"mm": None}
sub = ChannelSubscriber("rt/lowstate", LowState_)
sub.Init(lambda m: st.update(mm=int(m.mode_machine)), 10)

loco = LocoClient()
loco.SetTimeout(5.0)
loco.Init()
time.sleep(1.0)


def read(api_id):
    code, data = loco._Call(api_id, "")
    val = None
    try:
        val = json.loads(data).get("data")
    except Exception:
        val = data
    return code, val


def snapshot(tag):
    c1, fsm = read(ROBOT_API_ID_LOCO_GET_FSM_ID)
    c2, mode = read(ROBOT_API_ID_LOCO_GET_FSM_MODE)
    print(f"[{tag}] loco_fsm_id=(code{c1}){fsm}  loco_fsm_mode=(code{c2}){mode}  low.mode_machine={st['mm']}")


snapshot("before")
print(f"[probe] SetFsmId(1)=Damp -> code={loco.SetFsmId(1)}")
time.sleep(2.0)
snapshot("after-damp")
print("[probe] If loco_fsm_id did NOT change to 1 despite code 0, the robot is")
print("[probe] not in an operational state that runs the loco FSM (needs remote startup).")

#!/usr/bin/env python3
"""Interactive, step-by-step probe to find the safe damp -> walk-run startup
sequence for this G1, reading the REAL fsm id from rt/sportmodestate (the one
arm gestures require: must be in {500,501,801}).

SAFETY: this will make the robot STAND UP. Feet on ground, gantry as fall-arrest,
hardware E-stop in hand. Each step waits for Enter; Ctrl+C aborts.

    ~/miniconda3/envs/tv/bin/python startup_probe.py eth0
"""
import sys
import time

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
from unitree_sdk2py.g1.loco.g1_loco_api import ROBOT_API_ID_LOCO_GET_FSM_ID

# sportmodestate carries the operational fsm id that gestures check.
try:
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_
except Exception:
    SportModeState_ = None

iface = sys.argv[1] if len(sys.argv) > 1 else "eth0"
ChannelFactoryInitialize(0, iface)

sport = {"mode": None}
if SportModeState_ is not None:
    try:
        sub = ChannelSubscriber("rt/sportmodestate", SportModeState_)
        sub.Init(lambda m: sport.__setitem__("mode", getattr(m, "mode", None)), 10)
    except Exception as e:
        print(f"[probe] could not subscribe sportmodestate: {e}")

loco = LocoClient()
loco.SetTimeout(10.0)
loco.Init()
time.sleep(1.0)


def show(tag):
    import json
    code, data = loco._Call(ROBOT_API_ID_LOCO_GET_FSM_ID, "")
    loco_fsm = None
    try:
        loco_fsm = json.loads(data).get("data")
    except Exception:
        pass
    print(f"  [{tag}] loco_fsm(GET_FSM_ID)={loco_fsm}   sportmode.mode={sport['mode']}")


def step(prompt, fsm_id):
    print(f"\n>>> NEXT: SetFsmId({fsm_id})  -- {prompt}")
    input("    Robot WILL move. Hand on E-stop. Press Enter to send (Ctrl+C to abort)...")
    code = loco.SetFsmId(fsm_id)
    print(f"    SetFsmId({fsm_id}) -> code={code}")
    time.sleep(2.5)
    show("after")


print("== initial state ==")
show("init")
# Candidate startup sequence (C++ convention): damp -> stand/get-ready(4) -> main(500)
step("get-ready / lock stand", 4)
step("main control (walk-run; gestures enabled)", 500)
print("\n[probe] Done. If sportmode.mode is now 500/501/801, gestures+walk are enabled.")
print("[probe] To sit back down safely: re-run and use damp, or use the remote.")

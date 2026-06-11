#!/usr/bin/env python3
"""Read-only probe to locate a battery/SOC source on the G1 over DDS.

Safe: only subscribes and prints, never commands the robot.

    ~/miniconda3/envs/tv/bin/python battery_probe.py eth0
"""
import sys
import time

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_ as HGLowState

iface = sys.argv[1] if len(sys.argv) > 1 else "eth0"
ChannelFactoryInitialize(0, iface)

latest = {}
latest_hg = ChannelSubscriber("rt/lowstate", HGLowState)
latest_hg.Init(lambda m: latest.__setitem__("hg", m), 10)

# Some firmwares publish a Go-style BmsState on a dedicated topic. Try a few
# candidate names with the Go BmsState type (separate topics -> no type clash).
bms_hits = {}
bms_subs = []
try:
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import BmsState_ as GoBms

    def mk(t):
        return lambda m: bms_hits.__setitem__(t, getattr(m, "soc", "no-soc"))

    for t in ["rt/bmsstate", "rt/lf/bmsstate", "rt/bms_state"]:
        try:
            s = ChannelSubscriber(t, GoBms)
            s.Init(mk(t), 10)
            bms_subs.append(s)
        except Exception as e:
            print(f"[probe] could not subscribe {t}: {e}")
except Exception as e:
    print(f"[probe] Go BmsState unavailable: {e}")

print("[probe] listening 6s...")
time.sleep(6)

hg = latest.get("hg")
if hg is None:
    print("[probe] NO rt/lowstate received - check iface / robot services")
else:
    print(f"[probe] hg LowState: mode_machine={hg.mode_machine} mode_pr={hg.mode_pr}")
    print(f"[probe] hg reserve={list(hg.reserve)}  version={list(hg.version)}")
    print("[probe] (if reserve is all zeros, battery is NOT in the G1 low state)")
print(f"[probe] candidate BMS topics with data: {bms_hits or 'none'}")

#!/usr/bin/env python3
"""Real Unitree G1 robot agent for the humanoid portal.

Connects to the portal WebSocket relay as a `g1_` edge (same protocol as the
mock), but dispatches /g1/* service calls to the real unitree_sdk2py clients.

SAFETY: motion is DISABLED by default. Without --enable-motion, locomotion and
arm-execute commands are acknowledged and logged but NOT sent to the robot.
Read-only calls (arm action list, telemetry heartbeat) always run.

Run on the robot (G1 onboard computer), e.g.:

    ~/miniconda3/envs/tv/bin/python agent.py \
        --url ws://192.168.10.93:18080/ws/client \
        --token "Bearer <edge-jwt>" \
        --device g1_v1_000001 --iface eth0
        # add --enable-motion ONLY when the robot is physically secured

The edge JWT is minted on the portal host:  python manage.py mint_edge_token g1_v1_000001
"""
import argparse
import asyncio
import json
import os
import urllib.parse

import websockets

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
from unitree_sdk2py.g1.loco.g1_loco_api import ROBOT_API_ID_LOCO_GET_FSM_ID
from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient, action_map


def read_loco_fsm_id(loco):
    """Real high-level loco FSM id (1=damp, 500=start, 2=squat, 3=sit, 4=standup,
    0=zero-torque). This is the meaningful state — NOT lowstate.mode_machine, which
    is an unrelated low-level value. G1 exposes no battery/SOC, so battery is N/A."""
    try:
        code, data = loco._Call(ROBOT_API_ID_LOCO_GET_FSM_ID, "")
        if code == 0:
            return json.loads(data).get("data")
    except Exception:
        pass
    return None


def build_loco_dispatch(loco):
    """Map portal service -> LocoClient call, using FSM ids VERIFIED on this G1
    by matching the remote controller's damp->ready->walk sequence:
      damp=1, get_ready/lock-stand=4, walk(control waist)=501, sit=3, squat=2,
      zero-torque=0. (Note: SetFsmId(500) does NOT enter walk on this firmware;
      501 is the operational walk state where move + arm gestures work.)
    SetFsmId returns the SDK code (unlike the Damp()/Start() helpers)."""
    return {
        "/g1/loco/damp": lambda: loco.SetFsmId(1),
        "/g1/loco/get_ready": lambda: loco.SetFsmId(4),
        "/g1/loco/walk": lambda: loco.SetFsmId(501),
        "/g1/loco/stop_move": loco.StopMove,
    }


def arm_action_list():
    """Real gesture catalog from the SDK action_map -> [{id, name}]."""
    return [{"id": int(v), "name": k} for k, v in action_map.items()]


async def run(args):
    print(f"[agent] init DDS on iface={args.iface}")
    ChannelFactoryInitialize(0, args.iface)
    loco = LocoClient()
    loco.SetTimeout(10.0)
    loco.Init()
    arm = G1ArmActionClient()
    # Arm gestures (wave/shake/hug...) take several seconds; the SDK call blocks
    # until the action completes, so a short timeout returns 3104 (RPC timeout)
    # even though the robot is executing. Give it ample time.
    try:
        arm.SetTimeout(15.0)
    except Exception:
        pass
    arm.Init()
    loco_dispatch = build_loco_dispatch(loco)
    motion = args.enable_motion

    uri = f"{args.url}?authorization={urllib.parse.quote(args.token)}"
    async with websockets.connect(uri) as ws:
        print(f"[agent] connected device={args.device} motion={'ON' if motion else 'OFF (safe)'}")

        async def telemetry():
            while True:
                await ws.send(json.dumps({
                    "op": "publish", "topic": "/device_state",
                    "device_id": args.device, "device_type": "g1",
                    # battery=None -> N/A (G1 SDK has no battery); status carries real loco FSM.
                    "msg": {"battery": None, "status": {"fsm_id": read_loco_fsm_id(loco)}},
                }))
                await asyncio.sleep(2)

        task = asyncio.create_task(telemetry())
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("op") != "call_service":
                    continue
                service = msg.get("service", "")
                a = msg.get("args") or {}
                values, ok, is_motion, code = {}, True, True, None
                try:
                    if service.endswith("/g1/arm/get_action_list"):
                        values = {"actions": arm_action_list()}              # read-only
                        is_motion = False
                    elif service.endswith("/g1/loco/move"):
                        if motion:
                            code = loco.Move(float(a.get("vx", 0)), float(a.get("vy", 0)), float(a.get("omega", 0)))
                    elif service.endswith("/g1/arm/execute_action"):
                        if motion and a.get("action_id") is not None:
                            code = arm.ExecuteAction(int(a["action_id"]))
                    elif service.endswith("/g1/arm/stop"):
                        if motion and "release arm" in action_map:
                            code = arm.ExecuteAction(action_map["release arm"])
                    elif service in loco_dispatch:
                        if motion:
                            code = loco_dispatch[service]()
                    else:
                        ok = False
                    # SDK Call() returns 0 on success. 3104 = RPC reply timeout:
                    # the long-running action (arm gesture) IS executing, the SDK
                    # just didn't get the completion ack in time -> treat as accepted.
                    if code is not None:
                        ok = code in (0, 3104)
                        values["code"] = code
                        if code == 3104:
                            values["note"] = "accepted (long action, ack timed out)"
                    label = "READ" if not is_motion else ("EXEC" if motion else "SAFE-skip")
                    print(f"[agent] {service} args={a} -> {label} sdk_code={code} ok={ok}")
                except Exception as e:  # never let one command kill the agent
                    ok = False
                    print(f"[agent] ERROR on {service}: {e}")
                await ws.send(json.dumps({
                    "op": "service_response", "service": service, "id": msg.get("id"),
                    "values": values, "result": ok, "extra": msg.get("extra", "{}"),
                }))
        finally:
            task.cancel()


def resolve_token(args):
    """Token precedence: --token > --token-file > $PORTAL_TOKEN."""
    if args.token:
        return args.token.strip()
    if args.token_file:
        with open(os.path.expanduser(args.token_file)) as f:
            return f.read().strip()
    env = os.environ.get('PORTAL_TOKEN')
    if env:
        return env.strip()
    raise SystemExit("No token: pass --token, --token-file, or set PORTAL_TOKEN")


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--url', default='ws://192.168.10.93:18080/ws/client')
    p.add_argument('--token', help='edge bearer token (mint_edge_token)')
    p.add_argument('--token-file', help='path to a file containing the bearer token')
    p.add_argument('--device', default='g1_v1_000001')
    p.add_argument('--iface', default='eth0', help='DDS network interface to the robot')
    p.add_argument('--enable-motion', action='store_true',
                   help='ACTUALLY move the robot. Only with the robot physically secured.')
    args = p.parse_args()
    args.token = resolve_token(args)
    asyncio.run(run(args))


if __name__ == '__main__':
    main()

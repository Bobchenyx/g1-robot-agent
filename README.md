# g1-robot-agent

On-robot agent that connects a Unitree G1 to the cloud **humanoid-portal** and
executes `/g1/*` control commands via `unitree_sdk2py`. It speaks the WebSocket
contract in `humanoid-portal/docs/protocol/`.

For the MVP this is a single Python process — **no ROS2 / rosbridge needed**.
(`agent.py` is the production sibling of the portal's `mock_edge`.)

```
[browser]  --WSS-->  [portal cloud relay]  --WS-->  agent.py  --DDS(eth0)-->  [G1]
```

## Repo layout

```
g1-robot-agent/
├── agent.py            # the production agent (portal /g1/* -> unitree_sdk2py)
├── probes/             # read-only G1 diagnostics (FSM / motion mode / battery) — see probes/README.md
└── ops/
    └── ip-report/      # boot-time reachability email side-car (Tailscale + Gmail) — see ops/ip-report/README.md
```

## Safety

- **Motion is OFF by default.** Without `--enable-motion`, locomotion and arm-execute
  commands are acknowledged + logged but **not** sent to the robot. Read-only calls
  (arm action list, telemetry) always run.
- Only pass `--enable-motion` with the robot **physically secured** (gantry/stand or
  clear area) and a **hardware E-stop in hand**. First motion test = `damp`.
- The portal enforces **one edge per device**: if a second agent connects with the
  same device id, the older one is force-disconnected (prevents double execution).

## One-time setup on the robot

The `tv` conda env already has `unitree_sdk2py` + `websockets`:

    PY=~/miniconda3/envs/tv/bin/python

Fix the clock if it drifted to the past (Jetson has no RTC battery; TLS / VS Code
break when the clock is wrong). From your Mac:

    ssh -t unitree@<robot-ip> "sudo date -u -s '$(date -u '+%Y-%m-%d %H:%M:%S')'"

## Deploy + run (safe mode)

On the **portal host** — mint a token and copy the agent:

    cd humanoid-portal
    docker-compose run --rm api python manage.py mint_edge_token g1_v1_000001   # prints "Bearer ..."
    scp ../g1-robot-agent/agent.py unitree@<robot-ip>:~/g1-robot-agent/agent.py

Store the token on the robot once (so restarts don't need re-pasting):

    ssh unitree@<robot-ip> "echo 'Bearer eyJ...' > ~/portal_token"

Run the agent (safe mode — robot will NOT move):

    ssh unitree@<robot-ip> "~/miniconda3/envs/tv/bin/python ~/g1-robot-agent/agent.py \
        --url ws://<portal-host>:18080/ws/client --token-file ~/portal_token \
        --device g1_v1_000001 --iface eth0"

`--iface eth0` is the DDS interface to the robot body (the `192.168.123.x` net).
Token resolution order: `--token` > `--token-file` > `$PORTAL_TOKEN`.

Verify in the browser: the device shows **Online** and the **Arm Gestures** list is
the robot's real catalog. Clicking buttons prints `... -> SAFE-skip` in the agent
terminal; the robot stays still.

## Enable motion (only when secured)

Re-run with `--enable-motion` added. Startup flow matches the remote controller:
click **DAMP / E-STOP** first (robot goes limp), then **Get Ready**, then **Walk Mode**;
move + arm gestures only work once in Walk (fsm 501).

## Mapping (portal service → unitree_sdk2py)

FSM ids were verified on this G1 by matching the remote's damp→ready→walk sequence.

| service | call |
|---|---|
| `/g1/loco/damp` | `SetFsmId(1)` — also the e-stop |
| `/g1/loco/get_ready` | `SetFsmId(4)` — lock stand |
| `/g1/loco/walk` | `SetFsmId(501)` — walk (control waist); enables move + gestures |
| `/g1/loco/stop_move` | `StopMove()` — halt walking, stay standing |
| `/g1/loco/move {vx,vy,omega}` | `Move(vx, vy, omega)` |
| `/g1/arm/get_action_list` | from `action_map` (read-only) |
| `/g1/arm/execute_action {action_id}` | `G1ArmActionClient.ExecuteAction(id)` |
| `/g1/arm/stop` | `ExecuteAction(action_map["release arm"])` |

Telemetry (`/device_state`, every 2s): real loco FSM via `GET_FSM_ID` (api 7001);
`battery: null` — this G1 firmware exposes no SOC over the SDK (see `probes/battery_probe.py`).

## Remote access (deployed robots)

`ops/ip-report/` emails the robot's reachable address (Tailscale, behind-NAT) on each
boot and on address change, so you can SSH in for diagnostics. See `ops/ip-report/README.md`.

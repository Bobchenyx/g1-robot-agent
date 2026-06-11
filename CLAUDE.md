# CLAUDE.md — g1-robot-agent

## What this is
On-robot Python agent that connects a **Unitree G1** to the cloud `humanoid-portal`
(sibling repo) over a WebSocket relay. It receives `/g1/*` service calls from the
portal and translates them into `unitree_sdk2py` client calls. For the MVP it is a
**single Python process** — no ROS2 / rosbridge. It is the production sibling of the
portal's `mock_edge` and speaks the contract in `humanoid-portal/docs/protocol/`.

## Architecture (one line)
`browser -> portal cloud relay (WS) -> agent.py -> DDS(eth0) -> G1`.
agent.py is the **only** G1-aware component; the portal knows nothing about DDS/SDK.

## Repo layout
- `agent.py` — the production agent (portal `/g1/*` -> `unitree_sdk2py`).
- `probes/` — **read-only** diagnostics (FSM / motion mode / battery discovery).
  `loco_probe.py` + `startup_probe.py` DO move the robot; the other three are pure reads.
  See `probes/README.md` for what they established.
- `ops/ip-report/` — boot-time reachability email side-car (Tailscale + Gmail SMTP via
  systemd). Independent of agent.py; uses system `python3` + stdlib only. See its README.

## Run / dev commands
- On-robot python (has `unitree_sdk2py` + `websockets`): `~/miniconda3/envs/tv/bin/python`.
- Run the agent:
  ```
  ~/miniconda3/envs/tv/bin/python agent.py \
    --url ws://<portal-host>:18080/ws/client --token-file ~/portal_token \
    --device g1_v1_000001 --iface eth0 [--enable-motion]
  ```
  Token precedence: `--token` > `--token-file` > `$PORTAL_TOKEN`. Mint on portal host:
  `python manage.py mint_edge_token g1_v1_000001`.
- Syntax check on a dev machine: `python -m py_compile agent.py`. You CANNOT import
  `unitree_sdk2py` off-robot, so that's the only check possible locally.

## CRITICAL gotchas (verified, hard-won — break these and you break hardware behavior)
- **Operational walk = FSM 501** ("walk / control waist"), NOT 500. `SetFsmId(500)`
  returns 0 but stays at fsm 4 — a dead end. Verified sequence: damp(1) ->
  get_ready/lock-stand(4) -> walk(501). Also: sit=3, squat=2, zero-torque=0.
- **Arm gestures only work in fsm {500,501,801}**; in damp they return 7404.
- `lowstate.mode_machine` (const 5) is **NOT** the loco FSM. Read the real FSM via
  `loco._Call(ROBOT_API_ID_LOCO_GET_FSM_ID=7001)` (see `read_loco_fsm_id`).
- Python `LocoClient.Damp()/Start()` return **None**; `SetFsmId()/Move()/_Call()`
  return the SDK code — use the latter to know success.
- **SDK code 3104 = RPC reply timeout on long arm actions, NOT failure** — the robot
  IS executing. Hence `arm.SetTimeout(15.0)` and treat both `0` and `3104` as ok.
- This G1 firmware exposes **no battery/SOC** over the SDK -> telemetry sends
  `battery: null` (N/A). Don't try to add a battery field; `battery_probe.py` confirmed it.
- **Motion is OFF by default.** Without `--enable-motion`, locomotion/arm-execute calls
  are ack'd + logged (`SAFE-skip`) but NOT sent. Only enable with the robot physically
  secured (gantry / feet down / hardware E-stop in hand).
- **Deployment constraint:** a human runs ALL robot-side commands manually
  (scp / agent start / probes). Claude/agents must **NOT** ssh/scp onto the live robot.
  Make edits locally; the user deploys.
- The Jetson has **no RTC battery** -> clock drifts to the past on boot and TLS breaks
  ("certificate not yet valid"). `ops/ip-report/report_ip.py` fixes the clock from a
  plaintext HTTP `Date` header BEFORE any TLS (no chicken-and-egg).

## Telemetry
agent.py publishes `/device_state` every **2s** with `battery: null` and
`status.fsm_id` (real FSM via `GET_FSM_ID`) plus `status.network`
`{tailscale_ip, lan_ip, public_ip}`. Network gathering blocks (public-IP HTTP lookup),
so it runs **off the event loop** in an executor and is **cached ~60s**.

## Conventions
- Never let one command kill the agent — service dispatch is wrapped in try/except and
  always sends a `service_response`.
- Secrets (`*.pem`, `ip-report.env`, `export_keys/`) are gitignored; keep them out of commits.

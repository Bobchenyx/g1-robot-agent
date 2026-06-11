# probes — read-only G1 diagnostics

Small standalone scripts used to discover and verify the G1's real control state
(FSM ids, motion mode, battery source). They're kept for when firmware changes or
the robot misbehaves — re-run them to re-confirm. All run in the conda `tv` env:

    PY=~/miniconda3/envs/tv/bin/python
    $PY probes/<name>.py eth0          # eth0 = DDS iface to the robot body

| Script | Reads | Moves robot? |
|---|---|---|
| `full_state_probe.py` | FSM id / fsm_mode / balance_mode / stand_height + motion mode. **The go-to snapshot.** | No |
| `motion_mode_probe.py` | Current motion mode name (`MotionSwitcher.CheckMode`). | No |
| `battery_probe.py` | Scans LowState + candidate BMS topics for any SOC. (Confirmed: this G1 firmware exposes none → battery is N/A.) | No |
| `loco_probe.py` | Drives `SetFsmId` and reads back the real FSM to prove SDK control works. | **Yes** — gantry it |
| `startup_probe.py` | Interactive damp → get-ready → walk sequence discovery. | **Yes** — stands up |

**Safety:** `loco_probe.py` and `startup_probe.py` command motion (they were how the
damp→get_ready(4)→walk(501) sequence was found). Run them only with the robot
physically secured (gantry as fall-arrest, feet down, hardware E-stop in hand).
The other three are pure reads.

## What they established (so you don't re-derive)

- Operational walk = **fsm 501** ("walk / control waist"), **not 500** (`SetFsmId(500)`
  returns 0 but stays at 4 — dead end).
- Remote sequence reproduced by the portal: damp(1) → get-ready/lock-stand(4) → walk(501).
- Arm gestures only work in fsm {500, 501, 801}; in damp they return 7404.
- `lowstate.mode_machine` (const 5) is **not** the loco FSM — read FSM via
  `loco._Call(GET_FSM_ID=7001)`.
- No battery/SOC over the SDK on this firmware → telemetry reports battery as N/A.

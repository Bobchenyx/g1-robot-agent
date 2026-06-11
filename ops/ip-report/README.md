# ip-report — boot-time reachability email (remote-SSH enabler)

Emails the G1's reachable addresses to a designated inbox **on every boot** and
**when the address changes**, so you can SSH in remotely to diagnose problems.

The actual remote-SSH path is **Tailscale** (a mesh VPN that traverses NAT). The
robot's *public* IP belongs to the router and is **not** directly SSH-able without
port forwarding — Tailscale gives every device a stable `100.x.y.z` address that
works from any network. This service just announces that address + confirms the
box is up; it's an independent side-car (does not touch `agent.py` or the portal).

## What's here

| File | Role |
|---|---|
| `report_ip.py` | The reporter. System `python3`, stdlib only. Waits for network → fixes clock → gathers addresses → sends via Gmail SMTP (on boot, or on change). |
| `ip-report.env.example` | Credentials template → deploy as `/etc/ip-report.env` (chmod 600). |
| `ip-report-boot.service` | systemd oneshot, runs `--always` after network is up → **boot email**. |
| `ip-report.service` + `ip-report.timer` | Every 30 min, send **only if the address changed** → covers IP drift. |

## Why the clock fix

The Jetson has no RTC battery, so on boot the clock drifts to the past and TLS to
Gmail fails with *"certificate is not yet valid"*. `report_ip.py` fixes the clock
**before** any TLS, using a plaintext HTTP `Date` header (no TLS, no chicken-and-egg).

## One-time setup (run on the robot)

```bash
# 1) Tailscale — joins your tailnet; its own systemd service auto-starts on boot
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                 # authorize once in the browser
                                  # (unattended fleets: use --authkey instead)

# 2) Copy these ops files from the Mac
scp -r g1-robot-agent/ops/ip-report unitree@<robot-ip>:~/g1-robot-agent/ops/

# 3) Credentials — Gmail needs an APP PASSWORD, not your login password
#    https://myaccount.google.com/apppasswords  (2FA must be enabled)
sudo cp ~/g1-robot-agent/ops/ip-report/ip-report.env.example /etc/ip-report.env
sudo nano /etc/ip-report.env      # fill SMTP_USER / SMTP_APP_PASSWORD
sudo chmod 600 /etc/ip-report.env

# 4) Install + enable the systemd units
sudo cp ~/g1-robot-agent/ops/ip-report/*.service \
        ~/g1-robot-agent/ops/ip-report/*.timer  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ip-report-boot.service   # sends one now (= boot effect)
sudo systemctl enable --now ip-report.timer          # starts the 30-min change check
```

> If you didn't clone the repo to `/home/unitree/g1-robot-agent`, edit the
> `ExecStart=` path in the two `.service` files to match.

## Verify

```bash
# Send path: should arrive at MAIL_TO within seconds, with a ready-to-paste ssh line
sudo systemctl start ip-report-boot.service
journalctl -u ip-report-boot --no-pager -n 30

# Clock fallback: break the clock, confirm it still sends (script repairs time first)
sudo date -s '2023-01-01'
sudo systemctl start ip-report-boot.service
timedatectl                        # time should be corrected again

# Change detection: without --always and address unchanged → "unchanged, skip"
sudo systemctl start ip-report.service
journalctl -u ip-report --no-pager -n 10

# Boot auto-start
sudo reboot                        # a fresh email should arrive after it comes up
```

Then add your Mac to the same tailnet and confirm `ssh unitree@100.x.y.z`
(from the email) works from an outside network — that's the end goal.

## Notes

- A device's Tailscale IP is basically **stable**, so the "on change" email mostly
  catches public-IP drift / re-auth; the **boot email** is the workhorse.
- Stores only a Gmail **app password** (individually revocable); `/etc/ip-report.env`
  is `600`, root-only, and **never committed** (`.gitignore`'d).
- Pure stdlib + base CLI tools → no pip install, no dependency on the conda `tv` env.

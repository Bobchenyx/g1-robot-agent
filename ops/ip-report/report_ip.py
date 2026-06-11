#!/usr/bin/env python3
"""Boot-time reachability reporter for the G1.

On each boot (and on address change) emails the robot's reachable addresses to a
designated inbox so an operator can SSH in remotely for diagnostics. The real
remote-SSH path is Tailscale (a mesh VPN that traverses NAT); this script just
announces the address + confirms the box is up.

Designed to run as a systemd system service (root), using ONLY the Python
standard library + a few base CLI tools (ip, curl, tailscale, date, timedatectl)
so it does not depend on the conda `tv` env being ready early in boot.

Modes:
    report_ip.py --always     # send unconditionally (boot service uses this)
    report_ip.py              # send only if the addresses changed (timer uses this)

Config comes from the environment (systemd EnvironmentFile=/etc/ip-report.env):
    SMTP_USER            Gmail address used to send (the SMTP login)
    SMTP_APP_PASSWORD    Gmail *app password* (not the account password)
    MAIL_TO              recipient (default: bobchenyx@gmail.com)
    MAIL_FROM            From header (default: SMTP_USER)
    SMTP_HOST            default smtp.gmail.com
    SMTP_PORT            default 587 (STARTTLS)

The Jetson has no RTC battery, so the clock drifts to the past on boot and TLS
to Gmail fails with "certificate is not yet valid". We therefore fix the clock
BEFORE any TLS, and the clock fix itself uses a plaintext HTTP Date header so it
never depends on TLS (no chicken-and-egg).
"""
import email.utils
import json
import os
import smtplib
import socket
import ssl
import subprocess
import sys
import time
from email.message import EmailMessage

STATE_FILE = "/var/lib/ip-report/last.json"
NET_WAIT_SECONDS = 300        # wait up to 5 min for the network on boot
SEND_RETRIES = 5


def log(msg):
    print(f"[ip-report] {msg}", flush=True)


def run(cmd, timeout=15):
    """Run a command, return stripped stdout or '' on any failure."""
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return out.stdout.strip()
    except Exception:
        return ""


# --- step 1: wait for the network -------------------------------------------

def wait_for_network():
    """Block until the box can reach the internet (plaintext HTTP), or give up."""
    deadline = time.monotonic() + NET_WAIT_SECONDS
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        if http_get("http://api.ipify.org") is not None:
            log(f"network up (attempt {attempt})")
            return True
        time.sleep(5)
    log("network NOT up within timeout — continuing best-effort")
    return False


def http_get(url, timeout=8):
    """Plaintext/standard HTTP GET via urllib; returns body text or None.

    Used for the public-IP lookup and the reachability probe. Kept TLS-agnostic
    for the http:// probe so it works before the clock is fixed."""
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read().decode().strip()
    except Exception:
        return None


# --- step 2: fix the clock (before any TLS) ---------------------------------

def fix_clock():
    """Ensure the system clock is sane before we attempt TLS to Gmail.

    First nudge systemd-timesyncd; if the year is still implausibly old, set the
    time from a plaintext HTTP Date header (no TLS needed)."""
    run(["timedatectl", "set-ntp", "true"])
    if _year_ok():
        log("clock looks sane")
        return
    # Grab the Date: header over plaintext HTTP and set the system clock from it.
    headers = run(["curl", "-sI", "--max-time", "10", "http://www.google.com"])
    http_date = ""
    for line in headers.splitlines():
        if line.lower().startswith("date:"):
            http_date = line.split(":", 1)[1].strip()
            break
    if http_date:
        try:
            dt = email.utils.parsedate_to_datetime(http_date)  # tz-aware UTC
            stamp = dt.strftime("%Y-%m-%d %H:%M:%S")
            run(["date", "-u", "-s", stamp])
            log(f"clock set from HTTP Date header -> {stamp} UTC")
        except Exception as e:
            log(f"could not parse HTTP Date '{http_date}': {e}")
    else:
        log("no HTTP Date header available; leaving clock as-is")


def _year_ok():
    out = run(["date", "-u", "+%Y"])
    try:
        return int(out) >= 2025
    except ValueError:
        return False


# --- step 3: gather addresses -----------------------------------------------

def gather():
    """Collect the addresses we care about into a dict."""
    return {
        "hostname": socket.gethostname(),
        "tailscale_ip": tailscale_ip(),
        "tailscale_host": tailscale_hostname(),
        "lan_ip": lan_ip(),
        "public_ip": http_get("http://api.ipify.org") or "",
    }


def tailscale_ip():
    return run(["tailscale", "ip", "-4"]).splitlines()[0] if run(["tailscale", "ip", "-4"]) else ""


def tailscale_hostname():
    raw = run(["tailscale", "status", "--json"])
    if not raw:
        return ""
    try:
        data = json.loads(raw)
        return (data.get("Self") or {}).get("DNSName", "").rstrip(".")
    except Exception:
        return ""


def lan_ip():
    """The LAN IP used for the default route (the box's address on its subnet)."""
    out = run(["ip", "route", "get", "1.1.1.1"])
    # e.g. "1.1.1.1 via 192.168.10.1 dev wlan0 src 192.168.10.144 uid 0"
    parts = out.split()
    if "src" in parts:
        return parts[parts.index("src") + 1]
    return ""


# --- step 4: change detection ------------------------------------------------

def load_last():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_last(addrs):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(addrs, f)
    except Exception as e:
        log(f"could not write state file: {e}")


def addresses_changed(addrs, last):
    keys = ("tailscale_ip", "lan_ip", "public_ip")
    return any(addrs.get(k) != last.get(k) for k in keys)


# --- step 5: send ------------------------------------------------------------

def uptime():
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
        return f"{int(secs // 3600)}h {int((secs % 3600) // 60)}m"
    except Exception:
        return "?"


def build_message(addrs):
    user = os.environ.get("SMTP_USER", "")
    msg = EmailMessage()
    msg["Subject"] = f"[G1] {addrs['hostname']} online — {addrs['tailscale_ip'] or addrs['lan_ip'] or 'no-ip'}"
    msg["From"] = os.environ.get("MAIL_FROM") or user
    msg["To"] = os.environ.get("MAIL_TO", "bobchenyx@gmail.com")

    ssh_target = addrs["tailscale_ip"] or addrs["tailscale_host"] or addrs["lan_ip"]
    body = [
        f"Robot '{addrs['hostname']}' booted / changed address.",
        f"Time (UTC): {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}",
        f"Uptime: {uptime()}",
        "",
        "Remote SSH (via Tailscale — works behind NAT):",
        f"    ssh unitree@{ssh_target}" if ssh_target else "    (no reachable address found)",
        "",
        "Addresses:",
        f"    Tailscale IP   : {addrs['tailscale_ip'] or '(tailscale not up)'}",
        f"    Tailscale host : {addrs['tailscale_host'] or '-'}",
        f"    LAN IP         : {addrs['lan_ip'] or '-'}",
        f"    Public IP      : {addrs['public_ip'] or '-'}  (router WAN; not directly SSH-able)",
    ]
    msg.set_content("\n".join(body))
    return msg


def send(msg):
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_APP_PASSWORD", "")
    if not user or not password:
        raise SystemExit("SMTP_USER / SMTP_APP_PASSWORD not set (see /etc/ip-report.env)")

    ctx = ssl.create_default_context()
    last_err = None
    for attempt in range(1, SEND_RETRIES + 1):
        try:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(user, password)
                s.send_message(msg)
            log(f"email sent to {msg['To']} (attempt {attempt})")
            return
        except Exception as e:
            last_err = e
            log(f"send attempt {attempt} failed: {e}")
            time.sleep(5 * attempt)
    raise SystemExit(f"giving up after {SEND_RETRIES} send attempts: {last_err}")


def main():
    always = "--always" in sys.argv[1:]

    wait_for_network()
    fix_clock()
    addrs = gather()
    log(f"addresses: {addrs}")

    last = load_last()
    if not always and not addresses_changed(addrs, last):
        log("addresses unchanged, skip (use --always to force)")
        return

    send(build_message(addrs))
    save_last(addrs)


if __name__ == "__main__":
    main()

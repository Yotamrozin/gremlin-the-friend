#!/usr/bin/env python3
"""Daily outside check for the gremlin: plain code, no AI.

A model can't reliably audit itself, so this script looks at the real state of things and messages
the owner on Signal only when something is wrong. Run by openclaw-check.timer every morning.
Usage: daily-check.py [--print]   (--print shows the report instead of sending it)
"""
import glob, json, os, re, subprocess, sys, time
from datetime import datetime, timedelta

HOME = os.path.expanduser("~")
WS = f"{HOME}/.openclaw/workspace"
CONF = json.load(open(f"{HOME}/.openclaw/openclaw.json"))
TO = (CONF.get("channels", {}).get("signal", {}).get("allowFrom") or [None])[0]   # the owner's number
_bk = open(f"{HOME}/.openclaw/openclaw-backup.sh").read() if os.path.exists(f"{HOME}/.openclaw/openclaw-backup.sh") else ""
_m = re.search(r'^DEST="([^"]+)"', _bk, re.M)
BACKUPS = _m.group(1) if _m else f"{HOME}/openclaw-backups"
VAULT = ((CONF.get("plugins", {}).get("entries", {}).get("memories") or {}).get("config") or {}).get("vaultPath")  # optional
ROOT_FILES = {"AGENTS.md", "SOUL.md", "USER.md", "IDENTITY.md", "MEMORY.md", "RULES.md", "DREAMS.md"}
AGENTS_BUDGET = 12000          # bytes; past this, rules start crowding out the conversation
NARRATIVE_JOB = "Nightly narrative pass"  # the one automation allowed to edit vault notes
ENV = dict(os.environ, PATH=f"{HOME}/.npm-global/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin")


def sh(*args, timeout=120):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=ENV)
    return r.returncode, r.stdout + r.stderr


def oc_json(*args):
    code, out = sh("openclaw", *args, "--json")
    start = out.find("{") if "{" in out else out.find("[")
    return json.loads(out[start:]) if code == 0 and start >= 0 else None


problems = []

# 1. Backup freshness
snaps = sorted(glob.glob(f"{BACKUPS}/*openclaw-backup*.tar.gz"), key=os.path.getmtime)
if not snaps:
    problems.append("No backups found in Dropbox.")
elif time.time() - os.path.getmtime(snaps[-1]) > 30 * 3600:
    problems.append(f"Newest backup is old: {os.path.basename(snaps[-1])}.")

# 2. Gateway + Signal
_, out = sh("openclaw", "gateway", "status", "--deep")
if "Listening: 127.0.0.1:18789" not in out or "Connectivity probe: ok" not in out:
    problems.append("Gateway isn't healthy, or isn't bound to 127.0.0.1 only.")
code, out = sh("curl", "-s", "-m", "5", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:8080/api/v1/check")
if out.strip() != "200":
    problems.append("Signal daemon isn't answering.")

# 3. No silent fallback to another brain
_, out = sh("openclaw", "config", "get", "agents.defaults.model.fallbacks")
if out.strip() not in ("[]", "") and "unset" not in out:
    problems.append(f"Model fallbacks are configured ({out.strip()}); data could silently go to another brain.")

# 4. Rules: one file, within budget, no new rule files
if os.path.getsize(f"{WS}/AGENTS.md") > AGENTS_BUDGET:
    problems.append(f"AGENTS.md is {os.path.getsize(f'{WS}/AGENTS.md')} bytes (budget {AGENTS_BUDGET}).")
extra = sorted(set(os.path.basename(p) for p in glob.glob(f"{WS}/*.md")) - ROOT_FILES)
if extra:
    problems.append("New files at the workspace root (possible new rule files): " + ", ".join(extra))

# 5. Every context note MEMORY.md lists exists
memory = open(f"{WS}/MEMORY.md").read()
for name in re.findall(r"`([\w.-]+\.md)`", memory):
    if not (glob.glob(f"{WS}/memory/context/{name}") or glob.glob(f"{WS}/memory-system/{name}")
            or glob.glob(f"{WS}/drafts/{name}") or glob.glob(f"{WS}/{name}")):
        problems.append(f"MEMORY.md lists {name}, which doesn't exist.")

# 6. Automation messages must be instructions, not questions to the user
jobs = (oc_json("automations", "list", "--all") or oc_json("automations", "list") or {}).get("jobs", [])
for job in jobs:
    msg = ((job.get("payload") or {}).get("message") or "").strip()
    if job.get("enabled", True) and msg and re.search(r"\?$|^[^.]{0,120}\?", msg) and "NO_REPLY" not in msg and not re.match(r"(?i)(send|remind|check|look|read|write)", msg):
        problems.append(f"Automation '{job.get('name')}' reads like a question to you, so it may answer itself.")

# 7. Vault writes: none during automation runs (except the narrative pass); event notes carry source: user
since = datetime.now() - timedelta(hours=26)
writes = []
for f in sorted(glob.glob(f"{WS}/ledger/*.jsonl"))[-3:]:
    for line in open(f):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("action") == "memory_note_written":
            ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            if ts >= since:
                writes.append((ts, e.get("path")))
if writes:
    windows = []
    for job in jobs:
        if job.get("name") == NARRATIVE_JOB:
            continue
        runs = oc_json("automations", "runs", job.get("id", "")) or {}
        for r in runs.get("entries", []):
            end = r.get("ts")
            dur = r.get("durationMs") or 600000
            if end:
                windows.append((datetime.fromtimestamp((end - dur) / 1000) - timedelta(seconds=30),
                                datetime.fromtimestamp(end / 1000) + timedelta(seconds=30), job.get("name")))
    for ts, path in writes:
        for a, b, name in windows:
            if a <= ts <= b:
                problems.append(f"Vault note '{path}' was written during the automation '{name}'.")
for p in (glob.glob(f"{VAULT}/events/*.md") if VAULT else []):
    if os.path.getmtime(p) >= since.timestamp():
        head = open(p, encoding="utf-8", errors="ignore").read(800)
        if "source: user" not in head:
            problems.append(f"Event note '{os.path.basename(p)}' changed without 'source: user'.")

# 8. Logs not ballooning
_, out = sh("journalctl", "--user", "--disk-usage")
m = re.search(r"([\d.]+)([GM])", out)
if m and (float(m.group(1)) * (1024 if m.group(2) == "G" else 1)) > 1500:
    problems.append(f"System logs are large ({m.group(0)}).")

report = "\n".join(f"• {p}" for p in problems)
if "--print" in sys.argv:
    print(report or "All checks passed.")
elif problems and TO:
    sh("openclaw", "message", "send", "--channel", "signal", "--target", TO,
       "--message", "🔎 Daily check found something:\n" + report)

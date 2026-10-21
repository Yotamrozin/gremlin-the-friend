#!/usr/bin/env python3
"""Daily outside check for the gremlin: plain code, no AI.

A model can't reliably audit itself, so this script looks at the real state of things and messages
the owner on Signal only when something is wrong. Run by openclaw-check.timer every morning.
Usage: daily-check.py [--print]   (--print shows the report instead of sending it)
"""
import glob, json, os, re, subprocess, sys, time
from datetime import datetime, timedelta, timezone

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

# 9. Only approved plugins enabled (the heartbeat's own audit missed one; this doesn't rely on the model)
approved_file = f"{HOME}/.openclaw/checks/approved-plugins.txt"
if os.path.exists(approved_file):
    approved = {l.strip() for l in open(approved_file) if l.strip() and not l.startswith("#")}
    plugins = (oc_json("plugins", "list") or {}).get("plugins", [])
    extra = sorted(p["id"] for p in plugins if p.get("enabled") and p["id"] not in approved)
    if extra:
        problems.append("Unapproved plugins are enabled: " + ", ".join(extra))

# 10. Vault event notes keep the user's own words
for p in (glob.glob(f"{VAULT}/events/*.md") if VAULT else []):
    if os.path.getmtime(p) >= since.timestamp() and "## In your words" not in open(p, encoding="utf-8", errors="ignore").read():
        problems.append(f"Event note '{os.path.basename(p)}' has no 'In your words' section.")

# 11. Claims without action: replies saying "I've updated/added/..." with no matching change in the ledger
import sqlite3
AGENT = next(iter(CONF.get("agents", {}).get("entries", {}) or {"main": 0}))
DB = f"{HOME}/.openclaw/agents/{AGENT}/agent/openclaw-agent.sqlite"
CLAIM = re.compile(r"(?i)\b(i've|i have|i just)\s+(updated|added|scheduled|created|noted|logged|recorded|saved|marked|booked|moved|deleted|documented|set up|put)\b")
if os.path.exists(DB):
    ledger_times = []
    for f in sorted(glob.glob(f"{WS}/ledger/*.jsonl"))[-3:]:
        for line in open(f):
            try:
                ledger_times.append(datetime.fromisoformat(json.loads(line)["ts"].replace("Z", "+00:00")).timestamp())
            except (ValueError, KeyError):
                pass
    try:
        db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=26)).strftime("%Y-%m-%dT%H:%M")
        for (ej,) in db.execute("select event_json from transcript_events where event_json like '%\"role\":\"assistant\"%' and event_json > ''"):
            try:
                e = json.loads(ej)
            except ValueError:
                continue
            ts, msg = e.get("timestamp", ""), e.get("message") or {}
            if ts < cutoff or msg.get("role") != "assistant":
                continue
            text = " ".join(c.get("text", "") for c in (msg.get("content") or []) if isinstance(c, dict) and c.get("type") == "text")
            m = CLAIM.search(text)
            if not m or text[m.end():m.end() + 20].strip().lower().startswith(("my understanding", "my notes", "my memory")):
                continue   # 'I've updated my understanding' isn't a claim to have changed anything
            t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            if not any(t - 300 <= lt <= t + 300 for lt in ledger_times):   # writes can land just before or after the reply
                problems.append(f"At {datetime.fromtimestamp(t):%H:%M} Bat said \"{text[max(0, m.start()-10):m.start()+90].strip()}…\" but nothing was changed.")
    except sqlite3.Error:
        pass

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

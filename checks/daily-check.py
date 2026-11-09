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
ROOT_FILES = {"AGENTS.md", "SOUL.md", "USER.md", "IDENTITY.md", "MEMORY.md"}
AGENTS_BUDGET = 14000          # bytes; past this, rules start crowding out the conversation
NARRATIVE_JOB = "Nightly narrative pass"  # the one automation allowed to edit vault notes
ENV = dict(os.environ, PATH=f"{HOME}/.npm-global/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin")


# --print is what Claude Code sees while fixing things: names, quotes and USER.md stay out of it.
# The Signal report goes to the owner and keeps the detail.
SAFE = "--print" in sys.argv


def priv(detail, label):
    return label if SAFE else detail


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
_t = CONF["plugins"]["entries"]["tasks"]["config"]
code, out = sh("curl", "-s", "-m", "10", "-o", "/dev/null", "-w", "%{http_code}", "-u", f"{_t['username']}:{_t['password']}", _t["serverUrl"])
if out.strip() not in ("200", "207", "301", "302"):
    problems.append(f"The task server ({_t['serverUrl']}) isn't answering, so the bot can't read or change tasks.")

# 3. No silent fallback to another brain
# (A fallback on the same provider is fine: same privacy terms, it only steps in when the main model fails.)
_model = CONF["agents"]["defaults"]["model"]
other = [f for f in _model.get("fallbacks") or [] if f.split("/")[0] != _model["primary"].split("/")[0]]
if other:
    problems.append(f"Model fallbacks go to another provider ({', '.join(other)}); data could silently go to another brain.")

# 4. Rules: one file, within budget, no new rule files
if os.path.getsize(f"{WS}/AGENTS.md") > AGENTS_BUDGET:
    problems.append(f"AGENTS.md is {os.path.getsize(f'{WS}/AGENTS.md')} bytes (budget {AGENTS_BUDGET}).")
extra = sorted(set(os.path.basename(p) for p in glob.glob(f"{WS}/*.md")) - ROOT_FILES)
if extra:
    problems.append("New files at the workspace root (possible new rule files): " + ", ".join(extra))

# 5. Every context note MEMORY.md lists exists
memory = open(f"{WS}/MEMORY.md").read()
for name in re.findall(r"`([\w./-]+\.md)`", memory):
    if not any(os.path.exists(f"{WS}/{d}{name}") for d in ("", "memory/context/", "memory-system/", "drafts/")):
        problems.append(f"MEMORY.md lists {priv(name, 'a note')}, which doesn't exist.")

# 12. No secrets in notes: card or account numbers, IBANs, API keys or tokens in the workspace or vault
SECRET = re.compile(
    r"(?<![\w/.-])(?:\d[ -]?){12,18}\d(?![\w/-])"                # card / account numbers (13–19 digits)
    r"|\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b"  # IBAN
    r"|\b(?:sk|pk|ghp|gho|xox[bp]|AKIA)[-_]?(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{16,}")  # common API key prefixes
for p in glob.glob(f"{WS}/**/*.md", recursive=True) + (glob.glob(f"{VAULT}/**/*.md", recursive=True) if VAULT else []):
    if "/memory/archive/" in p:
        continue
    m = SECRET.search(open(p, encoding="utf-8", errors="ignore").read())
    if m:
        where = os.path.relpath(p, VAULT) if VAULT and p.startswith(VAULT) else os.path.relpath(p, WS)
        problems.append(f"{priv(where, 'A note')} contains something that looks like a secret or account number (ending …{m.group(0)[-4:]}).")

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
                problems.append(f"Vault note {priv(repr(path), '(name hidden)')} was written during the automation '{name}'.")
for p in (glob.glob(f"{VAULT}/events/*.md") if VAULT else []):
    if os.path.getmtime(p) >= since.timestamp():
        head = open(p, encoding="utf-8", errors="ignore").read(800)
        if "source: user" not in head and "source: legacy" not in head:
            problems.append(f"Event note {priv(repr(os.path.basename(p)), '(name hidden)')} changed without 'source: user'.")

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
    text = open(p, encoding="utf-8", errors="ignore").read()
    if os.path.getmtime(p) >= since.timestamp() and "## In your words" not in text and "source: legacy" not in text[:800]:
        problems.append(f"Event note {priv(repr(os.path.basename(p)), '(name hidden)')} has no 'In your words' section.")

# 11. Claims without action: replies saying "I've updated/added/..." with no matching change in the ledger
import sqlite3
AGENT = next(iter(CONF.get("agents", {}).get("entries", {}) or {"main": 0}))
DB = f"{HOME}/.openclaw/agents/{AGENT}/agent/openclaw-agent.sqlite"
PROMISE = re.compile(r"(?i)\b(i'll|i will|let me)\s+(correct|create|add|fix|restore|record|save|update|document|set up|schedule)\b[^.]{0,80}\b(now|immediately|right away)\b|\b(i'll|i will)\s+(keep\s+)?(remind|nudg|ping)\w*\s+you")
CLAIM = re.compile(r"(?i)\b(i['’]ve|i have|i just)\s+(updated|added|scheduled|created|noted|logged|recorded|saved|marked|booked|moved|deleted|documented|set up|put|taken)\b")
# A vault claim needs a vault write (memory_* in the ledger), not just any change.
VAULT_CLAIM = re.compile(r"(?i)\b(created|recorded|saved|logged|added|updated|wrote)\b[^.\n]{0,60}\b(vault|event note|person note|note for|notes for|memor(y|ies)|era)\b")
if os.path.exists(DB):
    ledger_times, vault_times = [], []
    for f in sorted(glob.glob(f"{WS}/ledger/*.jsonl"))[-3:]:
        for line in open(f):
            try:
                d = json.loads(line)
                lt = datetime.fromisoformat(d["ts"].replace("Z", "+00:00")).timestamp()
                ledger_times.append(lt)
                if str(d.get("action", "")).startswith("memory_"):
                    vault_times.append(lt)
            except (ValueError, KeyError):
                pass
    try:
        db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=26)).strftime("%Y-%m-%dT%H:%M")
        try:
            from compression import zstd   # Python 3.14+; many events are stored compressed
        except ImportError:
            zstd = None
        since_ms = int((datetime.now(timezone.utc) - timedelta(hours=26)).timestamp() * 1000)
        for ej, ez in db.execute("select event_json, event_zstd from transcript_events where created_at >= ?", (since_ms,)):
            try:
                e = json.loads(ej if ej else zstd.decompress(ez).decode() if (ez and zstd) else "{}")
            except (ValueError, UnicodeDecodeError):
                continue
            ts, msg = e.get("timestamp", ""), e.get("message") or {}
            if ts < cutoff or msg.get("role") != "assistant":
                continue
            text = " ".join(c.get("text", "") for c in (msg.get("content") or []) if isinstance(c, dict) and c.get("type") == "text")
            if "Daily check found" in text:
                continue   # relaying this check's own report is not a claim
            t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            p = PROMISE.search(text)
            if p and not any(t - 60 <= lt <= t + 600 for lt in ledger_times):
                problems.append(f"At {datetime.fromtimestamp(t):%H:%M} Bat promised {priv(chr(34) + text[p.start():p.end()+40].strip() + '…' + chr(34), 'an action')} and then changed nothing.")
            v = VAULT_CLAIM.search(text)
            negated = v and re.search(r"(?i)(n['’]t|\bnot|\bno)\W+(\w+\W+)?$", text[max(0, v.start() - 25):v.start()])
            if v and not negated and not any(t - 600 <= lt <= t + 300 for lt in vault_times):
                problems.append(f"At {datetime.fromtimestamp(t):%H:%M} Bat said {priv(chr(34) + ' '.join(text[max(0, v.start()-20):v.end()+40].split()) + '…' + chr(34), 'it saved to the vault')} but nothing was written to the vault.")
                continue
            m = CLAIM.search(text)
            if not m or text[m.end():m.end() + 20].strip().lower().startswith(("my understanding", "my notes", "my memory")):
                continue   # 'I've updated my understanding' isn't a claim to have changed anything
            t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            if not any(t - 300 <= lt <= t + 300 for lt in ledger_times):   # writes can land just before or after the reply
                problems.append(f"At {datetime.fromtimestamp(t):%H:%M} Bat said {priv(chr(34) + text[max(0, m.start()-10):m.start()+90].strip() + '…' + chr(34), 'it changed something')} but nothing was changed.")
    except sqlite3.Error:
        pass

# 13. Rule changes: show what changed, flag vague or repeated wording, and rerun the regression suite
import difflib
RULE_FILES = ["AGENTS.md", "USER.md", "SOUL.md"]
VAGUE = re.compile(r"(?i)\b(be careful|be mindful|appropriate(ly)?|try to|if possible|as needed|when relevant|use (your )?judge?ment|where sensible|properly)\b")
STATE = f"{HOME}/.openclaw/checks/state"
os.makedirs(STATE, exist_ok=True)
rules_changed = []
for name in (n for n in RULE_FILES if os.path.exists(f"{WS}/{n}")):
    cur = open(f"{WS}/{name}", encoding="utf-8").read().splitlines()
    seen = f"{STATE}/{name}"
    old = open(seen, encoding="utf-8").read().splitlines() if os.path.exists(seen) else None
    if old is not None and old != cur:
        rules_changed.append(name)
        diff = [l for l in difflib.unified_diff(old, cur, lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        if SAFE and name == "USER.md":   # facts about the owner: say that it changed, not how
            problems.append(f"ℹ️ USER.md changed ({len(diff)} lines).")
            continue
        problems.append(f"ℹ️ {name} changed:\n" + "\n".join(d[:200] for d in diff[:20]) + ("\n…" if len(diff) > 20 else ""))
        for added in (d[1:] for d in diff if d.startswith("+") and d[1:].strip()):
            if (m := VAGUE.search(added)):
                problems.append(f"New wording in {name} is vague (\"{m.group(0)}\"); say what to do, observably: {added[:120]}")
            twin = next((o for o in cur if len(o) > 40 and o != added and difflib.SequenceMatcher(None, o, added).ratio() > 0.8), None)
            if twin:
                problems.append(f"New line in {name} nearly repeats another:\n  new: {added[:120]}\n  old: {twin[:120]}")
    if "--print" not in sys.argv:
        open(seen, "w", encoding="utf-8").write("\n".join(cur))
if rules_changed and "--print" not in sys.argv:
    _, out = sh("python3", f"{HOME}/.openclaw/checks/regression.py", "--detail", timeout=1800)
    fails = [l for l in out.splitlines() if l.startswith("FAIL")]
    problems.append("Regression tests after the rule change: " + ("all passed." if "PASS" in out and not fails else "\n" + "\n".join(fails or [out[-300:]])))

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

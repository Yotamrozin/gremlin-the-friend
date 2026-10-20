#!/usr/bin/env python3
"""Regression tests for the gremlin: run after any change to the brain, model, plugins or rules.

Five standard requests go through the real agent in fresh test sessions. Answers are checked against
the real calendar and task server (CalDAV), never against what the bot says
about itself. Anything a test creates is removed again. Costs a few cents per run.
Usage: regression.py
"""
import base64, glob, json, os, re, subprocess, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree as ET

HOME = os.path.expanduser("~")
ENV = dict(os.environ, PATH=f"{HOME}/.npm-global/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin")
CONF = json.load(open(f"{HOME}/.openclaw/openclaw.json"))
CFG = CONF["plugins"]["entries"]
_cal = (CFG.get("calendar") or CFG.get("fastmail-calendar"))["config"]
CAL = {"url": _cal.get("serverUrl", "https://caldav.fastmail.com/dav/"), "user": _cal["username"],
       "password": _cal.get("password") or _cal.get("appPassword")}
TASKS = CFG["tasks"]["config"]
AGENT = next(iter(CONF.get("agents", {}).get("entries", {}) or {"main": 0}))
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}
STAMP = datetime.now().strftime("%H%M%S")


def agent(message, timeout=360):
    key = f"agent:{AGENT}:regression-{STAMP}-{abs(hash(message)) % 10**6}"
    t0 = time.time()
    r = subprocess.run(["openclaw", "agent", "--agent", AGENT, "--session-key", key, "--message", message],
                       capture_output=True, text=True, timeout=timeout, env=ENV)
    return r.stdout.strip(), time.time() - t0


def dav(method, url, user, password, body=None, depth=None):
    req = urllib.request.Request(url, data=body.encode() if body else None, method=method)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode())
    req.add_header("Content-Type", "application/xml; charset=utf-8")
    if depth is not None:
        req.add_header("Depth", depth)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "ignore")


def calendar_homes():
    """Find the calendars on any CalDAV server: principal -> calendar home -> calendar collections."""
    from urllib.parse import urljoin
    u, pw, base = CAL["user"], CAL["password"], CAL["url"]
    prop = lambda name: f'<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><{name}/></d:prop></d:propfind>'
    x = ET.fromstring(dav("PROPFIND", base, u, pw, prop("d:current-user-principal"), "0"))
    principal = urljoin(base, x.find(".//d:current-user-principal/d:href", NS).text)
    x = ET.fromstring(dav("PROPFIND", principal, u, pw, prop("c:calendar-home-set"), "0"))
    home = urljoin(base, x.find(".//c:calendar-home-set/d:href", NS).text)
    x = ET.fromstring(dav("PROPFIND", home, u, pw, prop("d:resourcetype"), "1"))
    return [urljoin(base, r.find("d:href", NS).text) for r in x.findall("d:response", NS)
            if r.find(".//c:calendar", NS) is not None]


def calendar_events(start, end):
    """(summary, absolute href) of VEVENTs overlapping [start, end) across all calendars."""
    from urllib.parse import urljoin
    fmt = lambda t: t.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    query = ('<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><c:calendar-data/></d:prop>'
             '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
             f'<c:time-range start="{fmt(start)}" end="{fmt(end)}"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>')
    out = []
    for cal in calendar_homes():
        try:
            xml = dav("REPORT", cal, CAL["user"], CAL["password"], query, "1")
        except Exception:
            continue   # e.g. a task-only collection that rejects VEVENT queries
        for r in ET.fromstring(xml).findall("d:response", NS):
            data = r.find(".//c:calendar-data", NS)
            m = data is not None and re.search(r"^SUMMARY[^:]*:(.*)$", data.text or "", re.M)
            if m:
                out.append((m.group(1).strip(), urljoin(CAL["url"], r.find("d:href", NS).text)))
    return out


def radicale_tasks():
    """(summary, status, completed-local-date, path) for every task on the Radicale server."""
    out = []
    for f in glob.glob(f"{HOME}/radicale-data/collection-root/*/*/*.ics"):
        s = open(f, errors="ignore").read()
        if "VTODO" not in s:
            continue
        g = lambda k: (re.search(rf"^{k}[^:\n]*:(.*)$", s, re.M) or [None, ""])[1].strip()
        done = g("COMPLETED")
        done_day = (datetime.strptime(done[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).astimezone().date()
                    if len(done) >= 15 else None)
        out.append((g("SUMMARY"), g("STATUS"), done_day, f))
    return out


def words(title):
    return [w for w in re.findall(r"[a-z0-9']+", title.lower()) if len(w) > 3]


def mentioned(title, reply):
    ws = words(title)
    return not ws or sum(w in reply.lower() for w in ws) >= max(1, len(ws) // 2)


results = []
def record(name, ok, seconds, detail=""):
    results.append((name, ok, seconds, detail))

# 1. Tomorrow's calendar, all-day events included
tomorrow = date.today() + timedelta(days=1)
start = datetime.combine(tomorrow, datetime.min.time()).astimezone()
truth = [t for t, _ in calendar_events(start, start + timedelta(days=1))]
reply, secs = agent("What's on my calendar tomorrow? List every event, including all-day ones.")
missing = [t for t in truth if not mentioned(t, reply)]
record("Tomorrow's calendar", not missing, secs, f"missing: {missing}" if missing else f"{len(truth)} events")

# 2. Tasks finished today
done_today = [s for s, st, d, _ in radicale_tasks() if st == "COMPLETED" and d == date.today()]
reply, secs = agent("Which tasks did I finish today? Just list them.")
if done_today:
    missing = [t for t in done_today if not mentioned(t, reply)]
    record("Done today", not missing, secs, f"missing: {missing}" if missing else f"{len(done_today)} tasks")
else:
    record("Done today", bool(re.search(r"(?i)\b(no|none|nothing|haven't|didn't)\b", reply)), secs, "expected 'none'")

# 3. Create a task, then remove it
title = f"Regression check {STAMP}"
reply, secs = agent(f"Add a task to my Daily list: {title}")
made = []
for _ in range(15):   # the reply can arrive a moment before the server write lands
    made = [p for s, _, _, p in radicale_tasks() if s == title]
    if made:
        break
    time.sleep(1)
record("Create task", bool(made), secs, "" if made else "task not found on the server")
for p in made:
    rel = p.split("/collection-root/", 1)[1]
    dav("DELETE", TASKS["serverUrl"].rstrip("/") + "/" + rel, TASKS["username"], TASKS["password"])

# 4. Weekday guard: Tuesday + a Wednesday's date must not create an event
wed = date.today() + timedelta(days=(2 - date.today().weekday()) % 7 or 7)
etitle = f"Regression weekday check {STAMP}"
reply, secs = agent(f"Add a calendar event '{etitle}' on Tuesday {wed.strftime('%d %B %Y')} at 15:00.")
wstart = datetime.combine(wed - timedelta(days=2), datetime.min.time()).astimezone()
made = [h for t, h in calendar_events(wstart, wstart + timedelta(days=4)) if t == etitle]
record("Weekday guard", not made, secs, "event was created on a mismatched weekday" if made else "")
for h in made:
    dav("DELETE", h, CAL["user"], CAL["password"])

# 5. Reminder: created, phrased as an instruction, then removed
before = {j["id"] for j in json.loads(subprocess.run(["openclaw", "automations", "list", "--json"], capture_output=True,
          text=True, env=ENV).stdout or '{"jobs": []}').get("jobs", [])}
reply, secs = agent("Remind me in 3 hours to drink water.")
jobs = json.loads(subprocess.run(["openclaw", "automations", "list", "--json"], capture_output=True, text=True, env=ENV).stdout or '{"jobs": []}').get("jobs", [])
new = [j for j in jobs if j["id"] not in before]
msg = ((new[0].get("payload") or {}).get("message") or "") if new else ""
ok = bool(new) and not msg.strip().endswith("?")
record("Reminder", ok, secs, "no reminder created" if not new else ("message is a question: " + msg[:80] if not ok else ""))
for j in new:
    subprocess.run(["openclaw", "automations", "rm", j["id"]], capture_output=True, env=ENV)

width = max(len(r[0]) for r in results)
for name, ok, secs, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {secs:5.0f}s  {detail}")
sys.exit(0 if all(r[1] for r in results) else 1)

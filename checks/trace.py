#!/usr/bin/env python3
"""What the bot did, never what was said: a content-free timeline of its conversations and scheduled runs.

    trace.py                    last 24 hours, every conversation
    trace.py --hours 6          a shorter window
    trace.py --since 2026-11-04T18:00
    trace.py --session 44c0     one conversation (id prefix)
    trace.py --show 44c0#2965   ONE event's full content. Only with the owner's yes for that item.

Shows: time, conversation, who (you / bot / job / tool), tool names, ok or the kind of error, text length,
the model, and flags. Never shows message text, tool inputs, tool results, note titles or names.
"""
import argparse, json, os, re, sqlite3, sys
from datetime import datetime, timedelta, timezone

try:
    from compression import zstd   # Python 3.14+; many events are stored compressed
except ImportError:
    zstd = None

HOME = os.path.expanduser("~")
CONF = json.load(open(f"{HOME}/.openclaw/openclaw.json"))
AGENT = next(iter(CONF.get("agents", {}).get("entries", {}) or {"main": 0}))
DB = f"{HOME}/.openclaw/agents/{AGENT}/agent/openclaw-agent.sqlite"

# Kept in step with daily-check.py #11.
PROMISE = re.compile(r"(?i)\b(i'll|i will|let me)\s+(correct|create|add|fix|restore|record|save|update|document|set up|schedule)\b[^.]{0,80}\b(now|immediately|right away)\b|\b(i'll|i will)\s+(keep\s+)?(remind|nudg|ping)\w*\s+you")
VAULT_CLAIM = re.compile(r"(?i)\b(created|recorded|saved|logged|added|updated|wrote)\b[^.\n]{0,60}\b(vault|event note|person note|note for|notes for|memor(y|ies)|era)\b")
NEGATED = re.compile(r"(?i)(n['’]t|\bnot|\bno)\W+(\w+\W+)?$")
JOB = re.compile(r"^\[cron:\S+ ([^\]]+)\]")   # automation names are ours, not the owner's words
ERRORS = [("network", r"fetch failed|ENOTFOUND|ECONNREFUSED|EAI_AGAIN|getaddrinfo"), ("timeout", r"(?i)time ?out|timed out"),
          ("denied", r"(?i)denied|not allowed|allowlist"), ("not found", r"(?i)not found|no such|ENOENT|beyond end"),
          ("not unique", r"(?i)occurrences|must be unique"), ("rejected", r"(?i)reject|invalid|must|refus"),
          ("future date", r"(?i)future")]


def kind_of_error(text):
    return next((k for k, rx in ERRORS if re.search(rx, text or "")), "other")


def events(db, where, args):
    for sid, seq, ej, ez, ts in db.execute(f"select session_id, seq, event_json, event_zstd, created_at from transcript_events where {where} order by created_at, seq", args):
        try:
            yield sid, seq, json.loads(ej if ej else zstd.decompress(ez).decode() if (ez and zstd) else "{}")
        except (ValueError, UnicodeDecodeError):
            yield sid, seq, {"type": "unreadable"}


def texts(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return c
    return " ".join(p.get("text", "") for p in c or [] if isinstance(p, dict) and p.get("type") == "text")


def show(ref):
    sid, _, seq = ref.partition("#")
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    for s, q, e in events(db, "session_id like ? and seq = ?", (sid + "%", int(seq))):
        print(f"{s}#{q}\n{json.dumps(e.get('message', e), ensure_ascii=False, indent=1)}")


def trace(since_ms, session):
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    where, args = ("session_id like ? and created_at >= ?", (session + "%", since_ms)) if session else ("created_at >= ?", (since_ms,))
    vault_writes, last = {}, {}
    for sid, seq, e in events(db, where, args):
        m = e.get("message") or {}
        role, ts = m.get("role"), (e.get("timestamp") or "")[:19].replace("T", " ")
        where_ = f"{sid[:8]}#{seq}"
        if role == "user":
            t = texts(m)
            job = JOB.match(t)
            who = f"job '{job.group(1)}'" if job else ("you, voice note" if t.startswith("[Audio]") else "you")
            print(f"{ts}  {where_:14} {who}  ({len(t)} chars)")
            vault_writes[sid] = False
            last[sid] = "user"
        elif role == "assistant":
            calls = [p.get("name") for p in m.get("content") or [] if isinstance(p, dict) and p.get("type") in ("toolCall", "tool_use")]
            if any(c and c.startswith("memories_record") or c in ("memories_update_era", "memories_update_narrative", "memories_write_note") for c in calls):
                vault_writes[sid] = True
            t = texts(m)
            flags = []
            if m.get("model") == "delivery-mirror":   # a scheduled job's message relayed into the chat, not a reply
                print(f"{ts}  {where_:14} relayed job message ({len(t)} chars)")
                continue
            if m.get("stopReason") in ("aborted", "error") or m.get("errorMessage"):
                flags.append(f"FAILED: {kind_of_error(m.get('errorMessage', ''))}")
            v = VAULT_CLAIM.search(t)
            if v and not NEGATED.search(t[max(0, v.start() - 25):v.start()]) and not vault_writes.get(sid):
                flags.append("CLAIMS A VAULT SAVE, none made")
            if PROMISE.search(t) and not calls:
                flags.append("PROMISES ACTION, no call")
            if not calls and t.strip() in ("", "NO_REPLY") and last.get(sid) == "user":
                flags.append("no reply")
            what = ("calls " + ", ".join(calls)) if calls else f"replies ({len(t)} chars)"
            model = (m.get("model") or "").split("/")[-1]
            print(f"{ts}  {where_:14} bot {what}  [{model}]" + ("  ⚠ " + "; ".join(flags) if flags else ""))
            last[sid] = "bot"
        elif role == "toolResult":
            t = texts(m)
            err = m.get("isError") or re.search(r'"status":\s*"error"|^\s*\{\s*"error"', t)
            print(f"{ts}  {where_:14}   ↳ {m.get('toolName', '?')}: " + (f"ERROR ({kind_of_error(t)})" if err else "ok"))


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--hours", type=float, default=24)
    a.add_argument("--since")
    a.add_argument("--session", default="")
    a.add_argument("--show")
    o = a.parse_args()
    if o.show:
        sys.exit(show(o.show))
    start = datetime.fromisoformat(o.since).astimezone(timezone.utc) if o.since else datetime.now(timezone.utc) - timedelta(hours=o.hours)
    trace(int(start.timestamp() * 1000), o.session)

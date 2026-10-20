#!/usr/bin/env bash
# Step 6: privacy and safety settings, the bot's rulebook, and daily backups.
# Usage: bash 06-harden.sh ["/mnt/c/Users/<you>/Dropbox/openclaw-backups"]
#   The optional argument is where backups go. A folder synced by Dropbox/OneDrive gets you an off-PC copy.
set -euo pipefail
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
KIT="$(cd "$(dirname "$0")/.." && pwd)"
W="$HOME/.openclaw/workspace"

echo "==> Turn off plugins this setup doesn't use"
keep=" anthropic ollama deepinfra signal memory-core calendar tasks "   # anthropic/ollama/deepinfra: brain providers
for id in $(openclaw plugins list --json 2>/dev/null | python3 -c 'import json,sys; print(" ".join(p["id"] for p in json.load(sys.stdin)["plugins"] if p.get("enabled")))'); do
  [[ "$keep" == *" $id "* ]] || openclaw plugins disable "$id" || true
done

echo "==> Only the tools the gremlin uses, and a quiet heartbeat"
# Measured on a real gremlin: 53 tools behind a search step cost an extra model call per request, and a
# 30-minute heartbeat running inside the chat bloated every later call to ~76k tokens. These settings fix both.
cat > /tmp/gremlin-tools.json <<'J'
[{"path":"tools","value":{"profile":"minimal","toolSearch":false,"alsoAllow":[
 "cron","read","write","edit","exec","memory_search","memory_get",
 "calendar_list_calendars","calendar_create_calendar","calendar_list_events","calendar_create_event","calendar_delete_event",
 "tasks_list_lists","tasks_create_list","tasks_list","tasks_create","tasks_complete","tasks_delete"]}},
 {"path":"agents.defaults.heartbeat","value":{"every":"4h","isolatedSession":true}}]
J
openclaw config set --batch-file /tmp/gremlin-tools.json --replace
rm -f /tmp/gremlin-tools.json

echo "==> Rulebook for the bot"
cp "$KIT/workspace/RULES.md" "$W/RULES.md"
grep -q '## Timed reminders' "$W/AGENTS.md" 2>/dev/null || cat "$KIT/workspace/AGENTS-additions.md" >> "$W/AGENTS.md"

echo "==> Private file permissions, no error reporting, private files by default"
chmod 700 "$W"; chmod 600 "$W"/*.md
chmod -R go-rwx "$W"/memory "$W"/media "$W"/.git ~/.openclaw 2>/dev/null || true
mkdir -p ~/.config/systemd/user/openclaw-gateway.service.d
cat > ~/.config/systemd/user/openclaw-gateway.service.d/privacy.conf <<'EOF'
[Service]
UMask=0077
Environment=DISABLE_ERROR_REPORTING=1
EOF
grep -q DISABLE_ERROR_REPORTING ~/.bashrc || echo 'export DISABLE_ERROR_REPORTING=1' >> ~/.bashrc

echo "==> No overnight 'dreaming' (it writes free-form diary entries and can promote them into MEMORY.md)"
echo '[{"path":"plugins.entries.memory-core.config.dreaming","value":{"enabled":false}}]' > /tmp/gremlin-dream.json
openclaw config set --batch-file /tmp/gremlin-dream.json && rm -f /tmp/gremlin-dream.json

echo "==> Workspace history (every change to rules and notes becomes a reversible git commit)"
git -C "$W" init -q 2>/dev/null || true
git -C "$W" config user.name "Gremlin workspace"; git -C "$W" config user.email "gremlin@localhost"
git -C "$W" add -A && git -C "$W" commit -qm "Initial workspace" || true

echo "==> Daily backup, with a Signal alert if it ever fails"
DEST="${1:-$HOME/openclaw-backups}"
OWNER=$(openclaw config get channels.signal.allowFrom 2>/dev/null | python3 -c 'import json,sys; print((json.load(sys.stdin) or [""])[0])' 2>/dev/null || true)
cat > ~/.openclaw/openclaw-backup.sh <<EOF
#!/usr/bin/env bash
# Nightly backup: OpenClaw's own verified snapshot (a plain tar fails on its live databases) plus the
# tasks server's data. Any failure is sent to Signal: a backup that fails silently is no backup.
set -uo pipefail
export PATH="\$HOME/.npm-global/bin:\$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
DEST="$DEST"
TO="$OWNER"
KEEP=7   # each snapshot is roughly 80-100 MB
LOG=\$(mktemp)
fail() {
  local last; last=\$(ls -1t "\$DEST"/*openclaw-backup*.tar.gz 2>/dev/null | head -1 | xargs -r -d '\n' basename)
  [ -n "\$TO" ] && openclaw message send --channel signal --target "\$TO" --message "⚠️ Nightly backup failed: \$1. Last good backup: \${last:-none found}." >/dev/null 2>&1
  echo "FAILED: \$1" >&2; cat "\$LOG" >&2; exit 1
}
mkdir -p "\$DEST" || fail "the backup folder isn't reachable"
git -C "\$HOME/.openclaw/workspace" add -A >/dev/null 2>&1 && git -C "\$HOME/.openclaw/workspace" commit -qm "Nightly snapshot \$(date +%F)" >/dev/null 2>&1 || true
openclaw backup create --output "\$DEST" --verify >"\$LOG" 2>&1 || fail "OpenClaw snapshot (\$(tail -1 "\$LOG"))"
TMP="\$DEST/.radicale-\$(date +%F).tar.gz.partial"
tar -czf "\$TMP" -C "\$HOME" radicale-data 2>>"\$LOG"; rc=\$?
[ "\$rc" -le 1 ] || fail "tasks data (tar exit \$rc)"   # exit 1 only means "a file changed"; Radicale writes atomically
mv "\$TMP" "\$DEST/radicale-\$(date +%F).tar.gz"
ls -1t "\$DEST"/*openclaw-backup*.tar.gz | tail -n +\$((KEEP + 1)) | xargs -r -d '\n' rm -f
ls -1t "\$DEST"/radicale-*.tar.gz | tail -n +\$((KEEP + 1)) | xargs -r -d '\n' rm -f
rm -f "\$LOG"
EOF
chmod 700 ~/.openclaw/openclaw-backup.sh
cat > ~/.config/systemd/user/openclaw-backup.service <<'EOF'
[Unit]
Description=OpenClaw daily backup

[Service]
Type=oneshot
ExecStart=%h/.openclaw/openclaw-backup.sh
EOF
cat > ~/.config/systemd/user/openclaw-backup.timer <<'EOF'
[Unit]
Description=Daily OpenClaw backup

[Timer]
OnCalendar=*-*-* 04:00:00
RandomizedDelaySec=15min
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now openclaw-backup.timer
systemctl --user start openclaw-backup.service && echo "Test backup written to $DEST"

echo "==> Daily outside check (plain code, no AI): messages you only if something is wrong"
mkdir -p ~/.openclaw/checks && cp "$KIT/checks/daily-check.py" "$KIT/checks/regression.py" ~/.openclaw/checks/ && chmod 700 ~/.openclaw/checks/*.py
cat > ~/.config/systemd/user/openclaw-check.service <<'EOF'
[Unit]
Description=Gremlin daily outside check (no AI)

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 %h/.openclaw/checks/daily-check.py
EOF
cat > ~/.config/systemd/user/openclaw-check.timer <<'EOF'
[Unit]
Description=Gremlin daily outside check

[Timer]
OnCalendar=*-*-* 09:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now openclaw-check.timer
python3 ~/.openclaw/checks/daily-check.py --print || true

echo "==> Restart the bot so the new settings apply"
systemctl --user restart openclaw-gateway
echo
echo "Step 6 done. Two things only you can do (see the guide, 'Privacy checklist'):"
echo "  1. If your brain is Claude: claude.ai > Settings > Data privacy controls: turn model training OFF."
echo "  2. Windows: turn on BitLocker and Memory Integrity."
echo "In Signal, send the bot /new so it reads its new rulebook."

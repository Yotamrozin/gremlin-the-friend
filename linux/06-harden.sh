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

echo "==> Daily backup"
DEST="${1:-$HOME/openclaw-backups}"
cat > ~/.openclaw/openclaw-backup.sh <<EOF
#!/usr/bin/env bash
# Daily snapshot of the bot's state and your tasks. Written as .partial then renamed,
# so a syncing folder never uploads a half-written file. Keeps 14 days.
set -euo pipefail
DEST="$DEST"
mkdir -p "\$DEST"
TMP="\$DEST/.openclaw-backup-\$(date +%F).tar.gz.partial"
FINAL="\$DEST/openclaw-backup-\$(date +%F).tar.gz"
cd "\$HOME/.openclaw"
ITEMS=(); for i in state agents workspace media backups openclaw.json; do [ -e "\$i" ] && ITEMS+=("\$i"); done
tar -czf "\$TMP" "\${ITEMS[@]}" -C "\$HOME" radicale-data
mv "\$TMP" "\$FINAL"
ls -1t "\$DEST"/openclaw-backup-*.tar.gz | tail -n +15 | xargs -r rm -f
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

echo "==> Restart the bot so the new settings apply"
systemctl --user restart openclaw-gateway
echo
echo "Step 6 done. Two things only you can do (see the guide, 'Privacy checklist'):"
echo "  1. If your brain is Claude: claude.ai > Settings > Data privacy controls: turn model training OFF."
echo "  2. Windows: turn on BitLocker and Memory Integrity."
echo "In Signal, send the bot /new so it reads its new rulebook."

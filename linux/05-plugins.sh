#!/usr/bin/env bash
# Step 5: installs the calendar and tasks tools for the bot, and connects them.
# Passwords are typed into a hidden prompt here - never into a chat with any AI.
set -euo pipefail
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
KIT="$(cd "$(dirname "$0")/.." && pwd)"
R="$HOME/.config/radicale"
TASKS_URL=$(cat "$R/url.txt")
TASKS_PASS=$(cat "$R/password.txt")
mkdir -p ~/.openclaw/plugins

for p in calendar tasks; do
  echo "==> Building $p"
  rm -rf ~/.openclaw/plugins/$p
  cp -r "$KIT/plugins/$p" ~/.openclaw/plugins/$p
  (cd ~/.openclaw/plugins/$p && npm install --no-fund --no-audit && npm run plugin:build)
  (cd ~/.openclaw && openclaw plugins install ./plugins/$p --force)
  openclaw plugins enable $p
done

cat <<'EOF'

Where should your calendar live?
  1) On this PC (free). Same private server as your tasks. Syncs to your phone
     while the PC is awake; no email invitations, no web view.
  2) iCloud (free). Needs an Apple account with two-factor login.
  3) Fastmail (paid). Invitations, web calendar, syncs even when the PC is off.
  4) Another CalDAV service: Nextcloud, Disroot, mailbox.org, Posteo, Zoho...
EOF
read -rp "Choose 1-4 [1]: " CHOICE
case "${CHOICE:-1}" in
  1) CAL_URL="$TASKS_URL"; CAL_USER="$USER"; CAL_PASS="$TASKS_PASS"; CAL_NAME="Calendar" ;;
  2) CAL_URL="https://caldav.icloud.com/"
     echo "Create an app-specific password at account.apple.com > Sign-In and Security > App-Specific Passwords."
     read -rp "Apple account email: " CAL_USER ;;
  3) CAL_URL="https://caldav.fastmail.com/dav/"
     echo "Create an app password at Fastmail > Settings > Privacy & Security > App passwords (access: Calendars (CalDAV))."
     read -rp "Fastmail login email: " CAL_USER ;;
  4) echo "Find the 'CalDAV address' in your provider's help pages. Nextcloud: https://<your-server>/remote.php/dav/"
     read -rp "CalDAV address: " CAL_URL
     read -rp "Username: " CAL_USER ;;
  *) echo "Please run again and choose 1-4."; exit 1 ;;
esac
if [ "${CHOICE:-1}" != "1" ]; then
  read -rsp "App password (hidden; never your main password): " CAL_PASS; echo
  read -rp "Default calendar name, exactly as your calendar app shows it (Enter = the first one): " CAL_NAME
fi

echo "==> Checking the login"
CODE=$(printf 'user = "%s:%s"\n' "$CAL_USER" "$CAL_PASS" | curl -s -K - -o /dev/null -w '%{http_code}' -X PROPFIND -H 'Depth: 0' "$CAL_URL" || true)
case "$CODE" in
  207|200|301|302) echo "Login OK ($CODE)." ;;
  401) echo "The server rejected the login (401). Check the email and app password, then run this script again."; exit 1 ;;
  *)   echo "Unexpected answer from the server ($CODE). Continuing; if the bot can't see your calendar, check the address." ;;
esac

# Values go through a private temp file, not the command line, so they never show in the process list.
umask 077
B=$(mktemp)
CAL_URL="$CAL_URL" CAL_USER="$CAL_USER" CAL_PASS="$CAL_PASS" CAL_NAME="${CAL_NAME:-}" \
TASKS_URL="$TASKS_URL" TASKS_PASS="$TASKS_PASS" TU="$USER" \
python3 - > "$B" <<'EOF'
import json, os
e = os.environ
cal = {"serverUrl": e["CAL_URL"], "username": e["CAL_USER"], "password": e["CAL_PASS"]}
if e["CAL_NAME"]:
    cal["calendarName"] = e["CAL_NAME"]
print(json.dumps([
  {"path": "plugins.entries.calendar.config", "value": cal},
  {"path": "plugins.entries.tasks.config", "value": {"serverUrl": e["TASKS_URL"], "username": e["TU"], "password": e["TASKS_PASS"], "listName": "Tasks"}},
]))
EOF
openclaw config set --batch-file "$B"
shred -u "$B" 2>/dev/null || rm -f "$B"
unset CAL_PASS TASKS_PASS

openclaw plugins reload calendar || true
openclaw plugins reload tasks || true
openclaw plugins list | grep -E 'calendar|tasks' || true
echo
echo "Step 5 done. In Signal, send the bot: /new   (it only sees new tools in a fresh conversation)"
echo "Then try: 'What's on my calendar this week?' and 'Add a task: buy milk'."
if [ "${CHOICE:-1}" = "1" ]; then
  echo "Phone: in DAVx5, add an account with the same address, username and password as Tasks.org,"
  echo "and turn on the 'Calendar' calendar. Calendula then shows it."
fi
echo "Next: bash 06-harden.sh"

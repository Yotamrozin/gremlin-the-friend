#!/usr/bin/env bash
# Step 3: links the bot's Signal account and restricts it to your own number.
# You need: the bot phone (second number) with Signal installed and set up.
set -euo pipefail
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
CFG="$HOME/.config/signal-cli"   # always this path; the gateway reads it
mkdir -p "$CFG" && chmod 700 "$CFG"

if ! signal-cli --config "$CFG" listAccounts 2>/dev/null | grep -q Number; then
  sudo apt-get install -y qrencode >/dev/null
  systemctl --user stop openclaw-gateway   # nothing else may receive while linking
  echo
  echo "On the BOT phone: Signal > Settings > Linked devices > + , then scan the QR below."
  echo
  # Render the sgnl:// link as a QR right here (signal-cli's own output shows only '?' characters).
  signal-cli --config "$CFG" link -n "Gremlin" | while read -r line; do
    case "$line" in
      sgnl://*) qrencode -t ansiutf8 "$line"
                echo "If the QR looks broken, make the terminal window bigger and re-run this script."
                echo "Waiting for you to scan...";;
      *) echo "$line";;
    esac
  done
fi
signal-cli --config "$CFG" listAccounts

read -rp "Bot's phone number (international format, e.g. +447700900123): " BOT
read -rp "YOUR personal number, the one allowed to talk to the bot: " ME
[[ "$BOT" =~ ^\+[0-9]{8,15}$ && "$ME" =~ ^\+[0-9]{8,15}$ ]] || { echo "Numbers must look like +447700900123"; exit 1; }
[[ "$BOT" != "$ME" ]] || { echo "Those are the same number. The allowed number is YOUR personal one."; exit 1; }

openclaw config set channels.signal --strict-json "{
  \"enabled\": true,
  \"account\": \"$BOT\",
  \"dmPolicy\": \"allowlist\",
  \"allowFrom\": [\"$ME\"],
  \"groupPolicy\": \"disabled\",
  \"transport\": {\"kind\": \"managed-native\", \"configPath\": \"$CFG\", \"receiveMode\": \"on-start\", \"startupTimeoutMs\": 120000}
}"
systemctl --user restart openclaw-gateway
echo
echo "Step 3 done. In about a minute, message the bot from your personal Signal."
echo "If it asks for a pairing code, run: openclaw pairing approve signal <CODE>"
echo "IMPORTANT: from now on, never run 'signal-cli receive' - it steals the bot's messages."
echo "Next: bash 04-tasks-server.sh"

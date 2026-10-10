#!/usr/bin/env bash
# Step 4: your private tasks (and, if you choose, calendar) server (Radicale),
# reachable only inside your Tailscale network, over HTTPS.
set -euo pipefail
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

TSIP=$(tailscale ip -4 | head -1)
[ -n "$TSIP" ] || { echo "Tailscale isn't connected in Ubuntu. Run: sudo tailscale up"; exit 1; }
D="$HOME/.config/radicale"
mkdir -p "$D" "$HOME/radicale-data" && chmod 700 "$D" "$HOME/radicale-data"

if [ ! -f "$D/users" ]; then
  PASS=$(openssl rand -base64 18)
  umask 077
  echo "$PASS" > "$D/password.txt"
  echo "$USER:$(openssl passwd -apr1 "$PASS")" > "$D/users"
  unset PASS
fi

cat > "$D/config" <<EOF
[server]
hosts = $TSIP:5232

[auth]
type = htpasswd
htpasswd_filename = $D/users
htpasswd_encryption = autodetect

[storage]
filesystem_folder = $HOME/radicale-data

[rights]
type = owner_only
EOF
chmod 600 "$D/config"

mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/radicale.service <<EOF
[Unit]
Description=Radicale tasks server (private, over Tailscale)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$HOME/.local/bin/radicale --config $D/config
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now radicale
sleep 3

echo "==> HTTPS via Tailscale Serve (Android apps refuse plain HTTP)"
echo "If this prints a link, open it, enable Serve, then re-run this script."
tailscale serve --bg "http://$TSIP:5232"
URL="https://$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')/"
echo "$URL" > "$D/url.txt"

# Credentials go to curl on stdin (-K -), never on its command line.
auth() { printf 'user = "%s:%s"\n' "$USER" "$(cat "$D/password.txt")"; }
CODE=$(auth | curl -s -K - -o /dev/null -w '%{http_code}' -X PROPFIND -H 'Depth: 0' "$URL" || true)

# A starter task list and calendar. Re-running is harmless: an existing one just answers 405.
mk() {  # mk <slug> <display name> <VEVENT|VTODO>
  auth | curl -s -K - -o /dev/null -X MKCALENDAR -H 'Content-Type: application/xml' "$URL$USER/$1/" --data \
    "<?xml version=\"1.0\"?><C:mkcalendar xmlns:D=\"DAV:\" xmlns:C=\"urn:ietf:params:xml:ns:caldav\"><D:set><D:prop><D:displayname>$2</D:displayname><C:supported-calendar-component-set><C:comp name=\"$3\"/></C:supported-calendar-component-set></D:prop></D:set></C:mkcalendar>" || true
}
if [ "$CODE" = "207" ]; then
  mk tasks "Tasks" VTODO
  mk calendar "Calendar" VEVENT
fi
echo
echo "Server check: $CODE (207 = working. A certificate error right after enabling HTTPS is normal - wait a minute and re-run.)"
echo
echo "For the Tasks.org app on your phone:"
echo "   Server:   $URL"
echo "   Username: $USER"
echo "   Password: in the file $D/password.txt  (open it with: cat $D/password.txt)"
echo "Save the password in your password manager. Don't paste it into any chat."
echo "Next: bash 05-plugins.sh"

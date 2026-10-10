#!/usr/bin/env bash
# Step 2: creates the OpenClaw gateway, bound to this computer only (127.0.0.1).
# Run AFTER `claude auth login` has succeeded.
set -euo pipefail
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

claude auth status >/dev/null 2>&1 || { echo "Run 'claude auth login' first, then re-run this."; exit 1; }

openclaw onboard --accept-risk --agent-name main --auth-choice anthropic-cli \
  --flow quickstart --gateway-bind loopback --gateway-port 18789 \
  --install-daemon --non-interactive --json

systemctl --user daemon-reload
systemctl --user restart openclaw-gateway
sleep 25
openclaw gateway status --deep | grep -E 'Listening|Connectivity' || true
echo
echo "Step 2 done. You want to see 'Listening: 127.0.0.1:18789' and 'Connectivity probe: ok'."
echo "If the probe timed out, wait 30 seconds and run: openclaw gateway status --deep"
echo "Next: bash 03-signal.sh"

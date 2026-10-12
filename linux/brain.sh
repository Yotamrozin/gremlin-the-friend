#!/usr/bin/env bash
# Chooses (or switches) your gremlin's brain: the AI model that reads your messages and answers them.
# Run during setup (after 02-onboard.sh), and again any time you want to switch.
# API keys are typed into hidden prompts and kept in OpenClaw's secret store, never in a chat or a config file.
set -euo pipefail
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

# Models used for each option. Change these to try others.
OLLAMA_CLOUD_MODEL="deepseek-v4-flash"                  # open-weight model from Ollama's hosted catalog
CLAUDE_MODEL="anthropic/claude-haiku-4-5"

cat <<'EOF'

Choose your gremlin's brain. Privacy is rated from ●○○○○ (least) to ●●●●● (most).

  1) Local, on this PC (Ollama)            ●●●●●  Nothing leaves your PC. Free.
                                                  Needs a strong PC; slower and makes more mistakes than the cloud options.
  2) Ollama Cloud                          ●●●○○  Says it processes and discards prompts, no training. Mostly US servers.
                                                  Free with usage limits, or $20/month.
  3) Claude (Anthropic)                    ●●○○○  Most capable. Kept 30 days with training switched off (up to 5 years if on).
                                                  Needs a Claude Pro subscription.
EOF
read -rp "Choose 1-3: " CHOICE

# One config change for every option: the provider entry (if any), the default model, and no fallbacks,
# so a failure shows as an error instead of silently sending your data to a different, less private brain.
apply() {  # apply <primary-model> [<provider-id> <provider-json>]
  local b; b=$(mktemp)
  PRIMARY="$1" PID="${2:-}" PJSON="${3:-null}" python3 - > "$b" <<'PY'
import json, os
ops = [{"path": "agents.defaults.model", "value": {"primary": os.environ["PRIMARY"], "fallbacks": []}}]
if os.environ["PID"]:
    ops.insert(0, {"path": f'models.providers.{os.environ["PID"]}', "value": json.loads(os.environ["PJSON"])})
print(json.dumps(ops))
PY
  openclaw config set --batch-file "$b" --replace   # --replace: switching models replaces the model list
  rm -f "$b"
}

store_key() {  # store_key <SECRET_NAME> <prompt>
  local k
  read -rsp "$2 (hidden): " k; echo
  [ -n "$k" ] || { echo "No key entered."; exit 1; }
  printf '%s' "$k" | openclaw secrets store set "$1" --kind secret --value-file - >/dev/null
  unset k
}
ref() { printf '{"source":"store","provider":"default","id":"%s"}' "$1"; }

case "$CHOICE" in
1)
  echo "==> Checking this PC"
  RAM_GB=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)
  VRAM_GB=0
  if command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1; then
    VRAM_GB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | awk '{printf "%d", $1/1024}')
  fi
  echo "   Memory available to Ubuntu: ${RAM_GB} GB. NVIDIA graphics memory: ${VRAM_GB} GB."
  # ponytail: three hardware tiers; LM Studio / llama.cpp with expert offload can do better on split models.
  if   [ "$VRAM_GB" -ge 12 ]; then MODEL="gpt-oss:20b"; CTX=32768
  elif [ "$VRAM_GB" -ge 8 ];  then MODEL="qwen3:8b";    CTX=16384
  elif [ "$RAM_GB" -ge 12 ];  then MODEL="qwen3:4b";    CTX=16384
    echo
    echo "   No NVIDIA graphics card found. A local brain will run on the processor:"
    echo "   expect replies to take a minute or more, and more mistakes."
    read -rp "   Continue anyway? [y/N] " ok; [[ "$ok" =~ ^[Yy] ]] || exit 1
  else
    echo "   This PC doesn't have enough memory for a local brain. Choose option 2 or 3 instead."; exit 1
  fi
  echo "==> Installing Ollama (inside Ubuntu, reachable only from this PC)"
  command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
  sudo mkdir -p /etc/systemd/system/ollama.service.d
  printf '[Service]\nEnvironment=OLLAMA_HOST=127.0.0.1:11434\nEnvironment=OLLAMA_KEEP_ALIVE=30m\n' | sudo tee /etc/systemd/system/ollama.service.d/gremlin.conf >/dev/null
  sudo systemctl daemon-reload && sudo systemctl restart ollama
  if [ "$VRAM_GB" -gt 0 ]; then
    # GPU models in WSL2 can make Windows kill and restart WSL in a loop (see OpenClaw's Ollama troubleshooting).
    WINCFG="$(wslpath "$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')")/.wslconfig"
    if ! grep -q autoMemoryReclaim "$WINCFG" 2>/dev/null; then
      printf '\n[experimental]\nautoMemoryReclaim=disabled\n' >> "$WINCFG"
      echo "   Added autoMemoryReclaim=disabled to .wslconfig (takes effect after the next Windows restart)."
    fi
  fi
  echo "==> Downloading $MODEL (several GB; this takes a while)"
  ollama pull "$MODEL"
  apply "ollama/$MODEL" ollama "$(printf '{"baseUrl":"http://127.0.0.1:11434","apiKey":"ollama-local","api":"ollama","timeoutSeconds":300,"models":[{"id":"%s","name":"%s","input":["text"],"contextTokens":%s,"params":{"num_ctx":%s,"keep_alive":"30m"}}]}' "$MODEL" "$MODEL" "$CTX" "$CTX")"
  ;;
2)
  echo "Create an API key at ollama.com > Settings > Keys."
  store_key OLLAMA_API_KEY "Ollama API key"
  apply "ollama-cloud/$OLLAMA_CLOUD_MODEL" ollama-cloud "$(printf '{"apiKey":%s}' "$(ref OLLAMA_API_KEY)")"
  ;;
3)
  command -v claude >/dev/null || npm install -g @anthropic-ai/claude-code
  claude auth status >/dev/null 2>&1 || { echo "Run 'claude auth login' (a browser login), then run this again."; exit 1; }
  b=$(mktemp)
  printf '[{"path":"agents.defaults.models[\\"%s\\"]","value":{"agentRuntime":{"id":"claude-cli"}}},{"path":"agents.defaults.model","value":{"primary":"%s","fallbacks":[]}}]' \
    "$CLAUDE_MODEL" "$CLAUDE_MODEL" > "$b"
  openclaw config set --batch-file "$b"; rm -f "$b"
  echo
  echo "Remember: claude.ai > Settings > Data privacy controls > turn model training OFF."
  ;;
*) echo "Please run again and choose 1-3."; exit 1 ;;
esac

echo "==> Restarting your gremlin with its new brain"
systemctl --user restart openclaw-gateway
# Startup takes 30-60 s (plugins, then Signal); wait until the gateway answers rather than guessing.
for _ in $(seq 1 24); do
  openclaw gateway status --deep 2>/dev/null | grep -q 'Connectivity probe: ok' && break
  sleep 5
done
openclaw models status 2>&1 | grep -E '^Default' || true
echo
echo "Done. In Signal, send your gremlin /new, then try: 'What's on my calendar this week?'"
echo "To switch brains later, run this script again."

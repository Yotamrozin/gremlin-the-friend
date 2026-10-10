#!/usr/bin/env bash
# Step 1: installs everything the bot needs inside Ubuntu (WSL).
# Run in the Ubuntu terminal:  bash 01-install.sh
# It asks for your Ubuntu password (for sudo) once or twice. Safe to re-run.
set -euo pipefail
SIGNAL_CLI_VERSION=0.14.8

echo "==> System packages, Node.js 24, Tailscale"
sudo apt-get update
sudo apt-get install -y ca-certificates curl git wget unzip default-jdk python3-pip python3-venv pipx
if ! node -v 2>/dev/null | grep -qE '^v(24\.(1[6-9]|[2-9][0-9])|26\.)'; then
  curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh

echo "==> npm global folder in your home directory (avoids EACCES errors)"
mkdir -p ~/.npm-global
npm config set prefix "$HOME/.npm-global"
grep -q 'npm-global/bin' ~/.bashrc || echo 'export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"' >> ~/.bashrc
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

echo "==> OpenClaw and Claude Code"
npm install -g openclaw@latest @anthropic-ai/claude-code

echo "==> signal-cli $SIGNAL_CLI_VERSION (native build; the binary sits at the archive root)"
if ! signal-cli --version 2>/dev/null | grep -q "$SIGNAL_CLI_VERSION"; then
  tmp=$(mktemp -d)
  wget -qO "$tmp/signal-cli.tar.gz" "https://github.com/AsamK/signal-cli/releases/download/v$SIGNAL_CLI_VERSION/signal-cli-$SIGNAL_CLI_VERSION-Linux-native.tar.gz"
  sudo mkdir -p /opt/signal-cli
  sudo tar -xzf "$tmp/signal-cli.tar.gz" -C /opt/signal-cli
  sudo ln -sf /opt/signal-cli/signal-cli /usr/local/bin/signal-cli
  rm -rf "$tmp"
fi

echo "==> Radicale (your private tasks server)"
pipx install radicale || pipx upgrade radicale

echo "==> Let your services run without an open terminal"
sudo loginctl enable-linger "$(whoami)"

echo "==> Let you manage Tailscale Serve without sudo"
sudo tailscale up --hostname="$(hostname)-wsl" --accept-routes --reset
sudo tailscale set --operator="$USER"

echo
node -v; openclaw --version; claude --version; signal-cli --version
echo
echo "Step 1 done. Next: run 'source ~/.bashrc', then 'claude auth login', then 'bash 02-onboard.sh'."

# Gremlin the Friend: setup guide (Windows + WSL2)

This guide is the reference for the kit, written for whoever runs the setup, a person or Claude Code. Each step names its script, says how to check that it worked, and lists the known problems at that stage. The final section, "Known problems", collects every failure seen so far.

Verified on: Windows 11 25H2, WSL 2.7, Ubuntu, Node 24.21, OpenClaw 2026.9.6, Claude Code 2.1.283, signal-cli 0.14.8, Radicale 3.8. **Config field names change between OpenClaw versions.** If a command in this guide is rejected, `openclaw doctor` and `openclaw config schema` on the installed version are more authoritative than this file.

## How it fits together

```
Your phone (Signal) ──► bot's Signal account ──► signal-cli (in WSL) ──► OpenClaw gateway (127.0.0.1 only)
                                                                         ├─ Claude (the brain)
                                                                         ├─ calendar plugin ──► your choice: Radicale (default), iCloud, Fastmail, any CalDAV
                                                                         └─ tasks plugin ──► Radicale (in WSL, HTTPS over Tailscale)
Your phone: Tasks.org ──► Radicale over Tailscale.   DAVx5 + Calendula ──► wherever the calendar lives.
```

**Choosing where the calendar lives (asked in step G):**

| Option | Cost | Trade-offs |
|---|---|---|
| **This PC** (Radicale, the default) | Free | Syncs only while the PC is awake; the phone keeps working offline and catches up. No email invitations, no web view. The nightly backup is the only other copy. |
| **iCloud** | Free | Needs an Apple account with two-factor login and an app-specific password. Works on Android through DAVx5. Apple can read the data. |
| **Fastmail** | Paid | Invitations, web calendar, always online. |
| **Other CalDAV** (Nextcloud, Disroot, mailbox.org, Posteo, Zoho…) | Free to cheap | Needs the provider's CalDAV address and an app password. |

Google Calendar, Outlook/Microsoft 365, Proton and Tuta are **not supported**. Google and Microsoft would need a separate OAuth plugin; Proton and Tuta have no CalDAV access at all.

- **Nothing is exposed to the internet.** The gateway listens only on `127.0.0.1`. Radicale listens only on the Tailscale address, which only your own devices can reach.
- **The brain is not local.** Every message, and whatever the agent reads to answer it (events, tasks, workspace notes), is sent to Anthropic. With training off, Anthropic keeps conversations for 30 days; with it on, for up to 5 years, and uses them for training. Don't describe this setup as "nothing leaves your devices". That's true of storage, not of conversations. See the README's "What stays private" section.
- **Windows keeps WSL alive.** WSL2 shuts Ubuntu down when nothing is attached to it, so three hidden scheduled tasks keep one tiny process attached (step B).

## A. WSL and Ubuntu (Windows, administrator)

1. Run `wsl --install` in an **administrator** PowerShell, then restart.
2. If Ubuntu doesn't finish installing, check that virtualization is enabled (`systeminfo`, "Virtualization Enabled In Firmware") and run `wsl --install -d Ubuntu` again.
3. Create the Linux user: lowercase, no spaces, and a password you'll remember. Every `sudo` asks for it.

**Shell rules (the most common early mistakes):**
- Linux commands go in the **Ubuntu** terminal, not PowerShell. In PowerShell, `sudo` says "Sudo is disabled" and `curl -fsSL` fails as `Invoke-WebRequest`.
- In the Ubuntu terminal, **paste with right-click**.
- Windows PowerShell 5.1 has no `&&`. Use `;` instead.
- Paste multi-line PowerShell as a single line. Multi-line paste can drop into a `>>` prompt and corrupt the command.
- `sudo` and administrator commands are typed by the human. An AI assistant has no way to enter those passwords.

## B. Windows autostart — `windows/setup-autostart.ps1`

Run this from an administrator PowerShell: `powershell -ExecutionPolicy Bypass -File .\windows\setup-autostart.ps1`. It copies the scripts to `%LOCALAPPDATA%\OpenClaw`, registers three **hidden** tasks, and puts a `Start OpenClaw` shortcut on the Desktop.

- **OpenClaw Gateway** runs `wsl -- true` at logon and at startup. It needs both triggers because Fast Startup makes "shut down" a hibernate, so the startup trigger alone doesn't always fire.
- **OpenClaw Keepalive** runs the watchdog every 30 minutes. The watchdog makes sure one hidden `wsl -- sleep infinity` process exists.
- **OpenClaw Wake Watchdog** runs the same watchdog on wake from sleep (Kernel-Power event 507).

To check it: `Get-ScheduledTask -TaskName "OpenClaw*"` lists three tasks, and this command returns one process:

```powershell
Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" | ? CommandLine -match 'sleep infinity'
```

The tasks don't keep the PC awake. While the PC sleeps, the bot is offline; it comes back on wake.

**Things that were tried and don't work:**
- `vmIdleTimeout=-1` in `.wslconfig` has no effect.
- A timer that runs `wsl -- true` doesn't help, because the process exits instantly.
- A single `sleep infinity` with no watchdog dies on sleep/wake.
- A task without `-Hidden` flashes a window every time it runs.

## C. Install — `linux/01-install.sh`

The script installs Node 24, sets up a user-owned npm folder, installs OpenClaw and Claude Code, signal-cli (the native build), Radicale (via pipx) and Tailscale, enables linger, and joins Ubuntu to Tailscale (a browser login).

- **Node must be `>=24.16 <25` or `>=26.1`.** Node 22 and Node 24.15 are both too old.
- **The npm prefix lives at `~/.npm-global`**, because the system folder gives `EACCES`.
- **signal-cli's native archive has the binary at its root** (`/opt/signal-cli/signal-cli`), not under `bin/`. `apt install signal-cli` doesn't work.
- **Don't add `--advertise-tags`** to `tailscale up`. It fails unless the tag exists in your ACLs.
- Before running it, install **Tailscale on Windows and the phone** too. On Windows: `winget install --id Tailscale.Tailscale -e`. On Android, turn on **Always-on VPN** for Tailscale (Settings → Network → VPN), and keep **Private DNS** off or on Automatic.

When it finishes, run `source ~/.bashrc`, then `claude auth login` (a browser login).

## D. Onboard — `linux/02-onboard.sh`

The script runs onboarding non-interactively with `--auth-choice anthropic-cli --gateway-bind loopback --gateway-port 18789 --install-daemon`.

To check it: `openclaw gateway status --deep` shows `Listening: 127.0.0.1:18789` and `Connectivity probe: ok`. The probe can time out for about 30 seconds after a restart.

- **Onboarding may offer a Codex or OpenAI device login.** Not needed; this kit uses `claude auth login`.
- **"Another onboarding operation is running (pid N)"** means a stale lock. Check it with `ps -fp N`, then `kill N` and re-run.
- **`ECONNREFUSED 127.0.0.1:18789`** means linger isn't enabled: run `sudo loginctl enable-linger $USER`, then restart the gateway.
- **`StateDatabaseCoordinatorContentionError`** means someone started the gateway by hand alongside the service. Run it only through systemd. Fix with `openclaw doctor --fix`, then `systemctl --user restart openclaw-gateway`.
- **The local web UI asks for a token.** Get it with `openclaw gateway auth-token --show`.
- **The workspace is `~/.openclaw/workspace`.** Don't create a second one.

## E. Signal — `linux/03-signal.sh`

The script links the bot's Signal account as a linked device, shows the QR code in the terminal, and asks for the bot's number and the owner's number.

To check it: message the bot from the owner's personal Signal and get a reply within about a minute. If it asks for a pairing code, run `openclaw pairing approve signal <CODE>`.

- **Always use `--config ~/.config/signal-cli`.** Without it, signal-cli uses `~/.local/share/signal-cli`. That leaves a second, stale copy of the account, and later you get misleading "User … is not registered" errors.
- **Don't pass `-a` when linking.** It fails with "cannot specify a account when linking".
- **The QR is a one-time secret.** Don't put it in a chat or an online QR generator. The script renders it locally.
- **Config fields that work on this version:** `account` (the bot's number), `dmPolicy: "allowlist"`, `allowFrom: ["+<owner>"]`, `groupPolicy: "disabled"`, and `transport.kind: "managed-native"`.
  - These older names are rejected: `phoneNumber`, `allowedContacts`, `groupPolicy: "never"`.
  - Group policy `open` would let anyone in any group trigger the bot, so it stays `disabled`.
- **`allowFrom` is the owner's personal number,** not the bot's.

**Signal operating rules:**
- **A linked device receives each message exactly once.** Never run `signal-cli receive` or a second daemon while the gateway is up; it consumes the bot's messages.
- **Restart with `systemctl --user restart openclaw-gateway`, never `kill -9`.** The channel allows 10 automatic restarts, then stays down.
- **To debug, read the stream; don't receive.** `curl -sN http://127.0.0.1:8080/api/v1/events` is safe to run alongside the gateway.
- **Don't re-link as a fix.** Re-link only if the device disappeared from the phone's Linked devices list.
- **`/new` in Signal starts a fresh conversation.** Do this after any plugin change.

## F. Tasks server — `linux/04-tasks-server.sh`

The script does the following:
- Generates a random password. It saves it to `~/.config/radicale/password.txt` (mode 600) and stores only a hash in Radicale's `users` file.
- Binds Radicale to the Tailscale IP only, with `owner_only` rights, as a systemd user service.
- Wraps Radicale in HTTPS with `tailscale serve --bg http://<tailscale-ip>:5232`.
- Creates a starter task list ("Tasks") and a starter calendar ("Calendar"). The calendar is used only if you choose "This PC" in step G; otherwise it sits empty and doesn't show up anywhere.
- Prints the Tasks.org settings.

To check it, the script's PROPFIND check prints **207**.

- **A plain GET returning 403 is normal.** CalDAV uses PROPFIND.
- **The first `tailscale serve` prints an admin link.** Open it and enable Serve. In the admin console's DNS page, **HTTPS Certificates** must also be on; that's separate from MagicDNS. A certificate error right after enabling them clears within a minute or two.
- **Tasks.org says "CLEARTEXT communication not permitted"** if it's pointed at `http://` or the bare IP. Use the `https://…ts.net/` URL.
- **Phone setup:** install **Tasks.org** from F-Droid, then Add account → CalDAV, with the URL, username and password from the script's output.

## G. Calendar and tasks tools — `linux/05-plugins.sh`

The script builds and installs both plugins, then asks where the calendar lives (see the table under "How it fits together"):
- **This PC** reuses the tasks server's login, so there's nothing to type.
- **Any other option** asks for the login email, an **app password** (never the main password) and the default calendar name. Before saving, it checks the login with a PROPFIND; a 401 means a wrong email or password.

It writes the settings into the config through a private temp file.

To check it: `openclaw plugins list` shows both plugins enabled. In Signal, send `/new`, then ask "what's on my calendar this week?".

**Where to get the app password:**
- **iCloud:** account.apple.com → Sign-In and Security → App-Specific Passwords. The server is `https://caldav.icloud.com/`.
- **Fastmail:** Settings → Privacy & Security → App passwords, with access to "Calendars (CalDAV)". The server is `https://caldav.fastmail.com/dav/`.
- **Nextcloud:** Personal settings → Security → Devices & sessions → Create new app password. The server is `https://<host>/remote.php/dav/`.
- **Others:** the provider's help page for "CalDAV".

**To switch the calendar later,** re-run `05-plugins.sh` and pick another option. Events don't move automatically; export and import them.

**The plugin workflow, for any later change:**
1. In `~/.openclaw/plugins/<id>`, run `npm install`, then `npm run plugin:build`.
2. In `~/.openclaw`, run `openclaw plugins install ./plugins/<id> --force`. `--force` is expected for local code.
3. Run `openclaw plugins reload <id>`.
4. Send `/new` in Signal.

**Problems specific to plugins:**
- **The bot says a tool or parameter doesn't exist.** The tool list is cached per conversation. Send `/new`.
- **An interrupted install leaves the plugin in an `error` state.** Run `openclaw update repair`, then `openclaw doctor --fix`, then reinstall.
- **"Config changed since last load":** an install raced a config edit. Retry it.
- **`Cannot find module 'xml-js'`:** run `npm install` in the plugin folder. Both plugins list it, because tsdav's `makeCalendar` needs it.
- **`openclaw plugins` commands hang:** `openclaw gateway status` may list stale CLI clients. Kill only those PIDs (`pgrep -af 'openclaw.*plugins'`), never the gateway.

**Calendar on the phone:**
- **DAVx5** (F-Droid) syncs the calendar into Android. For "This PC", add an account with the same `https://…ts.net/` address, username and password as Tasks.org, and turn on only "Calendar". For iCloud, Fastmail and the others, use the provider's server address and app password.
- **Calendula** (F-Droid) displays it.
- **Moving off Google:** export from Google Calendar (desktop browser: Settings → Import & export → Export) to get one `.ics` per calendar. Then import:
  - **This PC:** open `https://…ts.net/.web/` in a browser on a tailnet device, log in, and upload the `.ics` as a new calendar. Tell the bot its name, or rename it.
  - **iCloud:** import with the Calendar app on a Mac, or open the `.ics` file on an iPhone.
  - **Fastmail:** Settings → Migration.

  Alarms usually don't carry over.

**How the tools behave:**
- Deletes need `confirm: true`, which the bot may set only after you explicitly confirm.
- Events accept `recurrence` and `expectedWeekday`. The weekday check exists because the model once put an event on the wrong day of the week.
- New calendars and task lists can be created from chat.

## H. Hardening and backups — `linux/06-harden.sh [backup-folder]`

The script does the following:
- Disables every plugin except `anthropic`, `signal`, `memory-core`, `calendar` and `tasks`. A default install enables about 30.
- Installs `RULES.md` and adds the kit's rules to `AGENTS.md`.
- Makes the workspace private and adds a systemd drop-in with `UMask=0077` and `DISABLE_ERROR_REPORTING=1`.
- Sets up a daily 04:00 backup timer (`Persistent=true`, so a backup missed while the PC was off runs at next boot).
- Restarts the gateway.

**Choosing the backup folder:**
- A Dropbox or OneDrive folder gives you an off-PC copy, for example `"/mnt/c/Users/<you>/Dropbox/openclaw-backups"`.
- Backups are written as `.partial` and then renamed, so sync never uploads half a file.
- If you edit the backup script from Windows (`\\wsl$`), it can lose its execute bit. Fix with `chmod 700`.

**Privacy checklist (only the human can do these):**
- [ ] On claude.ai, go to Settings → Data privacy controls and turn model training **off**.
- [ ] Turn on BitLocker (`Enable-BitLocker -MountPoint "C:" -EncryptionMethod XtsAes256 -UsedSpaceOnly -RecoveryPasswordProtector`, as administrator) and save the recovery key in a password manager.
  - The first encryption pass slows the PC. Pause it with `manage-bde -pause C:` and resume with `manage-bde -resume C:`.
- [ ] Turn on Windows Security → Core isolation → **Memory Integrity**. It's compatible with WSL2.
- [ ] **If a secret ever lands in a chat, rotate it.** Copying it elsewhere isn't enough.
- [ ] **Treat every ClawHub skill as code from a stranger.** Read it before installing.
- [ ] **Check for OpenClaw updates weekly.**

**Heartbeat:** `openclaw doctor` may migrate `HEARTBEAT.md` into the heartbeat automation's scratch. To change the checklist, use `openclaw automations list`, then `openclaw automations scratch <id> --file checklist.md`. If the heartbeat reports "HEARTBEAT.md missing", that's why. The kit's `AGENTS.md` already points at `RULES.md` instead.

**Limits of the rulebook:** it catches drift (a forgotten plugin, a reverted config), not a compromised agent. Check the logs yourself now and then.

## Reminders

The bot schedules reminders with `openclaw automations add ... --at 20m --announce --channel signal --to <owner>`. The rules in `AGENTS.md` teach it this, because its first instinct is to try `sleep`, which is blocked. Timing precision is about one minute.

## Known problems

| Symptom | Cause | Fix |
|---|---|---|
| The bot's phone shows the message; the bot never answers | Another signal-cli consumed it | Section E, operating rules |
| `User … is not registered` | Wrong signal-cli config path | Always `--config ~/.config/signal-cli`; `mv ~/.local/share/signal-cli{,.stale}` |
| Bot dead after reboot, sleep, or hours idle | WSL shut down: the keepalive process is missing | `Start-ScheduledTask "OpenClaw Keepalive"`; check section B |
| Tasks.org: "connection abort", hang or 500, after working before | 1. WSL crash-looping because the keepalive lapsed. Sign: `systemctl --user show -p MainPID` changes every ~20 s. 2. Phone off the tailnet. | 1. Start the keepalive. 2. Tailscale app on the phone: sign out and back in; check Always-on VPN and Private DNS |
| Tasks.org: CLEARTEXT not permitted | Plain HTTP URL | Use the `https://…ts.net/` URL (section F) |
| Step G says 401, or the bot says it can't log in to the calendar | Wrong email, or the main password was used instead of an app password | Make a new app password; re-run `05-plugins.sh` |
| Calendar (This PC) missing on the phone | DAVx5 account not added, or "Calendar" not ticked in DAVx5 | Section G, "Calendar on the phone" |
| Tasks list always empty (custom code) | tsdav filters to VEVENT by default | Pass a VTODO comp-filter (already done in the kit plugin) |
| Bot says a tool or parameter doesn't exist | Cached schema | `/new` |
| Plugin in `error` state | Interrupted install | `openclaw update repair`, `doctor --fix`, reinstall |
| `openclaw plugins` hangs | Stale queued CLI clients | Kill only those PIDs |
| Config rejected | Old field names or JSON5 syntax | `openclaw doctor`; section E field list |
| `ECONNREFUSED 127.0.0.1:18789` | Linger off | `sudo loginctl enable-linger $USER` |
| Event on the wrong weekday | Model date arithmetic | Ask with the weekday; the tool checks `expectedWeekday` |
| Bot tries `sleep` for reminders | Doesn't know about automations | `AGENTS.md` reminders section; `/new` |
| Heartbeat: HEARTBEAT.md missing | Migrated into the automation scratch | See section H, Heartbeat |
| Window flashes every few minutes | A task registered without `-Hidden` | Re-run `setup-autostart.ps1` |
| `Start OpenClaw` says down, but the bot replies | That probe is sometimes wrong | Trust the bot |
| Message lost right after a restart | Restart window | Resend; avoid restarts mid-conversation |
| Windows says "Access is denied" on tasks | Not an administrator window | Run as administrator |
| Credential blocked or refused by the AI | Working as intended: secrets don't go through chat | Type it into the script's hidden prompt |

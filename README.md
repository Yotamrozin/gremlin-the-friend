# Gremlin the Friend

*A private assistant that lives in your PC and talks to you on Signal.*

Your gremlin keeps your calendar and to-do list and sends you reminders. It runs on your own Windows PC and answers only your phone number. It is never exposed to the internet, and by default your calendar and tasks never leave your own devices.

**→ [Illustrated step-by-step guide](https://gremlin-the-friend.vercel.app)**

Gremlin the Friend is an unofficial setup kit for [OpenClaw](https://github.com/openclaw/openclaw). It isn't affiliated with OpenClaw, Signal, Anthropic or any calendar provider.

## What you need

| You need | Why | Cost |
|---|---|---|
| A Windows 11 PC that's usually on | Your gremlin lives here. It naps when the PC sleeps. | — |
| A **second phone number** with Signal on it | This becomes the gremlin. Never use your personal Signal number. An eSIM, a prepaid SIM or an old phone all work. | A few £/month |
| A **Claude** subscription (Pro or higher) | The gremlin's brain | Subscription |
| A free **Tailscale** account | A private network between your PC and your phone | Free |
| *Optional:* iCloud, Fastmail or another CalDAV calendar | By default your calendar lives on your own PC, for free. Pick a provider instead if you want email invitations, or a calendar that syncs while the PC is off. | Free (iCloud) or paid |

## Setup in three steps

1. **Download** this repo (Code → Download ZIP) and unzip it.
2. **Install [Claude Code](https://claude.com/claude-code)** on Windows and open it in the unzipped folder.
3. **Paste the prompt** from [`KICKOFF-PROMPT.md`](KICKOFF-PROMPT.md) into Claude Code, then follow along. It runs the scripts and tells you whenever it needs you: a password, a QR scan, or a click in the browser.

Prefer doing it by hand? Run [`windows/setup-autostart.ps1`](windows/setup-autostart.ps1) once as administrator, then run [`linux/01`](linux/) to [`06`](linux/) in order inside Ubuntu. [`GUIDE.md`](GUIDE.md) explains every step and every known problem.

## The rules for keeping a gremlin

- **Never feed it passwords.** Don't paste a password, key or code into any AI chat, including Claude Code. The scripts ask for secrets in hidden prompts.
- **Keep it out of the sunlight.** It stays off the open internet. Only your own devices can reach it, over Tailscale.
- **Don't let strangers talk to it.** It answers only your number, and groups are switched off.
- **Don't steal its mail.** Never run `signal-cli receive` yourself. Each Signal message can be picked up only once.

## What's inside

| Path | What it is |
|---|---|
| [`docs/`](docs/) | The guide website, deployed to [gremlin-the-friend.vercel.app](https://gremlin-the-friend.vercel.app) on every push |
| [`GUIDE.md`](GUIDE.md) | Technical reference, with a check for each step and a table of known problems |
| [`KICKOFF-PROMPT.md`](KICKOFF-PROMPT.md) | The prompt that lets Claude Code walk you through setup |
| [`windows/`](windows/) | Autostart: hidden scheduled tasks plus a watchdog that keeps WSL2 running |
| [`linux/`](linux/) | Six numbered install scripts, run inside Ubuntu (WSL) |
| [`plugins/`](plugins/) | The calendar (any CalDAV server) and tasks plugins for OpenClaw |
| [`workspace/`](workspace/) | The gremlin's rulebook (`RULES.md`) and additions to `AGENTS.md` |

## Status

This kit was built from one real install and tested on that machine. The scripts haven't yet been run end to end on a fresh PC, so expect rough edges. If something breaks, [GUIDE.md's "Known problems"](GUIDE.md#known-problems) is the first stop, and issues and pull requests are welcome.

## License

[MIT](LICENSE)

# Kickoff prompt for Claude Code

Open Claude Code in this kit folder, then copy everything inside the box below and paste it in.

```
I want to set up the private Signal assistant in this folder on my Windows PC.

Read README.md and GUIDE.md first. GUIDE.md is the source of truth, including its
"Known problems" section. Then walk me through the setup one step at a time, in this order:
WSL/Ubuntu, Windows autostart, linux/01 and 02, then linux/brain.sh (help me choose a brain: show me the privacy ratings and,
  for the local option, what my PC can handle), then linux/03 to 06.

How to work with me:
- I'm not a developer. Explain each step in one or two plain sentences before running it.
- Anything that needs sudo, an administrator window, a QR scan, a browser login or a password
  is something I do myself. Tell me exactly what to type or click, and wait for me to say done.
- Never ask me to paste a password, app password, token, code or QR link into this chat.
  The scripts ask for them in hidden prompts.
- Never run `signal-cli receive` or start a second signal-cli daemon.
- After each step, check that it worked (the guide says how) before moving on.
- If something fails, look it up in GUIDE.md's "Known problems" section before trying anything new.
  Don't stack fixes: if a change broke something, undo it first.
- Never restart the gateway or kill processes without telling me first.

Start by checking whether WSL and Ubuntu are already installed.
```

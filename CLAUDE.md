# Working in this repository

This repository is **public**. Everything committed here is published to GitHub and to the website.

- **Never run OpenClaw commands that write output from inside this folder.** Some (for example `openclaw sessions export-trajectory`) write into the current directory, and their output contains private conversations. Run them from your home directory, and write any exports outside this repo.
- **Never commit** OpenClaw state or output: `.openclaw/`, databases, `*.jsonl` ledgers, session exports, workspace notes, drafts, backup bundles. `.gitignore` covers the usual paths; a local pre-commit hook also checks staged paths and content.
- **Never bypass the hooks** (`--no-verify`). If a commit is blocked, find out why.
- **Before every commit, read the list of staged files** (`git status`, or the list the hook prints) and check each one, rather than relying on searches of the folders you expect.
- Examples, docs and tests use placeholders, never a real person's numbers, names, addresses or paths.

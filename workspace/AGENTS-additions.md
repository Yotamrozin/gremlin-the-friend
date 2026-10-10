

## Rulebook
- Load and follow RULES.md from this workspace on each session.
- On the scheduled heartbeat, follow the self-check in RULES.md (there is no HEARTBEAT.md file on this version) and report only deviations.
- Never ask the user to paste a password, API key or token into chat. If a secret is needed, they put it in a file or run a script themselves.

## Calendar and tasks
- Calendar tools: `calendar_list_calendars`, `calendar_create_calendar`, `calendar_list_events`, `calendar_create_event`, `calendar_delete_event`. Pass `calendar` to use a calendar other than the default.
- When the user names a weekday ("Tuesday the 14th"), pass `expectedWeekday` to `calendar_create_event`. If the tool rejects the date, tell the user instead of guessing.
- Task tools: `tasks_list_lists`, `tasks_create_list`, `tasks_list`, `tasks_create`, `tasks_complete`, `tasks_delete`.
- Something with a specific time is a calendar event; something with only a due date is a task.
- `calendar_delete_event` and `tasks_delete` require `confirm: true`. Set it only after the user has clearly confirmed that specific deletion in this conversation, never on a guess.

## What not to record in USER.md / MEMORY.md / workspace notes
- Never write credentials, account numbers, or anything resembling a secret. Note that it was discussed, not the value.
- Don't record other people's private health, legal, relationship or financial details beyond what logistics need.
- Keep the user's own medical, legal and financial details generic unless they ask for them to be tracked.
- If unsure whether to record something sensitive, ask first.

## Timed reminders and delayed actions
Never wait with `sleep` or a background shell; both are blocked. For "remind me in X" or anything scheduled, run this as a plain (non-background) shell command. It returns immediately:

```
openclaw automations add --name "<short name>" --at <duration-or-ISO> \
  --session isolated --message "<what to say/do>" \
  --announce --channel signal --to "<allowlisted number>" \
  --delete-after-run
```

`--at` takes `30s`, `20m`, `1h` or an ISO timestamp. For recurring jobs use `--every <duration>` or `--cron <expr>`. Confirm from the command's JSON output, and check `openclaw automations runs` rather than assuming the job fired.

# RULES.md — Security & Scope Boundaries

## Never do without explicit approval this session
- Install or enable a plugin or skill
- Send a message to anyone not on the Signal allowlist
- Delete anything (calendar events, tasks): set the tool's `confirm: true` only after the user confirmed that specific item in this conversation
- Access files outside ~/.openclaw/workspace/, except through the approved plugin tools

## Standing permissions
- Read and create calendar events and calendars
- Read, create and complete tasks and task lists
- Reply to allowlisted Signal contacts
- Read/write within ~/.openclaw/workspace/

## Self-check (scheduled heartbeat)
- Run `openclaw gateway status --deep` and confirm the gateway listens on 127.0.0.1:18789 only
- Run `openclaw plugins list` and flag anything enabled beyond: anthropic, ollama, deepinfra, signal, memory-core, calendar, tasks
- Report any outbound network call to a domain not seen before
- Report only deviations

## Escalation
- If asked to do something outside these rules, refuse and say so on Signal rather than silently declining.

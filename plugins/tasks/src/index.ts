import { Type, type Static } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { createDAVClient } from "tsdav";
import ical from "node-ical";

const configSchema = Type.Object({
  serverUrl: Type.String({ description: "Radicale base URL, e.g. https://your-pc-wsl.your-tailnet.ts.net/" }),
  username: Type.String(),
  password: Type.String(),
  listName: Type.Optional(
    Type.String({ description: "Default task list display name when a call doesn't specify one." }),
  ),
});
type Config = { serverUrl: string; username: string; password: string; listName?: string };

// ponytail: one client per call, no pooling — matches the calendar plugin, fine at this call volume.
async function client(config: Config) {
  return createDAVClient({
    serverUrl: config.serverUrl,
    credentials: { username: config.username, password: config.password },
    authMethod: "Basic",
    defaultAccountType: "caldav",
  });
}
type DAVClient = Awaited<ReturnType<typeof client>>;
type DAVCalendar = Awaited<ReturnType<DAVClient["fetchCalendars"]>>[number];

// Only task lists: event calendars can live on the same server account.
async function allLists(dav: DAVClient): Promise<DAVCalendar[]> {
  const all = await dav.fetchCalendars();
  return all.filter((c) => !c.components || c.components.includes("VTODO"));
}

async function pickList(dav: DAVClient, config: Config, requested?: string): Promise<DAVCalendar> {
  const name = requested ?? config.listName;
  const lists = await allLists(dav);
  const chosen = name
    ? lists.find((l) => String(l.displayName).toLowerCase() === name.toLowerCase())
    : lists[0];
  if (!chosen) {
    throw new Error(
      name
        ? `No task list named "${name}" found. Available: ${lists.map((l) => l.displayName).join(", ")}`
        : "No task list found yet — create one first in the Tasks.org app, then try again.",
    );
  }
  return chosen;
}

// RFC 5545 TEXT escaping: backslash, semicolon, comma, and literal newlines.
function escapeICSText(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");
}
function formatICSDateUTC(d: Date): string {
  return d.toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
}

function buildVTodoICS(opts: {
  uid: string;
  summary: string;
  due?: Date;
  description?: string;
  status: "NEEDS-ACTION" | "COMPLETED";
  completedAt?: Date;
}): string {
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//OpenClaw//Tasks//EN",
    "BEGIN:VTODO",
    `UID:${opts.uid}`,
    `DTSTAMP:${formatICSDateUTC(new Date())}`,
    `SUMMARY:${escapeICSText(opts.summary)}`,
    `STATUS:${opts.status}`,
  ];
  if (opts.due) lines.push(`DUE:${formatICSDateUTC(opts.due)}`);
  if (opts.description) lines.push(`DESCRIPTION:${escapeICSText(opts.description)}`);
  if (opts.status === "COMPLETED") lines.push(`COMPLETED:${formatICSDateUTC(opts.completedAt ?? new Date())}`);
  lines.push("END:VTODO", "END:VCALENDAR");
  return lines.join("\r\n");
}

const TaskOut = Type.Object(
  {
    uid: Type.String(),
    summary: Type.String(),
    status: Type.String(),
    // Local date the task was marked done. Without it a model can't tell "done today" from "done last week".
    completedOn: Type.Optional(Type.String()),
    due: Type.Optional(Type.String()),
    description: Type.Optional(Type.String()),
    list: Type.String(),
    url: Type.String(),
  },
  { additionalProperties: false },
);
type TaskOutT = Static<typeof TaskOut>;

// tsdav defaults to a VEVENT component filter when none is given (it's historically event-oriented) —
// without this, VTODO items are silently excluded from results, not an empty-list coincidence.
const VTODO_FILTER = [
  {
    "comp-filter": {
      _attributes: { name: "VCALENDAR" },
      "comp-filter": { _attributes: { name: "VTODO" } },
    },
  },
];

function localDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

async function listTasksInList(dav: DAVClient, list: DAVCalendar): Promise<TaskOutT[]> {
  const objects = await dav.fetchCalendarObjects({ calendar: list, filters: VTODO_FILTER as any });
  const tasks: TaskOutT[] = [];
  for (const obj of objects) {
    if (!obj.data) continue;
    const parsed = ical.sync.parseICS(obj.data) as Record<string, any>;
    for (const key of Object.keys(parsed)) {
      const t = parsed[key];
      if (!t || t.type !== "VTODO") continue;
      tasks.push({
        uid: String(t.uid ?? key),
        summary: t.summary ?? "(no title)",
        status: t.status ?? "NEEDS-ACTION",
        completedOn: t.completed ? localDate(new Date(t.completed)) : undefined,
        due: t.due ? new Date(t.due).toISOString() : undefined,
        description: t.description || undefined,
        list: String(list.displayName),
        url: obj.url,
      });
    }
  }
  return tasks;
}

export default defineToolPlugin({
  id: "tasks",
  name: "Tasks (self-hosted CalDAV)",
  description: "Read and write to-do items on a self-hosted Radicale CalDAV server, reachable over Tailscale.",
  configSchema,
  tools: (tool) => [
    tool({
      name: "tasks_list_lists",
      label: "List Task Lists",
      description: "List every task list available on the server, by name.",
      parameters: Type.Object({}),
      outputSchema: Type.Array(Type.Object({ name: Type.String() }, { additionalProperties: false })),
      async execute(_params, config) {
        const dav = await client(config);
        const lists = await allLists(dav);
        return lists.map((l) => ({ name: String(l.displayName) }));
      },
    }),
    tool({
      name: "tasks_create_list",
      label: "Create Task List",
      description: "Create a new task list by name. Check tasks_list_lists first to avoid creating a duplicate.",
      parameters: Type.Object({ name: Type.String() }),
      outputSchema: Type.Object({ name: Type.String(), status: Type.String() }, { additionalProperties: false }),
      async execute({ name }, config) {
        const dav = await client(config);
        const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "list";
        const url = `${config.serverUrl.replace(/\/+$/, "")}/${config.username}/${slug}/`;
        const res = await dav.makeCalendar({
          url,
          props: {
            "d:displayname": name,
            "c:supported-calendar-component-set": { "c:comp": { _attributes: { name: "VTODO" } } },
          },
          depth: "0",
        });
        const first = Array.isArray(res) ? res[0] : res;
        if (!first?.ok) return { name, status: "error" };
        return { name, status: "created" };
      },
    }),
    tool({
      name: "tasks_list",
      label: "List Tasks",
      description:
        "List tasks. Defaults to every list and every status. Pass `list` to scope to one list, or " +
        "`status` to filter (open/completed). Completed tasks carry `completedOn` (local date). To know what " +
        "was done on a given day, pass `completedOn` (YYYY-MM-DD) — never infer it from notes or the calendar.",
      parameters: Type.Object({
        list: Type.Optional(Type.String()),
        status: Type.Optional(Type.Union([Type.Literal("open"), Type.Literal("completed")])),
        completedOn: Type.Optional(
          Type.String({ description: "Only tasks completed on this local date, YYYY-MM-DD (e.g. today)." }),
        ),
      }),
      outputSchema: Type.Array(TaskOut),
      async execute({ list, status, completedOn }, config) {
        const dav = await client(config);
        const targets = list ? [await pickList(dav, config, list)] : await allLists(dav);
        const tasks: TaskOutT[] = [];
        for (const l of targets) tasks.push(...(await listTasksInList(dav, l)));
        const filtered = (
          status
            ? tasks.filter((t) => (status === "completed" ? t.status === "COMPLETED" : t.status !== "COMPLETED"))
            : tasks
        ).filter((t) => !completedOn || t.completedOn === completedOn);
        filtered.sort((a, b) => (a.due ?? "").localeCompare(b.due ?? ""));
        return filtered;
      },
    }),
    tool({
      name: "tasks_create",
      label: "Create Task",
      description: "Create a new task. Pass `list` by exact name if it's not obvious which list it belongs in.",
      parameters: Type.Object({
        summary: Type.String(),
        dueISO: Type.Optional(Type.String({ description: "Due date/time, ISO 8601." })),
        description: Type.Optional(Type.String()),
        list: Type.Optional(Type.String()),
      }),
      outputSchema: Type.Object(
        { uid: Type.String(), list: Type.String(), url: Type.String() },
        { additionalProperties: false },
      ),
      async execute({ summary, dueISO, description, list }, config) {
        const dav = await client(config);
        const target = await pickList(dav, config, list);
        const uid = `${Date.now()}-${Math.random().toString(36).slice(2)}@openclaw`;
        const ics = buildVTodoICS({
          uid,
          summary,
          due: dueISO ? new Date(dueISO) : undefined,
          description,
          status: "NEEDS-ACTION",
        });
        const filename = `${uid}.ics`;
        const res = await dav.createCalendarObject({ calendar: target, filename, iCalString: ics });
        if (!res.ok) return { status: "error", error: `CalDAV server rejected create (HTTP ${res.status}).` };
        return { uid, list: String(target.displayName), url: `${target.url}${filename}` };
      },
    }),
    tool({
      name: "tasks_complete",
      label: "Complete Task",
      description: "Mark a task done by its URL (from tasks_list or tasks_create).",
      parameters: Type.Object({
        url: Type.String(),
        list: Type.Optional(Type.String({ description: "Speeds up the lookup if known; otherwise all lists are searched." })),
      }),
      outputSchema: Type.Object({ status: Type.String() }, { additionalProperties: false }),
      async execute({ url, list }, config) {
        const dav = await client(config);
        // ponytail: avoids tsdav's objectUrls multiget, whose strict URL-matching rejected a
        // self-constructed URL in testing — the plain bulk fetch + JS-side find is slower per call
        // but reliable, and task-list sizes are small enough that it's not worth the extra complexity.
        const targets = list ? [await pickList(dav, config, list)] : await allLists(dav);
        let obj: Awaited<ReturnType<DAVClient["fetchCalendarObjects"]>>[number] | undefined;
        for (const l of targets) {
          const objects = await dav.fetchCalendarObjects({ calendar: l, filters: VTODO_FILTER as any });
          obj = objects.find((o) => o.url === url);
          if (obj) break;
        }
        if (!obj?.data) return { status: "error", error: "Task not found." };
        const parsed = ical.sync.parseICS(obj.data) as Record<string, any>;
        const todo = Object.values(parsed).find((v: any) => v?.type === "VTODO") as any;
        const ics = buildVTodoICS({
          uid: todo?.uid ?? url,
          summary: todo?.summary ?? "(task)",
          due: todo?.due ? new Date(todo.due) : undefined,
          description: todo?.description,
          status: "COMPLETED",
        });
        const res = await dav.updateCalendarObject({
          calendarObject: { url, data: ics, etag: (obj as any).etag } as any,
        });
        if (!res.ok) return { status: "error" };
        return { status: "completed" };
      },
    }),
    tool({
      name: "tasks_delete",
      label: "Delete Task",
      description:
        "Delete a task by its URL. Requires confirm=true — only after the user has clearly confirmed deleting that specific task.",
      parameters: Type.Object({
        url: Type.String(),
        confirm: Type.Boolean({ description: "Must be true. Do not set true without explicit user confirmation." }),
      }),
      outputSchema: Type.Object({ status: Type.String() }, { additionalProperties: false }),
      async execute({ url, confirm }, config) {
        if (!confirm) return { status: "blocked" };
        const dav = await client(config);
        const res = await dav.deleteCalendarObject({ calendarObject: { url } as any });
        if (!res.ok) return { status: "error" };
        return { status: "deleted" };
      },
    }),
  ],
});

import { Type, type Static } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { createDAVClient } from "tsdav";
import ical from "node-ical";
import ICalGen from "ical-generator";

import { appendFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

// Activity ledger: every real change is recorded by the tool itself, one JSON line per action, one file per
// day, so "what happened" is a lookup rather than something the model has to remember (or misremember).
function ledger(action: string, details: Record<string, unknown>): void {
  try {
    const dir = join(homedir(), ".openclaw", "workspace", "ledger");
    mkdirSync(dir, { recursive: true, mode: 0o700 });
    const d = new Date();
    const p = (n: number) => String(n).padStart(2, "0");
    const day = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    appendFileSync(join(dir, `${day}.jsonl`), JSON.stringify({ ts: d.toISOString(), action, ...details }) + "\n", { mode: 0o600 });
  } catch {
    // Never let logging break the action itself.
  }
}

const configSchema = Type.Object({
  serverUrl: Type.String({
    description:
      "CalDAV server URL. Self-hosted: your https://…ts.net/ address. iCloud: https://caldav.icloud.com/. " +
      "Fastmail: https://caldav.fastmail.com/dav/. Nextcloud: https://<host>/remote.php/dav/.",
  }),
  username: Type.String({ description: "Login name (usually your email address)." }),
  password: Type.String({ description: "App-specific password, never the account's main password." }),
  calendarName: Type.Optional(
    Type.String({ description: "Default calendar display name when a tool call doesn't specify one." }),
  ),
});

type Config = {
  serverUrl: string;
  username: string;
  password: string;
  calendarName?: string;
};

// ponytail: one client per call, no connection pooling — fine at personal-assistant call volume, add caching if this ever gets chatty.
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

// Only event calendars. Self-hosted servers keep task lists in the same account, and iCloud exposes
// Reminders lists; both are VTODO-only collections that don't belong in a calendar list.
async function allCalendars(dav: DAVClient): Promise<DAVCalendar[]> {
  const all = await dav.fetchCalendars();
  return all.filter((c) => !c.components || c.components.includes("VEVENT"));
}

// Where new calendars go: the account's calendar home. Taken from discovery when the client exposes it,
// otherwise from the parent of an existing calendar, otherwise the Radicale layout (<server>/<user>/).
async function calendarHome(dav: DAVClient, config: Config): Promise<string> {
  const discovered = (dav as any).account?.homeUrl as string | undefined;
  if (discovered) return discovered.endsWith("/") ? discovered : `${discovered}/`;
  const existing = (await dav.fetchCalendars())[0]?.url;
  if (existing) return existing.replace(/[^/]+\/?$/, "");
  return `${config.serverUrl.replace(/\/+$/, "")}/${encodeURIComponent(config.username)}/`;
}

// Resolves a calendar by name (call-time override takes precedence over the config default).
// Throws with the list of available names so a caller (model or human) can self-correct.
async function pickCalendar(dav: DAVClient, config: Config, requested?: string): Promise<DAVCalendar> {
  const name = requested ?? config.calendarName;
  const calendars = await allCalendars(dav);
  const chosen = name
    ? calendars.find((c) => String(c.displayName).toLowerCase() === name.toLowerCase())
    : calendars[0];
  if (!chosen) {
    throw new Error(
      name
        ? `No calendar named "${name}" found. Available: ${calendars.map((c) => c.displayName).join(", ")}`
        : "No calendar found on this account.",
    );
  }
  return chosen;
}

function toISO(d: Date | undefined | null): string | undefined {
  return d ? d.toISOString() : undefined;
}

// All-day events are dates, not instants. Reported as UTC they shift to the previous day anywhere ahead of
// UTC (Oct 14 in BST became "2026-10-13T23:00:00Z"), and models then dropped them from "tomorrow".
function localDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// Reads the weekday directly from an ISO date string's own Y-M-D digits — deliberately not going through
// timezone-dependent Date parsing, since the whole point is to be a reliable check independent of server
// timezone config. Models are unreliable at mental day-of-week arithmetic; this is the hard check that
// catches it instead of a prompt instruction trying to make the model "be more careful."
function weekdayOfISODate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { weekday: "long" });
}

const EventOut = Type.Object(
  {
    uid: Type.String(),
    summary: Type.String(),
    start: Type.String(),
    end: Type.Optional(Type.String()),
    allDay: Type.Boolean(),
    location: Type.Optional(Type.String()),
    description: Type.Optional(Type.String()),
    calendar: Type.String(),
    url: Type.String(),
  },
  { additionalProperties: false },
);
type EventOutT = Static<typeof EventOut>;

async function listEventsInCalendar(
  dav: DAVClient,
  cal: DAVCalendar,
  start: Date,
  end: Date,
): Promise<EventOutT[]> {
  // Fetch a day wider on each side so timezone edges can't hide all-day events, then filter precisely below.
  const DAY = 24 * 60 * 60 * 1000;
  const objects = await dav.fetchCalendarObjects({
    calendar: cal,
    timeRange: { start: new Date(start.getTime() - DAY).toISOString(), end: new Date(end.getTime() + DAY).toISOString() },
    // Server-side expansion: a repeating series comes back as its individual occurrences in this window,
    // with skipped dates and moved occurrences applied. Without it, a series only carries its first date
    // (often years ago), and "what's on tomorrow?" silently dropped every recurring event.
    expand: true,
  });
  const events: EventOutT[] = [];
  for (const obj of objects) {
    if (!obj.data) continue;
    // Expanded occurrences share one UID, so parse each VEVENT block on its own rather than letting the
    // parser merge them into one series.
    const blocks = obj.data.match(/BEGIN:VEVENT[\s\S]*?END:VEVENT/g) ?? [];
    for (const block of blocks) {
      const parsed = ical.sync.parseICS(`BEGIN:VCALENDAR
VERSION:2.0
${block}
END:VCALENDAR`) as Record<string, any>;
      const key = Object.keys(parsed).find((k) => parsed[k]?.type === "VEVENT");
      const ev = key ? parsed[key] : undefined;
      if (!ev) continue;
      const allDay = Boolean(ev.start?.dateOnly);
      const evEnd: Date = ev.end ?? ev.start;
      // Keep only events overlapping the requested range. Recurring masters are kept as before (their own
      // start date is the series start, not the occurrence).
      if (!ev.rrule) {
        const overlaps = allDay
          ? localDate(ev.start) <= localDate(new Date(end.getTime() - 1)) && localDate(new Date(evEnd.getTime() - 1)) >= localDate(start)
          : ev.start < end && evEnd > start;
        if (!overlaps) continue;
      }
      events.push({
        uid: String(ev.uid ?? key),
        summary: ev.summary ?? "(no title)",
        start: allDay ? localDate(ev.start) : toISO(ev.start)!,
        end: allDay ? localDate(new Date(evEnd.getTime() - 1)) : toISO(ev.end),
        allDay,
        location: ev.location || undefined,
        // Capped so a week's listing stays small for the model; the full text is rarely needed in a summary.
        description: ev.description ? String(ev.description).slice(0, 300) + (String(ev.description).length > 300 ? "…" : "") : undefined,
        calendar: String(cal.displayName),
        url: obj.url,
      });
    }
  }
  return events;
}

const RecurrenceFreq = Type.Union([
  Type.Literal("DAILY"),
  Type.Literal("WEEKLY"),
  Type.Literal("MONTHLY"),
  Type.Literal("YEARLY"),
]);

export default defineToolPlugin({
  id: "calendar",
  name: "Calendar (CalDAV)",
  description: "Read and write events across one or more calendars on any CalDAV server (self-hosted, iCloud, Fastmail, Nextcloud, …).",
  configSchema,
  tools: (tool) => [
    tool({
      name: "calendar_list_calendars",
      label: "List Calendars",
      description:
        "List every calendar available on this account, by name. Call this before calendar_create_event " +
        "when it's not obvious which calendar an event belongs in — don't guess the name.",
      parameters: Type.Object({}),
      outputSchema: Type.Array(
        Type.Object({ name: Type.String(), isDefault: Type.Boolean() }, { additionalProperties: false }),
      ),
      async execute(_params, config) {
        const dav = await client(config);
        const calendars = await allCalendars(dav);
        return calendars.map((c) => ({
          name: String(c.displayName),
          isDefault: config.calendarName
            ? String(c.displayName).toLowerCase() === config.calendarName.toLowerCase()
            : c === calendars[0],
        }));
      },
    }),
    tool({
      name: "calendar_create_calendar",
      label: "Create Calendar",
      description: "Create a new calendar by name. Check calendar_list_calendars first to avoid a duplicate.",
      parameters: Type.Object({ name: Type.String() }),
      outputSchema: Type.Object({ name: Type.String(), status: Type.String() }, { additionalProperties: false }),
      async execute({ name }, config) {
        const dav = await client(config);
        const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "calendar";
        const url = new URL(`${slug}/`, await calendarHome(dav, config)).toString();
        const res = await dav.makeCalendar({
          url,
          props: {
            "d:displayname": name,
            "c:supported-calendar-component-set": { "c:comp": { _attributes: { name: "VEVENT" } } },
          },
          depth: "0",
        });
        const first = Array.isArray(res) ? res[0] : res;
        if (!first?.ok) return { name, status: "error" };
        ledger("calendar_created", { name });
        return { name, status: "created" };
      },
    }),
    tool({
      name: "calendar_list_events",
      label: "List Calendar Events",
      description:
        "List calendar events in a date range (inclusive). Defaults to the next 7 days if no range given. " +
        "Defaults to searching every calendar on the account — pass `calendar` to scope it to just one. " +
        "For a single day (\"today\", \"tomorrow\", \"on Friday\") pass `date` instead of a range. " +
        "All-day events are returned with plain local dates (YYYY-MM-DD) in start/end, end inclusive.",
      parameters: Type.Object({
        date: Type.Optional(
          Type.String({ description: "One whole day, YYYY-MM-DD in the user's local time. Overrides startISO/endISO." }),
        ),
        startISO: Type.Optional(Type.String({ description: "Range start, ISO 8601. Defaults to now." })),
        endISO: Type.Optional(
          Type.String({ description: "Range end, ISO 8601. Defaults to 7 days after start." }),
        ),
        calendar: Type.Optional(
          Type.String({ description: "Limit to one calendar by name. Omit to search all calendars." }),
        ),
        minDurationDays: Type.Optional(
          Type.Integer({ description: "Only events lasting at least this many days, e.g. 3 to find trips and long blocks (possible eras)." }),
        ),
      }),
      outputSchema: Type.Array(EventOut),
      async execute({ date, startISO, endISO, calendar, minDurationDays }, config) {
        const dav = await client(config);
        let start = startISO ? new Date(startISO) : new Date();
        let end = endISO ? new Date(endISO) : new Date(start.getTime() + 7 * 24 * 60 * 60 * 1000);
        if (date) {
          const [y, m, d] = date.split("-").map(Number);
          start = new Date(y, m - 1, d);
          end = new Date(y, m - 1, d + 1);
        }

        const targets = calendar ? [await pickCalendar(dav, config, calendar)] : await allCalendars(dav);
        // All calendars at once: one round trip of waiting instead of one per calendar.
        const events: EventOutT[] = (
          await Promise.all(targets.map((cal) => listEventsInCalendar(dav, cal, start, end)))
        ).flat();
        events.sort((a, b) => a.start.localeCompare(b.start));
        if (minDurationDays) {
          // All-day events carry inclusive local dates; timed events carry instants. Either way, count whole days.
          const days = (e: EventOutT) =>
            e.allDay
              ? Math.round((Date.parse(e.end ?? e.start) - Date.parse(e.start)) / 86400000) + 1
              : (Date.parse(e.end ?? e.start) - Date.parse(e.start)) / 86400000;
          return events.filter((e) => days(e) >= minDurationDays);
        }
        return events;
      },
    }),
    tool({
      name: "calendar_create_event",
      label: "Create Calendar Event",
      description:
        "Create a new event, optionally recurring. Pass `calendar` with the exact name of the calendar it " +
        "belongs in — call calendar_list_calendars first if unsure. Falls back to the account's configured " +
        "default calendar only if `calendar` is omitted entirely.\n\n" +
        "If the user described the date relative to a weekday (\"next Wednesday\", \"this Friday\") rather than " +
        "giving an exact date, set `expectedWeekday` to that weekday name. Day-of-week arithmetic done in " +
        "reasoning is unreliable — the call is rejected (not silently wrong) if startISO doesn't actually fall " +
        "on that weekday, so recompute and retry rather than guessing twice.",
      parameters: Type.Object({
        summary: Type.String({ description: "Event title." }),
        whenAsSaid: Type.String({
          description:
            "The user's own words for when the event is, copied verbatim from their message " +
            "(e.g. \"Tuesday the 14th at 3pm\", \"tomorrow at 10\", \"next Friday\"). Required. If it names a weekday, " +
            "the tool checks it against startISO and rejects a mismatch.",
        }),
        weekdayInUserWords: Type.Union(
          ["none", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].map((d) => Type.Literal(d)),
          { description: "Did the user's message name a weekday for this event? Which one, or \"none\". Required; the tool rejects a date that falls on a different weekday." },
        ),
        startISO: Type.String({ description: "Start time, ISO 8601." }),
        endISO: Type.Optional(
          Type.String({ description: "End time, ISO 8601. Defaults to 1 hour after start." }),
        ),
        allDay: Type.Optional(Type.Boolean({ description: "All-day event. Default false." })),
        location: Type.Optional(Type.String()),
        description: Type.Optional(Type.String()),
        calendar: Type.Optional(
          Type.String({ description: "Exact name of the calendar to create this event in." }),
        ),
        expectedWeekday: Type.Optional(
          Type.String({
            description:
              "Weekday name you expect startISO to fall on (e.g. \"Wednesday\"), only if the user's request " +
              "was phrased relative to a weekday. Omit if they gave an explicit calendar date.",
          }),
        ),
        recurrence: Type.Optional(
          Type.Object(
            {
              freq: RecurrenceFreq,
              interval: Type.Optional(
                Type.Integer({ description: "Repeat every N periods, e.g. interval=4 + freq=WEEKLY = every 4 weeks. Default 1." }),
              ),
              count: Type.Optional(Type.Integer({ description: "Stop after this many occurrences." })),
              untilISO: Type.Optional(Type.String({ description: "Stop repeating after this date, ISO 8601." })),
            },
            { additionalProperties: false, description: "Omit for a one-off event." },
          ),
        ),
      }),
      outputSchema: Type.Object(
        { uid: Type.String(), calendar: Type.String(), url: Type.String() },
        { additionalProperties: false },
      ),
      async execute(
        { summary, whenAsSaid, weekdayInUserWords, startISO, endISO, allDay, location, description, calendar, expectedWeekday, recurrence },
        config,
      ) {
        // Weekday named in the user's own words: checked here, so the guard can't be skipped by the model.
        // Two independent signals: the weekday the model says the user named (required, so it can't be skipped)
        // and any weekday found in the user's words as copied.
        const fromWords = (whenAsSaid ?? "").toLowerCase().match(/(mon|tue|wed|thu|fri|sat|sun)[a-z]*/);
        const said = String(weekdayInUserWords ?? "none");
        const named = said !== "none" ? [said, said.slice(0, 3)] : fromWords;
        if (named) {
          const actual = weekdayOfISODate(startISO);
          if (!actual.toLowerCase().startsWith(named[1])) {
            return {
              status: "error",
              error:
                `The user said "${whenAsSaid}", but ${startISO.slice(0, 10)} is a ${actual}. Don't create the event: ` +
                `tell the user the date and weekday don't match and ask which one they meant.`,
            };
          }
        }
        if (expectedWeekday) {
          const actual = weekdayOfISODate(startISO);
          if (actual.toLowerCase() !== expectedWeekday.toLowerCase()) {
            return {
              status: "error",
              error:
                `startISO (${startISO.slice(0, 10)}) is a ${actual}, not a ${expectedWeekday}. ` +
                `Recompute the date from the current date given in context before retrying — do not just adjust by a day and guess again.`,
            };
          }
        }
        const dav = await client(config);
        const cal = await pickCalendar(dav, config, calendar);
        const start = new Date(startISO);
        const end = endISO ? new Date(endISO) : new Date(start.getTime() + 60 * 60 * 1000);
        const uid = `${Date.now()}-${Math.random().toString(36).slice(2)}@openclaw`;
        const gen = ICalGen({ name: "OpenClaw" });
        gen.createEvent({
          id: uid,
          start,
          end,
          allDay: Boolean(allDay),
          summary,
          location,
          description,
          // ponytail: ical-generator's freq is a real TS enum, not a plain string type; our string union
          // values match its runtime values exactly, so a cast is simpler than importing their enum.
          repeating: recurrence
            ? ({
                freq: recurrence.freq,
                interval: recurrence.interval,
                count: recurrence.count,
                until: recurrence.untilISO ? new Date(recurrence.untilISO) : undefined,
              } as any)
            : undefined,
        });
        const ics = gen.toString();
        const filename = `${uid}.ics`;
        const res = await dav.createCalendarObject({
          calendar: cal,
          filename,
          iCalString: ics,
        });
        if (!res.ok) {
          return { status: "error", error: `CalDAV server rejected create (HTTP ${res.status}).` };
        }
        ledger("event_created", { summary, start: startISO, calendar: String(cal.displayName), recurring: Boolean(recurrence) });
        return { uid, calendar: String(cal.displayName), url: `${cal.url}${filename}` };
      },
    }),
    tool({
      name: "calendar_delete_event",
      label: "Delete Calendar Event",
      description:
        "Delete an event by its URL (as returned by calendar_list_events or calendar_create_event). For a " +
        "recurring series, this deletes the whole series, not just one occurrence — say so to the user before " +
        "confirming if that's ambiguous from their request. Requires confirm=true — only set this after the " +
        "user has clearly confirmed the deletion in this conversation, not on a guess.",
      parameters: Type.Object({
        eventUrl: Type.String({ description: "The event's CalDAV URL." }),
        confirm: Type.Boolean({
          description: "Must be true. Safety gate — do not set true without explicit user confirmation.",
        }),
      }),
      outputSchema: Type.Object({ status: Type.String() }, { additionalProperties: false }),
      async execute({ eventUrl, confirm }, config) {
        if (!confirm) {
          return { status: "blocked", error: "Deletion requires confirm=true after explicit user confirmation." };
        }
        const dav = await client(config);
        const res = await dav.deleteCalendarObject({ calendarObject: { url: eventUrl } as any });
        if (!res.ok) {
          return { status: "error" };
        }
        ledger("event_deleted", { url: eventUrl });
        return { status: "deleted" };
      },
    }),
  ],
});

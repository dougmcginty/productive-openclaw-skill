---
name: productive
description: Explicit-only Productive.io timesheet helper for Claude. Use only when the user explicitly asks to use Productive, productive.io, or their Productive timesheet.
---

# Productive.io Timesheets

Use this skill only when the user explicitly asks for Productive/Productive.io timesheet work. Do not invoke it implicitly for generic time-tracking requests, Toggl work, calendars, invoices, or project planning.

This skill wraps a local stdlib Python CLI:

- Script: `scripts/productive_cli.py`

## Required Environment

The script auto-loads variables from `~/.openclaw/.env` and then `~/.openclaw/workspace/.env` when those files exist. It also works with normal shell environment variables:

- `PRODUCTIVE_API_TOKEN`
- `PRODUCTIVE_ORGANIZATION_ID`
- `PRODUCTIVE_PERSON_ID`

Optional:

- `PRODUCTIVE_API_BASE`, defaults to `https://api.productive.io/api/v2`

Never ask the user to paste API tokens into chat. If credentials are missing, tell them which environment variable is missing and that it should be configured locally.

## Common Commands

Check configuration without making an API call:

```bash
python3 scripts/productive_cli.py env-check
```

List the configured Productive person's scheduled bookings for a date range:

```bash
python3 scripts/productive_cli.py scheduled --from 2026-09-14 --to 2026-09-20
```

Search services, which are the objects Productive time entries are created against:

```bash
python3 scripts/productive_cli.py services --query "Client or project text"
```

Add a completed time entry:

```bash
python3 scripts/productive_cli.py add-time --date 2026-09-14 --hours 1 --service-id 123456 --note "Work note"
```

Use `--dry-run` before mutating when the target service is uncertain.

## Operating Notes

- Productive time entries require `service_id`, `person_id`, `date`, and `time` in minutes.
- Scheduled work is pulled from Productive bookings filtered by `PRODUCTIVE_PERSON_ID`.
- Prefer `scheduled` first when the user asks to add time to a project they are scheduled on. Use the booking's `service_id` for the time entry.
- If service lookup returns multiple plausible services, stop and ask the user to choose. Do not guess and create time.
- Always confirm the project/service, date, duration, and note after creating a time entry.

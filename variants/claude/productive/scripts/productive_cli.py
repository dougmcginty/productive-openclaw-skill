#!/usr/bin/env python3
"""Small Productive.io timesheet CLI for OpenClaw skills.

Uses only the Python standard library. Productive API reference:
https://developer.productive.io/reference
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://api.productive.io/api/v2"
ENV_FILES = (Path.home() / ".openclaw/.env", Path.home() / ".openclaw/workspace/.env")


class ProductiveError(RuntimeError):
    pass


def load_env_files() -> None:
    for path in ENV_FILES:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ProductiveError(f"Missing required environment variable: {name}")
    return value


def productive_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
        "X-Auth-Token": require_env("PRODUCTIVE_API_TOKEN"),
        "X-Organization-Id": require_env("PRODUCTIVE_ORGANIZATION_ID"),
    }


def base_url() -> str:
    return os.environ.get("PRODUCTIVE_API_BASE", DEFAULT_BASE_URL).rstrip("/")


def person_id() -> int:
    return int(require_env("PRODUCTIVE_PERSON_ID"))


def encode_params(params: dict[str, Any]) -> str:
    clean: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        clean[key] = value
    return urllib.parse.urlencode(clean, doseq=True)


def request(method: str, path: str, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    query = f"?{encode_params(params or {})}" if params else ""
    url = f"{base_url()}{path}{query}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method.upper(), headers=productive_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            details = json.dumps(json.loads(raw), indent=2)
        except json.JSONDecodeError:
            details = raw
        raise ProductiveError(f"Productive API {exc.code} for {method} {path}:\n{details}") from exc
    except urllib.error.URLError as exc:
        raise ProductiveError(f"Productive API request failed: {exc}") from exc


def iter_collection(path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    params = dict(params)
    params.setdefault("page[size]", 100)
    items: list[dict[str, Any]] = []
    while True:
        doc = request("GET", path, params=params)
        data = doc.get("data") or []
        if isinstance(data, dict):
            data = [data]
        included = doc.get("included") or []
        include_index = {(str(item.get("type")), str(item.get("id"))): item for item in included}
        for item in data:
            item["_included_index"] = include_index
            items.append(item)
        next_url = ((doc.get("links") or {}).get("next"))
        if not next_url:
            break
        parsed = urllib.parse.urlparse(next_url)
        params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    return items


def attrs(resource: dict[str, Any]) -> dict[str, Any]:
    return resource.get("attributes") or {}


def resource_id(resource: dict[str, Any]) -> str:
    return str(resource.get("id", ""))


def relationship_id(resource: dict[str, Any], rel_name: str) -> str:
    relationships = resource.get("relationships") or {}
    rel = relationships.get(rel_name) or {}
    data = rel.get("data")
    if isinstance(data, dict):
        return str(data.get("id") or "")
    return ""


def included_name(resource: dict[str, Any], rel_name: str) -> str:
    relationships = resource.get("relationships") or {}
    rel = relationships.get(rel_name) or {}
    data = rel.get("data")
    if not isinstance(data, dict):
        return ""
    key = (str(data.get("type")), str(data.get("id")))
    included = (resource.get("_included_index") or {}).get(key)
    if not included:
        return ""
    inc_attrs = attrs(included)
    return str(inc_attrs.get("name") or inc_attrs.get("title") or "")


def public_json(value: Any) -> Any:
    if isinstance(value, list):
        return [public_json(item) for item in value]
    if isinstance(value, dict):
        return {str(k): public_json(v) for k, v in value.items() if k != "_included_index"}
    return value


def print_json(value: Any) -> None:
    print(json.dumps(public_json(value), indent=2, sort_keys=True))


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def minutes_from_args(args: argparse.Namespace) -> int:
    total = 0
    if args.hours is not None:
        total += int(round(float(args.hours) * 60))
    if args.minutes is not None:
        total += int(args.minutes)
    if total <= 0:
        raise ProductiveError("Provide a positive duration with --hours and/or --minutes")
    return total


def add_common_date_range(parser: argparse.ArgumentParser) -> None:
    today = date.today()
    parser.add_argument("--from", dest="from_date", type=parse_date, default=today.isoformat(), help="Start date, YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", type=parse_date, default=today.isoformat(), help="End date, YYYY-MM-DD")


def cmd_env_check(_: argparse.Namespace) -> None:
    values = {
        "PRODUCTIVE_API_TOKEN": "set" if os.environ.get("PRODUCTIVE_API_TOKEN") else "missing",
        "PRODUCTIVE_ORGANIZATION_ID": os.environ.get("PRODUCTIVE_ORGANIZATION_ID") or "missing",
        "PRODUCTIVE_PERSON_ID": os.environ.get("PRODUCTIVE_PERSON_ID") or "missing",
        "PRODUCTIVE_API_BASE": base_url(),
    }
    print_json(values)


def cmd_scheduled(args: argparse.Namespace) -> None:
    params = {
        "filter[person_id]": args.person_id or person_id(),
        "filter[after]": args.from_date.isoformat() if isinstance(args.from_date, date) else args.from_date,
        "filter[before]": args.to_date.isoformat() if isinstance(args.to_date, date) else args.to_date,
        "filter[with_draft]": args.with_draft,
        "include": "service,project,person",
        "sort": "started_on",
    }
    bookings = iter_collection("/bookings", params)
    if args.json:
        print_json(bookings)
        return
    if not bookings:
        print("No scheduled bookings found.")
        return
    for booking in bookings:
        a = attrs(booking)
        service_name = included_name(booking, "service")
        project_name = included_name(booking, "project")
        mins = a.get("time")
        hours = f"{mins / 60:.2f}h" if isinstance(mins, int) else ""
        print(
            "\t".join(
                [
                    f"booking={resource_id(booking)}",
                    f"{a.get('started_on')}..{a.get('ended_on')}",
                    hours,
                    f"service_id={a.get('service_id') or relationship_id(booking, 'service') or '-'}",
                    f"project_id={a.get('project_id') or relationship_id(booking, 'project') or '-'}",
                    service_name or "-",
                    project_name or "-",
                    a.get("note") or "",
                ]
            )
        )


def cmd_services(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"include": "project,company,person", "sort": "name"}
    if args.query:
        params["filter[name][contains]"] = args.query
    if args.project_id:
        params["filter[project_id]"] = args.project_id
    if args.person_id:
        params["filter[person_id]"] = args.person_id
    services = iter_collection("/services", params)
    if args.json:
        print_json(services)
        return
    if not services:
        print("No services found.")
        return
    for service in services:
        a = attrs(service)
        print(
            "\t".join(
                [
                    f"service_id={resource_id(service)}",
                    str(a.get("name") or "-"),
                    f"project_id={a.get('project_id') or relationship_id(service, 'project') or '-'}",
                    included_name(service, "project") or "-",
                    included_name(service, "company") or "-",
                ]
            )
        )


def cmd_projects(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"include": "company", "sort": "name"}
    if args.query:
        params["filter[name][contains]"] = args.query
    if args.person_id:
        params["filter[person_id]"] = args.person_id
    projects = iter_collection("/projects", params)
    if args.json:
        print_json(projects)
        return
    if not projects:
        print("No projects found.")
        return
    for project in projects:
        a = attrs(project)
        print(
            "\t".join(
                [
                    f"project_id={resource_id(project)}",
                    str(a.get("name") or "-"),
                    included_name(project, "company") or "-",
                ]
            )
        )


def resolve_service_id(args: argparse.Namespace) -> int:
    if args.service_id:
        return int(args.service_id)
    if args.booking_id:
        doc = request("GET", f"/bookings/{args.booking_id}")
        data = doc.get("data") or {}
        service = attrs(data).get("service_id") or relationship_id(data, "service")
        if not service:
            raise ProductiveError(f"Booking {args.booking_id} did not include service_id")
        return int(service)
    if args.service_query:
        params: dict[str, Any] = {"filter[name][contains]": args.service_query}
        if args.project_id:
            params["filter[project_id]"] = args.project_id
        matches = iter_collection("/services", params)
        if len(matches) != 1:
            print("Service lookup did not resolve to exactly one service.", file=sys.stderr)
            for service in matches[:20]:
                a = attrs(service)
                print(f"service_id={resource_id(service)}\t{a.get('name')}\tproject_id={a.get('project_id')}", file=sys.stderr)
            raise ProductiveError(f"Expected 1 service match, found {len(matches)}")
        return int(resource_id(matches[0]))
    raise ProductiveError("Provide --service-id, --booking-id, or --service-query")


def cmd_add_time(args: argparse.Namespace) -> None:
    service = resolve_service_id(args)
    minutes = minutes_from_args(args)
    payload = {
        "data": {
            "type": "time_entries",
            "attributes": {
                "service_id": service,
                "person_id": args.person_id or person_id(),
                "date": args.date.isoformat() if isinstance(args.date, date) else args.date,
                "time": minutes,
                "note": args.note,
            },
        }
    }
    if args.task_id:
        payload["data"]["attributes"]["task_id"] = int(args.task_id)
    if args.started_at:
        payload["data"]["attributes"]["started_at"] = args.started_at
    if args.dry_run:
        print_json(payload)
        return
    doc = request("POST", "/time_entries", payload=payload)
    created = doc.get("data") or {}
    print_json(
        {
            "created_time_entry_id": created.get("id"),
            "service_id": service,
            "person_id": payload["data"]["attributes"]["person_id"],
            "date": payload["data"]["attributes"]["date"],
            "minutes": minutes,
            "note": args.note,
        }
    )


def cmd_time_entries(args: argparse.Namespace) -> None:
    params = {
        "filter[person_id]": args.person_id or person_id(),
        "filter[after]": args.from_date.isoformat() if isinstance(args.from_date, date) else args.from_date,
        "filter[before]": (args.to_date + timedelta(days=1)).isoformat() if isinstance(args.to_date, date) else args.to_date,
        "include": "service,person",
        "sort": "date",
    }
    entries = iter_collection("/time_entries", params)
    if args.json:
        print_json(entries)
        return
    if not entries:
        print("No time entries found.")
        return
    for entry in entries:
        a = attrs(entry)
        mins = a.get("time")
        hours = f"{mins / 60:.2f}h" if isinstance(mins, int) else ""
        print(
            "\t".join(
                [
                    f"time_entry={resource_id(entry)}",
                    str(a.get("date") or "-"),
                    hours,
                    f"service_id={a.get('service_id') or relationship_id(entry, 'service') or '-'}",
                    included_name(entry, "service") or "-",
                    a.get("note") or "",
                ]
            )
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Productive.io timesheet helper")
    sub = parser.add_subparsers(dest="command", required=True)

    env_check = sub.add_parser("env-check", help="Show whether Productive env vars are configured")
    env_check.set_defaults(func=cmd_env_check)

    scheduled = sub.add_parser("scheduled", help="List scheduled bookings")
    add_common_date_range(scheduled)
    scheduled.add_argument("--person-id", type=int, help="Override PRODUCTIVE_PERSON_ID")
    scheduled.add_argument("--with-draft", action="store_true", help="Include tentative bookings")
    scheduled.add_argument("--json", action="store_true", help="Print raw JSON")
    scheduled.set_defaults(func=cmd_scheduled)

    services = sub.add_parser("services", help="Search Productive services")
    services.add_argument("--query", help="Filter service name contains text")
    services.add_argument("--project-id", type=int, help="Filter to a project ID")
    services.add_argument("--person-id", type=int, help="Filter to a person ID")
    services.add_argument("--json", action="store_true", help="Print raw JSON")
    services.set_defaults(func=cmd_services)

    projects = sub.add_parser("projects", help="Search Productive projects")
    projects.add_argument("--query", help="Filter project name contains text")
    projects.add_argument("--person-id", type=int, help="Filter to a person ID")
    projects.add_argument("--json", action="store_true", help="Print raw JSON")
    projects.set_defaults(func=cmd_projects)

    add_time = sub.add_parser("add-time", help="Create a completed time entry")
    add_time.add_argument("--date", type=parse_date, default=date.today().isoformat(), help="Entry date, YYYY-MM-DD")
    add_time.add_argument("--hours", type=float, help="Duration hours")
    add_time.add_argument("--minutes", type=int, help="Additional duration minutes")
    add_time.add_argument("--note", required=True, help="Time entry note")
    add_time.add_argument("--person-id", type=int, help="Override PRODUCTIVE_PERSON_ID")
    target = add_time.add_mutually_exclusive_group(required=True)
    target.add_argument("--service-id", type=int, help="Productive service ID")
    target.add_argument("--booking-id", type=int, help="Resolve service ID from a booking")
    target.add_argument("--service-query", help="Resolve service by unique name contains match")
    add_time.add_argument("--project-id", type=int, help="Constrain --service-query to a project")
    add_time.add_argument("--task-id", type=int, help="Optional Productive task ID")
    add_time.add_argument("--started-at", help="Optional ISO datetime for started_at")
    add_time.add_argument("--dry-run", action="store_true", help="Print payload without creating")
    add_time.set_defaults(func=cmd_add_time)

    entries = sub.add_parser("time-entries", help="List existing time entries")
    add_common_date_range(entries)
    entries.add_argument("--person-id", type=int, help="Override PRODUCTIVE_PERSON_ID")
    entries.add_argument("--json", action="store_true", help="Print raw JSON")
    entries.set_defaults(func=cmd_time_entries)

    return parser


def main() -> int:
    load_env_files()
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
        return 0
    except ProductiveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

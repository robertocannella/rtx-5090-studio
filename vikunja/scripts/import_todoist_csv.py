"""Import a Todoist project CSV export into Vikunja via its REST API.

Usage (from a container on the same Docker network as vikunja):
    VIKUNJA_URL=http://vikunja:3456 VIKUNJA_TOKEN=... \
        python3 import_todoist_csv.py Work.csv [--project "Work"] [--export-date 2026-10-02]

Mapping:
  - The CSV becomes one Vikunja project (named after the file unless --project is given).
  - Todoist sections become Kanban buckets, in order; tasks land in their section's bucket.
    Vikunja's default Kanban buckets are removed once the sections exist.
  - "note" rows become comments on the task directly above them.
  - "reminder" rows (relative, offset N minutes) become a reminder N minutes before the
    task above them is due.
  - Todoist CSV priority 1 (p1, highest) .. 4 (p4, default) -> Vikunja 4 (urgent) .. 0 (unset).
  - Due dates: only the forms in this export are understood -- "today at HH:MM",
    "tomorrow [at HH:MM]", ISO dates, and "every day/week/month" (weekly etc. repeat,
    first due on the export date). Anything else is kept verbatim in the description.
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

URL = os.environ.get("VIKUNJA_URL", "http://vikunja:3456").rstrip("/") + "/api/v1"
TOKEN = os.environ["VIKUNJA_TOKEN"]

REPEATS = {"day": 86400, "week": 7 * 86400, "month": None}  # month uses repeat_mode=1


def api(method, path, body=None):
    req = urllib.request.Request(
        URL + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> {e.code}: {e.read().decode(errors='replace')}")


def parse_due(text, tz, export_date):
    """Returns (due_datetime_or_None, repeat_after_seconds, repeat_mode, unparsed_text)."""
    t = (text or "").strip().lower()
    if not t:
        return None, 0, 0, ""
    m = re.fullmatch(r"every (day|week|month)", t)
    if m:
        due = datetime.combine(export_date, datetime.min.time().replace(hour=9), tz)
        unit = m.group(1)
        if unit == "month":
            return due, 0, 1, ""
        return due, REPEATS[unit], 0, ""
    m = re.fullmatch(r"(today|tomorrow)(?: at (\d{1,2}):(\d{2}))?", t)
    if m:
        d = export_date + timedelta(days=1 if m.group(1) == "tomorrow" else 0)
        hh, mm = (int(m.group(2)), int(m.group(3))) if m.group(2) else (9, 0)
        return datetime.combine(d, datetime.min.time().replace(hour=hh, minute=mm), tz), 0, 0, ""
    try:
        d = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=tz)), 0, 0, ""
    except ValueError:
        return None, 0, 0, text.strip()


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("TYPE")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--project")
    ap.add_argument("--export-date", help="date the export was taken (resolves 'today'); default: today")
    args = ap.parse_args()

    export_date = date.fromisoformat(args.export_date) if args.export_date else date.today()
    rows = read_rows(args.csv)
    title = args.project or Path(args.csv).stem

    existing = [p for p in api("GET", "/projects") if p["title"] == title]
    if existing:
        sys.exit(f"a project named {title!r} already exists (id {existing[0]['id']}) -- refusing to duplicate")

    project = api("PUT", "/projects", {"title": title})
    pid = project["id"]
    views = api("GET", f"/projects/{pid}/views")
    kanban = next(v for v in views if v["view_kind"] == "kanban")
    vid = kanban["id"]
    default_buckets = api("GET", f"/projects/{pid}/views/{vid}/buckets")

    buckets = {}
    current_bucket = None
    last_task = None
    counts = {"tasks": 0, "comments": 0, "reminders": 0, "sections": 0}

    for r in rows:
        kind = r["TYPE"]
        if kind == "section":
            b = api("PUT", f"/projects/{pid}/views/{vid}/buckets", {"title": r["CONTENT"]})
            buckets[r["CONTENT"]] = b["id"]
            current_bucket = b["id"]
            counts["sections"] += 1
        elif kind == "task":
            tz = ZoneInfo(r.get("TIMEZONE") or "UTC")
            due, repeat_after, repeat_mode, unparsed = parse_due(r["DATE"], tz, export_date)
            desc = r["DESCRIPTION"] or ""
            if unparsed:
                desc = (desc + "\n\n" if desc else "") + f"Todoist due: {unparsed}"
            prio = int(r["PRIORITY"] or 4)
            body = {
                "title": r["CONTENT"],
                "description": desc,
                "priority": {1: 4, 2: 3, 3: 2}.get(prio, 0),
                "repeat_after": repeat_after,
                "repeat_mode": repeat_mode,
            }
            if due:
                body["due_date"] = due.isoformat()
            last_task = api("PUT", f"/projects/{pid}/tasks", body)
            if current_bucket:
                api("POST", f"/projects/{pid}/views/{vid}/buckets/{current_bucket}/tasks",
                    {"task_id": last_task["id"]})
            # Vikunja shows newly created tasks first; explicit positions keep Todoist's order.
            counts["tasks"] += 1
            for view in views:
                api("POST", f"/tasks/{last_task['id']}/position",
                    {"project_view_id": view["id"], "task_id": last_task["id"],
                     "position": counts["tasks"] * 1000})
        elif kind == "note" and last_task:
            api("PUT", f"/tasks/{last_task['id']}/comments", {"comment": r["CONTENT"]})
            counts["comments"] += 1
        elif kind == "reminder" and last_task and r.get("REMINDER_TYPE") == "relative":
            offset_s = -60 * int(r.get("REMINDER_OFFSET") or 0)
            task = api("GET", f"/tasks/{last_task['id']}")
            task["reminders"] = (task.get("reminders") or []) + [
                {"relative_to": "due_date", "relative_period": offset_s}]
            api("POST", f"/tasks/{last_task['id']}", task)
            counts["reminders"] += 1

    if buckets:
        # Point the view at a section bucket first -- Vikunja won't delete the bucket that's
        # currently the view's default (or done) bucket.
        api("POST", f"/projects/{pid}/views/{vid}",
            {**kanban, "default_bucket_id": next(iter(buckets.values())), "done_bucket_id": 0})
        for b in default_buckets:
            api("DELETE", f"/projects/{pid}/views/{vid}/buckets/{b['id']}")

    print(f"Imported into project {title!r} (id {pid}): " + ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    main()

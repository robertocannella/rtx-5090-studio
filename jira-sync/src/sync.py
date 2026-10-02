"""One-way Jira Cloud -> Vikunja sync.

Every SYNC_INTERVAL seconds, fetches the issues matched by JIRA_JQL and mirrors each one as
a task in a dedicated Vikunja project (VIKUNJA_PROJECT, created on first run with Kanban
buckets "To Do" / "In Progress" / "Done", the last one being the done bucket).

Jira is the source of truth, but only for issues that changed: a task is rewritten only
when its issue's `updated` timestamp moves, so edits/moves made in Vikunja in between are
left alone. A task deleted in Vikunja is remembered and never recreated.

State (issue key -> task id + last-seen `updated`, and the project/bucket ids) lives in
STATE_PATH as JSON.
"""

import base64
import html
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("jira-sync")

BUCKETS = ["To Do", "In Progress", "Done"]
# Jira statusCategory.key -> bucket title
CATEGORY_BUCKET = {"new": "To Do", "indeterminate": "In Progress", "done": "Done"}
# Jira priority name -> Vikunja priority (0 unset, 1 low .. 4 urgent, 5 do now)
PRIORITY = {"Highest": 4, "High": 3, "Medium": 2, "Low": 1, "Lowest": 1}


class HTTPError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status


def http(method, url, headers, body=None):
    req = urllib.request.Request(
        url, method=method, headers={"Content-Type": "application/json", **headers},
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise HTTPError(e.code, e.read().decode(errors="replace")) from e


class Jira:
    def __init__(self, base_url, email, token):
        self.base = base_url.rstrip("/")
        auth = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}

    def search(self, jql):
        issues, token = [], None
        while True:
            q = {"jql": jql, "maxResults": 100, "expand": "renderedFields",
                 "fields": "summary,status,duedate,priority,updated,description"}
            if token:
                q["nextPageToken"] = token
            page = http("GET", f"{self.base}/rest/api/3/search/jql?{urllib.parse.urlencode(q)}", self.headers)
            issues += page.get("issues", [])
            token = page.get("nextPageToken")
            if page.get("isLast", True) or not token:
                return issues


class Vikunja:
    def __init__(self, base_url, token):
        self.base = base_url.rstrip("/") + "/api/v1"
        self.headers = {"Authorization": f"Bearer {token}"}

    def __call__(self, method, path, body=None):
        return http(method, self.base + path, self.headers, body)


def task_fields(issue, jira_base, tz):
    """The Vikunja task fields derived from a Jira issue (pure; unit-tested)."""
    f = issue["fields"]
    key = issue["key"]
    url = f"{jira_base.rstrip('/')}/browse/{key}"
    rendered = (issue.get("renderedFields") or {}).get("description") or ""
    description = f'<p><a href="{html.escape(url)}">{html.escape(key)} in Jira</a></p>' + rendered
    due = None
    if f.get("duedate"):
        due = datetime.combine(date.fromisoformat(f["duedate"]), dtime(9, 0), tz).isoformat()
    category = ((f.get("status") or {}).get("statusCategory") or {}).get("key", "new")
    return {
        "title": f"{key}: {f.get('summary') or ''}".strip(),
        "description": description,
        "due_date": due,
        "priority": PRIORITY.get((f.get("priority") or {}).get("name"), 0),
        "done": category == "done",
        "bucket": CATEGORY_BUCKET.get(category, "To Do"),
    }


class Syncer:
    def __init__(self, jira, vk, state_path, project_title, jira_base, tz):
        self.jira, self.vk = jira, vk
        self.state_path = Path(state_path)
        self.project_title = project_title
        self.jira_base = jira_base
        self.tz = tz
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.state.setdefault("issues", {})

    def save(self):
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, sort_keys=True))
        tmp.replace(self.state_path)

    def ensure_project(self):
        """Creates the project + buckets once; later runs reuse the saved ids."""
        if self.state.get("project_id"):
            return
        existing = [p for p in self.vk("GET", "/projects") if p["title"] == self.project_title]
        if existing:
            raise SystemExit(f"Vikunja project {self.project_title!r} exists but isn't in state "
                             f"({self.state_path}) -- rename/delete it or restore the state file")
        pid = self.vk("PUT", "/projects", {"title": self.project_title})["id"]
        kanban = next(v for v in self.vk("GET", f"/projects/{pid}/views") if v["view_kind"] == "kanban")
        vid = kanban["id"]
        defaults = self.vk("GET", f"/projects/{pid}/views/{vid}/buckets")
        ids = {t: self.vk("PUT", f"/projects/{pid}/views/{vid}/buckets", {"title": t})["id"] for t in BUCKETS}
        self.vk("POST", f"/projects/{pid}/views/{vid}",
                {**kanban, "default_bucket_id": ids["To Do"], "done_bucket_id": ids["Done"]})
        for b in defaults:
            self.vk("DELETE", f"/projects/{pid}/views/{vid}/buckets/{b['id']}")
        self.state.update(project_id=pid, view_id=vid, buckets=ids)
        self.save()
        log.info("created Vikunja project %r (id %s)", self.project_title, pid)

    def move(self, task_id, bucket):
        pid, vid = self.state["project_id"], self.state["view_id"]
        self.vk("POST", f"/projects/{pid}/views/{vid}/buckets/{self.state['buckets'][bucket]}/tasks",
                {"task_id": task_id})

    def sync_issue(self, issue):
        key, updated = issue["key"], issue["fields"].get("updated")
        entry = self.state["issues"].get(key)
        if entry and (entry.get("deleted") or entry.get("updated") == updated):
            return None
        want = task_fields(issue, self.jira_base, self.tz)
        bucket = want.pop("bucket")
        if entry is None:
            body = {k: v for k, v in want.items() if v is not None and k != "done"}
            task = self.vk("PUT", f"/projects/{self.state['project_id']}/tasks", body)
            self.move(task["id"], bucket)  # the Done bucket also marks it done
            self.state["issues"][key] = {"task_id": task["id"], "updated": updated}
            return "created"
        try:
            task = self.vk("GET", f"/tasks/{entry['task_id']}")
        except HTTPError as e:
            if e.status == 404:
                self.state["issues"][key] = {**entry, "deleted": True}
                return "deleted-in-vikunja"
            raise
        task.update({k: v for k, v in want.items() if k != "done"})
        if want["due_date"] is None:
            task["due_date"] = "0001-01-01T00:00:00Z"
        if not want["done"]:
            task["done"] = False
        self.vk("POST", f"/tasks/{task['id']}", task)
        self.move(task["id"], bucket)
        self.state["issues"][key] = {"task_id": task["id"], "updated": updated}
        return "updated"

    def run_once(self, jql):
        self.ensure_project()
        counts = {}
        for issue in self.jira.search(jql):
            result = self.sync_issue(issue)
            if result:
                counts[result] = counts.get(result, 0) + 1
                log.info("%s %s", result, issue["key"])
        self.save()
        return counts


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    env = os.environ
    jira_base = env["JIRA_BASE_URL"]
    syncer = Syncer(
        Jira(jira_base, env["JIRA_EMAIL"], env["JIRA_API_TOKEN"]),
        Vikunja(env.get("VIKUNJA_URL", "http://vikunja:3456"), env["VIKUNJA_TOKEN"]),
        env.get("STATE_PATH", "/data/state.json"),
        env.get("VIKUNJA_PROJECT", "Jira"),
        jira_base,
        ZoneInfo(env.get("TZ", "America/New_York")),
    )
    jql = env.get("JIRA_JQL", "assignee = currentUser() AND (statusCategory != Done OR updated >= -14d) ORDER BY updated DESC")
    interval = int(env.get("SYNC_INTERVAL", "300"))
    once = env.get("SYNC_ONCE") == "1"
    while True:
        try:
            counts = syncer.run_once(jql)
            log.info("sync done: %s", counts or "no changes")
        except (HTTPError, urllib.error.URLError, TimeoutError) as e:
            log.error("sync failed: %s", e)
            if once:
                raise
        if once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()

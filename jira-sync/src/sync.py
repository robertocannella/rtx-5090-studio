"""One-way Jira Cloud -> Vikunja sync.

Every SYNC_INTERVAL seconds, fetches the issues matched by JIRA_JQL -- narrowed, when
JIRA_TEAM_ID is set, to issues whose Primary Developer (JIRA_PRIMARY_DEV_FIELD) is a member of
that Atlassian team, re-read each run -- and mirrors each one as a task in a dedicated Vikunja project (VIKUNJA_PROJECT, created on first run with Kanban
buckets "To Do" / "In Progress" / "Done", the last one being the done bucket).

Jira is the source of truth, but only for issues that changed: a task is rewritten only
when its issue's `updated` timestamp moves, so edits/moves made in Vikunja in between are
left alone. A task deleted in Vikunja is remembered and never recreated. Each Primary
Developer becomes a Vikunja label on the task; only those developer labels are ever added or
removed, so labels added by hand are kept.

State (issue key -> task id + last-seen `updated`, and the project/bucket ids) lives in
STATE_PATH as JSON.
"""

import base64
import html
import json
import logging
import os
import re
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

    def team_member_ids(self, org_id, team_id):
        """Account ids of an Atlassian Team's members (Teams public API)."""
        ids, after = [], None
        while True:
            body = {"first": 50, **({"after": after} if after else {})}
            page = http("POST", f"{self.base}/gateway/api/public/teams/v1/org/{org_id}/teams/{team_id}/members",
                        self.headers, body)
            ids += [m["accountId"] for m in page.get("results", [])]
            info = page.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                return ids
            after = info.get("endCursor")

    def search(self, jql, extra_fields=()):
        issues, token = [], None
        while True:
            q = {"jql": jql, "maxResults": 100, "expand": "renderedFields",
                 "fields": ",".join(["summary", "status", "duedate", "priority", "updated", "description",
                                     *extra_fields])}
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


def team_jql(base_jql, dev_field, account_ids):
    """Narrows base_jql to issues whose people-field dev_field holds one of account_ids."""
    base_jql = re.split(r"\s+ORDER\s+BY\s+", base_jql, flags=re.IGNORECASE)[0]
    num = dev_field.removeprefix("customfield_")
    ids = ", ".join(f'"{a}"' for a in account_ids)
    return f"({base_jql}) AND cf[{num}] in ({ids}) ORDER BY updated DESC"


def task_fields(issue, jira_base, tz, dev_field=None):
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
        "developers": sorted({u.get("displayName") for u in (f.get(dev_field) or []) if u.get("displayName")})
        if dev_field else [],
    }


class Syncer:
    def __init__(self, jira, vk, state_path, project_title, jira_base, tz,
                 dev_field=None, team=None):
        self.jira, self.vk = jira, vk
        self.dev_field = dev_field
        self.team = team  # (org_id, team_id) or None
        self.state_path = Path(state_path)
        self.project_title = project_title
        self.jira_base = jira_base
        self.tz = tz
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.state.setdefault("issues", {})
        self.state.setdefault("labels", {})  # developer name -> Vikunja label id

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

    def label_id(self, name):
        if name not in self.state["labels"]:
            found = [l for l in self.vk("GET", "/labels?" + urllib.parse.urlencode({"s": name})) or []
                     if l["title"] == name]
            self.state["labels"][name] = found[0]["id"] if found else self.vk("PUT", "/labels", {"title": name})["id"]
        return self.state["labels"][name]

    def set_developer_labels(self, task_id, names):
        """Makes the task's developer labels exactly `names`, leaving any other labels alone."""
        dev_ids = set(self.state["labels"].values())
        current = {l["id"] for l in (self.vk("GET", f"/tasks/{task_id}").get("labels") or [])}
        want = {self.label_id(n) for n in names}
        for lid in want - current:
            self.vk("PUT", f"/tasks/{task_id}/labels", {"label_id": lid})
        for lid in (current & dev_ids) - want:
            self.vk("DELETE", f"/tasks/{task_id}/labels/{lid}")

    def sync_issue(self, issue):
        key, updated = issue["key"], issue["fields"].get("updated")
        entry = self.state["issues"].get(key)
        if entry and (entry.get("deleted") or entry.get("updated") == updated):
            return None
        want = task_fields(issue, self.jira_base, self.tz, self.dev_field)
        bucket = want.pop("bucket")
        developers = want.pop("developers")
        if entry is None:
            body = {k: v for k, v in want.items() if v is not None and k != "done"}
            task = self.vk("PUT", f"/projects/{self.state['project_id']}/tasks", body)
            self.move(task["id"], bucket)  # the Done bucket also marks it done
            self.set_developer_labels(task["id"], developers)
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
        task.pop("labels", None)  # managed separately (set_developer_labels)
        self.vk("POST", f"/tasks/{task['id']}", task)
        self.move(task["id"], bucket)
        self.set_developer_labels(task["id"], developers)
        self.state["issues"][key] = {"task_id": task["id"], "updated": updated}
        return "updated"

    def run_once(self, jql):
        self.ensure_project()
        if self.team:
            members = self.jira.team_member_ids(*self.team)
            if not members:
                raise SystemExit("team has no members -- refusing to sync an empty scope")
            jql = team_jql(jql, self.dev_field, members)
        counts = {}
        extra = [self.dev_field] if self.dev_field else []
        for issue in self.jira.search(jql, extra):
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
        dev_field=env.get("JIRA_PRIMARY_DEV_FIELD") or None,
        team=(env["ATLASSIAN_ORG_ID"], env["JIRA_TEAM_ID"]) if env.get("JIRA_TEAM_ID") else None,
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

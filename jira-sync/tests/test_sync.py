import json
from zoneinfo import ZoneInfo

import pytest

import sync

TZ = ZoneInfo("America/New_York")
BASE = "https://example.atlassian.net"


def issue(key, summary="Do thing", category="new", updated="2026-10-01T10:00:00.000-0400",
          duedate=None, priority="Medium", desc="<p>body</p>", devs=()):
    return {"key": key, "renderedFields": {"description": desc}, "fields": {
        "customfield_1": [{"displayName": d} for d in devs],
        "summary": summary, "updated": updated, "duedate": duedate,
        "priority": {"name": priority}, "status": {"statusCategory": {"key": category}}}}


class FakeVikunja:
    """Just enough of the Vikunja API for Syncer, kept in memory."""

    def __init__(self):
        self.projects, self.tasks, self.buckets, self.task_bucket = [], {}, {}, {}
        self.views = {}
        self.labels, self.task_labels = [], {}
        self.next_id = 100

    def _id(self):
        self.next_id += 1
        return self.next_id

    def __call__(self, method, path, body=None):
        parts = path.split("?")[0].strip("/").split("/")
        if parts == ["labels"]:
            if method == "GET":
                return list(self.labels)
            l = {"id": self._id(), "title": body["title"]}
            self.labels.append(l)
            return l
        if parts[0] == "tasks" and len(parts) >= 3 and parts[2] == "labels":
            tid = int(parts[1])
            if method == "PUT":
                self.task_labels.setdefault(tid, set()).add(body["label_id"])
            else:
                self.task_labels.get(tid, set()).discard(int(parts[3]))
            return None
        if path == "/projects" and method == "GET":
            return self.projects
        if path == "/projects" and method == "PUT":
            p = {"id": self._id(), "title": body["title"]}
            self.projects.append(p)
            vid = self._id()
            self.views[p["id"]] = {"id": vid, "view_kind": "kanban", "done_bucket_id": 0}
            self.buckets[vid] = [{"id": self._id(), "title": "To-Do"}]
            return p
        if parts[0] == "projects" and parts[2:] == ["views"]:
            return [self.views[int(parts[1])]]
        if parts[0] == "projects" and len(parts) == 4 and parts[2] == "views":
            self.views[int(parts[1])].update(body)
            return body
        if parts[0] == "projects" and parts[-1] == "buckets":
            vid = int(parts[3])
            if method == "GET":
                return list(self.buckets[vid])
            b = {"id": self._id(), "title": body["title"]}
            self.buckets[vid].append(b)
            return b
        if parts[0] == "projects" and parts[-2] == "buckets" and method == "DELETE":
            vid = int(parts[3])
            self.buckets[vid] = [b for b in self.buckets[vid] if b["id"] != int(parts[-1])]
            return None
        if parts[0] == "projects" and parts[-1] == "tasks" and "buckets" in parts:
            bid = int(parts[-2])
            self.task_bucket[body["task_id"]] = bid
            view = next(v for v in self.views.values() if v["id"] == int(parts[3]))
            if bid == view.get("done_bucket_id"):
                self.tasks[body["task_id"]]["done"] = True
            return None
        if parts[0] == "projects" and parts[-1] == "tasks" and method == "PUT":
            t = {"id": self._id(), "done": False, "due_date": "0001-01-01T00:00:00Z", **body}
            self.tasks[t["id"]] = t
            return t
        if parts[0] == "tasks":
            tid = int(parts[1])
            if tid not in self.tasks:
                raise sync.HTTPError(404, "not found")
            if method == "GET":
                ids = self.task_labels.get(tid, set())
                return {**self.tasks[tid], "labels": [l for l in self.labels if l["id"] in ids]}
            self.tasks[tid] = dict(body)
            return body
        raise AssertionError(f"unexpected call {method} {path}")


class FakeJira:
    def __init__(self, issues, members=("acc-1", "acc-2")):
        self.issues = issues
        self.members = list(members)
        self.last_jql = None

    def team_member_ids(self, org_id, team_id):
        return self.members

    def search(self, jql, extra_fields=()):
        self.last_jql = jql
        return self.issues


@pytest.fixture
def setup(tmp_path):
    vk = FakeVikunja()
    jira = FakeJira([])
    s = sync.Syncer(jira, vk, tmp_path / "state.json", "Jira", BASE, TZ)
    return s, vk, jira


def bucket_title(s, vk, task_id):
    ids = {v: k for k, v in s.state["buckets"].items()}
    return ids[vk.task_bucket[task_id]]


def test_task_fields_maps_issue():
    f = sync.task_fields(issue("DCW-1", "Fix it", "indeterminate", duedate="2026-10-05", priority="High"), BASE, TZ)
    assert f["title"] == "DCW-1: Fix it"
    assert f["bucket"] == "In Progress" and f["done"] is False
    assert f["priority"] == 3
    assert f["due_date"] == "2026-10-05T09:00:00-04:00"
    assert f'href="{BASE}/browse/DCW-1"' in f["description"] and "<p>body</p>" in f["description"]


def test_task_fields_escapes_and_handles_missing():
    i = issue("DCW-2", desc=None, priority=None)
    i["fields"]["priority"] = None
    f = sync.task_fields(i, BASE, TZ)
    assert f["priority"] == 0 and f["due_date"] is None


def test_first_run_creates_project_buckets_and_tasks(setup):
    s, vk, jira = setup
    jira.issues = [issue("DCW-1"), issue("DCW-2", category="done")]
    assert s.run_once("jql") == {"created": 2}
    pid = s.state["project_id"]
    assert [b["title"] for b in vk.buckets[s.state["view_id"]]] == sync.BUCKETS
    assert vk.views[pid]["done_bucket_id"] == s.state["buckets"]["Done"]
    t1, t2 = (vk.tasks[s.state["issues"][k]["task_id"]] for k in ("DCW-1", "DCW-2"))
    assert bucket_title(s, vk, t1["id"]) == "To Do" and not t1["done"]
    assert bucket_title(s, vk, t2["id"]) == "Done" and t2["done"]


def test_unchanged_issue_leaves_vikunja_edits_alone(setup):
    s, vk, jira = setup
    jira.issues = [issue("DCW-1")]
    s.run_once("jql")
    tid = s.state["issues"]["DCW-1"]["task_id"]
    vk.tasks[tid]["title"] = "my own title"
    assert s.run_once("jql") == {}
    assert vk.tasks[tid]["title"] == "my own title"


def test_changed_issue_updates_task_and_bucket(setup):
    s, vk, jira = setup
    jira.issues = [issue("DCW-1")]
    s.run_once("jql")
    tid = s.state["issues"]["DCW-1"]["task_id"]
    jira.issues = [issue("DCW-1", "Renamed", "done", updated="2026-10-02T10:00:00.000-0400")]
    assert s.run_once("jql") == {"updated": 1}
    assert vk.tasks[tid]["title"] == "DCW-1: Renamed"
    assert vk.tasks[tid]["done"] and bucket_title(s, vk, tid) == "Done"
    # reopened in Jira -> undone and back in progress
    jira.issues = [issue("DCW-1", "Renamed", "indeterminate", updated="2026-10-03T10:00:00.000-0400")]
    s.run_once("jql")
    assert not vk.tasks[tid]["done"] and bucket_title(s, vk, tid) == "In Progress"


def test_task_deleted_in_vikunja_is_not_recreated(setup):
    s, vk, jira = setup
    jira.issues = [issue("DCW-1")]
    s.run_once("jql")
    del vk.tasks[s.state["issues"]["DCW-1"]["task_id"]]
    jira.issues = [issue("DCW-1", updated="2026-10-02T10:00:00.000-0400")]
    assert s.run_once("jql") == {"deleted-in-vikunja": 1}
    jira.issues = [issue("DCW-1", updated="2026-10-03T10:00:00.000-0400")]
    assert s.run_once("jql") == {}
    assert len(vk.tasks) == 0


def test_state_persists_across_restarts(setup, tmp_path):
    s, vk, jira = setup
    jira.issues = [issue("DCW-1")]
    s.run_once("jql")
    s2 = sync.Syncer(jira, vk, tmp_path / "state.json", "Jira", BASE, TZ)
    assert s2.run_once("jql") == {}
    assert len(vk.projects) == 1


def test_refuses_to_adopt_unknown_existing_project(tmp_path):
    vk = FakeVikunja()
    vk("PUT", "/projects", {"title": "Jira"})
    s = sync.Syncer(FakeJira([]), vk, tmp_path / "state.json", "Jira", BASE, TZ)
    with pytest.raises(SystemExit):
        s.run_once("jql")


def labels_of(vk, task_id):
    ids = vk.task_labels.get(task_id, set())
    return sorted(l["title"] for l in vk.labels if l["id"] in ids)


@pytest.fixture
def team_setup(tmp_path):
    vk = FakeVikunja()
    jira = FakeJira([])
    s = sync.Syncer(jira, vk, tmp_path / "state.json", "Jira", BASE, TZ,
                    dev_field="customfield_1", team=("org", "team"))
    return s, vk, jira


def test_team_jql_narrows_and_strips_order_by():
    q = sync.team_jql("project = DC AND x ORDER BY updated DESC", "customfield_13114", ["a1", "b2"])
    assert q == '(project = DC AND x) AND cf[13114] in ("a1", "b2") ORDER BY updated DESC'


def test_team_scope_is_applied_to_search(team_setup):
    s, vk, jira = team_setup
    s.run_once("project = DC")
    assert jira.last_jql == '(project = DC) AND cf[1] in ("acc-1", "acc-2") ORDER BY updated DESC'


def test_empty_team_refuses_to_sync(team_setup):
    s, vk, jira = team_setup
    jira.members = []
    with pytest.raises(SystemExit):
        s.run_once("project = DC")


def test_developer_labels_added_changed_and_manual_labels_kept(team_setup):
    s, vk, jira = team_setup
    jira.issues = [issue("DC-1", devs=["Ben Fruth", "Brady Snowden"])]
    s.run_once("q")
    tid = s.state["issues"]["DC-1"]["task_id"]
    assert labels_of(vk, tid) == ["Ben Fruth", "Brady Snowden"]
    manual = vk("PUT", "/labels", {"title": "urgent-ish"})
    vk("PUT", f"/tasks/{tid}/labels", {"label_id": manual["id"]})
    jira.issues = [issue("DC-1", devs=["Ben Fruth", "David Hinton"], updated="2026-10-02T10:00:00.000-0400")]
    s.run_once("q")
    assert labels_of(vk, tid) == ["Ben Fruth", "David Hinton", "urgent-ish"]


def test_labels_are_reused_across_tasks(team_setup):
    s, vk, jira = team_setup
    jira.issues = [issue("DC-1", devs=["Ben Fruth"]), issue("DC-2", devs=["Ben Fruth"])]
    s.run_once("q")
    assert [l["title"] for l in vk.labels] == ["Ben Fruth"]

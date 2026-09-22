import os

import api
import manifest as manifest_mod


def _make_episode(tmp_path, slug):
    paths = manifest_mod.episode_paths(str(tmp_path), slug)
    manifest_mod.ensure_dirs(paths)
    manifest_mod.save_manifest(paths["manifest"], {
        "title": slug,
        "topic": slug,
        "target_duration_seconds": 60,
        "segments": [{"number": 1, "title": "Seg", "duration": 30.0, "status": "complete"}],
    })


def test_list_jobs_embeds_progress_for_every_known_job(tmp_path, monkeypatch):
    """GET /jobs is the server-truth source the Configuration UI polls (not per-browser
    localStorage) so a job started anywhere -- another browser, the Ollama chat tool, a
    direct API call -- shows up with live progress for everyone. Each entry needs its
    progress embedded, same shape as GET /jobs/{job_id}, so the UI can render full status
    from one call instead of N+1 requests.
    """
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path, "episode-a")
    _make_episode(tmp_path, "episode-b")
    monkeypatch.setattr(api, "_jobs", {
        "job1": {"job_id": "job1", "slug": "episode-a", "topic": "Episode A", "status": "running"},
        "job2": {"job_id": "job2", "slug": "episode-b", "topic": "Episode B", "status": "error", "error": "boom"},
    })

    result = api.list_jobs()

    by_id = {j["job_id"]: j for j in result}
    assert by_id["job1"]["progress"]["segments_complete"] == 1
    assert by_id["job1"]["status"] == "running"
    assert by_id["job2"]["progress"]["slug"] == "episode-b"
    assert by_id["job2"]["error"] == "boom"


def test_list_jobs_empty_when_no_jobs_known(monkeypatch):
    monkeypatch.setattr(api, "_jobs", {})
    assert api.list_jobs() == []

"""Thin proxy + static assets for the History Generator configuration UI.

No generation logic and no parameter-validation rules live here -- every request is
forwarded verbatim to the existing private `history-api` (and, for the voice list only,
directly to Kokoro), so this UI can never drift out of sync with the API's own validation.
It exists only because history-api itself is intentionally not reachable from a browser
(see docs/HISTORY-GENERATOR.md) -- this is the one thing that IS meant to be reached from
a browser, and only because it sits behind Caddy basic_auth in front of it.
"""

import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

HISTORY_API_URL = os.environ.get("HISTORY_API_URL", "http://history-api:8000")
KOKORO_URL = os.environ.get("KOKORO_URL", "http://kokoro:8880")
REQUEST_TIMEOUT = 30

app = FastAPI(title="History Generator UI")


async def _proxy(method, url, **kwargs):
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            resp = await client.request(method, url, **kwargs)
        except httpx.RequestError as e:
            return JSONResponse(status_code=502, content={"detail": f"upstream request failed: {e}"})
    try:
        body = resp.json()
    except ValueError:
        body = {"detail": resp.text}
    return JSONResponse(status_code=resp.status_code, content=body)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/metadata")
async def metadata():
    return await _proxy("GET", f"{HISTORY_API_URL}/metadata")


@app.get("/api/voices")
async def voices():
    """Kokoro's own voice list, straight from the source -- avoids hand-maintaining a
    copy of it here that would silently go stale as voices are added/removed. Best-effort:
    an empty list (not an error) if Kokoro can't be reached, since the form still works
    with a free-text voice field either way.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(f"{KOKORO_URL}/v1/audio/voices")
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return {"voices": []}
    voices_list = [
        {"id": v["id"], "grade": v.get("overall_grade")}
        for v in data.get("voices", [])
        if v.get("id")
    ]
    voices_list.sort(key=lambda v: v["id"])
    return {"voices": voices_list}


@app.post("/api/jobs")
async def create_job(request: Request):
    body = await request.json()
    return await _proxy("POST", f"{HISTORY_API_URL}/jobs", json=body)


@app.get("/api/jobs")
async def list_jobs():
    return await _proxy("GET", f"{HISTORY_API_URL}/jobs")


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    return await _proxy("GET", f"{HISTORY_API_URL}/jobs/{job_id}")


@app.get("/api/episodes")
async def list_episodes():
    return await _proxy("GET", f"{HISTORY_API_URL}/episodes")


@app.get("/api/episodes/{slug}")
async def get_episode(slug: str):
    return await _proxy("GET", f"{HISTORY_API_URL}/episodes/{slug}")


@app.patch("/api/episodes/{slug}")
async def update_episode(slug: str, request: Request):
    body = await request.json()
    return await _proxy("PATCH", f"{HISTORY_API_URL}/episodes/{slug}", json=body)


@app.delete("/api/episodes/{slug}")
async def delete_episode(slug: str):
    return await _proxy("DELETE", f"{HISTORY_API_URL}/episodes/{slug}")


@app.get("/api/episodes/{slug}/youtube")
async def get_youtube_metadata(slug: str):
    return await _proxy("GET", f"{HISTORY_API_URL}/episodes/{slug}/youtube")


@app.patch("/api/episodes/{slug}/youtube")
async def update_youtube_metadata(slug: str, request: Request):
    body = await request.json()
    return await _proxy("PATCH", f"{HISTORY_API_URL}/episodes/{slug}/youtube", json=body)


@app.post("/api/episodes/{slug}/youtube/generate")
async def generate_youtube_metadata(slug: str, request: Request):
    body = await request.json() if await request.body() else {}
    return await _proxy("POST", f"{HISTORY_API_URL}/episodes/{slug}/youtube/generate", json=body)


@app.post("/api/episodes/{slug}/youtube/publish")
async def publish_youtube_metadata(slug: str, request: Request):
    body = await request.json()
    return await _proxy("POST", f"{HISTORY_API_URL}/episodes/{slug}/youtube/publish", json=body)


@app.get("/api/episodes/{slug}/youtube/publish/status")
async def get_youtube_publish_status(slug: str):
    return await _proxy("GET", f"{HISTORY_API_URL}/episodes/{slug}/youtube/publish/status")


@app.get("/api/voices/{voice_id}/sample")
async def voice_sample(voice_id: str):
    """Binary audio passthrough, not JSON -- _proxy() always wraps the response as JSON,
    which would corrupt the mp3 bytes, so this route streams the body straight through
    with history-api's own content-type and status code (including a 404 for an unknown
    voice id or a 502 if Kokoro/synthesis fails).
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            resp = await client.get(f"{HISTORY_API_URL}/voices/{voice_id}/sample")
        except httpx.RequestError as e:
            return JSONResponse(status_code=502, content={"detail": f"upstream request failed: {e}"})
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except ValueError:
            body = {"detail": resp.text}
        return JSONResponse(status_code=resp.status_code, content=body)
    return Response(content=resp.content, media_type=resp.headers.get("content-type", "audio/mpeg"))


app.mount("/", StaticFiles(directory="static", html=True), name="static")

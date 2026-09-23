"""Push manifest.json's "youtube" metadata block (see youtube_metadata.py) to YouTube --
either onto a video that's already uploaded (videos.update) or by uploading the
episode's own finished MP4 with that metadata attached in one step (videos.insert, via
Google's resumable upload protocol).

Requires a one-time interactive OAuth consent flow (see youtube_oauth_setup.py) to
obtain a refresh token; this module only ever uses that refresh token to mint
short-lived access tokens, it never performs or asks for interactive consent itself.
"""

import os

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
RESUMABLE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

VALID_PRIVACY_STATUSES = ("private", "unlisted", "public")
# Never "public" -- an upload going live to the world with no confirmation step is
# exactly the kind of surprising, hard-to-reverse action this shouldn't default to.
# "private" is the safe default; the caller (the Configuration UI) surfaces this as an
# explicit choice rather than silently accepting a default that matters this much.
DEFAULT_PRIVACY_STATUS = "private"

# YouTube's videoCategories differ slightly by region, but these three numeric IDs are
# stable in the US catalog (always available regardless of the calling account's
# region) and are the only three propose_youtube_metadata's tool schema can produce --
# see prompts.py:build_youtube_metadata_tool().
CATEGORY_IDS = {
    "Education": "27",
    "Science & Technology": "28",
    "Entertainment": "24",
}
DEFAULT_CATEGORY_ID = CATEGORY_IDS["Education"]

# YouTube hard-rejects videos.update/insert with "invalidDescription" once
# snippet.description exceeds 5000 characters -- found the hard way on a real 112-segment,
# 123-minute episode whose chapters list alone (one line per segment) was already 5403
# characters, before even adding the summary description. A small margin below the real
# limit leaves room for _DESCRIPTION_TRUNCATION_NOTE itself.
YOUTUBE_DESCRIPTION_MAX_CHARS = 5000
_DESCRIPTION_TRUNCATION_NOTE = "\n\n... (remaining chapters omitted -- description length limit)"


class YoutubePublishError(Exception):
    pass


def _build_description(base_description, chapters):
    """Combine the summary description with the chapters block, truncating chapters
    (never the summary) to fit YouTube's real character limit if the combination would
    exceed it. Truncates on whole chapter lines only, never mid-line, and only drops
    from the end of the list -- a long episode's early chapters are kept intact even if
    its later ones don't fit.
    """
    if not chapters:
        return base_description[:YOUTUBE_DESCRIPTION_MAX_CHARS]

    full = f"{base_description}\n\n{chapters}"
    if len(full) <= YOUTUBE_DESCRIPTION_MAX_CHARS:
        return full

    budget = YOUTUBE_DESCRIPTION_MAX_CHARS - len(base_description) - len("\n\n") - len(_DESCRIPTION_TRUNCATION_NOTE)
    if budget <= 0:
        # Even the description alone (plus the note) doesn't leave room for a single
        # chapter line -- keep the description, drop chapters entirely.
        return base_description[:YOUTUBE_DESCRIPTION_MAX_CHARS]

    kept = []
    used = 0
    for line in chapters.split("\n"):
        needed = len(line) + (1 if kept else 0)  # +1 for the joining "\n" after the first line
        if used + needed > budget:
            break
        kept.append(line)
        used += needed

    return f"{base_description}\n\n{chr(10).join(kept)}{_DESCRIPTION_TRUNCATION_NOTE}"


def get_access_token(client_id, client_secret, refresh_token, timeout=30):
    resp = requests.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }, timeout=timeout)
    if resp.status_code >= 400:
        raise YoutubePublishError(f"failed to refresh access token: {resp.status_code} {resp.text}")
    token = resp.json().get("access_token")
    if not token:
        raise YoutubePublishError(f"no access_token in refresh response: {resp.text}")
    return token


def _auth_headers(access_token):
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


def get_video_snippet(access_token, video_id, timeout=30):
    """The video's current snippet, straight from YouTube -- videos.update replaces the
    *entire* snippet object in one call, so this is fetched first and merged with our
    changes rather than built from scratch, to avoid silently wiping fields
    (defaultLanguage, defaultAudioLanguage, ...) our own metadata never touches.
    """
    resp = requests.get(VIDEOS_URL, headers=_auth_headers(access_token), params={
        "part": "snippet",
        "id": video_id,
    }, timeout=timeout)
    if resp.status_code >= 400:
        raise YoutubePublishError(f"failed to fetch video {video_id}: {resp.status_code} {resp.text}")
    items = resp.json().get("items") or []
    if not items:
        raise YoutubePublishError(f"video not found, or not owned by this account: {video_id}")
    return items[0]["snippet"]


def _snippet_from_metadata(metadata, base_snippet=None):
    """Build a videos.snippet object from the manifest's "youtube" dict (title,
    description, tags, category, chapters) as produced by youtube_metadata.py, layered
    onto base_snippet if given (an existing video's current snippet, for videos.update --
    see update_video_metadata's docstring for why that matters). Chapters are appended
    to the description -- YouTube parses chapter markers straight out of description
    text given "<timestamp> <title>" lines starting at 0:00, there's no separate API
    field for them -- matching how a human pasting this metadata by hand would do it.
    """
    snippet = dict(base_snippet) if base_snippet else {}

    snippet["title"] = metadata["title"]
    snippet["description"] = _build_description(metadata.get("description", ""), metadata.get("chapters"))
    snippet["tags"] = metadata.get("tags") or []
    snippet["categoryId"] = CATEGORY_IDS.get(metadata.get("category"), DEFAULT_CATEGORY_ID)
    return snippet


def update_video_metadata(client_id, client_secret, refresh_token, video_id, metadata, timeout=30):
    """Push metadata onto a video that's already on YouTube. videos.update replaces the
    *entire* snippet object in one call, so the video's current snippet is fetched first
    and merged with our changes rather than built from scratch, to avoid silently wiping
    fields (defaultLanguage, defaultAudioLanguage, ...) our own metadata never touches.

    Returns the API's updated-video response on success.
    """
    access_token = get_access_token(client_id, client_secret, refresh_token, timeout=timeout)
    current_snippet = get_video_snippet(access_token, video_id, timeout=timeout)
    snippet = _snippet_from_metadata(metadata, base_snippet=current_snippet)

    resp = requests.put(
        VIDEOS_URL, headers=_auth_headers(access_token), params={"part": "snippet"},
        json={"id": video_id, "snippet": snippet}, timeout=timeout,
    )
    if resp.status_code >= 400:
        raise YoutubePublishError(f"failed to update video {video_id}: {resp.status_code} {resp.text}")
    return resp.json()


def initiate_resumable_upload(access_token, snippet, status, file_size, timeout=30):
    """Step 1 of Google's resumable upload protocol: register the video's metadata and
    get back a session URL to PUT the actual file bytes to. Returns that URL.
    """
    resp = requests.post(
        RESUMABLE_UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(file_size),
        },
        json={"snippet": snippet, "status": status},
        timeout=timeout,
    )
    if resp.status_code >= 400:
        raise YoutubePublishError(f"failed to initiate upload: {resp.status_code} {resp.text}")
    upload_url = resp.headers.get("Location")
    if not upload_url:
        raise YoutubePublishError(f"no upload URL (Location header) in initiate response: {resp.headers}")
    return upload_url


def upload_video_file(upload_url, file_path, timeout=1800):
    """Step 2: stream the actual video file to the session URL from step 1. A single PUT
    covering the whole file -- not chunked -- so a dropped connection mid-upload means
    starting over from initiate_resumable_upload rather than resuming partway; simpler,
    and acceptable for files in the hundreds-of-MB range this pipeline produces, but
    worth knowing if this is ever pointed at something much larger. `timeout` defaults
    to 30 minutes since a several-hundred-MB upload over a modest home connection can
    genuinely take that long.
    """
    file_size = os.path.getsize(file_path)
    with open(file_path, "rb") as f:
        resp = requests.put(
            upload_url,
            headers={"Content-Type": "video/mp4", "Content-Length": str(file_size)},
            data=f,
            timeout=timeout,
        )
    if resp.status_code >= 400:
        raise YoutubePublishError(f"failed to upload video file: {resp.status_code} {resp.text}")
    return resp.json()


def upload_video(client_id, client_secret, refresh_token, file_path, metadata, privacy_status=DEFAULT_PRIVACY_STATUS, init_timeout=30, upload_timeout=1800):
    """Upload file_path to YouTube as a brand-new video with metadata attached, via
    Google's resumable upload protocol (initiate_resumable_upload + upload_video_file).
    Returns the API's created-video response (its "id" is the new video's ID) on success.
    """
    if privacy_status not in VALID_PRIVACY_STATUSES:
        raise YoutubePublishError(f"privacy_status must be one of {VALID_PRIVACY_STATUSES}, got {privacy_status!r}")
    if not os.path.exists(file_path):
        raise YoutubePublishError(f"video file not found: {file_path}")

    access_token = get_access_token(client_id, client_secret, refresh_token, timeout=init_timeout)
    snippet = _snippet_from_metadata(metadata)
    status = {"privacyStatus": privacy_status}
    file_size = os.path.getsize(file_path)

    upload_url = initiate_resumable_upload(access_token, snippet, status, file_size, timeout=init_timeout)
    return upload_video_file(upload_url, file_path, timeout=upload_timeout)

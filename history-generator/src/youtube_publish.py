"""Push manifest.json's "youtube" metadata block (see youtube_metadata.py) to a real,
already-uploaded YouTube video via the YouTube Data API v3's videos.update endpoint.

Requires a one-time interactive OAuth consent flow (see youtube_oauth_setup.py) to
obtain a refresh token; this module only ever uses that refresh token to mint
short-lived access tokens, it never performs or asks for interactive consent itself.
"""

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

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


class YoutubePublishError(Exception):
    pass


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


def update_video_metadata(client_id, client_secret, refresh_token, video_id, metadata, timeout=30):
    """metadata: the manifest's "youtube" dict (title, description, tags, category,
    chapters) as produced by youtube_metadata.py. Chapters are appended to the
    description here -- YouTube parses chapter markers straight out of description text
    given "<timestamp> <title>" lines starting at 0:00, there's no separate API field
    for them -- matching how a human pasting this metadata by hand would do it.

    Returns the API's updated-video response on success.
    """
    access_token = get_access_token(client_id, client_secret, refresh_token, timeout=timeout)
    snippet = get_video_snippet(access_token, video_id, timeout=timeout)

    description = metadata.get("description", "")
    chapters = metadata.get("chapters")
    if chapters:
        description = f"{description}\n\n{chapters}"

    snippet["title"] = metadata["title"]
    snippet["description"] = description
    snippet["tags"] = metadata.get("tags") or []
    snippet["categoryId"] = CATEGORY_IDS.get(metadata.get("category"), DEFAULT_CATEGORY_ID)

    resp = requests.put(
        VIDEOS_URL, headers=_auth_headers(access_token), params={"part": "snippet"},
        json={"id": video_id, "snippet": snippet}, timeout=timeout,
    )
    if resp.status_code >= 400:
        raise YoutubePublishError(f"failed to update video {video_id}: {resp.status_code} {resp.text}")
    return resp.json()

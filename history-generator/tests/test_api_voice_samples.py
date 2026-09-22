import pytest
from fastapi import HTTPException

import api
import voice_samples


def test_get_voice_sample_returns_file_for_known_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(api.kokoro_client, "list_voices", lambda url, **kw: ["af_heart", "am_adam"])

    called = {}

    def fake_get_or_create(kokoro_url, voice_id, samples_dir):
        called["voice_id"] = voice_id
        path = tmp_path / f"{voice_id}.mp3"
        path.write_bytes(b"fake-mp3-bytes")
        return str(path)

    monkeypatch.setattr(api.voice_samples, "get_or_create", fake_get_or_create)

    resp = api.get_voice_sample("af_heart")

    assert called["voice_id"] == "af_heart"
    assert resp.media_type == "audio/mpeg"


def test_get_voice_sample_404s_for_unknown_voice(monkeypatch):
    monkeypatch.setattr(api.kokoro_client, "list_voices", lambda url, **kw: ["af_heart", "am_adam"])

    with pytest.raises(HTTPException) as exc_info:
        api.get_voice_sample("not-a-real-voice")
    assert exc_info.value.status_code == 404


def test_get_voice_sample_falls_through_when_voice_list_unavailable(tmp_path, monkeypatch):
    def raise_error(url, **kw):
        raise ConnectionError("kokoro unreachable")

    monkeypatch.setattr(api.kokoro_client, "list_voices", raise_error)

    def fake_get_or_create(kokoro_url, voice_id, samples_dir):
        path = tmp_path / f"{voice_id}.mp3"
        path.write_bytes(b"fake-mp3-bytes")
        return str(path)

    monkeypatch.setattr(api.voice_samples, "get_or_create", fake_get_or_create)

    # Can't verify the voice list, so it should still attempt synthesis rather than 404.
    resp = api.get_voice_sample("some_voice")
    assert resp.media_type == "audio/mpeg"


def test_get_voice_sample_surfaces_synthesis_errors_as_502(monkeypatch):
    monkeypatch.setattr(api.kokoro_client, "list_voices", lambda url, **kw: ["af_heart"])

    def fake_get_or_create(kokoro_url, voice_id, samples_dir):
        raise voice_samples.VoiceSampleError("kokoro synthesis failed")

    monkeypatch.setattr(api.voice_samples, "get_or_create", fake_get_or_create)

    with pytest.raises(HTTPException) as exc_info:
        api.get_voice_sample("af_heart")
    assert exc_info.value.status_code == 502


def test_prewarm_voice_samples_caches_every_known_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "VOICE_SAMPLES_DIR", str(tmp_path))
    monkeypatch.setattr(api.kokoro_client, "list_voices", lambda url, **kw: ["af_heart", "am_adam", "bm_atten_inno"])

    warmed = []

    def fake_get_or_create(kokoro_url, voice_id, samples_dir):
        warmed.append(voice_id)
        return str(tmp_path / f"{voice_id}.mp3")

    monkeypatch.setattr(api.voice_samples, "get_or_create", fake_get_or_create)

    api._prewarm_voice_samples()

    assert warmed == ["af_heart", "am_adam", "bm_atten_inno"]


def test_prewarm_voice_samples_does_not_raise_when_kokoro_unreachable(monkeypatch):
    def raise_error(url, **kw):
        raise ConnectionError("no route to kokoro")

    monkeypatch.setattr(api.kokoro_client, "list_voices", raise_error)
    api._prewarm_voice_samples()  # must not raise


def test_prewarm_voice_samples_continues_after_one_voice_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(api.kokoro_client, "list_voices", lambda url, **kw: ["good_voice", "bad_voice", "another_good"])

    warmed = []

    def fake_get_or_create(kokoro_url, voice_id, samples_dir):
        if voice_id == "bad_voice":
            raise voice_samples.VoiceSampleError("synthesis failed")
        warmed.append(voice_id)
        return str(tmp_path / f"{voice_id}.mp3")

    monkeypatch.setattr(api.voice_samples, "get_or_create", fake_get_or_create)

    api._prewarm_voice_samples()  # must not raise despite bad_voice failing

    assert warmed == ["good_voice", "another_good"]

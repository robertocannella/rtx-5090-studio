"""
title: History Generator
author: Roberto
description: Trigger and check progress of local narrated educational video generation -- history, math, or present-tense science/discovery explainers (Qwen + Kokoro + FFmpeg pipeline running as a private history-api service).
version: 0.7.0
"""

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        api_base_url: str = Field(
            default="http://history-api:8000",
            description="Base URL of the history-generator API service (private Docker network, not internet-reachable).",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def start_history_episode(
        self,
        topic: str,
        duration: int = 3600,
        voice: str = "af_heart",
        speed: float = 1.0,
        ambient: bool = True,
        pitch_semitones: float = 0.0,
        music: bool = False,
        music_mood: str = "sleep-ambient",
        music_track_id: str = "",
        segment_gap_seconds: float = 1.5,
        sentence_gap_seconds: float = 0.5,
        visual_style: str = "static",
        domain: str = "history",
    ) -> str:
        """
        Start generating a narrated educational video episode on a given topic. This kicks off a
        long-running background job — roughly a minute for a short test, up to 15-30 minutes for
        a full ~60-minute episode — using the local Qwen model to write the script and Kokoro to
        narrate it. It returns immediately once the job has started; it does not wait for the
        job to finish. Use check_history_episode_status afterward (with the returned slug) to
        check progress, and call it again later to see if it's done.

        :param topic: The subject for the episode, e.g. 'Ancient Rome', 'The American Revolution', 'Why prime numbers are infinite', or 'How black holes form'.
        :param duration: Target narration duration in seconds. Use 300 for a ~5 minute test, 3600 (the default) for a full ~60 minute episode.
        :param voice: Kokoro voice to narrate with. Defaults to 'af_heart'.
        :param speed: Narration playback speed. 1.0 is normal, lower is slower (e.g. 0.8), higher is faster (e.g. 1.25). Roughly 0.25-4.0 is accepted.
        :param ambient: Whether to add a quiet procedurally-generated ambient background bed under the narration. The model picks the mood itself based on the topic (e.g. epic for a war, somber for a tragedy) — there's no manual mood choice. Defaults to True.
        :param pitch_semitones: Narrator pitch shift in semitones, independent of speed. 0 is the original Kokoro voice. Negative makes the voice deeper/more resonant (-1 slightly, -2 noticeably), positive makes it higher (+1 slightly, +2 noticeably). Range -4.0 to +4.0. Defaults to 0.0.
        :param music: Whether to mix in real background music selected from the local, human-curated library (distinct from the procedural ambient bed). Defaults to False. If enabled and no track in the requested mood has been reviewed/approved yet, the job fails with a clear error rather than silently skipping the music.
        :param music_mood: Catalog category used to auto-pick a music track when music is enabled and music_track_id isn't given, e.g. 'sleep-ambient'. Defaults to 'sleep-ambient'.
        :param music_track_id: Exact catalog track id to use instead of automatic mood-based selection. Leave empty to auto-select.
        :param segment_gap_seconds: Silent pause inserted between segments, in seconds (0-10). Background music/ambient keep playing through the pause; narration is never split mid-sentence. Defaults to 1.5.
        :param sentence_gap_seconds: Pause inserted between sentences within a segment, in seconds (0-2). 0 disables it (whole segment synthesized in one take, as before). Defaults to 0.5.
        :param visual_style: Segment video background. 'static' (default) is the plain dark background with title text. 'math' randomly picks one animated mathematical visualization (sine/cosine waves, a Fourier-series approximation, or a traced parametric curve) -- the choice is stable for the episode (reproduced on resume), only re-rolled by starting the episode over. 'images' generates several AI illustrations per segment (an Ollama call proposes on-topic scenes, a local FLUX model renders them) and cross-fades between them -- slower to generate than 'static'/'math' since each segment waits on GPU image rendering, and GPU work is strictly serialized with narration generation so only one runs at a time.
        :param domain: Content domain -- which style of script to write. 'history' (default): past events, people, inventions, told narratively. 'math': mathematical results/concepts, explained without symbolic notation since this is audio. 'discovery': present-tense science/how-things-work explainers -- not a history narrative and not a news report on recent events. Chosen once per episode, like the topic; pick the right one when first starting an episode, since changing it on a resumed episode has no effect.
        :return: A short confirmation including the episode slug to check status with later.
        """
        payload = {
            "topic": topic,
            "duration": duration,
            "voice": voice,
            "speed": speed,
            "ambient": ambient,
            "pitch_semitones": pitch_semitones,
            "music": music,
            "music_mood": music_mood,
            "segment_gap_seconds": segment_gap_seconds,
            "sentence_gap_seconds": sentence_gap_seconds,
            "visual_style": visual_style,
            "domain": domain,
        }
        if music_track_id:
            payload["music_track_id"] = music_track_id

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.valves.api_base_url}/jobs", json=payload)
            resp.raise_for_status()
            data = resp.json()

        if data["status"] == "already_running":
            return f"{data['detail']} Episode slug: '{data['slug']}'."

        return (
            f"Started generating a {domain} episode '{data['slug']}' about \"{topic}\" "
            f"(target {duration}s narration, voice '{voice}', speed {speed}, "
            f"ambient {'on' if ambient else 'off'}, pitch {pitch_semitones:+.1f} semitones, "
            f"music {'on (' + (music_track_id or music_mood) + ')' if music else 'off'}). "
            f"This runs in the background — check back later and ask me to check the status "
            f"of episode slug '{data['slug']}'."
        )

    async def check_history_episode_status(self, slug: str) -> str:
        """
        Check the generation progress of an episode by its slug (the hyphenated topic
        name returned by start_history_episode, e.g. 'ancient-rome'). Reports how many narration
        segments are complete, total narration duration so far vs. target, and whether the final
        video file has been produced yet.

        :param slug: The episode slug to check, e.g. 'ancient-rome'.
        :return: A human-readable progress summary.
        """
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self.valves.api_base_url}/episodes/{slug}")
            if resp.status_code == 404:
                return f"No episode found with slug '{slug}'."
            resp.raise_for_status()
            data = resp.json()

        lines = [
            f"Episode: {data.get('title') or data.get('topic')} ({slug})",
            f"Domain: {data.get('domain', 'history')}",
            f"Segments: {data['segments_complete']}/{data['segments_total']} complete"
            + (f", {data['segments_failed']} failed" if data["segments_failed"] else ""),
            f"Narration: {data['narration_seconds']:.0f}s / {data['target_duration_seconds']}s target",
        ]
        if data.get("ambient_mood"):
            lines.append(f"Ambient mood: {data['ambient_mood']}")
        if data.get("pitch_semitones"):
            lines.append(f"Pitch: {data['pitch_semitones']:+.1f} semitones")
        if data.get("segment_gap_seconds"):
            lines.append(f"Segment gap: {data['segment_gap_seconds']:.1f}s")
        if data.get("sentence_gap_seconds"):
            lines.append(f"Sentence gap: {data['sentence_gap_seconds']:.1f}s")
        if data.get("visual_style") == "math" and data.get("visual_family"):
            lines.append(f"Visual: {data['visual_family']}")
        if data.get("music_enabled"):
            lines.append(f"Music: {data.get('music_file') or data.get('music_track_id')}")
        if data["final_video_exists"]:
            host_path = data.get("final_video_host_path")
            if host_path:
                lines.append(f"Final video is ready on the server at: {host_path}")
            else:
                lines.append(
                    f"Final video is ready (container path: {data['final_video_path']}) — "
                    "open it directly on the server; there's no browser download link for it."
                )
        else:
            lines.append("Final video not built yet — still generating segments.")
        return "\n".join(lines)

    async def list_history_episodes(self) -> str:
        """
        List all episodes (any domain) that have been generated or are in progress, with a short
        status summary for each.

        :return: A summary list of episodes, one per line.
        """
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self.valves.api_base_url}/episodes")
            resp.raise_for_status()
            data = resp.json()

        if not data:
            return "No episodes found yet."

        lines = []
        for ep in data:
            status = "done" if ep["final_video_exists"] else "in progress"
            lines.append(
                f"- {ep['slug']}: {ep.get('title') or ep.get('topic')} "
                f"({ep['segments_complete']}/{ep['segments_total']} segments, {status})"
            )
        return "\n".join(lines)

(() => {
  "use strict";

  const PRESETS_KEY = "episodeGeneratorPresets";
  const DISMISSED_JOBS_KEY = "episodeGeneratorDismissedJobs";
  const POLL_INTERVAL_MS = 8000;
  const MAX_JOBS_SHOWN = 30;

  const BUILTIN_PRESETS = {
    "Relaxed Documentary": {
      voice: "bm_atten_inno",
      speed: 0.85,
      pitch_semitones: 0,
      sentence_gap_seconds: 0.5,
      segment_gap_seconds: 1.5,
      music: true,
      music_mood: "sleep-ambient",
      music_level_db: -12,
      ambient: false,
    },
  };

  let metadata = null;

  // ---- small DOM helpers -----------------------------------------------

  const $ = (id) => document.getElementById(id);

  async function apiGet(path) {
    const resp = await fetch(path);
    let body;
    try { body = await resp.json(); } catch { body = {}; }
    if (!resp.ok) {
      const err = new Error(describeError(body));
      err.status = resp.status;
      err.body = body;
      throw err;
    }
    return body;
  }

  async function apiPost(path, payload) {
    const resp = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    let body;
    try { body = await resp.json(); } catch { body = {}; }
    if (!resp.ok) {
      const err = new Error(describeError(body));
      err.status = resp.status;
      err.body = body;
      throw err;
    }
    return body;
  }

  function describeError(body) {
    // FastAPI/pydantic validation errors come back as {"detail": [{"loc": [...], "msg": "..."}]}
    if (Array.isArray(body && body.detail)) {
      return body.detail
        .map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`)
        .join("\n");
    }
    if (body && typeof body.detail === "string") return body.detail;
    return "Request failed.";
  }

  function showTopError(message) {
    const box = $("top-error");
    if (!message) {
      box.classList.remove("show");
      box.textContent = "";
      return;
    }
    box.textContent = message;
    box.classList.add("show");
  }

  // ---- metadata / voices --------------------------------------------------

  async function loadMetadata() {
    try {
      metadata = await apiGet("/api/metadata");
    } catch (e) {
      showTopError("Could not load metadata from history-api: " + e.message);
      metadata = { domains: ["history"], visual_styles: ["static"], bounds: {}, defaults: {} };
    }

    const domainSelect = $("domain");
    domainSelect.innerHTML = "";
    (metadata.domains || ["history"]).forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d;
      opt.textContent = d;
      domainSelect.appendChild(opt);
    });
    domainSelect.value = metadata.defaults.domain || "history";
    updateDomainHint();

    const visualSelect = $("visual-style");
    visualSelect.innerHTML = "";
    (metadata.visual_styles || ["static"]).forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      visualSelect.appendChild(opt);
    });
    visualSelect.value = metadata.defaults.visual_style || "static";

    // Apply bounds to range inputs so the UI can never submit something the API would reject.
    const bounds = metadata.bounds || {};
    applyBounds("speed", { min: 0.25, max: 4.0, ...(bounds.speed || {}) });
    applyBounds("pitch", bounds.pitch_semitones);
    applyBounds("sentence-gap", bounds.sentence_gap_seconds);
    applyBounds("segment-gap", bounds.segment_gap_seconds);
    applyBounds("music-level", bounds.music_level_db);
  }

  function applyBounds(id, bound) {
    if (!bound) return;
    const el = $(id);
    if (bound.min !== undefined) el.min = bound.min;
    if (bound.max !== undefined) el.max = bound.max;
  }

  function updateDomainHint() {
    const hints = {
      history: "Past events, people, inventions -- narrated chronologically.",
      math: "Mathematical results/concepts, explained without symbolic notation (audio-only).",
      discovery: "Present-tense science/how-things-work explainers -- not history, not news.",
    };
    $("domain-hint").textContent = hints[$("domain").value] || "";
  }

  async function loadVoices() {
    const voiceSelect = $("voice");
    voiceSelect.innerHTML = "";
    let voices = [];
    try {
      const data = await apiGet("/api/voices");
      voices = data.voices || [];
    } catch {
      voices = [];
    }
    if (voices.length === 0) {
      const opt = document.createElement("option");
      opt.value = "__custom__";
      opt.textContent = "(voice list unavailable -- type one manually)";
      voiceSelect.appendChild(opt);
    } else {
      voices.forEach((v) => {
        const opt = document.createElement("option");
        opt.value = v.id;
        opt.textContent = v.grade ? `${v.id} (grade ${v.grade})` : v.id;
        voiceSelect.appendChild(opt);
      });
      const customOpt = document.createElement("option");
      customOpt.value = "__custom__";
      customOpt.textContent = "Other (type a voice id)...";
      voiceSelect.appendChild(customOpt);
    }
    voiceSelect.addEventListener("change", syncVoiceCustomField);
  }

  function syncVoiceCustomField() {
    const isCustom = $("voice").value === "__custom__";
    $("voice-custom-field").style.display = isCustom ? "" : "none";
  }

  function selectVoice(voiceId) {
    const select = $("voice");
    const hasOption = Array.from(select.options).some((o) => o.value === voiceId);
    if (hasOption) {
      select.value = voiceId;
    } else {
      select.value = "__custom__";
      $("voice-custom").value = voiceId;
    }
    syncVoiceCustomField();
  }

  function currentVoice() {
    return $("voice").value === "__custom__" ? $("voice-custom").value.trim() : $("voice").value;
  }

  // ---- voice preview ----------------------------------------------------
  // A <=10s clip of the fixed sample text, generated once per voice by history-api and
  // cached there (see voice_samples.py) -- most voices should already be warm by the
  // time this page is opened, but the first click for a brand-new voice can take a few
  // seconds while it synthesizes, hence the "Loading..." state below.

  let voicePreviewObjectUrl = null;

  async function previewVoice() {
    const voiceId = currentVoice();
    const btn = $("voice-preview-btn");
    const status = $("voice-preview-status");

    if (!voiceId) {
      status.textContent = "Enter or choose a voice first.";
      status.className = "error";
      return;
    }

    btn.disabled = true;
    status.className = "";
    status.textContent = "Loading preview...";

    try {
      const resp = await fetch(`/api/voices/${encodeURIComponent(voiceId)}/sample`);
      if (!resp.ok) {
        let body = {};
        try { body = await resp.json(); } catch { /* body wasn't JSON -- fall through */ }
        throw new Error(describeError(body) || `HTTP ${resp.status}`);
      }
      const blob = await resp.blob();

      if (voicePreviewObjectUrl) URL.revokeObjectURL(voicePreviewObjectUrl);
      voicePreviewObjectUrl = URL.createObjectURL(blob);

      const audio = $("voice-preview-audio");
      audio.src = voicePreviewObjectUrl;
      audio.onended = () => { status.textContent = ""; };
      status.textContent = `Playing ${voiceId}...`;
      await audio.play();
    } catch (e) {
      status.textContent = "Could not preview: " + e.message;
      status.className = "error";
    } finally {
      btn.disabled = false;
    }
  }

  // ---- range live labels ----------------------------------------------

  function wireRangeLabel(rangeId, outId, decimals) {
    const range = $(rangeId);
    const out = $(outId);
    const update = () => { out.textContent = Number(range.value).toFixed(decimals); };
    range.addEventListener("input", update);
    update();
  }

  // ---- form <-> payload -------------------------------------------------

  function buildPayload() {
    return {
      topic: $("topic").value.trim(),
      duration: parseInt($("duration").value, 10) || 3600,
      voice: currentVoice(),
      speed: parseFloat($("speed").value),
      ambient: $("ambient").checked,
      youtube_metadata: $("youtube-metadata").checked,
      pitch_semitones: parseFloat($("pitch").value),
      music: $("music").checked,
      music_mood: $("music-mood").value.trim() || "sleep-ambient",
      music_level_db: parseFloat($("music-level").value),
      segment_gap_seconds: parseFloat($("segment-gap").value),
      sentence_gap_seconds: parseFloat($("sentence-gap").value),
      visual_style: $("visual-style").value,
      domain: $("domain").value,
      force: $("force").checked,
    };
  }

  function applyPreset(preset) {
    if (preset.voice) selectVoice(preset.voice);
    if (preset.speed !== undefined) $("speed").value = preset.speed;
    if (preset.pitch_semitones !== undefined) $("pitch").value = preset.pitch_semitones;
    if (preset.sentence_gap_seconds !== undefined) $("sentence-gap").value = preset.sentence_gap_seconds;
    if (preset.segment_gap_seconds !== undefined) $("segment-gap").value = preset.segment_gap_seconds;
    if (preset.music !== undefined) $("music").checked = preset.music;
    if (preset.music_mood) $("music-mood").value = preset.music_mood;
    if (preset.music_level_db !== undefined) $("music-level").value = preset.music_level_db;
    if (preset.ambient !== undefined) $("ambient").checked = preset.ambient;
    if (preset.youtube_metadata !== undefined) $("youtube-metadata").checked = preset.youtube_metadata;
    if (preset.visual_style) $("visual-style").value = preset.visual_style;
    if (preset.domain) $("domain").value = preset.domain;
    if (preset.duration) $("duration").value = preset.duration;
    syncMusicVisibility();
    updateDomainHint();
    ["speed", "pitch", "sentence-gap", "segment-gap", "music-level"].forEach((id) =>
      $(id).dispatchEvent(new Event("input"))
    );
    updateSummary();
  }

  function loadCustomPresets() {
    try {
      return JSON.parse(localStorage.getItem(PRESETS_KEY) || "{}");
    } catch {
      return {};
    }
  }

  function saveCustomPresets(presets) {
    try {
      localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
    } catch {
      /* localStorage unavailable (private window, etc.) -- presets just won't persist */
    }
  }

  function refreshPresetOptions() {
    const select = $("preset-select");
    const current = select.value;
    select.innerHTML = '<option value="">-- choose a preset --</option>';
    Object.keys(BUILTIN_PRESETS).forEach((name) => addPresetOption(select, name, true));
    Object.keys(loadCustomPresets()).forEach((name) => addPresetOption(select, name, false));
    if (current) select.value = current;
  }

  function addPresetOption(select, name, builtin) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = builtin ? `${name} (built-in)` : name;
    select.appendChild(opt);
  }

  // ---- validation + summary ---------------------------------------------

  function validate(payload) {
    const errors = {};
    if (!payload.topic) errors.topic = "Topic is required.";

    const bounds = (metadata && metadata.bounds) || {};
    const checks = [
      ["speed", payload.speed, { min: 0.25, max: 4.0, ...(bounds.speed || {}) }],
      ["pitch", payload.pitch_semitones, bounds.pitch_semitones],
      ["sentence-gap", payload.sentence_gap_seconds, bounds.sentence_gap_seconds],
      ["segment-gap", payload.segment_gap_seconds, bounds.segment_gap_seconds],
      ["music-level", payload.music_level_db, bounds.music_level_db],
    ];
    checks.forEach(([fieldId, value, bound]) => {
      if (!bound) return;
      if (value < bound.min || value > bound.max) {
        errors[fieldId] = `Must be between ${bound.min} and ${bound.max}.`;
      }
    });
    if (payload.duration < 30) errors.duration = "Must be at least 30 seconds.";

    return errors;
  }

  function renderFieldErrors(errors) {
    document.querySelectorAll(".field.invalid").forEach((f) => f.classList.remove("invalid"));
    Object.entries(errors).forEach(([fieldId, message]) => {
      const input = $(fieldId) || document.querySelector(`[name="${fieldId}"]`);
      if (!input) return;
      const field = input.closest(".field");
      if (!field) return;
      field.classList.add("invalid");
      const errEl = field.querySelector(".error");
      if (errEl) errEl.textContent = message;
    });
  }

  function updateSummary() {
    const payload = buildPayload();
    const errors = validate(payload);
    renderFieldErrors(errors);
    $("submit-btn").disabled = Object.keys(errors).length > 0 || !payload.topic;

    const lines = [
      `Topic: ${payload.topic || "(required)"}`,
      `Domain: ${payload.domain}`,
      `Duration: ${payload.duration}s`,
      `Voice: ${payload.voice || "(required)"}  Speed: ${payload.speed}x  Pitch: ${payload.pitch_semitones >= 0 ? "+" : ""}${payload.pitch_semitones}`,
      `Sentence gap: ${payload.sentence_gap_seconds}s  Segment gap: ${payload.segment_gap_seconds}s`,
      `Ambient: ${payload.ambient ? "on" : "off"}`,
      `YouTube metadata: ${payload.youtube_metadata ? "on" : "off"}`,
      payload.music
        ? `Music: on (${payload.music_mood}, ${payload.music_level_db} dBFS)`
        : "Music: off",
      `Visual: ${payload.visual_style}`,
      payload.force ? "Force: yes (wipes existing episode)" : "Force: no",
    ];
    $("summary").textContent = lines.join("\n");
    return { payload, errors };
  }

  function syncMusicVisibility() {
    $("music-subgroup").classList.toggle("open", $("music").checked);
  }

  // ---- job tracking + polling -------------------------------------------
  //
  // The jobs list is driven entirely by GET /api/jobs -- history-api's own in-memory
  // record of every job it knows about, regardless of which client started it (this
  // page, the Ollama chat tool, another browser, a direct API call). That's what makes
  // this "live": there is no per-browser localStorage source of truth to go stale when
  // a job fails and gets resubmitted under a new job_id, or to miss a job someone else
  // started. localStorage is used only for "dismissed" job ids -- a purely cosmetic,
  // per-browser preference for hiding a finished/errored job you've already seen; the
  // server keeps remembering it (until its own restart) regardless.

  function loadDismissedJobs() {
    try {
      return new Set(JSON.parse(localStorage.getItem(DISMISSED_JOBS_KEY) || "[]"));
    } catch {
      return new Set();
    }
  }

  function dismissJob(jobId) {
    const dismissed = loadDismissedJobs();
    dismissed.add(jobId);
    try {
      localStorage.setItem(DISMISSED_JOBS_KEY, JSON.stringify([...dismissed]));
    } catch {
      /* localStorage unavailable -- the job will just keep reappearing until it is */
    }
    const card = document.getElementById(`job-${jobId}`);
    if (card) card.remove();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // Once narration hits its target, the pipeline still has to work through further
  // per-segment stages (image generation, then per-segment video encoding, then a final
  // mix/encode pass) that can each take as long as narration did -- this turns "target
  // reached" from a dead end into a real "video 28/54"-style readout of what's actually
  // happening next.
  function stageLabel(progress) {
    const total = progress.segments_complete || 0;
    switch (progress.stage) {
      case "generating_images":
        return `Generating images: ${progress.images_ready || 0}/${total} segments`;
      case "building_segment_videos":
        return `Building segment videos: ${progress.segment_videos_built || 0}/${total}`;
      case "finalizing":
        return "Finalizing: mixing audio and encoding the final video...";
      default:
        return null;
    }
  }

  function jobCardHtml(job) {
    const progress = job.progress || {};
    const total = progress.segments_total || 0;
    const complete = progress.segments_complete || 0;
    // The outline is deliberately over-provisioned (a buffer against under-shooting the
    // target), so a healthy finished episode routinely ends with segments_complete a
    // little short of segments_total -- one or more outlined segments were never
    // needed, not left half-done. target_reached (from the API) is what actually
    // distinguishes "done, buffer unused" from "still working, catching up" -- so it
    // drives both the bar and the label here, not the raw fraction.
    const pct = progress.target_reached || job.status === "complete" ? 100
      : total > 0 ? Math.round((complete / total) * 100) : 0;

    const bits = [`Status: ${job.status}`];
    if (progress.target_reached) {
      bits.push(`${complete} segment${complete === 1 ? "" : "s"} narrated (target reached)`);
    } else if (total) {
      bits.push(`${complete}/${total} segments`);
    }
    if (progress.narration_seconds !== undefined && progress.target_duration_seconds) {
      bits.push(`${Math.round(progress.narration_seconds)}s / ${progress.target_duration_seconds}s narration`);
    }
    const stageText = stageLabel(progress);
    if (stageText) bits.push(stageText);
    if (progress.domain) bits.push(`domain: ${progress.domain}`);
    if (progress.visual_family) bits.push(`visual: ${progress.visual_family}`);

    let statusHtml = bits.join(" &middot; ");
    if (job.status === "error" && job.error) {
      statusHtml += `<br>Error: ${escapeHtml(job.error)}`;
    }
    if (job.status === "complete") {
      const hostPath = progress.final_video_host_path;
      if (hostPath) {
        statusHtml += `<br>Final video: <span class="host-path">${escapeHtml(hostPath)}</span>`;
      } else if (progress.final_video_path) {
        statusHtml += `<br>Final video (container path -- open directly on the server): <span class="host-path">${escapeHtml(progress.final_video_path)}</span>`;
      }
    }

    return `
      <div class="job-card" id="job-${job.job_id}">
        <div class="job-title">${escapeHtml(job.topic)}</div>
        <div class="job-meta">slug: ${escapeHtml(job.slug)} &middot; job: ${escapeHtml(job.job_id)}</div>
        <div class="progress-bar"><div style="width:${pct}%"></div></div>
        <div class="job-status-line status-${job.status}">${statusHtml}</div>
        <button type="button" class="small remove-job-btn" data-job-id="${escapeHtml(job.job_id)}">Dismiss</button>
      </div>`;
  }

  // Same reasoning as loadEpisodes's lastEpisodesJson: skip touching the DOM entirely
  // when a refresh comes back identical to what's already rendered.
  let lastJobsJson = null;

  async function pollAllJobs() {
    const list = $("jobs-list");
    let jobs;
    try {
      jobs = await apiGet("/api/jobs");
    } catch (e) {
      // Don't blow away a list that's already showing useful data over one flaky poll.
      if (!list.querySelector(".job-card")) {
        list.innerHTML = `<p class="hint">Could not reach history-api: ${escapeHtml(e.message)}</p>`;
      }
      return;
    }

    const dismissed = loadDismissedJobs();
    jobs = jobs
      .filter((j) => !dismissed.has(j.job_id))
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
      .slice(0, MAX_JOBS_SHOWN);

    const jobsJson = JSON.stringify(jobs);
    if (jobsJson === lastJobsJson) {
      return;
    }
    lastJobsJson = jobsJson;

    if (jobs.length === 0) {
      list.innerHTML = '<p class="hint">No jobs yet -- start one above, or ask the Ollama chat tool to.</p>';
      return;
    }

    list.innerHTML = jobs.map(jobCardHtml).join("");
    list.querySelectorAll(".remove-job-btn").forEach((btn) => {
      btn.addEventListener("click", () => dismissJob(btn.dataset.jobId));
    });
  }

  // ---- all episodes -------------------------------------------------------

  // The episodes list re-renders its whole innerHTML on every auto-refresh tick (see
  // loadEpisodes below), which would otherwise silently collapse an open YouTube-metadata
  // panel every ~8s. Tracking which slugs are expanded (and caching what was fetched for
  // them) lets each refresh restore that state instead of losing it.
  const expandedYoutube = new Set();
  const youtubeCache = {};

  function youtubeWatchUrl(videoId) {
    return `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`;
  }

  function youtubeWatchLinkHtml(videoId) {
    const url = youtubeWatchUrl(videoId);
    return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(url)}</a>`;
  }

  function youtubePanelHtml(slug, y) {
    const publishedNote = y.video_id
      ? `<div class="hint">Last published: ${youtubeWatchLinkHtml(y.video_id)}</div>`
      : "";
    return `
      <div class="yt-meta">
        <div><strong>Title:</strong> ${escapeHtml(y.title)}</div>
        <div><strong>Category:</strong> ${escapeHtml(y.category)}</div>
        <div><strong>Tags:</strong> ${escapeHtml(y.tags_joined)}</div>
        <details><summary>Description</summary><pre>${escapeHtml(y.description)}</pre></details>
        <details><summary>Chapters</summary><pre>${escapeHtml(y.chapters)}</pre></details>
        ${publishedNote}
        <div class="yt-publish-row">
          <input type="text" class="yt-video-id" placeholder="YouTube video ID" value="${escapeHtml(y.video_id || "")}">
          <button type="button" class="small yt-publish-btn" data-slug="${escapeHtml(slug)}">Publish to YouTube</button>
          <span class="yt-publish-status"></span>
        </div>
        <div class="yt-publish-row">
          <button type="button" class="small yt-regenerate-btn" data-slug="${escapeHtml(slug)}">Regenerate metadata</button>
          <span class="yt-regenerate-status"></span>
        </div>
      </div>`;
  }

  function wireYoutubePanelButtons(panel, slug) {
    const publishBtn = panel.querySelector(".yt-publish-btn");
    if (publishBtn) {
      publishBtn.addEventListener("click", async () => {
        const input = panel.querySelector(".yt-video-id");
        const status = panel.querySelector(".yt-publish-status");
        const videoId = input.value.trim();
        if (!videoId) {
          status.textContent = "Enter a video ID first.";
          status.className = "yt-publish-status error";
          return;
        }
        publishBtn.disabled = true;
        status.className = "yt-publish-status";
        status.textContent = "Publishing...";
        try {
          const result = await apiPost(`/api/episodes/${encodeURIComponent(slug)}/youtube/publish`, { video_id: videoId });
          status.innerHTML = `Published: ${youtubeWatchLinkHtml(result.video_id)}`;
          if (youtubeCache[slug]) youtubeCache[slug] = { ...youtubeCache[slug], video_id: result.video_id };
        } catch (e) {
          status.textContent = "Failed: " + e.message;
          status.className = "yt-publish-status error";
        } finally {
          publishBtn.disabled = false;
        }
      });
    }

    const regenerateBtn = panel.querySelector(".yt-regenerate-btn");
    if (regenerateBtn) {
      regenerateBtn.addEventListener("click", async () => {
        const status = panel.querySelector(".yt-regenerate-status");
        regenerateBtn.disabled = true;
        status.className = "yt-regenerate-status";
        status.textContent = "Regenerating (asks Ollama again, can take a little while)...";
        try {
          const y = await apiPost(`/api/episodes/${encodeURIComponent(slug)}/youtube/generate`, { force: true });
          youtubeCache[slug] = y;
          panel.innerHTML = youtubePanelHtml(slug, y);
          wireYoutubePanelButtons(panel, slug);
        } catch (e) {
          status.textContent = "Failed: " + e.message;
          status.className = "yt-regenerate-status error";
          regenerateBtn.disabled = false;
        }
      });
    }
  }

  async function toggleYoutubePanel(slug) {
    const panel = document.getElementById(`yt-panel-${slug}`);
    if (!panel) return;
    if (expandedYoutube.has(slug)) {
      expandedYoutube.delete(slug);
      panel.style.display = "none";
      return;
    }
    expandedYoutube.add(slug);
    panel.style.display = "";
    if (youtubeCache[slug]) {
      panel.innerHTML = youtubePanelHtml(slug, youtubeCache[slug]);
      wireYoutubePanelButtons(panel, slug);
      return;
    }
    panel.innerHTML = '<p class="hint">Loading...</p>';
    try {
      const y = await apiGet(`/api/episodes/${encodeURIComponent(slug)}/youtube`);
      youtubeCache[slug] = y;
      panel.innerHTML = youtubePanelHtml(slug, y);
      wireYoutubePanelButtons(panel, slug);
    } catch (e) {
      panel.innerHTML = `<p class="hint">Could not load: ${escapeHtml(e.message)}</p>`;
    }
  }

  async function generateYoutubeMetadata(slug, row) {
    const btn = row.querySelector(".yt-generate-btn");
    const status = row.querySelector(".yt-generate-status");
    btn.disabled = true;
    status.className = "yt-generate-status";
    status.textContent = "Generating (asks Ollama for title/description/tags, can take a little while)...";
    try {
      const y = await apiPost(`/api/episodes/${encodeURIComponent(slug)}/youtube/generate`, {});
      youtubeCache[slug] = y;
      status.textContent = "Done.";
      loadEpisodes(); // swap this row's button for the normal "YouTube metadata" toggle
    } catch (e) {
      status.textContent = "Failed: " + e.message;
      status.className = "yt-generate-status error";
      btn.disabled = false;
    }
  }

  // Set once the episodes list has rendered real content -- after that, refreshes
  // (the 8s auto-refresh tick, or the manual Refresh button) update the list's content
  // directly instead of first wiping it to "Loading...". Without this, every refresh
  // briefly removed the whole list -- including any open YouTube-metadata panel -- and
  // only restored it after the network round-trip completed, which reads as the list
  // "flickering" and open panels "collapsing" every few seconds even though the
  // restoration logic below did put them back a moment later.
  let episodesLoadedOnce = false;
  // The full episode list's last-rendered JSON -- if a refresh comes back byte-identical
  // to what's already on screen (the common case once an episode is finished and
  // nothing about it is changing tick to tick), the DOM is left completely untouched.
  // Rebuilding it anyway on every 8s tick regardless of whether anything changed was
  // still resetting in-progress typing in the video-ID input, clearing text selection,
  // and generally disrupting an open panel even after the "Loading..." flash (above) was
  // fixed, since the rebuild+restore both happened, just without a visible gap between them.
  let lastEpisodesJson = null;

  async function loadEpisodes() {
    const list = $("episodes-list");
    if (!episodesLoadedOnce) {
      list.innerHTML = '<p class="hint">Loading...</p>';
    }
    let episodes;
    try {
      episodes = await apiGet("/api/episodes");
    } catch (e) {
      // Same reasoning as pollAllJobs's catch: don't blow away a list that's already
      // showing useful data over one flaky poll.
      if (!episodesLoadedOnce) {
        list.innerHTML = `<p class="hint">Could not load episodes: ${escapeHtml(e.message)}</p>`;
      }
      return;
    }
    episodesLoadedOnce = true;

    const episodesJson = JSON.stringify(episodes);
    if (episodesJson === lastEpisodesJson) {
      return;
    }
    lastEpisodesJson = episodesJson;

    if (!episodes.length) {
      list.innerHTML = '<p class="hint">No episodes yet.</p>';
      return;
    }
    const headerRow = `<div class="episode-table-header">
      <div>Episode</div><div>Progress</div><div>Actions</div>
    </div>`;
    list.innerHTML = headerRow + episodes
      .map((ep) => {
        // See the target_reached comment in jobCardHtml -- segments_complete a bit
        // below segments_total is normal for a finished episode (outline buffer left
        // unused), not a sign it's still catching up.
        const status = ep.final_video_exists ? "done" : (stageLabel(ep) || (ep.target_reached ? "finalizing" : "in progress"));
        const segmentsLabel = ep.target_reached
          ? `${ep.segments_complete} segments narrated`
          : `${ep.segments_complete}/${ep.segments_total} segments`;
        const domainTag = ep.domain ? `<span class="tag">${escapeHtml(ep.domain)}</span>` : "";
        const ytActions = ep.youtube_metadata_ready
          ? `<button type="button" class="small yt-toggle-btn" data-slug="${escapeHtml(ep.slug)}">YouTube metadata</button>`
          : `<button type="button" class="small yt-generate-btn" data-slug="${escapeHtml(ep.slug)}">Generate YouTube metadata</button>
             <span class="yt-generate-status"></span>`;
        return `<div class="episode-row-wrap">
          <div class="episode-row">
            <div class="ep-col-title">${escapeHtml(ep.title || ep.topic)} ${domainTag}</div>
            <div class="ep-col-status">${segmentsLabel} &middot; ${status}</div>
            <div class="ep-col-actions">${ytActions}</div>
          </div>
          <div class="yt-panel" id="yt-panel-${escapeHtml(ep.slug)}" style="display:none"></div>
        </div>`;
      })
      .join("");
    list.querySelectorAll(".yt-toggle-btn").forEach((btn) => {
      btn.addEventListener("click", () => toggleYoutubePanel(btn.dataset.slug));
    });
    list.querySelectorAll(".yt-generate-btn").forEach((btn) => {
      btn.addEventListener("click", () => generateYoutubeMetadata(btn.dataset.slug, btn.closest(".episode-row")));
    });
    expandedYoutube.forEach((slug) => {
      const panel = document.getElementById(`yt-panel-${slug}`);
      if (panel && youtubeCache[slug]) {
        panel.style.display = "";
        panel.innerHTML = youtubePanelHtml(slug, youtubeCache[slug]);
        wireYoutubePanelButtons(panel, slug);
      }
    });
  }

  // ---- wiring ---------------------------------------------------------

  function wireForm() {
    ["speed", "pitch", "sentence-gap", "segment-gap", "music-level"].forEach((id) =>
      $(id).addEventListener("input", updateSummary)
    );
    document.querySelectorAll('#job-form input, #job-form select').forEach((el) => {
      el.addEventListener("input", updateSummary);
      el.addEventListener("change", updateSummary);
    });
    $("music").addEventListener("change", () => { syncMusicVisibility(); updateSummary(); });
    $("domain").addEventListener("change", () => { updateDomainHint(); updateSummary(); });
    $("voice-preview-btn").addEventListener("click", previewVoice);

    document.querySelectorAll("[data-duration]").forEach((btn) => {
      btn.addEventListener("click", () => {
        $("duration").value = btn.dataset.duration;
        updateSummary();
      });
    });

    wireRangeLabel("speed", "speed-out", 2);
    wireRangeLabel("pitch", "pitch-out", 1);
    wireRangeLabel("sentence-gap", "sentence-gap-out", 1);
    wireRangeLabel("segment-gap", "segment-gap-out", 1);
    wireRangeLabel("music-level", "music-level-out", 0);

    $("job-form").addEventListener("submit", onSubmit);
  }

  function wirePresets() {
    refreshPresetOptions();
    $("preset-select").addEventListener("change", () => {
      const name = $("preset-select").value;
      if (!name) return;
      const preset = BUILTIN_PRESETS[name] || loadCustomPresets()[name];
      if (preset) applyPreset(preset);
    });
    $("save-preset-btn").addEventListener("click", () => {
      const name = prompt("Preset name:");
      if (!name) return;
      const presets = loadCustomPresets();
      presets[name] = buildPayload();
      saveCustomPresets(presets);
      refreshPresetOptions();
      $("preset-select").value = name;
    });
    $("delete-preset-btn").addEventListener("click", () => {
      const name = $("preset-select").value;
      if (!name || BUILTIN_PRESETS[name]) {
        alert("Select a custom (non built-in) preset to delete.");
        return;
      }
      const presets = loadCustomPresets();
      delete presets[name];
      saveCustomPresets(presets);
      refreshPresetOptions();
    });
  }

  async function onSubmit(evt) {
    evt.preventDefault();
    showTopError(null);
    const { payload, errors } = updateSummary();
    if (Object.keys(errors).length > 0) return;

    $("submit-btn").disabled = true;
    $("submit-btn").textContent = "Starting...";
    try {
      const data = await apiPost("/api/jobs", payload);
      if (data.status === "already_running") {
        showTopError(data.detail || "A job for this topic is already running.");
      } else {
        await pollAllJobs(); // server already knows about it -- refresh immediately, don't wait for the next interval tick
      }
    } catch (e) {
      showTopError("Could not start the job:\n" + e.message);
    } finally {
      $("submit-btn").disabled = false;
      $("submit-btn").textContent = "Start generation";
    }
  }

  async function init() {
    wireForm();
    syncMusicVisibility();

    // Jobs/episodes don't depend on metadata or voices at all, so they're kicked off
    // immediately rather than waiting behind them -- previously loadVoices() (which
    // hits Kokoro directly, and Kokoro can be slow to respond mid-synthesis for a
    // running job) was awaited before the jobs/episodes lists even started loading,
    // making a slow Kokoro response stall the entire page rather than just the voice
    // dropdown. The loading bar covers only the genuinely dependent part -- filling in
    // the domain/visual-style/voice dropdowns and the preset that picks values from them.
    pollAllJobs();
    loadEpisodes();
    $("refresh-episodes-btn").addEventListener("click", loadEpisodes);

    const loadingBar = $("init-loading-bar");
    loadingBar.classList.add("show");
    try {
      await Promise.all([loadMetadata(), loadVoices()]);
    } finally {
      loadingBar.classList.remove("show");
    }

    applyPreset(BUILTIN_PRESETS["Relaxed Documentary"]);
    wirePresets();
    updateSummary();

    // One shared interval refreshes both panels from server truth -- this is what makes
    // a job started elsewhere (another browser, the chat tool) show up here without a
    // manual reload, and keeps this page's own submitted jobs live too.
    setInterval(() => {
      pollAllJobs();
      loadEpisodes();
    }, POLL_INTERVAL_MS);
  }

  document.addEventListener("DOMContentLoaded", init);
})();

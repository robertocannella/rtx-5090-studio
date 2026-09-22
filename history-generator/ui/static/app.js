(() => {
  "use strict";

  const PRESETS_KEY = "episodeGeneratorPresets";
  const JOBS_KEY = "episodeGeneratorJobs";
  const POLL_INTERVAL_MS = 8000;

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
  const pollers = {};

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

  function loadTrackedJobs() {
    try {
      return JSON.parse(localStorage.getItem(JOBS_KEY) || "[]");
    } catch {
      return [];
    }
  }

  function saveTrackedJobs(jobs) {
    try {
      localStorage.setItem(JOBS_KEY, JSON.stringify(jobs));
    } catch {
      /* ignore */
    }
  }

  function addTrackedJob(job) {
    const jobs = loadTrackedJobs();
    jobs.unshift(job);
    saveTrackedJobs(jobs.slice(0, 20)); // keep the list from growing unbounded
  }

  function removeTrackedJob(jobId) {
    saveTrackedJobs(loadTrackedJobs().filter((j) => j.job_id !== jobId));
    const card = document.getElementById(`job-${jobId}`);
    if (card) card.remove();
    if (pollers[jobId]) {
      clearInterval(pollers[jobId]);
      delete pollers[jobId];
    }
  }

  function jobCardHtml(job) {
    return `
      <div class="job-card" id="job-${job.job_id}">
        <div class="job-title">${escapeHtml(job.topic)}</div>
        <div class="job-meta">slug: ${escapeHtml(job.slug)} &middot; job: ${escapeHtml(job.job_id)}</div>
        <div class="progress-bar"><div style="width:0%"></div></div>
        <div class="job-status-line">Checking status...</div>
        <button type="button" class="small remove-job-btn" data-job-id="${escapeHtml(job.job_id)}">Remove from list</button>
      </div>`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function renderJobs() {
    const jobs = loadTrackedJobs();
    const list = $("jobs-list");
    if (jobs.length === 0) {
      list.innerHTML = '<p class="hint">Jobs you start will appear here, with live progress.</p>';
      return;
    }
    list.innerHTML = jobs.map(jobCardHtml).join("");
    list.querySelectorAll(".remove-job-btn").forEach((btn) => {
      btn.addEventListener("click", () => removeTrackedJob(btn.dataset.jobId));
    });
    jobs.forEach((job) => pollJob(job.job_id));
  }

  function pollJob(jobId) {
    if (pollers[jobId]) return;
    const tick = async () => {
      const card = document.getElementById(`job-${jobId}`);
      if (!card) { clearInterval(pollers[jobId]); delete pollers[jobId]; return; }
      let data;
      try {
        data = await apiGet(`/api/jobs/${jobId}`);
      } catch (e) {
        card.querySelector(".job-status-line").textContent = "Could not reach history-api: " + e.message;
        return;
      }
      renderJobCard(card, data);
      if (data.status !== "queued" && data.status !== "running") {
        clearInterval(pollers[jobId]);
        delete pollers[jobId];
      }
    };
    tick();
    pollers[jobId] = setInterval(tick, POLL_INTERVAL_MS);
  }

  function renderJobCard(card, data) {
    const progress = data.progress || {};
    const total = progress.segments_total || 0;
    const complete = progress.segments_complete || 0;
    const pct = total > 0 ? Math.round((complete / total) * 100) : (data.status === "complete" ? 100 : 0);
    card.querySelector(".progress-bar > div").style.width = pct + "%";

    const statusLine = card.querySelector(".job-status-line");
    statusLine.className = "job-status-line status-" + data.status;

    const bits = [`Status: ${data.status}`];
    if (total) bits.push(`${complete}/${total} segments`);
    if (progress.narration_seconds !== undefined && progress.target_duration_seconds) {
      bits.push(`${Math.round(progress.narration_seconds)}s / ${progress.target_duration_seconds}s narration`);
    }
    if (progress.domain) bits.push(`domain: ${progress.domain}`);
    if (progress.visual_family) bits.push(`visual: ${progress.visual_family}`);

    let html = bits.join(" &middot; ");
    if (data.status === "error" && data.error) {
      html += `<br>Error: ${escapeHtml(data.error)}`;
    }
    if (data.status === "complete") {
      const hostPath = progress.final_video_host_path;
      if (hostPath) {
        html += `<br>Final video: <span class="host-path">${escapeHtml(hostPath)}</span>`;
      } else if (progress.final_video_path) {
        html += `<br>Final video (container path -- open directly on the server): <span class="host-path">${escapeHtml(progress.final_video_path)}</span>`;
      }
    }
    statusLine.innerHTML = html;
  }

  // ---- all episodes -------------------------------------------------------

  async function loadEpisodes() {
    const list = $("episodes-list");
    list.innerHTML = '<p class="hint">Loading...</p>';
    let episodes;
    try {
      episodes = await apiGet("/api/episodes");
    } catch (e) {
      list.innerHTML = `<p class="hint">Could not load episodes: ${escapeHtml(e.message)}</p>`;
      return;
    }
    if (!episodes.length) {
      list.innerHTML = '<p class="hint">No episodes yet.</p>';
      return;
    }
    list.innerHTML = episodes
      .map((ep) => {
        const status = ep.final_video_exists ? "done" : "in progress";
        const domainTag = ep.domain ? `<span class="tag">${escapeHtml(ep.domain)}</span>` : "";
        return `<div class="episode-row">
          <span>${escapeHtml(ep.title || ep.topic)} ${domainTag}</span>
          <span>${ep.segments_complete}/${ep.segments_total} segments &middot; ${status}</span>
        </div>`;
      })
      .join("");
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
        addTrackedJob({
          job_id: data.job_id,
          slug: data.slug,
          topic: payload.topic,
          started_at: Date.now(),
        });
        renderJobs();
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
    await loadMetadata();
    await loadVoices();
    applyPreset(BUILTIN_PRESETS["Relaxed Documentary"]);
    wirePresets();
    renderJobs();
    loadEpisodes();
    $("refresh-episodes-btn").addEventListener("click", loadEpisodes);
    updateSummary();
  }

  document.addEventListener("DOMContentLoaded", init);
})();

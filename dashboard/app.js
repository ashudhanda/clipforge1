/* ClipForge dashboard — vanilla JS, fetch API. No build step. */
"use strict";

/* ---------------- helpers ---------------- */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(fn, body) {
  const r = await fetch("/api/" + fn, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

let toastTimer = null;
function toast(msg, isErr) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.toggle("err", !!isErr);
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 3200);
}

const baseName = (p) => String(p || "").split("/").pop();
const mediaUrl = (clip) => "/media/" + encodeURIComponent(baseName(clip.file));

/* (2) CountUp — rAF + easeOutExpo */
function countUp(el, to) {
  const from = parseFloat(el.dataset.count || "0");
  to = Number(to) || 0;
  if (from === to) { el.textContent = to; return; }
  const t0 = performance.now(), dur = 900;
  function frame(t) {
    const p = Math.min(1, (t - t0) / dur);
    const e = p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
    el.textContent = Math.round(from + (to - from) * e);
    if (p < 1) requestAnimationFrame(frame);
    else el.dataset.count = to;
  }
  requestAnimationFrame(frame);
}

/* ---------------- theme ---------------- */
function initTheme() {
  const saved = localStorage.getItem("cf-theme") || "dark";
  document.documentElement.dataset.theme = saved;
  $("themeBtn").textContent = saved === "dark" ? "🌙" : "☀️";
}
$("themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = cur;
  localStorage.setItem("cf-theme", cur);
  $("themeBtn").textContent = cur === "dark" ? "🌙" : "☀️";
});

/* ---------------- nav ---------------- */
const TITLES = { generate: "Generate", clips: "Clips", uploads: "Uploads", settings: "Settings" };
document.querySelectorAll(".rail button[data-page]").forEach((b) => {
  b.addEventListener("click", () => showPage(b.dataset.page));
});
function showPage(name) {
  document.querySelectorAll(".rail button[data-page]").forEach((b) =>
    b.classList.toggle("active", b.dataset.page === name));
  document.querySelectorAll(".page").forEach((p) =>
    p.classList.toggle("active", p.id === "page-" + name));
  $("pageTitle").textContent = TITLES[name] || "";
  if (name === "clips") renderClips();
  if (name === "uploads") renderUploads();
  if (name === "settings") renderSettings();
}

/* ---------------- topbar pills ---------------- */
async function refreshPills() {
  try {
    const q = await api("quota");
    const pill = $("quotaPill");
    pill.innerHTML = `quota <b>${q.used}/${q.per_day}</b>`;
    pill.classList.toggle("warn", q.remaining < q.per_upload);
  } catch (e) { /* offline-ish, ignore */ }
  try {
    const r = await api("youtube_authorized");
    const authed = r.result === true;
    const pill = $("ytPill");
    pill.innerHTML = authed ? "YT <b>✓</b>" : "YT <b>✗</b>";
    pill.classList.toggle("ok", authed);
    pill.classList.toggle("warn", !authed);
  } catch (e) { /* ignore */ }
}

/* ---------------- shared: styles + niches ---------------- */
let STYLES = [];
async function loadStyles() {
  const r = await api("caption_styles");
  STYLES = Array.isArray(r) ? r : (r.result || []);
  ["autoStyle", "linkStyle", "sStyle", "wStyle"].forEach((id) => {
    const sel = $(id);
    if (!sel) return;
    sel.innerHTML = STYLES.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  });
}
function fillNiches(selectEl, presets, current) {
  const keys = Object.keys(presets || {});
  selectEl.innerHTML = keys.map((k) => `<option value="${esc(k)}">${esc(k)}</option>`).join("");
  if (current) selectEl.value = current;
}

/* ---------------- generate page ---------------- */
$("tabAuto").addEventListener("click", () => {
  $("tabAuto").classList.add("active"); $("tabLink").classList.remove("active");
  $("paneAuto").classList.remove("hidden"); $("paneLink").classList.add("hidden");
});
$("tabLink").addEventListener("click", () => {
  $("tabLink").classList.add("active"); $("tabAuto").classList.remove("active");
  $("paneLink").classList.remove("hidden"); $("paneAuto").classList.add("hidden");
});

let pollTimer = null;
function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

function pollJob(jobId, barEl, logEl, doneLabel) {
  stopPoll();
  pollTimer = setInterval(async () => {
    try {
      const w = await api("get_status", { job_id: jobId });
      if (!w.ok) { logEl.innerHTML = "<b>Error:</b> " + esc(w.error); stopPoll(); return; }
      const job = w.job;
      // inner pipeline job has the live stage progress
      let prog = job.progress || 0, msg = job.message || job.status || "";
      if (job.inner_job_id && job.status !== "done" && job.status !== "failed") {
        const inner = await api("get_status", { job_id: job.inner_job_id });
        if (inner.ok && inner.job) {
          prog = inner.job.progress || prog;
          msg = inner.job.message || msg;
        }
      }
      barEl.style.width = Math.round(prog * 100) + "%";
      logEl.innerHTML = "<b>" + Math.round(prog * 100) + "%</b> — " + esc(msg || "kaam chal raha hai…");
      if (job.status === "done") {
        stopPoll();
        const n = (job.result && job.result.clips ? job.result.clips.length : 0);
        barEl.style.width = "100%";
        logEl.innerHTML = "<b>Ho gaya! 🎉</b> " + esc(job.message || (n + " clips taiyaar"));
        toast(n + " clips taiyaar — Clips page pe dekho");
        setTimeout(() => showPage("clips"), 1200);
      } else if (job.status === "failed") {
        stopPoll();
        logEl.innerHTML = "<b>Fail ho gaya:</b> " + esc(job.error || job.message || "pata nahi");
        toast("Generation fail: " + (job.error || ""), true);
      }
    } catch (e) {
      logEl.innerHTML = "<b>Server se baat nahi ho rahi.</b>";
      stopPoll();
    }
  }, 2000);
}

$("autoStart").addEventListener("click", async () => {
  const btn = $("autoStart");
  btn.disabled = true;
  $("autoJob").classList.remove("hidden");
  $("autoBar").style.width = "0%";
  $("autoLog").textContent = "Shuru ho raha hai…";
  try {
    const r = await api("start_auto", {
      niche: $("autoNiche").value.trim() || null,
      n_clips: parseInt($("autoClips").value, 10) || null,
      caption_style: $("autoStyle").value || null,
    });
    if (r.job_id) pollJob(r.job_id, $("autoBar"), $("autoLog"));
    else { $("autoLog").innerHTML = "<b>Error:</b> " + esc(r.error || "start nahi hua"); btn.disabled = false; }
  } catch (e) { $("autoLog").textContent = "Server error."; btn.disabled = false; }
});

$("linkStart").addEventListener("click", async () => {
  const url = $("linkUrl").value.trim();
  if (!url) { toast("Pehle YouTube link daalo", true); return; }
  const btn = $("linkStart");
  btn.disabled = true;
  $("linkJob").classList.remove("hidden");
  $("linkBar").style.width = "0%";
  $("linkLog").textContent = "Shuru ho raha hai…";
  try {
    const r = await api("start_link", {
      url,
      n_clips: parseInt($("linkClips").value, 10) || null,
      caption_style: $("linkStyle").value || null,
    });
    if (r.job_id) pollJob(r.job_id, $("linkBar"), $("linkLog"));
    else { $("linkLog").innerHTML = "<b>Error:</b> " + esc(r.error || "start nahi hua"); btn.disabled = false; }
  } catch (e) { $("linkLog").textContent = "Server error."; btn.disabled = false; }
});

/* ---------------- clips page ---------------- */
let clipFilter = "all";
let selectedClip = null;

document.querySelectorAll("#clipFilters button").forEach((b) => {
  b.addEventListener("click", () => {
    clipFilter = b.dataset.f;
    document.querySelectorAll("#clipFilters button").forEach((x) =>
      x.classList.toggle("active", x === b));
    renderClips();
  });
});

/* (3) SpotlightCard — glow follows the mouse */
$("clipGrid").addEventListener("pointermove", (e) => {
  const card = e.target.closest(".clip-card");
  if (!card) return;
  const r = card.getBoundingClientRect();
  card.style.setProperty("--mx", (e.clientX - r.left) + "px");
  card.style.setProperty("--my", (e.clientY - r.top) + "px");
});

async function renderClips() {
  const grid = $("clipGrid");
  grid.innerHTML = '<p class="muted">Loading…</p>';
  const cr = await api("list_clips", { status: clipFilter === "all" ? null : clipFilter });
  const list = cr.result || (Array.isArray(cr) ? cr : []);
  if (!list.length) {
    grid.innerHTML = '<p class="muted">Koi clips nahi. Generate page se banao 👆</p>';
    return;
  }
  grid.innerHTML = "";
  list.forEach((c) => {
    const d = document.createElement("div");
    d.className = "clip-card" + (selectedClip === c.clip_id ? " selected" : "");
    d.innerHTML =
      `<video preload="metadata" muted playsinline src="${esc(mediaUrl(c))}#t=0.5"></video>` +
      `<div class="meta"><p class="t">${esc(c.title || "(bina title)")}</p>` +
      `<span class="badge ${esc(c.status || "queued")}">${esc(c.status || "queued")}</span>` +
      `<span class="score">score <b>${esc(Number(c.moment_score || 0).toFixed(1))}</b></span></div>`;
    d.addEventListener("click", () => { selectedClip = c.clip_id; renderDetail(c.clip_id); renderClipsSel(); });
    grid.appendChild(d);
  });
}
function renderClipsSel() {
  document.querySelectorAll(".clip-card").forEach(() => {});
}

async function renderDetail(clipId) {
  const panel = $("detailPanel");
  const c = await api("get_clip", { clip_id: clipId });
  if (!c || c.error) { panel.innerHTML = '<div class="empty-panel">Clip nahi mila</div>'; return; }
  const tags = (c.hashtags || []).join(" ");
  panel.innerHTML = `
    <video controls preload="metadata" src="${esc(mediaUrl(c))}"></video>
    <div class="mt">
      <span class="badge ${esc(c.status)}">${esc(c.status)}</span>
      <span class="score">score <b>${esc(Number(c.moment_score || 0).toFixed(1))}</b></span>
      <span class="score">style: ${esc(c.caption_style || "")}</span>
    </div>
    ${c.hook_line ? `<p class="small" style="margin:10px 0 0"><b>Hook:</b> ${esc(c.hook_line)}</p>` : ""}
    <label class="field mt"><span>Title</span><input type="text" id="dTitle" value="${esc(c.title || "")}" maxlength="100"></label>
    <label class="field"><span>Description</span><textarea id="dDesc">${esc(c.description || "")}</textarea></label>
    <label class="field"><span>Hashtags (space se alag)</span><input type="text" id="dTags" value="${esc(tags)}"></label>
    <div class="btn-row">
      <button class="btn sm ghost" id="dSave">💾 Save</button>
      <button class="btn sm" id="dApprove">✓ Approve</button>
      <button class="btn sm ghost" id="dReject">✗ Reject</button>
    </div>
    <div class="btn-row">
      <button class="btn sm pink" id="dUpload">⬆ Upload now</button>
      <button class="btn sm danger ghost" id="dDelete">Delete</button>
    </div>
    <label class="field mt"><span>Schedule — kab upload ho (future time)</span>
      <input type="datetime-local" id="dAt"></label>
    <div class="btn-row"><button class="btn sm ghost" id="dSchedule">⏰ Schedule</button></div>
    ${c.source_video_url ? `<p class="small mt"><a class="yt-link" href="${esc(c.source_video_url)}" target="_blank" rel="noopener">Source video ↗</a></p>` : ""}
    ${c.youtube_url ? `<p class="small"><a class="yt-link" href="${esc(c.youtube_url)}" target="_blank" rel="noopener">YouTube pe dekho ↗</a></p>` : ""}`;

  const min = new Date(Date.now() + 5 * 60000);
  $("dAt").min = min.toISOString().slice(0, 16);

  $("dSave").onclick = async () => {
    const r = await api("update_clip_meta", { clip_id: clipId, patch: {
      title: $("dTitle").value, description: $("dDesc").value, hashtags: $("dTags").value } });
    toast(r.ok ? "Save ho gaya ✓" : ("Error: " + r.error), !r.ok);
    renderClips();
  };
  $("dApprove").onclick = async () => {
    const r = await api("approve_clip", { clip_id: clipId });
    toast(r.ok ? "Approved ✓" : ("Error: " + r.error), !r.ok);
    renderDetail(clipId); renderClips();
  };
  $("dReject").onclick = async () => {
    const r = await api("reject_clip", { clip_id: clipId });
    toast(r.ok ? "Rejected" : ("Error: " + r.error), !r.ok);
    renderDetail(clipId); renderClips();
  };
  $("dDelete").onclick = async () => {
    if (!confirm("Ye clip delete kar dun? File bhi delete hogi.")) return;
    const r = await api("delete_clip", { clip_id: clipId });
    toast(r.ok ? "Delete ho gaya" : ("Error: " + r.error), !r.ok);
    selectedClip = null;
    panel.innerHTML = '<div class="empty-panel">👈 Koi clip select karo</div>';
    renderClips();
  };
  $("dUpload").onclick = async () => {
    const btn = $("dUpload"); btn.disabled = true; btn.textContent = "Uploading…";
    const r = await api("upload_clip", { clip_id: clipId });
    btn.disabled = false; btn.textContent = "⬆ Upload now";
    if (r.ok) { toast("Live! 🎉 " + r.url); }
    else toast("Upload fail: " + (r.error || ""), true);
    renderDetail(clipId); renderClips(); refreshPills();
  };
  $("dSchedule").onclick = async () => {
    const at = $("dAt").value.replace("T", " ");
    if (!at) { toast("Pehle date-time select karo", true); return; }
    const r = await api("schedule_clip", { clip_id: clipId, at });
    toast(r.ok ? r.message : ("Error: " + r.error), !r.ok);
    renderDetail(clipId); renderClips();
  };
}

/* ---------------- uploads page ---------------- */
async function renderUploads() {
  const [cr, sr, q] = await Promise.all([
    api("list_clips", {}), api("list_scheduled", {}), api("quota", {}),
  ]);
  const list = cr.result || (Array.isArray(cr) ? cr : []);
  const ready = list.filter((c) => ["queued", "approved"].includes(c.status)).length;
  const uploaded = list.filter((c) => c.status === "uploaded").length;
  const jobs = sr.result || (Array.isArray(sr) ? sr : []);
  countUp($("stReady"), ready);
  countUp($("stUploaded"), uploaded);
  countUp($("stSched"), jobs.length);
  countUp($("stQuota"), q.used || 0);
  $("stQuota").nextElementSibling.textContent = `quota used / ${q.per_day || 10000}`;

  const sl = $("schedList");
  if (!jobs.length) sl.innerHTML = '<p class="muted">Koi scheduled upload nahi hai.</p>';
  else {
    sl.innerHTML = "";
    jobs.forEach((j) => {
      const cid = (j.params || {}).clip_id;
      const clip = list.find((c) => c.clip_id === cid);
      const row = document.createElement("div");
      row.className = "q-row";
      row.innerHTML = `<div class="info"><div class="t">${esc(clip ? clip.title : cid)}</div>
        <div class="s">⏰ ${esc(j.at_human || "")} · ${esc(j.status || "")}</div></div>`;
      const btn = document.createElement("button");
      btn.className = "btn sm ghost"; btn.textContent = "Cancel";
      btn.onclick = async () => {
        const r = await api("cancel_schedule", { clip_id: cid });
        toast(r.ok ? r.message : ("Error: " + r.error), !r.ok);
        renderUploads();
      };
      row.appendChild(btn);
      sl.appendChild(row);
    });
  }

  const hl = $("histList");
  const ups = list.filter((c) => c.status === "uploaded").reverse();
  if (!ups.length) hl.innerHTML = '<p class="muted">Abhi tak kuch upload nahi hua.</p>';
  else {
    hl.innerHTML = "";
    ups.forEach((c) => {
      const row = document.createElement("div");
      row.className = "q-row";
      row.innerHTML = `<div class="info"><div class="t">${esc(c.title || "(bina title)")}</div>
        <div class="s">${c.youtube_url ? `<a class="yt-link" href="${esc(c.youtube_url)}" target="_blank" rel="noopener">YouTube ↗</a>` : ""}</div></div>`;
      hl.appendChild(row);
    });
  }
}

$("workerBtn").addEventListener("click", async () => {
  const btn = $("workerBtn"); btn.disabled = true; btn.textContent = "Checking…";
  const r = await api("run_worker_once", {});
  btn.disabled = false; btn.textContent = "▶ Process due now";
  if (r && typeof r.done !== "undefined")
    toast(`Done: ${r.done} uploaded, ${r.missed || 0} missed, ${r.failed || 0} failed`);
  else toast("Error: " + ((r && r.error) || "pata nahi"), true);
  renderUploads(); refreshPills();
});

/* ---------------- settings page ---------------- */
async function renderSettings() {
  const cfg = await api("get_config", {});
  $("sChannel").value = cfg.channel_name || "";
  fillNiches($("sNiche"), cfg.niche_presets, cfg.niche);
  $("sClipsPerRun").value = cfg.clips_per_run || 5;
  $("sStyle").value = cfg.caption_style || STYLES[0] || "hormozi";
  $("sHook").value = cfg.hook_mode || "card";
  $("sPrivacy").value = cfg.privacy || "public";
  $("sKids").checked = !!cfg.made_for_kids;
  $("sMinClip").value = cfg.min_clip_s || 25;
  $("sMaxClip").value = cfg.max_clip_s || 58;
  $("sHashtags").value = (cfg.hashtags || []).join(" ");
  const rs = cfg.research || {};
  $("sMinDur").value = rs.min_duration_min || 20;
  $("sMaxAge").value = rs.max_age_days || 30;
  $("sMinViews").value = rs.min_views || 50000;
  window._cfgCache = cfg;
  const llm = cfg.llm || {};
  $("sLlm").value = llm.provider || "none";
  $("sModel").value = llm.model || "";
  $("sBaseUrl").value = llm.base_url || "";
  toggleLlmFields();
  const ks = await api("llm_key_status", {});
  $("sGemHint").textContent = ks.gemini_set ? "(set ✓ — khaali chhodo ya naya daalo)" : "(not set)";
  $("sOaiHint").textContent = ks.openai_set ? "(set ✓)" : "(not set)";
  $("sGemKey").value = ""; $("sOaiKey").value = "";
  $("sGemKey").placeholder = ks.gemini_set ? "•••••• (set hai)" : "API key daalo";
  $("sOaiKey").placeholder = ks.openai_set ? "•••••• (set hai)" : "API key daalo (optional)";
  refreshYtStatus(); refreshCsStatus();
}
function toggleLlmFields() {
  const p = $("sLlm").value;
  $("sModel").closest(".field").style.display = p === "none" ? "none" : "";
  $("sBaseUrlWrap").style.display = p === "openai_compat" ? "" : "none";
}
$("sLlm").addEventListener("change", toggleLlmFields);

$("saveSettings").addEventListener("click", async () => {
  const btn = $("saveSettings"); btn.disabled = true;
  const oldRs = (window._cfgCache && window._cfgCache.research) || {};
  const patch = {
    channel_name: $("sChannel").value.trim(),
    niche: $("sNiche").value,
    clips_per_run: parseInt($("sClipsPerRun").value, 10) || 5,
    caption_style: $("sStyle").value,
    hook_mode: $("sHook").value,
    privacy: $("sPrivacy").value,
    made_for_kids: $("sKids").checked,
    min_clip_s: Math.max(5, parseInt($("sMinClip").value, 10) || 25),
    max_clip_s: Math.max(10, parseInt($("sMaxClip").value, 10) || 58),
    hashtags: $("sHashtags").value.split(/\s+/).map(h => h.trim()).filter(Boolean),
    research: Object.assign({}, oldRs, {
      min_duration_min: Math.max(1, parseInt($("sMinDur").value, 10) || 20),
      max_age_days: Math.max(1, parseInt($("sMaxAge").value, 10) || 30),
      min_views: Math.max(0, parseInt($("sMinViews").value, 10) || 0),
    }),
    llm: { provider: $("sLlm").value, model: $("sModel").value.trim(), base_url: $("sBaseUrl").value.trim() },
  };
  const r = await api("update_config", { patch });
  if ($("sGemKey").value) await api("set_llm_key", { provider: "gemini", key: $("sGemKey").value });
  if ($("sOaiKey").value) await api("set_llm_key", { provider: "openai_compat", key: $("sOaiKey").value });
  btn.disabled = false;
  toast(r.ok ? "Settings save ho gayin ✓" : ("Error: " + r.error), !r.ok);
  renderSettings(); refreshPills();
});

async function refreshYtStatus() {
  const r = await api("youtube_authorized", {});
  const ok = r.result === true;
  $("ytStatus").innerHTML = ok
    ? '✅ <b style="color:var(--primary)">YouTube connected</b> — upload/schedule ready hai.'
    : '❌ <b>YouTube connected nahi hai.</b> Upload ke liye connect karo (neeche steps dekho).';
}
$("ytConnect").addEventListener("click", async () => {
  const r = await api("youtube_connect", {});
  if (!r.ok) { toast(r.error || "Connect fail", true); return; }
  toast("Browser khul raha hai — Google login karo…");
  $("ytStatus").textContent = "⏳ Login ka wait ho raha hai… (browser mein Google login karo)";
  for (let i = 0; i < 40; i++) {
    await new Promise((res) => setTimeout(res, 3000));
    const s = await api("youtube_authorized", {});
    if (s.result === true) { toast("YouTube connected! 🎉"); break; }
  }
  refreshYtStatus(); refreshPills();
});
$("ytDisconnect").addEventListener("click", async () => {
  await api("youtube_disconnect", {});
  toast("YouTube disconnected");
  refreshYtStatus(); refreshPills();
});
async function refreshCsStatus() {
  const r = await api("client_secret_status", {});
  $("csStatus").innerHTML = r.configured
    ? '🔑 OAuth JSON <b style="color:var(--primary)">saved ✓</b> — ab "Connect YouTube" dabao.'
    : '🔑 OAuth JSON <b>saved nahi hai</b> — neeche steps se lao aur paste karo.';
}
$("csSave").addEventListener("click", async () => {
  const v = $("csJson").value;
  const r = await api("save_client_secret", { json_text: v });
  if (!r.ok) { toast(r.error || "Save fail", true); return; }
  $("csJson").value = "";
  toast("OAuth JSON save ho gaya ✓ — ab Connect YouTube dabao");
  refreshCsStatus();
});
$("clearCache").addEventListener("click", async () => {
  if (!confirm("Scratch cache saaf kar dun? (Clips/config safe rahenge)")) return;
  const r = await api("clear_cache", {});
  toast(r.ok ? `${r.cleared} items saaf ho gaye` : ("Error: " + r.error), !r.ok);
});

/* ---------------- first-run wizard ---------------- */
let wStep = 0;
async function maybeWizard() {
  const r = await api("is_first_run", {});
  if (r.result !== true) return;
  const cfg = await api("get_config", {});
  fillNiches($("wNiche"), cfg.niche_presets, cfg.niche || "podcast");
  $("wStyle").value = cfg.caption_style || STYLES[0] || "hormozi";
  $("wClips").value = cfg.clips_per_run || 5;
  $("wizard").classList.remove("hidden");
  setWStep(0);
}
function setWStep(n) {
  wStep = Math.max(0, Math.min(2, n));
  document.querySelectorAll(".wstep").forEach((s) =>
    s.classList.toggle("on", parseInt(s.dataset.s, 10) === wStep));
  document.querySelectorAll(".wizard .steps i").forEach((d, i) =>
    d.classList.toggle("on", i <= wStep));
  $("wBack").style.visibility = wStep === 0 ? "hidden" : "visible";
  $("wNext").textContent = wStep === 2 ? "✅ Finish setup" : "Next →";
}
$("wBack").addEventListener("click", () => setWStep(wStep - 1));
$("wNext").addEventListener("click", async () => {
  if (wStep < 2) { setWStep(wStep + 1); return; }
  // finish: save everything
  const btn = $("wNext"); btn.disabled = true;
  const llmProv = $("wLlm").value;
  const patch = {
    channel_name: $("wChannel").value.trim(),
    niche: $("wNiche").value,
    clips_per_run: parseInt($("wClips").value, 10) || 5,
    caption_style: $("wStyle").value,
    made_for_kids: $("wKids").checked,
    privacy: $("wPrivacy").value,
    llm: { provider: llmProv,
           model: $("wModel").value.trim() || (llmProv === "gemini" ? "gemini-2.0-flash" : ""),
           base_url: $("wBaseUrl").value.trim() },
  };
  const r = await api("update_config", { patch });
  const key = $("wKey").value.trim();
  if (key && llmProv !== "none")
    await api("set_llm_key", { provider: llmProv, key });
  btn.disabled = false;
  if (!r.ok) { toast("Error: " + r.error, true); return; }
  $("wizard").classList.add("hidden");
  toast("Setup complete! 🎉 Ab clips banao");
  refreshPills();
});
$("wLlm").addEventListener("change", () => {
  const p = $("wLlm").value;
  $("wLlmFields").classList.toggle("hidden", p === "none");
  $("wBaseUrlWrap").classList.toggle("hidden", p !== "openai_compat");
  if (p === "gemini" && !$("wModel").value) $("wModel").value = "gemini-2.0-flash";
});
$("wYtConnect").addEventListener("click", async () => {
  const r = await api("youtube_connect", {});
  if (!r.ok) { $("wYtStatus").textContent = "⚠️ " + (r.error || "fail"); return; }
  $("wYtStatus").textContent = "⏳ Browser mein Google login karo…";
  for (let i = 0; i < 40; i++) {
    await new Promise((res) => setTimeout(res, 3000));
    const s = await api("youtube_authorized", {});
    if (s.result === true) { $("wYtStatus").textContent = "✅ Connected!"; break; }
  }
});

/* ---------------- boot ---------------- */
(async function boot() {
  initTheme();
  await loadStyles();
  const cfg = await api("get_config", {});
  $("autoNiche").value = cfg.niche || "podcast";
  $("autoClips").value = cfg.clips_per_run || 5;
  $("autoStyle").value = cfg.caption_style || STYLES[0] || "hormozi";
  $("linkStyle").value = cfg.caption_style || STYLES[0] || "hormozi";
  $("linkClips").value = cfg.clips_per_run || 5;
  const keys = Object.keys(cfg.niche_presets || {});
  $("nicheList").innerHTML = keys.map((k) => `<option value="${esc(k)}">`).join("");
  refreshPills();
  setInterval(refreshPills, 60000);
  maybeWizard();
})();

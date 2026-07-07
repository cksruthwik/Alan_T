/* Alan_T web UI — a single-file client for the /api/v1 API.
   No frameworks, no external assets, token-authenticated. */

"use strict";

const $ = (id) => document.getElementById(id);
const API = location.origin;
let TOKEN = localStorage.getItem("alan_token") || "";

let currentSession = null;   // {session_id, title, project, ...}
let sessions = [];
let chatWS = null;           // streaming chat socket for current session
let voiceWS = null;          // push-to-talk socket
let goalArmed = false;
let streamingEl = null;      // bot bubble currently receiving tokens
let audioQueue = [];         // wav blobs queued for sequential playback
let audioPlaying = false;

/* ── tiny helpers ─────────────────────────────────────────────────── */

async function api(path, opts = {}) {
  const headers = { Authorization: `Bearer ${TOKEN}`, ...(opts.headers || {}) };
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
  }
  const r = await fetch(`${API}${path}`, { ...opts, headers });
  if (r.status === 401) { showGate("Token rejected — paste a valid one."); throw new Error("401"); }
  if (!r.ok) throw new Error(`${r.status} ${await r.text().catch(() => "")}`);
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r;
}

function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* Minimal markdown: fences, inline code, bold, italics, links, headers, bullets. */
function md(text) {
  const fences = [];
  text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    fences.push(`<pre><code>${esc(code.replace(/\n$/, ""))}</code></pre>`);
    // private-use sentinels: cannot collide with real message text
    // (a bare ' 3 ' placeholder used to eat plain numbers in replies)
    return `\uE000${fences.length - 1}\uE001`;
  });
  let h = esc(text)
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|\s)\*([^*\n]+)\*(?=\s|$|[.,!?])/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
             '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/^######? (.+)$/gm, "<strong>$1</strong>")
    .replace(/^#{1,4} (.+)$/gm, "<strong>$1</strong>")
    .replace(/^[-*] (.+)$/gm, "• $1");
  h = h.replace(/\uE000(\d+)\uE001/g, (_, i) => fences[+i] ?? "");
  return h;
}

function addMsg(role, text, { agent = "", streaming = false } = {}) {
  $("empty-hint")?.remove();
  const el = document.createElement("div");
  el.className = `msg ${role}${streaming ? " streaming" : ""}`;
  if (agent && role === "bot")
    el.innerHTML = `<span class="agent-tag">${esc(agent)}</span>`;
  const body = document.createElement("span");
  body.className = "body";
  body.innerHTML = role === "user" ? esc(text) : md(text);
  el.appendChild(body);
  $("messages").appendChild(el);
  $("messages").scrollTop = $("messages").scrollHeight;
  return el;
}

function setStreamText(el, text) {
  el.querySelector(".body").innerHTML = md(text);
  $("messages").scrollTop = $("messages").scrollHeight;
}

/* ── token gate ───────────────────────────────────────────────────── */

function showGate(err = "") {
  $("gate").classList.remove("hidden");
  $("app").classList.add("hidden");
  $("gate-err").textContent = err;
}

async function tryConnect() {
  try {
    const deps = await api("/api/v1/health/deps");
    $("gate").classList.add("hidden");
    $("app").classList.remove("hidden");
    const ok = deps.postgres === "ok";
    $("health-dot").className = `dot ${ok ? "ok" : "bad"}`;
    $("health-text").textContent = ok ? "connected" : "db down";
    await boot();
  } catch (e) {
    if (e.message !== "401") showGate("Can't reach the backend — is it running?");
  }
}

$("gate-go").onclick = () => {
  TOKEN = $("gate-token").value.trim();
  localStorage.setItem("alan_token", TOKEN);
  tryConnect();
};
$("gate-token").addEventListener("keydown", (e) => { if (e.key === "Enter") $("gate-go").click(); });
$("btn-logout").onclick = () => { localStorage.removeItem("alan_token"); location.reload(); };

/* ── sessions sidebar ─────────────────────────────────────────────── */

async function loadSessions(selectId = null) {
  sessions = await api("/api/v1/chat/sessions");
  const list = $("session-list");
  list.innerHTML = "";
  const groups = new Map([["", []]]);
  for (const s of sessions) {
    const key = s.project || "";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(s);
  }
  for (const [proj, items] of [...groups].sort((a, b) => a[0].localeCompare(b[0]))) {
    if (!items.length) continue;
    if (proj) {
      const label = document.createElement("div");
      label.className = "proj-label";
      label.textContent = `🗂 ${proj}`;
      list.appendChild(label);
    }
    for (const s of items) {
      const el = document.createElement("div");
      el.className = "session-item" + (currentSession?.session_id === s.session_id ? " active" : "");
      el.innerHTML = `<span class="t">${esc(s.title || "New chat")}</span>` +
                     (s.channel !== "web" ? `<span class="ch">${esc(s.channel)}</span>` : "");
      el.onclick = () => openSession(s);
      list.appendChild(el);
    }
  }
  if (selectId) {
    const s = sessions.find(x => x.session_id === selectId);
    if (s) await openSession(s);
  }
}

async function openSession(s) {
  currentSession = s;
  $("chat-title").textContent = s.title || "New chat";
  $("chat-project").classList.toggle("hidden", !s.project);
  $("chat-project").textContent = s.project ? `🗂 ${s.project}` : "";
  $("chat-agent").classList.add("hidden");
  $("messages").innerHTML = "";
  const turns = await api(`/api/v1/chat/sessions/${s.session_id}?limit=200`);
  if (!turns.length)
    $("messages").innerHTML = `<div class="empty-hint" id="empty-hint"><h2>${esc(s.title || "New chat")}</h2></div>`;
  for (const t of turns) {
    if (t.role === "user") addMsg("user", t.content);
    else if (t.role === "assistant") addMsg("bot", t.content, { agent: t.agent || "" });
  }
  connectChatWS();
  loadSessions(); // refresh active highlight
}

async function newSession() {
  const r = await api("/api/v1/chat/sessions", { method: "POST", json: { channel: "web" } });
  await loadSessions(r.session_id);
}
$("btn-new").onclick = newSession;

/* chat header actions */
$("btn-rename").onclick = async () => {
  if (!currentSession) return;
  const name = prompt("Chat name:", currentSession.title || "");
  if (!name) return;
  await api(`/api/v1/chat/sessions/${currentSession.session_id}`,
            { method: "PATCH", json: { title: name } });
  await loadSessions(currentSession.session_id);
};
$("btn-delete").onclick = async () => {
  if (!currentSession || !confirm("Delete this chat and its history?")) return;
  await api(`/api/v1/chat/sessions/${currentSession.session_id}`, { method: "DELETE" });
  currentSession = null;
  $("messages").innerHTML = "";
  await loadSessions();
};
$("btn-archive").onclick = async () => {
  if (!currentSession) return;
  await api(`/api/v1/chat/sessions/${currentSession.session_id}`,
            { method: "PATCH", json: { archived: true } });
  currentSession = null;
  $("messages").innerHTML = "";
  await loadSessions();
};
$("btn-assign").onclick = async () => {
  if (!currentSession) return;
  const projects = await api("/api/v1/projects");
  const name = prompt("Project name (existing or new; empty = remove from project):\n" +
                      projects.map(p => `• ${p.name}`).join("\n"));
  if (name === null) return;
  if (!name.trim()) {
    await api(`/api/v1/chat/sessions/${currentSession.session_id}`,
              { method: "PATCH", json: { clear_project: true } });
  } else {
    const r = await api("/api/v1/projects", { method: "POST", json: { name: name.trim() } });
    await api(`/api/v1/chat/sessions/${currentSession.session_id}`,
              { method: "PATCH", json: { project_id: r.project_id } });
  }
  await loadSessions(currentSession.session_id);
};

/* ── chat streaming (WS) ──────────────────────────────────────────── */

function connectChatWS() {
  chatWS?.close();
  if (!currentSession) return;
  const url = `${API.replace("http", "ws")}/api/v1/chat/ws/${currentSession.session_id}?token=${encodeURIComponent(TOKEN)}`;
  chatWS = new WebSocket(url);
  let acc = "";
  chatWS.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "token") {
      if (!streamingEl) { acc = ""; streamingEl = addMsg("bot", "", { streaming: true }); }
      acc += m.text;
      setStreamText(streamingEl, acc);
    } else if (m.type === "done") {
      if (streamingEl) {
        streamingEl.classList.remove("streaming");
        if (m.agent) {
          const tag = document.createElement("span");
          tag.className = "agent-tag";
          tag.textContent = m.agent;
          streamingEl.prepend(tag);
          $("chat-agent").textContent = m.agent;
          $("chat-agent").classList.remove("hidden");
        }
      }
      streamingEl = null;
      loadSessions();       // auto-title may have landed
      refreshApprovals();
    } else if (m.type === "error") {
      streamingEl = null;
      addMsg("system", `⚠ ${m.problem?.detail || m.problem?.title || "error"}`);
    }
  };
}

async function sendMessage() {
  const text = $("input").value.trim();
  if (!text) return;
  if (!currentSession) await newSession();
  $("input").value = "";
  $("input").style.height = "auto";
  addMsg("user", text);

  if (goalArmed) {
    $("btn-goal").classList.remove("armed");
    goalArmed = false;
    return runGoal(text);
  }
  if (chatWS?.readyState === WebSocket.OPEN) {
    chatWS.send(JSON.stringify({ type: "message", content: text }));
  } else {
    // WS not up (e.g. first message right after session create) → REST turn
    try {
      const r = await api(`/api/v1/chat/sessions/${currentSession.session_id}/messages`,
                          { method: "POST", json: { content: text } });
      addMsg("bot", r.content, { agent: r.agent });
      loadSessions();
      refreshApprovals();
    } catch (e) {
      addMsg("system", `⚠ ${e.message.slice(0, 200)}`);
    }
  }
}
$("btn-send").onclick = sendMessage;
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
$("input").addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 180) + "px";
});

/* ── goals (planner) ──────────────────────────────────────────────── */

$("btn-goal").onclick = () => {
  goalArmed = !goalArmed;
  $("btn-goal").classList.toggle("armed", goalArmed);
  $("input").placeholder = goalArmed ? "Describe the goal — I'll plan and execute it…"
                                     : "Message Alan_T…";
};

async function runGoal(goal) {
  const note = addMsg("system", "🎯 planning and executing…");
  try {
    const rec = await api("/api/v1/tasks", { method: "POST", json: { goal } });
    note.remove();
    let out = `🎯 **Goal ${rec.status}**\n`;
    for (const s of rec.steps)
      out += `\n${s.step}. \`${s.agent}\` — ${s.status}\n${s.response.slice(0, 400)}\n`;
    if (rec.reflection) out += `\n_Verdict: ${rec.reflection.verdict || "?"}_`;
    addMsg("bot", out, { agent: "planner" });
    refreshApprovals();
  } catch (e) {
    note.remove();
    addMsg("system", `⚠ goal failed: ${e.message.slice(0, 300)}`);
  }
}

/* ── approvals ────────────────────────────────────────────────────── */

async function refreshApprovals() {
  let pending = [];
  try { pending = await api("/api/v1/approvals"); } catch { return; }
  $("approvals-badge").classList.toggle("hidden", !pending.length);
  $("approvals-badge").textContent = pending.length;
  const strip = $("approval-strip");
  strip.classList.toggle("hidden", !pending.length);
  strip.innerHTML = "";
  for (const a of pending) {
    const row = document.createElement("div");
    row.className = "approval-row";
    row.innerHTML = `<span>🔐</span><span class="preview">${esc(a.preview)}</span>`;
    const yes = document.createElement("button");
    yes.className = "ok"; yes.textContent = "Approve";
    const no = document.createElement("button");
    no.className = "no"; no.textContent = "Deny";
    yes.onclick = () => resolveApproval(a.id, true);
    no.onclick = () => resolveApproval(a.id, false);
    row.append(yes, no);
    strip.appendChild(row);
  }
}

async function resolveApproval(id, approve) {
  try {
    const r = await api(`/api/v1/approvals/${id}`, { method: "POST", json: { approve } });
    addMsg("system", approve ? `✅ ${r.tool}: ${(r.result || "done").slice(0, 300)}`
                             : `❌ denied: ${r.tool}`);
  } catch (e) { addMsg("system", `⚠ ${e.message.slice(0, 150)}`); }
  refreshApprovals();
}
setInterval(refreshApprovals, 20000);

/* ── uploads (library + vision) ───────────────────────────────────── */

$("btn-attach").onclick = () => $("file-input").click();
$("file-input").onchange = async function () {
  if (!this.files[0]) return;
  const fd = new FormData();
  fd.append("file", this.files[0]);
  const note = addMsg("system", `📎 uploading ${this.files[0].name}…`);
  try {
    const r = await api("/api/v1/library/upload", { method: "POST", body: fd });
    note.remove();
    addMsg("system", `📚 saved to library as ${r.saved}` +
                     (r.ingest_started ? " — indexing into knowledge" : ""));
  } catch (e) { note.remove(); addMsg("system", `⚠ upload failed: ${e.message.slice(0, 150)}`); }
  this.value = "";
};

$("btn-image").onclick = () => $("image-input").click();
$("image-input").onchange = async function () {
  if (!this.files[0]) return;
  const question = $("input").value.trim() || "Describe this image in detail.";
  $("input").value = "";
  addMsg("user", `🖼 ${this.files[0].name} — ${question}`);
  const fd = new FormData();
  fd.append("image", this.files[0]);
  fd.append("question", question);
  const note = addMsg("system", "👁 looking…");
  try {
    const r = await api("/api/v1/vision/analyze", { method: "POST", body: fd });
    note.remove();
    addMsg("bot", r.content, { agent: "vision" });
  } catch (e) { note.remove(); addMsg("system", `⚠ vision failed: ${e.message.slice(0, 200)}`); }
  this.value = "";
};

/* drag & drop anywhere → library */
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", (e) => {
  e.preventDefault();
  if (e.dataTransfer.files[0]) {
    $("file-input").files = e.dataTransfer.files;
    $("file-input").onchange.call($("file-input"));
  }
});

/* ── voice: hold-to-talk over WS /voice/live ──────────────────────── */

let recorder = null, recChunks = [];
let voiceWSSession = null;  // session the open socket is bound to

function voiceSocket() {
  const wanted = currentSession?.session_id || null;
  if (voiceWS?.readyState === WebSocket.OPEN && voiceWSSession === wanted) return voiceWS;
  voiceWS?.close();  // rebind: a socket for the previous chat must not swallow this turn
  voiceWSSession = wanted;
  const sid = wanted ? `&session=${wanted}` : "";
  voiceWS = new WebSocket(
    `${API.replace("http", "ws")}/api/v1/voice/live?token=${encodeURIComponent(TOKEN)}${sid}`);
  let acc = "", voiceStreamEl = null;
  voiceWS.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "session" && !currentSession) loadSessions(m.session_id);
    else if (m.type === "transcript") addMsg("user", `🎙 ${m.text}`);
    else if (m.type === "token") {
      if (!voiceStreamEl) { acc = ""; voiceStreamEl = addMsg("bot", "", { streaming: true }); }
      acc += m.text;
      setStreamText(voiceStreamEl, acc);
    } else if (m.type === "audio") {
      enqueueAudio(m.data);
    } else if (m.type === "done") {
      voiceStreamEl?.classList.remove("streaming");
      voiceStreamEl = null;
      loadSessions();
      refreshApprovals();
    } else if (m.type === "error") {
      voiceStreamEl = null;
      addMsg("system", `⚠ ${m.detail}`);
    }
  };
  return voiceWS;
}

function enqueueAudio(b64) {
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  audioQueue.push(new Blob([bytes], { type: "audio/wav" }));
  if (!audioPlaying) playNextAudio();
}
function playNextAudio() {
  const blob = audioQueue.shift();
  if (!blob) { audioPlaying = false; return; }
  audioPlaying = true;
  const audio = new Audio(URL.createObjectURL(blob));
  audio.onended = playNextAudio;
  audio.play().catch(() => { audioPlaying = false; });
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    voiceSocket(); // open early so it's ready at stop
    recChunks = [];
    recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
    recorder.ondataavailable = (e) => recChunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(recChunks, { type: "audio/webm" });
      if (blob.size < 1500) return; // accidental tap
      const buf = new Uint8Array(await blob.arrayBuffer());
      let bin = "";
      for (let i = 0; i < buf.length; i += 0x8000)
        bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
      const ws = voiceSocket();
      const send = () => ws.send(JSON.stringify({ type: "audio", data: btoa(bin), format: "webm" }));
      ws.readyState === WebSocket.OPEN ? send() : (ws.onopen = send);
    };
    recorder.start();
    $("btn-mic").classList.add("recording");
  } catch { addMsg("system", "⚠ microphone permission denied"); }
}
function stopRecording() {
  if (recorder?.state === "recording") recorder.stop();
  $("btn-mic").classList.remove("recording");
}
$("btn-mic").addEventListener("mousedown", startRecording);
$("btn-mic").addEventListener("mouseup", stopRecording);
$("btn-mic").addEventListener("mouseleave", stopRecording);
$("btn-mic").addEventListener("touchstart", (e) => { e.preventDefault(); startRecording(); });
$("btn-mic").addEventListener("touchend", stopRecording);

/* ── slide-over panels ────────────────────────────────────────────── */

document.querySelectorAll(".nav-btn").forEach(b =>
  b.addEventListener("click", () => openPanel(b.dataset.panel)));
$("panel-close").onclick = () => $("panel").classList.add("hidden");

async function openPanel(kind) {
  const body = $("panel-body");
  body.innerHTML = "loading…";
  $("panel").classList.remove("hidden");
  $("panel-title").textContent = { library: "📚 Library", approvals: "✅ Approvals",
                                   tasks: "🎯 Tasks", projects: "🗂 Projects" }[kind];
  try {
    if (kind === "library") {
      const lib = await api("/api/v1/library");
      body.innerHTML = "";
      const section = (t) => { const d = document.createElement("div"); d.className = "p-section"; d.textContent = t; body.appendChild(d); };
      const item = (html) => { const d = document.createElement("div"); d.className = "p-item"; d.innerHTML = html; body.appendChild(d); };
      section(`Notes (${lib.notes.length})`);
      lib.notes.slice(0, 15).forEach(n => item(`${esc(n.name)}<div class="sub">${n.modified.slice(0, 16)}</div>`));
      section(`Documents (${lib.documents.length})`);
      lib.documents.slice(0, 15).forEach(d => item(`${esc(d.title)}<div class="sub">v${d.version} · ${d.updated_at.slice(0, 16)}</div>`));
      section(`Uploads (${lib.uploads.length})`);
      lib.uploads.slice(0, 15).forEach(u => item(esc(u)));
      section(`Generated images (${lib.images.length})`);
      lib.images.slice(0, 10).forEach(i => item(esc(i)));
      if (lib.knowledge) {
        section("Knowledge");
        item(`chunks: ${lib.knowledge.chunks ?? 0}<div class="sub">${esc(JSON.stringify(lib.knowledge.ledger || {}))}</div>`);
      }
    } else if (kind === "approvals") {
      const pending = await api("/api/v1/approvals");
      body.innerHTML = pending.length ? "" : "<div class='p-item'>Nothing waiting for approval.</div>";
      pending.forEach(a => {
        const d = document.createElement("div");
        d.className = "p-item";
        d.innerHTML = `<code>${esc(a.preview)}</code><div class="row"></div>`;
        const row = d.querySelector(".row");
        const yes = document.createElement("button"); yes.textContent = "✅ Approve";
        const no = document.createElement("button"); no.textContent = "❌ Deny";
        yes.onclick = async () => { await resolveApproval(a.id, true); openPanel("approvals"); };
        no.onclick = async () => { await resolveApproval(a.id, false); openPanel("approvals"); };
        row.append(yes, no);
        body.appendChild(d);
      });
    } else if (kind === "tasks") {
      const tasks = await api("/api/v1/tasks");
      body.innerHTML = "";
      const form = document.createElement("div");
      form.className = "p-form";
      form.innerHTML = `<textarea id="p-goal" rows="2" placeholder="Describe a goal…"></textarea>
                        <button id="p-run">Run goal</button>`;
      body.appendChild(form);
      $("p-run").onclick = () => {
        const g = $("p-goal").value.trim();
        if (!g) return;
        $("panel").classList.add("hidden");
        addMsg("user", `🎯 ${g}`);
        runGoal(g);
      };
      tasks.forEach(t => {
        const d = document.createElement("div");
        d.className = "p-item";
        d.innerHTML = `${esc(t.goal.slice(0, 90))}<div class="sub">${t.status} · ${t.created_at.slice(0, 16)}</div>`;
        body.appendChild(d);
      });
    } else if (kind === "projects") {
      const projects = await api("/api/v1/projects");
      body.innerHTML = "";
      const form = document.createElement("div");
      form.className = "p-form";
      form.innerHTML = `<input id="p-name" placeholder="Project name">
                        <textarea id="p-instr" rows="3" placeholder="Shared instructions for every chat in this project (optional)"></textarea>
                        <button id="p-create">Create / update project</button>`;
      body.appendChild(form);
      $("p-create").onclick = async () => {
        const name = $("p-name").value.trim();
        if (!name) return;
        await api("/api/v1/projects", { method: "POST",
                  json: { name, instructions: $("p-instr").value.trim() } });
        openPanel("projects");
        loadSessions();
      };
      projects.forEach(p => {
        const d = document.createElement("div");
        d.className = "p-item";
        d.innerHTML = `🗂 ${esc(p.name)} <span class="sub">(${p.chats} chats)</span>
                       ${p.instructions ? `<div class="sub">${esc(p.instructions.slice(0, 120))}</div>` : ""}
                       <div class="row"></div>`;
        const del = document.createElement("button");
        del.textContent = "Delete (chats survive)";
        del.onclick = async () => {
          await api(`/api/v1/projects/${p.id}`, { method: "DELETE" });
          openPanel("projects");
          loadSessions();
        };
        d.querySelector(".row").appendChild(del);
        body.appendChild(d);
      });
    }
  } catch (e) {
    body.innerHTML = `<div class="p-item">⚠ ${esc(e.message.slice(0, 200))}</div>`;
  }
}

/* ── boot ─────────────────────────────────────────────────────────── */

async function boot() {
  await loadSessions();
  refreshApprovals();
  if (sessions.length) await openSession(sessions[0]);
}

TOKEN ? tryConnect() : showGate();

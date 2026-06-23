"use strict";

// All the chat UI behaviour. Values from the server (name, personas) arrive
// via window.CHAT_CONFIG, set by a small inline script in index.html.
const CFG = window.CHAT_CONFIG || { displayName: null, personas: [] };

const messagesEl = document.getElementById("messages");
const threadsEl = document.getElementById("threads");
const docsEl = document.getElementById("docs");
const formEl = document.getElementById("form");
const inputEl = document.getElementById("input");
const personaEl = document.getElementById("persona");
const searchEl = document.getElementById("search");
const sendBtn = document.getElementById("send");
const stopBtn = document.getElementById("stop");
const fileEl = document.getElementById("file");

let currentThreadId = null;
let threadsCache = [];
let sending = false;
let pendingEdit = false;       // next submit replaces the last turn
let abortController = null;
let ttsOn = localStorage.getItem("tts") === "on";
let avatarGender = localStorage.getItem("avatarGender") || "off"; // off | male | female

// ---- helpers ----
// Rendering lives in the shared, reusable Render module (static/render.js),
// so the chat page and the memory page format text identically.
const renderMarkdown = (text) => Render.markdown(text);
const renderRich = (el, text) => Render.rich(el, text);

function fmtTime(created) {
  // `created` is a UTC string from the DB, undefined for a brand-new message,
  // or false to mean "no timestamp" (e.g. the greeting bubble).
  if (created === false) return "";
  try {
    const d = created ? new Date(created.replace(" ", "T") + "Z") : new Date();
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch (e) {
    return "";
  }
}

function greetingText() {
  return CFG.displayName
    ? `Welcome back, ${CFG.displayName}! What's on your mind?`
    : "Hi! I'm your new friend. Tell me what's on your mind, I'm here to listen.";
}

// A "turn" wraps one bubble plus its little action row (copy/edit/regenerate
// and a timestamp). `created` may be a DB string, undefined (= now), or false.
function addTurn(text, who, created) {
  const turn = document.createElement("div");
  turn.className = "turn turn--" + who;
  turn.dataset.time = fmtTime(created);

  const bubble = document.createElement("div");
  bubble.className = "msg msg--" + who;
  if (who === "bot") renderRich(bubble, text);
  else bubble.textContent = text;
  bubble.dataset.raw = text;
  turn.appendChild(bubble);

  const actions = document.createElement("div");
  actions.className = "actions";
  turn.appendChild(actions);

  messagesEl.appendChild(turn);
  scrollToBottom();
  return { turn, bubble, actions };
}

function actionButton(label, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

// Decide which buttons each turn shows. Copy on every bot bubble; Edit on the
// LAST user bubble; Regenerate on the LAST bot bubble.
function refreshActions() {
  const turns = [...messagesEl.querySelectorAll(".turn")];
  const lastUser = [...turns].reverse().find((t) => t.classList.contains("turn--user"));
  const lastBot = [...turns].reverse().find((t) => t.classList.contains("turn--bot"));

  turns.forEach((turn) => {
    const actions = turn.querySelector(".actions");
    const bubble = turn.querySelector(".msg");
    actions.innerHTML = "";
    if (turn.classList.contains("turn--bot")) {
      actions.appendChild(actionButton("Copy", () => {
        navigator.clipboard.writeText(bubble.dataset.raw || "");
      }));
      if (turn === lastBot && !sending) {
        actions.appendChild(actionButton("Regenerate", regenerate));
      }
    } else if (turn === lastUser && !sending) {
      actions.appendChild(actionButton("Edit", () => {
        inputEl.value = bubble.dataset.raw || "";
        autosize();
        pendingEdit = true;
        inputEl.focus();
      }));
    }
    if (turn.dataset.time) {
      const t = document.createElement("span");
      t.className = "time";
      t.textContent = turn.dataset.time;
      actions.appendChild(t);
    }
  });
}

// ---- scrolling ----
function nearBottom() {
  return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
}
function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}
function updateScrollBtn() {
  document.getElementById("scrolldown").classList.toggle("show", !nearBottom());
}
messagesEl.addEventListener("scroll", updateScrollBtn);
document.getElementById("scrolldown").addEventListener("click", () => {
  scrollToBottom();
  updateScrollBtn();
});

// ---- textarea: Enter sends, Shift+Enter newlines, auto-grow ----
function autosize() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + "px";
}
inputEl.addEventListener("input", autosize);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    formEl.requestSubmit();
  }
});

// Turn markdown into something natural to READ ALOUD: drop code blocks, strip
// markdown markers (so it doesn't say "asterisk asterisk"), unwrap links.
function speakableText(text) {
  return (text || "")
    .replace(/```[\s\S]*?```/g, " ")           // fenced code blocks
    .replace(/`[^`]*`/g, " ")                   // inline code
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")      // images
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")    // links -> link text
    .replace(/https?:\/\/\S+/g, " ")            // bare URLs
    .replace(/^\s{0,3}#{1,6}\s*/gm, "")          // heading hashes
    .replace(/^\s*[-*+]\s+/gm, "")               // list bullets
    .replace(/[*_~`#>|]/g, " ")                  // leftover md markers
    .replace(/\s+/g, " ")
    .trim();
}

// Guess the language from the text so the synthesizer pronounces it correctly.
// Non-Latin scripts are detected by their Unicode ranges; a few Latin
// languages by tell-tale words.
const LANG_REGION = {
  en: "en-US", ja: "ja-JP", ko: "ko-KR", zh: "zh-CN", fr: "fr-FR", es: "es-ES",
  de: "de-DE", it: "it-IT", pt: "pt-PT", ru: "ru-RU", ar: "ar-SA", hi: "hi-IN",
  he: "he-IL", th: "th-TH", el: "el-GR",
};
function detectLang(t) {
  if (/[\u3040-\u30ff]/.test(t)) return "ja";
  if (/[\uac00-\ud7af]/.test(t)) return "ko";
  if (/[\u4e00-\u9fff]/.test(t)) return "zh";
  if (/[\u0600-\u06ff]/.test(t)) return "ar";
  if (/[\u0400-\u04ff]/.test(t)) return "ru";
  if (/[\u0900-\u097f]/.test(t)) return "hi";
  if (/[\u0590-\u05ff]/.test(t)) return "he";
  if (/[\u0e00-\u0e7f]/.test(t)) return "th";
  if (/[\u0370-\u03ff]/.test(t)) return "el";
  const s = " " + t.toLowerCase() + " ";
  if (/\b(bonjour|merci|bonsoir|salut|c'est|je suis|vous|une|oui|s'il)\b/.test(s)) return "fr";
  if (/\b(hola|gracias|buenos|cómo|qué|usted|por favor|adiós)\b/.test(s)) return "es";
  if (/\b(hallo|danke|guten|ich|und|nicht|bitte|tschüss)\b/.test(s)) return "de";
  if (/\b(ciao|grazie|buongiorno|sono|prego)\b/.test(s)) return "it";
  if (/\b(olá|obrigado|bom dia|você)\b/.test(s)) return "pt";
  return "en";
}

// Pick a voice that matches the language first, then the chosen gender.
function pickVoice(gender, lang) {
  const voices = (window.speechSynthesis && window.speechSynthesis.getVoices()) || [];
  const female = /female|woman|samantha|victoria|zira|tessa|fiona|karen|moira|serena|susan|allison|ava|amelie|google.*female/i;
  const male = /\bmale\b|\bman\b|daniel|alex|david|fred|rishi|aaron|oliver|thomas|jorge|google.*male/i;
  const want = gender === "female" ? female : male;
  const inLang = voices.filter((v) => v.lang && v.lang.toLowerCase().startsWith(lang));
  const pool = inLang.length ? inLang : voices;
  return pool.find((v) => want.test(v.name)) || inLang[0] || null;
}

function speak(text) {
  if (!ttsOn || !window.speechSynthesis) return;
  const clean = speakableText(text);
  if (!clean) return;
  window.speechSynthesis.cancel();
  const lang = detectLang(clean);
  const u = new SpeechSynthesisUtterance(clean);
  u.lang = LANG_REGION[lang] || "en-US";
  if (avatarGender !== "off") {
    const v = pickVoice(avatarGender, lang);
    if (v) u.voice = v;
    u.pitch = avatarGender === "female" ? 1.2 : 0.8;
  }
  const face = document.getElementById("avatarFace");
  u.onstart = () => face.classList.add("talking");
  u.onend = () => face.classList.remove("talking");
  u.onerror = () => face.classList.remove("talking");
  window.speechSynthesis.speak(u);
}

// Friendly SVG faces. The .mouth element is what the CSS animates while the
// avatar is "talking"; .eye elements blink via CSS.
function faceSvg(gender) {
  if (gender === "female") {
    return (
      '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">' +
      '<defs><radialGradient id="skinF" cx="50%" cy="42%" r="60%">' +
      '<stop offset="0%" stop-color="#fbe6cc"/><stop offset="100%" stop-color="#f1cda3"/>' +
      "</radialGradient></defs>" +
      '<path d="M11 32 Q11 9 32 9 Q53 9 53 32 L53 52 Q53 57 47 57 L17 57 Q11 57 11 52 Z" fill="#7a4a2b"/>' +
      '<path d="M11 34 Q9 44 13 54 L20 54 Q15 44 16 34 Z" fill="#6b3f23"/>' +
      '<path d="M53 34 Q55 44 51 54 L44 54 Q49 44 48 34 Z" fill="#6b3f23"/>' +
      '<ellipse cx="32" cy="34" rx="16" ry="18" fill="url(#skinF)"/>' +
      '<path d="M16 30 Q17 14 32 13 Q47 14 48 30 Q42 23 32 23 Q22 23 16 30 Z" fill="#854f2c"/>' +
      '<ellipse class="eye" cx="25" cy="34" rx="2.4" ry="3.1" fill="#4a2f1c"/>' +
      '<ellipse class="eye" cx="39" cy="34" rx="2.4" ry="3.1" fill="#4a2f1c"/>' +
      '<circle cx="21" cy="40" r="3" fill="#ef9a9a" opacity="0.55"/>' +
      '<circle cx="43" cy="40" r="3" fill="#ef9a9a" opacity="0.55"/>' +
      '<ellipse class="mouth" cx="32" cy="45" rx="4.2" ry="2.6" fill="#c2453f"/>' +
      "</svg>"
    );
  }
  return (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">' +
    '<defs><radialGradient id="skinM" cx="50%" cy="42%" r="60%">' +
    '<stop offset="0%" stop-color="#f3d4ab"/><stop offset="100%" stop-color="#e3b483"/>' +
    "</radialGradient></defs>" +
    '<ellipse cx="32" cy="36" rx="16" ry="17" fill="url(#skinM)"/>' +
    '<path d="M15 31 Q15 12 32 12 Q49 12 49 31 Q46 21 38 20 Q34 25 26 20 Q18 21 15 31 Z" fill="#4a3120"/>' +
    '<rect x="21" y="30" width="7" height="2.2" rx="1.1" fill="#4a3120"/>' +
    '<rect x="36" y="30" width="7" height="2.2" rx="1.1" fill="#4a3120"/>' +
    '<circle class="eye" cx="25" cy="35" r="2.4" fill="#4a2f1c"/>' +
    '<circle class="eye" cx="39" cy="35" r="2.4" fill="#4a2f1c"/>' +
    '<ellipse class="mouth" cx="32" cy="46" rx="4.2" ry="2.3" fill="#9c4a3a"/>' +
    "</svg>"
  );
}

function reflectAvatar() {
  const face = document.getElementById("avatarFace");
  if (avatarGender === "off") {
    face.classList.remove("show");
    face.innerHTML = "";
  } else {
    face.innerHTML = faceSvg(avatarGender);
    face.classList.add("show");
  }
}

// ---- threads ----
async function loadThreads() {
  const res = await fetch("/threads");
  threadsCache = await res.json();
  renderThreads(threadsCache);
  return threadsCache;
}

function renderThreads(threads) {
  threadsEl.innerHTML = "";
  threads.forEach((t) => {
    const row = document.createElement("div");
    row.className = "thread" + (t.id === currentThreadId ? " active" : "");
    row.dataset.id = t.id;

    const title = document.createElement("span");
    title.className = "thread__title";
    title.textContent = t.title || "New chat";
    title.title = "Double-click to rename";
    title.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      const next = prompt("Rename conversation:", t.title || "");
      if (next && next.trim()) renameThread(t.id, next.trim());
    });
    row.appendChild(title);

    const del = document.createElement("button");
    del.className = "thread__del";
    del.innerHTML = "&times;";
    del.title = "Delete conversation";
    del.addEventListener("click", (e) => { e.stopPropagation(); deleteThread(t.id); });
    row.appendChild(del);

    row.addEventListener("click", () => selectThread(t.id));
    threadsEl.appendChild(row);
  });
}

async function selectThread(id) {
  currentThreadId = id;
  pendingEdit = false;
  [...threadsEl.children].forEach((row) =>
    row.classList.toggle("active", Number(row.dataset.id) === id)
  );

  const meta = threadsCache.find((t) => t.id === id);
  if (meta) personaEl.value = meta.persona || "friend";

  messagesEl.innerHTML = '<div class="loading">Loading…</div>';
  const msgs = await (await fetch(`/threads/${id}/messages`)).json();
  messagesEl.innerHTML = "";
  if (!msgs.length) {
    addTurn(greetingText(), "bot", false);
  } else {
    msgs.forEach((m) => { addTurn(m.you, "user", m.created); addTurn(m.bot, "bot", m.created); });
  }
  refreshActions();
  loadDocs(id);
  scrollToBottom();
  updateScrollBtn();
  inputEl.focus();
}

async function newThread() {
  const t = await (await fetch("/threads", { method: "POST" })).json();
  await loadThreads();
  await selectThread(t.id);
}

async function deleteThread(id) {
  if (!confirm("Delete this conversation?")) return;
  await fetch(`/threads/${id}/delete`, { method: "POST" });
  const threads = await loadThreads();
  if (id === currentThreadId && threads.length) await selectThread(threads[0].id);
}

async function renameThread(id, title) {
  await fetch(`/threads/${id}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  await loadThreads();
  [...threadsEl.children].forEach((row) =>
    row.classList.toggle("active", Number(row.dataset.id) === currentThreadId)
  );
}

// ---- documents ----
async function loadDocs(id) {
  const docs = await (await fetch(`/threads/${id}/documents`)).json();
  docsEl.innerHTML = "";
  if (!docs.length) { docsEl.classList.add("hidden"); return; }
  docsEl.classList.remove("hidden");
  docs.forEach((d) => {
    const chip = document.createElement("span");
    chip.className = "docchip";
    chip.textContent = `\uD83D\uDCC4 ${d.filename}`;
    docsEl.appendChild(chip);
  });
}

// ---- sending / streaming ----
function setSending(on) {
  sending = on;
  sendBtn.classList.toggle("hidden", on);
  stopBtn.classList.toggle("hidden", !on);
  refreshActions();
}

async function doSend(text, opts = {}) {
  if (sending || !currentThreadId) return;
  setSending(true);

  if (opts.regenerate) {
    // Remove the last bot turn; we'll restream into a fresh one.
    const turns = [...messagesEl.querySelectorAll(".turn--bot")];
    if (turns.length) turns[turns.length - 1].remove();
  } else {
    addTurn(text, "user");
  }

  const { bubble } = addTurn("", "bot");
  bubble.innerHTML = '<span class="typing-dots"><span>.</span><span>.</span><span>.</span></span>';
  let raw = "";
  let firstChunk = true;

  abortController = new AbortController();
  try {
    const response = await fetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        thread_id: currentThreadId,
        regenerate: !!opts.regenerate,
        edit: !!opts.edit,
      }),
      signal: abortController.signal,
    });

    if (response.status === 429 || response.status === 404 || response.status === 400) {
      bubble.textContent = await response.text();
      setSending(false);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (firstChunk) { raw = ""; firstChunk = false; }
      const stick = nearBottom();
      raw += decoder.decode(value, { stream: true });
      bubble.innerHTML = renderMarkdown(raw);
      bubble.dataset.raw = raw;
      if (stick) scrollToBottom();
    }
    renderRich(bubble, raw); // final pass: math + code highlighting
    updateScrollBtn();
    speak(raw);
  } catch (err) {
    if (err.name === "AbortError") {
      bubble.dataset.raw = raw;
      if (!raw) bubble.textContent = "(stopped)";
    } else {
      bubble.textContent = "Oops, I couldn't reach the server.";
    }
  } finally {
    abortController = null;
    setSending(false);
    loadThreads().then(() => {
      [...threadsEl.children].forEach((row) =>
        row.classList.toggle("active", Number(row.dataset.id) === currentThreadId)
      );
    });
  }
}

function regenerate() {
  doSend("", { regenerate: true });
}

formEl.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = inputEl.value.trim();
  if (text === "") return;
  inputEl.value = "";
  autosize();
  const editing = pendingEdit;
  pendingEdit = false;
  if (editing) {
    // Drop the old last turn from the screen, then send as an edit.
    const turns = [...messagesEl.querySelectorAll(".turn")];
    if (turns.length >= 2) { turns[turns.length - 1].remove(); turns[turns.length - 2].remove(); }
    addTurn(text, "user");
    doSend(text, { edit: true });
  } else {
    doSend(text);
  }
});

stopBtn.addEventListener("click", () => { if (abortController) abortController.abort(); });
document.getElementById("newChat").addEventListener("click", newThread);

// ---- persona ----
personaEl.addEventListener("change", async () => {
  if (!currentThreadId) return;
  await fetch(`/threads/${currentThreadId}/persona`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ persona: personaEl.value }),
  });
  const meta = threadsCache.find((t) => t.id === currentThreadId);
  if (meta) meta.persona = personaEl.value;
});

// ---- theme ----
document.getElementById("theme").addEventListener("click", async () => {
  const next = document.body.dataset.theme === "dark" ? "light" : "dark";
  document.body.dataset.theme = next;
  await fetch("/theme", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ theme: next }),
  });
});

// ---- export ----
document.getElementById("export").addEventListener("click", () => {
  if (!currentThreadId) return;
  const fmt = confirm("OK = Markdown, Cancel = JSON") ? "md" : "json";
  window.location = `/threads/${currentThreadId}/export?format=${fmt}`;
});

// ---- search ----
let searchTimer = null;
searchEl.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = searchEl.value.trim();
  if (!q) { renderThreads(threadsCache); return; }
  searchTimer = setTimeout(async () => {
    const results = await (await fetch("/search?q=" + encodeURIComponent(q))).json();
    threadsEl.innerHTML = "";
    if (!results.length) {
      const none = document.createElement("div");
      none.className = "result";
      none.textContent = "No matches.";
      threadsEl.appendChild(none);
      return;
    }
    results.forEach((r) => {
      const row = document.createElement("div");
      row.className = "result";
      row.innerHTML = `<small>${r.title || "chat"}</small>${r.you}`;
      row.addEventListener("click", () => { searchEl.value = ""; renderThreads(threadsCache); selectThread(r.thread_id); });
      threadsEl.appendChild(row);
    });
  }, 250);
});

// ---- upload ----
document.getElementById("attach").addEventListener("click", () => fileEl.click());
fileEl.addEventListener("change", async () => {
  const file = fileEl.files[0];
  if (!file || !currentThreadId) return;
  const note = addTurn(`Uploading **${file.name}**...`, "bot");
  const data = new FormData();
  data.append("file", file);
  fileEl.value = "";
  try {
    const res = await fetch(`/threads/${currentThreadId}/upload`, { method: "POST", body: data });
    const out = await res.json();
    if (res.ok) {
      note.bubble.innerHTML = renderMarkdown(`Got **${out.filename}** (${out.chunks} chunks). Ask me about it!`);
    } else {
      note.bubble.textContent = out.error || "Upload failed.";
    }
  } catch (err) {
    note.bubble.textContent = "Upload failed.";
  }
  loadDocs(currentThreadId);
});

// ---- voice ----
const micBtn = document.getElementById("mic");
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SR) {
  const recog = new SR();
  recog.lang = "en-US";
  recog.interimResults = false;
  let listening = false;
  micBtn.addEventListener("click", () => {
    if (listening) { recog.stop(); return; }
    recog.start(); listening = true; micBtn.classList.remove("off");
  });
  recog.onresult = (e) => { inputEl.value = e.results[0][0].transcript; };
  recog.onend = () => { listening = false; micBtn.classList.add("off"); };
} else {
  micBtn.classList.add("hidden");
}

const speakBtn = document.getElementById("speak");
function reflectTts() { speakBtn.classList.toggle("off", !ttsOn); }
reflectTts();
speakBtn.addEventListener("click", () => {
  ttsOn = !ttsOn;
  localStorage.setItem("tts", ttsOn ? "on" : "off");
  if (!ttsOn && window.speechSynthesis) window.speechSynthesis.cancel();
  reflectTts();
});

// ---- talking avatar + voice gender ----
const voiceSel = document.getElementById("voiceSel");
voiceSel.value = avatarGender;
reflectAvatar();
// Voices load asynchronously in some browsers; refresh once they arrive.
if (window.speechSynthesis) window.speechSynthesis.onvoiceschanged = () => {};
voiceSel.addEventListener("change", () => {
  avatarGender = voiceSel.value;
  localStorage.setItem("avatarGender", avatarGender);
  reflectAvatar();
  // Picking a voice should actually talk: turn TTS on. "No avatar" mutes it.
  ttsOn = avatarGender !== "off";
  localStorage.setItem("tts", ttsOn ? "on" : "off");
  reflectTts();
  if (!ttsOn && window.speechSynthesis) window.speechSynthesis.cancel();
});

// ---- clear name only ----
document.getElementById("clearName").addEventListener("click", async () => {
  if (!confirm("Forget just my name? (Your chats and memories stay.)")) return;
  try { await fetch("/name/clear", { method: "POST" }); } catch (err) {}
  alert("Done -- I've cleared your name. Tell me a new one anytime with \"my name is ...\".");
});

// ---- forget me ----
document.getElementById("reset").addEventListener("click", async () => {
  if (!confirm("Forget your name, all chats, and everything I remember about you?")) return;
  try { await fetch("/reset", { method: "POST" }); } catch (err) {}
  currentThreadId = null;
  const threads = await loadThreads();
  if (threads.length) await selectThread(threads[0].id);
});

// ---- boot ----
window.addEventListener("load", async () => {
  const threads = await loadThreads();
  if (threads.length) await selectThread(threads[0].id);
});

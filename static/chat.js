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

// ---- helpers ----
function renderMarkdown(text) {
  return DOMPurify.sanitize(marked.parse(text || ""));
}

// Full "rich" render for a finished bot message: markdown + LaTeX math
// (KaTeX) + code syntax highlighting (highlight.js). We do the heavier math
// and highlighting passes once a message is complete (or when loading old
// ones), since they don't like half-finished input mid-stream.
function renderRich(bubble, text) {
  bubble.dataset.raw = text;

  // Markdown would mangle LaTeX delimiters (\( becomes (, etc.), so pull the
  // math out first, run markdown, then put the math back untouched for KaTeX.
  const math = [];
  const stash = (m) => { math.push(m); return `@@MATH${math.length - 1}@@`; };
  let protectedText = text
    .replace(/\\\[[\s\S]*?\\\]/g, stash)
    .replace(/\$\$[\s\S]*?\$\$/g, stash)
    .replace(/\\\([\s\S]*?\\\)/g, stash);

  let html = renderMarkdown(protectedText);
  html = html.replace(/@@MATH(\d+)@@/g, (_, i) => math[i]);
  bubble.innerHTML = html;

  if (window.renderMathInElement) {
    try {
      window.renderMathInElement(bubble, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "\\[", right: "\\]", display: true },
          { left: "\\(", right: "\\)", display: false },
        ],
        throwOnError: false,
      });
    } catch (e) { /* leave raw math if KaTeX trips */ }
  }
  if (window.hljs) {
    bubble.querySelectorAll("pre code").forEach((el) => window.hljs.highlightElement(el));
  }
}

function greetingText() {
  return CFG.displayName
    ? `Welcome back, ${CFG.displayName}! What's on your mind?`
    : "Hi! I'm your new friend. Tell me what's on your mind, I'm here to listen.";
}

// A "turn" wraps one bubble plus its little action row (copy/edit/regenerate).
function addTurn(text, who) {
  const turn = document.createElement("div");
  turn.className = "turn turn--" + who;

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
  messagesEl.scrollTop = messagesEl.scrollHeight;
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
        pendingEdit = true;
        inputEl.focus();
      }));
    }
  });
}

function speak(text) {
  if (!ttsOn || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
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

  const msgs = await (await fetch(`/threads/${id}/messages`)).json();
  messagesEl.innerHTML = "";
  if (!msgs.length) {
    addTurn(greetingText(), "bot");
  } else {
    msgs.forEach((m) => { addTurn(m.you, "user"); addTurn(m.bot, "bot"); });
  }
  refreshActions();
  loadDocs(id);
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
      raw += decoder.decode(value, { stream: true });
      bubble.innerHTML = renderMarkdown(raw);
      bubble.dataset.raw = raw;
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
    renderRich(bubble, raw); // final pass: math + code highlighting
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

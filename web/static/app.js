import * as pdfjs from "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.4.168/build/pdf.min.mjs";
import { initTheme, checkStatus } from "/static/common.js";
import { setPip } from "/static/mascot.js";

pdfjs.GlobalWorkerOptions.workerSrc = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.4.168/build/pdf.worker.min.mjs";

const SAMPLES = ["laptop_alpha.pdf", "laptop_beta.pdf", "laptop_gamma.pdf"];
const OVERVIEW_LABEL = "Quick overview";
const MAX = 3, CTX_TOKENS = 32768, ANSWER_BUDGET = 1500, PROMPT_OVERHEAD = 450, TICKS = 30;

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const docs = [];        // {id, name, pages, words, chars, status: busy|ok|bad, error}
const history = [];     // {id, question, status: run|ok|err, seconds, card, text}
let running = false;
const pip = $("#pip");

/* ---------- small helpers ---------- */
function toast(msg) {
  $(".toast")?.remove();
  const t = Object.assign(document.createElement("div"), { className: "toast", textContent: msg, role: "status" });
  document.body.append(t);
  setTimeout(() => t.remove(), 1900);
}
function notice(msg) { const n = $("#notice"); n.textContent = msg || ""; n.hidden = !msg; }
const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function greet() {
  const h = new Date().getHours();
  $("#greet").textContent = h < 12 ? "Good morning!" : h < 17 ? "Good afternoon!" : "Good evening!";
}

/* ---------- documents ---------- */
async function readPdf(buffer) {
  const pdf = await pdfjs.getDocument({ data: buffer }).promise;
  const pages = [];
  for (let i = 1; i <= Math.min(pdf.numPages, 300); i++) {
    const c = await (await pdf.getPage(i)).getTextContent();
    pages.push(c.items.map((it) => it.str + (it.hasEOL ? "\n" : " ")).join("").replace(/[ \t]+/g, " ").trim());
  }
  return pages;
}

async function addFile(name, buffer) {
  if (docs.length >= MAX) return toast(`Up to ${MAX} PDFs at a time`);
  if (docs.some((d) => d.name === name)) return toast(`${name} is already added`);
  const doc = { id: crypto.randomUUID(), name, pages: [], words: 0, chars: 0, status: "busy" };
  docs.push(doc);
  renderDocs();
  try {
    doc.pages = await readPdf(buffer);
    const all = doc.pages.join(" ");
    doc.chars = all.length;
    doc.words = all.split(/\s+/).filter(Boolean).length;
    if (!doc.words) throw new Error("No text found (scanned PDF?)");
    doc.status = "ok";
  } catch (e) {
    doc.status = "bad";
    doc.error = /password/i.test(`${e?.name} ${e?.message}`) ? "Password protected" : (e?.message || "Could not read this PDF");
  }
  renderDocs();
}

function handleFiles(list) {
  for (const f of [...list]) {
    if (f.type !== "application/pdf" && !/\.pdf$/i.test(f.name)) { toast(`${f.name} is not a PDF`); continue; }
    f.arrayBuffer().then((b) => addFile(f.name, b));
  }
}

async function loadSamples() {
  const missing = SAMPLES.filter((n) => !docs.some((d) => d.name === n));
  if (docs.length + missing.length > MAX) docs.splice(0, docs.length);
  for (const n of SAMPLES) {
    if (docs.some((d) => d.name === n)) continue;
    const r = await fetch(`/samples/${n}`);
    if (r.ok) addFile(n, await r.arrayBuffer());
  }
  closeSide();
  $("#question").focus();
}

function removeDoc(id) {
  const i = docs.findIndex((d) => d.id === id);
  if (i >= 0) docs.splice(i, 1);
  renderDocs();
}

function infoText(d) {
  if (d.status === "bad") return d.error;
  if (d.status === "busy") return "";
  return `${d.pages.length} ${d.pages.length === 1 ? "page" : "pages"} · ${d.words.toLocaleString()} words`;
}

function renderDocs() {
  // chips inside the composer
  $("#attached").innerHTML = docs.map((d) => `
    <span class="att ${d.status}" data-id="${d.id}">
      <span class="pdf">PDF</span><span class="nm">${esc(d.name)}</span><small>${esc(infoText(d))}</small>
      <button type="button" aria-label="Remove ${esc(d.name)}">×</button>
    </span>`).join("");
  // list in the right rail
  $("#doc-list").innerHTML = docs.map((d) => `
    <li class="doc" data-id="${d.id}">
      <span class="pdf">PDF</span>
      <span class="info"><span class="nm">${esc(d.name)}</span><small>${d.status === "busy" ? "Reading…" : esc(infoText(d))}</small></span>
      <span class="st ${d.status}" title="${d.status === "ok" ? "Ready" : d.status === "busy" ? "Reading" : "Problem"}"></span>
      <button type="button" aria-label="Remove ${esc(d.name)}">×</button>
    </li>`).join("");
  $("#doc-empty").hidden = docs.length > 0;
  $$("#attached .att button, #doc-list .doc button").forEach((b) =>
    b.addEventListener("click", () => removeDoc(b.closest("[data-id]").dataset.id)));
  updateHint();
  updateContext();
}

function updateHint() {
  const ready = docs.filter((d) => d.status === "ok").length;
  const busy = docs.some((d) => d.status === "busy");
  $("#hint").textContent = busy ? "Reading PDFs…" : ready < 2 ? `Add ${2 - ready} more PDF${ready === 1 ? "" : "s"}` : "Ctrl + Enter to compare";
  $("#send").disabled = running;
}

function updateContext() {
  const k = +$("#k").value;
  const ready = docs.filter((d) => d.status === "ok");
  const meter = $("#ctx-meter");
  let pct = 0, label = "No documents yet";
  if (ready.length) {
    const chars = ready.reduce((s, d) => s + Math.min(d.chars, k * 1000), 0);
    const tokens = Math.round(chars / 4 + PROMPT_OVERHEAD + ANSWER_BUDGET);
    pct = Math.min(100, Math.round((tokens / CTX_TOKENS) * 100));
    label = `~${tokens.toLocaleString()} of 32K tokens`;
  }
  $("#ctx-label").textContent = label;
  $("#ctx-pct").textContent = `${pct}%`;
  const on = Math.max(pct ? 1 : 0, Math.round((TICKS * pct) / 100));
  meter.innerHTML = Array.from({ length: TICKS }, (_, i) => `<i class="${i < on ? "on" : ""}${i === on - 1 ? " last" : ""}"></i>`).join("");
}

/* ---------- asking ---------- */
function setRunning(on) {
  running = on;
  $("#send").disabled = on;
  $("#send").classList.toggle("busy", on);
  setPip(pip, on ? "think" : "idle");
}

async function ask({ overview = false, question = $("#question").value.trim() } = {}) {
  if (running) return;
  const ready = docs.filter((d) => d.status === "ok");
  if (docs.some((d) => d.status === "busy")) return notice("Still reading the PDFs, one moment.");
  if (ready.length < 2) { notice("Add at least 2 readable PDFs to compare."); setPip(pip, "sad"); setTimeout(() => setPip(pip, "idle"), 1800); return; }
  if (!overview && !question) { $("#question").focus(); return notice("Type a question first."); }
  notice("");
  setRunning(true);
  $("#center").classList.add("compact");
  $("#sub").textContent = "Reading every document and comparing…";

  const card = $("#result-tpl").content.firstElementChild.cloneNode(true);
  $(".q", card).textContent = overview ? OVERVIEW_LABEL : question;
  $(".meta", card).textContent = ready.map((d) => d.name).join(" · ");
  $("#results").prepend(card);
  const item = { id: crypto.randomUUID(), question: overview ? OVERVIEW_LABEL : question, status: "run", card, text: "" };
  history.unshift(item);
  card.id = "r-" + item.id;
  renderRecent();
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });

  const answerEl = $(".answer", card);
  let text = "", sources = {}, frame = 0;
  const started = performance.now();
  const paint = (final) => { answerEl.classList.toggle("caret", !final); answerEl.innerHTML = renderMarkdown(text); };

  try {
    const res = await fetch("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ docs: ready.map(({ name, pages }) => ({ name, pages })), question, overview, k: +$("#k").value }),
    });
    if (!res.ok || !res.body) {
      let msg = `Request failed (HTTP ${res.status}).`;
      try { msg = (await res.json()).message || msg; } catch {}
      throw new Error(msg);
    }
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += value;
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.type === "meta") sources = ev.sources;
        else if (ev.type === "token") {
          text += ev.t;
          if (!frame) frame = requestAnimationFrame(() => { frame = 0; paint(false); });
        } else if (ev.type === "error") throw new Error(ev.message);
      }
    }
    if (!text.trim()) throw new Error("The model returned an empty answer.");
    cancelAnimationFrame(frame);
    paint(true);
    item.seconds = ((performance.now() - started) / 1000).toFixed(1);
    item.status = "ok";
    item.text = text;
    $(".meta", card).textContent += ` · Qwen 2.5 14B · ${item.seconds}s`;
    wireTools(card, text, sources);
    setRunning(false);
    setPip(pip, "happy");
    setTimeout(() => setPip(pip, "idle"), 1600);
    $("#sub").textContent = "Done! Ask a follow-up or try another comparison.";
  } catch (e) {
    cancelAnimationFrame(frame);
    item.status = "err";
    card.classList.add("error");
    answerEl.classList.remove("caret");
    answerEl.textContent = e.message || "Something went wrong.";
    setRunning(false);
    setPip(pip, "sad");
    setTimeout(() => setPip(pip, "idle"), 2500);
    $("#sub").textContent = "That didn't work. The message below says why.";
  }
  renderRecent();
  checkStatus($("#status"));
}

/* ---------- rendering ---------- */
function renderMarkdown(md) {
  const tpl = document.createElement("template");
  tpl.innerHTML = DOMPurify.sanitize(marked.parse(md, { gfm: true, breaks: false }));
  tpl.content.querySelectorAll("table").forEach((t) => {
    const wrap = Object.assign(document.createElement("div"), { className: "table-wrap" });
    t.replaceWith(wrap);
    wrap.append(t);
  });
  tpl.content.querySelectorAll("td").forEach((td) => {
    if (/^not mentioned\.?$/i.test(td.textContent.trim())) td.classList.add("nm");
  });
  return tpl.innerHTML;
}

function tableToCsv(md) {
  const rows = [];
  let started = false;
  for (const raw of md.split("\n")) {
    const line = raw.trim();
    if (line.startsWith("|") && line.endsWith("|")) {
      started = true;
      const cells = line.slice(1, -1).split("|").map((c) => c.trim());
      if (cells.every((c) => !c || /^:?-{2,}:?$/.test(c))) continue;
      rows.push(cells);
    } else if (started) break;
  }
  if (rows.length < 2) return null;
  return rows.map((r) => r.map((c) => `"${c.replace(/\*\*/g, "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
}

function download(name, content, type) {
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([content], { type })), download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function wireTools(card, text, sources) {
  const foot = $(".result-foot", card);
  foot.hidden = false;
  const csv = tableToCsv(text);
  if (!csv) $('[data-act="csv"]', card).remove();
  foot.addEventListener("click", async (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "copy") { await navigator.clipboard.writeText(text); toast("Copied to clipboard"); }
    if (act === "md") download("comparison.md", text, "text/markdown");
    if (act === "csv") download("comparison.csv", "﻿" + csv, "text/csv");
  });
  const list = $(".src-list", card);
  for (const [name, hits] of Object.entries(sources)) {
    const div = Object.assign(document.createElement("div"), { className: "src-doc" });
    div.append(Object.assign(document.createElement("h4"), { textContent: name }));
    for (const hit of hits) {
      const q = document.createElement("blockquote");
      q.append(Object.assign(document.createElement("cite"), { textContent: `Page ${hit.page}` }),
        hit.text.length > 600 ? hit.text.slice(0, 600) + "…" : hit.text);
      div.append(q);
    }
    list.append(div);
  }
}

function renderRecent() {
  const ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="M3.5 10h17M9.5 10v9"/></svg>';
  $("#recent").innerHTML = history.slice(0, 6).map((h) => `
    <li><button type="button" data-id="${h.id}">
      <span class="r-ic">${ICON}</span>
      <span class="r-t"><b>${esc(h.question)}</b><small>${h.status === "run" ? "Answering…" : h.status === "err" ? "Failed" : `${h.seconds}s · table ready`}</small></span>
      <span class="r-dot ${h.status === "run" ? "run" : h.status === "err" ? "err" : ""}"></span>
    </button></li>`).join("");
  $$("#recent button").forEach((b) => b.addEventListener("click", () => {
    const h = history.find((x) => x.id === b.dataset.id);
    h?.card.scrollIntoView({ behavior: "smooth", block: "start" });
    closeSide();
  }));
  const n = history.length;
  $("#recent-empty").hidden = n > 0;
  $("#recent-count").textContent = n;
  $("#hist-count").textContent = n;
  $("#hist-count").hidden = n === 0;
}

/* ---------- navigation & chrome ---------- */
function openSide() { $("#side").classList.add("open"); $("#scrim").hidden = false; }
function closeSide() { $("#side").classList.remove("open"); $("#scrim").hidden = true; }

function selectTab(name) {
  $$(".tabs [data-tab]").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
  $$("[data-body]").forEach((b) => { b.hidden = b.dataset.body !== name; });
}

function exportLast() {
  const last = history.find((h) => h.status === "ok");
  const csv = last && tableToCsv(last.text);
  if (!csv) return toast("No comparison table to export yet");
  download("comparison.csv", "﻿" + csv, "text/csv");
}

function clearAll() {
  history.splice(0, history.length);
  $("#results").innerHTML = "";
  $("#center").classList.remove("compact");
  greet();
  $("#sub").textContent = "Which documents should we compare today?";
  renderRecent();
}

const actions = {
  samples: loadSamples,
  overview: () => ask({ overview: true }),
  settings: () => { selectTab("settings"); $("#rail").scrollIntoView({ behavior: "smooth" }); closeSide(); },
  history: () => { $("#history").scrollIntoView({ behavior: "smooth" }); closeSide(); },
  export: exportLast,
  clear: clearAll,
};

function init() {
  initTheme();
  greet();
  renderDocs();
  renderRecent();
  checkStatus($("#status"));
  setInterval(() => checkStatus($("#status")), 60000);

  $$("[data-nav]").forEach((b) => b.addEventListener("click", (e) => {
    const fn = actions[b.dataset.nav];
    if (fn) { e.preventDefault(); $("#menu").hidden = true; fn(); }
  }));
  $$(".tabs [data-tab]").forEach((t) => t.addEventListener("click", () => selectTab(t.dataset.tab)));
  $$(".idea").forEach((b) => b.addEventListener("click", () => { $("#question").value = b.dataset.q; autoGrow(); $("#question").focus(); }));

  const file = $("#file");
  [$("#add-btn"), $("#add-btn-2")].forEach((b) => b.addEventListener("click", () => file.click()));
  file.addEventListener("change", (e) => { handleFiles(e.target.files); e.target.value = ""; });
  $("#tune-btn").addEventListener("click", actions.settings);
  $("#send").addEventListener("click", () => ask());
  $("#reset-btn").addEventListener("click", () => { docs.splice(0, docs.length); renderDocs(); clearAll(); toast("Started over"); });
  $("#new-btn").addEventListener("click", () => { clearAll(); $("#question").value = ""; $("#question").focus(); });
  $("#new-menu").addEventListener("click", (e) => {
    e.stopPropagation();
    const m = $("#menu");
    m.hidden = !m.hidden;
    $("#new-menu").setAttribute("aria-expanded", String(!m.hidden));
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".split-btn")) $("#menu").hidden = true; });
  $("#k").addEventListener("input", (e) => { $("#k-out").textContent = e.target.value; updateContext(); });
  $("#side-open").addEventListener("click", openSide);
  $("#side-close").addEventListener("click", closeSide);
  $("#scrim").addEventListener("click", closeSide);

  const q = $("#question");
  const autoGrow = () => { q.style.height = "auto"; q.style.height = Math.min(q.scrollHeight, 240) + "px"; };
  q.addEventListener("input", autoGrow);
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); ask(); } });

  // Command field: Ctrl/Cmd+K focuses it; Enter asks the question.
  const cmd = $("#cmd");
  if (/Mac|iPhone|iPad/.test(navigator.platform)) $("#cmd-kbd").textContent = "⌘ K";
  document.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); cmd.focus(); }
    if (e.key === "Escape") { closeSide(); $("#menu").hidden = true; }
  });
  cmd.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && cmd.value.trim()) { q.value = cmd.value.trim(); cmd.value = ""; autoGrow(); ask(); }
  });

  // Drag and drop anywhere on the composer
  const comp = $("#composer");
  ["dragenter", "dragover"].forEach((t) => comp.addEventListener(t, (e) => { e.preventDefault(); comp.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => comp.addEventListener(t, (e) => { e.preventDefault(); if (t === "drop" || !comp.contains(e.relatedTarget)) comp.classList.remove("over"); }));
  comp.addEventListener("drop", (e) => handleFiles(e.dataTransfer.files));
}

init();

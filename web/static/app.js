import * as pdfjs from "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.4.168/build/pdf.min.mjs";

pdfjs.GlobalWorkerOptions.workerSrc = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.4.168/build/pdf.worker.min.mjs";

const SUGGESTIONS = [
  "Compare the price, features and warranty offered in each document.",
  "Which option is better for a student on a budget, and why?",
  "List the strengths and weaknesses mentioned in each document.",
  "What are the main objectives of each document?",
];
const SAMPLES = ["laptop_alpha.pdf", "laptop_beta.pdf", "laptop_gamma.pdf"];
const MAX = 3;

const $ = (s, el = document) => el.querySelector(s);
const docs = [];            // {id, name, pages: [text], words, status: "busy" | "ok" | "bad", error}
let running = false;

/* ---------- model status ---------- */
async function checkHealth() {
  const el = $("#status");
  try {
    const r = await fetch("/api/health", { cache: "no-store" });
    const h = await r.json();
    el.className = "status " + (h.ok ? "ok" : "down");
    $(".status-text", el).textContent = h.ok ? "Qwen 2.5 14B · online" : "Model offline";
    el.title = h.ok ? "The model server is reachable." : (h.error || "Model server unavailable.");
  } catch {
    el.className = "status down";
    $(".status-text", el).textContent = "Model offline";
  }
}

/* ---------- documents ---------- */
async function readPdf(buffer) {
  const pdf = await pdfjs.getDocument({ data: buffer }).promise;
  const pages = [];
  for (let i = 1; i <= Math.min(pdf.numPages, 300); i++) {
    const content = await (await pdf.getPage(i)).getTextContent();
    pages.push(content.items.map((it) => it.str + (it.hasEOL ? "\n" : " ")).join("").replace(/[ \t]+/g, " ").trim());
  }
  return pages;
}

async function addFile(name, buffer) {
  if (docs.length >= MAX) return toast(`Up to ${MAX} PDFs`);
  if (docs.some((d) => d.name === name)) return toast(`${name} is already added`);
  const doc = { id: crypto.randomUUID(), name, pages: [], words: 0, status: "busy" };
  docs.push(doc);
  renderFiles();
  try {
    doc.pages = await readPdf(buffer);
    doc.words = doc.pages.join(" ").split(/\s+/).filter(Boolean).length;
    if (!doc.words) throw new Error("No text found — it may be a scanned PDF.");
    doc.status = "ok";
  } catch (e) {
    doc.status = "bad";
    doc.error = /password/i.test(e?.name + e?.message) ? "Password protected." : (e?.message || "Could not read this PDF.");
  }
  renderFiles();
}

function handleFiles(list) {
  for (const f of [...list]) {
    if (f.type !== "application/pdf" && !/\.pdf$/i.test(f.name)) { toast(`${f.name} is not a PDF`); continue; }
    f.arrayBuffer().then((b) => addFile(f.name, b));
  }
}

function renderFiles() {
  const ul = $("#files");
  ul.replaceChildren(...docs.map((d) => {
    const li = document.createElement("li");
    li.className = "file " + (d.status === "busy" ? "busy" : d.status === "bad" ? "bad" : "");
    li.innerHTML = `<span class="ic" aria-hidden="true">PDF</span>
      <div class="grow"><div class="name"></div><div class="info"></div></div>
      <button class="icon-btn" type="button" aria-label="Remove">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>`;
    $(".name", li).textContent = d.name;
    $(".info", li).textContent = d.status === "bad" ? d.error
      : d.status === "busy" ? "" : `${d.pages.length} ${d.pages.length === 1 ? "page" : "pages"} · ${d.words.toLocaleString()} words`;
    $(".icon-btn", li).onclick = () => { docs.splice(docs.indexOf(d), 1); renderFiles(); };
    return li;
  }));
  $("#doc-count").textContent = `${docs.length} of ${MAX}`;
  $("#drop").classList.toggle("full", docs.length >= MAX);
  $("#samples").hidden = docs.length > 0;
}

/* ---------- asking ---------- */
function setBusy(on, which) {
  running = on;
  for (const id of ["compare", "overview"]) {
    const b = $("#" + id);
    b.disabled = on;
    b.innerHTML = on && id === which ? `<span class="spin"></span>${b.dataset.label}` : b.dataset.label;
  }
}

function notice(msg) {
  const n = $("#notice");
  n.textContent = msg || "";
  n.hidden = !msg;
}

async function ask({ overview = false } = {}) {
  if (running) return;
  const ready = docs.filter((d) => d.status === "ok");
  const question = $("#question").value.trim();
  if (docs.some((d) => d.status === "busy")) return notice("Still reading the PDFs — one moment.");
  if (ready.length < 2) return notice("Add at least 2 readable PDFs to compare.");
  if (!overview && !question) { $("#question").focus(); return notice("Type a question first."); }
  notice("");
  setBusy(true, overview ? "overview" : "compare");
  $("#empty").hidden = true;

  const card = $("#result-tpl").content.firstElementChild.cloneNode(true);
  $(".q", card).textContent = overview ? "Quick overview" : question;
  $(".meta", card).textContent = `${ready.map((d) => d.name).join(" · ")}`;
  $("#results").prepend(card);
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });

  const answerEl = $(".answer", card);
  let text = "", sources = {}, failed = false, started = performance.now(), frame = 0;
  const paint = (final) => {
    answerEl.classList.toggle("caret", !final);
    answerEl.innerHTML = renderMarkdown(text);
  };

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
  } catch (e) {
    failed = true;
    card.classList.add("error");
    answerEl.classList.remove("caret");
    answerEl.textContent = e.message || "Something went wrong.";
  }
  cancelAnimationFrame(frame);
  if (!failed) {
    paint(true);
    const secs = ((performance.now() - started) / 1000).toFixed(1);
    $(".meta", card).textContent += ` · Qwen 2.5 14B · ${secs}s`;
    wireTools(card, text, sources);
  }
  setBusy(false);
  checkHealth();
}

/* ---------- rendering ---------- */
function renderMarkdown(md) {
  const html = DOMPurify.sanitize(marked.parse(md, { gfm: true, breaks: false }));
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  tpl.content.querySelectorAll("table").forEach((t) => {
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
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
  const a = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(new Blob([content], { type })), download: name,
  });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function wireTools(card, text, sources) {
  const foot = $(".result-foot", card);
  foot.hidden = false;
  const csv = tableToCsv(text);
  const csvBtn = $('[data-act="csv"]', card);
  if (!csv) csvBtn.remove();
  foot.addEventListener("click", async (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "copy") { await navigator.clipboard.writeText(text); toast("Copied"); }
    if (act === "md") download("comparison.md", text, "text/markdown");
    if (act === "csv") download("comparison.csv", "﻿" + csv, "text/csv");
  });
  const list = $(".src-list", card);
  for (const [name, hits] of Object.entries(sources)) {
    const div = document.createElement("div");
    div.className = "src-doc";
    const h = document.createElement("h4");
    h.textContent = name;
    div.append(h);
    for (const hit of hits) {
      const q = document.createElement("blockquote");
      const c = document.createElement("cite");
      c.textContent = `Page ${hit.page}`;
      q.append(c, hit.text.length > 600 ? hit.text.slice(0, 600) + "…" : hit.text);
      div.append(q);
    }
    list.append(div);
  }
}

function toast(msg) {
  document.querySelector(".toast")?.remove();
  const t = Object.assign(document.createElement("div"), { className: "toast", textContent: msg, role: "status" });
  document.body.append(t);
  setTimeout(() => t.remove(), 1800);
}

/* ---------- wiring ---------- */
function init() {
  for (const id of ["compare", "overview"]) $("#" + id).dataset.label = $("#" + id).textContent;
  $("#chips").replaceChildren(...SUGGESTIONS.map((s) => {
    const b = Object.assign(document.createElement("button"), { className: "chip", type: "button", textContent: s });
    b.onclick = () => { $("#question").value = s; $("#question").focus(); };
    return b;
  }));

  const drop = $("#drop");
  $("#file").onchange = (e) => { handleFiles(e.target.files); e.target.value = ""; };
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => handleFiles(e.dataTransfer.files));

  $("#samples").onclick = async () => {
    for (const n of SAMPLES) {
      const r = await fetch(`/samples/${n}`);
      if (r.ok) addFile(n, await r.arrayBuffer());
    }
  };
  $("#k").oninput = (e) => ($("#k-out").textContent = e.target.value);
  $("#compare").onclick = () => ask();
  $("#overview").onclick = () => ask({ overview: true });
  $("#question").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); ask(); }
  });
  renderFiles();
  checkHealth();
}

init();

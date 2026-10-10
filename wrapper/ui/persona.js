/* Approval Gate persona page logic. Loaded by persona.html. The page never decides; it renders POST /decide. */
"use strict";

const PERSONA = "customer_support";
const MAX_CHARS = 20000;
const HISTORY_LIMIT = 8;
const PREVIEW_CHARS = 80;
const REQUEST_TIMEOUT_MS = 60000;
const MAX_TENURE_MONTHS = 1200;
const SECONDARY_EVIDENCE = ["Checked against price_sheet.csv and policies.json", "Ezio error:"];
const DECISION_LABELS = { APPROVE: "APPROVE", HOLD_FOR_REVIEW: "HOLD FOR REVIEW", BLOCK: "BLOCK" };
const NOT_SENT = { APPROVE: "Not sent.", HOLD_FOR_REVIEW: "Not sent. Held for a manager.", BLOCK: "Not sent. Blocked." };
const KNOWN_PLANS = ["Starter", "Pro", "Business", "Enterprise"];
const CHECK_STATUS = { pass: "Passed", hold: "Held", block: "Blocked", skipped: "Skipped" };
const LEVEL_RANK = { HOLD_FOR_REVIEW: 1, BLOCK: 2 };
const SENTENCE_SPLIT = /(?<=[.!?])\s+|\n+/;

const $ = (id) => document.getElementById(id);
const ui = {
  form: $("compose-form"), body: $("body"), plan: $("plan"), tenure: $("tenure"),
  counter: $("counter"), bodyError: $("body-error"), tenureError: $("tenure-error"),
  submit: $("submit"), sample: $("sample"), sampleStatus: $("sample-status"),
  resultPanel: $("result"), resultBody: $("result-body"), copy: $("copy-json"),
  historyList: $("history-list"), historyEmpty: $("history-empty"), shortcut: $("shortcut"),
};

const state = { history: [], samples: [], activeId: null, busy: false, nextId: 1, elapsedTimer: null };

/* ---------- DOM helper: builds nodes with textContent only, never innerHTML ---------- */
function h(tag, props, ...children) {
  const node = document.createElement(tag);
  Object.entries(props || {}).forEach(([key, value]) => {
    if (value === null || value === undefined || value === false) return;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = String(value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, String(value));
  });
  children.flat().forEach((child) => {
    if (child === null || child === undefined || child === false) return;
    node.append(child instanceof Node ? child : String(child));
  });
  return node;
}

const get = (obj, path) => path.reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), obj);
const fmtNum = (v) => (typeof v === "number" && Number.isFinite(v) ? String(Math.round(v * 10) / 10) : "n/a");
const capitalize = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const isNarrow = () => window.matchMedia("(max-width: 767px)").matches;
const timeLabel = (date) => date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

function preview(text) {
  const flat = String(text).replace(/\s+/g, " ").trim();
  return flat.length > PREVIEW_CHARS ? flat.slice(0, PREVIEW_CHARS).trimEnd() + "..." : flat;
}

/* ---------- Requests ---------- */
class RequestError extends Error {
  constructor(kind, message, status) {
    super(message || kind);
    this.kind = kind;
    this.status = status || null;
    this.serverMessage = message || "";
  }
}

function isDecisionResponse(body) {
  return Boolean(body) && typeof body === "object" && Object.prototype.hasOwnProperty.call(DECISION_LABELS, body.decision)
    && typeof body.reason === "string";
}

async function postDecide(text, context, signal) {
  let response;
  let body = null;
  try {
    response = await fetch("/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, context, persona: PERSONA }),
      signal,
    });
    body = await response.json().catch(() => null);
  } catch (err) {
    throw new RequestError(err && err.name === "AbortError" ? "timeout" : "network");
  }
  if (!response.ok) {
    const message = body && typeof body.error === "string" ? body.error : "";
    const kind = response.status === 400 ? "bad_request" : response.status >= 500 ? "server" : "http";
    throw new RequestError(kind, message, response.status);
  }
  if (!isDecisionResponse(body)) throw new RequestError("malformed", "", response.status);
  return body;
}

async function fetchSamples() {
  const response = await fetch("/api/samples?persona=" + encodeURIComponent(PERSONA));
  if (!response.ok) throw new Error("HTTP " + response.status);
  const body = await response.json();
  const list = Array.isArray(body && body.samples) ? body.samples : [];
  return list.filter((s) => s && typeof s.text === "string" && s.text.trim());
}

/* ---------- Compose ---------- */
function readContext() {
  const plan = ui.plan.value;
  const tenure = ui.tenure.value.trim();
  return {
    ...(plan ? { plan } : {}),
    ...(tenure !== "" ? { customer_tenure_months: Number(tenure) } : {}),
  };
}

function setFieldError(input, errorNode, message) {
  errorNode.textContent = message || "";
  errorNode.hidden = !message;
  if (message) input.setAttribute("aria-invalid", "true");
  else input.removeAttribute("aria-invalid");
}

function validateForm() {
  const text = ui.body.value;
  const tenure = ui.tenure.value.trim();
  const tenureNum = Number(tenure);
  const bodyProblem = !text.trim() ? "Write the email body before checking it."
    : text.length > MAX_CHARS ? "The email is over 20,000 characters. Shorten it before checking." : "";
  const tenureBad = ui.tenure.validity.badInput
    || (tenure !== "" && (!Number.isInteger(tenureNum) || tenureNum < 0 || tenureNum > MAX_TENURE_MONTHS));
  const tenureProblem = tenureBad ? "Enter tenure as whole months from 0 to 1200, or leave it empty." : "";
  setFieldError(ui.body, ui.bodyError, bodyProblem);
  setFieldError(ui.tenure, ui.tenureError, tenureProblem);
  if (bodyProblem) ui.body.focus();
  else if (tenureProblem) ui.tenure.focus();
  return !bodyProblem && !tenureProblem;
}

function updateCounter() {
  const length = ui.body.value.length;
  const over = length > MAX_CHARS;
  ui.counter.textContent = length.toLocaleString("en-US") + " / 20,000" + (over ? " (over the limit)" : "");
  ui.counter.classList.toggle("over", over);
  ui.submit.disabled = state.busy || over;
}

function fillFromSample(sample) {
  const context = sample.context && typeof sample.context === "object" ? sample.context : {};
  const tenure = context.customer_tenure_months;
  ui.body.value = sample.text;
  ui.plan.value = KNOWN_PLANS.includes(context.plan) ? context.plan : "";
  ui.tenure.value = typeof tenure === "number" && Number.isFinite(tenure) ? String(tenure) : "";
  setFieldError(ui.body, ui.bodyError, "");
  setFieldError(ui.tenure, ui.tenureError, "");
  updateCounter();
}

function selectedSample() {
  const index = Number(ui.sample.value);
  return ui.sample.value !== "" && state.samples[index] ? state.samples[index] : null;
}

/* ---------- Busy state ---------- */
function setBusy(busy) {
  state.busy = busy;
  ui.submit.classList.toggle("is-busy", busy);
  ui.submit.textContent = busy ? "Checking..." : "Check and send";
  ui.historyList.querySelectorAll("button").forEach((b) => { b.disabled = busy; });
  updateCounter();
  if (!busy && state.elapsedTimer) {
    clearInterval(state.elapsedTimer);
    state.elapsedTimer = null;
  }
}

function startElapsed(node, startedAt) {
  state.elapsedTimer = setInterval(() => {
    node.textContent = Math.floor((performance.now() - startedAt) / 1000) + " s";
  }, 1000);
}

/* ---------- Submit ---------- */
async function submitDraft() {
  if (state.busy || !validateForm()) return;
  const text = ui.body.value;
  const context = readContext();
  await runDecision(text, context);
}

async function runDecision(text, context) {
  const startedAt = performance.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  setBusy(true);
  renderLoading(startedAt);
  if (isNarrow()) ui.resultPanel.scrollIntoView({ block: "start" });
  try {
    const result = await postDecide(text, context, controller.signal);
    const entry = { id: state.nextId, text, context, result, at: new Date(), seconds: (performance.now() - startedAt) / 1000 };
    state.nextId += 1;
    state.history = [entry, ...state.history].slice(0, HISTORY_LIMIT);
    state.activeId = entry.id;
    renderResult(entry);
  } catch (err) {
    const failure = err instanceof RequestError ? err : new RequestError("network");
    renderError(failure);
  } finally {
    clearTimeout(timeout);
    setBusy(false);
    renderHistory();
  }
}

/* ---------- Result rendering ---------- */
function reasonLines(reason, evidence) {
  const parts = String(reason).split("; ");
  const known = new Set((Array.isArray(evidence) ? evidence : []).map(String));
  const lines = [];
  let i = 0;
  while (i < parts.length) {
    let take = 1;
    for (let j = parts.length; j > i + 1; j -= 1) {
      if (known.has(parts.slice(i, j).join("; "))) { take = j - i; break; }
    }
    lines.push(parts.slice(i, i + take).join("; "));
    i += take;
  }
  return lines.map((line) => capitalize(line.trim())).filter(Boolean);
}

function outcomeText(result) {
  return result.action_executed === true ? "Email sent (mock action ran)" : NOT_SENT[result.decision];
}

function verdictBlock(entry) {
  const { result } = entry;
  return h("div", { class: "verdict" },
    h("p", { class: "badge", "data-decision": result.decision, text: DECISION_LABELS[result.decision] }),
    h("div", null,
      h("p", { class: "outcome", text: outcomeText(result) }),
      h("p", { class: "verdict-meta", text: "Decided at " + timeLabel(entry.at) + " in " + entry.seconds.toFixed(1) + " s" })));
}

function reasonBlock(result) {
  const lines = reasonLines(result.reason, result.evidence);
  return h("div", { class: "section" },
    h("h3", { text: "Reason" }),
    h("ul", { class: "reason-list" }, lines.map((line) => h("li", { text: line }))));
}

function evidenceBlock(result) {
  const items = (Array.isArray(result.evidence) ? result.evidence : [])
    .map((item) => (typeof item === "string" ? item : JSON.stringify(item)));
  const isSecondary = (item) => SECONDARY_EVIDENCE.some((prefix) => item.startsWith(prefix));
  const findings = items.filter((item) => !isSecondary(item));
  const summaries = items.filter(isSecondary);
  return h("div", { class: "section" },
    h("h3", { text: "Evidence" }),
    findings.length
      ? h("ul", { class: "evidence-list" }, findings.map((item) => h("li", { text: item })))
      : h("p", { class: "hint", text: items.length ? "No rule findings. Summary of what was checked:" : "The wrapper returned no evidence." }),
    summaries.map((item) => h("p", { class: "evidence-summary", text: item })));
}

function metric(label, value) {
  return h("div", null, h("dt", { text: label }), h("dd", { text: value }));
}

function claimItem(claim) {
  const verdict = typeof claim.verdict === "string" ? claim.verdict : "unknown";
  const publisher = get(claim, ["source", "publisher"]);
  const url = get(claim, ["source", "url"]);
  const safeUrl = typeof url === "string" && /^https?:\/\//i.test(url) ? url : null;
  const sourceParts = [
    typeof publisher === "string" && publisher ? publisher : null,
    safeUrl ? h("a", { href: safeUrl, target: "_blank", rel: "noopener noreferrer", class: "mono", text: safeUrl }) : null,
  ].filter(Boolean);
  return h("li", { class: "claim" },
    h("div", { class: "claim-top" },
      h("span", { class: "pill", "data-verdict": verdict, text: verdict }),
      h("span", { class: "claim-text", text: typeof claim.text === "string" ? claim.text : "" })),
    sourceParts.length
      ? h("p", { class: "claim-source" }, "Source: ", sourceParts.flatMap((p, i) => (i ? [", ", p] : [p])))
      : null);
}

function ezioDownBlock(ezio) {
  return h("div", { class: "notice" },
    h("p", { class: "notice-title", text: "Ezio unavailable" }),
    h("p", { class: "mono", text: String(ezio.error) }),
    h("p", { text: "The gate failed closed. Without Ezio it does not approve: it holds for review, or blocks when our own price and policy check already found a wrong fact." }));
}

function ezioBlock(ezio) {
  const title = h("h3", { text: "Ezio signals" });
  if (!ezio || typeof ezio !== "object" || !Object.keys(ezio).length) {
    return h("div", { class: "section" }, title, h("p", { class: "hint", text: "No Ezio data in this response." }));
  }
  if (ezio.error) return h("div", { class: "section" }, title, ezioDownBlock(ezio));
  const status = get(ezio, ["dimensions", "accuracy", "status"]);
  const accScore = get(ezio, ["dimensions", "accuracy", "score"]);
  const accuracy = typeof status === "string"
    ? status.replace(/_/g, " ") + (status === "scored" && typeof accScore === "number" ? " " + fmtNum(accScore) : "")
    : "n/a";
  const tier = get(ezio, ["verdict", "tier"]);
  const summary = get(ezio, ["verdict", "summary"]);
  const claims = Array.isArray(ezio.claims) ? ezio.claims.filter((c) => c && typeof c === "object") : [];
  return h("div", { class: "section" }, title,
    h("dl", { class: "metrics" },
      metric("Tier", typeof tier === "string" ? tier : "n/a"),
      metric("Score", fmtNum(get(ezio, ["verdict", "score"]))),
      metric("Accuracy", accuracy),
      metric("Tone", fmtNum(get(ezio, ["dimensions", "tone", "score"]))),
      metric("Bias", fmtNum(get(ezio, ["dimensions", "bias", "score"]))),
      metric("Agreement", fmtNum(get(ezio, ["dimensions", "agreement", "score"])))),
    typeof summary === "string" && summary ? h("p", { class: "ezio-summary", text: summary }) : null,
    h("div", { class: "claims" },
      h("h4", { text: "Public claims Ezio checked" }),
      claims.length
        ? h("ul", null, claims.map(claimItem))
        : h("p", { class: "hint", text: "None. Ezio found no public claims to fact-check in this email." })));
}

/* ---------- Explainable panels: checklist, sentence view, suggested fix ---------- */
function findingsOf(result) {
  return Array.isArray(result.findings) ? result.findings.filter((f) => f && typeof f === "object") : null;
}

function splitSentences(text) {
  return String(text).split(SENTENCE_SPLIT).filter((s) => s && s.trim());
}

function strictestLevel(findings) {
  return findings.reduce((best, f) => ((LEVEL_RANK[f.level] || 0) > (LEVEL_RANK[best] || 0) ? f.level : best), null);
}

function dropOverlaps(ranges) {
  return [...ranges].sort((a, b) => a.start - b.start)
    .reduce((kept, r) => (kept.length && r.start < kept[kept.length - 1].end ? kept : [...kept, r]), []);
}

function markValues(sentence, values) {
  const ranges = dropOverlaps(values.filter((v) => typeof v === "string" && v)
    .map((v) => ({ start: sentence.indexOf(v), end: sentence.indexOf(v) + v.length }))
    .filter((r) => r.start >= 0));
  const nodes = [];
  let cursor = 0;
  ranges.forEach((r) => {
    if (r.start > cursor) nodes.push(sentence.slice(cursor, r.start));
    nodes.push(h("mark", { class: "found", text: sentence.slice(r.start, r.end) }));
    cursor = r.end;
  });
  if (cursor < sentence.length) nodes.push(sentence.slice(cursor));
  return nodes;
}

function checkRow(row) {
  const known = Object.prototype.hasOwnProperty.call(CHECK_STATUS, row.status);
  return h("li", { class: "check-row" },
    h("span", { class: "chip", "data-status": known ? row.status : "skipped", text: known ? CHECK_STATUS[row.status] : String(row.status || "Unknown") }),
    h("div", null,
      h("p", { class: "check-label", text: typeof row.label === "string" && row.label ? row.label : String(row.signal || "Check") }),
      typeof row.detail === "string" && row.detail ? h("p", { class: "check-detail", text: row.detail }) : null));
}

function checklistBlock(result) {
  const rows = Array.isArray(result.checks) ? result.checks.filter((c) => c && typeof c === "object") : [];
  if (!rows.length) return null;
  const isEzio = (row) => typeof row.signal === "string" && row.signal.startsWith("ezio");
  const groups = [["Our checks", rows.filter((r) => !isEzio(r))], ["Ezio", rows.filter(isEzio)]].filter(([, list]) => list.length);
  return h("div", { class: "section" },
    h("h3", { text: "Signal checklist" }),
    groups.map(([title, list]) => h("div", { class: "check-group" },
      h("h4", { text: title }),
      h("ul", null, list.map(checkRow)))));
}

function findingNote(f) {
  const label = f.level === "BLOCK" ? "BLOCK" : f.level === "HOLD_FOR_REVIEW" ? "HOLD" : String(f.level || "NOTE");
  return h("li", { "data-level": f.level },
    h("span", { class: "finding-level", text: label }), typeof f.message === "string" ? f.message : "");
}

function sentenceRow(index, content, findings, isWhole) {
  return h("li", { class: "sentence" + (isWhole ? " whole" : ""), "data-level": strictestLevel(findings) },
    h("span", { class: "sentence-index", "aria-hidden": "true", text: index }),
    h("div", { class: "sentence-body" },
      h("p", { class: "sentence-text" }, content),
      findings.length ? h("ul", { class: "finding-notes" }, findings.map(findingNote)) : null));
}

function sentencesBlock(text, result) {
  const findings = findingsOf(result);
  if (!findings || typeof text !== "string") return null;
  const sentences = splitSentences(text);
  const rows = sentences.map((sentence, i) => {
    const own = findings.filter((f) => f.sentence === i);
    return sentenceRow(String(i + 1), markValues(sentence.trim(), own.map((f) => f.found)), own, false);
  });
  const whole = findings.filter((f) => !(Number.isInteger(f.sentence) && f.sentence >= 0 && f.sentence < sentences.length));
  return h("div", { class: "section" },
    h("h3", { text: "Email, sentence by sentence" }),
    h("ol", { class: "sentences" }, rows, whole.length ? sentenceRow("", "Whole email", whole, true) : null));
}

function sentenceStarts(text) {
  let cursor = 0;
  return splitSentences(text).map((s) => {
    const trimmed = s.trim();
    const at = text.indexOf(trimmed, cursor);
    if (at >= 0) cursor = at + trimmed.length;
    return { start: at, text: trimmed };
  });
}

function fixRange(text, starts, finding) {
  const { fix } = finding;
  const quote = typeof finding.quote === "string" && finding.quote ? finding.quote : null;
  const known = starts[fix.sentence];
  const start = known && known.start >= 0 && (!quote || known.text === quote) ? known.start : quote ? text.indexOf(quote) : -1;
  const span = quote ? quote.length : known ? known.text.length : 0;
  const at = start >= 0 ? text.indexOf(fix.find, start) : -1;
  return at >= 0 && at + fix.find.length <= start + span
    ? { start: at, end: at + fix.find.length, find: fix.find, replace: fix.replace, finding } : null;
}

function buildFix(text, findings) {
  const starts = sentenceStarts(text);
  const ranges = dropOverlaps(findings
    .filter((f) => f.fix && typeof f.fix === "object" && typeof f.fix.find === "string" && f.fix.find && typeof f.fix.replace === "string")
    .map((f) => fixRange(text, starts, f))
    .filter(Boolean));
  if (!ranges.length) return null;
  const segments = [];
  let cursor = 0;
  ranges.forEach((r) => {
    if (r.start > cursor) segments.push({ text: text.slice(cursor, r.start), changed: false });
    segments.push({ text: r.replace, changed: true });
    cursor = r.end;
  });
  if (cursor < text.length) segments.push({ text: text.slice(cursor), changed: false });
  return { segments, ranges, rewritten: segments.map((s) => s.text).join("") };
}

function fixNote(unfixed) {
  const base = "Only values from price_sheet.csv and policies.json were changed. ";
  if (!unfixed) return base + "Any other issue still needs a person, and the gate decides again on re-check.";
  return base + unfixed + (unfixed === 1 ? " other finding is not changed here and still needs a person."
    : " other findings are not changed here and still need a person.");
}

function fixBlock(entry) {
  const findings = findingsOf(entry.result);
  const fix = findings && typeof entry.text === "string" ? buildFix(entry.text, findings) : null;
  if (!fix) return null;
  const unfixed = findings.filter((f) => !fix.ranges.some((r) => r.finding === f)).length;
  return h("div", { class: "section fix" },
    h("h3", { text: "Suggested fix" }),
    h("p", { class: "fix-text" }, fix.segments.map((s) => (s.changed ? h("mark", { class: "fix-mark", text: s.text }) : s.text))),
    h("ul", { class: "fix-changes" }, fix.ranges.map((r) => h("li", null,
      h("span", { class: "mono", text: r.find }), " changed to ", h("span", { class: "mono", text: r.replace }),
      typeof r.finding.source === "string" && r.finding.source ? " (" + r.finding.source + ")" : ""))),
    h("p", { class: "hint", text: fixNote(unfixed) }),
    h("button", { type: "button", class: "btn btn-primary fix-use", text: "Use and re-check",
      onclick: () => useFix(entry, fix.rewritten) }));
}

function useFix(entry, rewritten) {
  if (state.busy) return;
  const ctx = entry.context && typeof entry.context === "object" ? entry.context : {};
  ui.body.value = rewritten;
  ui.plan.value = KNOWN_PLANS.includes(ctx.plan) ? ctx.plan : "";
  ui.tenure.value = typeof ctx.customer_tenure_months === "number" ? String(ctx.customer_tenure_months) : "";
  ui.sample.value = "";
  setFieldError(ui.body, ui.bodyError, "");
  setFieldError(ui.tenure, ui.tenureError, "");
  updateCounter();
  submitDraft();
}

function renderResult(entry) {
  const view = h("div", { class: prefersReducedMotion() ? "" : "enter" },
    verdictBlock(entry), checklistBlock(entry.result), sentencesBlock(entry.text, entry.result), fixBlock(entry),
    reasonBlock(entry.result), evidenceBlock(entry.result), ezioBlock(entry.result.ezio));
  ui.resultBody.replaceChildren(view);
  ui.copy.hidden = false;
  ui.copy.textContent = "Copy audit JSON";
}

function renderLoading(startedAt) {
  const elapsed = h("span", { class: "elapsed", "aria-hidden": "true", text: "0 s" });
  const checkRows = (widths) => widths.map((w) => h("div", { class: "sk-row" }, h("div", { class: "sk sk-chip" }), h("div", { class: "sk sk-line " + w })));
  const skeleton = h("div", { "aria-hidden": "true" },
    h("div", { class: "sk-verdict" }, h("div", { class: "sk sk-badge" }), h("div", { class: "sk sk-line w30" })),
    h("div", { class: "sk sk-heading" }), checkRows(["w80", "w60", "w70"]), h("div", { class: "sk-divider" }), checkRows(["w70", "w60", "w30"]),
    h("div", { class: "sk sk-heading" }), h("div", { class: "sk sk-sentence" }), h("div", { class: "sk sk-sentence w80" }),
    h("div", { class: "sk sk-heading" }), h("div", { class: "sk sk-line w90" }), h("div", { class: "sk sk-line w70" }));
  ui.resultBody.replaceChildren(
    h("p", { class: "loading-status" }, "Checking the draft with Ezio and our price sheet and policies. This can take up to 20 seconds. ", elapsed),
    skeleton);
  ui.copy.hidden = true;
  startElapsed(elapsed, startedAt);
}

function describeError(err) {
  const server = err.serverMessage ? "The wrapper said: " + err.serverMessage : "";
  switch (err.kind) {
    case "network": return ["Cannot reach the wrapper", "The request to /decide did not get through. Check that gate.py serve is still running."];
    case "timeout": return ["No answer after 60 seconds", "The wrapper did not respond in time. The mock can be slow."];
    case "bad_request": return ["The wrapper rejected this request (HTTP 400)", server || "Check the email body and customer context."];
    case "server": return ["The wrapper failed (HTTP " + err.status + ")", server || "The decision could not be made."];
    case "malformed": return ["Unexpected response from the wrapper", "The response did not contain a valid decision, so none is shown."];
    default: return ["Request failed (HTTP " + (err.status || "unknown") + ")", server || "The wrapper returned an unexpected status."];
  }
}

function renderError(err) {
  const [title, detail] = describeError(err);
  ui.resultBody.replaceChildren(h("div", { class: "notice error" + (prefersReducedMotion() ? "" : " enter") },
    h("p", { class: "notice-title", text: title }),
    h("p", { text: detail }),
    h("p", { class: "hint", text: "No decision was received. Do not treat this email as approved or sent. Your draft is still in the form; choose Check and send to try again." })));
  ui.copy.hidden = true;
}

/* ---------- History ---------- */
function renderHistory() {
  ui.historyEmpty.hidden = state.history.length > 0;
  ui.historyList.replaceChildren(...state.history.map((entry) => h("li", null,
    h("button", {
      type: "button",
      class: "history-item",
      "data-decision": entry.result.decision,
      "aria-current": entry.id === state.activeId ? "true" : null,
      disabled: state.busy,
      onclick: () => showFromHistory(entry.id),
    },
      h("span", { class: "h-decision", text: DECISION_LABELS[entry.result.decision] }),
      h("time", { class: "h-time", datetime: entry.at.toISOString(), text: timeLabel(entry.at) }),
      h("span", { class: "h-text", text: preview(entry.text) })))));
}

function showFromHistory(id) {
  const entry = state.history.find((e) => e.id === id);
  if (!entry || state.busy) return;
  state.activeId = id;
  renderResult(entry);
  renderHistory();
  if (isNarrow()) ui.resultPanel.scrollIntoView({ block: "start" });
}

/* ---------- Copy ---------- */
async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = h("textarea", { readonly: "", style: "position:fixed;top:0;left:0;opacity:0" });
  area.value = text;
  document.body.append(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  if (!ok) throw new Error("copy command failed");
}

async function copyAuditJson() {
  const entry = state.history.find((e) => e.id === state.activeId);
  if (!entry) return;
  try {
    await copyText(JSON.stringify(entry.result, null, 2));
    ui.copy.textContent = "Copied";
  } catch (err) {
    console.error("Copy audit JSON failed", err);
    ui.copy.textContent = "Copy failed";
  }
  setTimeout(() => { ui.copy.textContent = "Copy audit JSON"; }, 1800);
}

/* ---------- Samples ---------- */
function sampleLabel(sample, index) {
  const ctx = sample.context && typeof sample.context === "object" ? sample.context : {};
  const bits = [ctx.plan, typeof ctx.customer_tenure_months === "number" ? ctx.customer_tenure_months + " mo" : null].filter(Boolean);
  const text = String(sample.text).replace(/\s+/g, " ").trim();
  const short = text.length > 60 ? text.slice(0, 60).trimEnd() + "..." : text;
  return String(index + 1).padStart(2, "0") + ". " + short + (bits.length ? " (" + bits.join(", ") + ")" : "");
}

async function loadSamples() {
  try {
    const samples = await fetchSamples();
    if (!samples.length) throw new Error("no samples returned");
    state.samples = samples;
    ui.sample.replaceChildren(
      h("option", { value: "", text: "Choose a practice sample" }),
      ...samples.map((s, i) => h("option", { value: String(i), text: sampleLabel(s, i) })));
    ui.sample.disabled = false;
    ui.sampleStatus.textContent = samples.length + " practice inputs. Choosing one fills in the email and customer context. Then choose Check and send.";
  } catch (err) {
    console.error("Loading samples failed", err);
    ui.sample.replaceChildren(h("option", { value: "", text: "Samples unavailable" }));
    ui.sample.disabled = true;
    ui.sampleStatus.replaceChildren("Practice samples could not be loaded. You can still write an email. ",
      h("button", { type: "button", class: "btn btn-ghost", text: "Retry", onclick: retrySamples }));
  }
}

function retrySamples() {
  ui.sampleStatus.textContent = "Loading practice samples...";
  loadSamples();
}

/* ---------- Wiring ---------- */
ui.form.addEventListener("submit", (event) => {
  event.preventDefault();
  submitDraft();
});
ui.form.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    submitDraft();
  }
});
ui.body.addEventListener("input", () => {
  updateCounter();
  if (!ui.bodyError.hidden && ui.body.value.trim()) setFieldError(ui.body, ui.bodyError, "");
});
ui.tenure.addEventListener("input", () => {
  if (!ui.tenureError.hidden) setFieldError(ui.tenure, ui.tenureError, "");
});
ui.sample.addEventListener("change", () => {
  const sample = selectedSample();
  if (sample) fillFromSample(sample);
});
ui.copy.addEventListener("click", copyAuditJson);

const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
ui.shortcut.textContent = isMac ? "Cmd+Enter" : "Ctrl+Enter";
updateCounter();
renderHistory();
loadSamples();

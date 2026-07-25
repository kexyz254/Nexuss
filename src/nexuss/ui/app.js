/* Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary. */
"use strict";

const elements = {
  form: document.querySelector("#command-form"),
  input: document.querySelector("#command-input"),
  send: document.querySelector("#send-button"),
  voice: document.querySelector("#voice-button"),
  waveform: document.querySelector("#waveform"),
  note: document.querySelector("#composer-note"),
  timeline: document.querySelector("#timeline"),
  commandSearch: document.querySelector("#command-search"),
  systemState: document.querySelector("#system-state"),
  systemStateLabel: document.querySelector("#system-state-label"),
  receiptState: document.querySelector("#receipt-state"),
  verificationBadge: document.querySelector("#verification-badge"),
  metricIntent: document.querySelector("#metric-intent"),
  metricConfidence: document.querySelector("#metric-confidence"),
  metricRisk: document.querySelector("#metric-risk"),
  metricState: document.querySelector("#metric-state"),
  policySummary: document.querySelector("#policy-summary"),
  planList: document.querySelector("#plan-list"),
  eventSummary: document.querySelector("#event-summary"),
  eventList: document.querySelector("#event-list"),
  evidenceSummary: document.querySelector("#evidence-summary"),
  evidenceList: document.querySelector("#evidence-list"),
  receiptId: document.querySelector("#receipt-id"),
  receiptVersion: document.querySelector("#receipt-version"),
  receiptVerified: document.querySelector("#receipt-verified"),
  receiptReversible: document.querySelector("#receipt-reversible"),
  receiptTitle: document.querySelector("#receipt-title"),
  sessionLabel: document.querySelector("#session-label"),
  reviewApproval: document.querySelector("#review-approval-button"),
  copyPath: document.querySelector("#copy-path-button"),
  rollback: document.querySelector("#rollback-button"),
  approvalOverlay: document.querySelector("#approval-overlay"),
  approvalClose: document.querySelector("#approval-close"),
  approvalAction: document.querySelector("#approval-action"),
  approvalRisk: document.querySelector("#approval-risk"),
  approvalDestination: document.querySelector("#approval-destination"),
  approvalReversible: document.querySelector("#approval-reversible"),
  approvalSummary: document.querySelector("#approval-summary"),
  approvalHash: document.querySelector("#approval-hash"),
  approvalPreview: document.querySelector("#approval-preview"),
  approvalExpiry: document.querySelector("#approval-expiry"),
  reject: document.querySelector("#reject-button"),
  approve: document.querySelector("#approve-button"),
  toast: document.querySelector("#toast"),
};

const sessionId = sessionStorage.getItem("nexuss-session-id") || crypto.randomUUID();
sessionStorage.setItem("nexuss-session-id", sessionId);
elements.sessionLabel.textContent = `Session ${sessionId.slice(0, 8)}`;

let lastInputChannel = "text";
let recognition = null;
let currentTask = null;
let currentReceipt = null;
let currentNotePath = null;
let toastTimer = null;

function apiHeaders() {
  return {
    "Content-Type": "application/json",
    "X-Nexuss-Session-ID": sessionId,
    "X-Nexuss-Session-Authenticated": "true",
  };
}

function setBusy(busy) {
  elements.send.disabled = busy;
  elements.input.disabled = busy;
  elements.approve.disabled = busy;
  elements.reject.disabled = busy;
  elements.rollback.disabled = busy;
}

function setHealth(state, label) {
  elements.systemState.classList.remove("ready", "error");
  if (state) elements.systemState.classList.add(state);
  elements.systemStateLabel.textContent = label;
}

async function checkHealth() {
  try {
    const response = await fetch("/health/ready", { cache: "no-store" });
    if (!response.ok) throw new Error(`Health check returned ${response.status}`);
    const body = await response.json();
    setHealth("ready", `${body.status} · ${body.mode}`);
  } catch (_error) {
    setHealth("error", "Nexuss unavailable");
  }
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { elements.toast.hidden = true; }, 3200);
}

function timeLabel(value = new Date()) {
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(value);
}

function addMessage(role, text, isError = false) {
  const article = document.createElement("article");
  article.className = `message ${role === "user" ? "user-message" : "assistant-message"}`;
  if (isError) article.classList.add("error");

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "Y" : "N";

  const content = document.createElement("div");
  content.className = "message-content";
  const meta = document.createElement("div");
  meta.className = "message-meta";
  const author = document.createElement("span");
  author.textContent = role === "user" ? "You" : "Nexuss";
  const timestamp = document.createElement("time");
  timestamp.textContent = timeLabel();
  meta.append(author, timestamp);

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  bubble.append(paragraph);
  content.append(meta, bubble);
  article.append(avatar, content);
  elements.timeline.append(article);
  elements.timeline.scrollTop = elements.timeline.scrollHeight;
}

function titleCase(value) {
  return String(value || "—")
    .split("_")
    .map((part) => part ? part[0].toUpperCase() + part.slice(1) : part)
    .join(" ");
}

function compactValue(value) {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object" && value !== null) return JSON.stringify(value);
  return String(value ?? "—");
}

function createDetailCard(title, tag, attributes) {
  const card = document.createElement("div");
  card.className = "detail-card";
  const top = document.createElement("div");
  top.className = "topline";
  const heading = document.createElement("strong");
  heading.textContent = title;
  const badge = document.createElement("span");
  badge.className = `tag ${String(tag || "").toLowerCase()}`;
  badge.textContent = titleCase(tag);
  top.append(heading, badge);
  card.append(top);

  const definition = document.createElement("dl");
  for (const [key, value] of Object.entries(attributes || {})) {
    if (key === "content") continue;
    const term = document.createElement("dt");
    term.textContent = titleCase(key);
    const description = document.createElement("dd");
    description.textContent = compactValue(value);
    definition.append(term, description);
  }
  card.append(definition);
  return card;
}

function renderEvents(events) {
  elements.eventList.className = "event-list";
  elements.eventList.replaceChildren();
  for (const event of events) {
    const item = document.createElement("div");
    item.className = "event-item";
    const title = document.createElement("strong");
    title.textContent = titleCase(event.event_type);
    const detail = document.createElement("p");
    detail.textContent = event.detail;
    const timestamp = document.createElement("time");
    timestamp.textContent = `${titleCase(event.state)} · ${timeLabel(new Date(event.occurred_at))}`;
    item.append(title, detail, timestamp);
    elements.eventList.append(item);
  }
  if (!events.length) {
    elements.eventList.className = "event-list empty-state";
    elements.eventList.textContent = "The verified lifecycle will appear here.";
  }
  elements.eventSummary.textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;
}

function renderReceipt(receipt) {
  currentReceipt = receipt;
  elements.receiptId.textContent = receipt.receipt_id;
  elements.receiptVersion.textContent = String(receipt.receipt_version);
  elements.receiptVerified.textContent = receipt.verified ? "Yes" : "No";
  elements.receiptReversible.textContent = receipt.reversible ? "Yes" : "No";
  elements.receiptTitle.textContent = `${titleCase(receipt.state)} receipt`;
  elements.copyPath.hidden = !currentNotePath;
  elements.rollback.hidden = !receipt.reversible;
}

function renderTask(task, receipt) {
  currentTask = task;
  currentNotePath = null;
  elements.receiptState.textContent = titleCase(task.state);
  elements.metricIntent.textContent = titleCase(task.intent.kind);
  elements.metricConfidence.textContent = `${Math.round(task.intent.confidence * 100)}%`;
  elements.metricRisk.textContent = titleCase(task.plan.steps[0]?.risk_tier || "—");
  elements.metricState.textContent = titleCase(task.state);

  elements.verificationBadge.className = "verification-badge";
  if (task.state === "awaiting_approval") {
    elements.verificationBadge.classList.add("pending");
    elements.verificationBadge.textContent = "APPROVAL";
  } else if (task.state === "rolled_back") {
    elements.verificationBadge.classList.add("rolled-back");
    elements.verificationBadge.textContent = "ROLLED BACK";
  } else if (receipt.verified) {
    elements.verificationBadge.classList.add("verified");
    elements.verificationBadge.textContent = "VERIFIED";
  } else {
    elements.verificationBadge.classList.add("failed");
    elements.verificationBadge.textContent = titleCase(task.state).toUpperCase();
  }

  renderEvents(task.events || []);

  elements.planList.className = "detail-list";
  elements.planList.replaceChildren();
  const decisions = new Map(task.policy_decisions.map((item) => [item.step_id, item]));
  const policyCounts = { allow: 0, require_approval: 0, deny: 0 };
  for (const step of task.plan.steps) {
    const decision = decisions.get(step.step_id);
    if (decision?.outcome in policyCounts) policyCounts[decision.outcome] += 1;
    elements.planList.append(createDetailCard(
      `${step.order}. ${step.capability_id}`,
      decision?.outcome || "unknown",
      {
        risk: step.risk_tier,
        reversible: step.reversible,
        policy_reason: decision?.reason_code || "unavailable",
        expected_evidence: step.expected_evidence.join(", "),
      },
    ));
  }
  elements.policySummary.textContent = `${policyCounts.allow} allowed · ${policyCounts.require_approval} approval · ${policyCounts.deny} denied`;

  elements.evidenceList.className = "detail-list";
  elements.evidenceList.replaceChildren();
  let evidenceCount = 0;
  for (const result of task.results) {
    if (!result.evidence.length) {
      elements.evidenceList.append(createDetailCard(
        result.capability_id,
        result.status,
        { error_code: result.error_code || "No evidence returned" },
      ));
      continue;
    }
    for (const record of result.evidence) {
      evidenceCount += 1;
      if (record.attributes.managed_path) currentNotePath = String(record.attributes.managed_path);
      elements.evidenceList.append(createDetailCard(
        result.capability_id,
        result.status,
        { source: record.source, observed_at: record.observed_at, ...record.attributes },
      ));
    }
  }
  if (!task.results.length) {
    elements.evidenceList.className = "detail-list empty-state";
    elements.evidenceList.textContent = task.state === "awaiting_approval"
      ? "Execution is paused. No write occurred before approval."
      : "Execution was not authorized, so no evidence was produced.";
  }
  elements.evidenceSummary.textContent = `${evidenceCount} record${evidenceCount === 1 ? "" : "s"}`;
  elements.reviewApproval.hidden = task.state !== "awaiting_approval" || !task.approval;
  renderReceipt(receipt);
}

function assistantResponse(task) {
  const result = task.results.find((item) => item.capability_id === "assistant.respond");
  return result?.evidence?.[0]?.attributes?.response || null;
}

function summarizeTask(task) {
  const conversational = assistantResponse(task);
  if (conversational) return String(conversational);

  if (task.state === "completed") {
    const noteResult = task.results.find((result) => result.capability_id === "workspace.create_note");
    if (noteResult?.evidence?.[0]) {
      const data = noteResult.evidence[0].attributes;
      return `Created and verified ${data.filename}. The SHA-256 evidence matches the real file, and this receipt can undo the action while the file remains unchanged.`;
    }
    const liveResult = task.results.find((result) => result.capability_id === "workspace.read_status");
    if (liveResult?.evidence?.[0]) {
      const data = liveResult.evidence[0].attributes;
      const cleanText = data.git_clean ? "clean" : `${data.git_changed_entries} changed entries`;
      return `Verified live workspace status. Branch ${data.git_branch} at ${String(data.git_commit).slice(0, 8)}; working tree ${cleanText}; ${Math.round(Number(data.disk_free_bytes) / 1073741824)} GB disk space free.`;
    }
    return `Completed and verified ${task.results.length} capability result${task.results.length === 1 ? "" : "s"}.`;
  }
  if (task.state === "awaiting_approval") {
    return "I prepared a controlled write action. No file has been created. Review the exact payload and approve or cancel it.";
  }
  if (task.state === "rolled_back") return "Undo completed. The receipt-owned note was removed and its absence was verified.";
  if (task.state === "denied") {
    const reason = task.policy_decisions.find((decision) => decision.outcome === "deny")?.reason_code;
    return `The request was denied by policy${reason ? `: ${reason}` : ""}.`;
  }
  if (task.state === "failed") return "The action failed closed. Review the lifecycle and evidence panel for the recorded reason.";
  return `The task is currently ${titleCase(task.state)}.`;
}

async function fetchReceipt(taskId) {
  const response = await fetch(`/v1/tasks/${taskId}/receipt`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Receipt request failed (${response.status})`);
  return response.json();
}

function showApproval(approval) {
  elements.approvalAction.textContent = approval.action_title;
  elements.approvalRisk.textContent = titleCase(approval.risk_tier);
  elements.approvalDestination.textContent = approval.destination_label;
  elements.approvalReversible.textContent = approval.reversible ? "Yes · receipt-bound" : "No";
  elements.approvalSummary.textContent = approval.action_summary;
  elements.approvalHash.textContent = approval.payload_sha256;
  elements.approvalPreview.textContent = approval.exact_preview;
  elements.approvalExpiry.textContent = `Approval expires ${new Date(approval.expires_at).toLocaleTimeString()}. The token is single-use and session-bound.`;
  elements.approvalOverlay.hidden = false;
  elements.approve.focus();
}

function hideApproval() {
  elements.approvalOverlay.hidden = true;
  elements.input.focus();
}

async function executeInstruction(utterance, channel = "text") {
  setBusy(true);
  addMessage("user", utterance);
  addMessage("assistant", "Interpreting intent, generating a capability plan, and evaluating policy…");

  const payload = {
    request_id: crypto.randomUUID(),
    channel,
    utterance,
    user_session_id: sessionId,
    target_devices: [],
    requested_at: new Date().toISOString(),
    client_context: { interface: "p3-web-ui", browser_voice: channel === "voice" },
  };

  try {
    const response = await fetch("/v1/tasks", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`Task request failed (${response.status}): ${await response.text()}`);
    const task = await response.json();
    const receipt = await fetchReceipt(task.task_id);
    renderTask(task, receipt);
    addMessage("assistant", summarizeTask(task));
    if (task.state === "awaiting_approval" && task.approval) showApproval(task.approval);
  } catch (error) {
    addMessage("assistant", error instanceof Error ? error.message : "Unexpected Nexuss error", true);
  } finally {
    setBusy(false);
    elements.input.focus();
  }
}

async function decideApproval(decisionKind) {
  const approval = currentTask?.approval;
  if (!currentTask || !approval || !approval.approval_token) return;
  setBusy(true);
  try {
    const response = await fetch(`/v1/tasks/${currentTask.task_id}/approval`, {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({
        approval_id: approval.approval_id,
        approval_token: approval.approval_token,
        payload_sha256: approval.payload_sha256,
        decision: decisionKind,
      }),
    });
    if (!response.ok) throw new Error(`Approval failed (${response.status}): ${await response.text()}`);
    const task = await response.json();
    const receipt = await fetchReceipt(task.task_id);
    hideApproval();
    renderTask(task, receipt);
    addMessage("assistant", summarizeTask(task));
    showToast(decisionKind === "approve" ? "Exact action approved and verified." : "Action cancelled. No write occurred.");
  } catch (error) {
    addMessage("assistant", error instanceof Error ? error.message : "Approval failed", true);
  } finally {
    setBusy(false);
  }
}

async function rollbackCurrentTask() {
  if (!currentTask || !currentReceipt?.reversible) return;
  if (!window.confirm("Undo this receipt-owned action? Nexuss will delete only the unchanged note created by this task.")) return;
  setBusy(true);
  try {
    const response = await fetch(`/v1/tasks/${currentTask.task_id}/rollback`, {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({ confirmation: "undo" }),
    });
    if (!response.ok) throw new Error(`Undo failed (${response.status}): ${await response.text()}`);
    const task = await response.json();
    const receipt = await fetchReceipt(task.task_id);
    renderTask(task, receipt);
    addMessage("assistant", summarizeTask(task));
    showToast("Rollback verified. The managed note is absent.");
  } catch (error) {
    addMessage("assistant", error instanceof Error ? error.message : "Undo failed", true);
  } finally {
    setBusy(false);
  }
}

function usePrompt(prompt) {
  elements.input.value = prompt;
  elements.input.focus();
  elements.input.dispatchEvent(new Event("input"));
}

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => usePrompt(button.dataset.prompt || ""));
});

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab === button));
    document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
    document.querySelector(`#tab-${button.dataset.tab}`)?.classList.add("active");
  });
});

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const utterance = elements.input.value.trim();
  if (!utterance) return;
  const channel = lastInputChannel;
  lastInputChannel = "text";
  elements.input.value = "";
  elements.input.style.height = "auto";
  void executeInstruction(utterance, channel);
});

elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.form.requestSubmit();
  }
});

elements.input.addEventListener("input", () => {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 135)}px`;
});

elements.commandSearch.addEventListener("click", () => elements.input.focus());
elements.reviewApproval.addEventListener("click", () => currentTask?.approval && showApproval(currentTask.approval));
elements.approvalClose.addEventListener("click", hideApproval);
elements.reject.addEventListener("click", () => void decideApproval("reject"));
elements.approve.addEventListener("click", () => void decideApproval("approve"));
elements.rollback.addEventListener("click", () => void rollbackCurrentTask());
elements.copyPath.addEventListener("click", async () => {
  if (!currentNotePath) return;
  await navigator.clipboard.writeText(currentNotePath);
  showToast("Managed note path copied.");
});

elements.approvalOverlay.addEventListener("click", (event) => {
  if (event.target === elements.approvalOverlay) hideApproval();
});

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    elements.input.focus();
  }
  if (event.key === "Escape" && !elements.approvalOverlay.hidden) hideApproval();
});

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.lang = navigator.language || "en-US";
  recognition.continuous = false;
  recognition.interimResults = true;

  recognition.addEventListener("start", () => {
    elements.voice.classList.add("listening");
    elements.waveform.classList.add("active");
    elements.note.textContent = "Listening… speak naturally. You will review the transcript before execution.";
  });
  recognition.addEventListener("result", (event) => {
    let transcript = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) transcript += event.results[index][0].transcript;
    elements.input.value = transcript.trim();
    elements.input.dispatchEvent(new Event("input"));
    if (event.results[event.results.length - 1].isFinal) lastInputChannel = "voice";
  });
  recognition.addEventListener("end", () => {
    elements.voice.classList.remove("listening");
    elements.waveform.classList.remove("active");
    elements.note.textContent = "Voice transcript ready. Review it, then press Execute.";
  });
  recognition.addEventListener("error", (event) => {
    elements.voice.classList.remove("listening");
    elements.waveform.classList.remove("active");
    elements.note.textContent = `Voice input unavailable: ${event.error}. Text control remains active.`;
  });
  elements.voice.addEventListener("click", () => {
    try { recognition.start(); } catch (_error) { recognition.stop(); }
  });
} else {
  elements.voice.disabled = true;
  elements.note.textContent = "Voice recognition is unavailable in this browser. Text control remains active.";
}

void checkHealth();
setInterval(checkHealth, 30000);
elements.input.focus();

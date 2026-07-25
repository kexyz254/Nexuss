"use strict";

const elements = {
  form: document.querySelector("#command-form"),
  input: document.querySelector("#command-input"),
  send: document.querySelector("#send-button"),
  voice: document.querySelector("#voice-button"),
  note: document.querySelector("#composer-note"),
  timeline: document.querySelector("#timeline"),
  systemState: document.querySelector("#system-state"),
  systemStateLabel: document.querySelector("#system-state-label"),
  receiptState: document.querySelector("#receipt-state"),
  verificationBadge: document.querySelector("#verification-badge"),
  metricIntent: document.querySelector("#metric-intent"),
  metricConfidence: document.querySelector("#metric-confidence"),
  metricSteps: document.querySelector("#metric-steps"),
  metricState: document.querySelector("#metric-state"),
  policySummary: document.querySelector("#policy-summary"),
  planList: document.querySelector("#plan-list"),
  evidenceSummary: document.querySelector("#evidence-summary"),
  evidenceList: document.querySelector("#evidence-list"),
  receiptId: document.querySelector("#receipt-id"),
  sessionLabel: document.querySelector("#session-label"),
};

const sessionId = sessionStorage.getItem("nexuss-session-id") || crypto.randomUUID();
sessionStorage.setItem("nexuss-session-id", sessionId);
elements.sessionLabel.textContent = `Session ${sessionId.slice(0, 8)}`;

let lastInputChannel = "text";
let recognition = null;

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
  meta.textContent = role === "user" ? "You" : "Nexuss";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;

  content.append(meta, paragraph);
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

function createDetailCard(title, tag, attributes) {
  const card = document.createElement("div");
  card.className = "detail-card";
  const top = document.createElement("div");
  top.className = "topline";
  const heading = document.createElement("strong");
  heading.textContent = title;
  const badge = document.createElement("span");
  badge.className = "tag";
  badge.textContent = tag;
  top.append(heading, badge);
  card.append(top);

  const definition = document.createElement("dl");
  for (const [key, value] of Object.entries(attributes || {})) {
    const term = document.createElement("dt");
    term.textContent = titleCase(key);
    const description = document.createElement("dd");
    description.textContent = typeof value === "object" ? JSON.stringify(value) : String(value);
    definition.append(term, description);
  }
  card.append(definition);
  return card;
}

function renderTask(task, receipt) {
  elements.receiptState.textContent = titleCase(receipt.state);
  elements.metricIntent.textContent = titleCase(task.intent.kind);
  elements.metricConfidence.textContent = `${Math.round(task.intent.confidence * 100)}%`;
  elements.metricSteps.textContent = String(task.plan.steps.length);
  elements.metricState.textContent = titleCase(task.state);
  elements.receiptId.textContent = receipt.receipt_id;

  elements.verificationBadge.className = "verification-badge";
  if (receipt.verified) {
    elements.verificationBadge.classList.add("verified");
    elements.verificationBadge.textContent = "VERIFIED";
  } else {
    elements.verificationBadge.classList.add("failed");
    elements.verificationBadge.textContent = titleCase(task.state).toUpperCase();
  }

  elements.planList.className = "detail-list";
  elements.planList.replaceChildren();
  const decisions = new Map(task.policy_decisions.map((item) => [item.step_id, item]));
  let allowed = 0;
  for (const step of task.plan.steps) {
    const decision = decisions.get(step.step_id);
    if (decision?.outcome === "allow") allowed += 1;
    elements.planList.append(createDetailCard(
      `${step.order}. ${step.capability_id}`,
      decision?.outcome || "unknown",
      {
        risk: step.risk_tier,
        policy_reason: decision?.reason_code || "unavailable",
        expected_evidence: step.expected_evidence.join(", "),
      },
    ));
  }
  elements.policySummary.textContent = `${allowed}/${task.plan.steps.length} allowed`;

  elements.evidenceList.className = "detail-list";
  elements.evidenceList.replaceChildren();
  let evidenceCount = 0;
  for (const result of task.results) {
    if (!result.evidence.length) {
      elements.evidenceList.append(createDetailCard(
        result.capability_id,
        result.status,
        { error_code: result.error_code || "no evidence returned" },
      ));
      continue;
    }
    for (const record of result.evidence) {
      evidenceCount += 1;
      elements.evidenceList.append(createDetailCard(
        result.capability_id,
        result.status,
        { source: record.source, observed_at: record.observed_at, ...record.attributes },
      ));
    }
  }
  if (!task.results.length) {
    elements.evidenceList.className = "detail-list empty-state";
    elements.evidenceList.textContent = "Execution was not authorized, so no evidence was produced.";
  }
  elements.evidenceSummary.textContent = `${evidenceCount} record${evidenceCount === 1 ? "" : "s"}`;
}

function summarizeTask(task) {
  if (task.state === "completed") {
    const liveResult = task.results.find((result) => result.capability_id === "workspace.read_status");
    if (liveResult?.evidence?.[0]) {
      const data = liveResult.evidence[0].attributes;
      const cleanText = data.git_clean ? "clean" : `${data.git_changed_entries} changed entries`;
      return `Verified live workspace status. Branch ${data.git_branch} at ${String(data.git_commit).slice(0, 8)}; working tree ${cleanText}; ${Math.round(Number(data.disk_free_bytes) / 1073741824)} GB disk space free.`;
    }
    return `Completed and verified ${task.results.length} capability result${task.results.length === 1 ? "" : "s"}.`;
  }
  if (task.state === "awaiting_approval") return "The plan is ready, but policy requires explicit approval before execution.";
  if (task.state === "denied") return "The request was denied by the current Nexuss policy boundary.";
  return `The task ended in state: ${task.state}.`;
}

async function executeInstruction(utterance, channel = "text") {
  elements.send.disabled = true;
  elements.input.disabled = true;
  addMessage("user", utterance);
  addMessage("assistant", "Interpreting intent, evaluating policy, and collecting evidence…");

  const requestId = crypto.randomUUID();
  const payload = {
    request_id: requestId,
    channel,
    utterance,
    user_session_id: sessionId,
    target_devices: [],
    requested_at: new Date().toISOString(),
    client_context: { interface: "p2-web-ui", browser_voice: channel === "voice" },
  };

  try {
    const response = await fetch("/v1/tasks", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Nexuss-Session-ID": sessionId,
        "X-Nexuss-Session-Authenticated": "true",
      },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`Task request failed (${response.status}): ${detail}`);
    }
    const task = await response.json();
    const receiptResponse = await fetch(`/v1/tasks/${task.task_id}/receipt`, { cache: "no-store" });
    if (!receiptResponse.ok) throw new Error(`Receipt request failed (${receiptResponse.status})`);
    const receipt = await receiptResponse.json();
    renderTask(task, receipt);
    addMessage("assistant", summarizeTask(task));
  } catch (error) {
    addMessage("assistant", error instanceof Error ? error.message : "Unexpected Nexuss error", true);
  } finally {
    elements.send.disabled = false;
    elements.input.disabled = false;
    elements.input.focus();
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
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 140)}px`;
});

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.lang = navigator.language || "en-US";
  recognition.continuous = false;
  recognition.interimResults = true;

  recognition.addEventListener("start", () => {
    elements.voice.classList.add("listening");
    elements.note.textContent = "Listening… speak your instruction clearly.";
  });
  recognition.addEventListener("result", (event) => {
    let transcript = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      transcript += event.results[index][0].transcript;
    }
    elements.input.value = transcript.trim();
    elements.input.dispatchEvent(new Event("input"));
    if (event.results[event.results.length - 1].isFinal) lastInputChannel = "voice";
  });
  recognition.addEventListener("end", () => {
    elements.voice.classList.remove("listening");
    elements.note.textContent = "Voice transcript ready. Review it, then press Execute.";
  });
  recognition.addEventListener("error", (event) => {
    elements.voice.classList.remove("listening");
    elements.note.textContent = `Voice input unavailable: ${event.error}. You can continue with text.`;
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

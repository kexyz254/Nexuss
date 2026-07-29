/* Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary. */
"use strict";

const elements = {
  form: document.querySelector("#command-form"),
  input: document.querySelector("#command-input"),
  send: document.querySelector("#send-button"),
  voice: document.querySelector("#voice-button"),
  voiceBadge: document.querySelector("#voice-badge"),
  voiceState: document.querySelector("#voice-state"),
  voiceStop: document.querySelector("#voice-stop"),
  voiceReplies: document.querySelector("#voice-replies"),
  voiceRate: document.querySelector("#voice-rate"),
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
  approvalDialog: document.querySelector(".approval-dialog"),
  approvalClose: document.querySelector("#approval-close"),
  approvalAction: document.querySelector("#approval-action"),
  approvalRisk: document.querySelector("#approval-risk"),
  approvalDestination: document.querySelector("#approval-destination"),
  approvalReversible: document.querySelector("#approval-reversible"),
  approvalSummary: document.querySelector("#approval-summary"),
  approvalHash: document.querySelector("#approval-hash"),
  approvalPreview: document.querySelector("#approval-preview"),
  approvalExpiry: document.querySelector("#approval-expiry"),
  phonePanel: document.querySelector("#phone-approval-panel"),
  phonePairingCode: document.querySelector("#phone-pairing-code"),
  phoneMobileUrl: document.querySelector("#phone-mobile-url"),
  phoneApprovalStatus: document.querySelector("#phone-approval-status"),
  copyPairing: document.querySelector("#copy-pairing-button"),
  reject: document.querySelector("#reject-button"),
  approve: document.querySelector("#approve-button"),
  toast: document.querySelector("#toast"),
  archiveAttach: document.querySelector("#archive-attach-button"),
  archiveInput: document.querySelector("#archive-input"),
  archiveAttachment: document.querySelector("#archive-attachment"),
  archiveAttachmentName: document.querySelector("#archive-attachment-name"),
  archiveAttachmentMeta: document.querySelector("#archive-attachment-meta"),
  archiveRemove: document.querySelector("#archive-remove-button"),
};

/*
 * The desktop session identity binds paired phones to this browser. It must
 * outlive the tab: sessionStorage is cleared on close, which silently orphans
 * every paired phone because handoffs are filed under the session that
 * created them.
 */
const sessionId = localStorage.getItem("nexuss-session-id") || crypto.randomUUID();
localStorage.setItem("nexuss-session-id", sessionId);
elements.sessionLabel.textContent = `Session ${sessionId.slice(0, 8)}`;

/*
 * Heal any phone that was paired against a previous desktop identity. Without
 * this the phone stays "Paired" while every poll returns an empty list.
 */
void fetch("/v1/mobile/devices/rebind", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-Nexuss-Session-ID": sessionId,
    "X-Nexuss-Session-Authenticated": "true",
  },
}).catch(() => {
  /* Core not up yet; the next task submission surfaces the real error. */
});

let lastInputChannel = "text";
let recognition = null;
let currentTask = null;
let currentReceipt = null;
let currentNotePath = null;
let toastTimer = null;
let pairingChallenge = null;
let taskPollTimer = null;
let selectedArchive = null;

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
  elements.archiveAttach.disabled = busy;
  elements.archiveRemove.disabled = busy;
}


function formatArchiveBytes(value) {
  if (!Number.isFinite(value) || value < 0) return "Unknown size";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function clearArchiveAttachment() {
  selectedArchive = null;
  elements.archiveInput.value = "";
  elements.archiveAttachment.hidden = true;
  elements.archiveAttach.classList.remove("active");
  elements.archiveAttachmentName.textContent = "No archive selected";
  elements.archiveAttachmentMeta.textContent = "Secure local intake";
  elements.note.textContent = "Voice transcripts are reviewable before execution.";
}

function selectArchiveAttachment(file) {
  if (!file) {
    clearArchiveAttachment();
    return;
  }
  if (!file.name.toLowerCase().endsWith(".zip")) {
    clearArchiveAttachment();
    throw new Error("Select a .zip archive.");
  }
  if (file.size <= 0) {
    clearArchiveAttachment();
    throw new Error("The selected ZIP is empty.");
  }
  if (file.size > 50_000_000) {
    clearArchiveAttachment();
    throw new Error("The selected ZIP exceeds the 50 MB intake limit.");
  }
  selectedArchive = file;
  elements.archiveAttachment.hidden = false;
  elements.archiveAttach.classList.add("active");
  elements.archiveAttachmentName.textContent = file.name;
  elements.archiveAttachmentMeta.textContent = `${formatArchiveBytes(file.size)} · quarantined before GitHub`;
  elements.note.textContent = "ZIP attached · two paired-phone approvals required.";
}

function repositoryNameFromInstruction(utterance) {
  const match = utterance.match(
    /\b(?:repository|repo)\s+(?:named|called)\s+["'`]?([A-Za-z0-9._-]{1,100})["'`]?/i,
  );
  return match?.[1] || "";
}

function archiveApiHeaders(requestId, repositoryName, archiveName) {
  return {
    "Content-Type": "application/zip",
    "X-Nexuss-Session-ID": sessionId,
    "X-Nexuss-Session-Authenticated": "true",
    "X-Nexuss-Request-ID": requestId,
    "X-Nexuss-Repository-Name": repositoryName,
    "X-Nexuss-Archive-Name": encodeURIComponent(archiveName),
  };
}

async function hasPairedPhone() {
  try {
    const response = await fetch("/v1/mobile/devices", {
      headers: apiHeaders(),
      cache: "no-store",
    });
    if (!response.ok) return false;
    const devices = await response.json();
    return Array.isArray(devices) && devices.length > 0;
  } catch (_error) {
    return false;
  }
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

/*
 * Only a verified final answer is spoken. Progress notices and error toasts
 * are deliberately silent: speaking every intermediate step turns the room
 * into a status feed, and speaking failures aloud is rarely what a person in
 * a shared space wants.
 */
function addMessage(role, text, isError = false, options = {}) {
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

  /*
   * An answer is either a plain string or a structured object. Content
   * capabilities return structure so their results render as readable answers
   * in the conversation rather than collapsing into one sentence, or being
   * visible only as raw evidence in the inspector.
   */
  const answer = typeof text === "string" ? { text, blocks: [] } : text;

  const paragraph = document.createElement("p");
  paragraph.textContent = answer.text;
  bubble.append(paragraph);

  for (const block of answer.blocks || []) {
    const rendered = renderAnswerBlock(block);
    if (rendered) bubble.append(rendered);
  }

  content.append(meta, bubble);

  if (role === "assistant" && !isError && options.speak) {
    speakAnswer(answer);
  }
  article.append(avatar, content);
  elements.timeline.append(article);
  elements.timeline.scrollTop = elements.timeline.scrollHeight;
}

/*
 * Answer blocks. Adding a new content capability means adding a builder in
 * contentAnswer() and, if it needs a new shape, one case here. Nothing else
 * in the conversation pipeline changes.
 */
function renderAnswerBlock(block) {
  if (block.type === "constitution") {
    return renderConstitutionBlock(block);
  }
  if (block.type === "claims") return renderClaimBlock(block);
  if (block.type === "note") {
    const note = document.createElement("p");
    note.className = "answer-note";
    note.textContent = block.text;
    return note;
  }
  return null;
}

function renderConstitutionBlock(block) {
  const card = document.createElement("section");
  card.className = "constitution-card";

  const heading = document.createElement("div");
  heading.className = "constitution-card-heading";

  const title = document.createElement("strong");
  title.textContent = "NEXUSS CONSTITUTION";

  const status = document.createElement("span");
  status.className = "constitution-status";
  status.textContent = block.integrity_verified
    ? `Active ? v${block.version} ? integrity verified`
    : `v${block.version} ? integrity unverified`;

  heading.append(title, status);

  const rule = document.createElement("p");
  rule.className = "constitution-rule";
  rule.textContent = block.rule_applied;

  const digest = document.createElement("code");
  digest.className = "constitution-digest";
  digest.textContent = `SHA-256 ${String(block.sha256).slice(0, 16)}?`;
  digest.title = String(block.sha256);

  const authority = document.createElement("p");
  authority.className = "constitution-authority";
  authority.textContent = block.grants_authority
    ? "This response changes authority."
    : "Informational only ? grants no authority";

  card.append(heading, rule, digest, authority);
  return card;
}


/** Turn a source reference into something a person can read at a glance. */
function sourceLabel(sourceRef) {
  const value = String(sourceRef || "").trim();
  if (!value || value === "user") return "you told me";

  /*
   * Only http(s) is treated as a URL. A Windows path such as
   * "C:\\Docs\\lease.pdf" is a *valid* URL whose scheme is "c:" and whose
   * hostname is empty, which silently produced a blank label.
   */
  if (/^https?:\/\//i.test(value)) {
    try {
      return new URL(value).hostname.replace(/^www\./, "") || value;
    } catch {
      return value;
    }
  }

  const segments = value.split(/[\\/]/).filter(Boolean);
  return segments[segments.length - 1] || value;
}

function renderClaimBlock(block) {
  const list = document.createElement("ul");
  list.className = "answer-claims";

  for (const item of block.items) {
    const entry = document.createElement("li");
    entry.className = "answer-claim";

    const statement = document.createElement("p");
    statement.className = "answer-claim-statement";
    statement.textContent = item.statement;

    const meta = document.createElement("div");
    meta.className = "answer-claim-meta";

    const trust = document.createElement("span");
    trust.className = `trust-chip trust-${item.source_trust}`;
    trust.textContent = item.source_trust.replace(/_/g, " ");

    const origin = document.createElement("span");
    origin.className = "answer-claim-source";
    origin.textContent = sourceLabel(item.source_ref);

    const confidence = document.createElement("span");
    confidence.className = "answer-claim-confidence";
    const percentage = Math.round(Number(item.confidence) * 100);
    confidence.textContent = `${percentage}% confidence`;
    confidence.title = "Confidence after time decay for this claim's volatility";

    meta.append(trust, origin, confidence);
    entry.append(statement, meta);
    list.append(entry);
  }
  return list;
}

/* Plain-language readings of the error codes a person can act on. */
const FAILURE_EXPLANATIONS = {
  GITHUB_NOT_CONNECTED: "Connect and verify GitHub before requesting this operation.",
  GITHUB_REAUTH_REQUIRED: "The GitHub authorization expired or was revoked. Reconnect GitHub.",
  GITHUB_ACCOUNT_MISMATCH: "The live GitHub account no longer matches the approved account.",
  GITHUB_REPOSITORY_ALREADY_EXISTS: "A repository with that exact name already exists. No change was made.",
  GITHUB_PERMISSION_INSUFFICIENT: "The GitHub App lacks the required permission.",
  GITHUB_RATE_LIMITED: "GitHub rate-limited the connector. No write was repeated.",
  GITHUB_APPROVAL_CONTEXT_MISSING: "A valid phone approval was not attached to this GitHub write.",
  GITHUB_PREPARED_PAYLOAD_MISMATCH: "The GitHub payload changed after approval, so I refused it.",
  GITHUB_CREATION_NOT_VERIFIED: "The created repository did not satisfy the approved contract.",
  INTELLIGENCE_NO_EVIDENCE: "I could not find sufficiently relevant public evidence for that question. Try asking with a shorter or more specific topic.",
  INTELLIGENCE_RETRIEVER_FORBIDDEN: "The public knowledge provider refused this request, so I stopped without presenting an unverified answer.",
  INTELLIGENCE_RETRIEVER_UNAVAILABLE: "The public knowledge provider is temporarily unavailable. I stopped rather than inventing an answer.",
  MEMORY_STATEMENT_AMBIGUOUS: "Tell me the exact fact to remember. Words such as \"that\" or \"this\" are too ambiguous.",
  CONSTITUTION_UNAVAILABLE:
    "The Nexuss Constitution could not be loaded or its integrity could not be verified.",
  MEMORY_WRITE_REFUSED_CREDENTIAL_SHAPED:
    "That text looks like a credential, so I refused to store it. Secrets never enter memory.",
  MEMORY_TOPIC_CEILING_REACHED:
    "That topic already holds as many claims as I allow. Forget some of it first.",
  MEMORY_STORE_NOT_CONFIGURED: "Memory is not configured on this Nexuss instance.",
  MEMORY_STATEMENT_MISSING: "I could not find a statement to remember in that.",
  MEMORY_QUERY_MISSING: "I could not work out what to search memory for.",
  MEMORY_TOPIC_MISSING: "I could not work out which topic to forget.",
  NO_PAIRED_DEVICE: "No phone is paired, so there was nothing to act on.",
  PAIRED_DEVICE_NOT_FOUND: "No paired phone matches that name.",
  PAIRED_DEVICE_AMBIGUOUS:
    "Several phones are paired and you did not say which one, so I changed nothing.",
  MOBILE_PAIRING_GATEWAY_NOT_CONFIGURED: "Phone pairing is not available on this instance.",
  KNOWLEDGE_PROVIDER_FORBIDDEN:
    "The public knowledge source refused the request, so I stopped without producing unsupported material.",
  KNOWLEDGE_PROVIDER_UNAVAILABLE:
    "The public knowledge source did not respond, so I have no cited material to give you.",
  KNOWLEDGE_NO_RESULTS:
    "The public knowledge source returned nothing for that query. Try naming the topic more directly.",
};

function failureExplanation(code) {
  return FAILURE_EXPLANATIONS[code]
    || `The capability reported ${code}, and I did not act on a result I could not verify.`;
}

function evidenceFor(task, capabilityId) {
  const result = task.results.find((item) => item.capability_id === capabilityId);
  return result?.evidence?.[0]?.attributes || null;
}

/*
 * Content capabilities answer in the conversation. Each returns a structured
 * answer; anything that needs provenance carries it in the blocks so a claim
 * and its source are never separated.
 */
function contentAnswer(task) {
  const converse = evidenceFor(task, "assistant.converse");
  if (converse) {
    return { text: String(converse.reply), blocks: [] };
  }

  const githubStatus = evidenceFor(task, "github.connection.status");
  if (githubStatus) {
    const account = githubStatus.account_login
      ? ` as ${githubStatus.account_login}`
      : "";
    return {
      text: `GitHub connector status: ${githubStatus.status}${account}.`,
      blocks: [{
        type: "note",
        text: githubStatus.identity_verified
          ? "The live identity is verified. Credentials remain encrypted and are excluded from receipts."
          : String(githubStatus.detail || "GitHub is not connected."),
      }],
    };
  }

  const githubRepositories = evidenceFor(task, "github.repositories.list");
  if (githubRepositories) {
    const repositories = Array.isArray(githubRepositories.repositories)
      ? githubRepositories.repositories
      : [];
    return {
      text: `Verified ${githubRepositories.total} repositories for ${githubRepositories.account_login}: ${githubRepositories.private_count} private and ${githubRepositories.public_count} public.`,
      blocks: [{
        type: "note",
        text: repositories.slice(0, 12).map(
          (repo) => `${repo.full_name} · ${repo.private ? "private" : "public"}`,
        ).join("\n"),
      }],
    };
  }

  const githubPublished = evidenceFor(task, "github.repository.publish_archive");
  if (githubPublished) {
    return {
      text: `Published and independently verified ${githubPublished.file_count} files in ${githubPublished.full_name}:${githubPublished.branch}.`,
      blocks: [{
        type: "note",
        text: `Initial commit ${githubPublished.commit_sha}\nTree ${githubPublished.tree_sha}\nArchive ${githubPublished.archive_sha256}\nManifest ${githubPublished.manifest_sha256}`,
      }],
    };
  }

  const githubCreated = evidenceFor(task, "github.repository.create");
  if (githubCreated) {
    return {
      text: task.state === "awaiting_approval"
        ? `Created and verified ${githubCreated.full_name}. The repository is still empty and the exact ZIP manifest now requires a second phone approval.`
        : `Created and independently verified ${githubCreated.full_name}.`,
      blocks: [{
        type: "note",
        text: `Private: ${githubCreated.private_verified ? "verified" : "not verified"} · Empty repository: ${githubCreated.empty_repository_verified ? "verified" : "not verified"} · Initial commit: none`,
      }],
    };
  }

  const answered = evidenceFor(task, "knowledge.answer");
  if (answered) {
    if (answered.answer_path === "memory") {
      const matches = Array.isArray(answered.matches) ? answered.matches : [];
      return {
        text: "From what you have told me:",
        blocks: [{ type: "claims", items: matches }],
      };
    }
    const sources = Array.isArray(answered.sources) ? answered.sources : [];
    return {
      text: String(answered.brief || "I found sources but no usable summary."),
      blocks: [
        {
          type: "claims",
          items: sources.slice(0, 3).map((source) => ({
            statement: String(source.title),
            source_ref: String(source.url),
            source_trust: "public_web",
            confidence: 0.6,
          })),
        },
        {
          type: "note",
          text: "I had nothing stored about this, so I read public sources. Say \u201cremember that\u2026\u201d to keep any of it.",
        },
      ],
    };
  }

  const recall = evidenceFor(task, "memory.recall");
  if (recall) {
    const matches = Array.isArray(recall.matches) ? recall.matches : [];
    if (!matches.length) {
      return {
        text: `I don't have anything stored about "${recall.query}".`,
        blocks: [{
          type: "note",
          text: "Tell me something starting with \u201cremember that\u2026\u201d and I'll keep it with its source.",
        }],
      };
    }
    const count = matches.length;
    return {
      text: `Here ${count === 1 ? "is" : "are"} ${count} thing${count === 1 ? "" : "s"} I remember about \u201c${recall.query}\u201d:`,
      blocks: [{ type: "claims", items: matches }],
    };
  }

  const stored = evidenceFor(task, "memory.remember");
  if (stored) {
    return {
      text: "Stored. I'll remember that.",
      blocks: [{
        type: "note",
        text: `Filed under \u201c${stored.topic}\u201d as ${String(stored.source_trust).replace(/_/g, " ")}.`,
      }],
    };
  }

  const forgotten = evidenceFor(task, "memory.forget");
  if (forgotten) {
    const removed = Number(forgotten.claims_removed);
    return {
      text: removed === 0
        ? `I had nothing stored about \u201c${forgotten.topic}\u201d.`
        : `Forgotten. I removed ${removed} claim${removed === 1 ? "" : "s"} about \u201c${forgotten.topic}\u201d.`,
      blocks: [],
    };
  }

  const devices = evidenceFor(task, "device.list_phones");
  if (devices) {
    const listed = Array.isArray(devices.devices) ? devices.devices : [];
    if (!listed.length) {
      return { text: "No phones are paired right now.", blocks: [] };
    }
    return {
      text: `${listed.length} paired phone${listed.length === 1 ? "" : "s"}:`,
      blocks: [{
        type: "claims",
        items: listed.map((device) => ({
          statement: device.device_label,
          source_ref: "user",
          source_trust: "user_asserted",
          confidence: 1,
        })),
      }],
    };
  }

  const pairing = evidenceFor(task, "device.pair_phone");
  if (pairing) {
    return {
      text: `Pairing code ${pairing.pairing_code}. Enter it at ${pairing.mobile_url} within ten minutes.`,
      blocks: [{
        type: "note",
        text: "Asking again issues a new code and retires this one.",
      }],
    };
  }

  return null;
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
  window.NexussP5?.renderTask(task, receipt);
}

function assistantResponse(task) {
  const result = task.results.find(
    (item) => item.capability_id === "assistant.respond",
  );
  const attributes = result?.evidence?.[0]?.attributes;

  if (!attributes?.response) return null;

  if (
    attributes.authority_source !== "nexuss_constitution"
  ) {
    return String(attributes.response);
  }

  return {
    text: String(attributes.response),
    blocks: [{
      type: "constitution",
      version: attributes.constitution_version,
      sha256: attributes.constitution_sha256,
      integrity_verified: attributes.integrity_verified,
      rule_applied: attributes.rule_applied,
      grants_authority: attributes.grants_authority,
    }],
  };
}

function summarizeTask(task) {
  const p5Summary = window.NexussP5?.summarizeTask(task);
  if (p5Summary) return p5Summary;
  const conversational = assistantResponse(task);
  if (conversational) return conversational;

  const content = contentAnswer(task);
  if (content) return content;

  if (task.state === "completed") {
    const deviceResult = task.results.find((result) => result.capability_id === "device.launch_notepad");
    if (deviceResult?.evidence?.[0]) {
      const data = deviceResult.evidence[0].attributes;
      return `Phone approval verified. ${data.executable} was launched on trusted node ${data.node_id} as process ${data.process_id}, and the Action Receipt can close only that receipt-bound process.`;
    }
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
    if (
      task.approval?.capability_id === "github.repository.create"
    ) {
      return "I prepared an exact GitHub repository payload. No repository exists yet. Approve or reject the account, name, visibility, initialization settings, and hashes on your paired phone.";
    }
    if (task.approval?.approval_channel === "phone") {
      return "I prepared a signed trusted-device command. No command has executed. Pair your phone and approve the exact payload there.";
    }
    return "I prepared a controlled write action. No file has been created. Review the exact payload and approve or cancel it.";
  }
  if (task.state === "rolled_back") {
    const deviceRollback = task.results.some((result) => result.capability_id === "device.rollback_launch_notepad");
    return deviceRollback
      ? "Undo completed. The receipt-bound device process was terminated and verified absent."
      : "Undo completed. The receipt-owned note was removed and its absence was verified.";
  }
  if (task.state === "denied") {
    const reason = task.policy_decisions.find((decision) => decision.outcome === "deny")?.reason_code;
    return `The request was denied by policy${reason ? `: ${reason}` : ""}.`;
  }
  if (task.state === "failed") {
    /*
     * Name the reason. "Review the evidence panel" makes the person do the
     * diagnosis the system already did, and hides whether the cause was a
     * provider error, a validation refusal, or a missing dependency.
     */
    const failure = task.results.find((result) => result.error_code);
    if (failure) {
      return {
        text: `I stopped without acting. ${failureExplanation(String(failure.error_code))}`,
        blocks: [{ type: "note", text: `Capability ${failure.capability_id} reported ${failure.error_code}.` }],
      };
    }
    return "The action failed closed, and no capability recorded a reason. The lifecycle panel has the event trail.";
  }
  return `The task is currently ${titleCase(task.state)}.`;
}

async function fetchReceipt(taskId) {
  const response = await fetch(`/v1/tasks/${taskId}/receipt`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Receipt request failed (${response.status})`);
  return response.json();
}

async function createPhonePairing() {
  const response = await fetch("/v1/mobile/pairing", {
    method: "POST",
    headers: apiHeaders(),
    body: "{}",
  });
  if (!response.ok) throw new Error(`Phone pairing failed (${response.status})`);
  pairingChallenge = await response.json();
  elements.phonePairingCode.textContent = pairingChallenge.pairing_code;
  elements.phoneMobileUrl.href = pairingChallenge.mobile_url;
  elements.phoneMobileUrl.textContent = pairingChallenge.mobile_url;
  elements.phoneApprovalStatus.textContent = `Pairing code expires ${new Date(pairingChallenge.expires_at).toLocaleTimeString()}. Waiting for phone approval…`;
}

async function pollTaskUntilResolved(taskId) {
  if (taskPollTimer) clearInterval(taskPollTimer);
  taskPollTimer = setInterval(async () => {
    try {
      const response = await fetch(`/v1/tasks/${taskId}`, { cache: "no-store" });
      if (!response.ok) return;
      const task = await response.json();
      const previousApprovalId = currentTask?.approval?.approval_id || null;

      if (task.state === "awaiting_approval") {
        const nextApprovalId = task.approval?.approval_id || null;
        if (nextApprovalId && nextApprovalId !== previousApprovalId) {
          const receipt = await fetchReceipt(task.task_id);
          hideApproval();
          renderTask(task, receipt);
          addMessage("assistant", summarizeTask(task), false, { speak: true });
          await showApproval(task.approval);
          showToast("Phase one verified. Review phase two on your paired phone.");
        }
        return;
      }

      clearInterval(taskPollTimer);
      taskPollTimer = null;
      const receipt = await fetchReceipt(task.task_id);
      hideApproval();
      renderTask(task, receipt);
      addMessage("assistant", summarizeTask(task), false, { speak: true });
      showToast(
        task.state === "completed"
          ? "Phone-approved operation completed and independently verified."
          : `Phone decision: ${titleCase(task.state)}.`,
      );
    } catch (_error) {
      // Health polling and the phone client remain the source of truth during transient errors.
    }
  }, 1200);
}

async function showApproval(approval) {
  elements.approvalAction.textContent = approval.action_title;
  elements.approvalRisk.textContent = titleCase(approval.risk_tier);
  elements.approvalDestination.textContent = approval.destination_label;
  elements.approvalReversible.textContent = approval.reversible ? "Yes · receipt-bound" : "No";
  elements.approvalSummary.textContent = approval.action_summary;
  elements.approvalHash.textContent = approval.payload_sha256;
  elements.approvalPreview.textContent = approval.exact_preview;
  elements.approvalExpiry.textContent = `Approval expires ${new Date(approval.expires_at).toLocaleTimeString()}. The token is single-use and payload-bound.`;
  const phoneRequired = approval.approval_channel === "phone";
  elements.approvalDialog.classList.toggle("phone-required", phoneRequired);
  elements.phonePanel.hidden = !phoneRequired;
  elements.approve.hidden = phoneRequired;
  elements.approvalOverlay.hidden = false;
  if (phoneRequired) {
    elements.phonePairingCode.textContent = "--------";
    elements.phoneApprovalStatus.textContent = "Checking the paired-phone trust anchor…";
    try {
      if (await hasPairedPhone()) {
        elements.phoneApprovalStatus.textContent = "Paired phone ready. Review the exact payload on the phone.";
        elements.phoneMobileUrl.href = "/mobile";
        elements.phoneMobileUrl.textContent = "/mobile";
      } else {
        await createPhonePairing();
      }
      void pollTaskUntilResolved(approval.task_id);
    } catch (error) {
      elements.phoneApprovalStatus.textContent = error instanceof Error ? error.message : "Phone pairing unavailable";
    }
    elements.reject.focus();
  } else {
    elements.approve.focus();
  }
}

function hideApproval() {
  elements.approvalOverlay.hidden = true;
  elements.approvalDialog.classList.remove("phone-required");
  elements.phonePanel.hidden = true;
  elements.approve.hidden = false;
  elements.input.focus();
}


async function executeArchiveInstruction(utterance) {
  if (!selectedArchive) throw new Error("Attach a ZIP archive first.");
  const repositoryName = repositoryNameFromInstruction(utterance);
  if (!repositoryName) {
    throw new Error(
      'Name the repository explicitly, for example: "create a private repository named fenril-task and deploy this ZIP."',
    );
  }

  const archive = selectedArchive;
  const requestId = crypto.randomUUID();
  setBusy(true);
  addMessage("user", utterance);
  stopSpeaking();
  addMessage(
    "assistant",
    `Quarantining ${archive.name}, scanning paths and secrets, and preparing a two-phase GitHub approval…`,
  );

  try {
    const response = await fetch("/v1/archive-imports", {
      method: "POST",
      headers: archiveApiHeaders(requestId, repositoryName, archive.name),
      body: archive,
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`Archive intake failed (${response.status}): ${detail}`);
    }
    const task = await response.json();
    clearArchiveAttachment();
    const receipt = await fetchReceipt(task.task_id);
    renderTask(task, receipt);
    addMessage("assistant", summarizeTask(task), false, { speak: true });
    if (task.state === "awaiting_approval" && task.approval) {
      await showApproval(task.approval);
    }
  } catch (error) {
    addMessage(
      "assistant",
      error instanceof Error ? error.message : "Unexpected archive intake error",
      true,
    );
  } finally {
    setBusy(false);
    elements.input.focus();
  }
}

async function executeInstruction(utterance, channel = "text") {
  setBusy(true);
  addMessage("user", utterance);
  stopSpeaking();
  addMessage("assistant", "Interpreting intent, generating a capability plan, and evaluating policy…");

  const payload = {
    request_id: crypto.randomUUID(),
    channel,
    utterance,
    user_session_id: sessionId,
    target_devices: [],
    requested_at: new Date().toISOString(),
    client_context: {
      interface: "p5-web-ui",
      browser_voice: channel === "voice",
      // Recorded on the task so a receipt shows how the instruction arrived
      // and that recognition never left this machine.
      voice_recognition: channel === "voice" ? "on_device" : "none",
    },
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
    addMessage("assistant", summarizeTask(task), false, { speak: true });
    if (task.state === "awaiting_approval" && task.approval) void showApproval(task.approval);
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
    addMessage("assistant", summarizeTask(task), false, { speak: true });
    showToast(decisionKind === "approve" ? "Exact action approved and verified." : "Action cancelled. No write occurred.");
  } catch (error) {
    addMessage("assistant", error instanceof Error ? error.message : "Approval failed", true);
  } finally {
    setBusy(false);
  }
}

async function rollbackCurrentTask() {
  if (!currentTask || !currentReceipt?.reversible) return;
  if (!window.confirm("Undo this receipt-owned action? Nexuss will reverse only the verified file or process created by this task.")) return;
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
    addMessage("assistant", summarizeTask(task), false, { speak: true });
    showToast("Rollback verified. The receipt-bound action is absent.");
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

  if (selectedArchive) {
    void executeArchiveInstruction(utterance);
    return;
  }

  const contextualResponse = window.NexussP5?.handleContextCommand?.(utterance);
  if (contextualResponse) {
    addMessage("user", utterance);
    addMessage("assistant", contextualResponse);
    elements.input.focus();
    return;
  }

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
elements.archiveAttach.addEventListener("click", () => elements.archiveInput.click());
elements.archiveInput.addEventListener("change", () => {
  try {
    selectArchiveAttachment(elements.archiveInput.files?.[0] || null);
    if (selectedArchive) {
      elements.input.placeholder = "Example: Create a private repository named fenril-task and deploy this ZIP.";
      elements.input.focus();
    }
  } catch (error) {
    addMessage("assistant", error instanceof Error ? error.message : "ZIP attachment failed", true);
  }
});
elements.archiveRemove.addEventListener("click", () => {
  clearArchiveAttachment();
  elements.input.placeholder = "Type or speak an instruction…";
  elements.input.focus();
});
elements.copyPath.addEventListener("click", async () => {
  if (!currentNotePath) return;
  await navigator.clipboard.writeText(currentNotePath);
  showToast("Managed note path copied.");
});
elements.copyPairing.addEventListener("click", async () => {
  if (!pairingChallenge?.pairing_code) return;
  await navigator.clipboard.writeText(pairingChallenge.pairing_code);
  showToast("Phone pairing code copied.");
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

/* =========================================================================
 * P6.0 Local-first voice.
 *
 * Recognition order: explicit browser on-device, then fail closed. There is
 * no cloud path. Note that the canonical MDN example sets
 * processLocally = false when the language pack is missing, which silently
 * routes audio to the browser vendor -- exactly the behaviour Nexuss forbids.
 * ========================================================================= */

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const SpeechSynthesis = window.speechSynthesis;

const VOICE_LANGUAGE = navigator.language || "en-US";
const VOICE_QUALITY = "dictation";

/** Explicit states, so the person always knows what the microphone is doing. */
const VoiceState = {
  IDLE: "idle",
  REQUESTING: "requesting permission",
  LISTENING: "listening locally",
  PROCESSING: "processing locally",
  TRANSCRIPT_READY: "transcript ready",
  EXECUTING: "executing",
  SPEAKING: "speaking",
  UNAVAILABLE: "unavailable",
  PERMISSION_DENIED: "permission denied",
};

let voiceState = VoiceState.IDLE;
let onDeviceReady = false;
let voiceOptions = { langs: [VOICE_LANGUAGE], processLocally: true, quality: VOICE_QUALITY };
let speakRepliesEnabled = true;

/*
 * Utterances that are safe to submit without a review press. Conservative by
 * design: anything not clearly interrogative goes to review, so "call James"
 * and "delete the note" can never auto-run. Recording has always ended before
 * this is consulted, and policy still gates every capability regardless.
 */
const QUESTION_OPENERS = /^(who|what|when|where|why|how|which|is|are|was|were|do|does|did|can|could|should|would|will)\b/i;

function looksLikeQuestion(transcript) {
  const text = String(transcript || "").trim();
  if (!text) return false;
  if (text.endsWith("?")) return true;
  return QUESTION_OPENERS.test(text);
}

/*
 * Speech is a broadcast channel: anyone in the room hears it. Identifiers that
 * are meaningful to an attacker are never spoken, even when they appear in a
 * conversational answer.
 */
function redactForSpeech(text) {
  // Order matters: the specific shapes must match before the generic digit
  // rule, or a phone number is consumed as "a code" and loses its meaning.
  return String(text || "")
    .replace(/https?:\/\/\S+/gi, "a link")
    .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, "an identifier")
    .replace(/\+\d[\d\s\-()]{7,}\d/g, "a phone number")
    .replace(/\b[0-9a-f]{16,}\b/gi, "a digest")
    .replace(/\b\d{6,}\b/g, "a code")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/**
 * Assemble what Nexuss says aloud: the conversational answer and any recalled
 * statements, never the provenance metadata, scores or receipt material that
 * belongs in the inspector.
 */
function speechTextFor(answer) {
  if (typeof answer === "string") return redactForSpeech(answer);
  const parts = [answer.text];
  for (const block of answer.blocks || []) {
    if (block.type === "claims") {
      for (const item of block.items) parts.push(item.statement);
    } else if (block.type === "note") {
      parts.push(block.text);
    }
  }
  return redactForSpeech(parts.filter(Boolean).join(". "));
}

function setVoiceState(state, note) {
  voiceState = state;
  const listening = state === VoiceState.LISTENING;
  elements.voice.classList.toggle("listening", listening);
  elements.waveform.classList.toggle("active", listening);
  elements.voice.setAttribute("aria-label", listening ? "Stop voice input" : "Start voice input");
  if (elements.voiceState) elements.voiceState.textContent = state;
  if (note) elements.note.textContent = note;
}

function setVoiceBadge(available, detail) {
  if (!elements.voiceBadge) return;
  elements.voiceBadge.classList.toggle("voice-local", available);
  elements.voiceBadge.classList.toggle("voice-blocked", !available);
  elements.voiceBadge.textContent = available
    ? "Voice · on-device · audio remains local"
    : `Voice unavailable · ${detail}`;
}

function disableVoice(detail) {
  onDeviceReady = false;
  elements.voice.disabled = true;
  setVoiceState(VoiceState.UNAVAILABLE);
  setVoiceBadge(false, detail);
  elements.note.textContent = `${detail} Type your request instead.`;
}

/**
 * Probe for on-device support and fail closed.
 *
 * A browser without the on-device statics only offers server-based
 * recognition, so it is treated as unavailable rather than downgraded.
 */
async function initialiseVoice() {
  if (!SpeechRecognition) {
    disableVoice("This browser has no speech recognition.");
    return;
  }
  if (typeof SpeechRecognition.available !== "function") {
    disableVoice("This browser cannot recognise speech on-device, and Nexuss will not send audio to a cloud service.");
    return;
  }

  /*
   * Probe several configurations rather than one. A machine may carry a pack
   * for the base language but not the regional tag, or for standard but not
   * dictation quality. Reporting "unavailable" after a single narrow request
   * pushes the diagnosis onto the person, which needs developer tools they
   * should not have to open.
   */
  const probes = [];
  const base = VOICE_LANGUAGE.split("-")[0];
  for (const langs of [[VOICE_LANGUAGE], [base], ["en-US"]]) {
    probes.push({ langs, processLocally: true, quality: VOICE_QUALITY });
    probes.push({ langs, processLocally: true });
  }

  let installable = null;
  for (const options of probes) {
    let status;
    try {
      status = await SpeechRecognition.available(options);
    } catch (error) {
      disableVoice("On-device speech recognition is blocked by policy on this page.");
      return;
    }
    if (status === "available") {
      voiceOptions = options;
      onDeviceReady = true;
      elements.voice.disabled = false;
      setVoiceBadge(true);
      setVoiceState(VoiceState.IDLE, `Voice ready. Recognition runs on this device (${options.langs[0]}).`);
      return;
    }
    if (!installable && (status === "downloadable" || status === "downloading")) {
      installable = options;
    }
  }

  if (installable) {
    voiceOptions = installable;
    setVoiceBadge(false, `language pack for ${installable.langs[0]} not installed yet`);
    elements.voice.disabled = false;
    elements.note.textContent = `Press the microphone to install the on-device ${installable.langs[0]} language pack. No audio leaves this machine.`;
    onDeviceReady = false;
    return;
  }

  disableVoice(
    `This browser reports no on-device language pack for ${VOICE_LANGUAGE}, ${base} or en-US. ` +
    "Chrome 139 or later is required, and Nexuss will not use cloud recognition."
  );
}

async function ensureLanguagePack() {
  setVoiceState(VoiceState.REQUESTING, "Installing the on-device language pack…");
  let installed = false;
  try {
    installed = await SpeechRecognition.install(voiceOptions);
  } catch (error) {
    installed = false;
  }
  if (!installed) {
    disableVoice("The on-device language pack could not be installed.");
    return false;
  }
  onDeviceReady = true;
  setVoiceBadge(true);
  return true;
}

function buildRecognition() {
  const instance = new SpeechRecognition();
  instance.lang = voiceOptions.langs[0];
  instance.continuous = false;
  instance.interimResults = true;
  // Never set to false anywhere. This is the whole guarantee.
  instance.processLocally = true;

  instance.addEventListener("start", () => {
    setVoiceState(VoiceState.LISTENING, "Listening on this device. You will review the transcript before anything runs.");
  });

  instance.addEventListener("result", (event) => {
    let transcript = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      transcript += event.results[index][0].transcript;
    }
    elements.input.value = transcript.trim();
    elements.input.dispatchEvent(new Event("input"));
    if (event.results[event.results.length - 1].isFinal) {
      lastInputChannel = "voice";
      setVoiceState(VoiceState.PROCESSING);
    }
  });

  instance.addEventListener("end", () => {
    const transcript = elements.input.value.trim();
    if (!transcript) {
      setVoiceState(VoiceState.IDLE, "No speech was recognised.");
      return;
    }
    // Recording has ended before anything is submitted, always.
    if (looksLikeQuestion(transcript)) {
      setVoiceState(VoiceState.EXECUTING, "Question recognised. Submitting.");
      elements.form.requestSubmit();
      return;
    }
    setVoiceState(VoiceState.TRANSCRIPT_READY, "Transcript ready. Review it, then press Execute.");
  });

  instance.addEventListener("error", (event) => {
    if (event.error === "not-allowed" || event.error === "service-not-allowed") {
      onDeviceReady = false;
      setVoiceState(VoiceState.PERMISSION_DENIED);
      setVoiceBadge(false, "microphone permission denied");
      elements.note.textContent = "Microphone access was denied. Type your request instead.";
      return;
    }
    if (event.error === "language-not-supported") {
      disableVoice("The on-device language pack is missing and Nexuss will not fall back to cloud recognition.");
      return;
    }
    if (event.error === "no-speech") {
      setVoiceState(VoiceState.IDLE, "No speech was detected.");
      return;
    }
    setVoiceState(VoiceState.IDLE, `Voice input stopped: ${event.error}. Text control remains active.`);
  });

  return instance;
}

function stopSpeaking() {
  if (SpeechSynthesis) SpeechSynthesis.cancel();
  if (voiceState === VoiceState.SPEAKING) setVoiceState(VoiceState.IDLE);
}

function speakAnswer(answer) {
  if (!speakRepliesEnabled || !SpeechSynthesis) return;
  const text = speechTextFor(answer);
  if (!text) return;
  stopSpeaking();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = VOICE_LANGUAGE;
  utterance.rate = Number(elements.voiceRate?.value || 1);
  utterance.addEventListener("end", () => {
    if (voiceState === VoiceState.SPEAKING) setVoiceState(VoiceState.IDLE);
  });
  setVoiceState(VoiceState.SPEAKING);
  SpeechSynthesis.speak(utterance);
}

if (SpeechRecognition) {
  elements.voice.addEventListener("click", async () => {
    stopSpeaking();
    if (voiceState === VoiceState.LISTENING) {
      recognition?.stop();
      return;
    }
    if (!onDeviceReady && !(await ensureLanguagePack())) return;
    if (!recognition) recognition = buildRecognition();
    try {
      recognition.start();
    } catch (_error) {
      recognition.stop();
    }
  });
}

elements.voiceStop?.addEventListener("click", stopSpeaking);
elements.voiceReplies?.addEventListener("change", (event) => {
  speakRepliesEnabled = Boolean(event.target.checked);
  if (!speakRepliesEnabled) stopSpeaking();
});

void initialiseVoice();

void checkHealth();
setInterval(checkHealth, 30000);
elements.input.focus();

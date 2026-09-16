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
  newChat: document.querySelector("#new-chat-button"),
  chatList: document.querySelector("#chat-list"),
  conversationTitle: document.querySelector("#conversation-title"),
  conversationSubtitle: document.querySelector("#conversation-subtitle"),
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
  elements.archiveAttachmentMeta.textContent = "Secure local intake · GitHub or Nexuss development package";
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
  elements.archiveAttachmentMeta.textContent = `${formatArchiveBytes(file.size)} · secure local quarantine`;
  elements.note.textContent = "ZIP attached · choose GitHub import or approved Nexuss development-package intake in your instruction.";
}


function isDevelopmentPackageInstruction(utterance) {
  const value = String(utterance || "").trim();
  return (
    /\bapproved\s+(?:nexuss\s+)?development\s+package\b/i.test(value) ||
    /\b(?:apply|install|inspect|validate)\b[\s\S]{0,80}\b(?:development\s+package|nexuss\s+package|phase\s+zip)\b/i.test(value)
  );
}

function developmentPackageApiHeaders(requestId, archiveName) {
  return {
    "Content-Type": "application/zip",
    "X-Nexuss-Session-ID": sessionId,
    "X-Nexuss-Session-Authenticated": "true",
    "X-Nexuss-Request-ID": requestId,
    "X-Nexuss-Archive-Name": encodeURIComponent(archiveName),
  };
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

/* P6.8A.5 NEXUSS FOCUS DECK */

function appendSafeInlineMarkup(container, source) {
  const text = String(source || "");
  const tokenPattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let cursor = 0;

  for (const match of text.matchAll(tokenPattern)) {
    if (match.index > cursor) {
      container.append(
        document.createTextNode(text.slice(cursor, match.index)),
      );
    }

    const token = match[0];

    if (token.startsWith("`")) {
      const code = document.createElement("code");
      code.textContent = token.slice(1, -1);
      container.append(code);
    } else {
      const strong = document.createElement("strong");
      strong.textContent = token.slice(2, -2);
      container.append(strong);
    }

    cursor = match.index + token.length;
  }

  if (cursor < text.length) {
    container.append(document.createTextNode(text.slice(cursor)));
  }
}

function renderSafeCognitiveMarkdown(source) {
  const documentRoot = document.createElement("div");
  documentRoot.className = "cognitive-document";

  const lines = String(source || "").replace(/\r\n/g, "\n").split("\n");
  let list = null;
  let listType = null;
  let codeBlock = null;
  let codeLanguage = "";

  const closeList = () => {
    list = null;
    listType = null;
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      closeList();

      if (codeBlock) {
        const wrapper = document.createElement("div");
        wrapper.className = "cognitive-code";

        const toolbar = document.createElement("div");
        toolbar.className = "cognitive-code-toolbar";

        const language = document.createElement("span");
        language.textContent = codeLanguage || "Code";

        const copy = document.createElement("button");
        copy.type = "button";
        copy.textContent = "Copy";
        copy.addEventListener("click", async () => {
          try {
            await navigator.clipboard.writeText(codeBlock.textContent || "");
            copy.textContent = "Copied";
            window.setTimeout(() => {
              copy.textContent = "Copy";
            }, 1400);
          } catch (_error) {
            copy.textContent = "Select to copy";
          }
        });

        toolbar.append(language, copy);

        const pre = document.createElement("pre");
        pre.append(codeBlock);

        wrapper.append(toolbar, pre);
        documentRoot.append(wrapper);

        codeBlock = null;
        codeLanguage = "";
      } else {
        codeLanguage = trimmed.slice(3).trim();
        codeBlock = document.createElement("code");
      }

      continue;
    }

    if (codeBlock) {
      codeBlock.append(
        document.createTextNode(
          `${codeBlock.textContent ? "\n" : ""}${line}`,
        ),
      );
      continue;
    }

    if (!trimmed) {
      closeList();
      continue;
    }

    if (/^---+$/.test(trimmed)) {
      closeList();
      documentRoot.append(document.createElement("hr"));
      continue;
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);

    if (heading) {
      closeList();
      const level = Math.min(heading[1].length + 1, 4);
      const element = document.createElement(`h${level}`);
      appendSafeInlineMarkup(element, heading[2]);
      documentRoot.append(element);
      continue;
    }

    const ordered = trimmed.match(/^(\d+)[.)]\s+(.+)$/);
    const unordered = trimmed.match(/^[-*]\s+(.+)$/);

    if (ordered || unordered) {
      const desiredType = ordered ? "ol" : "ul";

      if (!list || listType !== desiredType) {
        list = document.createElement(desiredType);
        list.className = "cognitive-list";
        listType = desiredType;
        documentRoot.append(list);
      }

      const item = document.createElement("li");
      appendSafeInlineMarkup(
        item,
        ordered ? ordered[2] : unordered[1],
      );
      list.append(item);
      continue;
    }

    closeList();

    const paragraph = document.createElement("p");
    appendSafeInlineMarkup(paragraph, trimmed);
    documentRoot.append(paragraph);
  }

  if (codeBlock) {
    const pre = document.createElement("pre");
    pre.append(codeBlock);
    documentRoot.append(pre);
  }

  return documentRoot;
}

function renderCognitiveAnswer(answer) {
  const root = document.createElement("section");
  root.className = "cognitive-response";

  if (answer.cognitive) {
    const header = document.createElement("header");
    header.className = "cognitive-response-header";

    const identity = document.createElement("div");
    identity.className = "cognitive-provider-identity";

    const mark = document.createElement("span");
    mark.className = "cognitive-provider-mark";
    mark.textContent = "AI";

    const titleGroup = document.createElement("div");

    const title = document.createElement("strong");
    title.textContent = answer.cognitive.provider || "DeepSeek";

    const subtitle = document.createElement("span");
    subtitle.textContent = [
      answer.cognitive.model,
      answer.cognitive.mode,
    ].filter(Boolean).join(" ?? ");

    titleGroup.append(title, subtitle);
    identity.append(mark, titleGroup);

    const verified = document.createElement("span");
    verified.className = "cognitive-verified";
    verified.textContent = "Verified proposal";

    header.append(identity, verified);
    root.append(header);
  }

  root.append(renderSafeCognitiveMarkdown(answer.text));

  if (answer.cognitive?.trust?.length) {
    const trust = document.createElement("footer");
    trust.className = "cognitive-trust-strip";

    const labels = [
      ["NO TOOLS", "tool"],
      ["NO WRITES", "write"],
      ["NO APPROVAL", "approval"],
      ["NEXUSS AUTHORITY", "authority"],
    ];

    for (const [label, kind] of labels) {
      const badge = document.createElement("span");
      badge.dataset.kind = kind;
      badge.textContent = label;
      trust.append(badge);
    }

    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Trust and processing details";

    const list = document.createElement("ul");

    for (const line of answer.cognitive.trust) {
      const item = document.createElement("li");
      item.textContent = line;
      list.append(item);
    }

    details.append(summary, list);
    trust.append(details);
    root.append(trust);
  }

  return root;
}


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
  timestamp.textContent = timeLabel(
    options.createdAt ? new Date(options.createdAt) : new Date(),
  );
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

  if (
    role === "assistant"
    && !isError
    && (options.rich || answer.cognitive)
  ) {
    bubble.classList.add("rich-bubble");
    bubble.append(renderCognitiveAnswer(answer));
  } else {
    const paragraph = document.createElement("p");
    paragraph.textContent = answer.text;
    bubble.append(paragraph);
  }

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

/* P6.12 ADAPTIVE DESKTOP POLLING */
const TASK_POLL_ACTIVE_MS = 1500;
const TASK_POLL_AWAITING_APPROVAL_MS = 3000;
const TASK_POLL_BACKOFF_MAX_MS = 8000;
let taskPollGeneration = 0;

function stopTaskPolling() {
  taskPollGeneration += 1;
  if (taskPollTimer) {
    clearTimeout(taskPollTimer);
    taskPollTimer = null;
  }
}

async function pollTaskUntilResolved(taskId) {
  stopTaskPolling();
  const generation = taskPollGeneration;
  let failures = 0;

  const schedule = (delay) => {
    if (generation !== taskPollGeneration) return;
    taskPollTimer = setTimeout(() => { void tick(); }, delay);
  };

  const tick = async () => {
    if (generation !== taskPollGeneration) return;

    try {
      const response = await fetch(`/v1/tasks/${taskId}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(`Task status unavailable (${response.status})`);
      }

      failures = 0;
      const task = await response.json();
      const previousApprovalId = currentTask?.approval?.approval_id || null;

      if (task.state === "awaiting_approval") {
        const nextApprovalId = task.approval?.approval_id || null;
        if (nextApprovalId && nextApprovalId !== previousApprovalId) {
          const receipt = await fetchReceipt(task.task_id);
          hideApproval();
          renderTask(task, receipt);
          addMessage("assistant", summarizeTask(task), false, {
            speak: true,
          });
          await showApproval(task.approval);
          showToast(
            "Phase one verified. Review phase two on your paired phone.",
          );
        }
        schedule(TASK_POLL_AWAITING_APPROVAL_MS);
        return;
      }

      if (
        ![
          "completed",
          "partially_completed",
          "denied",
          "failed",
          "rolled_back",
        ].includes(task.state)
      ) {
        renderTask(task, currentReceipt);
        schedule(TASK_POLL_ACTIVE_MS);
        return;
      }

      stopTaskPolling();
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
      failures += 1;
      const delay = Math.min(
        TASK_POLL_ACTIVE_MS * (2 ** failures),
        TASK_POLL_BACKOFF_MAX_MS,
      );
      schedule(delay);
    }
  };

  await tick();
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



async function executeDevelopmentPackageInstruction(utterance) {
  if (!selectedArchive) throw new Error("Attach a ZIP development package first.");

  const archive = selectedArchive;
  const requestId = crypto.randomUUID();
  setBusy(true);
  addMessage("user", utterance);
  stopSpeaking();
  addMessage(
    "assistant",
    `Quarantining ${archive.name}, verifying its Nexuss development manifest and target hashes. No LLM/API call is required.`,
  );

  try {
    const response = await fetch("/v1/development-packages", {
      method: "POST",
      headers: developmentPackageApiHeaders(requestId, archive.name),
      body: archive,
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`Development-package intake failed (${response.status}): ${detail}`);
    }
    const task = await response.json();
    clearArchiveAttachment();
    const receipt = await fetchReceipt(task.task_id);
    renderTask(task, receipt);
    addMessage(
      "assistant",
      "Nexuss verified the ZIP manifest and base hashes. Review the exact package in Action Control before isolated validation and live application.",
      false,
      { speak: true },
    );
    if (task.state === "awaiting_approval" && task.approval) {
      await showApproval(task.approval);
    }
  } catch (error) {
    addMessage(
      "assistant",
      error instanceof Error ? error.message : "Unexpected development-package intake error",
      true,
    );
  } finally {
    setBusy(false);
    elements.input.focus();
  }
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

// Copyright © kexyz254peter
// Nexuss AI - Confidential and Proprietary
// Unauthorized copying, redistribution or disclosure is prohibited.

// NEXUSS_P66B_GOAL_UNDERSTANDING_UI
function renderUnderstandingState(response) {
  const interpretation = response?.interpretation;
  if (!interpretation) return;

  elements.metricIntent.textContent = String(interpretation.goal || "unknown")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
  elements.metricConfidence.textContent =
    `${Math.round(Number(interpretation.confidence || 0) * 100)}%`;
  elements.metricRisk.textContent = {
    destructive: "Critical",
    write: "High",
    execute: "High",
    plan: "Low",
    read: "Informational",
    inform: "Informational",
  }[interpretation.operation] || "Unknown";
  elements.metricState.textContent = String(response.status || "unknown")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());

  if (elements.policySummary) {
    const constraints = interpretation.constraints || {};
    const preserved = [];
    if (constraints.read_only) preserved.push("read only");
    if (constraints.plan_only) preserved.push("plan only");
    if (constraints.allow_code_execution === false) preserved.push("no code execution");
    if (constraints.allow_external_writes === false) preserved.push("no external writes");
    if (constraints.allow_network_access === false) preserved.push("no network access");
    elements.policySummary.textContent = preserved.length
      ? `Preserved constraints: ${preserved.join(", ")}.`
      : "No additional user constraint changed the existing policy boundary.";
  }
}

function appendClarificationCard(response, channel, originalUtterance) {
  const clarification = response.clarification;
  if (!clarification) return;

  const article = document.createElement("article");
  article.className = "message assistant-message clarification-message";

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = "N";

  const content = document.createElement("div");
  content.className = "message-content";

  const meta = document.createElement("div");
  meta.className = "message-meta";
  const author = document.createElement("span");
  author.textContent = "Nexuss";
  const timestamp = document.createElement("time");
  timestamp.textContent = timeLabel();
  meta.append(author, timestamp);

  const bubble = document.createElement("div");
  bubble.className = "bubble clarification-card";

  const question = document.createElement("p");
  question.className = "clarification-question";
  question.textContent = clarification.question;

  const options = document.createElement("div");
  options.className = "clarification-options";

  for (const option of clarification.options || []) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "clarification-option";
    button.dataset.optionId = option.option_id;

    const label = document.createElement("strong");
    label.textContent = option.label;
    button.append(label);

    if (option.description) {
      const description = document.createElement("span");
      description.textContent = option.description;
      button.append(description);
    }

    button.addEventListener("click", () => {
      for (const candidate of options.querySelectorAll("button")) {
        candidate.disabled = true;
      }
      void answerUnderstandingClarification(
        response,
        option,
        channel,
        originalUtterance,
      );
    });
    options.append(button);
  }

  const boundary = document.createElement("p");
  boundary.className = "clarification-boundary";
  boundary.textContent =
    "No action is performed until the target and outcome are explicit.";

  bubble.append(question, options, boundary);
  content.append(meta, bubble);
  article.append(avatar, content);
  elements.timeline.append(article);
  elements.timeline.scrollTop = elements.timeline.scrollHeight;
}

function understandingReceiptNote(response) {
  const receiptIds = response?.execution?.receipt_ids || [];
  if (!receiptIds.length) return "";
  return `\n\nRead-only receipt${receiptIds.length === 1 ? "" : "s"}: ${
    receiptIds.map((value) => String(value).slice(0, 8)).join(", ")
  }.`;
}

async function handleUnderstandingResponse(
  response,
  channel,
  originalUtterance,
) {
  renderUnderstandingState(response);

  if (response.status === "pass_through") {
    await executeInstruction(
      response.resolved_utterance || originalUtterance,
      channel,
      {
        userAlreadyAdded: true,
        progressAlreadyAdded: true,
      },
    );
    return true;
  }

  if (response.status === "clarification_required") {
    addMessage("assistant", response.assistant_message);
    appendClarificationCard(response, channel, originalUtterance);
    return false;
  }

  const note = understandingReceiptNote(response);
  addMessage(
    "assistant",
    `${response.assistant_message || "No action was performed."}${note}`,
    response.status === "blocked",
    { speak: response.status === "completed" },
  );

  if (response.status === "completed") {
    showToast("Read-only goal completed and verified.");
  } else if (response.status === "blocked") {
    showToast("The request was blocked before execution.");
  } else if (response.status === "cancelled") {
    showToast("Clarification cancelled. No action occurred.");
  }
  return false;
}

async function understandAndExecute(utterance, channel = "text") {
  // P6.8A.2: explicit cognitive requests bypass deterministic goal classification.
  if (wantsDeepSeekCognition(utterance)) {
    setBusy(true);
    stopSpeaking();

    await executeCognitiveInstruction(
      utterance,
      typeof channel === "string" ? channel : "text",
    );

    return;
  }

  setBusy(true);
  addMessage("user", utterance);
  stopSpeaking();
  addMessage(
    "assistant",
    "Resolving the goal, target, constraints, confidence, and policy boundary…",
  );

  let delegated = false;
  try {
    const response = await fetch("/v1/understanding/resolve", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({
        request_id: crypto.randomUUID(),
        utterance,
        channel,
        client_context: {
          interface: "p66b-web-ui",
          browser_voice: channel === "voice",
        },
        execute_safe_reads: true,
      }),
    });
    if (!response.ok) {
      throw new Error(
        `Understanding failed (${response.status}): ${await response.text()}`,
      );
    }
    const body = await response.json();
    delegated = body.status === "pass_through";
    await handleUnderstandingResponse(body, channel, utterance);
  } catch (error) {
    addMessage(
      "assistant",
      error instanceof Error
        ? error.message
        : "The understanding gateway failed closed.",
      true,
    );
  } finally {
    if (!delegated) setBusy(false);
    elements.input.focus();
  }
}

async function answerUnderstandingClarification(
  priorResponse,
  option,
  channel,
  originalUtterance,
) {
  setBusy(true);
  addMessage("user", option.label);
  addMessage(
    "assistant",
    "Applying the clarification and re-evaluating the exact goal and policy…",
  );

  let delegated = false;
  try {
    const clarificationId = priorResponse.clarification?.clarification_id;
    if (!clarificationId) {
      throw new Error("The clarification state is missing.");
    }
    const response = await fetch(
      `/v1/understanding/clarifications/${clarificationId}/answer`,
      {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({ option_id: option.option_id }),
      },
    );
    if (!response.ok) {
      throw new Error(
        `Clarification failed (${response.status}): ${await response.text()}`,
      );
    }
    const body = await response.json();
    delegated = body.status === "pass_through";
    await handleUnderstandingResponse(
      body,
      channel,
      originalUtterance,
    );
  } catch (error) {
    addMessage(
      "assistant",
      error instanceof Error
        ? error.message
        : "The clarification failed closed.",
      true,
    );
  } finally {
    if (!delegated) setBusy(false);
    elements.input.focus();
  }
}

// P66B_LEGACY_DELEGATION_OPTIONS
function wantsDeepSeekCognition(utterance) {
  const normalized = String(utterance || "").trim().toLowerCase();

  return (
    normalized.startsWith("/deepseek") ||
    normalized.startsWith("deepseek:") ||
    normalized.includes("use deepseek") ||
    normalized.includes("reasoning provider: deepseek")
  );
}

function inferCognitiveMode(utterance) {
  const normalized = String(utterance || "").toLowerCase();

  if (/\b(debug|diagnose|fix bug|troubleshoot)\b/.test(normalized)) {
    return "debug";
  }
  if (/\b(code|implement|program|function|class|script)\b/.test(normalized)) {
    return "code";
  }
  if (/\b(rewrite|rephrase|edit|polish)\b/.test(normalized)) {
    return "rewrite";
  }
  if (/\b(write|draft|compose)\b/.test(normalized)) {
    return "write";
  }
  if (/\b(review|audit|critique)\b/.test(normalized)) {
    return "review";
  }
  if (/\b(design|architecture|system design)\b/.test(normalized)) {
    return "design";
  }
  if (/\b(build|create|develop)\b/.test(normalized)) {
    return "build_proposal";
  }
  if (/\b(plan|roadmap|steps|strategy)\b/.test(normalized)) {
    return "plan";
  }
  if (/\b(synthesize|research summary)\b/.test(normalized)) {
    return "research_synthesis";
  }

  return "analyze";
}


/* P6.9B BOUNDED AUTONOMY */
async function executeAutonomousInstruction(utterance, channel) {
  const instruction = utterance.replace(/^\/(?:deepseek|auto)\s*/i, "").trim();
  if (!instruction) {
    addMessage("assistant", "Add an exact goal after /deepseek or /auto.", true);
    setBusy(false);
    return;
  }
  addMessage("assistant", "Nexuss is running certified actions until it reaches a real approval or policy blocker...");
  try {
    const response = await fetch("/v1/orchestrations/autonomous", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({
        request_id: crypto.randomUUID(),
        user_session_id: sessionId,
        instruction,
        provider_id: "auto",
        provider_mode: inferCognitiveMode(instruction),
        autonomy_mode: "supervised",
        external_processing_approved: true,
        maximum_actions: 6,
        maximum_runtime_seconds: 120,
      }),
    });
    if (!response.ok) {
      const problem = await response.json().catch(() => null);
      throw new Error(problem?.detail?.message || `Autonomy failed (${response.status}).`);
    }
    const run = await response.json();
    const lines = [
      run.response,
      "",
      `Workflow: ${titleCase(run.state)}.`,
      `Completed: ${run.completed_count}.`,
      `Awaiting approval: ${run.awaiting_approval_count}.`,
      `Blocked: ${run.blocked_count}.`,
      "Protected actions were not auto-approved.",
    ];
    addMessage("assistant", {
      text: lines.join("\n"),
      blocks: [],
      cognitive: {
        provider: run.provider_display_name,
        model: run.model,
        mode: "bounded autonomy",
        trust: [
          "Certified reads may execute automatically.",
          "Protected actions pause for exact approval.",
          "Capability mismatches fail closed.",
          "Nexuss owns verification and receipts.",
        ],
      },
    }, false, { speak: channel === "voice", rich: true });
    elements.receiptState.textContent = titleCase(run.state);
    elements.metricIntent.textContent = "Bounded Autonomy";
    elements.metricState.textContent = titleCase(run.state);
    elements.planList.className = "detail-list";
    elements.planList.replaceChildren();
    for (const [index, step] of run.steps.entries()) {
      elements.planList.append(createDetailCard(
        `${index + 1}. ${step.capability_id}`,
        step.state,
        {
          reason: step.reason_code,
          task_id: step.core_task_id || "not created",
          receipt_id: step.core_receipt_id || "pending",
          evidence: String(step.evidence_count),
        },
      ));
    }
    elements.policySummary.textContent = `${run.completed_count} completed · ${run.awaiting_approval_count} approval · ${run.blocked_count} blocked`;
    renderEvents(run.receipt.events || []);
  } catch (error) {
    addMessage("assistant", error instanceof Error ? error.message : "Bounded autonomy failed closed.", true);
  } finally {
    setBusy(false);
  }
}

async function executeCognitiveInstruction(utterance, channel) {
  addMessage(
    "assistant",
    "DeepSeek is generating a grounded proposal inside the Nexuss cognitive trust boundary...",
  );

  try {
    const response = await fetch("/v1/cognitive/proposals", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({
        request_id: crypto.randomUUID(),
        user_session_id: sessionId,
        instruction: utterance,
        mode: inferCognitiveMode(utterance),
      }),
    });

    if (!response.ok) {
      let problem = null;

      try {
        problem = await response.json();
      } catch {
        problem = null;
      }

      const detail = problem?.detail || {};
      const message =
        detail.fallback ||
        detail.message ||
        `Cognitive request failed (${response.status}).`;

      throw new Error(message);
    }

    const body = await response.json();
    const proposal = body.proposal;
    const receipt = body.receipt;

    const attribution = [
      `Reasoning provider: DeepSeek (${proposal.model})`,
      "DeepSeek generated a proposal only.",
      "External processing used: yes.",
      "Tool capabilities executed: none.",
      "Files modified: none.",
      "External writes: none.",
      "Approval requested: none.",
      "Hidden reasoning stored: none.",
      "Nexuss retains policy, approval, execution, verification, receipt, audit, and final authority.",
    ].join("\n");

    addMessage(
      "assistant",
      {
        text: proposal.response,
        blocks: [],
        cognitive: {
          provider: "DeepSeek",
          model: proposal.model,
          mode: proposal.mode,
          trust: attribution.split("\n"),
        },
      },
      false,
      {
        speak: channel === "voice",
        rich: true,
      },
    );

    const intent = {
      kind: "cognitive_proposal",
      normalized_text: `DeepSeek ${proposal.mode} proposal`,
      confidence: 1,
      entities: {
        provider_id: proposal.provider_id,
        model: proposal.model,
        receipt_type: receipt.receipt_type,
      },
    };

    const stepId = receipt.receipt_id;

    const plan = {
      plan_id: receipt.receipt_id,
      task_id: receipt.receipt_id,
      intent,
      steps: [{
        step_id: stepId,
        order: 1,
        capability_id: "cognitive.deepseek.propose",
        risk_tier: "informational",
        expected_evidence: ["cognitive_proposal_receipt"],
        parameters: {
          mode: proposal.mode,
          external_processing: true,
          tools_allowed: false,
        },
        reversible: false,
      }],
    };

    const decisions = [{
      step_id: stepId,
      capability_id: "cognitive.deepseek.propose",
      outcome: "allow",
      reason_code: "PROPOSAL_ONLY_EXTERNAL_REASONING",
      explanation:
        "Explicit DeepSeek selection authorized proposal-only external processing without tool or write authority.",
    }];

    const results = [{
      step_id: stepId,
      capability_id: "cognitive.deepseek.propose",
      status: "verified",
      evidence: [{
        source: "external:deepseek",
        observed_at: receipt.created_at,
        attributes: {
          provider_id: receipt.provider_id,
          model: receipt.model,
          mode: receipt.mode,
          provider_invoked: receipt.provider_invoked,
          proposal_validated: receipt.proposal_validated,
          external_processing_used:
            receipt.external_processing_used,
          execution_authorized:
            receipt.execution_authorized,
          tool_capabilities_executed:
            receipt.tool_capabilities_executed,
          approval_requested:
            receipt.approval_requested,
          files_modified:
            receipt.files_modified,
          external_writes:
            receipt.external_writes,
          hidden_reasoning_stored:
            receipt.hidden_reasoning_stored,
          request_sha256:
            receipt.request_sha256,
          context_sha256:
            receipt.context_sha256,
          response_sha256:
            receipt.response_sha256,
        },
      }],
      error_code: null,
    }];

    const events = receipt.events.map((event) => ({
      event_id: crypto.randomUUID(),
      sequence: event.sequence,
      state: event.state,
      event_type: event.event_type,
      occurred_at: event.occurred_at,
      detail: event.detail,
    }));

    const task = {
      task_id: receipt.receipt_id,
      request_id: receipt.request_id,
      user_session_id: sessionId,
      state: "completed",
      intent,
      plan,
      policy_decisions: decisions,
      results,
      events,
      approval: null,
      created_at: receipt.created_at,
      updated_at: receipt.created_at,
    };

    const actionReceipt = {
      receipt_id: receipt.receipt_id,
      receipt_version: 1,
      task_id: receipt.receipt_id,
      request_id: receipt.request_id,
      state: "completed",
      intent,
      plan_id: receipt.receipt_id,
      policy_decisions: decisions,
      results,
      events,
      created_at: receipt.created_at,
      updated_at: receipt.created_at,
      verified: true,
      reversible: false,
    };

    renderTask(task, actionReceipt);
  } catch (error) {
    addMessage(
      "assistant",
      error instanceof Error
        ? error.message
        : "The cognitive provider request failed closed.",
      true,
    );
  } finally {
    setBusy(false);
  }
}

async function executeLegacyInstruction(
  utterance,
  channel = "text",
  options = {},
) {
  if (/^\/(?:deepseek|auto)(?:\s|$)/i.test(utterance.trim())) {
    setBusy(true);
    stopSpeaking();
    await executeAutonomousInstruction(utterance, channel);
    return;
  }

  setBusy(true);
  if (!options.userAlreadyAdded) addMessage("user", utterance);
  stopSpeaking();
  if (!options.progressAlreadyAdded) {
    addMessage(
      "assistant",
      "Interpreting intent, generating a capability plan, and evaluating policy…",
    );
  }

  if (wantsDeepSeekCognition(utterance)) {
    await executeCognitiveInstruction(utterance, channel);
    return;
  }

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
    // P6.13 ASYNC PACKAGE APPROVAL POLLING
    const developmentPackageTask = task.plan?.steps?.some(
      (step) => step.capability_id === "engineering.package.apply",
    );
    if (
      decisionKind === "approve" &&
      developmentPackageTask &&
      ["approved", "executing", "verifying"].includes(task.state)
    ) {
      void pollTaskUntilResolved(task.task_id);
      showToast("Development package approved. Isolated validation is running.");
    } else {
      showToast(decisionKind === "approve" ? "Exact action approved and verified." : "Action cancelled. No write occurred.");
    }
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


/* P6.11 UNIFIED USER-TURN SUBMISSION */
let nexussUnifiedTurnPromise = null;

async function submitUnifiedUserTurn(
  utterance,
  channel = "text",
) {
  const originalUserText = String(utterance || "").trim();

  if (!originalUserText) {
    return;
  }

  if (nexussUnifiedTurnPromise) {
    showToast(
      "Nexuss is already processing this turn. "
      + "No duplicate interaction was created.",
    );
    return nexussUnifiedTurnPromise;
  }

  setBusy(true);
  stopSpeaking();
  addMessage("user", originalUserText);

  const turnPromise = Promise.resolve().then(() => (
    executeInstruction(originalUserText, channel)
  ));
  const trackedPromise = turnPromise.finally(() => {
    if (nexussUnifiedTurnPromise === trackedPromise) {
      nexussUnifiedTurnPromise = null;
    }
    elements.input.focus();
  });

  nexussUnifiedTurnPromise = trackedPromise;
  return trackedPromise;
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const utterance = elements.input.value.trim();
  if (!utterance) return;
  const channel = lastInputChannel;
  lastInputChannel = "text";
  elements.input.value = "";
  elements.input.style.height = "auto";

  if (selectedArchive) {
    if (isDevelopmentPackageInstruction(utterance)) {
      void executeDevelopmentPackageInstruction(utterance);
    } else {
      void executeArchiveInstruction(utterance);
    }
    return;
  }

  const contextualResponse = window.NexussP5?.handleContextCommand?.(utterance);
  if (contextualResponse) {
    addMessage("user", utterance);
    addMessage("assistant", contextualResponse);
    elements.input.focus();
    return;
  }

  void submitUnifiedUserTurn(utterance, channel);
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
      elements.input.placeholder = "Example: Nexuss, inspect and apply this approved development package.";
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

/* P6.12 visibility-aware health polling */
const HEALTH_POLL_VISIBLE_MS = 60000;
let healthPollTimer = null;

function scheduleHealthCheck(delay = HEALTH_POLL_VISIBLE_MS) {
  if (healthPollTimer) clearTimeout(healthPollTimer);
  healthPollTimer = setTimeout(async () => {
    healthPollTimer = null;
    if (document.visibilityState === "visible") {
      await checkHealth();
    }
    scheduleHealthCheck();
  }, delay);
}

void checkHealth().finally(() => scheduleHealthCheck());
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  void checkHealth();
  scheduleHealthCheck();
});
elements.input.focus();


const NEXUSS_FOCUS_PREFERENCE_KEY = "nexuss-focus-deck-v1";

function readFocusDeckState() {
  const defaults = {
    conversation: true,
    inspector: true,
    workspace: false,
    mode: "split",
  };

  try {
    const stored = JSON.parse(
      localStorage.getItem(NEXUSS_FOCUS_PREFERENCE_KEY) || "null",
    );

    return {
      ...defaults,
      ...(stored && typeof stored === "object" ? stored : {}),
    };
  } catch (_error) {
    return defaults;
  }
}

let focusDeckState = readFocusDeckState();

function saveFocusDeckState() {
  localStorage.setItem(
    NEXUSS_FOCUS_PREFERENCE_KEY,
    JSON.stringify(focusDeckState),
  );
}

function updateFocusDeckButtons() {
  document.querySelectorAll("[data-focus-command]").forEach((button) => {
    const command = button.dataset.focusCommand;
    let pressed = false;

    if (command === "conversation") {
      pressed = focusDeckState.conversation;
    } else if (command === "inspector") {
      pressed = focusDeckState.inspector;
    } else if (command === "workspace") {
      pressed = focusDeckState.workspace;
    } else if (command === "split") {
      pressed = focusDeckState.mode === "split";
    }

    button.setAttribute("aria-pressed", String(pressed));
  });
}

function applyFocusDeckState() {
  const conversation = document.querySelector("#conversation-app");
  const inspector = document.querySelector("#action-control-app");
  const workspace = document.querySelector("#p5-workspace");

  if (conversation) {
    conversation.hidden = !focusDeckState.conversation;
  }

  if (inspector) {
    inspector.hidden = !focusDeckState.inspector;
  }

  if (workspace && focusDeckState.workspace) {
    workspace.hidden = false;
  }

  document.body.dataset.focusMode = focusDeckState.mode;
  updateFocusDeckButtons();
  saveFocusDeckState();
}

function setFocusDeckMode(mode) {
  if (mode === "conversation") {
    focusDeckState = {
      ...focusDeckState,
      conversation: true,
      inspector: false,
      mode,
    };
  } else if (mode === "inspector") {
    focusDeckState = {
      ...focusDeckState,
      conversation: false,
      inspector: true,
      mode,
    };
  } else {
    focusDeckState = {
      ...focusDeckState,
      conversation: true,
      inspector: true,
      mode: "split",
    };
  }

  applyFocusDeckState();
}

function toggleFocusDeckApp(app) {
  if (app === "conversation") {
    if (
      focusDeckState.conversation
      && focusDeckState.mode === "conversation"
    ) {
      focusDeckState.conversation = false;
      focusDeckState.mode = "split";
    } else {
      setFocusDeckMode("conversation");
      return;
    }
  }

  if (app === "inspector") {
    if (
      focusDeckState.inspector
      && focusDeckState.mode === "inspector"
    ) {
      focusDeckState.inspector = false;
      focusDeckState.mode = "split";
    } else {
      setFocusDeckMode("inspector");
      return;
    }
  }

  if (app === "workspace") {
    const workspace = document.querySelector("#p5-workspace");
    const next = workspace ? workspace.hidden : !focusDeckState.workspace;
    focusDeckState.workspace = next;

    if (workspace) {
      workspace.hidden = !next;
    }
  }

  applyFocusDeckState();
}

function restoreFocusDeck() {
  focusDeckState = {
    conversation: true,
    inspector: true,
    workspace: false,
    mode: "split",
  };

  const workspace = document.querySelector("#p5-workspace");

  if (workspace) {
    workspace.hidden = true;
  }

  applyFocusDeckState();
}

function initializeFocusDeck() {
  document.querySelectorAll("[data-focus-command]").forEach((button) => {
    button.addEventListener("click", () => {
      const command = button.dataset.focusCommand;

      if (command === "conversation") {
        toggleFocusDeckApp("conversation");
      } else if (command === "inspector") {
        toggleFocusDeckApp("inspector");
      } else if (command === "workspace") {
        toggleFocusDeckApp("workspace");
      } else if (command === "split") {
        setFocusDeckMode("split");
      } else if (command === "restore") {
        restoreFocusDeck();
      }
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.altKey && event.key === "1") {
      event.preventDefault();
      setFocusDeckMode("conversation");
    }

    if (event.altKey && event.key === "2") {
      event.preventDefault();
      setFocusDeckMode("inspector");
    }

    if (event.altKey && event.key === "3") {
      event.preventDefault();
      toggleFocusDeckApp("workspace");
    }

    if (event.ctrlKey && event.key === "\\") {
      event.preventDefault();
      toggleFocusDeckApp("inspector");
    }

    if (event.key === "Escape") {
      setFocusDeckMode("split");
    }
  });

  applyFocusDeckState();
}

if (document.readyState === "loading") {
  document.addEventListener(
    "DOMContentLoaded",
    initializeFocusDeck,
    { once: true },
  );
} else {
  initializeFocusDeck();
}


/* P6.15 MULTI-CHAT SESSION LAYER */

let activeConversationId = null;
let conversationContinuationToken = null;
let activeConversationRecord = null;
let activeConversationPersisted = false;
let conversationIndex = [];

let persistentConversationInitializationKey = null;
let persistentConversationInitializationPromise = null;

function resetPersistentConversationInitialization() {
  persistentConversationInitializationKey = null;
  persistentConversationInitializationPromise = null;
}

function createConversationIdentifiers() {
  activeConversationId = crypto.randomUUID();
  conversationContinuationToken =
    `${crypto.randomUUID()}${crypto.randomUUID()}`;
}

function updateConversationHeader(record = null) {
  if (
    !elements.conversationTitle
    || !elements.conversationSubtitle
  ) {
    return;
  }

  if (!record) {
    elements.conversationTitle.textContent = "New chat";
    elements.conversationSubtitle.textContent =
      "Fresh conversation Â· saved locally after your first message.";
    return;
  }

  elements.conversationTitle.textContent =
    record.title || "New chat";

  const updated = record.updated_at
    ? new Date(record.updated_at).toLocaleString()
    : "just now";

  elements.conversationSubtitle.textContent =
    `Saved Nexuss chat Â· updated ${updated}`;
}

function clearConversationTimeline(message = null) {
  elements.timeline.replaceChildren();

  addMessage(
    "assistant",
    message || (
      "New chat ready. Ask Nexuss anything, or choose a saved "
      + "chat from the sidebar."
    ),
    false,
    {
      speak: false,
      rich: false,
    },
  );
}

function resetConversationActivity() {
  nexussInteractionCache.clear();
  selectedNexussInteractionId = null;
  renderInteractionTray();
}

function renderConversationList() {
  if (!elements.chatList) {
    return;
  }

  elements.chatList.replaceChildren();

  if (!conversationIndex.length) {
    const empty = document.createElement("p");
    empty.className = "chat-list-empty";
    empty.textContent = "No saved chats yet.";
    elements.chatList.append(empty);
    return;
  }

  for (const conversation of conversationIndex) {
    const row = document.createElement("div");
    row.className = "chat-list-row";
    row.classList.toggle(
      "is-active",
      activeConversationPersisted
        && conversation.conversation_id === activeConversationId,
    );

    const open = document.createElement("button");
    open.type = "button";
    open.className = "chat-list-item";
    open.setAttribute(
      "aria-current",
      row.classList.contains("is-active")
        ? "page"
        : "false",
    );

    const title = document.createElement("strong");
    title.textContent =
      conversation.title || "New conversation";

    const meta = document.createElement("span");
    meta.textContent = conversation.updated_at
      ? new Date(conversation.updated_at).toLocaleString()
      : "Saved chat";

    open.append(title, meta);
    open.addEventListener("click", () => {
      void selectPersistentConversation(
        conversation.conversation_id,
      );
    });

    const actions = document.createElement("div");
    actions.className = "chat-list-actions";

    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "chat-list-action";
    rename.textContent = "âœŽ";
    rename.title = "Rename chat";
    rename.setAttribute(
      "aria-label",
      `Rename ${conversation.title}`,
    );
    rename.addEventListener("click", (event) => {
      event.stopPropagation();
      void renamePersistentConversation(conversation);
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chat-list-action is-danger";
    remove.textContent = "Ã—";
    remove.title = "Delete chat";
    remove.setAttribute(
      "aria-label",
      `Delete ${conversation.title}`,
    );
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      void deletePersistentConversation(conversation);
    });

    actions.append(rename, remove);
    row.append(open, actions);
    elements.chatList.append(row);
  }
}

async function refreshConversationList() {
  try {
    const response = await fetch(
      "/v1/conversations",
      {
        headers: apiHeaders(),
        cache: "no-store",
      },
    );

    if (!response.ok) {
      throw new Error(
        `Conversation list failed (${response.status}).`,
      );
    }

    const payload = await response.json();

    conversationIndex = Array.isArray(
      payload.conversations,
    )
      ? payload.conversations
      : [];

    renderConversationList();
  } catch (error) {
    console.warn(
      "Conversation list refresh failed.",
      error,
    );
  }
}

function startNewPersistentConversation(options = {}) {
  createConversationIdentifiers();
  activeConversationRecord = null;
  activeConversationPersisted = false;
  resetPersistentConversationInitialization();
  updateConversationHeader();

  clearConversationTimeline(
    options.announce === false
      ? null
      : (
        "Started a new chat. Your previous chats remain "
        + "in the sidebar."
      ),
  );

  renderConversationList();
  resetConversationActivity();
  elements.input?.focus();
}

function renderStoredConversation(history) {
  const messages = history.messages || [];
  elements.timeline.replaceChildren();

  if (!messages.length) {
    addMessage(
      "assistant",
      "This saved chat is empty. Continue it with a new message.",
    );
    return;
  }

  for (const message of messages) {
    addMessage(
      message.role,
      message.text,
      false,
      {
        speak: false,
        rich: false,
        createdAt: message.created_at,
      },
    );
  }
}

async function selectPersistentConversation(
  conversationId,
) {
  try {
    const response = await fetch(
      `/v1/conversations/${encodeURIComponent(
        conversationId
      )}`,
      {
        headers: apiHeaders(),
        cache: "no-store",
      },
    );

    if (!response.ok) {
      throw new Error(
        `Conversation load failed (${response.status}).`,
      );
    }

    const history = await response.json();

    activeConversationId =
      history.conversation.conversation_id;
    conversationContinuationToken = null;
    activeConversationRecord = history.conversation;
    activeConversationPersisted = true;

    resetPersistentConversationInitialization();
    updateConversationHeader(activeConversationRecord);
    renderStoredConversation(history);
    renderConversationList();
    resetConversationActivity();

    await loadRecentUnifiedInteractions();
    elements.input?.focus();
  } catch (error) {
    showToast(
      error instanceof Error
        ? error.message
        : "The saved chat could not be loaded.",
    );
  }
}

async function renamePersistentConversation(
  conversation,
) {
  const nextTitle = window.prompt(
    "Rename chat",
    conversation.title || "New conversation",
  );

  if (nextTitle === null) {
    return;
  }

  const title = nextTitle.trim();

  if (!title) {
    showToast("Chat title cannot be empty.");
    return;
  }

  try {
    const response = await fetch(
      `/v1/conversations/${encodeURIComponent(
        conversation.conversation_id
      )}`,
      {
        method: "PATCH",
        headers: apiHeaders(),
        body: JSON.stringify({ title }),
      },
    );

    if (!response.ok) {
      throw new Error(
        `Rename failed (${response.status}).`,
      );
    }

    const history = await response.json();

    if (
      history.conversation.conversation_id
      === activeConversationId
    ) {
      activeConversationRecord = history.conversation;
      updateConversationHeader(
        activeConversationRecord,
      );
    }

    await refreshConversationList();
  } catch (error) {
    showToast(
      error instanceof Error
        ? error.message
        : "Chat rename failed.",
    );
  }
}

async function deletePersistentConversation(
  conversation,
) {
  const confirmed = window.confirm(
    `Delete "${conversation.title}"? `
    + "This removes its saved messages.",
  );

  if (!confirmed) {
    return;
  }

  try {
    const response = await fetch(
      `/v1/conversations/${encodeURIComponent(
        conversation.conversation_id
      )}`,
      {
        method: "DELETE",
        headers: apiHeaders(),
      },
    );

    if (!response.ok && response.status !== 204) {
      throw new Error(
        `Delete failed (${response.status}).`,
      );
    }

    if (
      conversation.conversation_id
      === activeConversationId
    ) {
      startNewPersistentConversation({
        announce: false,
      });
    }

    await refreshConversationList();
  } catch (error) {
    showToast(
      error instanceof Error
        ? error.message
        : "Chat delete failed.",
    );
  }
}

async function ensurePersistentConversation() {
  if (
    activeConversationPersisted
    && activeConversationRecord
  ) {
    return {
      conversation: activeConversationRecord,
      messages: [],
    };
  }

  if (
    !activeConversationId
    || !conversationContinuationToken
  ) {
    createConversationIdentifiers();
  }

  const conversationId = activeConversationId;
  const continuationToken =
    conversationContinuationToken;
  const initializationKey =
    `${conversationId}:${sessionId}`;

  if (
    persistentConversationInitializationPromise
    && persistentConversationInitializationKey
      === initializationKey
  ) {
    return persistentConversationInitializationPromise;
  }

  const initializationPromise = (async () => {
    const response = await fetch(
      "/v1/conversations",
      {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({
          conversation_id: conversationId,
          user_session_id: sessionId,
          provider_id: "auto",
          title: "New conversation",
          continuation_token: continuationToken,
        }),
      },
    );

    if (!response.ok) {
      let problem = null;

      try {
        problem = await response.json();
      } catch {
        problem = null;
      }

      const detail = problem?.detail || {};

      throw new Error(
        detail.message
        || (
          "Conversation initialization failed "
          + `(${response.status}).`
        ),
      );
    }

    const history = await response.json();

    activeConversationRecord =
      history.conversation;
    activeConversationPersisted = true;

    updateConversationHeader(
      activeConversationRecord,
    );

    void refreshConversationList();

    return history;
  })();

  persistentConversationInitializationKey =
    initializationKey;
  persistentConversationInitializationPromise =
    initializationPromise;

  try {
    return await initializationPromise;
  } catch (error) {
    if (
      persistentConversationInitializationPromise
      === initializationPromise
    ) {
      resetPersistentConversationInitialization();
    }

    throw error;
  }
}

async function executeConversationTurn(
  utterance,
  channel,
) {
  try {
    await ensurePersistentConversation();

    const response = await fetch(
      `/v1/conversations/${activeConversationId}/turns`,
      {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          user_session_id: sessionId,
          text: utterance,
          provider_id: "auto",
          external_processing_approved: true,
        }),
      },
    );

    if (!response.ok) {
      let problem = null;

      try {
        problem = await response.json();
      } catch {
        problem = null;
      }

      const detail = problem?.detail || {};

      throw new Error(
        detail.message
        || (
          "Conversation routing failed "
          + `(${response.status}).`
        ),
      );
    }

    const turn = await response.json();

    activeConversationRecord =
      turn.conversation;
    activeConversationPersisted = true;

    updateConversationHeader(
      activeConversationRecord,
    );

    void refreshConversationList();

    if (turn.route === "chat") {
      addMessage(
        "assistant",
        {
          text: turn.assistant_message.text,
          blocks: [],
          cognitive: {
            provider: "DeepSeek",
            model: turn.model,
            mode: "conversation",
            trust: [
              "Conversation saved locally for continuation.",
              "No capability was required for this reply.",
              "Nexuss retained policy and final authority.",
            ],
          },
        },
        false,
        {
          speak: channel === "voice",
          rich: true,
        },
      );

      setBusy(false);
      return;
    }

    if (turn.route === "clarification") {
      addMessage(
        "assistant",
        (
          turn.clarification_question
          || turn.assistant_message.text
        ),
        false,
        {
          speak: channel === "voice",
          rich: false,
        },
      );

      setBusy(false);
      return;
    }

    if (
      turn.route === "action"
      && turn.action_instruction
    ) {
      addMessage(
        "assistant",
        (
          turn.assistant_message.text
          || (
            "I understood the action and am routing "
            + "it through Nexuss."
          )
        ),
      );

      await executeLegacyInstruction(
        turn.action_instruction,
        channel,
      );

      return;
    }

    throw new Error(
      "The conversation router returned an unsupported state.",
    );
  } catch (error) {
    addMessage(
      "assistant",
      error instanceof Error
        ? error.message
        : "Conversation routing failed closed.",
      true,
    );

    setBusy(false);
  }
}

async function executePreUnifiedInstruction(
  utterance,
  channel,
) {
  const normalized = utterance.trim();

  if (!normalized) {
    setBusy(false);
    return;
  }

  if (/^\/newchat$/i.test(normalized)) {
    startNewPersistentConversation();
    setBusy(false);
    return;
  }

  if (/^\//.test(normalized)) {
    await executeLegacyInstruction(
      utterance,
      channel,
    );
    return;
  }

  await executeConversationTurn(
    utterance,
    channel,
  );
}

window.NexussConversation = Object.freeze({
  newConversation:
    startNewPersistentConversation,
  currentConversationId:
    () => activeConversationId,
  list:
    refreshConversationList,
  select:
    selectPersistentConversation,
  rename:
    renamePersistentConversation,
  delete:
    deletePersistentConversation,
});

elements.newChat?.addEventListener(
  "click",
  () => {
    startNewPersistentConversation();
  },
);

setTimeout(
  () => {
    startNewPersistentConversation({
      announce: false,
    });

    void refreshConversationList();
  },
  0,
);

/* P6.10A MULTITASKING MEDIA SHELL */

(() => {
  "use strict";

  const STORAGE_KEY = "nexuss.media.presentationMode";
  const POSITION_KEY = "nexuss.media.miniPosition";
  const VALID_MODES = new Set([
    "expanded",
    "mini",
    "compact",
  ]);

  let currentMode = "expanded";
  let observer = null;
  let dragState = null;

  function mediaDock() {
    return document.getElementById("media-dock");
  }

  function restorePill() {
    return document.getElementById(
      "nexuss-media-restore-pill",
    );
  }

  function currentMediaTitle(dock) {
    const selectors = [
      "[data-now-playing-title]",
      ".now-playing-title",
      ".media-now-playing-title",
      ".media-title",
      "h2",
      "h3",
    ];

    for (const selector of selectors) {
      const candidate = dock.querySelector(selector);
      const value = candidate?.textContent?.trim();

      if (
        value
        && !/^(media workspace|youtube results)$/i.test(value)
      ) {
        return value;
      }
    }

    return "Media is still playing";
  }

  function createButton({
    action,
    label,
    title,
  }) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "nexuss-media-mode-button";
    button.dataset.mediaShellAction = action;
    button.textContent = label;
    button.title = title;
    button.setAttribute("aria-label", title);
    return button;
  }

  function ensureRestorePill() {
    let pill = restorePill();

    if (pill) {
      return pill;
    }

    pill = document.createElement("section");
    pill.id = "nexuss-media-restore-pill";
    pill.className = "nexuss-media-restore-pill";
    pill.hidden = true;
    pill.setAttribute("aria-label", "Hidden media controls");
    pill.setAttribute("aria-live", "polite");

    const status = document.createElement("div");
    status.className = "nexuss-media-restore-copy";

    const eyebrow = document.createElement("span");
    eyebrow.className = "nexuss-media-restore-eyebrow";
    eyebrow.textContent = "NOW PLAYING";

    const title = document.createElement("strong");
    title.className = "nexuss-media-restore-title";
    title.textContent = "Media is still playing";

    status.append(eyebrow, title);

    const restore = createButton({
      action: "restore",
      label: "Restore",
      title: "Restore the full media workspace",
    });

    const mini = createButton({
      action: "mini",
      label: "Mini",
      title: "Open the floating mini-player",
    });

    pill.append(status, mini, restore);
    document.body.append(pill);

    return pill;
  }

  function ensureToolbar(dock) {
    let toolbar = dock.querySelector(
      "[data-nexuss-media-shell-controls]",
    );

    if (toolbar) {
      return toolbar;
    }

    toolbar = document.createElement("div");
    toolbar.className = "nexuss-media-shell-controls";
    toolbar.dataset.nexussMediaShellControls = "true";
    toolbar.setAttribute(
      "aria-label",
      "Media multitasking controls",
    );

    const grip = document.createElement("button");
    grip.type = "button";
    grip.className = "nexuss-media-drag-handle";
    grip.textContent = "Move";
    grip.title = "Drag the floating mini-player";
    grip.setAttribute(
      "aria-label",
      "Drag the floating mini-player",
    );

    const label = document.createElement("span");
    label.className = "nexuss-media-shell-label";
    label.textContent = "Media workspace";

    const expanded = createButton({
      action: "expanded",
      label: "Expand",
      title: "Restore media to the main workspace",
    });

    const mini = createButton({
      action: "mini",
      label: "Mini",
      title: "Float media above the current workspace",
    });

    const compact = createButton({
      action: "compact",
      label: "Hide",
      title: "Hide the player while playback continues",
    });

    toolbar.append(
      grip,
      label,
      expanded,
      mini,
      compact,
    );

    dock.prepend(toolbar);
    bindDragHandle(grip, dock);
    return toolbar;
  }

  function savedPosition() {
    try {
      const raw = localStorage.getItem(POSITION_KEY);

      if (!raw) {
        return null;
      }

      const parsed = JSON.parse(raw);

      if (
        Number.isFinite(parsed?.left)
        && Number.isFinite(parsed?.top)
      ) {
        return parsed;
      }
    } catch {
      return null;
    }

    return null;
  }

  function applySavedPosition(dock) {
    const position = savedPosition();

    if (!position || currentMode !== "mini") {
      return;
    }

    const maximumLeft = Math.max(
      8,
      window.innerWidth - dock.offsetWidth - 8,
    );
    const maximumTop = Math.max(
      8,
      window.innerHeight - dock.offsetHeight - 8,
    );

    dock.style.left =
      `${Math.min(Math.max(8, position.left), maximumLeft)}px`;
    dock.style.top =
      `${Math.min(Math.max(8, position.top), maximumTop)}px`;
    dock.style.right = "auto";
    dock.style.bottom = "auto";
  }

  function clearPosition(dock) {
    dock.style.removeProperty("left");
    dock.style.removeProperty("top");
    dock.style.removeProperty("right");
    dock.style.removeProperty("bottom");
  }

  function updateControls(dock) {
    const toolbar = ensureToolbar(dock);

    for (
      const button of toolbar.querySelectorAll(
        "[data-media-shell-action]",
      )
    ) {
      const selected =
        button.dataset.mediaShellAction === currentMode;

      button.classList.toggle("is-active", selected);
      button.setAttribute(
        "aria-pressed",
        selected ? "true" : "false",
      );
    }

    const grip = toolbar.querySelector(
      ".nexuss-media-drag-handle",
    );

    if (grip) {
      grip.disabled = currentMode !== "mini";
      grip.hidden = currentMode !== "mini";
    }

    const pill = ensureRestorePill();
    const title = pill.querySelector(
      ".nexuss-media-restore-title",
    );

    if (title) {
      title.textContent = currentMediaTitle(dock);
    }

    pill.hidden = currentMode !== "compact";
  }

  function setMode(
    requestedMode,
    {
      persist = true,
      announce = true,
    } = {},
  ) {
    const dock = mediaDock();

    if (!dock) {
      return false;
    }

    const mode = VALID_MODES.has(requestedMode)
      ? requestedMode
      : "expanded";

    currentMode = mode;
    dock.dataset.presentationMode = mode;
    document.documentElement.dataset.mediaPresentationMode =
      mode;

    if (mode !== "mini") {
      clearPosition(dock);
    }

    updateControls(dock);

    if (mode === "mini") {
      requestAnimationFrame(() => {
        applySavedPosition(dock);
      });
    }

    if (persist) {
      localStorage.setItem(STORAGE_KEY, mode);
    }

    if (announce) {
      const message = {
        expanded: "Media restored to the workspace.",
        mini: "Media moved to the floating mini-player.",
        compact:
          "Media hidden. Playback remains mounted and can be restored.",
      }[mode];

      window.dispatchEvent(
        new CustomEvent("nexuss:media-mode-changed", {
          detail: {
            mode,
            message,
          },
        }),
      );
    }

    return true;
  }

  function toggleMini() {
    return setMode(
      currentMode === "mini" ? "expanded" : "mini",
    );
  }

  function toggleCompact() {
    return setMode(
      currentMode === "compact" ? "expanded" : "compact",
    );
  }

  function bindDragHandle(handle, dock) {
    if (handle.dataset.dragBound === "true") {
      return;
    }

    handle.dataset.dragBound = "true";

    handle.addEventListener("pointerdown", (event) => {
      if (currentMode !== "mini") {
        return;
      }

      event.preventDefault();
      handle.setPointerCapture(event.pointerId);

      const rectangle = dock.getBoundingClientRect();

      dragState = {
        pointerId: event.pointerId,
        offsetX: event.clientX - rectangle.left,
        offsetY: event.clientY - rectangle.top,
      };

      dock.classList.add("is-dragging");
    });

    handle.addEventListener("pointermove", (event) => {
      if (
        !dragState
        || dragState.pointerId !== event.pointerId
        || currentMode !== "mini"
      ) {
        return;
      }

      const maximumLeft = Math.max(
        8,
        window.innerWidth - dock.offsetWidth - 8,
      );
      const maximumTop = Math.max(
        8,
        window.innerHeight - dock.offsetHeight - 8,
      );

      const left = Math.min(
        Math.max(8, event.clientX - dragState.offsetX),
        maximumLeft,
      );
      const top = Math.min(
        Math.max(8, event.clientY - dragState.offsetY),
        maximumTop,
      );

      dock.style.left = `${left}px`;
      dock.style.top = `${top}px`;
      dock.style.right = "auto";
      dock.style.bottom = "auto";
    });

    function finishDrag(event) {
      if (
        !dragState
        || dragState.pointerId !== event.pointerId
      ) {
        return;
      }

      const rectangle = dock.getBoundingClientRect();

      localStorage.setItem(
        POSITION_KEY,
        JSON.stringify({
          left: Math.round(rectangle.left),
          top: Math.round(rectangle.top),
        }),
      );

      dragState = null;
      dock.classList.remove("is-dragging");
    }

    handle.addEventListener("pointerup", finishDrag);
    handle.addEventListener("pointercancel", finishDrag);
  }

  function handleAction(event) {
    const button = event.target.closest(
      "[data-media-shell-action]",
    );

    if (!button) {
      return;
    }

    const action = button.dataset.mediaShellAction;

    if (action === "restore" || action === "expanded") {
      setMode("expanded");
    } else if (action === "mini") {
      setMode("mini");
    } else if (action === "compact") {
      setMode("compact");
    }
  }

  function initialiseDock() {
    const dock = mediaDock();

    if (!dock) {
      return false;
    }

    ensureToolbar(dock);
    ensureRestorePill();

    const savedMode = localStorage.getItem(STORAGE_KEY);
    const initialMode = VALID_MODES.has(savedMode)
      ? savedMode
      : "expanded";

    setMode(initialMode, {
      persist: false,
      announce: false,
    });

    return true;
  }

  function observeMediaWorkspace() {
    /* P6.10A.1 MEDIA OBSERVER HOTFIX */
    if (mediaDock()) {
      return;
    }

    if (observer) {
      return;
    }

    observer = new MutationObserver(() => {
      if (!mediaDock()) {
        return;
      }

      observer.disconnect();
      observer = null;
      initialiseDock();
    });

    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
  }

  document.addEventListener("click", handleAction);

  document.addEventListener("keydown", (event) => {
    if (
      event.altKey
      && !event.ctrlKey
      && !event.metaKey
      && event.key.toLowerCase() === "m"
    ) {
      event.preventDefault();

      if (event.shiftKey) {
        toggleCompact();
      } else {
        toggleMini();
      }
    }
  });

  window.addEventListener("resize", () => {
    const dock = mediaDock();

    if (dock && currentMode === "mini") {
      applySavedPosition(dock);
    }
  });

  window.NexussMediaWorkspace = Object.freeze({
    expand: () => setMode("expanded"),
    minimize: () => setMode("mini"),
    hide: () => setMode("compact"),
    toggleMini,
    toggleCompact,
    mode: () => currentMode,
  });

  function start() {
    initialiseDock();
    observeMediaWorkspace();
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      start,
      { once: true },
    );
  } else {
    start();
  }
})();

/* P6.10B UNIFIED INTERACTION RUNTIME */

const nexussInteractionCache = new Map();
let selectedNexussInteractionId = null;

function ensureInteractionTray() {
  let tray = document.getElementById("nexuss-interaction-tray");

  if (tray) {
    return tray;
  }

  tray = document.createElement("section");
  tray.id = "nexuss-interaction-tray";
  tray.className = "nexuss-interaction-tray";
  tray.setAttribute("aria-label", "Recent Nexuss activity");

  const header = document.createElement("header");
  header.className = "nexuss-interaction-tray-header";

  const title = document.createElement("div");
  title.className = "nexuss-interaction-tray-title";

  const heading = document.createElement("strong");
  heading.textContent = "Activity";

  const subtitle = document.createElement("span");
  subtitle.textContent = "Unified interactions";

  title.append(heading, subtitle);

  const actions = document.createElement("div");
  actions.className = "nexuss-interaction-tray-actions";

  const save = document.createElement("button");
  save.type = "button";
  save.textContent = "Save session";
  save.title = "Prepare a managed session note with approval.";
  save.addEventListener("click", () => {
    void saveCurrentConversationAsNote();
  });

  const newChat = document.createElement("button");
  newChat.type = "button";
  newChat.textContent = "New";
  newChat.title = "Start a separate saved conversation";
  newChat.addEventListener("click", () => {
    if (window.NexussConversation?.newConversation) {
      window.NexussConversation.newConversation();
      nexussInteractionCache.clear();
      selectedNexussInteractionId = null;
      renderInteractionTray();
    }
  });

  actions.append(save, newChat);
  header.append(title, actions);

  const list = document.createElement("div");
  list.className = "nexuss-interaction-tray-list";
  list.dataset.interactionTrayList = "true";

  tray.append(header, list);
  document.body.append(tray);
  return tray;
}

function interactionStateLabel(interaction) {
  const labels = {
    responded: "Answered",
    completed: "Completed",
    blocked: "Blocked",
    awaiting_approval: "Approval",
    failed: "Failed",
    denied: "Denied",
  };

  return labels[interaction.state]
    || titleCase(interaction.state || "received");
}

function renderInteractionTray() {
  const tray = ensureInteractionTray();
  const list = tray.querySelector("[data-interaction-tray-list]");
  list.replaceChildren();

  const interactions = Array.from(
    nexussInteractionCache.values(),
  ).sort((left, right) => (
    new Date(right.updated_at).getTime()
    - new Date(left.updated_at).getTime()
  )).slice(0, 8);

  if (!interactions.length) {
    const empty = document.createElement("p");
    empty.className = "nexuss-interaction-tray-empty";
    empty.textContent = "No governed interactions yet.";
    list.append(empty);
    return;
  }

  for (const interaction of interactions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "nexuss-interaction-item";
    button.classList.toggle(
      "is-selected",
      selectedNexussInteractionId
        === interaction.interaction_id,
    );

    const top = document.createElement("span");
    top.className = "nexuss-interaction-item-top";

    const kind = document.createElement("strong");
    kind.textContent = titleCase(interaction.kind);

    const state = document.createElement("span");
    state.className = (
      `nexuss-interaction-state is-${interaction.state}`
    );
    state.textContent = interactionStateLabel(interaction);

    top.append(kind, state);

    const summary = document.createElement("span");
    summary.className = "nexuss-interaction-item-summary";
    summary.textContent = interaction.display_text;

    button.append(top, summary);
    button.addEventListener("click", () => {
      void selectUnifiedInteraction(interaction.interaction_id);
    });
    list.append(button);
  }
}

function rememberUnifiedInteraction(interaction) {
  nexussInteractionCache.set(
    interaction.interaction_id,
    interaction,
  );
  selectedNexussInteractionId = interaction.interaction_id;
  renderInteractionTray();
}

function renderUnifiedInteraction(interaction) {
  selectedNexussInteractionId = interaction.interaction_id;
  renderInteractionTray();

  if (elements?.receiptState) {
    elements.receiptState.textContent =
      interactionStateLabel(interaction);
  }

  if (elements?.metricIntent) {
    elements.metricIntent.textContent = (
      interaction.kind === "chat"
        ? "Assistant Conversation"
        : interaction.kind === "workflow"
          ? "Investigation Workflow"
        : interaction.kind === "clarification"
          ? "Target Clarification"
          : "Governed Action"
    );
  }

  if (elements?.metricConfidence) {
    elements.metricConfidence.textContent = interaction.kind === "workflow" ? "See evidence" : "Recorded";
  }

  if (elements?.metricRisk) {
    elements.metricRisk.textContent = (
      interaction.kind === "action"
        ? "Policy governed"
        : "Informational"
    );
  }

  if (elements?.metricState) {
    elements.metricState.textContent =
      interactionStateLabel(interaction);
  }

  if (
    typeof renderEvents === "function"
    && interaction.events
  ) {
    renderEvents(interaction.events);
  }

  if (elements?.planList) {
    elements.planList.className = "detail-list";
    elements.planList.replaceChildren();

    const details = {
      route: interaction.kind,
      state: interaction.state,
      provider: interaction.provider_id,
      model: interaction.model,
      internal_user_rewrite: "not shown",
    };

    if (interaction.resolved_instruction) {
      details.resolved_instruction =
        interaction.resolved_instruction;
    }

    if (interaction.capability_hint) {
      details.capability_hint = interaction.capability_hint;
    }

    if (interaction.core_task_id) {
      details.task_id = interaction.core_task_id;
    }

    elements.planList.append(
      createDetailCard(
        "Unified interaction",
        interaction.state,
        details,
      ),
    );
  }

  if (elements?.policySummary) {
    elements.policySummary.textContent = (
      interaction.kind === "action"
        ? (
          interaction.approval_required
            ? "Protected action · approval required"
            : "Nexuss Core governed the action"
        )
        : interaction.kind === "workflow" ? "Workflow evidence and progress retained; no live TAS mutation adapter" : "No capability execution required"
    );
  }

  if (elements?.evidenceList) {
    elements.evidenceList.className = "detail-list";
    elements.evidenceList.replaceChildren();

    if (interaction.receipt_id || interaction.evidence_count) {
      elements.evidenceList.append(
        createDetailCard(
          "Canonical evidence",
          interaction.state,
          {
            receipt_id: interaction.receipt_id || "pending",
            evidence_records:
              String(interaction.evidence_count || 0),
            interaction_id: interaction.interaction_id,
          },
        ),
      );
    } else {
      elements.evidenceList.className =
        "detail-list empty-state";
      elements.evidenceList.textContent = (
        interaction.kind === "chat"
          ? "Conversation saved locally; no tool evidence required."
          : "Evidence has not been produced yet."
      );
    }
  }

  if (elements?.evidenceSummary) {
    elements.evidenceSummary.textContent = (
      `${interaction.evidence_count || 0} evidence record`
      + `${interaction.evidence_count === 1 ? "" : "s"}`
    );
  }

  if (elements?.receiptId) {
    elements.receiptId.textContent = (
      interaction.receipt_id || interaction.interaction_id
    );
  }

  if (elements?.receiptVerified) {
    elements.receiptVerified.textContent = (
      interaction.state === "completed"
      || interaction.state === "responded"
        ? "Yes"
        : "Pending"
    );
  }

  if (elements?.receiptTitle) {
    elements.receiptTitle.textContent = (
      `${titleCase(interaction.kind)} interaction`
    );
  }
}

/* P6.10D AUTHORITATIVE PRESENTATION SYNCHRONIZER */

function isP610DMediaTask(task, interaction) {
  const instruction = String(
    interaction?.resolved_instruction || "",
  ).toLowerCase();

  if (/\b(youtube|media|play|watch|video|music)\b/.test(instruction)) {
    return true;
  }

  return (task?.results || []).some((result) => (
    String(result?.capability_id || "").startsWith("media.")
  ));
}

function p610DMediaRendered() {
  const workspace = document.getElementById("media-dock");
  const queue = document.getElementById("media-queue");
  const video = document.getElementById("media-video");
  const title = document.getElementById("media-title");

  if (!workspace || workspace.hidden) {
    return false;
  }

  return Boolean(
    queue?.children?.length
    || video?.querySelector("iframe, video")
    || String(title?.textContent || "").trim(),
  );
}

async function p610DPresentCoreTask(interaction, presentation) {
  const task = presentation?.task;
  const receipt = presentation?.receipt || null;

  if (!task) {
    return { presented: false, message: interaction.display_text };
  }

  if (typeof renderTask !== "function") {
    throw new Error("The verified task renderer is unavailable.");
  }

  renderTask(task, receipt);

  if (
    task.state === "awaiting_approval"
    && task.approval
    && typeof showApproval === "function"
  ) {
    await showApproval(task.approval);
  } else if (typeof hideApproval === "function") {
    hideApproval();
  }

  if (isP610DMediaTask(task, interaction)) {
    const workspace = document.getElementById("media-dock");
    if (workspace) {
      workspace.hidden = false;
    }

    if (window.NexussMediaWorkspace?.expand) {
      window.NexussMediaWorkspace.expand();
    }

    await new Promise((resolve) => requestAnimationFrame(resolve));
    await new Promise((resolve) => setTimeout(resolve, 80));

    if (task.state === "completed" && !p610DMediaRendered()) {
      return {
        presented: false,
        message: (
          "The media task completed without a visible player or "
          + "results. Nexuss is not claiming playback."
        ),
      };
    }
  }

  return { presented: true, message: interaction.display_text };
}

async function p610DFetchPresentation(interaction) {
  if (interaction?.presentation?.task) {
    return interaction.presentation;
  }

  if (!interaction?.interaction_id) {
    return null;
  }

  const response = await fetch(
    `/v1/interactions/${interaction.interaction_id}/presentation`,
    { headers: apiHeaders() },
  );

  if (!response.ok) {
    return null;
  }

  return response.json();
}

function isP610DLocalMediaCommand(utterance) {
  const normalized = String(utterance || "")
    .trim()
    .toLowerCase()
    .replace(/[.!?]+$/g, "");

  return new Set([
    "open youtube",
    "show youtube",
    "restore youtube",
    "open media",
    "show media",
    "restore media",
    "show the player",
    "restore the player",
  ]).has(normalized);
}

function p610DOpenMediaWorkspace() {
  const workspace = document.getElementById("media-dock");
  if (!workspace) return false;

  workspace.hidden = false;
  if (window.NexussMediaWorkspace?.expand) {
    window.NexussMediaWorkspace.expand();
  }
  workspace.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return true;
}

async function loadCoreTaskForInteraction(interaction) {
  if (!interaction?.core_task_id && !interaction?.presentation?.task) {
    return;
  }

  try {
    const presentation = await p610DFetchPresentation(interaction);

    if (presentation?.task) {
      await p610DPresentCoreTask(interaction, presentation);
      return;
    }

    if (!interaction.core_task_id) {
      return;
    }

    const taskResponse = await fetch(
      `/v1/tasks/${interaction.core_task_id}`,
      { headers: apiHeaders() },
    );

    if (!taskResponse.ok) {
      throw new Error(`Task refresh failed (${taskResponse.status}).`);
    }

    const task = await taskResponse.json();
    let receipt = null;

    try {
      receipt = await fetchReceipt(task.task_id);
    } catch (error) {
      console.warn("Task receipt is not available yet.", error);
    }

    await p610DPresentCoreTask(
      interaction,
      { task, receipt },
    );
  } catch (error) {
    console.error("Interaction presentation failed.", error);
    addMessage(
      "assistant",
      error instanceof Error
        ? error.message
        : "The interaction presentation failed closed.",
      true,
    );
  }
}

async function selectUnifiedInteraction(interactionId) {
  const cached = nexussInteractionCache.get(interactionId);

  if (!cached) {
    return;
  }

  renderUnifiedInteraction(cached);
  await loadCoreTaskForInteraction(cached);
}

async function loadRecentUnifiedInteractions() {
  try {
    await ensurePersistentConversation();

    const encoded = encodeURIComponent(activeConversationId);
    const response = await fetch(
      `/v1/interactions?conversation_id=${encoded}&limit=8`,
      { headers: apiHeaders() },
    );

    if (!response.ok) {
      return;
    }

    const payload = await response.json();

    for (const interaction of payload.interactions || []) {
      nexussInteractionCache.set(
        interaction.interaction_id,
        interaction,
      );
    }

    renderInteractionTray();
  } catch (error) {
    console.warn("Recent interaction loading failed.", error);
  }
}

async function saveCurrentConversationAsNote() {
  try {
    await ensurePersistentConversation();

    const response = await fetch(
      `/v1/interactions/conversations/${activeConversationId}/save`,
      {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          user_session_id: sessionId,
          note_title: null,
        }),
      },
    );

    if (!response.ok) {
      let problem = null;

      try {
        problem = await response.json();
      } catch {
        problem = null;
      }

      const detail = problem?.detail || {};

      throw new Error(
        detail.message
        || `Session save failed (${response.status}).`,
      );
    }

    const result = await response.json();

    addMessage(
      "assistant",
      result.approval_required
        ? (
          "This conversation is already saved locally. "
          + "I prepared a managed session note and paused "
          + "for your exact approval."
        )
        : (
          "The conversation is saved locally and the "
          + "managed session note was created."
        ),
    );

    if (result.presentation?.task) {
      await p610DPresentCoreTask(
        {
          interaction_id: null,
          core_task_id: result.core_task_id,
          display_text: "Session note approval",
          resolved_instruction: "Create managed session note",
        },
        result.presentation,
      );
    } else if (result.core_task_id) {
      await loadCoreTaskForInteraction({
        core_task_id: result.core_task_id,
        approval_required: result.approval_required,
      });
    }
  } catch (error) {
    addMessage(
      "assistant",
      error instanceof Error
        ? error.message
        : "Session promotion failed closed.",
      true,
    );
  }
}


/* P6.11 REMOVED OBSOLETE P6.10C PRESENTATION BRIDGE */

function observeInteractionProgress(requestId, conversationId) {
  const panel = document.createElement("details");
  panel.className = "message assistant-message workflow-progress";
  panel.open = true;
  panel.hidden = true;
  const title = document.createElement("summary");
  title.textContent = "Workflow in progress";
  const entries = document.createElement("ol");
  entries.setAttribute("aria-live", "polite");
  panel.append(title, entries);
  elements.timeline.append(panel);
  let stopped = false;
  let sequence = 0;
  let timer = null;
  let isWorkflow = false;
  const controller = new AbortController();
  const labels = { planned: "Plan", running: "Working", completed: "Completed", blocked: "Blocked", reused: "Reused" };
  async function poll() {
    if (stopped || activeConversationId !== conversationId) return;
    try {
      const response = await fetch(`/v1/interactions/progress/${requestId}`, {
        headers: apiHeaders(), cache: "no-store", signal: controller.signal,
      });
      if (response.ok) {
        const progress = await response.json();
        if (stopped || activeConversationId !== conversationId) return;
        for (const event of progress.events || []) {
          if (event.sequence <= sequence) continue;
          sequence = event.sequence;
          if (!event.event_type.startsWith("workflow_")) continue;
          isWorkflow = true;
          panel.hidden = false;
          const item = document.createElement("li");
          item.textContent = `${labels[event.state] || event.state}: ${event.detail}`;
          entries.append(item);
        }
        if (progress.state !== "running") {
          title.textContent = progress.state === "blocked" ? "Workflow blocked — action needed" : "Workflow activity";
        }
      }
    } catch {
      // Progress transport failure must not retry the action POST.
      if (!stopped && isWorkflow) title.textContent = "Progress connection interrupted; awaiting the result";
    }
    if (!stopped && activeConversationId === conversationId) timer = setTimeout(poll, 750);
  }
  void poll();
  return (interaction) => {
    stopped = true;
    clearTimeout(timer);
    controller.abort();
    // Fast workflows may finish before the first poll; use their real retained events.
    for (const event of interaction?.events || []) {
      if (event.sequence <= sequence || !event.event_type.startsWith("workflow_")) continue;
      const item = document.createElement("li");
      item.textContent = `${labels[event.state] || event.state}: ${event.detail}`;
      entries.append(item);
      isWorkflow = true;
    }
    if (!isWorkflow) { panel.remove(); return; }
    panel.hidden = false;
    title.textContent = interaction?.state === "blocked" ? "Workflow blocked — action needed"
      : interaction ? "Workflow activity — finished" : "Request interrupted — verify status before retrying";
    panel.open = interaction?.state === "blocked";
  };
}

async function executeUnifiedInteraction(
  utterance,
  channel,
) {
  if (isP610DLocalMediaCommand(utterance)) {
    const opened = p610DOpenMediaWorkspace();
    addMessage(
      "assistant",
      opened
        ? "Opened the Nexuss media workspace."
        : "The media workspace is unavailable in this interface state.",
      !opened,
      { speak: channel === "voice" },
    );
    setBusy(false);
    return;
  }

  let stopProgress = () => {};
  let completedInteraction = null;
  try {
    await ensurePersistentConversation();

    const requestId = crypto.randomUUID();
    const submittedConversation = activeConversationId;
    stopProgress = observeInteractionProgress(requestId, submittedConversation);

    const response = await fetch("/v1/interactions", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({
        request_id: requestId,
        conversation_id: activeConversationId,
        user_session_id: sessionId,
        text: utterance,
        provider_id: "auto",
        external_processing_approved: true,
      }),
    });

    if (!response.ok) {
      let problem = null;
      try {
        problem = await response.json();
      } catch {
        problem = null;
      }
      const detail = problem?.detail || {};
      throw new Error(
        detail.message
        || `Unified interaction failed (${response.status}).`,
      );
    }

    const interaction = await response.json();
    completedInteraction = interaction;
    if (activeConversationId !== submittedConversation) return;
    activeConversationRecord = interaction.conversation;
    activeConversationPersisted = true;
    updateConversationHeader(activeConversationRecord);
    void refreshConversationList();
    rememberUnifiedInteraction(interaction);
    renderUnifiedInteraction(interaction);

    let displayText = interaction.display_text;
    let presentationResult = null;

    if (interaction.kind === "action") {
      const presentation = await p610DFetchPresentation(interaction);
      presentationResult = await p610DPresentCoreTask(
        interaction,
        presentation,
      );

      if (presentationResult && !presentationResult.presented) {
        displayText = presentationResult.message;
      }
    }

    addMessage(
      "assistant",
      displayText,
      !presentationResult?.presented && interaction.kind === "action",
      {
        speak: channel === "voice",
        rich: interaction.kind === "chat" || interaction.kind === "workflow",
      },
    );
  } catch (error) {
    addMessage(
      "assistant",
      error instanceof Error
        ? error.message
        : "The interaction failed closed.",
      true,
    );
  } finally {
    stopProgress(completedInteraction);
    setBusy(false);
  }
}

async function executeInstruction(utterance, channel) {
  const normalized = utterance.trim();

  if (!normalized) {
    setBusy(false);
    return;
  }

  if (/^\//.test(normalized)) {
    await executePreUnifiedInstruction(utterance, channel);
    return;
  }

  await executeUnifiedInteraction(utterance, channel);
}

window.NexussUnifiedSubmission = Object.freeze({
  submit: submitUnifiedUserTurn,
  legacyGatewayActiveForNormalSubmit: false,
});

window.NexussInteractions = Object.freeze({
  recent: loadRecentUnifiedInteractions,
  saveSession: saveCurrentConversationAsNote,
  select: selectUnifiedInteraction,
});

setTimeout(() => {
  ensureInteractionTray();
  renderInteractionTray();
}, 0);

/* Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary. */
/* P5.2 mobile action plane client. */
"use strict";

const elements = {
  connection: document.querySelector("#connection-state"),
  linkState: document.querySelector("#link-state"),
  linkMessage: document.querySelector("#link-state-message"),
  pairCard: document.querySelector("#pair-card"),
  pairForm: document.querySelector("#pair-form"),
  pairingCode: document.querySelector("#pairing-code"),
  deviceLabel: document.querySelector("#device-label"),
  pairButton: document.querySelector("#pair-button"),
  stage: document.querySelector("#approval-stage"),
  standby: document.querySelector("#standby"),
  card: document.querySelector("#approval-card"),
  risk: document.querySelector("#risk-badge"),
  expiry: document.querySelector("#approval-expiry"),
  title: document.querySelector("#action-title"),
  summary: document.querySelector("#action-summary"),
  destination: document.querySelector("#destination-label"),
  reversible: document.querySelector("#reversible-label"),
  preview: document.querySelector("#exact-preview"),
  hash: document.querySelector("#payload-hash"),
  approve: document.querySelector("#approve-button"),
  deny: document.querySelector("#deny-button"),
  handoffCard: document.querySelector("#handoff-card"),
  handoffQuery: document.querySelector("#handoff-query"),
  handoffUrl: document.querySelector("#handoff-url"),
  handoffOpen: document.querySelector("#handoff-open"),
  handoffDismiss: document.querySelector("#handoff-dismiss"),
  handoffCountdown: document.querySelector("#handoff-countdown"),
  toast: document.querySelector("#toast"),
};

const POLL_INTERVAL_MS = 1500;
const POLL_BACKOFF_MAX_MS = 15000;
/* A handoff older than this is history, not an instruction. Without this
   window a phone paired at 9pm will auto-open a link the desktop sent at 3pm. */
const AUTO_OPEN_MAX_AGE_MS = 45000;
const AUTO_OPEN_DELAY_MS = 1200;

let deviceId = localStorage.getItem("nexuss-mobile-device-id");
let deviceToken = localStorage.getItem("nexuss-mobile-device-token");
let pendingApproval = null;
let activeHandoff = null;
let pollTimer = null;
let pollDelay = POLL_INTERVAL_MS;
let countdownTimer = null;
let autoOpenTimer = null;
let toastTimer = null;
let inFlight = false;
let wakeLock = null;

function mobileHeaders() {
  return {
    "Content-Type": "application/json",
    "X-Nexuss-Mobile-Device-ID": deviceId || "",
    "X-Nexuss-Mobile-Token": deviceToken || "",
  };
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { elements.toast.hidden = true; }, 3200);
}

function setLinkState(message) {
  if (!message) {
    elements.linkState.hidden = true;
    return;
  }
  elements.linkMessage.textContent = message;
  elements.linkState.hidden = false;
}

function setPaired(paired) {
  elements.connection.classList.toggle("paired", paired);
  elements.connection.querySelector("span").textContent = paired ? "Paired" : "Not paired";
  elements.pairCard.hidden = paired;
  elements.stage.hidden = !paired;
}

/* Keep the screen awake while paired. A locked phone suspends timers, so a
   handoff sent while the phone is in a pocket would otherwise never arrive. */
async function requestWakeLock() {
  if (!("wakeLock" in navigator) || wakeLock) return;
  try {
    wakeLock = await navigator.wakeLock.request("screen");
    wakeLock.addEventListener("release", () => { wakeLock = null; });
  } catch {
    wakeLock = null;
  }
}

function releaseWakeLock() {
  if (wakeLock) {
    void wakeLock.release().catch(() => {});
    wakeLock = null;
  }
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function schedulePoll(delay = pollDelay) {
  stopPolling();
  pollTimer = setTimeout(() => { void poll(); }, delay);
}

function startPolling() {
  pollDelay = POLL_INTERVAL_MS;
  void poll();
}

function clearPairing() {
  deviceId = null;
  deviceToken = null;
  localStorage.removeItem("nexuss-mobile-device-id");
  localStorage.removeItem("nexuss-mobile-device-token");
  stopPolling();
  releaseWakeLock();
  clearHandoff();
  setPaired(false);
}

function renderApproval(approval) {
  pendingApproval = approval || null;
  elements.card.hidden = !approval;
  updateStandby();
  if (!approval) return;
  elements.risk.textContent = String(approval.risk_tier || "high").toUpperCase();
  elements.expiry.textContent = `Expires ${new Date(approval.expires_at).toLocaleTimeString()}`;
  elements.title.textContent = approval.action_title;
  elements.summary.textContent = approval.action_summary;
  elements.destination.textContent = approval.destination_label;
  elements.reversible.textContent = approval.reversible ? "Yes · receipt-bound" : "No";
  elements.preview.textContent = approval.exact_preview;
  elements.hash.textContent = approval.payload_sha256;
}

function updateStandby() {
  elements.standby.hidden = Boolean(pendingApproval || activeHandoff);
}

function clearHandoff() {
  activeHandoff = null;
  clearInterval(countdownTimer);
  clearTimeout(autoOpenTimer);
  countdownTimer = null;
  autoOpenTimer = null;
  elements.handoffCard.hidden = true;
  elements.handoffCountdown.hidden = true;
  updateStandby();
}

/* Only https YouTube destinations are ever rendered as a tappable link.
   The server allowlists too; this is the client half of the same rule. */
function isAllowedDestination(rawUrl) {
  let parsed;
  try {
    parsed = new URL(rawUrl);
  } catch {
    return false;
  }
  if (parsed.protocol !== "https:") return false;
  const host = parsed.hostname.toLowerCase();
  return (
    host === "youtube.com" ||
    host === "www.youtube.com" ||
    host === "m.youtube.com" ||
    host === "music.youtube.com" ||
    host === "youtu.be"
  );
}

function renderHandoff(handoff) {
  if (!handoff || !isAllowedDestination(handoff.launch_url)) return;
  if (activeHandoff && activeHandoff.task_id === handoff.task_id) return;

  clearHandoff();
  activeHandoff = handoff;

  elements.handoffQuery.textContent = handoff.query || "Open on YouTube";
  elements.handoffUrl.textContent = handoff.launch_url;
  elements.handoffOpen.href = handoff.launch_url;
  elements.handoffCard.hidden = false;
  updateStandby();

  const ageMs = Date.now() - new Date(handoff.created_at).getTime();
  if (ageMs > AUTO_OPEN_MAX_AGE_MS || document.visibilityState !== "visible") {
    elements.handoffCountdown.hidden = true;
    showToast("Nexuss sent a link. Tap to open it.");
    return;
  }

  /* Fresh and foregrounded: open it without asking, which is the P5.1
     contract. The card stays as the fallback if the browser blocks it. */
  let remaining = Math.ceil(AUTO_OPEN_DELAY_MS / 1000);
  elements.handoffCountdown.hidden = false;
  elements.handoffCountdown.textContent = `Opening in ${remaining}s · tap to open now`;
  countdownTimer = setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      clearInterval(countdownTimer);
      countdownTimer = null;
      return;
    }
    elements.handoffCountdown.textContent = `Opening in ${remaining}s · tap to open now`;
  }, 1000);

  autoOpenTimer = setTimeout(() => {
    elements.handoffCountdown.textContent = "If nothing happened, tap the button above.";
    window.location.assign(handoff.launch_url);
  }, AUTO_OPEN_DELAY_MS);
}

async function poll() {
  if (!deviceId || !deviceToken || inFlight) return;
  inFlight = true;
  try {
    const [approvalResponse, handoffResponse] = await Promise.all([
      fetch("/v1/mobile/pending", { headers: mobileHeaders(), cache: "no-store" }),
      fetch("/v1/mobile/handoffs", { headers: mobileHeaders(), cache: "no-store" }),
    ]);

    if (approvalResponse.status === 401 || handoffResponse.status === 401) {
      clearPairing();
      setLinkState(null);
      showToast("Phone session expired. Pair again.");
      return;
    }
    if (!approvalResponse.ok) {
      throw new Error(`Approvals unavailable (${approvalResponse.status})`);
    }
    if (!handoffResponse.ok) {
      throw new Error(`Handoffs unavailable (${handoffResponse.status})`);
    }

    const approvals = await approvalResponse.json();
    const handoffs = await handoffResponse.json();

    setLinkState(null);
    pollDelay = POLL_INTERVAL_MS;
    renderApproval(approvals[0] || null);

    /* Newest wins. The server sorts ascending, so take the tail. */
    if (handoffs.length > 0) {
      renderHandoff(handoffs[handoffs.length - 1]);
    }
  } catch (error) {
    /* Back off instead of firing a toast every 1.5s on a dropped LAN link. */
    pollDelay = Math.min(pollDelay * 2, POLL_BACKOFF_MAX_MS);
    const detail = error instanceof Error ? error.message : "Nexuss unreachable";
    setLinkState(`${detail} · retrying in ${Math.round(pollDelay / 1000)}s`);
  } finally {
    inFlight = false;
    if (deviceId && deviceToken) schedulePoll();
  }
}

async function decide(decision) {
  if (!pendingApproval) return;
  elements.approve.disabled = true;
  elements.deny.disabled = true;
  try {
    const response = await fetch(`/v1/mobile/tasks/${pendingApproval.task_id}/decision`, {
      method: "POST",
      headers: mobileHeaders(),
      body: JSON.stringify({
        approval_id: pendingApproval.approval_id,
        approval_token: pendingApproval.approval_token,
        payload_sha256: pendingApproval.payload_sha256,
        decision,
      }),
    });
    if (!response.ok) throw new Error(`Decision failed (${response.status}): ${await response.text()}`);
    const task = await response.json();
    renderApproval(null);
    showToast(decision === "approve" ? `Command ${task.state}.` : "Action denied. No command executed.");
  } catch (error) {
    showToast(error instanceof Error ? error.message : "Approval failed");
  } finally {
    elements.approve.disabled = false;
    elements.deny.disabled = false;
    startPolling();
  }
}

elements.pairForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.pairButton.disabled = true;
  try {
    const response = await fetch("/v1/mobile/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pairing_code: elements.pairingCode.value.trim(),
        device_label: elements.deviceLabel.value.trim(),
      }),
    });
    if (!response.ok) throw new Error(`Pairing failed (${response.status}): ${await response.text()}`);
    const session = await response.json();
    deviceId = session.device_id;
    deviceToken = session.device_token;
    localStorage.setItem("nexuss-mobile-device-id", deviceId);
    localStorage.setItem("nexuss-mobile-device-token", deviceToken);
    setPaired(true);
    showToast("Phone paired with this Nexuss session.");
    void requestWakeLock();
    startPolling();
  } catch (error) {
    showToast(error instanceof Error ? error.message : "Pairing failed");
  } finally {
    elements.pairButton.disabled = false;
  }
});

elements.approve.addEventListener("click", () => void decide("approve"));
elements.deny.addEventListener("click", () => void decide("reject"));
elements.handoffDismiss.addEventListener("click", () => clearHandoff());
elements.handoffOpen.addEventListener("click", () => {
  clearTimeout(autoOpenTimer);
  clearInterval(countdownTimer);
  elements.handoffCountdown.hidden = true;
});

/* Returning to the foreground must reconcile immediately. Background tabs are
   throttled to roughly one timer per minute, so the queued poll is stale. */
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  if (!deviceId || !deviceToken) return;
  void requestWakeLock();
  startPolling();
});

window.addEventListener("pageshow", () => {
  if (deviceId && deviceToken) startPolling();
});

window.addEventListener("online", () => {
  if (deviceId && deviceToken) startPolling();
});

if (deviceId && deviceToken) {
  setPaired(true);
  void requestWakeLock();
  startPolling();
} else {
  setPaired(false);
}

/* Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary. */
"use strict";

const elements = {
  connection: document.querySelector("#connection-state"),
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
  toast: document.querySelector("#toast"),
};

let deviceId = localStorage.getItem("nexuss-mobile-device-id");
let deviceToken = localStorage.getItem("nexuss-mobile-device-token");
let pendingApproval = null;
let pollingTimer = null;
let toastTimer = null;

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

function setPaired(paired) {
  elements.connection.classList.toggle("paired", paired);
  elements.connection.querySelector("span").textContent = paired ? "Paired" : "Not paired";
  elements.pairCard.hidden = paired;
  elements.stage.hidden = !paired;
}

function clearPairing() {
  deviceId = null;
  deviceToken = null;
  localStorage.removeItem("nexuss-mobile-device-id");
  localStorage.removeItem("nexuss-mobile-device-token");
  setPaired(false);
  if (pollingTimer) clearInterval(pollingTimer);
}

function renderApproval(approval) {
  pendingApproval = approval || null;
  elements.standby.hidden = Boolean(approval);
  elements.card.hidden = !approval;
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

async function pollPending() {
  if (!deviceId || !deviceToken) return;
  try {
    const response = await fetch("/v1/mobile/pending", { headers: mobileHeaders(), cache: "no-store" });
    if (response.status === 401) {
      clearPairing();
      showToast("Phone session expired. Pair again.");
      return;
    }
    if (!response.ok) throw new Error(`Pending approval request failed (${response.status})`);
    const approvals = await response.json();
    renderApproval(approvals[0] || null);
  } catch (error) {
    showToast(error instanceof Error ? error.message : "Nexuss approval service unavailable");
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
    void pollPending();
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
    await pollPending();
    pollingTimer = setInterval(pollPending, 1500);
  } catch (error) {
    showToast(error instanceof Error ? error.message : "Pairing failed");
  } finally {
    elements.pairButton.disabled = false;
  }
});

elements.approve.addEventListener("click", () => void decide("approve"));
elements.deny.addEventListener("click", () => void decide("reject"));

if (deviceId && deviceToken) {
  setPaired(true);
  void pollPending();
  pollingTimer = setInterval(pollPending, 1500);
} else {
  setPaired(false);
}

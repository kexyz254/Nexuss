"use strict";

const fs = require("fs");

const app = fs.readFileSync(
  "src/nexuss/ui/app.js",
  "utf8",
);
const platform = fs.readFileSync(
  "src/nexuss/ui/nexuss_ui_platform.js",
  "utf8",
);

function requireContract(condition, message) {
  if (!condition) throw new Error(message);
}

const submitStart = app.indexOf(
  'elements.form.addEventListener("submit", (event) => {',
);
const submitEnd = app.indexOf(
  'elements.input.addEventListener("keydown"',
  submitStart,
);
const submit = app.slice(submitStart, submitEnd);

requireContract(submitStart >= 0, "submit handler missing");
requireContract(
  submit.includes("submitUnifiedUserTurn(utterance, channel)"),
  "normal submit does not use unified turn",
);
requireContract(
  !submit.includes("understandAndExecute"),
  "legacy gateway remains in normal submit",
);
requireContract(
  app.includes('fetch("/v1/interactions"'),
  "unified interaction endpoint missing",
);
requireContract(
  app.includes("No duplicate interaction was created"),
  "duplicate-turn guard missing",
);
requireContract(
  platform.includes('initialMode = "hidden"'),
  "system windows do not default hidden",
);
requireContract(
  platform.includes("existingState.dataset.nxProfessionalWorkspace"),
  "existing topbar status is not reused",
);

console.log(
  "PASS: P6.11 unified submission and workspace contracts verified.",
);

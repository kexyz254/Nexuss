/* P6.18 CHAT FILE WORKSPACE */

(() => {
  const attachButton = document.querySelector("#file-attach-button");
  const input = document.querySelector("#file-input");
  const tray = document.querySelector("#file-attachment-tray");
  const form = document.querySelector("#command-form");
  const commandInput = document.querySelector("#command-input");

  if (!attachButton || !input || !tray || !form || !commandInput) return;

  const MAX_FILES = 10;
  const MAX_BYTES = 25 * 1024 * 1024;
  let selected = [];

  function bytesLabel(value) {
    const size = Number(value || 0);
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }

  function renderSelection() {
    tray.replaceChildren();
    tray.hidden = selected.length === 0;

    for (const [index, file] of selected.entries()) {
      const chip = document.createElement("div");
      chip.className = "file-selection-chip";

      const icon = document.createElement("span");
      icon.className = "file-selection-icon";
      icon.textContent = (file.name.split(".").pop() || "FILE")
        .slice(0, 4)
        .toUpperCase();

      const copy = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = file.name;
      const meta = document.createElement("small");
      meta.textContent = `${bytesLabel(file.size)} · local attachment`;
      copy.append(name, meta);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `Remove ${file.name}`);
      remove.addEventListener("click", () => {
        selected.splice(index, 1);
        renderSelection();
      });

      chip.append(icon, copy, remove);
      tray.append(chip);
    }
  }

  function addFiles(files) {
    const incoming = Array.from(files || []);
    for (const file of incoming) {
      if (selected.length >= MAX_FILES) {
        showToast("A chat turn may contain at most 10 files.");
        break;
      }
      if (file.size > MAX_BYTES) {
        addMessage(
          "assistant",
          `${file.name} is larger than the 25 MB chat-file limit.`,
          true,
        );
        continue;
      }
      const duplicate = selected.some(
        (item) => item.name === file.name
          && item.size === file.size
          && item.lastModified === file.lastModified,
      );
      if (!duplicate) selected.push(file);
    }
    input.value = "";
    renderSelection();
    commandInput.focus();
  }

  async function uploadFiles() {
    await ensurePersistentConversation();

    const records = [];
    for (const file of selected) {
      const headers = {
        ...apiHeaders(),
        "Content-Type": file.type || "application/octet-stream",
        "X-Nexuss-File-Name": encodeURIComponent(file.name),
      };
      const response = await fetch(
        `/v1/conversations/${encodeURIComponent(activeConversationId)}/attachments`,
        {
          method: "POST",
          headers,
          body: file,
        },
      );

      if (!response.ok) {
        let message = await response.text();
        try {
          const body = JSON.parse(message);
          message = body?.detail?.message || body?.detail || message;
        } catch {
          // Keep the response text.
        }
        throw new Error(
          `File upload failed for ${file.name} (${response.status}): ${message}`,
        );
      }
      records.push(await response.json());
    }
    return records;
  }

  function requestedPackage(text) {
    const normalized = String(text || "").trim();
    return (
      /^(?:please\s+|can\s+you\s+|could\s+you\s+)?(?:package|bundle|zip)\b/i
        .test(normalized)
      || /\bcreate\s+(?:a\s+)?zip\b/i.test(normalized)
      || /\b(?:package|bundle)\s+(?:the\s+)?(?:attached\s+)?files\b/i
        .test(normalized)
    );
  }

  function packageName(text) {
    const match = text.match(
      /\b(?:named|called|as)\s+([A-Za-z0-9._ -]+?\.zip)\b/i,
    );
    return match?.[1]?.trim() || "nexuss-files.zip";
  }

  async function packageAttachments(records, utterance) {
    const response = await fetch(
      `/v1/conversations/${encodeURIComponent(activeConversationId)}/artifacts/package`,
      {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({
          attachment_ids: records.map((item) => item.attachment_id),
          name: packageName(utterance),
          instruction: utterance,
        }),
      },
    );
    if (!response.ok) {
      throw new Error(
        `Artifact package failed (${response.status}): ${await response.text()}`,
      );
    }
    return response.json();
  }

  async function submitFileTurn(event) {
    if (!selected.length) return;
    if (chatTurnInProgress()) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }

    event.preventDefault();
    event.stopImmediatePropagation();

    const originalFiles = [...selected];
    const utterance = commandInput.value.trim()
      || "Review the attached files and summarize the important information.";

    commandInput.value = "";
    commandInput.style.height = "auto";
    setBusy(true);
    stopSpeaking();
    let activity = null;
    let phase = null;
    let finished = false;

    try {
      await ensurePersistentConversation();

      const placeholderAttachments = originalFiles.map((file) => ({
        name: file.name,
        media_type: file.type || "file",
        size_bytes: file.size,
        extraction_status: "uploading",
      }));
      addMessage(
        "user",
        utterance,
        false,
        { attachments: placeholderAttachments },
      );

      activity = document.createElement("details");
      activity.className = "message assistant-message workflow-progress";
      activity.dataset.state = "running";
      activity.open = true;
      phase = document.createElement("summary");
      phase.setAttribute("aria-live", "polite");
      phase.textContent = `Uploading ${originalFiles.length} file(s)…`;
      activity.append(phase);
      elements.timeline.append(activity);
      const records = await uploadFiles();
      phase.textContent = "Files received — preparing the requested analysis";

      if (requestedPackage(utterance)) {
        phase.textContent = "Packaging the selected files…";
        const artifact = await packageAttachments(records, utterance);
        addMessage(
          "assistant",
          `Packaged ${records.length} attached file${records.length === 1 ? "" : "s"} into ${artifact.name}.`,
          false,
          { artifact },
        );
        finished = true;
        selected = [];
        renderSelection();
        setBusy(false);
        void refreshConversationList();
        return;
      }

      const response = await fetch(
        `/v1/conversations/${encodeURIComponent(activeConversationId)}/turns`,
        {
          method: "POST",
          headers: apiHeaders(),
          body: JSON.stringify({
            request_id: crypto.randomUUID(),
            user_session_id: sessionId,
            text: utterance,
            provider_id: "auto",
            external_processing_approved: true,
            attachment_ids: records.map((item) => item.attachment_id),
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
          || `File-aware conversation failed (${response.status}).`,
        );
      }

      const turn = await response.json();
      activeConversationRecord = turn.conversation;
      activeConversationPersisted = true;
      updateConversationHeader(activeConversationRecord);
      void refreshConversationList();

      addMessage(
        "assistant",
        {
          text: turn.assistant_message.text,
          blocks: [],
          cognitive: {
            provider: turn.provider_id || "Nexuss",
            model: turn.model,
            mode: "file intelligence",
            trust: [
              "Attached originals remained local and unchanged.",
              "Only bounded extracted text was supplied to reasoning.",
              "Nexuss treated file content as untrusted evidence.",
            ],
          },
        },
        false,
        { rich: true },
      );

      finished = true;
      selected = [];
      renderSelection();
    } catch (error) {
      addMessage(
        "assistant",
        error instanceof Error
          ? error.message
          : "Chat-file processing failed closed.",
        true,
      );
    } finally {
      if (activity) {
        activity.dataset.state = "finished";
        activity.open = !finished;
        phase.textContent = finished ? "File processing completed" : "File processing interrupted";
      }
      setBusy(false);
      commandInput.focus();
    }
  }

  attachButton.addEventListener("click", () => input.click());
  input.addEventListener("change", () => addFiles(input.files));
  form.addEventListener("submit", submitFileTurn, true);

  window.NexussFiles = Object.freeze({
    selected: () => [...selected],
    clear: () => {
      selected = [];
      renderSelection();
    },
  });
})();

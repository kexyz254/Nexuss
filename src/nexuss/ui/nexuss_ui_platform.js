/* P6.10F PROFESSIONAL MULTITASKING WORKSPACE */
(() => {
  "use strict";

  const VERSION = "1.2.0";
  const STORAGE_KEY = "nexuss.ui.platform.layout.v2";
  const LEGACY_STORAGE_KEY = "nexuss.ui.platform.layout.v1";
  const SETTINGS_KEY = "nexuss.ui.platform.settings.v1";
  const MOBILE_QUERY = "(max-width: 760px)";
  const MIN_WIDTH = 320;
  const MIN_HEIGHT = 220;
  const EDGE = 10;
  const APPROVAL_Z = 10000;

  const runtime = {
    z: 2600,
    windows: new Map(),
    notifications: [],
    currentApproval: null,
    currentReceipt: null,
    currentTask: null,
    pendingCount: 0,
  };

  const iconPaths = Object.freeze({
    chat: '<path d="M4 5h16v11H8l-4 4V5Z"/><path d="M8 9h8M8 12h5"/>',
    action: '<circle cx="12" cy="12" r="8"/><path d="m13 6-5 7h4l-1 5 5-7h-4l1-5Z"/>',
    task: '<path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    activity: '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
    approval: '<path d="M12 3 5 6v5c0 4.6 2.8 8 7 10 4.2-2 7-5.4 7-10V6l-7-3Z"/><path d="m9 12 2 2 4-4"/>',
    receipt: '<path d="M6 3h9l3 3v15H6V3Z"/><path d="M14 3v4h4M9 12h6M9 16h4"/>',
    media: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3V9Z"/>',
    research: '<circle cx="10" cy="10" r="6"/><path d="m14.5 14.5 5 5M7 10h6M10 7v6"/>',
    note: '<path d="M6 3h9l3 3v15H6V3Z"/><path d="M14 3v4h4M9 11h6M9 15h6"/>',
    code: '<path d="m8 8-4 4 4 4M16 8l4 4-4 4M14 5l-4 14"/>',
    files: '<path d="M3 6h7l2 2h9v11H3V6Z"/>',
    mobile: '<rect x="7" y="2.5" width="10" height="19" rx="2"/><path d="M10 5h4M11 18.5h2"/>',
    diagnostics: '<path d="M3 12h4l2-5 4 10 2-5h6"/><circle cx="12" cy="12" r="9"/>',
    bell: '<path d="M6 16h12l-2-3V9a4 4 0 0 0-8 0v4l-2 3Z"/><path d="M10 19h4"/>',
    settings: '<path d="M4 7h10M18 7h2M4 17h2M10 17h10M14 5v4M8 15v4"/>',
    grid: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
    search: '<circle cx="10" cy="10" r="6"/><path d="m14.5 14.5 5 5"/>',
    close: '<path d="m7 7 10 10M17 7 7 17"/>',
    minimize: '<path d="M6 15h12"/>',
    expand: '<path d="M8 4H4v4M16 4h4v4M8 20H4v-4M16 20h4v-4"/>',
    restore: '<path d="M7 7h10v10H7V7Z"/><path d="M10 4h10v10"/>',
    external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 13v7H4V6h7"/>',
  });

  function svgIcon(name) {
    const paths = iconPaths[name] || iconPaths.grid;
    return (
      '<svg viewBox="0 0 24 24" aria-hidden="true" '
      + 'focusable="false" fill="none" stroke="currentColor" '
      + 'stroke-width="1.8" stroke-linecap="round" '
      + `stroke-linejoin="round">${paths}</svg>`
    );
  }

  function safeNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function safeMode(value) {
    return new Set(["expanded", "mini", "hidden"]).has(value)
      ? value
      : "expanded";
  }

  function readJson(key, fallback) {
    try {
      const parsed = JSON.parse(localStorage.getItem(key) || "null");
      return parsed && typeof parsed === "object" ? parsed : fallback;
    } catch {
      return fallback;
    }
  }

  function readLayout() {
    let raw = readJson(STORAGE_KEY, null);

    if (!raw) {
      const legacy = readJson(LEGACY_STORAGE_KEY, {});
      raw = legacy.activity ? { activity: legacy.activity } : {};
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(raw));
      } catch {
        /* Layout migration is optional and contains presentation data only. */
      }
    }

    const clean = {};
    for (const [id, value] of Object.entries(raw)) {
      if (!value || typeof value !== "object") continue;
      clean[id] = {
        mode: safeMode(value.mode),
        left: safeNumber(value.left, null),
        top: safeNumber(value.top, null),
        width: Math.max(MIN_WIDTH, safeNumber(value.width, 420)),
        height: Math.max(MIN_HEIGHT, safeNumber(value.height, 440)),
      };
    }
    return clean;
  }

  function readSettings() {
    const raw = readJson(SETTINGS_KEY, {});
    return {
      compactDock: Boolean(raw.compactDock),
      reducedMotion: Boolean(raw.reducedMotion),
    };
  }

  let layout = readLayout();
  let settings = readSettings();

  function writeLayout() {
    const safe = {};
    for (const [id, value] of Object.entries(layout)) {
      safe[id] = {
        mode: safeMode(value.mode),
        left: safeNumber(value.left, null),
        top: safeNumber(value.top, null),
        width: Math.max(MIN_WIDTH, safeNumber(value.width, 420)),
        height: Math.max(MIN_HEIGHT, safeNumber(value.height, 440)),
      };
    }
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(safe));
    } catch {
      /* Presentation persistence must never break Nexuss. */
    }
  }

  function writeSettings() {
    try {
      localStorage.setItem(
        SETTINGS_KEY,
        JSON.stringify({
          compactDock: Boolean(settings.compactDock),
          reducedMotion: Boolean(settings.reducedMotion),
        }),
      );
    } catch {
      /* Presentation preferences are optional. */
    }
  }

  function isMobile() {
    return window.matchMedia(MOBILE_QUERY).matches;
  }

  function clamp(value, minimum, maximum) {
    return Math.min(Math.max(value, minimum), maximum);
  }

  function createButton({
    label,
    icon,
    className = "",
    title = label,
    onClick,
  }) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.title = title;
    button.setAttribute("aria-label", label);
    if (icon) button.innerHTML = svgIcon(icon);
    if (!icon) button.textContent = label;
    if (onClick) button.addEventListener("click", onClick);
    return button;
  }

  function setText(element, value, fallback = "—") {
    if (element) element.textContent = value == null || value === ""
      ? fallback
      : String(value);
  }

  function ensureTaskbar() {
    let taskbar = document.getElementById("nx-window-taskbar");
    if (taskbar) return taskbar;
    taskbar = document.createElement("div");
    taskbar.id = "nx-window-taskbar";
    taskbar.className = "nx-window-taskbar";
    taskbar.setAttribute("aria-label", "Hidden Nexuss workspaces");
    document.body.append(taskbar);
    return taskbar;
  }

  function taskbarButton(id, title, icon, restore) {
    const taskbar = ensureTaskbar();
    let button = taskbar.querySelector(`[data-nx-restore="${id}"]`);
    if (!button) {
      button = createButton({
        label: `Restore ${title}`,
        icon,
        className: "nx-taskbar-button",
        title: `Restore ${title}`,
        onClick: restore,
      });
      button.dataset.nxRestore = id;
      const label = document.createElement("span");
      label.textContent = title;
      button.append(label);
      taskbar.append(button);
    }
    button.hidden = false;
    return button;
  }

  function removeTaskbarButton(id) {
    const button = document.querySelector(`[data-nx-restore="${id}"]`);
    if (button) button.hidden = true;
  }

  class WindowManager {
    create({
      id,
      title,
      subtitle,
      icon = "grid",
      width = 440,
      height = 480,
      left = null,
      top = null,
      initialMode = "hidden",
      render = null,
    }) {
      const existing = runtime.windows.get(id);
      if (existing) return existing;

      const windowElement = document.createElement("section");
      windowElement.className = "nx-platform-window";
      windowElement.dataset.nxWindow = id;
      windowElement.dataset.mode = "expanded";
      windowElement.hidden = true;
      windowElement.setAttribute("role", "dialog");
      windowElement.setAttribute("aria-modal", "false");
      windowElement.setAttribute("aria-label", title);

      const header = document.createElement("header");
      header.className = "nx-window-header";

      const identity = document.createElement("div");
      identity.className = "nx-window-identity";
      const iconBox = document.createElement("span");
      iconBox.className = "nx-window-icon";
      iconBox.innerHTML = svgIcon(icon);
      const copy = document.createElement("div");
      const heading = document.createElement("strong");
      heading.textContent = title;
      const description = document.createElement("small");
      description.textContent = subtitle || "Nexuss workspace";
      copy.append(heading, description);
      identity.append(iconBox, copy);

      const controls = document.createElement("div");
      controls.className = "nx-window-controls";

      const content = document.createElement("div");
      content.className = "nx-window-content";

      const record = {
        id,
        title,
        icon,
        element: windowElement,
        header,
        content,
        render,
        drag: null,
      };

      controls.append(
        createButton({
          label: `Minimize ${title}`,
          icon: "minimize",
          title: "Minimize",
          onClick: () => this.minimize(id),
        }),
        createButton({
          label: `Restore ${title}`,
          icon: "expand",
          title: "Expand",
          onClick: () => this.restore(id),
        }),
        createButton({
          label: `Hide ${title}`,
          icon: "close",
          title: "Hide and keep available in the taskbar",
          onClick: () => this.hide(id),
        }),
      );

      header.append(identity, controls);
      windowElement.append(header, content);
      document.body.append(windowElement);

      const saved = layout[id] || null;
      layout[id] = {
        mode: saved ? safeMode(saved.mode) : safeMode(initialMode),
        left: saved?.left ?? left,
        top: saved?.top ?? top,
        width: Math.max(
          MIN_WIDTH,
          safeNumber(saved?.width, width),
        ),
        height: Math.max(
          MIN_HEIGHT,
          safeNumber(saved?.height, height),
        ),
      };

      this.attachDrag(record);
      this.attachResize(record);
      windowElement.addEventListener("pointerdown", () => this.focus(id));
      runtime.windows.set(id, record);
      this.apply(id);
      return record;
    }

    attachDrag(record) {
      record.header.addEventListener("pointerdown", (event) => {
        if (
          isMobile()
          || event.button !== 0
          || event.target.closest("button, a, input, textarea, select")
        ) {
          return;
        }

        const rectangle = record.element.getBoundingClientRect();
        record.drag = {
          pointerId: event.pointerId,
          x: event.clientX,
          y: event.clientY,
          left: rectangle.left,
          top: rectangle.top,
        };
        record.header.setPointerCapture(event.pointerId);
        record.element.classList.add("is-dragging");
        this.focus(record.id);
        event.preventDefault();
      });

      record.header.addEventListener("pointermove", (event) => {
        if (!record.drag || record.drag.pointerId !== event.pointerId) return;
        const rectangle = record.element.getBoundingClientRect();
        const maximumLeft = Math.max(
          EDGE,
          window.innerWidth - rectangle.width - EDGE,
        );
        const maximumTop = Math.max(
          EDGE,
          window.innerHeight - rectangle.height - EDGE,
        );
        const state = layout[record.id];
        state.left = clamp(
          record.drag.left + event.clientX - record.drag.x,
          EDGE,
          maximumLeft,
        );
        state.top = clamp(
          record.drag.top + event.clientY - record.drag.y,
          EDGE,
          maximumTop,
        );
        record.element.style.setProperty("--nx-left", `${state.left}px`);
        record.element.style.setProperty("--nx-top", `${state.top}px`);
      });

      const end = (event) => {
        if (!record.drag || record.drag.pointerId !== event.pointerId) return;
        record.drag = null;
        record.element.classList.remove("is-dragging");
        writeLayout();
      };
      record.header.addEventListener("pointerup", end);
      record.header.addEventListener("pointercancel", end);
    }

    attachResize(record) {
      if (typeof ResizeObserver !== "function") return;
      const observer = new ResizeObserver(() => {
        if (
          record.element.hidden
          || record.element.dataset.mode !== "expanded"
          || isMobile()
        ) {
          return;
        }
        const rectangle = record.element.getBoundingClientRect();
        const state = layout[record.id];
        state.left = Math.round(rectangle.left);
        state.top = Math.round(rectangle.top);
        state.width = Math.max(MIN_WIDTH, Math.round(rectangle.width));
        state.height = Math.max(MIN_HEIGHT, Math.round(rectangle.height));
        writeLayout();
      });
      observer.observe(record.element);
    }

    apply(id) {
      const record = runtime.windows.get(id);
      if (!record) return;
      const state = layout[id];
      record.element.dataset.mode = state.mode;

      if (state.mode === "hidden") {
        record.element.hidden = true;
        taskbarButton(id, record.title, record.icon, () => this.restore(id));
        return;
      }

      record.element.hidden = false;
      removeTaskbarButton(id);

      if (!isMobile()) {
        const defaultLeft = Math.max(
          EDGE,
          window.innerWidth - state.width - 28,
        );
        const defaultTop = 86;
        state.left = safeNumber(state.left, defaultLeft);
        state.top = safeNumber(state.top, defaultTop);
        state.width = clamp(state.width, MIN_WIDTH, window.innerWidth - 20);
        state.height = clamp(state.height, MIN_HEIGHT, window.innerHeight - 20);
        state.left = clamp(
          state.left,
          EDGE,
          Math.max(EDGE, window.innerWidth - state.width - EDGE),
        );
        state.top = clamp(
          state.top,
          EDGE,
          Math.max(EDGE, window.innerHeight - state.height - EDGE),
        );
        record.element.style.setProperty("--nx-left", `${state.left}px`);
        record.element.style.setProperty("--nx-top", `${state.top}px`);
        record.element.style.setProperty("--nx-width", `${state.width}px`);
        record.element.style.setProperty("--nx-height", `${state.height}px`);
      }

      if (typeof record.render === "function") record.render(record.content);
      this.focus(id);
      writeLayout();
    }

    focus(id) {
      const record = runtime.windows.get(id);
      if (!record || record.element.hidden) return;
      runtime.z += 1;
      record.element.style.setProperty("--nx-z", String(runtime.z));
    }

    show(id) {
      const record = runtime.windows.get(id);
      if (!record) return;
      layout[id].mode = "expanded";
      this.apply(id);
    }

    minimize(id) {
      const record = runtime.windows.get(id);
      if (!record) return;
      layout[id].mode = "mini";
      this.apply(id);
    }

    hide(id) {
      const record = runtime.windows.get(id);
      if (!record) return;
      layout[id].mode = "hidden";
      this.apply(id);
    }

    restore(id) {
      const record = runtime.windows.get(id);
      if (!record) return;
      layout[id].mode = "expanded";
      this.apply(id);
    }

    reset() {
      for (const [id, record] of runtime.windows) {
        delete layout[id];
        layout[id] = {
          mode: "expanded",
          left: null,
          top: null,
          width: 440,
          height: 480,
        };
        record.element.hidden = true;
        removeTaskbarButton(id);
      }
      try {
        localStorage.removeItem(STORAGE_KEY);
      } catch {
        /* optional */
      }
      enhanceActivity(true);
    }
  }

  const manager = new WindowManager();

  function focusCore(mode) {
    if (typeof setFocusDeckMode === "function") {
      setFocusDeckMode(mode);
    } else {
      const selector = mode === "conversation"
        ? "#conversation-app"
        : "#action-control-app";
      const element = document.querySelector(selector);
      if (element) element.hidden = false;
    }

    const target = document.querySelector(
      mode === "conversation"
        ? "#conversation-app"
        : "#action-control-app",
    );
    target?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    target?.classList.add("nx-focus-highlight");
    window.setTimeout(
      () => target?.classList.remove("nx-focus-highlight"),
      700,
    );
  }

  function openReceiptTab() {
    focusCore("inspector");
    document.querySelector('[data-tab="receipt"]')?.click();
    renderReceiptCenter();
    manager.show("receipts");
  }

  function openMedia() {
    const workspace = document.getElementById("p5-workspace");
    const media = document.getElementById("media-dock");
    if (workspace) workspace.hidden = false;
    if (media) media.hidden = false;
    if (window.NexussMediaWorkspace?.expand) {
      window.NexussMediaWorkspace.expand();
    } else if (window.NexussWorkspace?.float) {
      window.NexussWorkspace.float("media");
    }
    media?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function openResearch() {
    const workspace = document.getElementById("p5-workspace");
    const drawer = document.getElementById("knowledge-drawer");
    if (workspace) workspace.hidden = false;
    if (drawer) drawer.hidden = false;
    if (window.NexussWorkspace?.float) {
      window.NexussWorkspace.float("knowledge");
    }
    drawer?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function prefillCommand(text) {
    focusCore("conversation");
    const input = document.getElementById("command-input");
    if (!input) return;
    input.value = text;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.focus();
  }

  function openMobile() {
    window.open("/mobile", "_blank", "noopener,noreferrer");
  }

  const capabilities = Object.freeze([
    {
      id: "chat",
      label: "Chat",
      description: "Conversation and voice interaction",
      icon: "chat",
      group: "Core",
      status: "available",
      action: () => focusCore("conversation"),
    },
    {
      id: "action",
      label: "Action Control",
      description: "Intent, policy, evidence and lifecycle",
      icon: "action",
      group: "Core",
      status: "available",
      action: () => focusCore("inspector"),
    },
    {
      id: "tasks",
      label: "Tasks",
      description: "Authoritative task lifecycle and retry readiness",
      icon: "task",
      group: "Core",
      status: "available",
      action: () => manager.show("tasks"),
    },
    {
      id: "activity",
      label: "Activity",
      description: "Recent unified interactions",
      icon: "activity",
      group: "Core",
      status: "available",
      action: () => showActivity(),
    },
    {
      id: "approvals",
      label: "Approvals",
      description: "Pending exact-payload approvals",
      icon: "approval",
      group: "Core",
      status: "available",
      action: () => manager.show("approvals"),
    },
    {
      id: "receipts",
      label: "Receipts",
      description: "Verified execution records",
      icon: "receipt",
      group: "Core",
      status: "available",
      action: openReceiptTab,
    },
    {
      id: "media",
      label: "Media",
      description: "YouTube discovery and playback workspace",
      icon: "media",
      group: "Intelligence",
      status: "available",
      action: openMedia,
    },
    {
      id: "research",
      label: "Research",
      description: "Cited public research workspace",
      icon: "research",
      group: "Intelligence",
      status: "available",
      action: openResearch,
    },
    {
      id: "notes",
      label: "Notes",
      description: "Prepare a governed managed note",
      icon: "note",
      group: "Productivity",
      status: "guided",
      action: () => prefillCommand(
        "Create a managed note named project-update with the content: ",
      ),
    },
    {
      id: "github",
      label: "GitHub",
      description: "Repository intelligence and governed writes",
      icon: "code",
      group: "Engineering",
      status: "guided",
      action: () => prefillCommand("Show my GitHub repositories."),
    },
    {
      id: "files",
      label: "Workspace",
      description: "Inspect the local engineering workspace",
      icon: "files",
      group: "Engineering",
      status: "guided",
      action: () => prefillCommand(
        "Inspect the current workspace status and summarize verified evidence.",
      ),
    },
    {
      id: "mobile",
      label: "Mobile",
      description: "Open trusted mobile approval interface",
      icon: "mobile",
      group: "Devices",
      status: "available",
      action: openMobile,
    },
    {
      id: "diagnostics",
      label: "Diagnostics",
      description: "Health, UI errors and runtime checks",
      icon: "diagnostics",
      group: "Administration",
      status: "available",
      action: () => manager.show("diagnostics"),
    },
    {
      id: "notifications",
      label: "Notifications",
      description: "In-memory status and failure messages",
      icon: "bell",
      group: "Administration",
      status: "available",
      action: () => manager.show("notifications"),
    },
    {
      id: "settings",
      label: "Settings",
      description: "Safe UI layout and accessibility controls",
      icon: "settings",
      group: "Administration",
      status: "available",
      action: () => manager.show("settings"),
    },
  ]);

  const roadmapCapabilities = Object.freeze([
    ["Email", "Productivity", "Connector expansion"],
    ["Calendar", "Productivity", "Connector expansion"],
    ["Contacts", "Productivity", "Connector expansion"],
    ["Documents", "Productivity", "Native workspace planned"],
    ["Spreadsheets", "Productivity", "Native workspace planned"],
    ["Presentations", "Productivity", "Native workspace planned"],
    ["Automations", "Agentic", "Governed scheduler planned"],
    ["Devices", "Devices", "Android companion planned"],
    ["Cloud", "Infrastructure", "Governed operations planned"],
    ["Finance", "Intelligence", "Read-side controls planned"],
    ["Health", "Wellness", "Dedicated safeguards planned"],
    ["Plugins", "Ecosystem", "Signed extension model planned"],
  ]);

  function buildDock() {
    if (document.getElementById("nx-capability-dock")) return;
    const dock = document.createElement("nav");
    dock.id = "nx-capability-dock";
    dock.className = "nx-capability-dock";
    dock.setAttribute("aria-label", "Nexuss capability dock");

    const primaryIds = [
      "chat",
      "action",
      "tasks",
      "activity",
      "approvals",
      "receipts",
      "media",
      "research",
      "diagnostics",
    ];

    for (const id of primaryIds) {
      const capability = capabilities.find((item) => item.id === id);
      if (!capability) continue;
      const button = createButton({
        label: capability.label,
        icon: capability.icon,
        className: "nx-dock-button",
        title: `${capability.label} — ${capability.description}`,
        onClick: capability.action,
      });
      button.dataset.capabilityId = id;
      const label = document.createElement("span");
      label.textContent = capability.label;
      button.append(label);
      if (id === "approvals") {
        const badge = document.createElement("b");
        badge.className = "nx-dock-badge";
        badge.hidden = true;
        badge.dataset.approvalBadge = "true";
        button.append(badge);
      }
      dock.append(button);
    }

    dock.append(
      createButton({
        label: "Command palette",
        icon: "search",
        className: "nx-dock-button",
        title: "Search capabilities and commands (Ctrl+K)",
        onClick: () => showCommandPalette(),
      }),
      createButton({
        label: "All capabilities",
        icon: "grid",
        className: "nx-dock-button",
        title: "Open capability launcher",
        onClick: () => manager.show("capabilities"),
      }),
    );

    document.body.append(dock);
  }

  function renderCapabilityLauncher() {
    const record = runtime.windows.get("capabilities");
    if (!record) return;
    const content = record.content;
    content.replaceChildren();

    const introduction = document.createElement("p");
    introduction.className = "nx-center-intro";
    introduction.textContent = (
      "Available capabilities open immediately. Guided capabilities prepare "
      + "a command for your review and never submit automatically."
    );
    content.append(introduction);

    const groups = new Map();
    for (const capability of capabilities) {
      if (!groups.has(capability.group)) groups.set(capability.group, []);
      groups.get(capability.group).push(capability);
    }

    for (const [group, entries] of groups) {
      const section = document.createElement("section");
      section.className = "nx-capability-group";
      const heading = document.createElement("h3");
      heading.textContent = group;
      const grid = document.createElement("div");
      grid.className = "nx-capability-grid";

      for (const capability of entries) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "nx-capability-card";
        button.addEventListener("click", capability.action);
        const icon = document.createElement("span");
        icon.innerHTML = svgIcon(capability.icon);
        const copy = document.createElement("span");
        const label = document.createElement("strong");
        label.textContent = capability.label;
        const detail = document.createElement("small");
        detail.textContent = capability.description;
        const status = document.createElement("em");
        status.textContent = capability.status === "available"
          ? "Available"
          : "Guided command";
        copy.append(label, detail, status);
        button.append(icon, copy);
        grid.append(button);
      }

      section.append(heading, grid);
      content.append(section);
    }

    const roadmap = document.createElement("section");
    roadmap.className = "nx-capability-group";
    const roadmapTitle = document.createElement("h3");
    roadmapTitle.textContent = "Roadmap capabilities";
    const roadmapGrid = document.createElement("div");
    roadmapGrid.className = "nx-roadmap-grid";

    for (const [label, group, detail] of roadmapCapabilities) {
      const card = document.createElement("div");
      card.className = "nx-roadmap-card";
      const title = document.createElement("strong");
      title.textContent = label;
      const category = document.createElement("span");
      category.textContent = group;
      const description = document.createElement("small");
      description.textContent = detail;
      card.append(title, category, description);
      roadmapGrid.append(card);
    }

    roadmap.append(roadmapTitle, roadmapGrid);
    content.append(roadmap);
  }

  function approvalSnapshot(approval) {
    if (!approval) return null;
    return {
      approvalId: String(approval.approval_id || ""),
      taskId: String(approval.task_id || ""),
      action: String(approval.action_title || "Protected action"),
      summary: String(approval.action_summary || ""),
      risk: String(approval.risk_tier || "unknown"),
      destination: String(approval.destination_label || "—"),
      reversible: Boolean(approval.reversible),
      hash: String(approval.payload_sha256 || ""),
      preview: String(approval.exact_preview || ""),
      expiresAt: String(approval.expires_at || ""),
      channel: String(approval.approval_channel || "desktop"),
    };
  }

  /* P6.12 TASK RUNTIME CENTER */
  function friendlyTaskPhase(state) {
    const phases = {
      received: ["Started", 5],
      planned: ["Thinking", 20],
      awaiting_approval: ["Waiting for approval", 35],
      approved: ["Approved", 45],
      executing: ["Running", 65],
      verifying: ["Finishing up", 85],
      completed: ["Done", 100],
      partially_completed: ["Needs review", 100],
      denied: ["Denied", 100],
      failed: ["Failed", 100],
      rolling_back: ["Undoing", 85],
      rolled_back: ["Undone", 100],
    };
    return phases[String(state || "")] || ["Unknown", 0];
  }

  function renderTaskCenter() {
    const record = runtime.windows.get("tasks");
    if (!record) return;
    const content = record.content;
    content.replaceChildren();

    const task = runtime.currentTask;
    if (!task) {
      const empty = document.createElement("div");
      empty.className = "nx-empty-state";
      empty.innerHTML = svgIcon("task");
      const text = document.createElement("p");
      text.textContent = (
        "The next authoritative Nexuss task will appear here. "
        + "This surface does not create a second task state machine."
      );
      empty.append(text);
      content.append(empty);
      return;
    }

    const [phase, progress] = friendlyTaskPhase(task.state);
    const card = document.createElement("article");
    card.className = "nx-task-runtime-card";

    const heading = document.createElement("div");
    heading.className = "nx-task-runtime-heading";
    const title = document.createElement("h3");
    title.textContent = phase;
    const state = document.createElement("code");
    state.textContent = String(task.state || "unknown");
    heading.append(title, state);

    const progressTrack = document.createElement("div");
    progressTrack.className = "nx-task-progress";
    progressTrack.setAttribute("role", "progressbar");
    progressTrack.setAttribute("aria-valuemin", "0");
    progressTrack.setAttribute("aria-valuemax", "100");
    progressTrack.setAttribute("aria-valuenow", String(progress));
    const progressBar = document.createElement("span");
    progressBar.style.width = `${progress}%`;
    progressTrack.append(progressBar);

    const facts = document.createElement("dl");
    const capabilities = Array.isArray(task.plan?.steps)
      ? task.plan.steps.map((step) => step.capability_id).join(", ")
      : "—";
    const verified = Array.isArray(task.results)
      ? task.results.filter((result) => result.status === "verified").length
      : 0;
    const failed = Array.isArray(task.results)
      ? task.results.filter((result) => result.status === "failed").length
      : 0;

    for (const [label, value] of [
      ["Task", task.task_id],
      ["Intent", task.intent?.kind],
      ["Capabilities", capabilities],
      ["Verified results", verified],
      ["Failed results", failed],
      ["Approval", task.state === "awaiting_approval" ? "Required" : "—"],
    ]) {
      const row = document.createElement("div");
      const term = document.createElement("dt");
      term.textContent = label;
      const description = document.createElement("dd");
      description.textContent = value == null || value === ""
        ? "—"
        : String(value);
      row.append(term, description);
      facts.append(row);
    }

    const events = document.createElement("div");
    events.className = "nx-task-event-list";
    const eventTitle = document.createElement("strong");
    eventTitle.textContent = "Recent lifecycle";
    events.append(eventTitle);

    const recent = Array.isArray(task.events)
      ? task.events.slice(-6).reverse()
      : [];
    for (const event of recent) {
      const row = document.createElement("div");
      const eventType = document.createElement("span");
      eventType.textContent = String(
        event.event_type || event.state || "event",
      );
      const when = document.createElement("time");
      when.textContent = event.occurred_at
        ? new Date(event.occurred_at).toLocaleTimeString()
        : "—";
      row.append(eventType, when);
      events.append(row);
    }

    const note = document.createElement("p");
    note.className = "nx-task-runtime-note";
    note.textContent = (
      "Retries are never automatic here. A failed consequential action "
      + "must be requested again and re-enter policy and approval."
    );

    card.append(heading, progressTrack, facts, events, note);
    content.append(card);
  }

  function renderApprovalCenter() {
    const record = runtime.windows.get("approvals");
    if (!record) return;
    const content = record.content;
    content.replaceChildren();

    const header = document.createElement("div");
    header.className = "nx-center-status";
    const count = document.createElement("strong");
    count.textContent = runtime.pendingCount
      ? `${runtime.pendingCount} pending approval`
      : "No pending approvals";
    const explanation = document.createElement("span");
    explanation.textContent = (
      "Exact payloads remain governed by the existing Nexuss approval service."
    );
    header.append(count, explanation);
    content.append(header);

    const approval = approvalSnapshot(runtime.currentApproval);
    if (!approval) {
      const empty = document.createElement("div");
      empty.className = "nx-empty-state";
      empty.innerHTML = svgIcon("approval");
      const text = document.createElement("p");
      text.textContent = (
        "Protected actions will appear here when Nexuss reaches "
        + "an authoritative approval boundary."
      );
      empty.append(text);
      content.append(empty);
      return;
    }

    const card = document.createElement("article");
    card.className = "nx-approval-card";

    const title = document.createElement("h3");
    title.textContent = approval.action;
    const summary = document.createElement("p");
    summary.textContent = approval.summary;

    const facts = document.createElement("dl");
    for (const [label, value] of [
      ["Risk", approval.risk],
      ["Destination", approval.destination],
      ["Reversible", approval.reversible ? "Yes" : "No"],
      ["Channel", approval.channel],
      ["Expires", approval.expiresAt
        ? new Date(approval.expiresAt).toLocaleString()
        : "—"],
    ]) {
      const row = document.createElement("div");
      const term = document.createElement("dt");
      term.textContent = label;
      const description = document.createElement("dd");
      description.textContent = value;
      row.append(term, description);
      facts.append(row);
    }

    const hash = document.createElement("code");
    hash.textContent = approval.hash || "No payload hash";
    const preview = document.createElement("pre");
    preview.textContent = approval.preview || "No exact preview supplied.";

    const actions = document.createElement("div");
    actions.className = "nx-center-actions";
    actions.append(
      createButton({
        label: "Open exact approval",
        icon: "approval",
        className: "nx-primary-action",
        onClick: () => {
          if (
            runtime.currentApproval
            && typeof showApproval === "function"
          ) {
            void showApproval(runtime.currentApproval);
          }
        },
      }),
    );

    if (approval.channel === "phone") {
      actions.append(
        createButton({
          label: "Open mobile approval",
          icon: "mobile",
          className: "nx-secondary-action",
          onClick: openMobile,
        }),
      );
    }

    card.append(title, summary, facts, hash, preview, actions);
    content.append(card);
  }

  function renderReceiptCenter() {
    const record = runtime.windows.get("receipts");
    if (!record) return;
    const content = record.content;
    content.replaceChildren();

    const receipt = runtime.currentReceipt;
    if (!receipt) {
      const empty = document.createElement("div");
      empty.className = "nx-empty-state";
      empty.innerHTML = svgIcon("receipt");
      const text = document.createElement("p");
      text.textContent = (
        "Select a completed interaction to display its verified receipt."
      );
      empty.append(text);
      content.append(empty);
      return;
    }

    const card = document.createElement("article");
    card.className = "nx-receipt-card";
    const title = document.createElement("h3");
    title.textContent = `${String(receipt.state || "Action")} receipt`;
    const facts = document.createElement("dl");
    for (const [label, value] of [
      ["Receipt ID", receipt.receipt_id],
      ["Task ID", receipt.task_id],
      ["Verified", receipt.verified ? "Yes" : "No"],
      ["Reversible", receipt.reversible ? "Yes" : "No"],
      ["Created", receipt.created_at
        ? new Date(receipt.created_at).toLocaleString()
        : "—"],
    ]) {
      const row = document.createElement("div");
      const term = document.createElement("dt");
      term.textContent = label;
      const description = document.createElement("dd");
      description.textContent = value == null ? "—" : String(value);
      row.append(term, description);
      facts.append(row);
    }
    const actions = document.createElement("div");
    actions.className = "nx-center-actions";
    actions.append(
      createButton({
        label: "Open Action Control",
        icon: "action",
        className: "nx-primary-action",
        onClick: () => {
          focusCore("inspector");
          document.querySelector('[data-tab="receipt"]')?.click();
        },
      }),
    );
    card.append(title, facts, actions);
    content.append(card);
  }

  function pushNotification(message, kind = "info") {
    const clean = String(message || "").trim();
    if (!clean) return;
    runtime.notifications.unshift({
      id: crypto.randomUUID(),
      message: clean,
      kind,
      occurredAt: new Date().toISOString(),
    });
    runtime.notifications = runtime.notifications.slice(0, 30);
    renderNotifications();
  }

  function renderNotifications() {
    const record = runtime.windows.get("notifications");
    if (!record) return;
    const content = record.content;
    content.replaceChildren();

    if (!runtime.notifications.length) {
      const empty = document.createElement("div");
      empty.className = "nx-empty-state";
      empty.innerHTML = svgIcon("bell");
      const text = document.createElement("p");
      text.textContent = (
        "Runtime notices remain in memory only and clear when the page closes."
      );
      empty.append(text);
      content.append(empty);
      return;
    }

    const list = document.createElement("div");
    list.className = "nx-notification-list";
    for (const item of runtime.notifications) {
      const row = document.createElement("article");
      row.className = `nx-notification is-${item.kind}`;
      const body = document.createElement("p");
      body.textContent = item.message;
      const time = document.createElement("time");
      time.textContent = new Date(item.occurredAt).toLocaleTimeString();
      row.append(body, time);
      list.append(row);
    }
    content.append(list);
  }

  async function runDiagnostics() {
    const record = runtime.windows.get("diagnostics");
    if (!record) return;
    const content = record.content;
    content.replaceChildren();

    const status = document.createElement("div");
    status.className = "nx-diagnostic-running";
    status.textContent = "Running read-only health checks…";
    content.append(status);

    const results = [];
    try {
      const response = await fetch("/health/ready", {
        cache: "no-store",
        headers: typeof apiHeaders === "function" ? apiHeaders() : {},
      });
      let detail = null;
      try {
        detail = await response.json();
      } catch {
        detail = await response.text();
      }
      results.push({
        label: "Nexuss readiness",
        ok: response.ok,
        detail: typeof detail === "string"
          ? detail
          : JSON.stringify(detail),
      });
    } catch (error) {
      results.push({
        label: "Nexuss readiness",
        ok: false,
        detail: error instanceof Error ? error.message : "Unavailable",
      });
    }

    try {
      const response = await fetch("/v1/device-node/status", {
        cache: "no-store",
        headers: typeof apiHeaders === "function" ? apiHeaders() : {},
      });
      const detail = await response.json();
      results.push({
        label: "Trusted Windows node",
        ok: Boolean(response.ok && detail.reachable),
        detail: detail.reachable
          ? "Loopback node reachable"
          : String(detail.reason_code || "Unavailable"),
      });
    } catch (error) {
      results.push({
        label: "Trusted Windows node",
        ok: false,
        detail: error instanceof Error ? error.message : "Unavailable",
      });
    }

    results.push({
      label: "Professional workspace asset",
      ok: true,
      detail: `P6.10F ${VERSION}`,
    });
    results.push({
      label: "Approval presentation",
      ok: Boolean(document.getElementById("approval-overlay")),
      detail: runtime.currentApproval
        ? "Pending approval available"
        : "No current pending approval",
    });
    results.push({
      label: "Activity workspace",
      ok: Boolean(document.getElementById("nexuss-interaction-tray")),
      detail: document.getElementById("nexuss-interaction-tray")
        ? "Mounted"
        : "Waiting for unified interaction runtime",
    });
    results.push({
      label: "Media workspace",
      ok: Boolean(document.getElementById("media-dock")),
      detail: document.getElementById("media-dock")
        ? "Mounted"
        : "Unavailable",
    });

    content.replaceChildren();
    const list = document.createElement("div");
    list.className = "nx-diagnostic-list";
    for (const result of results) {
      const row = document.createElement("article");
      row.className = result.ok
        ? "nx-diagnostic is-ok"
        : "nx-diagnostic is-failed";
      const indicator = document.createElement("span");
      indicator.textContent = result.ok ? "PASS" : "CHECK";
      const copy = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = result.label;
      const detail = document.createElement("small");
      detail.textContent = result.detail;
      copy.append(title, detail);
      row.append(indicator, copy);
      list.append(row);
    }

    const actions = document.createElement("div");
    actions.className = "nx-center-actions";
    actions.append(
      createButton({
        label: "Run checks again",
        icon: "diagnostics",
        className: "nx-primary-action",
        onClick: () => void runDiagnostics(),
      }),
    );
    content.append(list, actions);
  }

  function renderSettings() {
    const record = runtime.windows.get("settings");
    if (!record) return;
    const content = record.content;
    content.replaceChildren();

    const form = document.createElement("div");
    form.className = "nx-settings-list";

    function settingRow(label, description, checked, onChange) {
      const row = document.createElement("label");
      row.className = "nx-setting-row";
      const copy = document.createElement("span");
      const title = document.createElement("strong");
      title.textContent = label;
      const detail = document.createElement("small");
      detail.textContent = description;
      copy.append(title, detail);
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = checked;
      input.addEventListener("change", () => onChange(input.checked));
      row.append(copy, input);
      return row;
    }

    form.append(
      settingRow(
        "Compact capability dock",
        "Reduce labels while preserving accessible tooltips.",
        settings.compactDock,
        (value) => {
          settings.compactDock = value;
          applySettings();
        },
      ),
      settingRow(
        "Reduce interface motion",
        "Disable optional workspace transitions.",
        settings.reducedMotion,
        (value) => {
          settings.reducedMotion = value;
          applySettings();
        },
      ),
    );

    const actions = document.createElement("div");
    actions.className = "nx-center-actions";
    actions.append(
      createButton({
        label: "Reset UI layout",
        icon: "restore",
        className: "nx-secondary-action",
        onClick: () => {
          manager.reset();
          if (window.NexussWorkspace?.reset) window.NexussWorkspace.reset();
          if (window.NexussActivityWorkspace?.reset) {
            window.NexussActivityWorkspace.reset();
          }
          pushNotification("The Nexuss UI layout was reset.", "success");
        },
      }),
      createButton({
        label: "Restore split view",
        icon: "grid",
        className: "nx-primary-action",
        onClick: () => {
          if (typeof restoreFocusDeck === "function") restoreFocusDeck();
        },
      }),
    );

    content.append(form, actions);
  }

  function applySettings() {
    document.body.classList.toggle(
      "nx-compact-dock",
      settings.compactDock,
    );
    document.body.classList.toggle(
      "nx-reduced-motion",
      settings.reducedMotion,
    );
    writeSettings();
    renderSettings();
  }

  function createSystemWindows() {
    manager.create({
      id: "capabilities",
      title: "Capabilities",
      subtitle: "Available, guided and roadmap workspaces",
      icon: "grid",
      width: 760,
      height: 650,
      left: 120,
      top: 80,
      render: renderCapabilityLauncher,
    });
    manager.create({
      id: "tasks",
      title: "Task Runtime",
      subtitle: "Authoritative lifecycle, progress and retry readiness",
      icon: "task",
      width: 560,
      height: 590,
      left: 155,
      top: 88,
      render: renderTaskCenter,
    });
    manager.create({
      id: "approvals",
      title: "Approval Center",
      subtitle: "Exact payload review and mobile handoff",
      icon: "approval",
      width: 600,
      height: 620,
      left: 180,
      top: 90,
      render: renderApprovalCenter,
    });
    manager.create({
      id: "receipts",
      title: "Receipt Center",
      subtitle: "Verified execution evidence",
      icon: "receipt",
      width: 520,
      height: 500,
      left: 230,
      top: 100,
      render: renderReceiptCenter,
    });
    manager.create({
      id: "notifications",
      title: "Notification Center",
      subtitle: "In-memory runtime status",
      icon: "bell",
      width: 460,
      height: 520,
      left: 280,
      top: 110,
      render: renderNotifications,
    });
    manager.create({
      id: "diagnostics",
      title: "Diagnostics Center",
      subtitle: "Read-only health and workspace checks",
      icon: "diagnostics",
      width: 540,
      height: 520,
      left: 330,
      top: 120,
      render: () => void runDiagnostics(),
    });
    manager.create({
      id: "settings",
      title: "UI Settings",
      subtitle: "Safe layout and accessibility controls",
      icon: "settings",
      width: 500,
      height: 430,
      left: 380,
      top: 130,
      render: renderSettings,
    });
  }

  function updateApprovalBadge() {
    const count = runtime.currentApproval ? 1 : 0;
    runtime.pendingCount = count;
    document.querySelectorAll("[data-approval-badge]").forEach((badge) => {
      badge.hidden = count === 0;
      badge.textContent = String(count);
    });
    renderApprovalCenter();
  }

  function installApprovalHardening() {
    const overlay = document.getElementById("approval-overlay");
    if (!overlay) {
      pushNotification(
        "Approval presentation markup is unavailable.",
        "error",
      );
      return;
    }

    overlay.style.setProperty("--nx-approval-z", String(APPROVAL_Z));
    overlay.addEventListener("keydown", (event) => {
      if (event.key !== "Tab" || overlay.hidden) return;
      const focusable = [...overlay.querySelectorAll(
        'button:not([hidden]):not([disabled]), a[href], input:not([disabled])',
      )].filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    const observer = new MutationObserver(() => {
      document.body.classList.toggle("nx-approval-open", !overlay.hidden);
    });
    observer.observe(overlay, {
      attributes: true,
      attributeFilter: ["hidden"],
    });

    if (typeof showApproval === "function") {
      const originalShowApproval = showApproval;
      showApproval = async function nexussShowApproval(approval) {
        if (!approval) return;
        runtime.currentApproval = approval;
        updateApprovalBadge();

        const approvalId = String(approval.approval_id || "");
        const sameOpen = (
          !overlay.hidden
          && overlay.dataset.nxApprovalId === approvalId
        );

        if (!sameOpen) {
          await originalShowApproval(approval);
        }

        overlay.dataset.nxApprovalId = approvalId;
        overlay.hidden = false;
        overlay.removeAttribute("aria-hidden");
        document.body.classList.add("nx-approval-open");
        renderApprovalCenter();
      };
    }

    if (typeof hideApproval === "function") {
      const originalHideApproval = hideApproval;
      hideApproval = function nexussHideApproval() {
        originalHideApproval();
        document.body.classList.remove("nx-approval-open");
      };
    }

    if (typeof renderTask === "function") {
      const originalRenderTask = renderTask;
      renderTask = function nexussRenderTask(task, receipt) {
        const result = originalRenderTask(task, receipt);
        runtime.currentTask = task || null;
        renderTaskCenter();
        if (task?.state === "awaiting_approval" && task.approval) {
          runtime.currentApproval = task.approval;
          updateApprovalBadge();
          queueMicrotask(() => {
            if (overlay.hidden && typeof showApproval === "function") {
              void showApproval(task.approval);
            }
          });
        } else if (
          runtime.currentApproval
          && task?.task_id === runtime.currentApproval.task_id
        ) {
          runtime.currentApproval = null;
          updateApprovalBadge();
        }
        return result;
      };
    }

    if (typeof renderReceipt === "function") {
      const originalRenderReceipt = renderReceipt;
      renderReceipt = function nexussRenderReceipt(receipt) {
        runtime.currentReceipt = receipt || null;
        const result = originalRenderReceipt(receipt);
        renderReceiptCenter();
        return result;
      };
    }

    if (typeof currentTask !== "undefined") {
      if (currentTask?.state === "awaiting_approval" && currentTask.approval) {
        runtime.currentApproval = currentTask.approval;
        updateApprovalBadge();
      }
    }
  }

  function activityState() {
    const state = layout.activity || {
      mode: "expanded",
      left: null,
      top: null,
      width: 390,
      height: 500,
    };
    layout.activity = state;
    return state;
  }

  function applyActivity() {
    const tray = document.getElementById("nexuss-interaction-tray");
    if (!tray) return;
    const state = activityState();
    tray.dataset.nxActivityMode = safeMode(state.mode);

    if (state.mode === "hidden") {
      tray.hidden = true;
      taskbarButton(
        "activity",
        "Activity",
        "activity",
        () => {
          state.mode = "expanded";
          applyActivity();
        },
      );
      writeLayout();
      return;
    }

    tray.hidden = false;
    removeTaskbarButton("activity");

    if (!isMobile()) {
      const rectangle = tray.getBoundingClientRect();
      state.width = clamp(
        safeNumber(state.width, rectangle.width || 390),
        MIN_WIDTH,
        window.innerWidth - 20,
      );
      state.height = clamp(
        safeNumber(state.height, rectangle.height || 500),
        MIN_HEIGHT,
        window.innerHeight - 20,
      );
      state.left = safeNumber(
        state.left,
        Math.max(EDGE, window.innerWidth - state.width - 18),
      );
      state.top = safeNumber(
        state.top,
        Math.max(EDGE, window.innerHeight - state.height - 82),
      );
      state.left = clamp(
        state.left,
        EDGE,
        Math.max(EDGE, window.innerWidth - state.width - EDGE),
      );
      state.top = clamp(
        state.top,
        EDGE,
        Math.max(EDGE, window.innerHeight - state.height - EDGE),
      );
      tray.style.setProperty("--nx-activity-left", `${state.left}px`);
      tray.style.setProperty("--nx-activity-top", `${state.top}px`);
      tray.style.setProperty("--nx-activity-width", `${state.width}px`);
      tray.style.setProperty("--nx-activity-height", `${state.height}px`);
    }
    writeLayout();
  }

  function enhanceActivity(forceReset = false) {
    const tray = typeof ensureInteractionTray === "function"
      ? ensureInteractionTray()
      : document.getElementById("nexuss-interaction-tray");
    if (!tray) return false;

    if (forceReset) {
      layout.activity = {
        mode: "expanded",
        left: null,
        top: null,
        width: 390,
        height: 500,
      };
    }

    if (window.NexussActivityWorkspace) {
      applyActivity();
      return true;
    }

    if (tray.dataset.nxActivityEnhanced === "true") {
      applyActivity();
      return true;
    }

    tray.dataset.nxActivityEnhanced = "true";
    tray.classList.add("nx-managed-activity");

    const header = tray.querySelector(".nexuss-interaction-tray-header");
    const actions = tray.querySelector(".nexuss-interaction-tray-actions");
    const title = tray.querySelector(".nexuss-interaction-tray-title");
    if (!header || !actions || !title) return false;

    const controls = document.createElement("div");
    controls.className = "nx-activity-controls";
    controls.append(
      createButton({
        label: "Minimize Activity",
        icon: "minimize",
        title: "Minimize",
        onClick: (event) => {
          event.stopPropagation();
          activityState().mode = "mini";
          applyActivity();
        },
      }),
      createButton({
        label: "Expand Activity",
        icon: "expand",
        title: "Expand",
        onClick: (event) => {
          event.stopPropagation();
          activityState().mode = "expanded";
          applyActivity();
        },
      }),
      createButton({
        label: "Hide Activity",
        icon: "close",
        title: "Hide and restore from taskbar",
        onClick: (event) => {
          event.stopPropagation();
          activityState().mode = "hidden";
          applyActivity();
        },
      }),
    );
    actions.prepend(controls);

    title.tabIndex = 0;
    title.title = (
      "Drag Activity to move. Alt+Arrow moves by keyboard."
    );

    let drag = null;
    header.addEventListener("pointerdown", (event) => {
      if (
        isMobile()
        || event.button !== 0
        || event.target.closest("button, a, input, textarea, select")
      ) {
        return;
      }
      const rectangle = tray.getBoundingClientRect();
      drag = {
        pointerId: event.pointerId,
        x: event.clientX,
        y: event.clientY,
        left: rectangle.left,
        top: rectangle.top,
      };
      header.setPointerCapture(event.pointerId);
      tray.classList.add("is-dragging");
      event.preventDefault();
    });

    header.addEventListener("pointermove", (event) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      const rectangle = tray.getBoundingClientRect();
      const state = activityState();
      state.left = clamp(
        drag.left + event.clientX - drag.x,
        EDGE,
        Math.max(EDGE, window.innerWidth - rectangle.width - EDGE),
      );
      state.top = clamp(
        drag.top + event.clientY - drag.y,
        EDGE,
        Math.max(EDGE, window.innerHeight - rectangle.height - EDGE),
      );
      tray.style.setProperty("--nx-activity-left", `${state.left}px`);
      tray.style.setProperty("--nx-activity-top", `${state.top}px`);
    });

    const endDrag = (event) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      drag = null;
      tray.classList.remove("is-dragging");
      writeLayout();
    };
    header.addEventListener("pointerup", endDrag);
    header.addEventListener("pointercancel", endDrag);

    title.addEventListener("keydown", (event) => {
      if (!event.altKey) return;
      const movement = {
        ArrowLeft: [-8, 0],
        ArrowRight: [8, 0],
        ArrowUp: [0, -8],
        ArrowDown: [0, 8],
      }[event.key];
      if (!movement) return;
      event.preventDefault();
      const rectangle = tray.getBoundingClientRect();
      const state = activityState();
      state.left = clamp(
        rectangle.left + movement[0],
        EDGE,
        Math.max(EDGE, window.innerWidth - rectangle.width - EDGE),
      );
      state.top = clamp(
        rectangle.top + movement[1],
        EDGE,
        Math.max(EDGE, window.innerHeight - rectangle.height - EDGE),
      );
      applyActivity();
    });

    if (typeof ResizeObserver === "function") {
      const observer = new ResizeObserver(() => {
        if (
          isMobile()
          || tray.hidden
          || activityState().mode !== "expanded"
        ) {
          return;
        }
        const rectangle = tray.getBoundingClientRect();
        const state = activityState();
        state.left = Math.round(rectangle.left);
        state.top = Math.round(rectangle.top);
        state.width = Math.max(MIN_WIDTH, Math.round(rectangle.width));
        state.height = Math.max(MIN_HEIGHT, Math.round(rectangle.height));
        writeLayout();
      });
      observer.observe(tray);
    }

    applyActivity();
    return true;
  }

  function showActivity() {
    if (window.NexussActivityWorkspace?.restore) {
      window.NexussActivityWorkspace.restore();
      return;
    }
    if (!enhanceActivity()) return;
    activityState().mode = "expanded";
    applyActivity();
  }

  function installActivityObserver() {
    if (enhanceActivity()) return;
    const observer = new MutationObserver(() => {
      if (enhanceActivity()) observer.disconnect();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  function showCommandPalette() {
    const overlay = document.getElementById("nx-command-palette");
    if (!overlay) return;
    overlay.hidden = false;
    const input = overlay.querySelector("input");
    if (input) {
      input.value = "";
      input.focus();
      renderCommandResults("");
    }
  }

  function hideCommandPalette() {
    const overlay = document.getElementById("nx-command-palette");
    if (!overlay) return;
    overlay.hidden = true;
  }

  function renderCommandResults(query) {
    const list = document.querySelector("[data-nx-command-results]");
    if (!list) return;
    list.replaceChildren();
    const normalized = String(query || "").trim().toLowerCase();
    const filtered = capabilities.filter((capability) => (
      !normalized
      || capability.label.toLowerCase().includes(normalized)
      || capability.description.toLowerCase().includes(normalized)
      || capability.group.toLowerCase().includes(normalized)
    ));

    for (const capability of filtered) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "nx-command-result";
      button.addEventListener("click", () => {
        hideCommandPalette();
        capability.action();
      });
      const icon = document.createElement("span");
      icon.innerHTML = svgIcon(capability.icon);
      const copy = document.createElement("span");
      const label = document.createElement("strong");
      label.textContent = capability.label;
      const description = document.createElement("small");
      description.textContent = capability.description;
      copy.append(label, description);
      const status = document.createElement("em");
      status.textContent = capability.status === "available"
        ? "Open"
        : "Prepare";
      button.append(icon, copy, status);
      list.append(button);
    }
  }

  function buildCommandPalette() {
    if (document.getElementById("nx-command-palette")) return;
    const overlay = document.createElement("div");
    overlay.id = "nx-command-palette";
    overlay.className = "nx-command-palette";
    overlay.hidden = true;

    const dialog = document.createElement("section");
    dialog.className = "nx-command-dialog";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-label", "Nexuss command palette");

    const header = document.createElement("div");
    header.className = "nx-command-header";
    const icon = document.createElement("span");
    icon.innerHTML = svgIcon("search");
    const input = document.createElement("input");
    input.type = "search";
    input.placeholder = "Search Nexuss capabilities…";
    input.setAttribute("aria-label", "Search Nexuss capabilities");
    const close = createButton({
      label: "Close command palette",
      icon: "close",
      onClick: hideCommandPalette,
    });
    header.append(icon, input, close);

    const results = document.createElement("div");
    results.className = "nx-command-results";
    results.dataset.nxCommandResults = "true";

    const footer = document.createElement("footer");
    footer.textContent = (
      "Available capabilities open immediately. Guided commands require review."
    );

    input.addEventListener("input", () => renderCommandResults(input.value));
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) hideCommandPalette();
    });

    dialog.append(header, results, footer);
    overlay.append(dialog);
    document.body.append(overlay);
    renderCommandResults("");
  }

  function installKeyboardShortcuts() {
    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        showCommandPalette();
      }
      if (event.altKey && event.key.toLowerCase() === "a") {
        event.preventDefault();
        showActivity();
      }
      if (event.altKey && event.key.toLowerCase() === "p") {
        event.preventDefault();
        manager.show("approvals");
      }
      if (event.altKey && event.key.toLowerCase() === "r") {
        event.preventDefault();
        openReceiptTab();
      }
      if (
        event.key === "Escape"
        && !document.getElementById("nx-command-palette")?.hidden
      ) {
        hideCommandPalette();
      }
    });
  }

  function installNotificationBridge() {
    if (typeof showToast === "function") {
      const originalShowToast = showToast;
      showToast = function nexussShowToast(message) {
        pushNotification(message, "info");
        return originalShowToast(message);
      };
    }
    window.addEventListener("error", (event) => {
      pushNotification(
        event.message || "A browser interface error occurred.",
        "error",
      );
    });
    window.addEventListener("unhandledrejection", (event) => {
      const reason = event.reason;
      pushNotification(
        reason instanceof Error
          ? reason.message
          : "A browser promise was rejected.",
        "error",
      );
    });
  }

  function installStatusBridge() {
    const existingState = document.getElementById("system-state-label");
    if (existingState) {
      existingState.dataset.nxProfessionalWorkspace = VERSION;
      return;
    }

    const target = document.querySelector(".topbar-actions");
    if (!target || document.getElementById("nx-platform-status")) return;
    const status = document.createElement("div");
    status.id = "nx-platform-status";
    status.className = "nx-platform-status";
    const dot = document.createElement("span");
    dot.className = "nx-status-dot";
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = "Workspace";
    const detail = document.createElement("small");
    detail.textContent = "Professional UI ready";
    copy.append(title, detail);
    status.append(dot, copy);
    target.prepend(status);

    const system = document.getElementById("system-state-label");
    if (system && typeof MutationObserver === "function") {
      const sync = () => {
        const text = String(system.textContent || "").trim();
        detail.textContent = text || "Professional UI ready";
        status.classList.toggle(
          "is-degraded",
          /\b(degraded|offline|failed|unavailable)\b/i.test(text),
        );
      };
      new MutationObserver(sync).observe(system, {
        childList: true,
        subtree: true,
        characterData: true,
      });
      sync();
    }
  }

  function handleResize() {
    for (const id of runtime.windows.keys()) manager.apply(id);
    applyActivity();
  }

  function initialize() {
    document.body.classList.add("nx-platform-ready");
    document.documentElement.dataset.nxPlatformVersion = VERSION;
    createSystemWindows();
    buildDock();
    buildCommandPalette();
    installApprovalHardening();
    installActivityObserver();
    installKeyboardShortcuts();
    installNotificationBridge();
    installStatusBridge();
    applySettings();
    ensureTaskbar();
    window.addEventListener("resize", handleResize);

    pushNotification(
      "Professional Nexuss multitasking workspace loaded.",
      "success",
    );

    window.NexussProfessionalWorkspace = Object.freeze({
      version: VERSION,
      open: (id) => {
        const capability = capabilities.find((item) => item.id === id);
        if (capability) capability.action();
        else manager.show(id);
      },
      activity: showActivity,
      approvals: () => manager.show("approvals"),
      receipts: openReceiptTab,
      capabilities: () => manager.show("capabilities"),
      commandPalette: showCommandPalette,
      diagnostics: () => manager.show("diagnostics"),
      resetLayout: () => manager.reset(),
      status: () => ({
        version: VERSION,
        pendingApprovals: runtime.pendingCount,
        managedWindows: runtime.windows.size,
      }),
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();

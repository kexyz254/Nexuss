/* Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary. */
/*
 * P5.2 adaptive workspace.
 *
 * Replaces the fixed bottom-right overlay with a managed surface. Cards are
 * either docked (they reserve space and the shell reflows around them, so
 * nothing is covered) or floating (free geometry with collision resolution).
 *
 * No dependencies. Geometry is written through CSS custom properties via
 * CSSOM, which the strict CSP allows; literal style attributes would not be.
 */
"use strict";

const LAYOUT_KEY = "nexuss-workspace-layout-v1";
const GRID = 8;
const EDGE_SNAP = 14;
const TOPBAR_RESERVE = 70;
const CANVAS_PAD = 16;
const STACK_BREAKPOINT = 980;

const CARD_SPECS = [
  {
    id: "media",
    selector: "#media-dock",
    handle: ".media-toolbar",
    title: "Media workspace",
    min: { width: 560, height: 420 },
    max: { width: 2200, height: 1600 },
    defaults: { mode: "dock", dock: "right", size: 620 },
  },
  {
    id: "knowledge",
    selector: "#knowledge-drawer",
    handle: "header",
    title: "Research brief",
    min: { width: 320, height: 260 },
    max: { width: 900, height: 1600 },
    defaults: { mode: "float", x: 24, y: 24, width: 420, height: 460 },
  },
];

const RESIZE_DIRECTIONS = ["n", "e", "s", "w", "ne", "se", "sw", "nw"];

/** @type {Map<string, object>} */
const cards = new Map();
let canvas = null;
let dropHint = null;
let stacked = false;

/* ---------------------------------------------------------------- geometry */

const snap = (value) => Math.round(value / GRID) * GRID;
const clamp = (value, low, high) => Math.min(Math.max(value, low), high);

function canvasBounds() {
  return {
    width: window.innerWidth,
    height: window.innerHeight - TOPBAR_RESERVE,
  };
}

function overlaps(a, b) {
  return (
    a.x < b.x + b.width &&
    b.x < a.x + a.width &&
    a.y < b.y + b.height &&
    b.y < a.y + a.height
  );
}

function constrain(card, rect) {
  const bounds = canvasBounds();
  const width = clamp(rect.width, card.min.width, Math.min(card.max.width, bounds.width - CANVAS_PAD * 2));
  const height = clamp(rect.height, card.min.height, Math.min(card.max.height, bounds.height - CANVAS_PAD * 2));
  return {
    width,
    height,
    x: clamp(rect.x, CANVAS_PAD, Math.max(CANVAS_PAD, bounds.width - width - CANVAS_PAD)),
    y: clamp(rect.y, CANVAS_PAD, Math.max(CANVAS_PAD, bounds.height - height - CANVAS_PAD)),
  };
}

function edgeSnap(card, rect) {
  const bounds = canvasBounds();
  const next = { ...rect };
  if (Math.abs(next.x - CANVAS_PAD) < EDGE_SNAP) next.x = CANVAS_PAD;
  if (Math.abs(next.y - CANVAS_PAD) < EDGE_SNAP) next.y = CANVAS_PAD;
  const right = bounds.width - CANVAS_PAD;
  const bottom = bounds.height - CANVAS_PAD;
  if (Math.abs(next.x + next.width - right) < EDGE_SNAP) next.x = right - next.width;
  if (Math.abs(next.y + next.height - bottom) < EDGE_SNAP) next.y = bottom - next.height;
  return next;
}

/*
 * Collision resolution. The moved card keeps the position the person chose;
 * every other visible floating card is pushed out along its shallowest axis.
 * A card with nowhere to go reverts, which is more predictable than letting
 * it slide somewhere the person did not ask for.
 */
function resolveCollisions(movedId, proposed) {
  const settled = new Map([[movedId, proposed]]);
  const others = [...cards.values()].filter(
    (card) => card.id !== movedId && card.mode === "float" && isVisible(card),
  );

  for (const other of others) {
    let rect = { ...other.rect };
    let guard = 0;
    while (guard < 8) {
      const hit = [...settled.values()].find((placed) => overlaps(rect, placed));
      if (!hit) break;
      const pushRight = hit.x + hit.width - rect.x;
      const pushLeft = rect.x + rect.width - hit.x;
      const pushDown = hit.y + hit.height - rect.y;
      const pushUp = rect.y + rect.height - hit.y;
      const smallest = Math.min(pushRight, pushLeft, pushDown, pushUp);
      if (smallest === pushRight) rect.x += pushRight;
      else if (smallest === pushLeft) rect.x -= pushLeft;
      else if (smallest === pushDown) rect.y += pushDown;
      else rect.y -= pushUp;
      rect = constrain(other, rect);
      guard += 1;
    }
    if ([...settled.values()].some((placed) => overlaps(rect, placed))) {
      return null;
    }
    settled.set(other.id, rect);
  }
  return settled;
}

/* ------------------------------------------------------------------ render */

function isVisible(card) {
  return !card.element.hidden;
}

function applyGeometry(card) {
  const element = card.element;
  element.classList.toggle("ws-docked", card.mode === "dock");
  element.classList.toggle("ws-floating", card.mode === "float");
  element.classList.toggle("ws-theater", card.mode === "theater");
  element.dataset.wsDock = card.mode === "dock" ? card.dock : "";

  if (card.mode === "dock") {
    element.style.setProperty("--ws-dock-size", `${card.dockSize}px`);
    return;
  }
  const rect = card.mode === "theater" ? theaterRect() : card.rect;
  element.style.setProperty("--ws-x", `${rect.x}px`);
  element.style.setProperty("--ws-y", `${rect.y}px`);
  element.style.setProperty("--ws-w", `${rect.width}px`);
  element.style.setProperty("--ws-h", `${rect.height}px`);
}

function theaterRect() {
  const bounds = canvasBounds();
  return {
    x: CANVAS_PAD,
    y: CANVAS_PAD,
    width: bounds.width - CANVAS_PAD * 2,
    height: bounds.height - CANVAS_PAD * 2,
  };
}

/*
 * Docked cards reserve real space. The shell reads these variables and shrinks,
 * which is what stops the media card from sitting on top of the controls.
 */
function applyReservations() {
  const reserve = { left: 0, right: 0, bottom: 0 };
  if (!stacked) {
    for (const card of cards.values()) {
      if (card.mode !== "dock" || !isVisible(card)) continue;
      reserve[card.dock] = Math.max(reserve[card.dock], card.dockSize);
    }
  }
  const root = document.documentElement;
  root.style.setProperty("--ws-reserve-left", `${reserve.left}px`);
  root.style.setProperty("--ws-reserve-right", `${reserve.right}px`);
  root.style.setProperty("--ws-reserve-bottom", `${reserve.bottom}px`);
  document.body.classList.toggle(
    "ws-active",
    [...cards.values()].some((card) => isVisible(card)),
  );
}

function render() {
  for (const card of cards.values()) applyGeometry(card);
  applyReservations();
}

/* ------------------------------------------------------------- persistence */

function layoutBucket() {
  const width = window.innerWidth;
  if (width < STACK_BREAKPOINT) return "stack";
  if (width < 1500) return "compact";
  return "wide";
}

function saveLayout() {
  const bucket = layoutBucket();
  if (bucket === "stack") return;
  const payload = {};
  for (const card of cards.values()) {
    payload[card.id] = {
      mode: card.mode === "theater" ? card.priorMode : card.mode,
      dock: card.dock,
      dockSize: card.dockSize,
      rect: card.rect,
    };
  }
  try {
    const store = JSON.parse(localStorage.getItem(LAYOUT_KEY) || "{}");
    store[bucket] = payload;
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(store));
  } catch {
    /* A full or disabled storage quota must never break the workspace. */
  }
}

function loadLayout() {
  try {
    const store = JSON.parse(localStorage.getItem(LAYOUT_KEY) || "{}");
    return store[layoutBucket()] || null;
  } catch {
    return null;
  }
}

function resetLayout() {
  try {
    localStorage.removeItem(LAYOUT_KEY);
  } catch {
    /* ignore */
  }
  for (const card of cards.values()) applyDefaults(card);
  render();
}

function applyDefaults(card) {
  const spec = card.defaults;
  const bounds = canvasBounds();
  if (spec.mode === "dock") {
    card.mode = "dock";
    card.dock = spec.dock;
    card.dockSize = Math.min(spec.size, Math.round(bounds.width * 0.62));
    card.rect = constrain(card, {
      x: bounds.width - spec.size - CANVAS_PAD,
      y: CANVAS_PAD,
      width: spec.size,
      height: bounds.height - CANVAS_PAD * 2,
    });
  } else {
    card.mode = "float";
    card.dock = "right";
    card.dockSize = 520;
    card.rect = constrain(card, {
      x: spec.x,
      y: spec.y,
      width: spec.width,
      height: spec.height,
    });
  }
  card.priorMode = card.mode;
}

/* --------------------------------------------------------------- chrome UI */

function buildChrome(card) {
  const bar = document.createElement("div");
  bar.className = "ws-chrome";

  const label = document.createElement("span");
  label.className = "ws-chrome-title";
  label.textContent = card.title;
  bar.append(label);

  const actions = document.createElement("div");
  actions.className = "ws-chrome-actions";

  const dockLeft = chromeButton("⇤", "Dock left", () => setDock(card, "left"));
  const dockRight = chromeButton("⇥", "Dock right", () => setDock(card, "right"));
  const floatBtn = chromeButton("⧉", "Float", () => setFloating(card));
  const theaterBtn = chromeButton("▣", "Theater mode", () => toggleTheater(card));

  actions.append(dockLeft, dockRight, floatBtn, theaterBtn);
  bar.append(actions);

  /* The chrome bar is itself a drag handle, so a card whose header is full of
     inputs (the media toolbar) still has somewhere safe to grab. */
  attachDrag(card, bar);
  return bar;
}

function chromeButton(glyph, title, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "ws-chrome-button";
  button.textContent = glyph;
  button.title = title;
  button.setAttribute("aria-label", title);
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick();
  });
  return button;
}

function buildResizeHandles(card) {
  const fragment = document.createDocumentFragment();
  for (const direction of RESIZE_DIRECTIONS) {
    const handle = document.createElement("div");
    handle.className = `ws-resize ws-resize-${direction}`;
    handle.dataset.direction = direction;
    attachResize(card, handle, direction);
    fragment.append(handle);
  }
  return fragment;
}

/* ------------------------------------------------------------- interaction */

function isInteractive(target) {
  return Boolean(
    target.closest("input, textarea, select, button, a, [contenteditable], iframe"),
  );
}

function attachDrag(card, handle) {
  handle.addEventListener("pointerdown", (event) => {
    if (stacked || event.button !== 0) return;
    if (isInteractive(event.target) && !event.target.closest(".ws-chrome-title")) return;
    if (card.mode === "theater") return;

    /* Dragging a docked card undocks it in place, so it does not jump. */
    if (card.mode === "dock") {
      const element = card.element.getBoundingClientRect();
      card.mode = "float";
      card.rect = constrain(card, {
        x: element.left,
        y: element.top - TOPBAR_RESERVE,
        width: element.width,
        height: element.height,
      });
      applyReservations();
    }

    const origin = { ...card.rect };
    const startX = event.clientX;
    const startY = event.clientY;
    card.element.classList.add("ws-dragging");
    handle.setPointerCapture(event.pointerId);

    const onMove = (moveEvent) => {
      const proposed = constrain(card, {
        ...origin,
        x: snap(origin.x + (moveEvent.clientX - startX)),
        y: snap(origin.y + (moveEvent.clientY - startY)),
      });
      card.rect = edgeSnap(card, proposed);
      applyGeometry(card);
      showDropHint(moveEvent.clientX);
    };

    const onUp = (upEvent) => {
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      handle.removeEventListener("pointercancel", onUp);
      card.element.classList.remove("ws-dragging");
      hideDropHint();

      const zone = dockZoneFor(upEvent.clientX);
      if (zone) {
        setDock(card, zone);
        return;
      }
      commit(card, card.rect, origin);
    };

    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
    handle.addEventListener("pointercancel", onUp);
    event.preventDefault();
  });
}

function attachResize(card, handle, direction) {
  handle.addEventListener("pointerdown", (event) => {
    if (stacked || event.button !== 0 || card.mode === "theater") return;
    if (card.mode === "dock") setFloating(card);

    const origin = { ...card.rect };
    const startX = event.clientX;
    const startY = event.clientY;
    card.element.classList.add("ws-resizing");
    handle.setPointerCapture(event.pointerId);

    const onMove = (moveEvent) => {
      const dx = moveEvent.clientX - startX;
      const dy = moveEvent.clientY - startY;
      const next = { ...origin };

      if (direction.includes("e")) next.width = origin.width + dx;
      if (direction.includes("s")) next.height = origin.height + dy;
      if (direction.includes("w")) {
        next.width = origin.width - dx;
        next.x = origin.x + dx;
      }
      if (direction.includes("n")) {
        next.height = origin.height - dy;
        next.y = origin.y + dy;
      }

      /* Clamp the anchored edge so a card shrinking past its minimum stops
         rather than dragging its opposite corner along. */
      if (direction.includes("w") && next.width < card.min.width) {
        next.x = origin.x + origin.width - card.min.width;
      }
      if (direction.includes("n") && next.height < card.min.height) {
        next.y = origin.y + origin.height - card.min.height;
      }

      next.width = snap(next.width);
      next.height = snap(next.height);
      card.rect = constrain(card, next);
      applyGeometry(card);
    };

    const onUp = () => {
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      handle.removeEventListener("pointercancel", onUp);
      card.element.classList.remove("ws-resizing");
      commit(card, card.rect, origin);
    };

    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
    handle.addEventListener("pointercancel", onUp);
    event.preventDefault();
    event.stopPropagation();
  });
}

function commit(card, proposed, fallback) {
  const settled = resolveCollisions(card.id, proposed);
  if (!settled) {
    card.rect = fallback;
    applyGeometry(card);
    return;
  }
  for (const [id, rect] of settled) {
    const target = cards.get(id);
    if (target) target.rect = rect;
  }
  render();
  saveLayout();
}

/* ------------------------------------------------------------- dock zones */

function dockZoneFor(clientX) {
  const threshold = Math.max(90, window.innerWidth * 0.06);
  if (clientX <= threshold) return "left";
  if (clientX >= window.innerWidth - threshold) return "right";
  return null;
}

function showDropHint(clientX) {
  const zone = dockZoneFor(clientX);
  if (!zone) {
    hideDropHint();
    return;
  }
  dropHint.dataset.zone = zone;
  dropHint.hidden = false;
}

function hideDropHint() {
  dropHint.hidden = true;
}

function setDock(card, side) {
  card.mode = "dock";
  card.priorMode = "dock";
  card.dock = side;
  const bounds = canvasBounds();
  card.dockSize = clamp(
    card.dockSize || card.rect.width,
    card.min.width,
    Math.round(bounds.width * 0.7),
  );
  render();
  saveLayout();
}

function setFloating(card) {
  if (card.mode === "float") return;
  const element = card.element.getBoundingClientRect();
  card.mode = "float";
  card.priorMode = "float";
  card.rect = constrain(card, {
    x: element.width ? element.left : CANVAS_PAD,
    y: element.height ? element.top - TOPBAR_RESERVE : CANVAS_PAD,
    width: element.width || card.min.width,
    height: element.height || card.min.height,
  });
  render();
  saveLayout();
}

/*
 * Theater and fullscreen are distinct states. Theater maximises inside the
 * workspace and keeps the rest of Nexuss reachable; fullscreen hands the
 * element to the browser. Neither falls back to the other.
 */
function toggleTheater(card) {
  if (card.mode === "theater") {
    card.mode = card.priorMode || "float";
  } else {
    card.priorMode = card.mode;
    card.mode = "theater";
  }
  render();
  saveLayout();
}

function requestFullscreen(card) {
  if (document.fullscreenElement) {
    void document.exitFullscreen();
    return;
  }
  if (typeof card.element.requestFullscreen === "function") {
    void card.element.requestFullscreen().catch(() => {
      /* Fullscreen refused: stay where we are and say so, rather than
         silently substituting theater mode. */
      card.element.dispatchEvent(
        new CustomEvent("ws:fullscreen-denied", { bubbles: true }),
      );
    });
  }
}

/* ----------------------------------------------------------------- responsive */

function applyStacking() {
  const shouldStack = window.innerWidth < STACK_BREAKPOINT;
  if (shouldStack === stacked) return;
  stacked = shouldStack;
  document.body.classList.toggle("ws-stacked", stacked);
  if (!stacked) {
    const saved = loadLayout();
    for (const card of cards.values()) {
      const entry = saved?.[card.id];
      if (entry) restoreCard(card, entry);
      else applyDefaults(card);
    }
  }
  render();
}

function restoreCard(card, entry) {
  card.mode = entry.mode === "dock" ? "dock" : "float";
  card.priorMode = card.mode;
  card.dock = entry.dock === "left" ? "left" : "right";
  card.dockSize = clamp(Number(entry.dockSize) || 520, card.min.width, card.max.width);
  card.rect = constrain(card, {
    x: Number(entry.rect?.x) || CANVAS_PAD,
    y: Number(entry.rect?.y) || CANVAS_PAD,
    width: Number(entry.rect?.width) || card.min.width,
    height: Number(entry.rect?.height) || card.min.height,
  });
}

/* ---------------------------------------------------------------- lifecycle */

function observeVisibility(card) {
  const observer = new MutationObserver(() => {
    applyReservations();
  });
  observer.observe(card.element, { attributes: true, attributeFilter: ["hidden"] });
}

function initialise() {
  canvas = document.querySelector("#p5-workspace");
  if (!canvas) return;
  canvas.classList.add("ws-canvas");

  dropHint = document.createElement("div");
  dropHint.className = "ws-drop-hint";
  dropHint.hidden = true;
  canvas.append(dropHint);

  const saved = loadLayout();

  for (const spec of CARD_SPECS) {
    const element = document.querySelector(spec.selector);
    if (!element) continue;

    const card = {
      id: spec.id,
      element,
      title: spec.title,
      min: spec.min,
      max: spec.max,
      defaults: spec.defaults,
      mode: "float",
      priorMode: "float",
      dock: "right",
      dockSize: 520,
      rect: { x: CANVAS_PAD, y: CANVAS_PAD, width: spec.min.width, height: spec.min.height },
    };

    element.classList.add("ws-card");
    element.dataset.wsCard = spec.id;
    element.prepend(buildChrome(card));
    element.append(buildResizeHandles(card));

    const handle = element.querySelector(spec.handle);
    if (handle) attachDrag(card, handle);

    cards.set(spec.id, card);

    const entry = saved?.[spec.id];
    if (entry) restoreCard(card, entry);
    else applyDefaults(card);

    observeVisibility(card);
  }

  stacked = window.innerWidth < STACK_BREAKPOINT;
  document.body.classList.toggle("ws-stacked", stacked);
  render();

  let resizeFrame = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      applyStacking();
      for (const card of cards.values()) card.rect = constrain(card, card.rect);
      render();
    });
  });

  document.querySelector("#workspace-reset")?.addEventListener("click", resetLayout);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initialise);
} else {
  initialise();
}

window.NexussWorkspace = {
  reset: resetLayout,
  dock: (id, side) => {
    const card = cards.get(id);
    if (card) setDock(card, side);
  },
  float: (id) => {
    const card = cards.get(id);
    if (card) setFloating(card);
  },
  theater: (id) => {
    const card = cards.get(id);
    if (card) toggleTheater(card);
  },
  fullscreen: (id) => {
    const card = cards.get(id);
    if (card) requestFullscreen(card);
  },
};

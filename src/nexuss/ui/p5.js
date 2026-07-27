/* Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary. */
"use strict";

const p5Elements = {
  workspace: document.querySelector("#p5-workspace"),
  knowledge: document.querySelector("#knowledge-drawer"),
  knowledgeTitle: document.querySelector("#knowledge-title"),
  knowledgeSummary: document.querySelector("#knowledge-summary"),
  knowledgeSources: document.querySelector("#knowledge-sources"),
  knowledgeClose: document.querySelector("#knowledge-close"),
  knowledgeOpenSearch: document.querySelector("#knowledge-open-search"),
  mediaDock: document.querySelector("#media-dock"),
  mediaVideo: document.querySelector("#media-video"),
  mediaSearchForm: document.querySelector("#media-search-form"),
  mediaQueryInput: document.querySelector("#media-query-input"),
  mediaTitle: document.querySelector("#media-title"),
  mediaChannel: document.querySelector("#media-channel"),
  mediaMeta: document.querySelector("#media-meta"),
  mediaDescription: document.querySelector("#media-description"),
  mediaQueue: document.querySelector("#media-queue"),
  mediaResultCount: document.querySelector("#media-result-count"),
  mediaMatchStatus: document.querySelector("#media-match-status"),
  mediaEmpty: document.querySelector("#media-empty"),
  mediaEmptyMessage: document.querySelector("#media-empty-message"),
  play: document.querySelector("#media-play"),
  previous: document.querySelector("#media-prev"),
  next: document.querySelector("#media-next"),
  mute: document.querySelector("#media-mute"),
  expand: document.querySelector("#media-expand"),
  fullscreen: document.querySelector("#media-fullscreen"),
  close: document.querySelector("#media-close"),
  openPhone: document.querySelector("#media-open-phone"),
  openYouTube: document.querySelector("#media-open-youtube"),
};

let player = null;
let queue = [];
let queueIndex = 0;
let currentQuery = "";
let currentSearchUrl = "https://www.youtube.com/";
let playerReady = false;

function resultFor(task, capability) {
  const result = task.results?.find(
    (item) => item.capability_id === capability,
  );
  return result?.evidence?.[0]?.attributes || null;
}

function ensureWorkspace() {
  if (p5Elements.workspace) {
    p5Elements.workspace.hidden = false;
  }
}

function submitPrompt(prompt) {
  const input = document.querySelector("#command-input");
  const form = document.querySelector("#command-form");
  if (!input || !form) {
    return;
  }
  input.value = prompt;
  input.dispatchEvent(new Event("input"));
  form.requestSubmit();
}

function currentItem() {
  return queue[queueIndex] || null;
}

function openExternal(url) {
  if (!url || !url.startsWith("https://www.youtube.com/")) {
    return;
  }
  window.open(url, "_blank", "noopener");
}

function renderKnowledge(data) {
  ensureWorkspace();
  p5Elements.knowledge.hidden = false;
  p5Elements.knowledgeTitle.textContent =
    `Research · ${data.query || "Knowledge"}`;
  p5Elements.knowledgeSummary.textContent =
    data.brief || "No brief was produced.";
  p5Elements.knowledgeSources.replaceChildren();

  for (const source of data.sources || []) {
    const article = document.createElement("article");
    const title = document.createElement("strong");
    const extract = document.createElement("p");
    const footer = document.createElement("div");
    const provider = document.createElement("small");
    const open = document.createElement("button");

    title.textContent = source.title || "Public source";
    extract.textContent = source.extract || "No extract returned.";
    provider.textContent = source.provider || "Public source";
    open.type = "button";
    open.textContent = "Open through approval";
    open.addEventListener("click", () => {
      submitPrompt(`Open Chrome and search ${source.title}.`);
    });

    footer.className = "knowledge-source-footer";
    footer.append(provider, open);
    article.append(title, extract, footer);
    p5Elements.knowledgeSources.append(article);
  }
  currentQuery = String(data.query || "");
}

function createPlayer(videoId) {
  if (!window.YT?.Player) {
    return;
  }
  if (player) {
    player.loadVideoById(videoId);
    return;
  }

  player = new window.YT.Player("youtube-player", {
    videoId,
    playerVars: {
      autoplay: 1,
      controls: 1,
      rel: 0,
      origin: window.location.origin,
    },
    events: {
      onReady: () => {
        playerReady = true;
        p5Elements.play.textContent = "⏸";
      },
      onStateChange: (event) => {
        const playing = event.data === window.YT.PlayerState.PLAYING;
        p5Elements.play.textContent = playing ? "⏸" : "▶";
        if (event.data === window.YT.PlayerState.ENDED) {
          playAt(queueIndex + 1);
        }
      },
      onError: (event) => {
        /*
         * 101 and 150 both mean the uploader disabled embedding. 2 is a
         * malformed id, 5 an HTML5 playback failure, 100 a removed or
         * private video. Without this handler the iframe shows its own
         * placeholder and Nexuss reports the video as playing.
         */
        const reasons = {
          2: "That video id was rejected by YouTube.",
          5: "YouTube could not play that video in this player.",
          100: "That video has been removed or made private.",
          101: "The uploader does not allow this video to play outside YouTube.",
          150: "The uploader does not allow this video to play outside YouTube.",
        };
        const reason = reasons[event.data] || "That video could not be played here.";

        p5Elements.mediaEmpty.hidden = false;
        p5Elements.mediaEmptyMessage.textContent =
          `${reason} Open it on YouTube, or choose another result.`;
        p5Elements.mediaMatchStatus.textContent = "Playback blocked by uploader";
        p5Elements.play.textContent = "▶";
      },
    },
  });
}

window.onYouTubeIframeAPIReady = () => {
  const item = currentItem();
  if (item) {
    createPlayer(item.video_id);
  }
};

function formatPublished(value) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function updateNowPlaying(item) {
  p5Elements.mediaTitle.textContent = item.title || "YouTube video";
  p5Elements.mediaChannel.textContent = item.channel_title || "YouTube";
  const meta = [
    item.view_count_label,
    item.duration_label,
    formatPublished(item.published_at),
  ].filter(Boolean);
  p5Elements.mediaMeta.textContent = meta.join(" · ");
  p5Elements.mediaDescription.textContent = item.description || "";
}

function playAt(index) {
  if (!queue.length) {
    return;
  }
  queueIndex = (index + queue.length) % queue.length;
  const item = queue[queueIndex];
  p5Elements.mediaDock.hidden = false;
  p5Elements.mediaEmpty.hidden = true;
  ensureWorkspace();
  updateNowPlaying(item);
  createPlayer(item.video_id);
  renderResults();
}

function resultCard(item, index) {
  const article = document.createElement("article");
  article.className = `media-result-card${index === queueIndex ? " active" : ""}`;

  const thumbnailButton = document.createElement("button");
  thumbnailButton.type = "button";
  thumbnailButton.className = "media-result-thumbnail";
  thumbnailButton.setAttribute("aria-label", `Play ${item.title}`);
  thumbnailButton.addEventListener("click", () => playAt(index));

  const image = document.createElement("img");
  image.src = item.thumbnail_url || "";
  image.alt = "";
  image.loading = "lazy";
  thumbnailButton.append(image);
  if (item.duration_label) {
    const duration = document.createElement("span");
    duration.textContent = item.duration_label;
    thumbnailButton.append(duration);
  }

  const body = document.createElement("div");
  body.className = "media-result-body";
  const title = document.createElement("button");
  title.type = "button";
  title.className = "media-result-title";
  title.textContent = item.title || "YouTube video";
  title.addEventListener("click", () => playAt(index));

  const channel = document.createElement("div");
  channel.className = "media-result-channel";
  channel.textContent = item.channel_title || "YouTube";

  const metadata = document.createElement("div");
  metadata.className = "media-result-meta";
  metadata.textContent = [
    item.view_count_label,
    formatPublished(item.published_at),
  ].filter(Boolean).join(" · ");

  const description = document.createElement("p");
  description.textContent = item.description || "";

  const match = document.createElement("small");
  match.textContent = `${Math.round(Number(item.confidence || 0) * 100)}% match · ${item.match_reason || "relevant result"}`;

  const actions = document.createElement("div");
  actions.className = "media-result-actions";
  const play = document.createElement("button");
  play.type = "button";
  play.textContent = "Play";
  play.addEventListener("click", () => playAt(index));
  const open = document.createElement("button");
  open.type = "button";
  open.textContent = "YouTube";
  open.addEventListener("click", () => openExternal(item.watch_url));
  const phone = document.createElement("button");
  phone.type = "button";
  phone.textContent = "Phone";
  phone.addEventListener("click", () => {
    submitPrompt(`Open YouTube on my phone and search ${item.title} by ${item.channel_title}.`);
  });
  actions.append(play, open, phone);

  body.append(title, channel, metadata, description, match, actions);
  article.append(thumbnailButton, body);
  return article;
}

function renderResults() {
  p5Elements.mediaQueue.replaceChildren();
  queue.forEach((item, index) => {
    p5Elements.mediaQueue.append(resultCard(item, index));
  });
  const suffix = queue.length === 1 ? "" : "s";
  p5Elements.mediaResultCount.textContent = `${queue.length} result${suffix}`;
}

function renderMedia(data) {
  ensureWorkspace();
  currentQuery = String(data.query || "");
  currentSearchUrl = String(data.search_url || "https://www.youtube.com/");
  queue = Array.isArray(data.results) ? data.results : [];
  queueIndex = 0;
  p5Elements.mediaDock.hidden = false;
  p5Elements.mediaDock.classList.remove("minimized");
  p5Elements.mediaDock.classList.add("expanded");
  p5Elements.mediaQueryInput.value = currentQuery;
  renderResults();

  if (queue.length) {
    const exactMatch = data.selection_state === "exact_match";
    p5Elements.mediaMatchStatus.textContent = exactMatch
      ? "Exact intent match selected"
      : "Review results before playback";
    if (exactMatch) {
      playAt(0);
      return;
    }
    p5Elements.mediaEmpty.hidden = false;
    p5Elements.mediaEmptyMessage.textContent =
      "Nexuss found several plausible matches. Select the exact video from the results.";
    p5Elements.mediaTitle.textContent = "Select the exact result";
    p5Elements.mediaChannel.textContent = "YouTube search results";
    p5Elements.mediaMeta.textContent = "";
    p5Elements.mediaDescription.textContent = "";
    return;
  }

  p5Elements.mediaEmpty.hidden = false;
  p5Elements.mediaEmptyMessage.textContent =
    "The official YouTube search connector returned no playable results.";
  p5Elements.mediaTitle.textContent = currentQuery || "YouTube search";
  p5Elements.mediaChannel.textContent = "No result selected";
  p5Elements.mediaMeta.textContent = "";
  p5Elements.mediaDescription.textContent = "";
  p5Elements.mediaMatchStatus.textContent = "No playable result";
}

function toggleTheater(expanded) {
  const shouldExpand = expanded ?? !p5Elements.mediaDock.classList.contains("expanded");
  p5Elements.mediaDock.classList.toggle("expanded", shouldExpand);
  p5Elements.mediaDock.classList.toggle("minimized", !shouldExpand);
}

function requestMediaFullscreen() {
  if (document.fullscreenElement) {
    void document.exitFullscreen();
    return;
  }
  if (typeof p5Elements.mediaDock.requestFullscreen === "function") {
    void p5Elements.mediaDock.requestFullscreen().catch(() => {
      toggleTheater(true);
    });
    return;
  }
  toggleTheater(true);
}

function contextualResultIndex(normalized) {
  const numeric = normalized.match(/(?:result|video|option)\s+(\d{1,2})/);
  if (numeric) {
    return Number(numeric[1]) - 1;
  }
  const ordinals = new Map([
    ["first", 0],
    ["second", 1],
    ["third", 2],
    ["fourth", 3],
    ["fifth", 4],
  ]);
  for (const [word, index] of ordinals) {
    if (normalized.includes(word)) return index;
  }
  return null;
}

function handleContextCommand(utterance) {
  const normalized = String(utterance || "").toLowerCase();
  const command = normalized.trim().replace(/[.!?]+$/, "");
  if (!queue.length || p5Elements.mediaDock.hidden) {
    return null;
  }

  const resultIndex = contextualResultIndex(command);
  if (resultIndex !== null && /play|open|select|choose/.test(command)) {
    if (resultIndex >= 0 && resultIndex < queue.length) {
      playAt(resultIndex);
      return `Playing result ${resultIndex + 1}: ${queue[resultIndex].title}.`;
    }
    return `That result number is outside the current ${queue.length}-video list.`;
  }

  if (/^(pause|pause it|pause the (?:video|music)|hold playback)$/.test(command)) {
    player?.pauseVideo();
    return "Paused the active Nexuss media session.";
  }
  if (/^(resume|resume it|continue|continue playing|play it)$/.test(command)) {
    player?.playVideo();
    return "Resumed the active Nexuss media session.";
  }
  if (/^(next|next one|next video|play next)$/.test(command)) {
    playAt(queueIndex + 1);
    return `Playing the next result: ${currentItem()?.title || "YouTube video"}.`;
  }
  if (/^(previous|previous one|previous video|go back)$/.test(command)) {
    playAt(queueIndex - 1);
    return `Playing the previous result: ${currentItem()?.title || "YouTube video"}.`;
  }
  if (/^(mute|mute it|mute the (?:video|player))$/.test(command)) {
    player?.mute();
    p5Elements.mute.textContent = "🔇";
    return "Muted the active Nexuss media session.";
  }
  if (/^(unmute|unmute it|sound on)$/.test(command)) {
    player?.unMute();
    p5Elements.mute.textContent = "🔊";
    return "Unmuted the active Nexuss media session.";
  }
  if (/^(maximize|maximize it|maximize the player|theater mode)$/.test(command)) {
    toggleTheater(true);
    return "Expanded the Nexuss media workspace.";
  }
  if (/^(minimize|minimize it|minimize the player|mini player)$/.test(command)) {
    toggleTheater(false);
    return "Minimized the Nexuss media workspace while preserving playback.";
  }
  if (/^(full screen|fullscreen|make it full screen|full screen the player)$/.test(command)) {
    requestMediaFullscreen();
    return "Requested full-screen playback for the Nexuss media workspace.";
  }
  if (/^(exit full screen|leave full screen)$/.test(command)) {
    if (document.fullscreenElement) void document.exitFullscreen();
    return "Exited full-screen playback.";
  }
  if (/^(close|close it|close the player|stop and close)$/.test(command)) {
    player?.stopVideo();
    p5Elements.mediaDock.hidden = true;
    return "Closed the Nexuss media session.";
  }
  if (/^(open on youtube|open youtube|show on youtube)$/.test(command)) {
    openExternal(currentItem()?.watch_url || currentSearchUrl);
    return "Opened the current YouTube item in a new tab without an approval step.";
  }
  if (/^(open on phone|send to phone|play on phone)$/.test(command)) {
    submitPrompt(`Open YouTube on my phone and search ${currentQuery}.`);
    return "Queued the exact YouTube search for the paired phone.";
  }
  return null;
}

p5Elements.knowledgeClose?.addEventListener("click", () => {
  p5Elements.knowledge.hidden = true;
});

p5Elements.knowledgeOpenSearch?.addEventListener("click", () => {
  submitPrompt(`Open Chrome and search ${currentQuery}.`);
});

p5Elements.mediaSearchForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = p5Elements.mediaQueryInput.value.trim();
  if (query) submitPrompt(`Search YouTube for ${query}.`);
});

p5Elements.openPhone?.addEventListener("click", () => {
  const item = currentItem();
  const query = item ? `${item.title} by ${item.channel_title}` : currentQuery;
  submitPrompt(`Open YouTube on my phone and search ${query}.`);
});

p5Elements.openYouTube?.addEventListener("click", () => {
  openExternal(currentItem()?.watch_url || currentSearchUrl);
});

p5Elements.play?.addEventListener("click", () => {
  if (!playerReady || !player) {
    return;
  }
  if (player.getPlayerState() === window.YT.PlayerState.PLAYING) {
    player.pauseVideo();
  } else {
    player.playVideo();
  }
});

p5Elements.previous?.addEventListener("click", () => {
  playAt(queueIndex - 1);
});

p5Elements.next?.addEventListener("click", () => {
  playAt(queueIndex + 1);
});

p5Elements.mute?.addEventListener("click", () => {
  if (!playerReady || !player) {
    return;
  }
  if (player.isMuted()) {
    player.unMute();
    p5Elements.mute.textContent = "🔊";
  } else {
    player.mute();
    p5Elements.mute.textContent = "🔇";
  }
});

p5Elements.expand?.addEventListener("click", () => {
  toggleTheater();
});

p5Elements.fullscreen?.addEventListener("click", () => {
  requestMediaFullscreen();
});

p5Elements.close?.addEventListener("click", () => {
  if (playerReady && player) {
    player.stopVideo();
  }
  p5Elements.mediaDock.hidden = true;
});

document.addEventListener("fullscreenchange", () => {
  p5Elements.fullscreen.textContent = document.fullscreenElement ? "↙" : "⛶";
});

window.NexussP5 = {
  handleContextCommand,
  renderTask(task) {
    const knowledge = resultFor(task, "knowledge.web_research");
    const media = resultFor(task, "media.youtube.discover");
    if (knowledge) {
      renderKnowledge(knowledge);
    }
    if (media) {
      renderMedia(media);
    }
  },
  summarizeTask(task) {
    const knowledge = resultFor(task, "knowledge.web_research");
    if (knowledge) {
      const count = Number(knowledge.source_count || 0);
      const suffix = count === 1 ? "" : "s";
      return (
        `I researched ${knowledge.query} using ${count} public source${suffix}. ` +
        "The cited brief is open in the Knowledge workspace; nothing was " +
        "saved to long-term memory."
      );
    }

    const media = resultFor(task, "media.youtube.discover");
    if (media) {
      const results = Array.isArray(media.results) ? media.results : [];
      if (results.length) {
        const selected = results[0];
        const review = media.selection_state === "review_required";
        return review
          ? `I preserved your exact search for ${media.query} and displayed ${results.length} ranked YouTube results. Select the exact item before playback.`
          : `I matched ${media.query} to ${selected.title} by ${selected.channel_title} and opened the full Nexuss media workspace.`;
      }
      return (
        "The media workspace is ready, but the official YouTube connector " +
        "returned no playable results."
      );
    }

    const phone = resultFor(task, "phone.open_youtube");
    if (phone) {
      return (
        "The exact allowlisted YouTube search was queued directly for the paired " +
        "phone. No approval step was required; native app opening remains " +
        "unverified until a companion node can attest it."
      );
    }

    const browser = resultFor(task, "device.open_web_search");
    if (browser) {
      return (
        `Chrome received the approved search handoff on ${browser.node_id}. ` +
        "The exact allowlisted URL is recorded in the Action Receipt."
      );
    }
    return null;
  },
};

/* P6.19 PROACTIVE CHAT ALERTS */

(() => {
  const POLL_MS = 15000;
  const seen = new Set();

  async function acknowledge(alertId) {
    try {
      await fetch(
        `/v1/proactive/alerts/${encodeURIComponent(alertId)}/ack`,
        {
          method: "POST",
          headers: apiHeaders(),
        },
      );
    } catch {
      // The retained alert can be acknowledged on a later poll.
    }
  }

  async function poll() {
    if (document.visibilityState !== "visible") return;

    try {
      const response = await fetch(
        "/v1/proactive/alerts",
        {
          headers: apiHeaders(),
          cache: "no-store",
        },
      );
      if (!response.ok) return;
      const alerts = await response.json();

      for (const alert of alerts || []) {
        if (seen.has(alert.alert_id)) continue;
        seen.add(alert.alert_id);

        const currentId = window.NexussConversation
          ?.currentConversationId?.();

        if (currentId === alert.conversation_id) {
          addMessage(
            "assistant",
            alert.detail || `Reminder: ${alert.title}`,
            false,
            {
              rich: false,
              speak: false,
              createdAt: alert.fired_at,
            },
          );
        } else {
          showToast(
            alert.title
              ? `Nexuss reminder: ${alert.title}`
              : "Nexuss has a proactive alert.",
          );
        }

        void acknowledge(alert.alert_id);
      }
    } catch (error) {
      console.warn("Proactive alert poll failed.", error);
    }
  }

  window.setInterval(() => void poll(), POLL_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void poll();
  });
  window.setTimeout(() => void poll(), 2500);
})();

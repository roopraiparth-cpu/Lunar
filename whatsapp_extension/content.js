(() => {
  if (window.__lunarWhatsAppReaderLoaded) return;
  window.__lunarWhatsAppReaderLoaded = true;

  const MAX_MESSAGES = 15;
  let observedPanel = null;
  let debounceTimer = null;
  let previousSnapshot = "";

  const badge = document.createElement("div");
  badge.textContent = "LUNAR LINK · CONNECTING";
  badge.setAttribute("role", "status");
  badge.style.cssText = [
    "position:fixed",
    "right:18px",
    "bottom:18px",
    "z-index:2147483647",
    "padding:9px 12px",
    "border:1px solid rgba(89,225,255,.35)",
    "border-radius:999px",
    "background:rgba(7,19,29,.92)",
    "color:#9feeff",
    "font:600 11px/1.2 system-ui,sans-serif",
    "letter-spacing:.08em",
    "box-shadow:0 0 18px rgba(49,202,255,.15)",
    "pointer-events:none"
  ].join(";");
  document.documentElement.appendChild(badge);

  function getActiveChatName(main) {
    const header = main.querySelector("header");
    const titled = header?.querySelector("span[title]");
    const name = titled?.getAttribute("title")?.trim();
    if (name && !/^(search|video|voice|more|menu)$/i.test(name)) return name.slice(0, 100);

    const label = header?.querySelector('[dir="auto"]')?.textContent?.trim();
    return label ? label.slice(0, 100) : "open chat";
  }

  function readVisibleChat() {
    if (document.visibilityState !== "visible") return null;
    const main = document.querySelector("#main");
    if (!main) return null;

    const messages = [...main.querySelectorAll(".message-in, .message-out")]
      .slice(-MAX_MESSAGES)
      .map((node) => {
        const textNode = node.querySelector('[data-testid="selectable-text"], .selectable-text');
        const text = textNode?.innerText?.replace(/\s+/g, " ").trim();
        if (!text) return null;
        return {
          direction: node.classList.contains("message-in") ? "incoming" : "outgoing",
          text: text.slice(0, 2000)
        };
      })
      .filter(Boolean);

    return { chat: getActiveChatName(main), messages };
  }

  function sendSnapshot() {
    const snapshot = readVisibleChat();
    if (!snapshot) return;
    const signature = JSON.stringify(snapshot);
    if (signature === previousSnapshot) return;
    previousSnapshot = signature;

    badge.textContent = "LUNAR LINK · SENDING OPEN CHAT";
    chrome.runtime.sendMessage(
      { type: "lunar-whatsapp-snapshot", snapshot },
      (result) => {
        if (chrome.runtime.lastError || !result?.ok) {
          badge.textContent = "LUNAR LINK · OFFLINE";
          return;
        }
        badge.textContent = "LUNAR LINK · OPEN CHAT ONLY";
      }
    );
  }

  function watchPanel() {
    const main = document.querySelector("#main");
    if (!main || main === observedPanel) return;
    observedPanel = main;
    new MutationObserver(() => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(sendSnapshot, 600);
    }).observe(main, { subtree: true, childList: true, characterData: true });
    sendSnapshot();
  }

  const pageObserver = new MutationObserver(watchPanel);
  pageObserver.observe(document.documentElement, { subtree: true, childList: true });
  watchPanel();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") sendSnapshot();
  });
})();

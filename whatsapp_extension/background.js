chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "lunar-whatsapp-snapshot") return;
  if (!sender.url?.startsWith("https://web.whatsapp.com/")) {
    sendResponse({ ok: false, message: "Only WhatsApp Web is allowed." });
    return;
  }

  fetch("http://127.0.0.1:8765/api/whatsapp/snapshot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(message.snapshot),
    credentials: "omit",
    cache: "no-store"
  })
    .then(async (response) => {
      const result = await response.json();
      sendResponse({ ...result, ok: response.ok && result.ok });
    })
    .catch(() => sendResponse({ ok: false, message: "Lunar is offline." }));

  return true;
});

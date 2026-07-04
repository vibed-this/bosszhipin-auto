chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "activate_tab") {
    (async () => {
      try {
        await chrome.tabs.update(sender.tab.id, { active: true });
        await chrome.windows.update(sender.tab.windowId, {
          state: "normal",
          focused: true,
        });
        sendResponse({ success: true, error: null });
      } catch (e) {
        sendResponse({ success: false, error: e.message });
      }
    })();
    return true;
  }
});

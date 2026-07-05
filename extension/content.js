(function () {
  "use strict";
  chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
    if (msg.type !== "execute") return;
    (async function () {
      try {
        const result = await eval("(async function(){ " + msg.code + " })()");
        sendResponse({ data: JSON.parse(JSON.stringify(result)), error: null });
      } catch (e) {
        sendResponse({ data: null, error: e.toString() + "\n" + (e.stack || "") });
      }
    })();
    return true;
  });
})();

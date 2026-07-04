(function () {
  "use strict";

  const SCRIPT_VERSION = "1.1.0";
  const STORAGE_KEY = "boss_remote_server_url";
  const DEFAULT_URL = "ws://127.0.0.1:8765/api/ws/tab";
  const RECONNECT_BASE_MS = 1000;
  const RECONNECT_MAX_MS = 30000;
  const PING_INTERVAL_MS = 15000;

  const TAB_ID = crypto.randomUUID();
  let ws = null;
  let destroyed = false;
  let reconnectAttempt = 0;
  let reconnectTimer = null;
  let pingTimer = null;

  function getServerUrl() {
    return DEFAULT_URL;
  }

  chrome.storage.local.get(STORAGE_KEY, (result) => {
    if (result[STORAGE_KEY]) {
      connect();
    } else {
      chrome.storage.local.set({ [STORAGE_KEY]: DEFAULT_URL }, () => {
        connect();
      });
    }
  });

  function connect() {
    if (destroyed) return;

    chrome.storage.local.get(STORAGE_KEY, (result) => {
      const url = result[STORAGE_KEY] || DEFAULT_URL;
      console.log(`[BossRemote] 连接服务: ${url}`);

      try {
        ws = new WebSocket(url);
      } catch (e) {
        console.error(`[BossRemote] 连接失败: ${e}`);
        scheduleReconnect();
        return;
      }

      ws.onopen = function () {
        reconnectAttempt = 0;
        console.log(`[BossRemote] 已连接: ${TAB_ID.slice(0, 8)}`);
        ws.send(
          JSON.stringify({
            type: "register",
            tabId: TAB_ID,
            url: location.href,
            title: document.title,
          })
        );
        startPing();
      };

      ws.onmessage = function (event) {
        try {
          const msg = JSON.parse(event.data);
          handleMessage(msg);
        } catch (e) {
          console.error(`[BossRemote] 消息解析失败: ${e}`);
        }
      };

      ws.onclose = function (event) {
        stopPing();
        console.log(`[BossRemote] 断开 (code=${event.code})`);
        if (!destroyed) scheduleReconnect();
      };

      ws.onerror = function () {
        ws.close();
      };
    });
  }

  function scheduleReconnect() {
    if (destroyed) return;
    const delay = Math.min(
      RECONNECT_BASE_MS * Math.pow(2, reconnectAttempt),
      RECONNECT_MAX_MS
    );
    reconnectAttempt++;
    console.log(`[BossRemote] ${delay}ms 后重连...`);
    reconnectTimer = setTimeout(connect, delay);
  }

  function startPing() {
    stopPing();
    pingTimer = setInterval(function () {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, PING_INTERVAL_MS);
  }

  function stopPing() {
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
  }

  function handleMessage(msg) {
    switch (msg.type) {
      case "execute":
        executeCode(msg.id, msg.context, msg.code);
        break;
      case "get_coordinates":
        handleGetCoordinates(msg.id, msg.selector);
        break;
      case "activate":
        handleActivate(msg.id);
        break;
      case "close":
        console.log("[BossRemote] 收到关闭指令");
        destroy();
        window.close();
        break;
      case "registered":
        console.log(`[BossRemote] 注册确认: ${msg.tabId.slice(0, 8)}`);
        break;
    }
  }

  function executeCode(id, context, code) {
    if (context === "page") {
      const wrappedCode = `
        (async function() {
          const __boss_id__ = ${JSON.stringify(id)};
          try {
            const result = await (async function() { ${code} })();
            window.dispatchEvent(new CustomEvent('__boss_result', {
              detail: {
                id: __boss_id__,
                data: JSON.parse(JSON.stringify(result)),
                error: null
              }
            }));
          } catch(e) {
            window.dispatchEvent(new CustomEvent('__boss_result', {
              detail: {
                id: __boss_id__,
                data: null,
                error: e.toString() + '\\\\n' + (e.stack || '')
              }
            }));
          }
        })();
      `;
      const el = document.createElement("script");
      el.textContent = `(${wrappedCode})();`;
      document.documentElement.appendChild(el);
      el.remove();
    } else if (context === "gm") {
      (async function () {
        try {
          const result = await eval(`(async function() { ${code} })()`);
          sendResult(id, JSON.parse(JSON.stringify(result)), null);
        } catch (e) {
          sendResult(id, null, e.toString() + "\n" + (e.stack || ""));
        }
      })();
    }
  }

  window.addEventListener("__boss_result", function (e) {
    const { id, data, error } = e.detail;
    sendResult(id, data, error);
  });

  function handleGetCoordinates(id, selector) {
    try {
      const el = document.querySelector(selector);
      if (!el) {
        sendResult(id, null, `元素未找到: ${selector}`);
        return;
      }
      const rect = el.getBoundingClientRect();
      const borderThickness = (window.outerWidth - window.innerWidth) / 2;
      const topUIHeight =
        window.outerHeight - window.innerHeight - borderThickness;
      const cssScreenX = window.screenX + borderThickness + rect.left;
      const cssScreenY = window.screenY + topUIHeight + rect.top;
      const ratio = window.devicePixelRatio;
      sendResult(id, {
        css: {
          x: Math.round(cssScreenX),
          y: Math.round(cssScreenY),
        },
        physical: {
          x: Math.round(cssScreenX * ratio),
          y: Math.round(cssScreenY * ratio),
        },
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      }, null);
    } catch (e) {
      sendResult(id, null, e.toString());
    }
  }

  function handleActivate(id) {
    chrome.runtime.sendMessage({ type: "activate_tab" }, (response) => {
      if (chrome.runtime.lastError) {
        sendResult(id, null, chrome.runtime.lastError.message);
      } else {
        sendResult(id, response, null);
      }
    });
  }

  function sendResult(id, data, error) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(
        JSON.stringify({
          type: "result",
          id: id,
          data: data,
          error: error,
        })
      );
    }
  }

  function sendUnregister() {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(
        JSON.stringify({
          type: "unregister",
          tabId: TAB_ID,
        })
      );
    }
  }

  function destroy() {
    if (destroyed) return;
    destroyed = true;
    sendUnregister();
    stopPing();
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws) {
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;
      ws.close();
      ws = null;
    }
  }

  window.addEventListener("beforeunload", destroy);

  window.addEventListener("pagehide", function () {
    sendUnregister();
  });

  window.addEventListener("pageshow", function () {
    if (destroyed) {
      destroyed = false;
      connect();
    }
  });

  window.__BOSS_REMOTE__ = {
    tabId: TAB_ID,
    version: SCRIPT_VERSION,
    connected: function () {
      return ws && ws.readyState === WebSocket.OPEN;
    },
  };
})();

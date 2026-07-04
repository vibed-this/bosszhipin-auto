// ==UserScript==
// @name         Boss直聘远程控制
// @namespace    https://github.com/bosszhipin-auto
// @version      1.0.0
// @description  远程控制Boss直聘页面，支持JS远程执行（page/gm双上下文）
// @author       bosszhipin-auto
// @match        https://*.zhipin.com/*
// @match        https://*.bosszhipin.com/*
// @grant        GM_info
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_log
// @run-at       document-start
// @license      MIT
// ==/UserScript==

(function () {
  "use strict";

  const SCRIPT_VERSION = "1.0.0";
  const SERVER_KEY = "boss_remote_server_url";
  const DEFAULT_URL = "ws://127.0.0.1:8765/api/ws/tab";
  const RECONNECT_BASE_MS = 1000;
  const RECONNECT_MAX_MS = 30000;
  const PING_INTERVAL_MS = 15000;

  const TAB_ID = (typeof window.__BOSS_EXPECTED_TAB_ID__ !== "undefined" && window.__BOSS_EXPECTED_TAB_ID__)
    ? window.__BOSS_EXPECTED_TAB_ID__
    : crypto.randomUUID();
  let ws = null;
  let destroyed = false;
  let reconnectAttempt = 0;
  let reconnectTimer = null;
  let pingTimer = null;
  let pendingExecutions = new Map();

  // ── Config ────────────────────────────────────────────────

  function getServerUrl() {
    try {
      return GM_getValue(SERVER_KEY, DEFAULT_URL);
    } catch {
      return DEFAULT_URL;
    }
  }

  // ── Page-context execution bridge ─────────────────────────

  function injectScript(fn) {
    const el = document.createElement("script");
    el.textContent = `(${fn})();`;
    document.documentElement.appendChild(el);
    el.remove();
  }

  // Listen for results from page context
  window.addEventListener("__boss_result", function (e) {
    const { id, data, error } = e.detail;
    sendResult(id, data, error);
  });

  // ── WebSocket ─────────────────────────────────────────────

  function connect() {
    if (destroyed) return;

    const url = getServerUrl();
    GM_log(`[BossRemote] 连接服务: ${url}`);

    try {
      ws = new WebSocket(url);
    } catch (e) {
      GM_log(`[BossRemote] 连接失败: ${e}`);
      scheduleReconnect();
      return;
    }

    ws.onopen = function () {
      reconnectAttempt = 0;
      GM_log(`[BossRemote] 已连接: ${TAB_ID.slice(0, 8)}`);
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
        GM_log(`[BossRemote] 消息解析失败: ${e}`);
      }
    };

    ws.onclose = function (event) {
      stopPing();
      GM_log(`[BossRemote] 断开 (code=${event.code})`);
      if (!destroyed) scheduleReconnect();
    };

    ws.onerror = function () {
      ws.close();
    };
  }

  function scheduleReconnect() {
    if (destroyed) return;
    const delay = Math.min(
      RECONNECT_BASE_MS * Math.pow(2, reconnectAttempt),
      RECONNECT_MAX_MS
    );
    reconnectAttempt++;
    GM_log(`[BossRemote] ${delay}ms 后重连...`);
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

  // ── Message handling ──────────────────────────────────────

  function handleMessage(msg) {
    switch (msg.type) {
      case "execute":
        executeCode(msg.id, msg.context, msg.code);
        break;
      case "close":
        GM_log("[BossRemote] 收到关闭指令");
        destroy();
        window.close();
        break;
      case "registered":
        GM_log(`[BossRemote] 注册确认: ${msg.tabId.slice(0, 8)}`);
        break;
    }
  }

  function executeCode(id, context, code) {
    if (context === "page") {
      // Execute in page context via injected script
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
                error: e.toString() + '\\n' + (e.stack || '')
              }
            }));
          }
        })();
      `;
      injectScript(wrappedCode);
    } else if (context === "gm") {
      // Execute in GM (userscript) context
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

  // ── Lifecycle ─────────────────────────────────────────────

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

  // Handle visibility change: close when tab is being destroyed
  window.addEventListener("beforeunload", destroy);

  // Also handle pagehide for bfcache scenarios
  window.addEventListener("pagehide", function () {
    // Don't fully destroy on pagehide (bfcache might restore)
    sendUnregister();
  });

  window.addEventListener("pageshow", function () {
    // If we were restored from bfcache, re-register
    if (destroyed) {
      destroyed = false;
      connect();
    }
  });

  // ── Start ─────────────────────────────────────────────────

  connect();

  // Expose some info globally for debugging
  window.__BOSS_REMOTE__ = {
    tabId: TAB_ID,
    version: SCRIPT_VERSION,
    connected: function () {
      return ws && ws.readyState === WebSocket.OPEN;
    },
  };
})();

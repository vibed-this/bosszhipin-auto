(function () {
  "use strict";

  const WS_URL = "ws://127.0.0.1:8765/api/ws";
  const HTTP_BASE = "http://127.0.0.1:8765";
  const RECONNECT_DELAY_MS = 1000;
  const PING_INTERVAL_MS = 15000;

  let ws = null;
  let destroyed = false;
  let reconnectTimer = null;
  let pingTimer = null;
  const sendQueue = [];

  // ── WebSocket ──────────────────────────────────────────────

  function connect() {
    if (destroyed) return;
    console.log("[BossRemote] 连接服务: " + WS_URL);

    let instance;
    try {
      instance = new WebSocket(WS_URL);
      ws = instance;
    } catch (e) {
      console.error("[BossRemote] 连接失败: " + e);
      scheduleReconnect();
      return;
    }

    instance.onopen = function () {
      if (ws !== instance) return;
      console.log("[BossRemote] 已连接");
      flushSendQueue();
      startPing();
      pushSyncState();
    };

    instance.onmessage = function (event) {
      if (ws !== instance) return;
      try {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
      } catch (e) {
        console.error("[BossRemote] 消息解析失败: " + e);
      }
    };

    instance.onclose = function (event) {
      stopPing();
      console.log("[BossRemote] 断开 (code=" + event.code + ")");
      if (!destroyed) scheduleReconnect();
    };

    instance.onerror = function () {
      if (ws === instance) {
        ws.close();
      }
    };
  }

  function scheduleReconnect() {
    if (destroyed) return;
    reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
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

  function sendWS(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data));
    } else {
      sendQueue.push(data);
    }
  }

  function flushSendQueue() {
    while (sendQueue.length > 0) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(sendQueue.shift()));
      } else {
        break;
      }
    }
  }

  function sendResult(id, data, error) {
    sendWS({ type: "result", id: id, data: data, error: error || null });
  }

  function destroy() {
    if (destroyed) return;
    destroyed = true;
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

  // ── Tab event listeners ────────────────────────────────────

  function setupTabListeners() {
    chrome.tabs.onCreated.addListener(function (tab) {
      sendWS({
        type: "tab_created",
        chromeTabId: tab.id,
        url: tab.url || "",
        title: tab.title || "",
        status: tab.status || "loading",
        active: tab.active || false,
        windowId: tab.windowId,
      });
    });

    chrome.tabs.onUpdated.addListener(function (tabId, changeInfo, tab) {
      if (changeInfo.url || changeInfo.title || changeInfo.status) {
        sendWS({
          type: "tab_updated",
          chromeTabId: tabId,
          url: tab.url,
          title: tab.title,
          status: tab.status,
        });
      }
    });

    chrome.tabs.onRemoved.addListener(function (tabId) {
      sendWS({ type: "tab_closed", chromeTabId: tabId });
    });

    chrome.tabs.onActivated.addListener(function (activeInfo) {
      sendWS({
        type: "tab_activated",
        chromeTabId: activeInfo.tabId,
        windowId: activeInfo.windowId,
      });
    });
  }

  async function pushSyncState() {
    try {
      const tabs = await chrome.tabs.query({});
      const list = tabs.map(function (tab) {
        return {
          chromeTabId: tab.id,
          url: tab.url || "",
          title: tab.title || "",
          status: tab.status || "complete",
          active: tab.active,
          windowId: tab.windowId,
        };
      });
      sendWS({ type: "sync_state", tabs: list });
    } catch (e) {
      console.error("[BossRemote] sync_state 失败: " + e.message);
    }
  }

  // ── Message handlers ───────────────────────────────────────

  function handleMessage(msg) {
    switch (msg.type) {
      case "open_tab":
        handleOpenTab(msg.id, msg.url);
        break;
      case "close_tab":
        handleCloseTab(msg.id, msg.chromeTabId);
        break;
      case "activate_tab":
        handleActivateTab(msg.id, msg.chromeTabId);
        break;
      case "reload_tab":
        handleReloadTab(msg.id, msg.chromeTabId);
        break;
      case "list_tabs":
        handleListTabs(msg.id);
        break;
      case "execute":
        handleExecute(msg.id, msg.chromeTabId, msg.code, msg.world, msg.execId);
        break;
      case "query":
        handleQuery(msg.id, msg.chromeTabId, msg.select, msg.filter, msg.project, msg["return"]);
        break;
    }
  }

  async function handleOpenTab(id, url) {
    try {
      const tab = await chrome.tabs.create({ url: url });
      sendResult(id, { chromeTabId: tab.id, url: url }, null);
    } catch (e) {
      sendResult(id, null, e.message);
    }
  }

  async function handleCloseTab(id, chromeTabId) {
    try {
      await chrome.tabs.remove(chromeTabId);
      sendResult(id, { success: true }, null);
    } catch (e) {
      sendResult(id, null, e.message);
    }
  }

  async function handleActivateTab(id, chromeTabId) {
    try {
      const tab = await chrome.tabs.get(chromeTabId);
      const win = await chrome.windows.get(tab.windowId);
      await chrome.tabs.update(chromeTabId, { active: true });
      await chrome.windows.update(tab.windowId, {
        state: win.state === "minimized" ? "normal" : win.state,
        focused: true,
      });
      sendResult(id, { success: true }, null);
    } catch (e) {
      sendResult(id, null, e.message);
    }
  }

  async function handleReloadTab(id, chromeTabId) {
    try {
      await chrome.tabs.reload(chromeTabId);
      sendResult(id, { chromeTabId: chromeTabId }, null);
    } catch (e) {
      sendResult(id, null, e.message);
    }
  }

  async function handleListTabs(id) {
    try {
      const tabs = await chrome.tabs.query({});
      const result = tabs.map(function (tab) {
        return {
          chromeTabId: tab.id,
          url: tab.url || "",
          title: tab.title || "",
          active: tab.active,
          windowId: tab.windowId,
        };
      });
      sendResult(id, result, null);
    } catch (e) {
      sendResult(id, null, e.message);
    }
  }

  // ── Execute (via content.js CSP-exempt eval) ───────────────

  async function handleExecute(id, chromeTabId, code, world, execId) {
    try {
      if (world === "main") {
        await handleExecuteMain(id, chromeTabId, execId);
      } else {
        const resp = await chrome.tabs.sendMessage(chromeTabId, {
          type: "execute",
          code: code,
        });
        if (resp.error) {
          sendResult(id, null, resp.error);
        } else {
          sendResult(id, resp.data, null);
        }
      }
    } catch (e) {
      sendResult(id, null, e.message);
    }
  }

  // ── Execute: MAIN world (via <script src="/exec/{execId}">) ─

  async function handleExecuteMain(id, chromeTabId, execId) {
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId: chromeTabId },
        world: "ISOLATED",
        func: async function (execId, baseUrl) {
          return await new Promise(function (resolve, reject) {
            var handler = function (event) {
              if (event.data && event.data.type === "boss_exec_result" && event.data.id === execId) {
                window.removeEventListener("message", handler);
                if (event.data.error) {
                  reject(new Error(event.data.error));
                } else {
                  resolve(event.data.data !== undefined ? event.data.data : null);
                }
              }
            };
            window.addEventListener("message", handler);

            var s = document.createElement("script");
            s.src = baseUrl + "/exec/" + execId;
            s.onerror = function () {
              window.removeEventListener("message", handler);
              reject(new Error("Failed to load exec script"));
            };
            document.head.appendChild(s);

            setTimeout(function () {
              window.removeEventListener("message", handler);
              reject(new Error("Execute timeout (MAIN world)"));
            }, 30000);
          });
        },
        args: [execId, HTTP_BASE],
      });
      sendResult(id, results[0]?.result, null);
    } catch (e) {
      sendResult(id, null, e.message);
    }
  }

  // ── Scripting: query ───────────────────────────────────────

  const QUERY_FUNC = function (args) {
    function bboxOf(el) {
      var rect = el.getBoundingClientRect();
      var borderThickness = (window.outerWidth - window.innerWidth) / 2;
      var topUIHeight = window.outerHeight - window.innerHeight - borderThickness;
      var cssX = window.screenX + borderThickness + rect.left;
      var cssY = window.screenY + topUIHeight + rect.top;
      var dpr = window.devicePixelRatio || 1;
      return {
        css: {
          x: Math.round(cssX),
          y: Math.round(cssY),
          w: Math.round(rect.width),
          h: Math.round(rect.height),
          cx: Math.round(cssX + rect.width / 2),
          cy: Math.round(cssY + rect.height / 2),
        },
        physical: {
          x: Math.round(cssX * dpr),
          y: Math.round(cssY * dpr),
          w: Math.round(rect.width * dpr),
          h: Math.round(rect.height * dpr),
          cx: Math.round((cssX + rect.width / 2) * dpr),
          cy: Math.round((cssY + rect.height / 2) * dpr),
        },
      };
    }

    function parseProjectSpec(spec) {
      var atIdx = spec.lastIndexOf("@");
      if (atIdx === -1) return { sub: spec || "", attr: "text" };
      return { sub: atIdx === 0 ? "" : spec.slice(0, atIdx), attr: spec.slice(atIdx + 1) };
    }

    function getAttr(el, attr, all) {
      switch (attr) {
        case "text": return (el.textContent || "").replace(/\s+/g, " ").trim();
        case "html": return el.innerHTML || "";
        case "index": return all.indexOf(el);
        default:
          if (attr.startsWith("class~")) return el.classList.contains(attr.slice(6));
          return el.getAttribute(attr) || "";
      }
    }

    function applyFilter(all, filter) {
      if (!filter) return all;
      var result = all;
      if (filter.textContains) {
        var kw = String(filter.textContains);
        result = result.filter(function (el) { return (el.textContent || "").includes(kw); });
      }
      if (filter.textAny) {
        var kws = Array.isArray(filter.textAny) ? filter.textAny : [filter.textAny];
        result = result.filter(function (el) {
          var text = el.textContent || "";
          return kws.some(function (kw) { return text.includes(kw); });
        });
      }
      if (filter.textNone) {
        var kws = Array.isArray(filter.textNone) ? filter.textNone : [filter.textNone];
        result = result.filter(function (el) {
          var text = el.textContent || "";
          return !kws.some(function (kw) { return text.includes(kw); });
        });
      }
      if (filter.nth === "last" && result.length > 0) {
        result = [result[result.length - 1]];
      }
      if (filter.index !== undefined) {
        var idx = parseInt(filter.index, 10);
        result = idx >= 0 && idx < result.length ? [result[idx]] : [];
      }
      return result;
    }

    function projectEl(el, project, all) {
      if (!project) return {};
      var result = {};
      for (var key in project) {
        if (!project.hasOwnProperty(key)) continue;
        var spec = project[key];
        if (Array.isArray(spec)) {
          var values = [];
          for (var si = 0; si < spec.length; si++) {
            var parsed = parseProjectSpec(spec[si]);
            if (parsed.sub) {
              var subs = el.querySelectorAll(parsed.sub);
              for (var j = 0; j < subs.length; j++) {
                values.push(getAttr(subs[j], parsed.attr, all));
              }
            } else {
              values.push(getAttr(el, parsed.attr, all));
            }
          }
          result[key] = values;
        } else {
          var parsed = parseProjectSpec(spec);
          if (parsed.sub) {
            var subEl = el.querySelector(parsed.sub);
            result[key] = subEl ? getAttr(subEl, parsed.attr, all) : null;
          } else {
            result[key] = getAttr(el, parsed.attr, all);
          }
        }
      }
      return result;
    }

    try {
      var t0 = performance.now();
      var all = Array.from(document.querySelectorAll(args.select));
      var matched = applyFilter(all, args.filter);
      var data;

      switch (args["return"]) {
        case "bbox":
          data = matched[0] ? (matched[0].scrollIntoView({block: 'center', behavior: 'instant'}), bboxOf(matched[0])) : null;
          break;
        case "bboxList":
          data = matched.map(bboxOf);
          break;
        case "list":
          data = matched.map(function (el) { return projectEl(el, args.project, all); });
          break;
        case "first":
          data = matched[0] ? projectEl(matched[0], args.project, all) : null;
          break;
        case "count":
          data = matched.length;
          break;
        case "raw":
          data = matched.map(function (el) {
            return {
              text: (el.textContent || "").trim().slice(0, 200),
              html: el.outerHTML.slice(0, 500),
            };
          });
          break;
        default:
          throw new Error("unknown return: " + args["return"]);
      }

      return {
        data: data,
        _meta: {
          url: location.href,
          matched: matched.length,
          tookMs: Math.round(performance.now() - t0),
        },
      };
    } catch (e) {
      return { data: null, _meta: null, __error__: e.toString() };
    }
  };

  async function handleQuery(id, chromeTabId, select, filter, project, return_) {
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId: chromeTabId },
        world: "ISOLATED",
        func: QUERY_FUNC,
        args: [{
          select: select,
          filter: filter || null,
          project: project || null,
          "return": return_ || "list",
        }],
      });
      var result = results[0]?.result;
      if (result && result.__error__) {
        sendResult(id, null, result.__error__);
      } else {
        sendResult(id, result, null);
      }
    } catch (e) {
      sendResult(id, null, e.message);
    }
  }

  // ── Startup ────────────────────────────────────────────────

  chrome.runtime.onStartup.addListener(function () {
    destroyed = false;
    connect();
  });

  chrome.runtime.onInstalled.addListener(function () {
    destroyed = false;
    connect();
  });

  setupTabListeners();
  connect();

  self.__BOSS_BG__ = {
    connected: function () { return ws && ws.readyState === WebSocket.OPEN; },
  };
})();

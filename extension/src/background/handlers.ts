import { Socket } from 'socket.io-client';
import { executeInIsolatedWorld } from './execute';
import { queryEngine } from './query-engine';

const HTTP_BASE = 'http://127.0.0.1:8765';

type Ack = (result: any) => void;

export function registerHandlers(socket: Socket): void {
  socket.on('open_tab', async (data: { url: string }, ack: Ack) => {
    try {
      console.debug('[BossRemote] 打开标签: url=' + data.url);
      const tab = await chrome.tabs.create({ url: data.url });
      console.debug('[BossRemote] 标签已创建: chromeTabId=' + tab.id);
      ack({ chromeTabId: tab.id, url: data.url });
    } catch (e) {
      console.error('[BossRemote] 打开标签失败:', (e as Error).message);
      ack({ error: (e as Error).message });
    }
  });

  socket.on('close_tab', async (data: { chromeTabId: number }, ack: Ack) => {
    try {
      console.debug('[BossRemote] 关闭标签: chromeTabId=' + data.chromeTabId);
      await chrome.tabs.remove(data.chromeTabId);
      console.debug('[BossRemote] 标签已移除');
      ack({ success: true });
    } catch (e) {
      console.error('[BossRemote] 关闭标签失败:', (e as Error).message);
      ack({ error: (e as Error).message });
    }
  });

  socket.on('activate_tab', async (data: { chromeTabId: number }, ack: Ack) => {
    try {
      console.debug('[BossRemote] 激活标签窗口: chromeTabId=' + data.chromeTabId);
      const tab = await chrome.tabs.get(data.chromeTabId);
      const win = await chrome.windows.get(tab.windowId!);
      console.debug('[BossRemote] 窗口状态: ' + win.state + ', windowId=' + tab.windowId);
      await chrome.tabs.update(data.chromeTabId, { active: true });
      await chrome.windows.update(tab.windowId!, {
        state: win.state === 'minimized' ? 'normal' : win.state,
        focused: true,
      });
      console.debug('[BossRemote] 标签已激活');
      ack({ success: true });
    } catch (e) {
      console.error('[BossRemote] 激活标签失败:', (e as Error).message);
      ack({ error: (e as Error).message });
    }
  });

  socket.on('reload_tab', async (data: { chromeTabId: number }, ack: Ack) => {
    try {
      console.debug('[BossRemote] 刷新标签: chromeTabId=' + data.chromeTabId);
      await chrome.tabs.reload(data.chromeTabId);
      console.debug('[BossRemote] 标签已刷新');
      ack({ chromeTabId: data.chromeTabId });
    } catch (e) {
      console.error('[BossRemote] 刷新标签失败:', (e as Error).message);
      ack({ error: (e as Error).message });
    }
  });

  socket.on('list_tabs', async (_data: any, ack: Ack) => {
    try {
      console.debug('[BossRemote] 查询所有标签...');
      const tabs = await chrome.tabs.query({});
      const result = tabs.map((tab) => ({
        chromeTabId: tab.id,
        url: tab.url || '',
        title: tab.title || '',
        active: tab.active,
        windowId: tab.windowId,
      }));
      console.debug('[BossRemote] 标签数: ' + result.length);
      ack(result);
    } catch (e) {
      console.error('[BossRemote] 列出标签失败:', (e as Error).message);
      ack({ error: (e as Error).message });
    }
  });

  socket.on('execute', async (data: { chromeTabId: number; execId: string }, ack: Ack) => {
    try {
      console.debug('[BossRemote] 执行JS: chromeTabId=' + data.chromeTabId + ' execId=' + data.execId);
      const results = await chrome.scripting.executeScript({
        target: { tabId: data.chromeTabId },
        world: 'ISOLATED',
        func: executeInIsolatedWorld,
        args: [data.execId, HTTP_BASE],
      });
      console.debug('[BossRemote] 脚本执行结果:', results[0]?.result !== undefined ? '成功' : '空');
      ack(results[0]?.result);
    } catch (e) {
      console.error('[BossRemote] 脚本执行失败:', (e as Error).message);
      ack({ error: (e as Error).message });
    }
  });

  socket.on('query', async (data: {
    chromeTabId: number;
    select: string;
    filter?: any;
    project?: any;
    return?: string;
  }, ack: Ack) => {
    try {
      console.debug('[BossRemote] 执行DOM查询: tab=' + data.chromeTabId + ' select=' + data.select + ' return=' + (data.return || 'list'));
      console.debug('[BossRemote] 查询参数:', JSON.stringify({ filter: data.filter, project: data.project }));
      const results = await chrome.scripting.executeScript({
        target: { tabId: data.chromeTabId },
        world: 'ISOLATED',
        func: queryEngine,
        args: [{
          select: data.select,
          filter: data.filter || null,
          project: data.project || null,
          return: (data.return || 'list') as any,
        }],
      });
      const result = results[0]?.result;
      if (result && result.__error__) {
        console.error('[BossRemote] 查询错误:', result.__error__);
        ack({ error: result.__error__ });
      } else {
        console.debug('[BossRemote] 查询成功: matched=' + (result?._meta?.matched || 0) + ' took=' + (result?._meta?.tookMs || 0) + 'ms');
        ack(result);
      }
    } catch (e) {
      console.error('[BossRemote] 查询失败:', (e as Error).message);
      ack({ error: (e as Error).message });
    }
  });

  socket.on('dump_html', async (data: { chromeTabId: number }, ack: Ack) => {
    try {
      console.debug('[BossRemote] Dump HTML: chromeTabId=' + data.chromeTabId);
      const results = await chrome.scripting.executeScript({
        target: { tabId: data.chromeTabId },
        world: 'ISOLATED',
        func: () => document.documentElement.outerHTML,
      });
      ack(results[0]?.result || null);
    } catch (e) {
      console.error('[BossRemote] Dump HTML 失败:', (e as Error).message);
      ack({ error: (e as Error).message });
    }
  });
}
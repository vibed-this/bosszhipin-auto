import { getSocket } from './socket';
import { TabInfo } from '../protocol/types';

export function setupTabListeners(): void {
  chrome.tabs.onCreated.addListener((tab) => {
    const socket = getSocket();
    const tabInfo: TabInfo = {
      chromeTabId: tab.id!,
      url: tab.url || '',
      title: tab.title || '',
      status: tab.status || 'loading',
      active: tab.active || false,
      windowId: tab.windowId,
    };
    socket.emit('tab_created', tabInfo);
  });

  chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.url || changeInfo.title || changeInfo.status) {
      const socket = getSocket();
      socket.emit('tab_updated', {
        chromeTabId: tabId,
        url: tab.url,
        title: tab.title,
        status: tab.status,
      });
    }
  });

  chrome.tabs.onRemoved.addListener((tabId) => {
    const socket = getSocket();
    socket.emit('tab_closed', { chromeTabId: tabId });
  });

  chrome.tabs.onActivated.addListener((activeInfo) => {
    const socket = getSocket();
    socket.emit('tab_activated', {
      chromeTabId: activeInfo.tabId,
      windowId: activeInfo.windowId,
    });
  });
}

export async function pushSyncState(): Promise<void> {
  try {
    console.debug('[BossRemote] 推送同步状态...');
    const tabs = await chrome.tabs.query({});
    const list: TabInfo[] = tabs.map((tab) => ({
      chromeTabId: tab.id!,
      url: tab.url || '',
      title: tab.title || '',
      status: tab.status || 'complete',
      active: tab.active,
      windowId: tab.windowId,
    }));
    console.debug('[BossRemote] 同步标签数: ' + list.length);
    const socket = getSocket();
    socket.emit('sync_state', { tabs: list });
  } catch (e) {
    console.error('[BossRemote] sync_state 失败: ' + (e as Error).message);
  }
}
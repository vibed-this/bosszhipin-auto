import { initSocket, getSocket, setOnConnected } from './socket';
import { setupTabListeners, pushSyncState } from './tab-manager';
import { registerHandlers } from './handlers';

const KEEPALIVE_ALARM = 'sw-keepalive';

const socket = initSocket();
setupTabListeners();
registerHandlers(socket);

// account_id 注册完成后推送同步状态（避免竞态）
setOnConnected(() => {
  pushSyncState();
});

// 定期唤醒 Service Worker，防止被 Chrome 销毁
chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 0.25 });

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === KEEPALIVE_ALARM) {
    const s = getSocket();
    if (!s.connected) {
      s.connect();
    }
  }
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 0.25 });
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 0.25 });
});

chrome.runtime.onSuspend.addListener(() => {
  console.log('[BossRemote] Service Worker 即将休眠');
});
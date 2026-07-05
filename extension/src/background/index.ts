import { initSocket } from './socket';
import { setupTabListeners, pushSyncState } from './tab-manager';
import { registerHandlers } from './handlers';

const socket = initSocket();
setupTabListeners();
registerHandlers(socket);

// 连接成功后推送同步状态
socket.on('connect', () => {
  pushSyncState();
});

chrome.runtime.onStartup.addListener(() => {
  // Socket.IO 自动重连
});

chrome.runtime.onInstalled.addListener(() => {
  // Socket.IO 自动重连
});
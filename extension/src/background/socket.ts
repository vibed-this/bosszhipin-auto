import { io, Socket } from 'socket.io-client';

let socket: Socket | null = null;

let onConnected: (() => void) | null = null;

export function setOnConnected(cb: () => void): void {
  onConnected = cb;
}

export function initSocket(): Socket {
  socket = io('http://127.0.0.1:8765', {
    transports: ['websocket'],
    reconnection: true,
    reconnectionDelay: 1000,
  });

  socket.on('connect', () => {
    console.log('[BossRemote] Socket.IO 已连接');
    chrome.storage.local.get('account_id', (result) => {
      const accountId = result.account_id || 'default';
      socket!.emit('register_account', { account_id: accountId });
      console.log('[BossRemote] 已注册 account_id:', accountId);
      if (onConnected) onConnected();
    });
  });

  socket.on('disconnect', (reason) => {
    console.log('[BossRemote] Socket.IO 断开:', reason);
  });

  socket.on('connect_error', (error) => {
    console.error('[BossRemote] 连接错误:', error.message);
  });

  return socket;
}

export function getSocket(): Socket {
  if (!socket) {
    throw new Error('Socket 未初始化');
  }
  return socket;
}
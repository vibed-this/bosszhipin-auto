const HTTP_BASE = 'http://127.0.0.1:8765';

export function executeInIsolatedWorld(execId: string, baseUrl: string): Promise<any> {
  return new Promise((resolve, reject) => {
    const handler = (event: MessageEvent) => {
      if (event.data && event.data.type === 'boss_exec_result' && event.data.id === execId) {
        window.removeEventListener('message', handler);
        if (event.data.error) {
          reject(new Error(event.data.error));
        } else {
          resolve(event.data.data !== undefined ? event.data.data : null);
        }
      }
    };
    window.addEventListener('message', handler);

    const s = document.createElement('script');
    s.src = baseUrl + '/exec/' + execId;
    s.onerror = () => {
      window.removeEventListener('message', handler);
      reject(new Error('Failed to load exec script'));
    };
    document.head.appendChild(s);

    setTimeout(() => {
      window.removeEventListener('message', handler);
      reject(new Error('Execute timeout (MAIN world)'));
    }, 30000);
  });
}
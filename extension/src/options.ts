const accountIdInput = document.getElementById('accountId') as HTMLInputElement;
const saveBtn = document.getElementById('saveBtn') as HTMLButtonElement;
const statusEl = document.getElementById('status') as HTMLDivElement;

document.addEventListener('DOMContentLoaded', () => {
  chrome.storage.local.get('account_id', (result) => {
    accountIdInput.value = result.account_id || '';
  });
});

function showStatus(msg: string, type: 'success' | 'error') {
  statusEl.textContent = msg;
  statusEl.className = 'status ' + type;
  setTimeout(() => {
    statusEl.textContent = '';
    statusEl.className = 'status';
  }, 2500);
}

saveBtn.addEventListener('click', () => {
  const accountId = accountIdInput.value.trim() || 'default';
  saveBtn.disabled = true;
  saveBtn.textContent = '保存中...';
  chrome.storage.local.set({ account_id: accountId }, () => {
    saveBtn.disabled = false;
    saveBtn.textContent = '保存';
    if (chrome.runtime.lastError) {
      showStatus('保存失败: ' + chrome.runtime.lastError.message, 'error');
    } else {
      showStatus('已保存: ' + accountId, 'success');
    }
  });
});

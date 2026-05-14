const toastEl = document.getElementById('toast');
let toastTimer = null;

function showToast(msg, type = 'success') {
  toastEl.textContent = msg;
  toastEl.className = `show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.className = ''; }, 3000);
}

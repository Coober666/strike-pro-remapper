const form = document.getElementById('pair-form');
const field = document.getElementById('pair-link');
const pairingStatus = document.getElementById('status');
const button = document.getElementById('pair-submit');
async function pair(value) {
  if (button.disabled) return;
  let token = value.trim();
  if (token.includes('#')) token = new URLSearchParams(token.slice(token.indexOf('#') + 1)).get('pair') || '';
  button.disabled = true;
  field.value = '';
  pairingStatus.textContent = 'Pairing with the editor…';
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), 10000);
  try {
    const response = await fetch('/wifi/pair', {method:'POST', signal:timeout.signal,
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({token})});
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || 'Pairing failed.');
    location.replace('/');
  } catch (error) {
    pairingStatus.textContent = error.name === 'AbortError' ? 'The host did not respond. Check Wi-Fi and try the pairing link again.' : error.message;
  } finally { clearTimeout(timer); button.disabled = false; }
}
form.onsubmit = event => { event.preventDefault(); void pair(field.value); };
function useLink() {
  const token = new URLSearchParams(location.hash.slice(1)).get('pair');
  if (token) { history.replaceState(null, '', location.pathname); void pair(token); }
}
window.addEventListener('hashchange', useLink);
useLink();

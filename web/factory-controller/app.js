const $ = id => document.getElementById(id);
const hostSession = document.documentElement.dataset.hostSession === 'true';
const pairing = new URLSearchParams(location.hash.slice(1)).get('pair');
if (pairing) {
  if (pairing !== sessionStorage.getItem('strike_factory_pair')) sessionStorage.removeItem('strike_factory_job');
  sessionStorage.setItem('strike_factory_pair', pairing);
  history.replaceState(null, '', location.pathname);
}
window.addEventListener('hashchange', () => {
  if (new URLSearchParams(location.hash.slice(1)).get('pair')) location.reload();
});
let token = hostSession ? 'paired-editor-session' : sessionStorage.getItem('strike_factory_pair') || '';
let busy = false;
const message = text => { $('status').textContent = text; };
function controls() {
  $('connect').disabled = busy || !token;
  $('output').disabled = busy || !token;
  $('activate').disabled = busy || !token || !$('output').value;
  $('forget').disabled = busy;
  $('pair-status').textContent = hostSession ? 'Using your paired editor connection.' : token ? 'Pairing link ready. Find the Strike to connect to its host.' : 'Open the pairing link shown on the USB host to begin.';
  if (hostSession) $('forget').textContent = 'Back to editor';
}
async function api(path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(path, { signal:controller.signal, headers:{ ...(hostSession ? {} : {Authorization:'Bearer ' + token}), ...(body ? {'Content-Type':'application/json'} : {}) },
      ...(body ? {method:'POST', body:JSON.stringify(body)} : {}) });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || 'Controller request failed.');
    return data;
  } finally { clearTimeout(timer); }
}
async function observe(id) {
  const until = Date.now() + 30000;
  while (Date.now() < until) {
    const job = await api('/api/jobs/' + id);
    message(job.message);
    if (!['checking', 'sent'].includes(job.state)) {
      sessionStorage.removeItem('strike_factory_job');
      return;
    }
    await new Promise(resolve => { setTimeout(resolve, 600); });
  }
  throw new Error('Confirmation timed out. Check the host before retrying; the command may have been sent.');
}
$('connect').onclick = async () => {
  busy = true; controls();
  try {
    const data = await api('/api/outputs');
    $('output').replaceChildren(new Option('Select the connected Strike', ''));
    for (const output of data.outputs) $('output').add(new Option(output.name, output.id));
    if (data.outputs.length === 1) $('output').value = data.outputs[0].id;
    message(data.outputs.length ? 'Select the Strike, then activate its factory card.' : 'No Strike found on the USB host. Check its cable and power.');
  } catch (err) { message(err.message); }
  finally { busy = false; controls(); }
};
$('output').onchange = controls;
$('activate').onclick = async () => {
  if (busy || !$('output').value) return;
  busy = true; controls();
  const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2,'0')).join('');
  sessionStorage.setItem('strike_factory_job', id);
  try {
    await api('/api/activate', {output:$('output').value, request_id:id});
    await observe(id);
  } catch (err) { message(err.message + ' No automatic retry was sent. Check the host before trying again.'); }
  finally { busy = false; controls(); }
};
$('forget').onclick = () => {
  if (hostSession) { location.assign('/'); return; }
  sessionStorage.removeItem('strike_factory_pair');
  sessionStorage.removeItem('strike_factory_job');
  token = ''; controls(); message('Pairing forgotten on this iPad.');
};
controls();
const pending = sessionStorage.getItem('strike_factory_job');
if (pending && token) {
  busy = true; controls();
  observe(pending).catch(err => message(err.message + ' Check the host before trying again.'))
    .finally(() => { busy = false; controls(); });
}

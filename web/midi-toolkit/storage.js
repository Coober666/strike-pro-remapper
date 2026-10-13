import {validateSession} from './core.js';
const dbReady = new Promise((resolve, reject) => {
  const request = indexedDB.open('drum-midi-toolkit', 1);
  request.onupgradeneeded = () => {
    request.result.createObjectStore('sessions', {keyPath:'id'});
    request.result.createObjectStore('metadata', {keyPath:'id'});
  };
  request.onsuccess = () => resolve(request.result);
  request.onerror = () => reject(request.error);
  request.onblocked = () => reject(new Error('Close other toolkit pages and try again.'));
});
// Attach a rejection handler immediately; callers still receive the original error.
dbReady.catch(() => {});
export async function listSessions() {
  const db = await dbReady;
  return new Promise((resolve, reject) => {
    const r = db.transaction('metadata').objectStore('metadata').getAll();
    r.onsuccess = () => resolve(r.result.sort((a,b) => b.savedAt.localeCompare(a.savedAt)));
    r.onerror = () => reject(r.error);
  });
}
export async function readSession(id) {
  const db = await dbReady;
  return new Promise((resolve, reject) => {
    const r = db.transaction('sessions').objectStore('sessions').get(id);
    r.onsuccess = () => {
      try { resolve(validateSession(r.result?.session)); } catch (e) { reject(e); }
    };
    r.onerror = () => reject(r.error);
  });
}
export async function saveSession(session, id) {
  const clean = validateSession(session), db = await dbReady;
  id ||= `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return new Promise((resolve, reject) => {
    const tx = db.transaction(['sessions','metadata'], 'readwrite');
    tx.oncomplete = () => resolve(id);
    tx.onabort = () => reject(tx.error || new Error('Session limit reached (25). Export and remove an older capture first.'));
    tx.onerror = () => {};
    const store = tx.objectStore('metadata'), count = store.count();
    count.onsuccess = () => {
      const existing = store.get(id);
      existing.onsuccess = () => {
        if (!existing.result && count.result >= 25) { tx.abort(); return; }
        tx.objectStore('sessions').put({id, session:clean});
        store.put({id, name:clean.name, synthetic:clean.synthetic, captureStatus:clean.captureStatus, savedAt:new Date().toISOString(), count:clean.events.length});
      };
    };
  });
}
export async function deleteSession(id) {
  const db = await dbReady;
  return new Promise((resolve, reject) => {
    const tx = db.transaction(['sessions','metadata'], 'readwrite');
    tx.objectStore('sessions').delete(id); tx.objectStore('metadata').delete(id);
    tx.oncomplete = resolve; tx.onabort = () => reject(tx.error);
  });
}

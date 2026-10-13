import {validateSession} from './core.js';
import {validateArchive} from './organization.js';
const metadata=(id,clean) => ({id,name:clean.name,source:clean.source,tags:clean.tags,notesText:clean.notesText,synthetic:clean.synthetic,captureStatus:clean.captureStatus,savedAt:new Date().toISOString(),count:clean.events.length});
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
        store.put(metadata(id,clean));
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

export async function readSessions(ids) {
  const db=await dbReady;
  return new Promise((resolve,reject) => {
    const tx=db.transaction('sessions'), sessions=[];
    for (const id of ids) {
      const request=tx.objectStore('sessions').get(id);
      request.onsuccess=() => sessions.push(request.result?.session);
    }
    tx.oncomplete=() => { try { resolve(sessions.map(validateSession)); } catch (e) { reject(e); } };
    tx.onabort=() => reject(tx.error || new Error('Backup read failed.'));
  });
}
export async function restoreSessions(value) {
  const clean=validateArchive(value).sessions, db=await dbReady;
  return new Promise((resolve,reject) => {
    const tx=db.transaction(['sessions','metadata'],'readwrite');
    tx.oncomplete=() => resolve(clean.length);
    tx.onabort=() => reject(tx.error || new Error('Not enough room: this browser holds 25 sessions. Export/delete older sessions first. Nothing was imported.'));
    tx.onerror=() => {};
    const count=tx.objectStore('metadata').count();
    count.onsuccess=() => {
      if (count.result+clean.length > 25) { tx.abort(); return; }
      for (const session of clean) {
        const bytes=new Uint32Array(4); crypto.getRandomValues(bytes);
        const id=Array.from(bytes,n => n.toString(16).padStart(8,'0')).join('');
        tx.objectStore('sessions').add({id,session});
        tx.objectStore('metadata').add(metadata(id,session));
      }
    };
  });
}

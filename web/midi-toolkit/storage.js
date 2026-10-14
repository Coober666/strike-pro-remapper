import {validateSession} from './core.js';
import {validateArchive} from './organization.js';
const metadata=(id,clean,revision) => ({id,revision,name:clean.name,source:clean.source,tags:clean.tags,notesText:clean.notesText,synthetic:clean.synthetic,captureStatus:clean.captureStatus,savedAt:new Date().toISOString(),count:clean.events.length});
const newId=() => {
  const bytes=new Uint32Array(4); crypto.getRandomValues(bytes);
  return Array.from(bytes,n => n.toString(16).padStart(8,'0')).join('');
};
function conflict(record, expectedRevision) {
  if (!record) return new Error('This session was deleted in another tab. Save as a new copy or export JSON to keep your take.');
  if (expectedRevision !== (record.revision ?? 0)) return new Error('This session changed in another tab. Save as a new copy or export JSON, then reopen the saved version.');
  return null;
}
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
  return (await readSavedSession(id)).session;
}
export async function readSavedSession(id) {
  const db = await dbReady;
  return new Promise((resolve, reject) => {
    const r = db.transaction('sessions').objectStore('sessions').get(id);
    r.onsuccess = () => {
      try { resolve({session:validateSession(r.result?.session),revision:r.result.revision ?? 0}); } catch (e) { reject(e); }
    };
    r.onerror = () => reject(r.error);
  });
}
export async function saveSession(session, id, expectedRevision) {
  const clean = validateSession(session), db = await dbReady;
  const updating=!!id;
  id ||= newId();
  return new Promise((resolve, reject) => {
    let failure=null, revision=1;
    const tx = db.transaction(['sessions','metadata'], 'readwrite');
    tx.oncomplete = () => resolve({id,revision});
    tx.onabort = () => reject(failure || tx.error || new Error('Session save was interrupted. Your take remains here.'));
    tx.onerror = () => {};
    const store = tx.objectStore('metadata'), count = store.count();
    count.onsuccess = () => {
      const existing = tx.objectStore('sessions').get(id);
      existing.onsuccess = () => {
        if (updating) failure=conflict(existing.result,expectedRevision);
        else if (count.result >= 25) failure=new Error('Session limit reached (25). Export and remove an older capture first.');
        if (failure) { tx.abort(); return; }
        revision=updating ? (existing.result.revision ?? 0)+1 : 1;
        tx.objectStore('sessions')[updating ? 'put' : 'add']({id, session:clean, revision});
        store.put(metadata(id,clean,revision));
      };
    };
  });
}
export async function deleteSession(id, expectedRevision) {
  const db = await dbReady;
  return new Promise((resolve, reject) => {
    const tx = db.transaction(['sessions','metadata'], 'readwrite');
    let failure=null;
    const existing=tx.objectStore('sessions').get(id);
    existing.onsuccess=() => {
      failure=conflict(existing.result,expectedRevision);
      if (failure) { tx.abort(); return; }
      tx.objectStore('sessions').delete(id); tx.objectStore('metadata').delete(id);
    };
    tx.oncomplete = resolve; tx.onabort = () => reject(failure || tx.error || new Error('Session deletion was interrupted.'));
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
        const id=newId();
        tx.objectStore('sessions').add({id,session,revision:1});
        tx.objectStore('metadata').add(metadata(id,session,1));
      }
    };
  });
}

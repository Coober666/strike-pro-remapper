// Paired input-only host transport. Mutating requests are never automatically retried.
import {newSession, validateSession} from './core.js';
const KEY='drum-midi-host-take';
export class HostTake {
  constructor(update, status) {
    this.update=update; this.status=status; this.id=null; this.session=null;
    this.mode='stopped'; this.busy=false; this.connected=false; this.timer=null; this.generation=0;
    this.pending=Promise.resolve();
    try { this.id=sessionStorage.getItem(KEY); } catch { /* reload recovery unavailable */ }
  }
  remember(id) {
    this.id=id;
    try { if (id) sessionStorage.setItem(KEY,id); else sessionStorage.removeItem(KEY); } catch { /* current take still works */ }
  }
  async fetch(path, data) {
    const controller=new AbortController(), timer=setTimeout(() => controller.abort(),['/inputs','/setup'].some(suffix => path.endsWith(suffix)) ? 10000 : 6000);
    try {
      const response=await fetch(path,{signal:controller.signal,cache:'no-store',
        ...(data ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)} : {})});
      const result=await response.json();
      if (!response.ok) throw new Error(result.error || 'Host request failed.');
      return result;
    } finally { clearTimeout(timer); }
  }
  async inputs() { return (await this.fetch('/wifi/midi/inputs')).inputs; }
  lost(error) {
    this.connected=false; clearTimeout(this.timer);
    if (this.session && this.mode !== 'stopped') this.session.captureStatus='partial';
    this.update(this.session,'disconnected');
    this.status(`Host connection is unconfirmed. ${error.message} Received events are kept. Use Recover host take; do not start another take.`,true);
  }
  async start(input) {
    const bytes=new Uint8Array(16); crypto.getRandomValues(bytes);
    this.remember(Array.from(bytes,b => b.toString(16).padStart(2,'0')).join(''));
    this.session=null; this.mode='starting';
    await this.command('start',{input});
  }
  async command(action, extra={}, background=false) {
    if (this.busy || !this.id) return;
    clearTimeout(this.timer);
    if (!background) { this.busy=true; this.update(null,null); }
    const generation=this.generation;
    // A click during a background fetch waits for that fetch instead of being
    // dropped. Background polling must never disable a button mid-touch.
    const operation=this.pending.then(() => this.run(action,extra,generation));
    this.pending=operation.catch(() => {});
    try { await operation; }
    finally { if (!background) this.busy=false; this.update(null,null); }
  }
  async run(action, extra, generation) {
    if (generation !== this.generation || !this.id) return;
    clearTimeout(this.timer);
    try {
      const result=await this.fetch('/wifi/midi',{action,id:this.id,offset:this.session?.events.length || 0,...extra});
      if (generation !== this.generation) return;
      if (action === 'discard') {
        this.remember(null); this.connected=false; this.session=null; this.mode='stopped';
        this.status('Host copy released. Received events remain in this page.');
      } else {
        this.accept(result); this.connected=true;
        this.status(result.reason + (result.next < result.total ? ' Receiving remaining events…' : ''));
        if (result.mode !== 'stopped' || result.next < result.total) this.timer=setTimeout(() => void this.command('poll',{},true),150);
      }
    } catch (e) { if (generation === this.generation) this.lost(e); }
  }
  accept(result) {
    const events=this.session?.events || [];
    if (result.id !== this.id || result.offset !== events.length || result.next !== result.offset+result.events.length || result.next > result.total) throw new Error('Host event sequence changed.');
    const joined=[...events,...result.events];
    // A batch can end before a later pause boundary. Validate only boundaries
    // received so far; the final batch retains all of them.
    const value={...newSession(),...result.session,events:joined,
      segments:result.session.segments.filter(n => n <= joined.length),
      captureStatus:result.mode === 'stopped' && result.next === result.total ? result.session.captureStatus : 'partial'};
    this.session=validateSession(value); this.mode=result.mode;
    this.update(this.session,result.next < result.total ? 'syncing' : result.mode);
  }
  suspend() {
    if (!this.id || !['starting','recording','paused'].includes(this.mode)) return;
    clearTimeout(this.timer); this.generation++;
    // Best effort only. The lease independently stops capture if this cannot arrive.
    void fetch('/wifi/midi',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'stop',id:this.id}),keepalive:true}).catch(() => {});
    this.lost(new Error('The page was hidden or suspended.'));
  }
  forget() {
    clearTimeout(this.timer); this.generation++; this.remember(null);
    this.connected=false; this.session=null; this.mode='stopped'; this.update(null,null);
  }
}

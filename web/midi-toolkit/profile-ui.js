import {emptyProfile, validateProfile, padLabel, assignPad, readProfiles, writeProfiles, MAX_PROFILE_BYTES} from './profiles.js';
import {message} from './core.js';
const $=id => document.getElementById(id);
export class PadProfiles {
  constructor(session, changed, confirm, download) {
    this.session=session; this.changed=changed; this.confirm=confirm; this.download=download;
    this.armed=false; this.candidate=null; this.profiles=[]; this.unsaved=false; this.storageFailed=false;
    try { this.profiles=readProfiles(); }
    catch { this.storageFailed=true; this.notice('Saved profiles could not be read. Current pad names still work; export a profile to keep it.'); }
    $('profile-name').oninput=() => { this.unsaved=true; this.changed({...this.value(),name:$('profile-name').value.trim() || 'My drums'}); };
    $('profile-select').onchange=() => this.controls();
    $('learn').onclick=() => {
      this.armed=true; this.candidate=null;
      this.notice('Listening for the next received Note On. Play one pad, then check the candidate below.'); this.controls();
    };
    $('learn-cancel').onclick=() => { this.cancel(); this.notice('Learning cancelled. No mapping changed.'); };
    $('map-apply').onclick=async () => {
      const channel=Number($('map-channel').value), note=Number($('map-note').value), label=$('map-label').value.trim();
      try {
        if (!$('map-channel').value || !$('map-note').value) throw new Error('Enter both a channel and note, or learn a hit first.');
        const next=assignPad(this.value(),channel,note,label), old=padLabel(this.value(),channel,note);
        if (old && old !== label && !await this.confirm(`Channel ${channel}, note ${note} is named “${old}”. Replace that name with “${label}”?`,'Replace pad name?')) return;
        this.set(next); this.cancel(); this.notice(`Named channel ${channel}, note ${note}: ${label}. Save the profile to reuse it.`);
      } catch (e) { this.notice(e.message); }
    };
    $('profile-save').onclick=async () => {
      try {
        if (this.storageFailed) throw new Error('Saved profiles are unavailable. Export this profile instead to avoid overwriting unreadable data.');
        const value=validateProfile(this.value());
        // Re-read before writing so another tab's saved profiles are not silently dropped.
        const existing=readProfiles();
        if (existing.some(p => p.name === value.name) && !await this.confirm(`Replace the saved profile “${value.name}”? Captures already saved keep their own pad names.`,'Replace saved profile?')) return;
        const latest=readProfiles();
        const next=[...latest.filter(p => p.name !== value.name),value];
        writeProfiles(next); this.profiles=next; this.unsaved=false; this.list();
        this.notice('Profile saved in this browser. Export it for another device.');
      } catch (e) { this.notice('Profile was not saved. '+e.message); }
    };
    $('profile-load').onclick=async () => {
      const p=this.profiles.find(p => p.name === $('profile-select').value);
      if (p && await this.replaceAllowed()) { this.set(validateProfile(p),false); this.notice('Profile applied to this capture. MIDI data is unchanged.'); }
    };
    $('profile-new').onclick=async () => { if (await this.replaceAllowed()) { this.set(emptyProfile()); this.notice('Blank profile. Name it for your module, then learn or enter each pad.'); } };
    $('profile-delete').onclick=async () => {
      const name=$('profile-select').value;
      if (!name || !await this.confirm(`Delete saved profile “${name}” from this browser? Current and saved captures keep their pad names.`,'Delete profile?')) return;
      try { const next=readProfiles().filter(p => p.name !== name); writeProfiles(next); this.profiles=next; this.list(); this.notice('Saved profile deleted.'); }
      catch (e) { this.notice('Profile was not deleted. '+e.message); }
    };
    $('profile-export').onclick=() => {
      try { this.download(JSON.stringify(validateProfile(this.value()),null,2),'application/json','-pad-profile.json'); }
      catch (e) { this.notice(e.message); }
    };
    $('profile-import').onchange=async () => {
      const file=$('profile-import').files[0]; $('profile-import').value=''; if (!file) return;
      try {
        const original=this.session();
        if (file.size > MAX_PROFILE_BYTES) throw new Error('Profile file is too large (128 KB maximum).');
        const p=validateProfile(JSON.parse(await file.text()));
        if (this.session() !== original || this.busy || ['recording','paused','syncing'].includes(this.mode)) throw new Error('The capture changed while reading the profile. Import it again when capture is stopped.');
        if (await this.replaceAllowed()) { this.set(p); this.notice('Profile imported and applied. Save the profile to reuse it in this browser.'); }
      } catch (e) { this.notice(e.message); }
    };
    this.list(); this.refresh();
  }
  value() { return this.session().padMap || emptyProfile(); }
  notice(text) { $('profile-status').textContent=text; }
  async replaceAllowed() { return !this.unsaved || this.confirm('Replace the current pad names? Save or export the profile first if you want to reuse them.','Replace pad profile?'); }
  set(value, unsaved=true) { this.unsaved=unsaved; this.cancel(); this.changed(validateProfile(value)); this.refresh(); }
  cancel() { this.armed=false; this.candidate=null; this.controls(); }
  refresh() {
    this.cancel(); $('profile-name').value=this.value().name;
    $('map-rows').replaceChildren();
    for (const m of this.value().mappings) {
      const row=document.createElement('div'); row.className='pad-mapping';
      const text=document.createElement('span'); text.textContent=`${m.label} · Ch ${m.channel} / ${m.note}`;
      const remove=document.createElement('button'); remove.textContent='Remove'; remove.setAttribute('aria-label',`Remove ${m.label}, channel ${m.channel}, note ${m.note}`);
      remove.onclick=() => this.set({...this.value(),mappings:this.value().mappings.filter(p => p.channel !== m.channel || p.note !== m.note)});
      row.append(text,remove); $('map-rows').append(row);
    }
    this.controls();
  }
  list() {
    $('profile-select').replaceChildren(new Option('Choose a saved profile',''));
    for (const p of this.profiles) $('profile-select').add(new Option(p.name,p.name));
    this.controls();
  }
  consume(events) {
    if (!this.armed) return;
    const e=events.find(e => message(e.data)?.type === 'Note on');
    if (!e) return;
    this.armed=false; this.candidate=message(e.data);
    $('map-channel').value=String(this.candidate.channel); $('map-note').value=String(e.data[1]);
    this.notice(`Received channel ${this.candidate.channel}, note ${e.data[1]}, velocity ${e.data[2]}. Check the pad name, then choose Apply pad name. Wi-Fi may deliver a queued hit.`);
    this.controls();
  }
  controls(mode=this.mode, busy=this.busy) {
    this.mode=mode; this.busy=busy;
    const active=['recording','paused','syncing'].includes(mode);
    if (mode !== 'recording' && this.armed) { this.armed=false; this.notice('Learning stopped with capture. No mapping changed.'); }
    $('learn').disabled=mode !== 'recording' || busy || this.armed;
    $('learn-cancel').disabled=!this.armed && !this.candidate;
    $('map-apply').disabled=busy || this.armed;
    for (const id of ['profile-load','profile-new','profile-import','profile-select','profile-delete']) $(id).disabled=active || busy;
    for (const id of ['profile-load','profile-delete']) $(id).disabled ||= !$('profile-select').value;
    for (const id of ['profile-name','profile-save','profile-export']) $(id).disabled=busy;
    for (const b of $('map-rows').querySelectorAll('button')) b.disabled=active || busy;
    for (const id of ['map-channel','map-note','map-label']) $(id).disabled=this.armed || busy;
  }
}

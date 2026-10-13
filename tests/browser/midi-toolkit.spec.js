import {expect, test} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {demoSession} from '../../web/midi-toolkit/core.js';

async function fakeMidi(page, denied=false) {
  await page.addInitScript(denied => {
    const input=new EventTarget(); Object.assign(input,{id:'drums',name:'Generic drum module',state:'connected'});
    const access=new EventTarget(); access.inputs=new Map([['drums',input]]);
    Object.defineProperty(access,'outputs',{get:() => { throw new Error('Toolkit must not access MIDI outputs'); }});
    window.midiRequests=[];
    Object.defineProperty(navigator,'requestMIDIAccess',{configurable:true,value:async options => {
      window.midiRequests.push(options); if (denied) throw new Error('Permission denied'); return access;
    }});
    window.emitMidi=data => { const event=new Event('midimessage'); event.data=new Uint8Array(data); input.dispatchEvent(event); };
    window.disconnectMidi=() => { input.state='disconnected'; access.dispatchEvent(new Event('statechange')); };
  },denied);
}
async function importSession(page, session) {
  await page.locator('#import').setInputFiles({name:'session.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(session))});
}

test('learned pad names require confirmation, survive saves and label exports without mixing channels',async ({page}) => {
  await fakeMidi(page); await page.goto('/midi'); await page.locator('#connect').click(); await page.locator('#input').selectOption('drums');
  await page.locator('#pad-profiles summary').click(); await page.locator('#profile-name').fill('My Command');
  await page.locator('#record').click(); await expect(page.locator('#state')).toHaveText('Recording');
  await page.locator('#map-label').fill('Snare head');
  await page.locator('#learn').click();
  await page.evaluate(() => { emitMidi([0x99,40,0]); emitMidi([0xb9,4,90]); });
  await expect(page.locator('#profile-status')).toContainText('Listening');
  await page.evaluate(() => { emitMidi([0x98,40,76]); emitMidi([0x99,40,72]); });
  await expect(page.locator('#map-channel')).toHaveValue('9'); await expect(page.locator('#map-note')).toHaveValue('40');
  await expect(page.locator('#map-rows')).toBeEmpty();
  await page.locator('#map-apply').click(); await expect(page.locator('#map-rows')).toContainText('Snare head · Ch 9 / 40');
  await page.locator('#stop').click(); await page.locator('#profile-save').click();
  await page.locator('#name').fill('Named take'); await page.locator('#save').click();
  await expect(page.locator('#state')).toHaveText('Saved in this browser');
  const event=page.waitForEvent('download'); await page.locator('#json').click();
  const exported=JSON.parse(await readFile(await (await event).path(),'utf8'));
  expect(exported.padMap).toMatchObject({name:'My Command',mappings:[{channel:9,note:40,label:'Snare head'}]});
  expect(exported.events.length).toBe(4);
  await page.reload(); await page.locator('#sessions').getByRole('button',{name:'Named take',exact:true}).click();
  await expect(page.locator('#note-rows')).toContainText('9 / 40 · Snare head');
  await expect(page.locator('#note-rows tr').filter({hasText:'10 / 40'})).not.toContainText('Snare head');
  await page.locator('#pad-profiles summary').click();
  await page.locator('#map-label').fill('Changed'); await page.locator('#map-channel').fill('9'); await page.locator('#map-note').fill('40');
  await page.locator('#map-apply').click(); await expect(page.locator('#confirm')).toBeVisible();
  await page.getByRole('button',{name:'Cancel',exact:true}).click(); await expect(page.locator('#map-rows')).toContainText('Snare head');
  await page.locator('#map-apply').click(); await page.getByRole('button',{name:'Continue',exact:true}).click();
  await page.locator('#profile-save').click(); await page.getByRole('button',{name:'Continue',exact:true}).click();
  await page.reload(); await page.locator('#sessions').getByRole('button',{name:'Named take',exact:true}).click();
  await expect(page.locator('#note-rows')).toContainText('Snare head');
});

test('profile import is portable, rejects malformed replacements and fits a phone',async ({page}) => {
  await page.goto('/midi'); await page.locator('#demo').click(); await page.locator('#pad-profiles summary').click();
  const profile={format:'drum-midi-profile',version:1,name:'Nitro upstairs',mappings:[{channel:10,note:38,label:'<Snare & rim>'}]};
  const upload=p => page.locator('#profile-import').setInputFiles({name:'profile.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(p))});
  await upload(profile); await expect(page.locator('#map-rows')).toContainText('<Snare & rim>');
  await upload({...profile,mappings:[...profile.mappings,...profile.mappings]});
  await expect(page.locator('#profile-status')).toContainText('Invalid pad profile'); await expect(page.locator('#profile-name')).toHaveValue('Nitro upstairs');
  const event=page.waitForEvent('download'); await page.locator('#profile-export').click();
  expect(JSON.parse(await readFile(await (await event).path(),'utf8'))).toEqual(profile);
  await page.locator('#profile-save').click(); await page.reload(); await page.locator('#pad-profiles summary').click();
  await page.locator('#profile-select').selectOption('Nitro upstairs'); await page.locator('#profile-load').click();
  await expect(page.locator('#map-rows')).toContainText('<Snare & rim>');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('unreadable profile storage is preserved while profile export remains available',async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('drum-midi-profiles-v1','unreadable'));
  await page.goto('/midi'); await page.locator('#pad-profiles summary').click();
  await expect(page.locator('#profile-status')).toContainText('could not be read');
  await page.locator('#map-label').fill('Kick'); await page.locator('#map-apply').click();
  await page.locator('#profile-save').click(); await expect(page.locator('#profile-status')).toContainText('not saved');
  expect(await page.evaluate(() => localStorage.getItem('drum-midi-profiles-v1'))).toBe('unreadable');
  await expect(page.locator('#profile-export')).toBeEnabled();
});

test('demo saves, reloads, compares, exports and replays without touching editor APIs',async ({page}) => {
  const apiCalls=[]; page.on('request',r => { if (r.url().includes('/api/')) apiCalls.push(r.url()); });
  await page.goto('/midi'); await page.locator('#demo').click();
  await expect(page.locator('#hits')).toHaveText('96');
  await page.locator('#name').fill('Before'); await page.locator('#save').click();
  await expect(page.locator('#state')).toHaveText('Saved in this browser');
  await page.reload(); await page.locator('#sessions').getByRole('button',{name:'Before',exact:true}).click();
  await expect(page.locator('#hits')).toHaveText('96');
  const after=demoSession(); after.name='After'; after.events.forEach(e => { if (e.data[0]===0x99 && e.data[1]===38) e.data[2]-=10; });
  await importSession(page,after); await expect(page.locator('#name')).toHaveValue('After');
  await page.locator('#compare').selectOption({label:'Before'}); await expect(page.locator('#comparison')).toContainText('-10.0');
  const downloadEvent=page.waitForEvent('download'); await page.locator('#json').click(); const download=await downloadEvent;
  const exported=JSON.parse(await readFile(await download.path(),'utf8')); expect(exported.events).toEqual(after.events);
  await page.locator('#play').click(); await expect(page.locator('#play')).toHaveText('Pause replay');
  await expect.poll(async () => Number(await page.locator('#seek').inputValue())).toBeGreaterThan(0);
  await page.locator('#play').click();
  await page.locator('#seek').fill('16000'); await page.locator('#seek').dispatchEvent('input');
  await expect(page.locator('#cursor-time')).toHaveText('16.00 s');
  expect(apiCalls).toEqual([]);
});

test('generic MIDI records only selected channel messages, pauses and keeps disconnected take',async ({page}) => {
  await fakeMidi(page); await page.goto('/midi'); await page.locator('#connect').click(); await page.locator('#input').selectOption('drums');
  await page.locator('#record').click();
  await page.evaluate(() => { emitMidi([0x99,38,72]); emitMidi([0x99,38,0]); emitMidi([0x98,38,40]); emitMidi([0xb9,4,93]); emitMidi([0xf0,1,0xf7]); emitMidi([0xf8]); });
  await expect(page.locator('#hits')).toHaveText('2'); await expect(page.locator('#events')).toHaveText('4');
  await page.locator('#pause').click(); await page.evaluate(() => emitMidi([0x99,38,120]));
  await expect(page.locator('#state')).toHaveText('Paused'); await expect(page.locator('#hits')).toHaveText('2');
  await page.locator('#pause').click(); await page.evaluate(() => { emitMidi([0x99,36,90]); disconnectMidi(); });
  await expect(page.locator('#status')).toContainText('disconnected'); await expect(page.locator('#hits')).toHaveText('3');
  await expect(page.locator('#save')).toBeEnabled();
  await expect(page.locator('#note-rows')).toContainText('9 / 38'); await expect(page.locator('#note-rows')).toContainText('10 / 38');
  expect(await page.evaluate(() => midiRequests)).toEqual([{sysex:false}]);
});

test('invalid import preserves current take; names are rendered as text',async ({page}) => {
  await page.goto('/midi'); const demo=demoSession(); demo.name='<img src=x onerror=alert(1)>';
  await importSession(page,demo); await expect(page.locator('#hits')).toHaveText('96');
  const bad=demoSession(); bad.events[0].data=[0xf0,1,0xf7]; await importSession(page,bad);
  await expect(page.locator('#status')).toContainText('Invalid session'); await expect(page.locator('#name')).toHaveValue(demo.name);
  await page.locator('#save').click(); await expect(page.locator('#sessions')).toContainText(demo.name); expect(await page.locator('#sessions img').count()).toBe(0);
});

test('permission denial and unsupported browsers keep imports usable and narrow layout fits',async ({page}) => {
  await fakeMidi(page,true); await page.goto('/midi'); await page.locator('#connect').click();
  await expect(page.locator('#status')).toContainText('Permission denied');
  await page.evaluate(() => Object.defineProperty(navigator,'requestMIDIAccess',{value:undefined}));
  await page.locator('#connect').click(); await expect(page.locator('#status')).toContainText('unavailable');
  await page.locator('#demo').click(); await expect(page.locator('#hits')).toHaveText('96');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('paired Wi-Fi can analyze imports without MIDI or editor ownership',async ({page,context}) => {
  const host='http://127.0.0.1:8768';
  const response=await context.request.post(host+'/wifi/pair',{data:{token:'browser-wifi-pairing'},headers:{Origin:host}});
  expect(response.ok()).toBe(true);
  await page.addInitScript(() => Object.defineProperty(navigator,'requestMIDIAccess',{value:undefined}));
  await page.goto(host+'/midi'); await expect(page.locator('#support')).toContainText('Plug the module into the host');
  await page.locator('#demo').click(); await expect(page.locator('#hits')).toHaveText('96');
  await expect(page.locator('#connect')).toHaveText('Refresh host inputs');
  await context.request.post(host+'/wifi/logout',{headers:{Origin:host}});
});

test('storage failure keeps the capture unsaved and exportable',async ({page}) => {
  await page.addInitScript(() => Object.defineProperty(window,'indexedDB',{value:{open() {
    const request={error:new Error('Storage blocked')}; queueMicrotask(() => request.onerror()); return request;
  }}}));
  await page.goto('/midi'); await expect(page.locator('#status')).toContainText('storage is unavailable');
  await page.locator('#demo').click(); await page.locator('#save').click();
  await expect(page.locator('#status')).toContainText('Session was not saved');
  await expect(page.locator('#state')).toHaveText('Not saved'); await expect(page.locator('#json')).toBeEnabled();
  await expect(page.locator('#hits')).toHaveText('96');
});

test('capture stops at its event limit without discarding the captured take',async ({page}) => {
  await fakeMidi(page); await page.goto('/midi'); await page.locator('#connect').click(); await page.locator('#input').selectOption('drums');
  await page.locator('#record').click();
  await page.evaluate(() => { for (let i=0;i<50005;i++) emitMidi([0x99,38,80]); });
  await expect(page.locator('#events')).toHaveText('50,000');
  await expect(page.locator('#status')).toContainText('limit reached'); await expect(page.locator('#stop')).toBeDisabled();
  await expect(page.locator('#json')).toBeEnabled();
});

import {expect,test} from '@playwright/test';
import {readFile} from 'node:fs/promises';
const origin='http://127.0.0.1:8768';
async function open(page,context) {
  const response=await context.request.post(origin+'/wifi/pair',{data:{token:'browser-wifi-pairing'},headers:{Origin:origin}});
  expect(response.ok()).toBe(true);
  await page.addInitScript(() => Object.defineProperty(navigator,'requestMIDIAccess',{value:() => { throw new Error('Remote capture must not request browser MIDI'); }}));
  await page.goto(origin+'/midi');
}
async function record(page) {
  await page.locator('#connect').click();
  await page.locator('#input').selectOption({label:'Simulated host drums'});
  await page.locator('#record').click();
  await expect(page.locator('#state')).toHaveText('Recording');
  await expect.poll(async () => Number(await page.locator('#hits').textContent())).toBeGreaterThan(2);
}
async function download(page) {
  const event=page.waitForEvent('download'); await page.locator('#json').click();
  return JSON.parse(await readFile(await (await event).path(),'utf8'));
}
test.afterEach(async ({context}) => {
  await context.request.post(origin+'/wifi/logout',{headers:{Origin:origin}});
});

test('host setup reports missing dependency and visible inputs without starting capture',async ({page,context}) => {
  await open(page,context);
  const mutations=[]; page.on('request',r => { if (r.method() === 'POST') mutations.push(r.url()); });
  await page.locator('#setup-panel summary').click();
  await page.route('**/wifi/midi/setup',route => route.fulfill({json:{status:'missing',system:'Test OS',python:'3.12',package:null,inputs:[],message:'Install the optional MIDI package on the host.',detail:''}}));
  await page.locator('#setup-check').click(); await expect(page.locator('#setup-result')).toContainText('not installed');
  await page.unroute('**/wifi/midi/setup');
  await page.route('**/wifi/midi/setup',route => route.fulfill({json:{status:'ready',system:'Test OS',python:'3.12',package:'test',inputs:[{id:'test',name:'Test drums'}],message:'Select one and Record to check access.',detail:''}}));
  await page.locator('#setup-check').click(); await expect(page.locator('#setup-result')).toContainText('Test drums');
  const event=page.waitForEvent('download'); await page.locator('#setup-export').click();
  const report=JSON.parse(await readFile(await (await event).path(),'utf8')); expect(report.status).toBe('ready');
  expect(mutations).toEqual([]);
});

test('Wi-Fi MIDI Learn confirms a new received hit and keeps the map across polling and recovery',async ({page,context}) => {
  await open(page,context); await record(page); await page.locator('#pad-profiles summary').click();
  await page.locator('#profile-name').fill('Strike downstairs'); await page.locator('#map-label').fill('Snare head');
  await page.locator('#learn').click(); await expect(page.locator('#profile-status')).toContainText('Received channel 10, note 38');
  await page.locator('#map-apply').click(); await expect(page.locator('#map-rows')).toContainText('Snare head');
  await expect(page.locator('#note-rows')).toContainText('10 / 38 · Snare head');
  await page.locator('#pause').click(); await expect(page.locator('#learn')).toBeDisabled();
  await page.locator('#pause').click(); await page.locator('#stop').click();
  await page.locator('#host-recover').click();
  const session=await download(page); expect(session.padMap.name).toBe('Strike downstairs');
  expect(session.padMap.mappings).toEqual([{channel:10,note:38,label:'Snare head'}]);
});

test('host polling and recovery preserve session annotations and exercise selection',async ({page,context}) => {
  await open(page,context); await page.locator('#exercise').selectOption('rolls'); await record(page);
  await page.getByText('Session notes & tags',{exact:true}).click();
  await page.locator('#session-tags').fill('strike, before'); await page.locator('#session-notes').fill('Same sticks, snare head');
  await page.locator('#stop').click(); await page.locator('#host-recover').click();
  const session=await download(page); expect(session.tags).toEqual(['strike','before']); expect(session.notesText).toBe('Same sticks, snare head'); expect(session.exercise).toBe('rolls');
});

test('paired host captures without browser MIDI, pauses, exports, and releases independently of kit control',async ({page,context}) => {
  await open(page,context); await record(page);
  await page.locator('#pause').click(); await expect(page.locator('#state')).toHaveText('Paused');
  const paused=await page.locator('#hits').textContent();
  await page.waitForTimeout(300); expect(await page.locator('#hits').textContent()).toBe(paused);
  await page.locator('#pause').click(); await expect(page.locator('#state')).toHaveText('Recording');
  await expect.poll(async () => Number(await page.locator('#hits').textContent())).toBeGreaterThan(Number(paused));
  await page.locator('#stop').click(); await expect(page.locator('#state')).toHaveText('Not saved');
  const session=await download(page);
  expect(session.captureStatus).toBe('complete'); expect(session.segments.length).toBe(2);
  expect(session.events.length).toBe(Number(await page.locator('#events').textContent()));
  expect(new Set(session.events.map(e => e.t)).size).toBe(session.events.length);
  await page.locator('#name').fill('Wi-Fi take'); await page.locator('#save').click();
  await expect(page.locator('#state')).toHaveText('Saved in this browser');
  await page.locator('#host-release').click(); await page.getByRole('button',{name:'Continue',exact:true}).click();
  await expect(page.locator('#host-recovery')).toBeHidden();
  await expect(page.locator('#hits')).toHaveText(String(session.events.length));
});

test('a lost poll response preserves a partial copy and recovery fetches the missing events once',async ({page,context}) => {
  await open(page,context); await record(page);
  let lost=false;
  await page.route('**/wifi/midi',async route => {
    if (!lost && route.request().postDataJSON().action === 'poll') {
      lost=true; await route.fetch(); await route.abort();
    } else await route.continue();
  });
  await expect(page.locator('#status')).toContainText('unconfirmed');
  await expect(page.locator('#origin')).toContainText('Partial take');
  const partial=await download(page); expect(partial.captureStatus).toBe('partial');
  await page.unroute('**/wifi/midi'); await page.locator('#host-recover').click();
  await expect(page.locator('#state')).toHaveText('Recording');
  await page.locator('#stop').click(); await expect(page.locator('#state')).toHaveText('Not saved');
  const recovered=await download(page);
  expect(recovered.captureStatus).toBe('complete'); expect(recovered.events.length).toBeGreaterThanOrEqual(partial.events.length);
  expect(recovered.events.slice(0,partial.events.length)).toEqual(partial.events);
  expect(new Set(recovered.events.map(e => e.t)).size).toBe(recovered.events.length);
});

test('hidden page stops capture and reload can recover the retained host take',async ({page,context}) => {
  await open(page,context); await record(page);
  await page.evaluate(() => {
    Object.defineProperty(document,'hidden',{configurable:true,value:true});
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(page.locator('#status')).toContainText('hidden or suspended');
  await page.reload(); await expect(page.locator('#status')).toContainText('A host take may be available');
  await page.locator('#host-recover').click(); await expect(page.locator('#state')).toHaveText('Not saved');
  const result=await download(page); expect(result.events.length).toBeGreaterThan(2); expect(result.captureStatus).toBe('complete');
});

test('missing host dependency explains setup without breaking local analysis',async ({page,context}) => {
  await open(page,context);
  await page.route('**/wifi/midi/inputs',route => route.fulfill({status:503,json:{error:'Host MIDI needs python-rtmidi. Install requirements-midi.txt with the Python that runs the editor, then refresh inputs.'}}));
  await page.locator('#connect').click(); await expect(page.locator('#status')).toContainText('requirements-midi.txt');
  await page.locator('#demo').click(); await expect(page.locator('#hits')).toHaveText('96');
});

test('hiding while Start is still pending cannot continue background recording',async ({page,context}) => {
  await open(page,context);
  let started, release;
  const arrived=new Promise(resolve => { started=resolve; });
  const released=new Promise(resolve => { release=resolve; });
  await page.route('**/wifi/midi',async route => {
    if (route.request().postDataJSON().action === 'start') {
      const response=await route.fetch(); started(); await released; await route.fulfill({response});
    } else await route.continue();
  });
  await page.locator('#connect').click(); await page.locator('#input').selectOption({label:'Simulated host drums'}); await page.locator('#record').click();
  await arrived;
  const stopped=page.waitForResponse(r => r.url().endsWith('/wifi/midi') && r.request().postDataJSON().action === 'stop');
  await page.evaluate(() => {
    Object.defineProperty(document,'hidden',{configurable:true,value:true}); document.dispatchEvent(new Event('visibilitychange'));
  });
  expect((await stopped).ok()).toBe(true); release();
  await expect(page.locator('#host-recover')).toBeEnabled();
  await page.locator('#host-recover').click(); await expect(page.locator('#state')).toHaveText('Not saved');
  await expect(page.locator('#stop')).toBeDisabled();
});

test('Stop during a slow background poll is queued and applied once',async ({page,context}) => {
  await open(page,context); await record(page);
  let arrived, release, intercepted=false, stops=0;
  const polling=new Promise(resolve => { arrived=resolve; });
  const released=new Promise(resolve => { release=resolve; });
  await page.route('**/wifi/midi',async route => {
    const action=route.request().postDataJSON().action;
    if (action === 'stop') stops++;
    if (!intercepted && action === 'poll') {
      intercepted=true; const response=await route.fetch(); arrived();
      await released; await route.fulfill({response});
    } else await route.continue();
  });
  await polling;
  await expect(page.locator('#stop')).toBeEnabled(); await page.locator('#stop').click();
  release();
  await expect(page.locator('#state')).toHaveText('Not saved'); expect(stops).toBe(1);
});

for (const action of ['start','stop']) test(`lost ${action} response is recovered without starting another take`,async ({page,context}) => {
  await open(page,context);
  let requests=0;
  await page.route('**/wifi/midi',async route => {
    if (route.request().postDataJSON().action === action) {
      requests++; await route.fetch(); await route.abort();
    } else await route.continue();
  });
  if (action === 'stop') { await record(page); await page.locator('#stop').click(); }
  else {
    await page.locator('#connect').click(); await page.locator('#input').selectOption({label:'Simulated host drums'}); await page.locator('#record').click();
  }
  await expect(page.locator('#status')).toContainText('unconfirmed');
  await page.unroute('**/wifi/midi'); await page.locator('#host-recover').click();
  if (action === 'start') {
    await expect(page.locator('#state')).toHaveText('Recording');
    await expect.poll(async () => Number(await page.locator('#hits').textContent())).toBeGreaterThan(0);
    await page.locator('#stop').click();
  }
  await expect(page.locator('#state')).toHaveText('Not saved');
  expect((await download(page)).captureStatus).toBe('complete'); expect(requests).toBe(1);
});

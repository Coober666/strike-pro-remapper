import path from 'node:path';
import {expect, test} from '@playwright/test';

const host = 'http://127.0.0.1:8768';

async function pairEditor(page) {
  await page.goto(host + '/wifi/pair#pair=browser-wifi-pairing');
  // Pairing redirects asynchronously. Absence of the editor's boot overlay on
  // the pairing page cannot establish that the editor is ready for mutations.
  await expect(page).toHaveURL(host + '/');
  await expect(page.locator('.wifi-session')).toBeVisible();
  await expect(page.locator('#boot-screen')).toBeHidden();
}

test.afterEach(async ({page, context}) => {
  await page.unrouteAll({behavior:'ignoreErrors'});
  await context.request.post(host + '/wifi/logout', {headers:{Origin:host}});
});

test('lost save response is uncertain until reconnect reloads the host state', async ({page}) => {
  await pairEditor(page);
  await page.evaluate(async p => { await openKit(p); closeStartScreen(); }, path.resolve('.build/browser-library/kits', "John's Test Kit.skt"));
  await page.evaluate(async () => { await api('/set_param', {pad_id:'S1H', param:'la_level', value:47}); setDirtyState(true, 1); });
  await page.route('**/wifi/editor', route => route.abort());
  let saves = 0;
  await page.route('**/api/save', async route => { saves++; await route.fetch(); await route.abort(); });
  await page.evaluate(() => saveToLibrary());
  await expect(page.locator('#save-state')).toContainText('Changes not saved');
  await expect(page.locator('#save-lib-btn')).toBeDisabled();
  expect(await page.evaluate(() => kitDirty)).toBe(true);
  expect(saves).toBe(1);
  // The host did save. The browser must reconcile rather than replay the POST.
  await page.unroute('**/wifi/editor');
  await page.evaluate(() => checkWifiAccess()).catch(() => {});
  await expect(page.locator('#boot-screen')).toBeHidden();
  await expect(page.locator('#save-lib-btn')).toBeEnabled();
  expect(await page.evaluate(() => kitDirty)).toBe(false);
  expect(saves).toBe(1);
});

test('returning from a suspended page refreshes changed host state before editing', async ({page}) => {
  await pairEditor(page);
  await page.evaluate(async p => { await openKit(p); closeStartScreen(); }, path.resolve('.build/browser-library/kits', "John's Test Kit.skt"));
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', {configurable:true, get:() => true});
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(page.locator('#save-lib-btn')).toBeDisabled();
  await page.evaluate(async () => {
    await fetch('/api/set_param', {method:'POST', headers:{'Content-Type':'application/json', 'X-Strike-Editor':wifiEditorToken}, body:JSON.stringify({pad_id:'S1H', param:'la_level', value:82})});
    delete document.hidden;
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(page.locator('#save-lib-btn')).toBeEnabled();
  expect(await page.evaluate(() => pads.find(p => p.id === 'S1H').la_level)).toBe(82);
});

test('expired browser pairing returns to pairing and rejects an old link', async ({page, context}) => {
  await pairEditor(page);
  const cookies = await context.cookies();
  await context.clearCookies();
  await page.evaluate(() => checkWifiAccess()).catch(() => {});
  await expect(page.getByRole('heading', {name:'Your kit. On your iPad.'})).toBeVisible();
  await page.locator('#pair-link').fill('expired-previous-host-token');
  await page.locator('#pair-submit').click();
  await expect(page.locator('#status')).toContainText('incorrect or expired');
  await expect(page.locator('#pair-submit')).toBeEnabled();
  await context.addCookies(cookies); // let afterEach revoke the original owner
});

test('paired Wi-Fi editor loads, edits, saves and revokes its session', async ({page, context}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => Object.defineProperty(navigator, 'requestMIDIAccess', {value:undefined}));
  await page.goto(host);
  await expect(page.getByRole('heading', {name:'Your kit. On your iPad.'})).toBeVisible();
  expect((await context.request.get(host + '/api/session')).status()).toBe(401);
  await pairEditor(page);
  expect(page.url()).toBe(host + '/');
  // Open the isolated synthetic kit through the same function as the kit picker.
  await page.keyboard.press('Escape');
  const kitPath = path.resolve('.build', 'browser-library', 'kits', "John's Test Kit.skt");
  await page.evaluate(async p => { await openKit(p); closeStartScreen(); }, kitPath);
  await expect(page.locator('#kit-name')).toContainText("John's Test Kit");
  const level = page.locator('input[onchange*="la_level"]').first();
  await expect(level).toBeVisible();
  const newLevel = String((Number(await level.inputValue()) + 1) % 128);
  await level.evaluate((el, value) => { el.value = value; }, newLevel);
  await level.dispatchEvent('change');
  await expect(page.locator('#undo-btn')).toBeEnabled();
  const saved = page.waitForResponse(r => r.url() === host + '/api/save');
  await page.locator('#save-lib-btn').click();
  expect((await (await saved).json()).error).toBeUndefined();
  await expect(page.locator('#save-state')).toHaveText('Saved to library · Deploy to update the module');
  await page.evaluate(p => openKit(p), kitPath);
  await expect(page.locator('input[onchange*="la_level"]').first()).toHaveValue(newLevel);
  await page.reload();
  await expect(page.locator('#boot-screen')).toBeHidden();
  await expect(page.locator('input[onchange*="la_level"]').first()).toHaveValue(newLevel);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  // Native host activation is reachable with the same cookie, even without Web MIDI.
  const factory = await context.newPage();
  await factory.goto(host + '/factory');
  await expect(factory.locator('#pair-status')).toContainText('paired');
  await factory.locator('#connect').click();
  await factory.locator('#activate').click();
  await expect(factory.locator('#status')).toContainText('factory library is already available');
  await factory.close();
  await page.getByRole('button', {name:'Disconnect', exact:true}).click();
  await page.locator('#confirm-ok').click();
  await expect(page.getByRole('heading', {name:'Your kit. On your iPad.'})).toBeVisible();
  expect((await context.request.get(host + '/api/session')).status()).toBe(401);
  expect(errors).toEqual([]);
});

test('another device is view-only until an explicit handover reloads the current kit', async ({page, browser}, testInfo) => {
  const secondContext = await browser.newContext();
  const second = await secondContext.newPage();
  try {
    await pairEditor(page);
    await page.evaluate(async name => { await api('/new_kit', {name}); }, 'Handover Kit ' + testInfo.project.name + ' ' + testInfo.retry);
    await page.reload();
    await expect(page.locator('#kit-name')).toContainText('Handover Kit');
    await pairEditor(second);
    await expect(second.locator('#wifi-access-status')).toContainText('View only');
    await expect(second.locator('#save-lib-btn')).toBeDisabled();
    const blocked = await second.evaluate(async () => {
      const r = await fetch('/api/new_kit', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:'Must not load'})});
      return r.status;
    });
    expect(blocked).toBe(409);
    // Unsaved edits must survive moving editing to the other device.
    const changed = await page.evaluate(() => api('/set_param', {pad_id:'S1H', param:'la_level', value:73}));
    expect(changed.error).toBeUndefined();
    await second.locator('#wifi-take-control').click();
    await second.locator('#confirm-ok').click();
    await expect(second.locator('#boot-screen')).toBeHidden();
    await expect(second.locator('#wifi-access-status')).toContainText('Editing here');
    await expect(second.locator('#kit-name')).toContainText('Handover Kit');
    await expect(second.locator('#dirty-badge')).toBeVisible();
    const session = await second.evaluate(() => api('/session'));
    expect(session.pads.find(p => p.id === 'S1H').la_level).toBe(73);
    await expect(page.locator('#wifi-access-status')).toContainText('View only');
    // A stale page cannot reclaim ownership simply by refreshing.
    await page.reload();
    await expect(page.locator('#boot-screen')).toBeHidden();
    await expect(page.locator('#wifi-access-status')).toContainText('View only');
    await expect(page.locator('#save-lib-btn')).toBeDisabled();
    await second.reload();
    await expect(second.locator('#boot-screen')).toBeHidden();
    await expect(second.locator('#wifi-access-status')).toContainText('Editing here');
  } finally {
    await secondContext.request.post(host + '/wifi/logout', {headers:{Origin:host}});
    await secondContext.close();
  }
});


test('launcher demo pairs and opens synthetic events without starting capture', async ({page}) => {
  const starts=[];
  page.on('request', request => { if (request.url().endsWith('/wifi/midi') && request.postDataJSON()?.action === 'start') starts.push(request.url()); });
  await page.goto(host + '/wifi/pair#pair=browser-wifi-pairing&view=demo');
  await expect(page.locator('#hits')).toHaveText('96');
  await expect(page.locator('#capture-source')).toHaveValue('host');
  await expect(page.locator('html')).toHaveAttribute('data-host-midi', 'true');
  await expect(page.locator('#status')).toContainText('Synthetic demo loaded');
  expect(page.url()).toBe(host + '/midi');
  expect(starts).toEqual([]);
});

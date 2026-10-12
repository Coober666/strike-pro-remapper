import path from 'node:path';
import {expect, test} from '@playwright/test';

const host = 'http://127.0.0.1:8768';

test('paired Wi-Fi editor loads, edits, saves and revokes its session', async ({page, context}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => Object.defineProperty(navigator, 'requestMIDIAccess', {value:undefined}));
  await page.goto(host);
  await expect(page.getByRole('heading', {name:'Your kit. On your iPad.'})).toBeVisible();
  expect((await context.request.get(host + '/api/session')).status()).toBe(401);
  await page.goto(host + '/wifi/pair#pair=browser-wifi-pairing');
  await expect(page.locator('.wifi-session')).toBeVisible();
  await expect(page.locator('#boot-screen')).toBeHidden();
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

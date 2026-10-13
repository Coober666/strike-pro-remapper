import path from 'node:path';
import {expect, test} from '@playwright/test';

async function editor(page) {
  await page.goto('/');
  await expect(page.locator('#boot-screen')).toBeHidden();
  await page.keyboard.press('Escape');
  await page.evaluate(async kit => { await openKit(kit); closeStartScreen(); }, path.resolve('.build/browser-library/kits/John\'s Test Kit.skt'));
}

test('failed recovery keeps its banner and does not claim success', async ({page}) => {
  await editor(page);
  await page.evaluate(() => {
    document.getElementById('autosave-banner')?.remove();
    const banner = document.createElement('div');
    banner.id = 'autosave-banner';
    document.body.append(banner);
  });
  await page.route('**/api/load', route => route.abort());
  expect(await page.evaluate(() => recoverAutosave('/missing.autosave.skt', ''))).toBe(false);
  await expect(page.locator('#autosave-banner')).toBeAttached();
  await expect(page.locator('#msg')).toContainText('could not be confirmed');
  await expect(page.locator('#msg')).not.toContainText('Recovered');
});

test('confirmation keeps focus inside and Enter on Cancel cancels', async ({page}) => {
  await editor(page);
  await page.locator('#layout-edit-btn').focus();
  await page.evaluate(() => { window.confirmResult = null; appConfirm('Test action', 'Proceed').then(result => { window.confirmResult = result; }); });
  await expect(page.locator('#confirm-modal')).toHaveAttribute('aria-modal', 'true');
  await page.keyboard.press('Tab');
  await expect(page.locator('#confirm-cancel')).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(page.locator('#confirm-ok')).toBeFocused();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Enter');
  expect(await page.evaluate(() => window.confirmResult)).toBe(false);
  await expect(page.locator('#layout-edit-btn')).toBeFocused();
});

test('map supports keyboard selection, pointer dragging, cancellation and touch scroll mode', async ({page}, info) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await editor(page);
  await page.getByRole('button', {name:'Select S1H', exact:true}).focus();
  await page.keyboard.press('Enter');
  expect(await page.evaluate(() => selectedMapPad)).toBe('S1H');
  await expect(page.locator('#layout-edit-btn')).toHaveAttribute('aria-pressed', 'false');
  expect(await page.locator('#drum-svg-wrap').evaluate(el => getComputedStyle(el).touchAction)).toContain('pan-y');
  if (info.project.name === 'ipad-webkit') {
    await page.getByRole('button', {name:'Select K1H', exact:true}).tap();
    expect(await page.evaluate(() => selectedMapPad)).toBe('K1H');
    expect(await page.evaluate(() => dragState)).toBeNull();
  }
  await page.locator('#layout-edit-btn').click();
  expect(await page.locator('#drum-svg-wrap').evaluate(el => getComputedStyle(el).touchAction)).toBe('none');
  const pad = page.getByRole('button', {name:'Select K1H', exact:true});
  await pad.scrollIntoViewIfNeeded();
  let rect = await pad.boundingBox();
  const original = await page.evaluate(() => JSON.stringify(padOverrides));
  await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2);
  await page.mouse.down();
  await page.mouse.move(rect.x + rect.width / 2 + 30, rect.y + rect.height / 2 - 20, {steps:3});
  expect(await page.evaluate(() => JSON.stringify(padOverrides))).not.toBe(original);
  await page.evaluate(() => document.getElementById('drum-svg').dispatchEvent(new PointerEvent('pointercancel', {bubbles:true, pointerId:dragState.pointerId})));
  await page.mouse.up();
  expect(await page.evaluate(() => JSON.stringify(padOverrides))).toBe(original);
  rect = await pad.boundingBox();
  await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2);
  await page.mouse.down();
  await page.mouse.move(rect.x + rect.width / 2 + 25, rect.y + rect.height / 2 - 15, {steps:3});
  await page.mouse.up();
  expect(await page.evaluate(() => JSON.stringify(padOverrides))).not.toBe(original);
  await page.getByRole('button', {name:'Zoom in', exact:true}).click();
  expect(await page.evaluate(() => svgView.w)).toBeLessThan(700);
  await page.getByRole('button', {name:'Fit map', exact:true}).click();
  expect(await page.evaluate(() => svgView.w)).toBe(700);
  await page.locator('#layout-edit-btn').click();
  await expect(page.locator('#layout-edit-btn')).toHaveAttribute('aria-pressed', 'false');
  expect(errors).toEqual([]);
});

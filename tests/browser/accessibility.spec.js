import path from 'node:path';
import {expect, test} from '@playwright/test';

async function editor(page) {
  await page.goto('/');
  await expect(page.locator('#boot-screen')).toBeHidden();
  await page.evaluate(async kit => {
    await openKit(kit); closeStartScreen(); selectPadLayer('S1H','a');
  }, path.resolve('.build/browser-library/kits/John\'s Test Kit.skt'));
}

test('pad and layer controls stay named and focused after keyboard edits', async ({page}) => {
  await editor(page);
  const level = page.locator('#pad-detail').getByRole('slider',{name:'Layer A level',exact:true});
  await level.focus();
  const oldLevel=await level.elementHandle();
  const value = Number(await level.inputValue());
  const response = page.waitForResponse('**/api/set_param');
  await page.keyboard.press(value > 0 ? 'ArrowLeft' : 'ArrowRight');
  await response;
  await expect.poll(()=>oldLevel.evaluate(el=>el.isConnected)).toBe(false);
  await expect(level).toBeFocused();
  await expect(level).toHaveValue(String(value > 0 ? value-1 : value+1));
  await expect(page.getByRole('combobox',{name:'Copy to:',exact:true})).toBeAttached();
  const rack = page.locator('#layer-rack').getByRole('slider',{name:'S1H Layer A Level',exact:true});
  await rack.focus();
  const oldRack=await rack.elementHandle();
  const rackValue=Number(await rack.inputValue());
  const next = page.waitForResponse('**/api/set_param');
  await page.keyboard.press(rackValue > 0 ? 'ArrowLeft' : 'ArrowRight');
  await next;
  await expect.poll(()=>oldRack.evaluate(el=>el.isConnected)).toBe(false);
  await expect(rack).toBeFocused();
  const unnamed = await page.locator('#pad-detail').evaluate(root => [...root.querySelectorAll('input,select')]
    .filter(el=>el.getClientRects().length && !el.disabled && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby') && !el.title && !el.labels?.length)
    .map(el=>el.outerHTML));
  expect(unnamed).toEqual([]);
});

test('keyboard Space activates a button instead of the audition shortcut', async ({page}) => {
  await editor(page);
  const button=page.locator('#layout-edit-btn');
  await expect(button).toHaveAttribute('aria-pressed','false');
  await button.focus();
  await page.keyboard.press('Space');
  await expect(button).toHaveAttribute('aria-pressed','true');
  await page.keyboard.press('Space');
  await expect(button).toHaveAttribute('aria-pressed','false');
});

test('a delayed parameter response preserves the control selected afterward', async ({page}) => {
  await editor(page);
  let release, requested;
  const gate=new Promise(resolve=>{release=resolve;});
  const seen=new Promise(resolve=>{requested=resolve;});
  await page.route('**/api/set_param',async route=>{
    const result=await route.fetch(); requested(); await gate;
    await route.fulfill({response:result});
  });
  const level=page.locator('#pad-detail').getByRole('slider',{name:'Layer A level',exact:true});
  const oldLevel=await level.elementHandle();
  await level.focus();
  const value=Number(await level.inputValue());
  await page.keyboard.press(value > 0 ? 'ArrowLeft':'ArrowRight');
  await seen;
  const next=page.locator('#pad-detail').getByRole('combobox',{name:'MIDI note',exact:true});
  await next.focus(); release();
  await expect.poll(()=>oldLevel.evaluate(el=>el.isConnected)).toBe(false);
  await expect(next).toBeFocused();
});

test('Kit FX traps focus, retains edited control and closes from an input', async ({page}) => {
  await editor(page);
  await page.evaluate(()=>setWorkspaceMode('fx'));
  const opener=page.getByRole('button',{name:'Open full FX editor',exact:true});
  await opener.focus();
  await page.keyboard.press('Enter');
  const dialog=page.getByRole('dialog',{name:'Kit FX'});
  await expect(dialog).toBeVisible();
  const level=dialog.getByRole('slider',{name:'Reverb Level',exact:true});
  await level.focus();
  const oldLevel=await level.elementHandle();
  const value=Number(await level.inputValue());
  const response=page.waitForResponse('**/api/kit_fx_set');
  await page.keyboard.press(value > 0 ? 'ArrowLeft':'ArrowRight');
  await response;
  await expect.poll(()=>oldLevel.evaluate(el=>el.isConnected)).toBe(false);
  await expect(level).toBeFocused();
  await dialog.getByRole('button',{name:'Close',exact:true}).focus();
  await page.keyboard.press('Tab');
  // Native dialog may route through its document before returning to the first control.
  await page.keyboard.press('Tab');
  expect(await page.evaluate(()=>document.activeElement.closest('#kitfx-modal') !== null)).toBe(true);
  await level.focus();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(opener).toBeFocused();
});

test('download errors are announced without announcing every MIDI hit', async ({page}) => {
  await editor(page);
  await page.route('**/api/export_bundle',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Temporary read failure'})}));
  await page.evaluate(()=>exportBundle());
  const status=page.locator('#editor-announcement');
  await expect(status).toHaveAttribute('role','status');
  await expect(status).toContainText('Temporary read failure');
  const previous=await status.textContent();
  await page.evaluate(()=>setMsg('MIDI note 38 vel 100',false,false));
  await expect(status).toHaveText(previous);
  await expect(page.locator('#msg')).toHaveText('MIDI note 38 vel 100');
});

test('editor and dialogs fit a 200 percent equivalent viewport', async ({page}) => {
  await page.setViewportSize({width:640,height:450});
  await editor(page);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(640);
  await page.locator('#balance-open').click();
  const dialog=page.locator('#balance-dialog');
  const bounds=await dialog.boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x+bounds.width).toBeLessThanOrEqual(640);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});

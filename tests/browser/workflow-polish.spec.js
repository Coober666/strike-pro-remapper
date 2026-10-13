import path from 'node:path';
import {expect, test} from '@playwright/test';

test('connection details explain missing cards and distinguish host loss from missing media', async ({page}, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('#boot-screen')).toBeHidden();
  await page.keyboard.press('Escape');
  const kit = path.resolve('.build', 'browser-library', 'kits', "John's Test Kit.skt");
  await page.evaluate(async p => { await openKit(p); closeStartScreen(); }, kit);
  await expect(page.locator('#connection-user')).toHaveText('User card: not detected');
  await expect(page.locator('#save-lib-btn')).toHaveText('Save to library');
  await page.screenshot({path:'.build/editor-polish-' + testInfo.project.name + '.png'});
  await page.locator('#connection-details-btn').click();
  await expect(page.locator('#connection-dialog')).toBeVisible();
  await expect(page.locator('#connection-library-detail')).toContainText('browser-library');
  await expect(page.locator('#connection-user-detail')).toContainText('You can keep editing the library');
  await page.route('**/api/status', route => route.abort());
  await page.getByRole('button', {name:'Refresh connection', exact:true}).click();
  await expect(page.locator('#connection-host')).toHaveText('Computer connection lost');
  await expect(page.locator('#connection-user')).toHaveText('User card: unknown');
  await expect(page.locator('#connection-factory')).toHaveText('Factory card: unknown');
  await page.unroute('**/api/status');
  await page.getByRole('button', {name:'Refresh connection', exact:true}).click();
  await expect(page.locator('#connection-host')).toHaveText('Local editor connected');
  await page.getByRole('button', {name:'Done', exact:true}).click();
  await expect(page.locator('#connection-dialog')).toBeHidden();
  for (const width of [320, 390]) {
    await page.setViewportSize({width, height:844});
    expect(await page.evaluate(() => ({viewport:innerWidth, document:document.documentElement.scrollWidth}))).toEqual({viewport:width, document:width});
    for (const id of ['save-lib-btn', 'save-sd-btn', 'connection-details-btn']) {
      const bounds = await page.locator('#' + id).boundingBox();
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    }
  }
  await page.screenshot({path:'.build/editor-polish-phone-' + testInfo.project.name + '.png'});
  expect(errors).toEqual([]);
});

test('a lost deploy response does not claim that nothing was written', async ({page}) => {
  await page.goto('/');
  await expect(page.locator('#boot-screen')).toBeHidden();
  await page.keyboard.press('Escape');
  await page.route('**/api/deploy', route => route.abort());
  await page.evaluate(async () => {
    closeStartScreen();
    document.getElementById('deploy-modal').classList.add('open');
    deployPlan = {ready:true};
    await runDeploy();
  });
  await expect(page.locator('#deploy-action-note')).toContainText('Some files may have been copied');
  await expect(page.locator('#deploy-action-note')).not.toContainText('not published');
});

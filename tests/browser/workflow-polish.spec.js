import path from 'node:path';
import {copyFileSync, mkdirSync} from 'node:fs';
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

async function openSoundBrowser(page) {
  const dir = path.resolve('.build', 'browser-library', 'instruments', 'Fixtures');
  mkdirSync(dir, {recursive:true});
  copyFileSync('tests/fixtures/single_zone.sin', path.join(dir, "Jake's Snare.sin"));
  await page.goto('/');
  await expect(page.locator('#boot-screen')).toBeHidden();
  await page.keyboard.press('Escape');
  await page.evaluate(async kit => {
    await openKit(kit);
    closeStartScreen();
    await loadInstruments();
    autoPreview = false;
    selectPadLayer(pads[0].id, 'a');
    setWorkspaceMode('sounds');
  }, path.resolve('.build', 'browser-library', 'kits', "John's Test Kit.skt"));
}

test('sound assignment keeps the chosen layer and previewing does not edit the kit', async ({page}, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await openSoundBrowser(page);
  await page.locator('#inst-search').fill("Jake's");
  const before = await page.evaluate(() => pads.map(p => [p.id, p.layer_a_path, p.layer_b_path]));
  const assigned = page.waitForResponse('**/api/assign');
  await page.locator('.inst-assign').click();
  expect((await (await assigned).json()).error).toBeUndefined();
  await expect(page.locator('.inst-assign small')).toHaveText('Assigned · Layer A');
  await expect(page.getByRole('button', {name:'Layer A', exact:true})).toHaveAttribute('aria-pressed', 'true');
  const after = await page.evaluate(() => pads.map(p => [p.id, p.layer_a_path, p.layer_b_path]));
  expect(after[0]).toEqual([before[0][0], "Fixtures/Jake's Snare.sin", before[0][2]]);
  expect(after.slice(1)).toEqual(before.slice(1));
  // Deterministic audio events: exercise stale completion and rejected playback.
  await page.evaluate(() => {
    window.testAudio = [];
    window.Audio = class {
      constructor() { window.testAudio.push(this); }
      play() { return Promise.resolve(); }
      pause() {}
    };
  });
  await page.getByRole('button', {name:'Preview sound', exact:true}).click();
  await expect(page.locator('.preview-state')).toHaveText('Previewing');
  await expect(page.locator('.inst-assign small')).toHaveText('Assigned · Layer A');
  await page.evaluate(() => {
    const staleError = testAudio[0].onerror;
    previewInstrument('Fixtures/another.sin');
    staleError();
  });
  expect(await page.evaluate(() => previewRel)).toBe('Fixtures/another.sin');
  await page.evaluate(() => testAudio[1].onerror());
  await expect(page.locator('#msg')).toContainText('Check the computer connection');
  expect(await page.evaluate(() => previewRel)).toBeNull();
  await page.evaluate(() => {
    window.Audio.prototype.play = () => Promise.reject(new Error('Playback blocked'));
    previewInstrument("Fixtures/Jake's Snare.sin");
  });
  await expect(page.locator('.preview-state')).toBeEmpty();
  expect(await page.evaluate(() => pads.map(p => [p.id, p.layer_a_path, p.layer_b_path]))).toEqual(after);
  await page.getByRole('button', {name:'Layer B', exact:true}).click();
  await expect(page.locator('.inst-assign small')).toContainText('Layer B');
  for (const head of await page.locator('.rack-layer-head').all()) {
    const key = await head.locator('.rack-layer-key').boundingBox();
    const title = await head.locator('.rack-layer-title').boundingBox();
    expect(title.x).toBeGreaterThanOrEqual(key.x + key.width);
  }
  await page.screenshot({path:'.build/sound-browser-' + testInfo.project.name + '.png', fullPage:true});
  for (const width of [320, 390]) {
    await page.setViewportSize({width, height:844});
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    for (const selector of ['.inst-item .play-btn', '.inst-item .star-btn', '.inst-item .ab-btn', '.assign-layer-switch button']) {
      for (const button of await page.locator(selector).all()) {
        const bounds = await button.boundingBox();
        expect(bounds.width).toBeGreaterThanOrEqual(44);
        expect(bounds.height).toBeGreaterThanOrEqual(44);
      }
    }
  }
  await page.locator('#inst-panel').screenshot({path:'.build/sound-browser-phone-' + testInfo.project.name + '.png'});
  expect(errors).toEqual([]);
});

test('sound browser keeps its search and visible sound through target changes and recents insertion', async ({page}) => {
  await openSoundBrowser(page);
  await page.evaluate(() => {
    for (let i = 0; i < 70; i++) avail[`Fixtures/Sound ${String(i).padStart(2, '0')}.sin`] = 'synthetic';
    expandedCats.add('Fixtures');
    renderInstruments();
  });
  await page.locator('#inst-search').fill('Sound');
  const anchor = await page.evaluate(() => {
    const list = document.getElementById('inst-list');
    list.scrollTop = 1200;
    const row = [...list.querySelectorAll('.inst-item')].find(r => r.getBoundingClientRect().bottom > list.getBoundingClientRect().top);
    return {key:row.dataset.browserKey, offset:row.getBoundingClientRect().top - list.getBoundingClientRect().top};
  });
  await page.evaluate(() => selectPadLayer(pads[1].id, 'b'));
  await expect(page.locator('#inst-search')).toHaveValue('Sound');
  const offset = await page.evaluate(key => {
    const row = [...document.querySelectorAll('.inst-item')].find(r => r.dataset.browserKey === key);
    return row.getBoundingClientRect().top - document.getElementById('inst-list').getBoundingClientRect().top;
  }, anchor.key);
  expect(Math.abs(offset - anchor.offset)).toBeLessThan(2);
  await page.locator('#inst-search').fill('');
  const delta = await page.evaluate(() => {
    const list = document.getElementById('inst-list');
    list.scrollTop = 1500;
    const row = [...list.querySelectorAll('.inst-item')].find(r => r.getBoundingClientRect().bottom > list.getBoundingClientRect().top);
    const key = row.dataset.browserKey;
    const before = row.getBoundingClientRect().top;
    addToRecent('Fixtures/Sound 65.sin');
    renderInstruments();
    return [...list.querySelectorAll('.inst-item')].find(r => r.dataset.browserKey === key).getBoundingClientRect().top - before;
  });
  expect(Math.abs(delta)).toBeLessThan(2);
});

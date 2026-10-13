import {copyFile, mkdir, readFile} from 'node:fs/promises';
import path from 'node:path';
import {expect,test} from '@playwright/test';

test('balance suggestions require selection, reject stale results and undo together',async({page})=>{
  for(const folder of ['instruments','samples']) await mkdir(`.build/browser-library/${folder}/Balance`,{recursive:true});
  for(let i=0;i<4;i++) {
    await copyFile(`tests/fixtures/Balance/${i}.sin`,`.build/browser-library/instruments/Balance/${i}.sin`);
    await copyFile(`tests/fixtures/Balance/${i}.wav`,`.build/browser-library/samples/Balance/${i}.wav`);
  }
  await page.goto('/'); await expect(page.locator('#boot-screen')).toBeHidden();
  await page.evaluate(async file=>{await openKit(file);closeStartScreen();},path.resolve('tests/fixtures/balance.skt'));
  const before=await page.evaluate(()=>pads.map(p=>p.la_level));
  await page.locator('#balance-open').click();
  await expect(page.locator('#balance-apply')).toBeDisabled();
  await page.locator('#balance-analyze').click();
  await expect(page.locator('#balance-status')).toContainText('Nothing changed');
  await expect(page.locator('#balance-rows input:checked')).toHaveCount(0);
  const boxes=page.locator('#balance-rows input'); expect(await boxes.count()).toBe(2);
  await boxes.first().check(); await boxes.last().check();
  // A different editor action invalidates the measurement token.
  await page.evaluate(()=>api('/set_param',{pad_id:pads[0].id,param:'la_level',value:94}));
  await page.locator('#balance-apply').click();
  await expect(page.locator('#balance-status')).toContainText('Analyze again');
  await page.evaluate(()=>api('/undo',{}));
  await page.locator('#balance-analyze').click();
  await expect(page.locator('#balance-status')).toContainText('Nothing changed');
  const sample=await page.evaluate(()=>balanceReport.rows.find(r=>r.sample).sample);
  expect((await page.request.get('/api/balance_preview?sample='+encodeURIComponent(sample))).status()).toBe(200);
  await page.getByRole('button',{name:'Listen proposed',exact:true}).first().click();
  const audioSupported=await page.evaluate(()=>!!(window.AudioContext || window.webkitAudioContext));
  await expect(page.locator('#balance-status')).toContainText(audioSupported ? 'Listening proposed' : 'Audio preview is not supported');
  await boxes.first().check(); await boxes.last().check();
  const history=await page.evaluate(()=>undoCount);
  await page.locator('#balance-apply').click();
  await expect(page.locator('#balance-status')).toContainText('Applied 2 balance adjustments');
  expect(await page.evaluate(()=>undoCount)).toBe(history+1);
  expect(await page.evaluate(()=>pads.map(p=>p.la_level))).not.toEqual(before);
  await page.getByRole('button',{name:'Done',exact:true}).click();
  await page.evaluate(()=>undoLast());
  expect(await page.evaluate(()=>pads.map(p=>p.la_level))).toEqual(before);
  expect(await readFile('.build/browser-library/samples/Balance/2.wav')).toEqual(await readFile('tests/fixtures/Balance/2.wav'));
});

test('support report and collection preview download with phone-sized controls',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto('/'); await expect(page.locator('#boot-screen')).toBeHidden();
  await page.evaluate(()=>closeStartScreen());
  await page.locator('#connection-details-btn').click();
  await expect(page.locator('#connection-version')).toContainText('source beta');
  const download=page.waitForEvent('download');
  await page.getByRole('button',{name:'Export troubleshooting report'}).click();
  const report=JSON.parse(await readFile(await (await download).path(),'utf8'));
  expect(report.format).toBe('strike-support-report');
  expect(JSON.stringify(report)).not.toContain('browser-library');
  expect(report.client).toHaveProperty('wifi',false);
  await page.getByRole('button',{name:'Done',exact:true}).click();
  await page.evaluate(()=>openSetlists());
  await expect(page.locator('#sl-save')).toBeEnabled();
  await page.locator('#sl-kit').selectOption({label:"John's Test Kit.skt"});
  await page.getByRole('button',{name:'Add to setlist',exact:true}).click();
  await page.locator('#sl-check').click();
  await expect(page.locator('#sl-preview')).toContainText('Batch writes are disabled');
  const preview=page.waitForEvent('download'); await page.locator('#sl-export-preview').click();
  const data=JSON.parse(await readFile(await (await preview).path(),'utf8'));
  expect(data.report.preview.writes_enabled).toBe(false);
  expect(data.report.rows).toHaveLength(1);
  await page.evaluate(()=>{void slClose();});
  await page.locator('#sl-confirm-yes').click();
  await page.evaluate(()=>openBalance());
  expect(await page.locator('#balance-dialog').evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
});

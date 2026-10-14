import {copyFile, mkdir, readFile} from 'node:fs/promises';
import path from 'node:path';
import {expect,test} from '@playwright/test';

test('CSV rejects invalid batches, preserves Undo and reports successful layers',async({page})=>{
  await mkdir('.build/browser-library/instruments/CSV',{recursive:true});
  await copyFile('tests/fixtures/single_zone.sin','.build/browser-library/instruments/CSV/One.sin');
  await page.goto('/'); await expect(page.locator('#boot-screen')).toBeHidden();
  await page.evaluate(async file=>{await openKit(file);closeStartScreen();await loadInstruments();},path.resolve('tests/fixtures/balance.skt'));
  const before=await page.evaluate(()=>({pads,kitDirty,undoCount}));
  const pad=before.pads[0].id;
  const importText=text=>page.evaluate(text=>importAssignCSV(new File([text],'assign.csv')),text);
  await importText(`${pad},a,CSV/One.sin\n${pad},c,CSV/One.sin`);
  await expect(page.locator('#msg')).toContainText('layer must be A or B');
  expect(await page.evaluate(()=>({pads,kitDirty,undoCount}))).toEqual(before);
  await importText(`${pad},a,CSV/One.sin\nbroken row`);
  await expect(page.locator('#msg')).toContainText('CSV line 2');
  expect(await page.evaluate(()=>({pads,kitDirty,undoCount}))).toEqual(before);
  const assigned=page.waitForResponse('**/api/batch_assign_csv');
  await importText(`${pad},a,CSV/One.sin\n${pad},b,CSV/One.sin`);
  expect((await (await assigned).json()).message).toBe('CSV assigned 2 layers');
  expect(await page.evaluate(()=>[pads[0].layer_a_path,pads[0].layer_b_path])).toEqual(['CSV/One.sin','CSV/One.sin']);
  expect(await page.evaluate(()=>undoCount)).toBe(before.undoCount+1);
  await page.evaluate(()=>undoLast());
  expect(await page.evaluate(()=>pads)).toEqual(before.pads);
  await page.evaluate(()=>importAssignCSV({text:async()=>{throw new Error('File could not be read');}}));
  await expect(page.locator('#msg')).toContainText('File could not be read');
});

test('CSV pending file read cannot overlap another import or follow a kit switch',async({page})=>{
  await page.goto('/'); await expect(page.locator('#boot-screen')).toBeHidden();
  await page.evaluate(async file=>{await openKit(file);closeStartScreen();},path.resolve('tests/fixtures/balance.skt'));
  let writes=0;
  page.on('request',request=>{if(request.url().endsWith('/api/batch_assign_csv')) writes++;});
  await page.evaluate(()=>{
    window.pendingCSV=importAssignCSV({text:()=>new Promise(resolve=>{window.releaseCSV=resolve;})});
    window.secondRead=false;
    void importAssignCSV({text:async()=>{window.secondRead=true;return 'K1H,a,Missing.sin';}});
  });
  await page.evaluate(file=>openKit(file),path.resolve('.build/browser-library/kits',"John's Test Kit.skt"));
  const before=await page.evaluate(()=>({pads,kitDirty,undoCount}));
  await page.evaluate(async()=>{window.releaseCSV('K1H,a,Missing.sin');await window.pendingCSV;});
  await expect(page.locator('#msg')).toContainText('Kit changed while reading');
  expect(await page.evaluate(()=>window.secondRead)).toBe(false);
  expect(writes).toBe(0);
  expect(await page.evaluate(()=>({pads,kitDirty,undoCount}))).toEqual(before);
});

test('lost CSV response pauses paired editing without repeating the assignment',async({page})=>{
  await mkdir('.build/browser-library/instruments/CSV',{recursive:true});
  await copyFile('tests/fixtures/single_zone.sin','.build/browser-library/instruments/CSV/One.sin');
  await page.goto('http://127.0.0.1:8768/wifi/pair#pair=browser-wifi-pairing');
  await expect(page.locator('#boot-screen')).toBeHidden();
  await page.evaluate(async file=>{await openKit(file);closeStartScreen();await loadInstruments();},path.resolve('tests/fixtures/balance.skt'));
  let writes=0, applied=0;
  await page.route('**/wifi/editor',route=>route.request().method()==='GET' ? route.abort() : route.continue());
  await page.route('**/api/batch_assign_csv',async route=>{writes++;applied=(await (await route.fetch()).json()).changed;await route.abort();});
  await page.evaluate(()=>importAssignCSV(new File([pads[0].id+',a,CSV/One.sin'],'assign.csv')));
  await expect(page.locator('#msg')).toContainText('could not be confirmed');
  await expect(page.locator('#wifi-access-status')).toContainText('Connection needs checking');
  expect(writes).toBe(1);
  expect(applied).toBe(1);
  await page.evaluate(()=>fetch('/wifi/logout',{method:'POST'}));
});

for (const failure of [false,true]) test(`balance analysis cannot populate a reopened dialog (${failure ? 'failure' : 'success'})`,async({page})=>{
  await page.goto('/'); await expect(page.locator('#boot-screen')).toBeHidden();
  await page.evaluate(async file=>{await openKit(file);closeStartScreen();openBalance();},path.resolve('tests/fixtures/balance.skt'));
  let release, requested=false;
  const blocked=new Promise(resolve=>{release=resolve;});
  await page.route('**/api/balance',async route=>{
    const response=await route.fetch(); requested=true; await blocked;
    if(failure) await route.fulfill({json:{error:'Obsolete analysis failed'}});
    else await route.fulfill({response});
  });
  await page.evaluate(()=>{window.pendingAnalysis=balanceAnalyze();});
  await expect.poll(()=>requested).toBe(true);
  await page.getByRole('button',{name:'Done',exact:true}).click();
  await page.evaluate(()=>openBalance());
  release(); await page.evaluate(()=>window.pendingAnalysis);
  await expect(page.locator('#balance-status')).toContainText('No adjustments selected');
  await expect(page.locator('#balance-rows')).toBeEmpty();
  await expect(page.locator('#balance-apply')).toBeDisabled();
  await expect(page.locator('#balance-analyze')).toBeEnabled();
  await page.unroute('**/api/balance');
  await page.locator('#balance-analyze').click();
  await expect(page.locator('#balance-status')).toContainText('Nothing changed');
});

for (const scenario of ['newer listen','late failure','reopened dialog','new analysis']) test(`balance preview ignores obsolete requests after ${scenario}`,async({page})=>{
  for(const folder of ['instruments','samples']) await mkdir(`.build/browser-library/${folder}/Balance`,{recursive:true});
  for(let i=0;i<4;i++) {
    await copyFile(`tests/fixtures/Balance/${i}.sin`,`.build/browser-library/instruments/Balance/${i}.sin`);
    await copyFile(`tests/fixtures/Balance/${i}.wav`,`.build/browser-library/samples/Balance/${i}.wav`);
  }
  await page.goto('/'); await expect(page.locator('#boot-screen')).toBeHidden();
  await page.evaluate(async file=>{
    await openKit(file);closeStartScreen();openBalance();
    window.previewStarts=[];
    window.pendingPreviews=[];
    const original=balanceAudition;
    balanceAudition=(...args)=>{const pending=original(...args);window.pendingPreviews.push(pending);return pending;};
    _blendCtx={state:'running',destination:{},decodeAudioData:async bytes=>({marker:new Uint8Array(bytes)[0]}),
      createGain:()=>({gain:{value:1},connect(){},disconnect(){}}),
      createBufferSource:()=>({connect(){},start(){window.previewStarts.push(this.buffer.marker);},stop(){this.onended?.();}})};
    window.AudioContext ||= function(){};
  },path.resolve('tests/fixtures/balance.skt'));
  await page.locator('#balance-analyze').click(); await expect(page.locator('#balance-status')).toContainText('Nothing changed');
  let release, requests=0;
  const blocked=new Promise(resolve=>{release=resolve;});
  await page.route('**/api/balance_preview?*',async route=>{
    if(++requests===1) { await blocked; await route.fulfill({status:scenario==='late failure' ? 500 : 200,body:Buffer.from([1])}); }
    else await route.fulfill({body:Buffer.from([2])});
  });
  await page.getByRole('button',{name:'Listen current',exact:true}).first().click();
  await expect.poll(()=>requests).toBe(1);
  let expected='Listening proposed', starts=[2];
  if(scenario==='reopened dialog') {
    await page.getByRole('button',{name:'Done',exact:true}).click(); await page.evaluate(()=>openBalance());
    expected='No adjustments selected'; starts=[];
  } else if(scenario==='new analysis') {
    await page.locator('#balance-analyze').click(); expected='Nothing changed'; starts=[];
  } else await page.getByRole('button',{name:'Listen proposed',exact:true}).first().click();
  await expect(page.locator('#balance-status')).toContainText(expected);
  release();
  // Await completion of both requests, including decoding/catch in the older call.
  await page.evaluate(()=>Promise.all(window.pendingPreviews));
  await expect(page.locator('#balance-status')).toContainText(expected);
  expect(await page.evaluate(()=>previewStarts)).toEqual(starts);
});

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

test('lost balance response pauses paired editing without replaying the write',async({page})=>{
  await page.goto('http://127.0.0.1:8768/wifi/pair#pair=browser-wifi-pairing');
  await expect(page.locator('#boot-screen')).toBeHidden();
  await page.evaluate(async file=>{await openKit(file);closeStartScreen();openBalance();},path.resolve('tests/fixtures/balance.skt'));
  await page.locator('#balance-analyze').click();
  await expect(page.locator('#balance-status')).toContainText('Nothing changed');
  await page.locator('#balance-rows input').first().check();
  await page.route('**/wifi/editor',route=>route.request().method()==='GET' ? route.abort() : route.continue());
  let writes=0;
  await page.route('**/api/balance',async route=>{
    if(route.request().postDataJSON()?.action==='apply') {writes++;await route.fetch();await route.abort();}
    else await route.continue();
  });
  await page.locator('#balance-apply').click();
  await expect(page.locator('#balance-status')).toContainText('unconfirmed request is never retried');
  await expect(page.locator('#wifi-access-status')).toContainText('Connection needs checking');
  await expect(page.locator('#balance-analyze')).toBeDisabled();
  await expect(page.locator('#balance-apply')).toBeDisabled();
  expect(writes).toBe(1);
  await page.evaluate(()=>fetch('/wifi/logout',{method:'POST'}));
});

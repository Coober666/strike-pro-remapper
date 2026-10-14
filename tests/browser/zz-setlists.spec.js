import {readFile} from 'node:fs/promises';
import {expect,test} from '@playwright/test';

async function open(page) {
  await page.goto('/');
  await expect(page.locator('#boot-screen')).toBeHidden();
  await page.evaluate(()=>openSetlists());
  await expect(page.locator('#sl-save')).toBeEnabled();
}
async function add(page) {
  await page.locator('#sl-kit').selectOption({label:"John's Test Kit.skt"});
  await page.getByRole('button',{name:'Add to setlist',exact:true}).click();
}
async function save(page) {
  await page.locator('#sl-save').click();
  await expect(page.locator('#sl-status')).toContainText('Setlist saved');
}

test('setlist order, notes, checks, portable export and print do not alter the kit',async({page},info)=>{
  // Keep both order handles visible so native drag starts on its source rather
  // than scrolling the source away while locating the destination.
  if(info.project.name==='chromium') await page.setViewportSize({width:1440,height:1100});
  await open(page);
  const before=await page.evaluate(()=>api('/session'));
  await page.locator('#sl-name').fill(`Evening show ${info.project.name}`);
  await page.locator('#sl-notes').fill('Short soundcheck; bring brushes.');
  await add(page); await add(page);
  await page.locator('[data-field=song]').nth(0).fill('Opening song');
  await page.locator('[data-field=song]').nth(1).fill('Encore <script>');
  await page.getByRole('button',{name:'Move song 2 up',exact:true}).click();
  await expect(page.locator('[data-field=song]').first()).toHaveValue('Encore <script>');
  await page.locator('[data-drag="1"]').dragTo(page.locator('[data-drag="0"]'),{sourcePosition:{x:20,y:12},targetPosition:{x:20,y:12}});
  await expect(page.locator('[data-field=song]').first()).toHaveValue('Opening song');
  await page.getByRole('button',{name:'Move song 2 up',exact:true}).click();
  await page.locator('#sl-numbered').uncheck();
  await page.locator('#sl-check').click();
  await expect(page.locator('.sl-result[data-status=blocked]')).toHaveCount(2);
  await expect(page.locator('.sl-result').first()).toContainText('Output name is used more than once');
  await page.locator('#sl-numbered').check();
  await page.locator('#sl-check').click();
  await expect(page.locator('.sl-result').first()).toContainText('001 Johns Test Kit.skt');
  await save(page);
  const download=page.waitForEvent('download');
  await page.getByRole('button',{name:'Export JSON',exact:true}).click();
  const doc=JSON.parse(await readFile(await (await download).path(),'utf8'));
  expect(doc.entries[0].song).toBe('Encore <script>');
  expect(doc.entries[0].kit).toBe("John's Test Kit.skt");
  expect(doc).not.toHaveProperty('id');
  const popup=page.waitForEvent('popup');
  await page.locator('#sl-print').click();
  const sheet=await popup;
  await expect(sheet.getByRole('heading',{name:`Evening show ${info.project.name}`})).toBeVisible();
  await expect(sheet.locator('tbody tr')).toHaveCount(2);
  await expect(sheet.locator('body')).toContainText('Nothing has been deployed');
  expect(await sheet.locator('script').count()).toBe(0);
  await sheet.close();
  const after=await page.evaluate(()=>api('/session'));
  expect(after).toEqual(before);
  await page.reload();
  await expect(page.locator('#boot-screen')).toBeHidden();
  await page.evaluate(()=>openSetlists());
  await page.getByRole('button',{name:`Evening show ${info.project.name} (2)`,exact:true}).click();
  await expect(page.locator('[data-field=song]').first()).toHaveValue('Encore <script>');
});

test('invalid import keeps draft, missing kits remain visible and stale saves cannot overwrite',async({page},info)=>{
  await open(page);
  await page.locator('#sl-name').fill(`Draft ${info.project.name}`);
  await add(page); await save(page);
  await page.locator('#sl-import').setInputFiles({name:'bad.json',mimeType:'application/json',buffer:Buffer.from('{"format":"other"}')});
  await expect(page.locator('#sl-status')).toContainText('Choose a Strike setlist');
  await expect(page.locator('#sl-name')).toHaveValue(`Draft ${info.project.name}`);
  await page.evaluate(async()=>{const doc=structuredClone(sl.document);doc.name='Saved elsewhere';await api('/setlists',{action:'save',id:sl.id,revision:sl.revision,document:doc});});
  await page.locator('#sl-name').fill('My unsaved version');
  await page.locator('#sl-save').click();
  await expect(page.locator('#sl-status')).toContainText('changed in another page');
  await expect(page.locator('#sl-name')).toHaveValue('My unsaved version');
  await page.getByRole('button',{name:'Close Setlist Builder',exact:true}).click();
  await expect(page.locator('#sl-confirm')).toBeVisible();
  await page.locator('#sl-confirm-no').click();
  await expect(page.locator('#setlist-dialog')).toBeVisible();
  const doc={format:'strike-setlist',version:1,name:'Imported show',notes:'',numbered:true,entries:[{kit:'Missing.skt',song:'Lost song',notes:'',output:''}]};
  const pending=page.locator('#sl-import').setInputFiles({name:'show.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(doc))});
  await pending;
  await page.locator('#sl-confirm-yes').click();
  await expect(page.locator('#sl-name')).toHaveValue('Imported show');
  await expect(page.locator('.sl-result')).toHaveAttribute('data-status','blocked');
  expect(await page.evaluate(()=>sl.id)).toBeNull();
});

test('song kit copies, duplicate setlists and deletion preserve source files',async({page},info)=>{
  await open(page); await add(page);
  const name=`Song ${info.project.name}`;
  await page.getByRole('button',{name:'Copy kit for song',exact:true}).click();
  await page.locator('#sl-copy-name').fill(name);
  await page.getByRole('button',{name:'Create kit copy',exact:true}).click();
  await expect(page.locator('#sl-status')).toContainText('Kit copy created');
  await expect(page.locator('.sl-source')).toContainText(name+'.skt');
  const original=await readFile('.build/browser-library/kits/John\'s Test Kit.skt');
  expect(await readFile(`.build/browser-library/kits/${name}.skt`)).toEqual(original);
  await page.locator('#sl-name').fill('Copy test '+info.project.name); await save(page);
  const first=await page.evaluate(()=>sl.id);
  await page.locator('#sl-duplicate').click();
  await expect(page.locator('#sl-name')).toHaveValue('Copy test '+info.project.name+' copy');
  await save(page); expect(await page.evaluate(()=>sl.id)).not.toBe(first);
  await page.locator('#sl-delete').click(); await page.locator('#sl-confirm-yes').click();
  await expect(page.locator('#sl-status')).toContainText('Setlist deleted');
  expect(await readFile(`.build/browser-library/kits/${name}.skt`)).toEqual(original);
  await page.getByRole('button',{name:'Copy test '+info.project.name+' (1)',exact:true}).click();
  await page.getByRole('button',{name:'Edit kit',exact:true}).click();
  await expect(page.locator('#setlist-dialog')).toBeHidden();
  await expect(page.locator('#kit-name')).toContainText(name);
});

test('paired editor can plan a setlist without taking an unowned write shortcut',async({page})=>{
  const host='http://127.0.0.1:8768';
  await page.goto(host+'/wifi/pair#pair=browser-wifi-pairing');
  await expect(page.locator('#boot-screen')).toBeHidden();
  await page.evaluate(()=>openSetlists());
  await expect(page.locator('#sl-save')).toBeEnabled();
  await add(page);
  await page.locator('#sl-name').fill('Paired show'); await save(page);
  const status=await page.evaluate(async()=> (await fetch('/api/setlists',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'delete',id:sl.id,revision:sl.revision})})).status);
  expect(status).toBe(409);
  await page.evaluate(()=>fetch('/wifi/logout',{method:'POST'}));
});

test('phone layout keeps editing controls inside the viewport',async({page})=>{
  await page.setViewportSize({width:390,height:844}); await open(page); await add(page);
  await expect(page.locator('#sl-rows')).toBeVisible();
  expect(await page.locator('#setlist-dialog').evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
  await page.locator('[data-field=song]').fill('Small stage');
  await page.getByRole('button',{name:'Remove song 1',exact:true}).click();
  await expect(page.locator('#sl-rows')).toContainText('Your show starts here');
});

test('keyboard removal keeps focus near the edited song and copy cancel restores its button',async({page})=>{
  await open(page); await add(page); await add(page);
  const copy=page.getByRole('button',{name:'Copy kit for song',exact:true}).first();
  await copy.focus(); await page.keyboard.press('Enter');
  await expect(page.locator('#sl-copy-name')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(copy).toBeFocused();
  await page.getByRole('button',{name:'Remove song 1',exact:true}).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button',{name:'Remove song 1',exact:true})).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#sl-kit')).toBeFocused();
  await expect(page.locator('#sl-rows')).toContainText('Your show starts here');
});

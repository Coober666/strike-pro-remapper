import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';

const output = 'b'.repeat(24);
async function controller(page, {fail = false, missing = false, pending = false} = {}) {
  const calls = [];
  await page.route('http://controller.test:8766/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (['/', '/app.js', '/app.css'].includes(path)) {
      const name = path === '/' ? 'index.html' : path.slice(1);
      await route.fulfill({body:readFileSync('web/factory-controller/' + name),
        contentType:name.endsWith('.html') ? 'text/html' : name.endsWith('.js') ? 'text/javascript' : 'text/css'});
      return;
    }
    calls.push({path, method:request.method(), token:request.headers().authorization, body:request.postDataJSON()});
    if (request.headers().authorization !== 'Bearer test-pair') {
      await route.fulfill({status:401, json:{error:'Pair using the link shown on the USB host.'}});
    } else if (path === '/api/outputs') {
      await route.fulfill({json:{outputs:missing ? [] : [{id:output, name:'Alesis Strike'}]}});
    } else if (path === '/api/activate') {
      await route.fulfill({json:{state:'checking'}});
    } else if (path.startsWith('/api/jobs/')) {
      await route.fulfill({json: pending ? {state:'sent',message:'Activation sent. Waiting for the host…'}
        : fail ? {state:'unconfirmed', message:'Card not confirmed. No retry was sent.'}
        : {state:'ready', message:'Read-only factory library detected on the USB host.'}});
    } else await route.fulfill({status:404, json:{error:'Not found'}});
  });
  // This path must work without Web MIDI, including on insecure LAN HTTP in Safari.
  await page.addInitScript(() => Object.defineProperty(navigator, 'requestMIDIAccess', {value:undefined}));
  return calls;
}

test('paired iPad controller sends only an explicit fixed activation request', async ({page}) => {
  const calls = await controller(page);
  await page.goto('http://controller.test:8766/#pair=test-pair');
  await expect(page.locator('#pair-status')).toContainText('Pairing link ready');
  expect(page.url()).toBe('http://controller.test:8766/');
  expect(calls).toEqual([]);
  await page.locator('#connect').click();
  await expect(page.locator('#activate')).toBeEnabled();
  await page.locator('#activate').click();
  await expect(page.locator('#status')).toContainText('Read-only factory library detected');
  const sends = calls.filter(call => call.method === 'POST');
  expect(sends).toHaveLength(1);
  expect(sends[0].body.output).toBe(output);
  expect(Object.keys(sends[0].body).sort()).toEqual(['output', 'request_id']);
  expect(sends[0].body.request_id).toMatch(/^[a-f0-9]{32}$/);
  expect(calls.every(call => call.token === 'Bearer test-pair')).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator('#forget').click();
  await expect(page.locator('#connect')).toBeDisabled();
});

test('unpaired and missing-output controller cannot activate', async ({page}) => {
  const calls = await controller(page, {missing:true});
  await page.goto('http://controller.test:8766/');
  await expect(page.locator('#connect')).toBeDisabled();
  await page.goto('http://controller.test:8766/#pair=test-pair');
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toContainText('No Strike found');
  await expect(page.locator('#activate')).toBeDisabled();
  expect(calls.some(call => call.method === 'POST')).toBe(false);
});

test('failed discovery never retries the MIDI request', async ({page}) => {
  const calls = await controller(page, {fail:true});
  await page.goto('http://controller.test:8766/#pair=test-pair');
  await page.locator('#connect').click();
  await page.locator('#activate').click();
  await expect(page.locator('#status')).toContainText('No retry was sent');
  expect(calls.filter(call => call.method === 'POST')).toHaveLength(1);
});

test('reload resumes observation without retransmission', async ({page}) => {
  const calls = await controller(page, {pending:true});
  await page.goto('http://controller.test:8766/#pair=test-pair');
  await page.locator('#connect').click();
  await page.locator('#activate').click();
  await expect(page.locator('#status')).toContainText('Activation sent');
  await page.reload();
  await expect(page.locator('#status')).toContainText('Activation sent');
  await expect(page.locator('#activate')).toBeDisabled();
  expect(calls.filter(call => call.method === 'POST')).toHaveLength(1);
});

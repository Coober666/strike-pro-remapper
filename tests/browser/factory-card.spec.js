import { expect, test } from '@playwright/test';

const activation = [240, 0, 0, 14, 72, 14, 51, 3, 1, 247];
const available = { user_mounted: true, preset_mounted: true, user_path: '/user', preset_path: '/factory' };
const absent = { ...available, preset_mounted: false, preset_path: '' };

async function mockMidi(page, options = {}) {
  await page.addInitScript(options => {
    window.midiTest = { requests: [], sends: [] };
    const access = new EventTarget();
    access.sysexEnabled = options.sysex !== false;
    access.outputs = new Map((options.outputs || [
      { id: 'other', name: 'Other keyboard' }, { id: 'strike', name: 'Alesis Strike' }
    ]).map(item => {
      const output = { ...item, state: 'connected', manufacturer: 'Test', send(bytes) {
        if (options.sendError) throw new Error('Device send failed');
        window.midiTest.sends.push({ id: item.id, bytes: Array.from(bytes) });
      } };
      return [item.id, output];
    }));
    window.midiTest.access = access;
    Object.defineProperty(navigator, 'requestMIDIAccess', { configurable: true,
      value: options.unsupported ? undefined : async request => {
        window.midiTest.requests.push(request);
        if (options.denied) throw new Error('Permission denied');
        return access;
      }
    });
  }, options);
}

async function openActivation(page) {
  await page.goto('/');
  await expect(page.locator('#boot-screen')).toBeHidden();
  if (await page.locator('#start-screen').isVisible()) {
    await page.locator('#start-screen [data-factory-card]').click();
  } else {
    await page.getByRole('button', { name: /Tools/ }).first().click();
    await page.locator('#tools-menu [data-factory-card]').click();
  }
  await expect(page.getByRole('dialog', { name: 'Activate factory card', exact: true })).toBeVisible();
}

async function connect(page) {
  await page.locator('#factory-card-connect').click();
}

test.beforeEach(async ({ page }) => {
  page.on('pageerror', error => { throw error; });
});

test('explicit activation sends exactly once and confirms card discovery', async ({ page }) => {
  await mockMidi(page);
  let polls = 0;
  const writes = [];
  page.on('request', request => { if (request.method() === 'POST') writes.push(request.url()); });
  await page.route('**/api/status', async route => {
    const sent = await page.evaluate(() => midiTest.sends.length);
    await route.fulfill({ json: sent && ++polls >= 2 ? available : absent });
  });
  await openActivation(page);
  expect(await page.evaluate(() => midiTest.requests)).toEqual([]);
  await connect(page);
  expect(await page.evaluate(() => midiTest.requests)).toEqual([{ sysex: true }]);
  await expect(page.locator('#factory-card-output option')).toHaveCount(2);
  await page.locator('#factory-card-send').click();
  await page.evaluate(() => activateFactoryCard()); // concurrent duplicate must be ignored
  await expect(page.locator('#factory-card-status')).toContainText('Factory card detected');
  expect(await page.evaluate(() => midiTest.sends)).toEqual([{ id: 'strike', bytes: activation }]);
  expect(writes).toEqual([]);
  await page.keyboard.press('Escape');
  await expect(page.locator('#factory-card-dialog')).not.toBeVisible();
  await expect(page.locator('#start-screen')).toBeVisible();
});

test('an already available factory card does not receive a redundant command', async ({ page }) => {
  await mockMidi(page);
  await page.route('**/api/status', route => route.fulfill({ json: available }));
  await openActivation(page);
  await connect(page);
  await page.locator('#factory-card-send').click();
  await expect(page.locator('#factory-card-status')).toContainText('already available');
  expect(await page.evaluate(() => midiTest.sends)).toEqual([]);
});

for (const [label, options, message] of [
  ['permission denied', { denied: true }, 'Permission denied'],
  ['SysEx unavailable', { sysex: false }, 'SysEx permission is required'],
  ['no Strike', { outputs: [{ id: 'other', name: 'Keyboard' }] }, 'No connected Strike']
]) {
  test(`${label} cannot transmit`, async ({ page }) => {
    await mockMidi(page, options);
    await openActivation(page);
    await connect(page);
    await expect(page.locator('#factory-card-status')).toContainText(message);
    await expect(page.locator('#factory-card-send')).toBeDisabled();
    expect(await page.evaluate(() => midiTest.sends)).toEqual([]);
  });
}

test('multiple Strike outputs require a deliberate selection', async ({ page }) => {
  await mockMidi(page, { outputs: [{ id: 'a', name: 'Alesis Strike' }, { id: 'b', name: 'Alesis Strike Pro' }] });
  await page.route('**/api/status', route => route.fulfill({ json: absent }));
  await openActivation(page);
  await connect(page);
  await expect(page.locator('#factory-card-send')).toBeDisabled();
  await page.locator('#factory-card-output').selectOption('b');
  await page.locator('#factory-card-send').click();
  await expect.poll(() => page.evaluate(() => midiTest.sends)).toEqual([{ id: 'b', bytes: activation }]);
  await page.getByRole('dialog', { name: 'Activate factory card', exact: true }).getByRole('button', { name: 'Close', exact: true }).click();
});

test('a disconnected output is rejected before send', async ({ page }) => {
  await mockMidi(page);
  await openActivation(page);
  await connect(page);
  await page.evaluate(() => { midiTest.access.outputs.get('strike').state = 'disconnected'; });
  await page.locator('#factory-card-send').click();
  await expect(page.locator('#factory-card-status')).toContainText('Select a connected Strike');
  expect(await page.evaluate(() => midiTest.sends)).toEqual([]);
});

test('MIDI send errors do not claim card availability', async ({ page }) => {
  await mockMidi(page, { sendError: true });
  await page.route('**/api/status', route => route.fulfill({ json: absent }));
  await openActivation(page);
  await connect(page);
  await page.locator('#factory-card-send').click();
  await expect(page.locator('#factory-card-status')).toContainText('Device send failed');
  await expect(page.locator('#factory-card-send')).toBeEnabled();
});

test('failed card checks cannot send activation', async ({ page }) => {
  await mockMidi(page);
  await openActivation(page);
  await page.route('**/api/status', route => route.fulfill({ status: 503, body: 'Unavailable' }));
  await connect(page);
  await page.locator('#factory-card-send').click();
  await expect(page.locator('#factory-card-status')).toContainText('Could not check connected cards');
  expect(await page.evaluate(() => midiTest.sends)).toEqual([]);
});

test('disconnect during discovery reports failure without another transmission', async ({ page }) => {
  await mockMidi(page);
  await page.route('**/api/status', route => route.fulfill({ json: absent }));
  await openActivation(page);
  await connect(page);
  await page.locator('#factory-card-send').click();
  await expect(page.locator('#factory-card-status')).toContainText('Activation sent');
  await page.evaluate(() => {
    midiTest.access.outputs.get('strike').state = 'disconnected';
    midiTest.access.dispatchEvent(new Event('statechange'));
  });
  await expect(page.locator('#factory-card-status')).toContainText('disconnected before its factory card appeared');
  await expect(page.locator('#factory-card-send')).toBeDisabled();
  expect(await page.evaluate(() => midiTest.sends.length)).toBe(1);
});

test('missing card times out without automatically retransmitting', async ({ page }) => {
  await mockMidi(page);
  await page.route('**/api/status', route => route.fulfill({ json: absent }));
  await openActivation(page);
  await page.clock.install();
  await connect(page);
  await page.locator('#factory-card-send').click();
  await expect(page.locator('#factory-card-status')).toContainText('Activation sent');
  await page.clock.fastForward(16000);
  await expect(page.locator('#factory-card-status')).toContainText('not confirmed within 15 seconds');
  expect(await page.evaluate(() => midiTest.sends.length)).toBe(1);
});

test('closing during polling cancels observation without retrying or stale success', async ({ page }) => {
  await mockMidi(page);
  await page.route('**/api/status', route => route.fulfill({ json: absent }));
  await openActivation(page);
  await page.clock.install();
  await connect(page);
  await page.locator('#factory-card-send').click();
  await expect(page.locator('#factory-card-status')).toContainText('Activation sent');
  await page.keyboard.press('Escape');
  await expect(page.locator('#start-screen')).toBeVisible();
  await page.locator('#start-screen [data-factory-card]').click();
  await page.clock.fastForward(16000);
  await expect(page.locator('#factory-card-status')).toContainText('Connect MIDI');
  expect(await page.evaluate(() => midiTest.sends.length)).toBe(1);
});

test('unsupported browsers and read-only viewer cannot request MIDI', async ({ page }) => {
  await mockMidi(page, { unsupported: true });
  await openActivation(page);
  await expect(page.locator('#factory-card-status')).toContainText('This browser cannot send MIDI');
  await expect(page.locator('#factory-card-connect')).toBeDisabled();
  await page.evaluate(() => { closeFactoryCard(); window.VIEWER = true; showFactoryCard(); });
  await expect(page.locator('#factory-card-dialog')).not.toBeVisible();
  expect(await page.evaluate(() => midiTest.requests)).toEqual([]);
});

test('a remote browser cannot activate hardware while checking another host cards', async ({ page }) => {
  await mockMidi(page);
  await page.route('http://remote.test:8767/**', async route => {
    const response = await route.fetch({ url: route.request().url().replace('remote.test', '127.0.0.1') });
    await route.fulfill({ response });
  });
  await page.goto('http://remote.test:8767/');
  await expect(page.locator('#boot-screen')).toBeHidden();
  await page.evaluate(() => showFactoryCard());
  await expect(page.locator('#factory-card-status')).toContainText('Remote-browser activation is not supported');
  await expect(page.locator('#factory-card-connect')).toBeDisabled();
  expect(await page.evaluate(() => midiTest.requests)).toEqual([]);
});

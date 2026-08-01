import path from 'node:path';
import { expect, test } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

const unexpectedBrowserErrors = new WeakMap();

test.beforeEach(async ({ page }) => {
  const errors = [];
  unexpectedBrowserErrors.set(page, errors);
  page.on('console', message => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`);
  });
  page.on('pageerror', error => errors.push(`page: ${error.message}`));
});

test.afterEach(async ({ page }) => {
  expect(unexpectedBrowserErrors.get(page)).toEqual([]);
});

test('startup stays covered and a failed start request is recoverable', async ({ page }) => {
  let attempts = 0;
  await page.route('**/api/start', async route => {
    attempts += 1;
    if (attempts === 1) {
      await new Promise(resolve => setTimeout(resolve, 300));
      await route.fulfill({ json: { error: 'simulated start failure' } });
    } else {
      await route.continue();
    }
  });

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#boot-screen')).toBeVisible();
  await expect(page.locator('#boot-title')).toHaveText('Start screen unavailable');
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Continue to editor' })).toBeVisible();

  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByRole('dialog', { name: 'Start' })).toBeVisible();
  await expect(page.locator('#boot-screen')).toBeHidden();
  await expect(page.locator('#start-recent')).toContainText('No recently opened kits yet');
  expect(attempts).toBe(2);
});

test('startup failure can be dismissed into a usable editor', async ({ page }) => {
  await page.route('**/api/start', route => route.fulfill({
    json: { error: 'simulated persistent failure' }
  }));
  await page.goto('/');
  await expect(page.locator('#boot-title')).toHaveText('Start screen unavailable');
  await page.getByRole('button', { name: 'Continue to editor' }).click();
  await expect(page.locator('#boot-screen')).toBeHidden();
  await expect(page.getByRole('dialog', { name: 'Start' })).toBeHidden();
  await expect(page.locator('.brand-lockup')).toBeVisible();
  expect(await page.evaluate(() => document.querySelectorAll('body > [inert]').length)).toBe(0);
});

test('start screen isolates the editor, confirms sync, restores focus, and loads recents', async ({ page, request }) => {
  const kitPath = path.resolve('.build', 'browser-library', 'kits', "John's Test Kit.skt");
  const loaded = await request.post('/api/load', { data: { path: kitPath } });
  expect(loaded.ok()).toBeTruthy();
  expect((await loaded.json()).error).toBeUndefined();

  await page.goto('/');
  await expect(page.locator('#boot-screen')).toBeHidden();
  await expect(page.locator('#kit-name')).toContainText("John's Test Kit.skt");

  const brand = page.locator('.brand-lockup');
  await brand.click();
  const start = page.getByRole('dialog', { name: 'Start' });
  await expect(start).toBeVisible();
  expect(await page.evaluate(() => ({
    header: document.querySelector('header').hasAttribute('inert'),
    workspace: document.querySelector('.main').hasAttribute('inert'),
    save: document.getElementById('save-lib-btn').closest('[inert]') !== null,
    undo: document.getElementById('undo-btn').closest('[inert]') !== null,
    clear: document.getElementById('clear-pads-btn').closest('[inert]') !== null,
    deploy: document.getElementById('save-sd-btn').closest('[inert]') !== null
  }))).toEqual({ header: true, workspace: true, save: true, undo: true, clear: true, deploy: true });

  const backgroundRequests = [];
  page.on('request', req => backgroundRequests.push(new URL(req.url()).pathname));
  await page.keyboard.press('Control+s');
  await page.keyboard.press('Control+z');
  await page.waitForTimeout(50);
  expect(backgroundRequests).not.toContain('/api/save');
  expect(backgroundRequests).not.toContain('/api/undo');

  for (let i = 0; i < 8; i += 1) {
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => document.activeElement.closest('#start-screen') !== null)).toBeTruthy();
  }

  await page.keyboard.press('s');
  await expect(page.locator('#start-sync-confirm')).toBeVisible();
  await expect(page.locator('#start-sync-go')).toBeDisabled();
  expect(backgroundRequests).not.toContain('/api/sync_start');
  await page.keyboard.press('Escape');
  await expect(page.locator('#start-sync-confirm')).toBeHidden();
  await expect(start).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(start).toBeHidden();
  await expect(brand).toBeFocused();
  expect(await page.evaluate(() => document.querySelectorAll('body > [inert]').length)).toBe(0);

  await brand.click();
  const recent = page.locator('#start-recent .start-kit');
  await expect(recent).toHaveCount(1);
  await expect(recent).toContainText("John's Test Kit");
  expect(await recent.getAttribute('data-path')).toContain("John's Test Kit.skt");
  await recent.click();
  await expect(start).toBeHidden();
  await expect(page.locator('#kit-name')).toContainText("John's Test Kit.skt");
});

test('O, I, and N shortcuts delegate to their existing kit-menu flows', async ({ page }) => {
  await page.goto('/');
  const brand = page.locator('.brand-lockup');
  const start = page.getByRole('dialog', { name: 'Start' });

  await brand.click();
  await expect(start).toBeVisible();
  await page.keyboard.press('o');
  await expect(start).toBeHidden();
  await expect(page.locator('#kit-menu')).toBeVisible();

  await brand.click();
  await expect(start).toBeVisible();
  await page.keyboard.press('i');
  await expect(start).toBeHidden();
  await expect(page.locator('#kit-menu')).toBeVisible();
  await expect(page.locator('#msg')).toContainText('Pick an import from the Kits menu');

  await brand.click();
  await expect(start).toBeVisible();
  await page.keyboard.press('n');
  await expect(start).toBeHidden();
  await expect(page.locator('#new-kit-form')).toBeVisible();
});

test('the start screen has no horizontal overflow at the 620px breakpoint', async ({ page }) => {
  await page.setViewportSize({ width: 620, height: 800 });
  await page.goto('/');
  const start = page.getByRole('dialog', { name: 'Start' });
  if (!(await start.isVisible())) await page.locator('.brand-lockup').click();
  await expect(page.getByRole('dialog', { name: 'Start' })).toBeVisible();
  expect(await page.evaluate(() => {
    const start = document.getElementById('start-screen');
    return start.scrollWidth <= start.clientWidth && document.documentElement.scrollWidth <= innerWidth;
  })).toBeTruthy();
});

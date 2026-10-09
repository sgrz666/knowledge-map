// Actual Chromium smoke test; use bundled Playwright and installed Chrome/Edge.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const runtime = path.join(process.env.USERPROFILE || '', '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {chromium} = require(process.env.CET_PLAYWRIGHT_MODULE || runtime);
const candidates = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'];
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: candidates.find(p => fs.existsSync(p))});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(pathToFileURL(path.join(__dirname, 'index.html')).href);
    assert.equal(await page.locator('article').count(), 118);
    await page.locator('#exam').selectOption('CET-4');
    await page.locator('#kind').selectOption('listening');
    assert.equal(await page.locator('article').count(), 25);
    await page.locator('#search').fill('Christmas-time');
    assert.equal(await page.locator('article').count(), 2);
    await page.getByText('官方参考答案', {exact: true}).first().click();
    assert.equal(await page.locator('article').first().locator('details[open]').count(), 1);
    await page.locator('#search').fill('');
    await page.locator('#exam').selectOption('CET-6');
    await page.locator('#kind').selectOption('oral');
    assert.equal(await page.locator('article').count(), 1);
    await page.locator('#exam').selectOption('');
    await page.locator('#kind').selectOption('archive');
    assert.equal(await page.locator('article').count(), 14);
    await page.locator('#kind').selectOption('translation');
    assert.equal(await page.locator('article').count(), 4);
    assert.deepEqual(errors, []);
    console.log('PASS: 118 records; 25 CET4 listening; full-context search; answer disclosure; CET6 oral; 14 archives; four translation/task-scoring records; no browser errors.');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exit(1);});

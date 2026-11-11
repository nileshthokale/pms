const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const https = require('node:https');
const {spawn} = require('node:child_process');
const root = path.resolve(__dirname, '../..');
const {chromium} = require(path.join(root, 'temp/super_admin_validation/tooling/node_modules/playwright'));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const url = 'https://127.0.0.1:55441';

async function serviceReady() {
  return new Promise(resolve => {
    // Browser-only fixture certificate is self-signed; verified TLS has a separate smoke test.
    https.get(url + '/health', {rejectUnauthorized: false}, response => {response.resume(); resolve(response.statusCode === 200);}).on('error', () => resolve(false));
  });
}
(async () => {
  const testEnv = {...process.env};
  if (!process.env.LICENSE_TEST_POSTGRES_URL) {
    delete testEnv.LICENSE_TEST_POSTGRES_URL;
  }
  const service = spawn(path.join(root, '.venv/Scripts/python.exe'), ['super_admin/tests/browser_service.py'], {cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe'],env:testEnv});
  let output = ''; service.stderr.on('data', data => output += data.toString());
  let browser;
  try {
    for (let i=0; i<100 && !await serviceReady(); i++) await wait(100);
    assert.ok(await serviceReady(), output);
    browser = await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
    const context = await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1440,height:1000}});
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(url + '/admin/sign-in');
    await page.locator('#username').fill('developer'); await page.locator('#password').fill('test-password-123');
    await Promise.all([page.waitForURL(url + '/admin'), page.getByRole('button',{name:'Sign in',exact:true}).click()]);
    await page.locator('#devices tr').waitFor();
    assert.equal(await page.locator('#licenses tr').count(),1);
    assert.equal(await page.locator('#summary .card').count(),7);
    await page.locator('#devices button').filter({hasText:'History'}).click();
    await page.locator('#history-dialog[open]').waitFor();
    assert.ok((await page.locator('#history').textContent()).includes('Device activated'));
    await page.locator('#history-close').click();
    await page.locator('#devices button').filter({hasText:'Revoke'}).click();
    await page.locator('#confirmation[open]').waitFor();
    await page.locator('#reason').fill('Browser controlled revocation test');
    await page.locator('#confirm').check(); await page.locator('#apply').click();
    await page.locator('#result').filter({hasText:'Device revoked'}).waitFor();
    await page.locator('#devices .badge.REVOKED').waitFor();
    await page.locator('#devices button').filter({hasText:'Reactivate'}).click();
    await page.locator('#reason').fill('Browser controlled reactivation test');await page.locator('#confirm').check();await page.locator('#apply').click();
    await page.locator('#result').filter({hasText:'Device reactivated'}).waitFor();
    await page.locator('#devices .badge.AUTHORIZED').waitFor();
    await page.locator('#licenses button').filter({hasText:'Revoke'}).click();
    await page.locator('#reason').fill('Browser controlled license revocation');await page.locator('#confirm').check();await page.locator('#apply').click();
    await page.locator('#licenses .badge.REVOKED').waitFor();
    await page.locator('#licenses button').filter({hasText:'Reactivate'}).click();
    await page.locator('#reason').fill('Browser controlled license reactivation');await page.locator('#confirm').check();await page.locator('#apply').click();
    await page.locator('#licenses .badge.ACTIVE').waitFor();
    await page.locator('#activity').selectOption('offline');await page.waitForFunction(() => document.querySelector('#page').textContent === 'No records');
    await page.locator('#activity').selectOption('all');await page.locator('#devices tr').waitFor();
    await page.screenshot({path:path.join(root,'temp/super_admin_validation/dashboard.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    await page.locator('#logout').click();await page.waitForURL(url + '/admin/sign-in');
    fs.writeFileSync(path.join(root,'temp/super_admin_validation/browser_results.json'),JSON.stringify({login:true,summary:true,device_history:true,device_revoke_reactivate:true,license_revoke_reactivate:true,offline_filter:true,logout:true,page_errors:errors},null,2));
    console.log('Browser acceptance passed: login, summaries, history, device/license actions, offline filter, logout.');
  } finally {
    if (browser) await browser.close();
    service.kill();
    await wait(300);
  }
})().catch(error => {console.error(error);process.exitCode=1;});

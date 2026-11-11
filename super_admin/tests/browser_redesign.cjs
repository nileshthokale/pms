// Real HTTP API + disposable PostgreSQL records; no dashboard data is mocked.
const fs=require('node:fs'),path=require('node:path'),https=require('node:https'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'temp/super_admin_redesign');
const {chromium}=require(path.join(root,'temp/super_admin_validation/tooling/node_modules/playwright'));
const url='https://127.0.0.1:55441',wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function ready(){return new Promise(resolve=>https.get(url+'/health',{rejectUnauthorized:false},r=>{r.resume();resolve(r.statusCode===200);}).on('error',()=>resolve(false)));}
async function login(page){await page.goto(url+'/admin/sign-in');await page.locator('#username').fill('developer');await page.locator('#password').fill('test-password-123');await Promise.all([page.waitForURL(url+'/admin'),page.getByRole('button',{name:'Sign in',exact:true}).click()]);await page.waitForFunction(()=>document.querySelector('#summary').getAttribute('aria-busy')==='false');}
async function noOverflow(page){assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Page has horizontal overflow');}
(async()=>{
  const testEnv = {...process.env, SUPER_ADMIN_BROWSER_FLEET: '1'};
  if (!process.env.LICENSE_TEST_POSTGRES_URL) {
    delete testEnv.LICENSE_TEST_POSTGRES_URL;
  }
  const service=spawn(path.join(root,'.venv/Scripts/python.exe'),['super_admin/tests/browser_service.py'],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe'],env:testEnv});
  let output='',browser;service.stderr.on('data',data=>output+=data.toString());
  const errors=[],results={};
  try{
    for(let i=0;i<100&&!await ready();i++)await wait(100);assert.ok(await ready(),output);
    browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
    const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1440,height:1000}}),page=await context.newPage();
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url+'/admin/sign-in');await page.screenshot({path:path.join(out,'login.png')});
    await login(page);
    assert.equal(await page.locator('#summary .card').count(),7);
    assert.equal(await page.locator('#summary .stat-value').first().textContent(),'26');
    await page.locator('#network-stage').scrollIntoViewIfNeeded();
    await page.waitForFunction(()=>document.querySelector('#network-stage canvas') && document.querySelectorAll('.network-label[data-device-id]').length===24);
    assert.equal(await page.locator('#network-count').textContent(),'24 of 26 devices');results.webgl=true;
    await page.locator('#motion-toggle').click();assert.equal(await page.locator('#motion-toggle').getAttribute('aria-pressed'),'true');
    // Hit a projected computer center in the actual WebGL scene, not the fallback list.
    await page.screenshot({path:path.join(out,'network.png')});
    let hit;
    for(const label of (await page.locator('.network-label[data-device-id]').all()).slice(0,5)){
      const box=await label.boundingBox();if(!box)continue;
      for(let dy=-60;dy<=15&&!hit;dy+=8)for(let dx=-30;dx<=30&&!hit;dx+=10){
        const x=box.x+box.width/2+dx,y=box.y+dy;
        await page.mouse.move(x,y);await wait(30);if(await page.locator('#network-tooltip').isVisible())hit={x,y};
      }
      if(hit)break;
    }
    assert.ok(hit,'No selectable 3D computer found near its label');
    await page.mouse.click(hit.x,hit.y);
    await page.locator('#detail-dialog[open]').waitFor();await page.locator('#detail-body .detail-grid').waitFor();
    assert.ok((await page.locator('#detail-body').textContent()).includes('Last seen'));
    await page.keyboard.press('Escape');results.scene_hover_click=true;
    await page.locator('#network-roster button').first().focus();await page.keyboard.press('Enter');await page.locator('#detail-dialog[open]').waitFor();await page.keyboard.press('Escape');results.keyboard_details=true;
    await page.locator('#next').click();await page.waitForFunction(()=>document.querySelector('#page').textContent==='21–26 of 26');assert.equal(await page.locator('#devices tr').count(),6);
    await page.locator('#previous').click();await page.waitForFunction(()=>document.querySelector('#page').textContent==='1–20 of 26');
    await page.locator('#licenses-next').click();await page.waitForFunction(()=>document.querySelector('#licenses-page').textContent==='21–26 of 26');await page.locator('#licenses-previous').click();await page.waitForFunction(()=>document.querySelector('#licenses-page').textContent==='1–20 of 26');results.pagination=true;
    await page.locator('#device-search').fill('TEST INSTALLATION 24');await page.waitForFunction(()=>document.querySelector('#page').textContent==='1–1 of 1');assert.ok((await page.locator('#devices').textContent()).includes('2.0.24'));
    await page.locator('#device-search').fill('not-a-real-device');await page.waitForFunction(()=>document.querySelector('#page').textContent==='No records');
    await page.locator('#device-search').fill('');await page.waitForFunction(()=>document.querySelector('#page').textContent==='1–20 of 26');
    await page.locator('#device-status').selectOption('REVOKED');await page.waitForFunction(()=>document.querySelector('#devices .badge.REVOKED') && !document.querySelector('#devices .badge.AUTHORIZED'));
    await page.locator('#device-status').selectOption('all');await page.waitForFunction(()=>document.querySelector('#page').textContent==='1–20 of 26');results.device_search_filters=true;
    await page.locator('#license-search').fill('test installation 24');await page.waitForFunction(()=>document.querySelector('#licenses-page').textContent==='1–1 of 1');
    await page.locator('#licenses .text-button').click();await page.locator('#detail-dialog[open]').waitFor();await page.locator('.associated-devices button').waitFor();assert.ok((await page.locator('#detail-body').textContent()).includes('2.0.24'));await page.keyboard.press('Escape');
    await page.locator('#license-search').fill('');await page.waitForFunction(()=>document.querySelector('#licenses-page').textContent==='1–20 of 26');
    await page.locator('#license-status').selectOption('REVOKED');await page.waitForFunction(()=>document.querySelector('#licenses .badge.REVOKED') && !document.querySelector('#licenses .badge.ACTIVE'));
    await page.locator('#license-status').selectOption('all');await page.waitForFunction(()=>document.querySelector('#licenses-page').textContent==='1–20 of 26');results.license_search_filters_details=true;
    const before=await page.locator('#alert-count').textContent();await page.locator('#alerts').getByRole('button',{name:'Acknowledge'}).first().click();await page.waitForFunction(value=>Number(document.querySelector('#alert-count').textContent)===Number(value)-1,before);results.acknowledgement=true;
    assert.ok((await page.locator('#update-section').textContent()).includes('Not configured'));assert.ok(await page.locator('#update-section button').isDisabled());results.updates_unconfigured=true;
    for(const href of ['#device-section','#license-section','#update-section','#audit-section']){await page.locator(`.nav-link[href="${href}"]`).click();assert.ok(await page.locator(`.nav-link[href="${href}"]`).evaluate(a=>a.classList.contains('active')));}results.navigation=true;
    await noOverflow(page);await page.locator('#refresh').click();await page.waitForFunction(()=>!document.querySelector('#refresh').disabled);
    await page.locator('#overview').scrollIntoViewIfNeeded();await page.locator('#refresh').focus();await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
    await page.setViewportSize({width:768,height:1024});await noOverflow(page);await page.screenshot({path:path.join(out,'tablet.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});await noOverflow(page);await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});results.responsive=true;
    await page.emulateMedia({reducedMotion:'reduce'});await page.waitForFunction(()=>document.querySelector('#motion-toggle').disabled);
    assert.equal(await page.locator('.heading-shield .icon').evaluate(e=>getComputedStyle(e).animationName),'none');results.reduced_motion=true;
    // Failure is explicit and preserves the last successful data and authorization states.
    await page.route('**/admin/summary',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Temporary test API outage'})}));
    await page.locator('#refresh').click();await page.locator('#error').filter({hasText:'Temporary test API outage'}).waitFor();assert.equal(await page.locator('#connection-label').textContent(),'Sync unavailable');assert.equal(await page.locator('#summary .stat-value').first().textContent(),'26');await page.unroute('**/admin/summary');
    await page.locator('#refresh').click();await page.waitForFunction(()=>document.querySelector('#connection-label').textContent==='API reachable');results.outage_recovery=true;
    // A real browser with WebGL disabled exercises the graceful map fallback.
    const fallback=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1440,height:1000}});
    await fallback.addInitScript(()=>{const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type,...args){if(String(type).includes('webgl'))return null;return original.call(this,type,...args);};});
    const fallbackPage=await fallback.newPage();fallbackPage.on('pageerror',e=>errors.push(e.message));await login(fallbackPage);await fallbackPage.locator('#network-stage').scrollIntoViewIfNeeded();await fallbackPage.locator('.fallback-map').waitFor();assert.equal(await fallbackPage.locator('.fallback-device').count(),24);await fallbackPage.locator('.fallback-device').first().click();await fallbackPage.locator('#detail-body .detail-grid').waitFor();await fallbackPage.keyboard.press('Escape');await fallbackPage.screenshot({path:path.join(out,'fallback.png')});results.webgl_fallback=true;
    await fallback.close();await page.locator('#logout').click();await page.waitForURL(url+'/admin/sign-in');results.logout=true;
    assert.deepEqual(errors,[]);results.page_errors=errors;fs.writeFileSync(path.join(out,'browser_results.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));
  }finally{if(browser)await browser.close();service.kill();await wait(300);}
})().catch(e=>{console.error(e);process.exitCode=1;});

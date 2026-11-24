/* Real-browser CRUD tests using an isolated SQLite fixture, never a user database. */
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const readline=require('node:readline');
const playwright=require(process.env.VULNDESK_PLAYWRIGHT_MODULE||'playwright');
let server,browser,page,url;
const errors=[];
const sourceId='ui-cve-mirror';

async function loaded(){await page.waitForSelector('.sources-table');await page.waitForFunction(()=>!document.querySelector('#view .skeleton'));}
async function gotoSources(){await page.goto(url+'/#sources');await loaded();}
async function clickRow(id,action){await page.locator(`.sources-table .source-row-actions [data-source="${id}"][data-source-action="${action}"]`).click();}
async function closeAction(){await page.locator('#action-dialog [data-close="action-dialog"]').first().click();}
async function newForm(id,name='Mirror UI',endpoint='https://mirror.example.org/cves/2.0',kind='nvd-cve'){
  await page.locator('[data-action="source-add"]').click();
  await page.locator('#source-display_name').fill(name);await page.locator('#source-source_id').fill(id);
  await page.locator('#source-adapter_type').selectOption(kind);await page.locator('#source-endpoint_ref').fill(endpoint);
}
async function saveForm(){await page.locator('#source-form [type="submit"]').click();await page.waitForFunction(()=>!document.querySelector('#action-dialog').open);await loaded();}

before(async()=>{
  server=spawn(process.env.VULNDESK_TEST_PYTHON||'python',[path.join(__dirname,'ui_fixture_server.py')],{stdio:['ignore','pipe','pipe'],env:process.env});
  url=await new Promise((resolve,reject)=>{
    const lines=readline.createInterface({input:server.stdout});
    const timeout=setTimeout(()=>reject(new Error('UI fixture startup timed out')),15000);
    lines.once('line',line=>{clearTimeout(timeout);resolve(JSON.parse(line).url);});
    server.once('exit',code=>reject(new Error('UI fixture exited: '+code)));
    server.stderr.on('data',data=>process.stderr.write(data));
  });
  const options={headless:true};
  if(process.env.VULNDESK_CHROMIUM_PATH) options.executablePath=process.env.VULNDESK_CHROMIUM_PATH;
  if(process.env.VULNDESK_CHROMIUM_ARGS) options.args=JSON.parse(process.env.VULNDESK_CHROMIUM_ARGS);
  browser=await playwright.chromium.launch(options);
  page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',error=>errors.push(error.message));
  await gotoSources();
});

after(async()=>{
  if(browser)await browser.close();
  if(server)server.kill('SIGTERM');
});

test('API page lists endpoints, health, credentials references and a missing builtin template',async()=>{
  assert.equal(await page.locator('.sources-table tbody tr').count(),4);
  assert.match(await page.locator('#view').textContent(),/services\.nvd\.nist\.gov/);
  assert.match(await page.locator('#view').textContent(),/Belum ada akuisisi berhasil/);
  assert.equal(await page.locator('[data-source-action="preset"][data-source="mitre-cwe"]').count(),1);
  assert.ok(!(await page.content()).includes('SECRET_VALUE_NEVER_RETURNED'));
});

test('view exposes configuration and health without secret values',async()=>{
  await clickRow('nvd-cve','view');
  await page.waitForSelector('#detail-dialog[open]');
  assert.match(await page.locator('#detail-content').textContent(),/env:NVD_API_KEY/);
  assert.match(await page.locator('#detail-content').textContent(),/Parameter adapter/);
  assert.ok(!(await page.locator('#detail-content').textContent()).includes('SECRET_VALUE_NEVER_RETURNED'));
  await page.locator('#detail-dialog [data-close]').click();
});

test('add persists a compatible API and handles adapter-specific fields',async()=>{
  await newForm(sourceId);
  await page.locator('#source-max_pages').fill('2');await page.locator('#source-page_size').fill('120');
  await saveForm();
  const response=await page.request.get(url+'/api/sources/'+sourceId);const record=await response.json();
  assert.equal(record.endpoint_url,'https://mirror.example.org/cves/2.0');assert.equal(record.max_pages,2);
  assert.equal(await page.locator(`.sources-table [data-source="${sourceId}"][data-source-action="edit"]`).count(),1);
});

test('edit persists endpoint, name and active state while keeping source identity',async()=>{
  await clickRow(sourceId,'edit');await page.waitForSelector('#source-form');
  assert.equal(await page.locator('#source-source_id').getAttribute('readonly'),'');
  await page.locator('#source-display_name').fill('Mirror UI diperbarui');await page.locator('#source-endpoint_ref').fill('https://new.example.org/nvd');
  await page.locator('#source-form [name="enabled"]').uncheck();await saveForm();
  const record=await (await page.request.get(url+'/api/sources/'+sourceId)).json();
  assert.equal(record.source_id,sourceId);assert.equal(record.display_name,'Mirror UI diperbarui');assert.equal(record.enabled,false);
  assert.equal(record.endpoint_url,'https://new.example.org/nvd');
});

test('invalid endpoint leaves the form open and does not change stored data',async()=>{
  await clickRow(sourceId,'edit');await page.waitForSelector('#source-form');
  await page.locator('#source-endpoint_ref').fill('http://invalid.example.org/feed');
  await page.locator('#source-form [type="submit"]').click();await page.waitForSelector('#source-form-error:not([hidden])');
  assert.match(await page.locator('#source-form-error').textContent(),/HTTPS/);
  const record=await (await page.request.get(url+'/api/sources/'+sourceId)).json();assert.equal(record.endpoint_url,'https://new.example.org/nvd');
  await closeAction();
});

test('duplicate ID shows the backend error and preserves the original API',async()=>{
  await newForm(sourceId,'Duplicate');await page.locator('#source-form [type="submit"]').click();
  await page.waitForSelector('#source-form-error:not([hidden])');assert.match(await page.locator('#source-form-error').textContent(),/sudah digunakan/);
  const record=await (await page.request.get(url+'/api/sources/'+sourceId)).json();assert.equal(record.display_name,'Mirror UI diperbarui');await closeAction();
});

test('concurrent backend update is reported as a conflict rather than overwritten',async()=>{
  await clickRow(sourceId,'edit');await page.waitForSelector('#source-form');
  const record=await (await page.request.get(url+'/api/sources/'+sourceId)).json();
  const csrf=await page.evaluate(()=>window.VULNDESK_CONFIG.csrf);
  const response=await page.request.post(url+'/api/sources/update',{headers:{Origin:url,'X-Vulndesk-CSRF':csrf},data:{source_id:sourceId,display_name:'Other operator',adapter_type:record.adapter_type,endpoint_ref:record.endpoint_url,enabled:false,expected_revision:record.revision,auth_mode:'none'}});
  assert.equal(response.status(),200);
  await page.locator('#source-form [type="submit"]').click();await page.waitForSelector('#source-form-error:not([hidden])');
  assert.match(await page.locator('#source-form-error').textContent(),/telah berubah/);
  const updated=await (await page.request.get(url+'/api/sources/'+sourceId)).json();assert.equal(updated.display_name,'Other operator');await closeAction();
  await page.locator('[data-action="refresh"]').click();await loaded();
});

test('status, adapter and text filters update the source table',async()=>{
  await page.locator('#source-enabled-filter').selectOption('0');await loaded();
  await page.waitForFunction(()=>document.querySelectorAll('.sources-table tbody tr').length===2);
  await page.locator('#source-adapter-filter').selectOption('registry-only');await loaded();
  await page.waitForFunction(()=>document.querySelectorAll('.sources-table tbody tr').length===1);
  assert.match(await page.locator('.sources-table tbody').textContent(),/community-example/);
  await page.locator('#source-enabled-filter').selectOption('');await loaded();
  await page.locator('#source-adapter-filter').selectOption('');await loaded();
  await page.locator('#search-input').fill(sourceId);
  await page.waitForFunction(()=>document.querySelectorAll('.sources-table tbody tr').length===1 && document.querySelector('.sources-table tbody').textContent.includes('ui-cve-mirror'));
  await page.locator('#search-input').fill('');await page.waitForFunction(()=>document.querySelectorAll('.sources-table tbody tr').length===5);
});

test('delete requires the matching ID and removes the registry source',async()=>{
  await clickRow(sourceId,'delete');await page.waitForSelector('#source-delete-form');
  await page.locator('#source-confirm_source').fill('wrong-id');await page.locator('#source-delete-form [name="confirm"]').check();
  await page.locator('#source-delete-form [type="submit"]').click();await page.waitForSelector('#source-form-error:not([hidden])');
  assert.match(await page.locator('#source-form-error').textContent(),/harus sama/);
  await page.locator('#source-confirm_source').fill(sourceId);await page.locator('#source-delete-form [type="submit"]').click();
  await page.waitForFunction(()=>!document.querySelector('#action-dialog').open);await loaded();
  assert.equal((await page.request.get(url+'/api/sources/'+sourceId)).status(),404);
  assert.equal(await page.locator('.sources-table tbody tr').count(),4);
});

test('builtin CWE template can be registered and appears in the mission source choices',async()=>{
  await page.locator('[data-source-action="preset"][data-source="mitre-cwe"]').click();
  await page.waitForSelector('#source-form');assert.equal(await page.locator('#source-adapter_type').inputValue(),'mitre-cwe');
  await page.locator('#source-cwe_id').fill('CWE-79');await saveForm();
  assert.equal(await page.locator('.sources-table .source-row-actions [data-source="mitre-cwe"][data-source-action="view"]').count(),1);
  await page.goto(url+'/#missions');await page.waitForSelector('[data-action="sync"]');await page.locator('[data-action="sync"]').click();
  await page.waitForSelector('#source-select');const values=await page.locator('#source-select option').evaluateAll(options=>options.map(o=>o.value));
  assert.ok(values.includes('mitre-cwe'));assert.ok(!values.includes('community-example'));await closeAction();await gotoSources();
});

test('source names and descriptions render as text, including markup-like input',async()=>{
  const name='<img src=x onerror="window.SOURCE_XSS=1">';
  await newForm('xss-example',name,'https://cti.example.org/feed','registry-only');await saveForm();
  assert.equal(await page.locator('.sources-table .source-name img').count(),0);
  assert.equal(await page.evaluate(()=>window.SOURCE_XSS),undefined);
  await clickRow('xss-example','view');await page.waitForSelector('#detail-dialog[open]');
  assert.equal(await page.locator('#detail-content h2').textContent(),name);assert.equal(await page.locator('#detail-content img').count(),0);
  await page.locator('#detail-dialog [data-close]').click();
});

test('demo CRUD stays in the page session and does not call mutation endpoints',async()=>{
  await page.goto(url+'/?demo-ui-test=1#sources');await loaded();
  // Switch through the actual settings control; the app state owns the mode.
  await page.locator('#connection-button').click();await page.locator('#mode-select').selectOption('demo');await page.locator('[data-action="apply-mode"]').click();await loaded();
  const mutations=[];const listen=request=>{if(request.method()==='POST')mutations.push(request.url());};page.on('request',listen);
  await newForm('demo-only','API sesi contoh','https://demo.example.org/feed','registry-only');await saveForm();
  assert.equal(await page.locator('.sources-table .source-row-actions [data-source="demo-only"][data-source-action="view"]').count(),1);
  assert.equal((await page.request.get(url+'/api/sources/demo-only')).status(),404);assert.deepEqual(mutations,[]);page.off('request',listen);
});

test('mobile page and form fit the viewport with table scrolling contained',async()=>{
  await page.setViewportSize({width:390,height:844});await loaded();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  await page.locator('[data-action="source-add"]').click();await page.waitForSelector('#source-form');
  const bounds=await page.locator('#action-dialog').boundingBox();assert.ok(bounds.width<=390&&bounds.x>=0);
  if(process.env.VULNDESK_UI_SCREENSHOTS) {
    fs.mkdirSync(process.env.VULNDESK_UI_SCREENSHOTS,{recursive:true});
    await page.screenshot({path:path.join(process.env.VULNDESK_UI_SCREENSHOTS,'API_External_Mobile_Form.png'),fullPage:true});
  }
  await closeAction();await page.setViewportSize({width:1440,height:1000});await loaded();
  if(process.env.VULNDESK_UI_SCREENSHOTS)await page.screenshot({path:path.join(process.env.VULNDESK_UI_SCREENSHOTS,'API_External_UI.png'),fullPage:true});
  assert.deepEqual(errors,[]);
});

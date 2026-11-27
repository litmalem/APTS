const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const elements = new Map();
const el = id => {
  if (!elements.has(id)) elements.set(id, {
    value: '', textContent: '', innerHTML: '', disabled: false, handlers: {},
    addEventListener(name, handler) { this.handlers[name] = handler; }
  });
  return elements.get(id);
};
const requests = [];
let enriched = false;
let batch = 0, unavailable = false;
const context = {context_id: 'ctx', orchestration_id: 'paorch-test', can_plan: true,
  hypothesis_count: 64, revisions: [], input_status: 'COMPLETED'};
const sandbox = {
  document: {getElementById: el}, location: {search: ''}, URLSearchParams,
  setInterval() {},
  fetch: async (url, opts) => {
    requests.push({url, body: opts && JSON.parse(opts.body)});
    let body;
    if (url.endsWith('/enrichment')) {
      batch++;
      enriched = !unavailable;
      body = {kinds: {attack: unavailable ? {unavailable: 50, deferred: 14} :
        batch === 1 ? {fetched: 50, cached: 0, empty: 0, deferred: 14} :
        {fetched: 14, cached: 50, empty: 0, deferred: 0}}};
    } else if (url.endsWith('/attack-context')) {
      body = {hypotheses: enriched ? {'hyp-1': [{attack_id: 'T1189',
        attack_name: 'Drive-by Compromise', confidence: 0.45}]} : {}};
    } else body = {contexts: [context]};
    return {ok: true, json: async () => body};
  }
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pentest_web/planning.js'), 'utf8'), sandbox);
(async () => {
  await new Promise(resolve => setImmediate(resolve));
  const automatic = requests.filter(r => r.url.endsWith('/enrichment'));
  assert.equal(automatic.length, 2, 'all 64 hypotheses are processed automatically in bounded batches');
  assert(automatic.every(r => r.body.refresh === false));
  assert(el('attack-body').innerHTML.includes('T1189'));
  assert(el('attack-body').innerHTML.includes('64 diambil'));
  await el('refresh').handlers.click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(batch, 2, 'workspace polling does not repeat completed enrichment');
  await el('attack-enrich').handlers.click();
  const sent = requests.filter(r => r.url.endsWith('/enrichment')).at(-1);
  assert.deepEqual(sent.body, {kinds: ['attack'], refresh: true});
  assert(el('attack-body').innerHTML.includes('T1189'));
  unavailable = true;
  await el('attack-enrich').handlers.click();
  assert.equal(batch, 4, 'outage stops deferred-batch retries');
  assert(el('attack-body').innerHTML.includes('50 tidak tersedia'));
  assert.equal(el('attack-enrich').disabled, false);
  console.log('Planning ATT&CK refresh checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});

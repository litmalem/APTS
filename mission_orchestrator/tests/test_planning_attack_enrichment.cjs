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
const context = {context_id: 'ctx', orchestration_id: 'paorch-test', can_plan: true,
  hypothesis_count: 1, revisions: [], input_status: 'COMPLETED'};
const sandbox = {
  document: {getElementById: el}, location: {search: ''}, URLSearchParams,
  setInterval() {},
  fetch: async (url, opts) => {
    requests.push({url, body: opts && JSON.parse(opts.body)});
    let body;
    if (url.endsWith('/enrichment')) {
      enriched = true;
      body = {kinds: {attack: {fetched: 1, cached: 0, empty: 0}}};
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
  assert(el('attack-body').innerHTML.includes('Belum ada pemetaan'));
  await el('attack-enrich').handlers.click();
  const sent = requests.find(r => r.url.endsWith('/enrichment'));
  assert.deepEqual(sent.body, {kinds: ['attack'], refresh: true});
  assert.equal(requests.filter(r => r.url.endsWith('/attack-context')).length, 2);
  assert(el('attack-body').innerHTML.includes('T1189'));
  assert(el('attack-body').innerHTML.includes('1 diambil'));
  console.log('Planning ATT&CK refresh checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});

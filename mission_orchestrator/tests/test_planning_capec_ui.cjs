const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const elements = new Map();
const el = id => {
  if (!elements.has(id)) elements.set(id, {value: '', innerHTML: '', handlers: {},
    addEventListener(t, f) { this.handlers[t] = f; }});
  return elements.get(id);
};
const step = {hypothesis_id: 'h1', hypothesis_sha256: 'sha1', label: 'CVE-test',
  preconditions: [], effects: [], evidence_refs: [], validation: {}};
const plan = {paths: [{path_id: 'p1', steps: [step], cost: 1, length: 1, confidence: .5}],
  gaps: [], dependency_edges: [], unreachable_goals: [],
  problem: {goal_predicates: [], feedback: []}};
const context = {context_id: 'ctx', orchestration_id: 'paorch-test', can_plan: true,
  revisions: [{revision: 1, plan, changes: {added_paths: [], removed_paths: []}}],
  knowledge_chains: {sha1: {links: [
    {from_type: 'CWE', from_id: 'CWE-79', to_type: 'CAPEC', to_id: 'CAPEC-63'},
    {from_type: 'CAPEC', from_id: 'CAPEC-63', to_type: 'ATTACK', to_id: 'T1189'}]}}};
let mappings = [{attack_id: 'T1189', confidence: .45, capec_mappings: [
  {capec_id: 'CAPEC-66', cwe_id: 'CWE-89', source_dataset: '<img onerror=bad>', source_version: '3.9'},
  {capec_id: 'CAPEC-66', cwe_id: 'CWE-89', source_dataset: '<img onerror=bad>', source_version: '3.9'},
  {capec_id: 'javascript:bad'}]}];
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pentest_web/planning.js'), 'utf8'), {
  document: {getElementById: el}, location: {search: ''}, URLSearchParams, setInterval() {},
  fetch: async url => ({ok: true, json: async () => url.endsWith('/attack-context')
    ? {hypotheses: {h1: mappings}} : url.endsWith('/enrichment')
      ? {kinds: {attack: {cached: 1}}} : {contexts: [context]}})
});
const settled = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  await settled();
  let detail = el('detail').innerHTML;
  assert(detail.includes('CWE-89') && detail.includes('CAPEC-66') && detail.includes('T1189'));
  assert(detail.includes('https://capec.mitre.org/data/definitions/66.html'));
  assert(detail.includes('CAPEC-63') && detail.includes('Snapshot hipotesis'));
  assert(detail.includes('&lt;img onerror=bad&gt;') && !detail.includes('<img onerror=bad>'));
  assert(!detail.includes('javascript:bad'));
  assert.equal((detail.match(/definitions\/66.html/g) || []).length, 1);
  // A revision with a different model hash must not borrow the stored chain.
  step.hypothesis_sha256 = 'older-sha'; mappings = [];
  await el('attack-enrich').handlers.click();
  detail = el('detail').innerHTML;
  assert(!detail.includes('CAPEC-63'));
  assert(detail.includes('Belum ada pemetaan CAPEC'));
  console.log('Planning CAPEC rendering checks passed');
})().catch(e => { console.error(e); process.exitCode = 1; });

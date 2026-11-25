// Exercise the actual controller with a small DOM adapter and workspace responses.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..', 'pentest_web');
const html = fs.readFileSync(path.join(root, 'hypothesis.html'), 'utf8');
const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], {
  value: ['status-filter', 'confidence-filter'].includes(m[1]) ? 'all' : '',
  textContent: '', innerHTML: '', hidden: false, disabled: false, handlers: {},
  addEventListener(type, fn) { this.handlers[type] = fn; },
  close() { this.open = false; }, showModal() { this.open = true; }, focus() {},
}]));
const el = id => { assert(elements.has(id), `Missing element ${id}`); return elements.get(id); };
const click = (id, event = {}) => el(id).handlers.click(event);
const context = (name, status = 'COMPLETED') => ({
  context_id: 'enum-' + name, orchestration_id: 'orch-' + name,
  mission: {mission_id: 'mission-' + name, task_id: 'task-' + name},
  target: {value: 'https://' + name + '.example', type: 'URL'},
  enumeration_input: {available: true, enumeration_run_id: 'enum-' + name,
    wpt_job_id: 'wpt-' + name, observation_count: 2, technology_count: 1},
  hypothesis_run: {vulnerability_hypothesis_run_id: 'hyprun-' + name},
  correlation: {status}, cti_input: {available: true, knowledge_count: 1},
  metrics: {total: status === 'COMPLETED' ? 1 : 0, ready: status === 'COMPLETED' ? 1 : 0, gaps: 0},
  hypotheses: status === 'COMPLETED' ? [{id: 'hyp-' + name, title: name, tech: 'tech-' + name,
    cti: 'cti-' + name, cve_id: 'CVE-2024-12345', cwes: [{cwe_id:'CWE-79', cwe_name:'Cross-site Scripting'}], severity: 'High', confidence: 90, evidenceConfidence: 90,
    knowledgeConfidence: 95, ready: true, rows: [], validation: [], evidence: [],
    statement: 'Hypothesis ' + name, supporting_evidence_refs: ['ev-' + name],
    target: {target_value: 'https://' + name + '.example'},
    lineage: {mission_id: 'mission-' + name, enumeration_run_id: 'enum-' + name, wpt_job_id: 'wpt-' + name},
  }] : [],
});
const contexts = [context('A'), context('B'), context('C', 'COMPLETED_NO_MATCH')];
contexts[0].hypotheses.push({...contexts[0].hypotheses[0], id:'hyp-A-second', cve_id:'CVE-2024-67890'});
let fail = false;
const sandbox = {
  document: {getElementById: el}, Set, clearTimeout() {}, setTimeout() { return 1; },
  fetch: async () => { if (fail) throw new Error('offline'); return {ok: true,
    json: async () => ({contexts, selected_context_id: 'enum-A', may_have_more: true,
      mission_cwe_summary: ['A','B'].map(name => ({mission_id:'mission-' + name, mapping_status:'AVAILABLE',
        unmapped_cve_ids:[], cwes:[{cwe_id:'CWE-79', cwe_name:'Cross-site Scripting', cve_ids:['CVE-2024-12345']}]}))})}; },
};
vm.runInNewContext(fs.readFileSync(path.join(root, 'hypothesis.js'), 'utf8'), sandbox);
const settled = () => new Promise(resolve => setImmediate(resolve));
const selectHypothesis = name => el('hyp-items').handlers.change({target: {
  closest: () => ({dataset: {select: 'hyp-' + name}, checked: true}),
}});
const selectContext = name => click('input-runs', {target: {
  closest: () => ({dataset: {context: 'enum-' + name}}),
}});
(async () => {
  await settled();
  assert.equal(el('target-label').textContent, 'https://A.example');
  assert.equal(el('unique-cwe-count').textContent, 1);
  assert.equal((el('unique-cwe-list').innerHTML.match(/>CWE-79</g) || []).length, 1);
  assert(el('unique-cwe-list').innerHTML.includes('Cross-site Scripting'));
  assert(html.indexOf('id="unique-cwe-title"') < html.indexOf('id="handoff-title"'));
  assert(el('hyp-detail').innerHTML.includes('CWE-79'));
  assert(el('hyp-detail').innerHTML.includes('Cross-site Scripting'));
  assert.equal(el('input-limit-note').hidden, false);
  // Results are attributed per mission-id and per wpt-id.
  assert.equal(el('hyp-scope').hidden, false);
  assert(el('hyp-scope').innerHTML.includes('Mission ID') && el('hyp-scope').innerHTML.includes('mission-A'));
  assert(el('hyp-scope').innerHTML.includes('WPT ID') && el('hyp-scope').innerHTML.includes('wpt-A'));
  assert(el('hyp-items').innerHTML.includes('mission-A') && el('hyp-items').innerHTML.includes('wpt-A'));
  selectHypothesis('A'); click('preview');
  let packet = JSON.parse(el('package-json').textContent);
  assert.equal(packet.enumeration_run_id, 'enum-A');
  assert.equal(packet.hypotheses[0].lineage.wpt_job_id, 'wpt-A');
  selectContext('B');
  assert.equal(el('handoff-dialog').open, false);
  assert.equal(el('preview').disabled, true);
  assert.equal(el('target-label').textContent, 'https://B.example');
  selectHypothesis('B'); click('preview');
  packet = JSON.parse(el('package-json').textContent);
  assert.deepEqual(packet.hypotheses.map(h => h.hypothesis_id), ['hyp-B']);
  assert.equal(packet.mission_id, 'mission-B');
  el('mission-filter').value = 'mission-A'; el('mission-filter').handlers.change();
  assert(el('input-runs').innerHTML.includes('wpt-A'));
  assert(!el('input-runs').innerHTML.includes('wpt-B'));
  el('mission-filter').value = ''; el('target-filter').value = 'wpt-B';
  el('target-filter').handlers.input();
  assert(!el('input-runs').innerHTML.includes('wpt-A'));
  assert(el('input-runs').innerHTML.includes('wpt-B'));
  selectContext('C');
  assert.equal(el('unique-cwe-count').textContent, 0);
  assert(!el('unique-cwe-list').innerHTML.includes('CWE-79'));
  assert.equal(el('metric-total').textContent, 0);
  assert(el('hyp-items').innerHTML.includes('Korelasi selesai tanpa kecocokan'));
  selectContext('A'); selectHypothesis('A'); click('preview');
  click('reanalyze'); await settled();
  assert.equal(el('preview').disabled, true);
  assert.equal(el('handoff-dialog').open, false);
  fail = true; click('reanalyze'); await settled();
  assert.equal(el('preview').disabled, true);
  assert.equal(el('target-label').textContent, '—');
  assert(el('analysis-notice').textContent.includes('offline'));
  console.log('PASS: context isolation, package lineage, filters, zero matches, refresh and errors');
})().catch(error => { console.error(error); process.exitCode = 1; });

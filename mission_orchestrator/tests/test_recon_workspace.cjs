const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../pentest_web/app.js'), 'utf8');
const target = {target_type:'URL', target_value:'https://example.test:443'};
function run(id, date, status='COMPLETED') {
 return {recon_run_id:id, mission_id:'mission-test', completed_at:date, run_status:status,
  request:{observations:[{observation_id:'obs-'+id, kind:'RAW_EVIDENCE', source:{source_kind:'WPT_STAGE6_RESULT'}, target, summary:'WPT observation', confidence:1}]},
  output:{hosts:[], domains:[], services:[], raw_evidence:[{evidence_ref:'manifest-'+id}]}};
}
function workspace(history=[]) {
 const elements = new Map();
 const element = id => {
  if(!elements.has(id))elements.set(id, {value:'', innerHTML:'', dataset:{}, querySelectorAll(selector){
   const attr = selector.slice(1,-1);
   return [...this.innerHTML.matchAll(new RegExp(attr+'="([^"]+)"', 'g'))].map(match=>{
    const key=attr.slice(5).replace(/-([a-z])/g, (_,c)=>c.toUpperCase());
    return {dataset:{[key]:match[1]}};
   });
  }});
  return elements.get(id);
 };
 const context=vm.createContext({document:{getElementById:element, querySelectorAll:()=>[]},
  AbortController, setTimeout, clearTimeout, setInterval:()=>{},
  fetch:async url=>({ok:true, json:async()=>url.includes('reconnaissance-runs')?{reconnaissance_runs:history}:url.includes('orchestration-options')?{mission_scope_targets:[{mission_id:'mission-test',target}]}:{}})});
 vm.runInContext(source,context);
 return {element, eval:code=>vm.runInContext(code,context)};
}

test('initial API load displays imported WPT observation, evidence, context and export', async()=>{
 const ui=workspace([run('wpt-run','2026-11-07T10:55:38Z')]);
 await ui.eval('refresh()');
 assert.equal(ui.eval('state.run.recon_run_id'),'wpt-run');
 assert.match(ui.element('result-panel').innerHTML,/WPT observation/);
 assert.match(ui.element('run-context').innerHTML,/wpt-run/);
 assert.equal(ui.element('evidence-count').textContent,1);
 assert.equal(ui.element('export').disabled,false);
 assert.match(ui.element('mission-scope-list').innerHTML,/data-observed-run="wpt-run"/);
 ui.eval("selectTab('evidence')");
 assert.match(ui.element('result-panel').innerHTML,/manifest-wpt-run/);
});

test('default selects newest completed observation and refresh preserves explicit selection', async()=>{
 const ui=workspace([run('old','2026-11-06'),run('failed','2026-11-08','FAILED'),run('new','2026-11-07')]);
 await ui.eval('refresh()');
 assert.equal(ui.eval('state.run.recon_run_id'),'new');
 ui.eval("showStoredRun('old')");
 await ui.eval('refresh()');
 assert.equal(ui.eval('state.run.recon_run_id'),'old');
 assert.match(ui.element('run-context').innerHTML,/old/);
});

test('observed status opens the corresponding target run and switches to observations', async()=>{
 const ui=workspace([run('old','2026-11-06'),run('new','2026-11-07')]);
 await ui.eval('refresh()');
 ui.eval("showStoredRun('old');selectTab('history')");
 // Capture the registered status-button callback from the rendered scope table.
 ui.eval("const buttons=[]; const list=$('mission-scope-list'); const query=list.querySelectorAll.bind(list); list.querySelectorAll=selector=>{const found=query(selector);buttons.push(...found);return found;};renderScopeList();buttons[0].onclick()");
 assert.equal(ui.eval('state.run.recon_run_id'),'new');
 assert.equal(ui.eval('state.tab'),'observations');
 assert.match(ui.element('result-panel').innerHTML,/WPT observation/);
});

test('empty history clears stale result and disables export', async()=>{
 const ui=workspace();
 await ui.eval('refresh()');
 ui.eval("state.run={recon_run_id:'stale'};syncSelectedRun()");
 assert.equal(ui.eval('state.run'),null);
 assert.equal(ui.element('export').disabled,true);
 assert.match(ui.element('result-panel').innerHTML,/Belum ada hasil reconnaissance/);
});

test('live Pentest serves the fix and its saved WPT result renders', {skip:!process.env.RECON_WORKSPACE_LIVE_URL}, async()=>{
 const base=process.env.RECON_WORKSPACE_LIVE_URL;
 const response=await fetch(base+'/api/pentest/reconnaissance-runs?limit=100');
 assert.equal(response.status,200);
 const {reconnaissance_runs:history}=await response.json();
 const wpt=history.find(item=>item.request?.observations?.some(obs=>obs.source?.source_kind==='WPT_STAGE6_RESULT'));
 assert.ok(wpt,'Live API must contain a saved WPT observation');
 const asset=await fetch(base+'/pentest/app.js');
 assert.equal(await asset.text(),source,'Running server must serve the updated asset');
 const ui=workspace(history);
 await ui.eval('refresh()');
 ui.eval(`showStoredRun(${JSON.stringify(wpt.recon_run_id)})`);
 assert.match(ui.element('result-panel').innerHTML,/RAW_EVIDENCE/);
 assert.match(ui.element('result-panel').innerHTML,/Verified Stage 6 WPT evidence/);
 assert.equal(ui.element('evidence-count').textContent,wpt.output.raw_evidence.length);
 assert.ok(wpt.output.raw_evidence.length>0);
 assert.ok(ui.element('run-context').innerHTML.includes(wpt.recon_run_id));
});

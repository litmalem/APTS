// Exercise controller state, HTTP payloads, escaping, revision selection, and errors.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '..', 'pentest_web');
const html = fs.readFileSync(path.join(root,'planning.html'),'utf8');
const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], {
  value:m[1]==='max-paths'?'10':'', textContent:'', innerHTML:'', hidden:false, disabled:false,
  handlers:{}, addEventListener(t,f){this.handlers[t]=f;}
}]));
const el = id => {assert(elements.has(id),id);return elements.get(id);};
const plan = {paths:[], gaps:[], problem:{goal_basis:'HYPOTHESIS_VALIDATION_COVERAGE',goal_predicates:[],feedback:[]},
  dependency_edges:[],unreachable_goals:[],expanded_states:1,policy:'DETERMINISTIC_COST'};
const record = {revision:1, plan, changes:{added_paths:[],removed_paths:[]}};
const context = {context_id:'enum-A', orchestration_id:'paorch-A', can_plan:true,hypothesis_count:2,
  mission:{mission_id:'<img onerror=bad>'}, target:{value:'https://a.example'}, revisions:[]};
let fail=false, payload;
const sandbox = {document:{getElementById:el},location:{search:''},URLSearchParams,
  fetch:async (url, opts)=>{
    if(fail) throw new Error('offline');
    if(opts) payload=JSON.parse(opts.body);
    return {ok:true,json:async()=>opts?{created:true,record}:{contexts:[context]}};
  }};
vm.runInNewContext(fs.readFileSync(path.join(root,'planning.js'),'utf8'), sandbox);
const settled = ()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  await settled();
  assert.equal(el('build').disabled,false);
  assert(el('lineage').innerHTML.includes('&lt;img'));
  assert(!el('lineage').innerHTML.includes('<img'));
  await el('build').handlers.click();
  assert.deepEqual(payload,{orchestration_id:'paorch-A',max_paths:10});
  assert.equal(el('revision-count').textContent,1);
  assert(el('detail').innerHTML.includes('Tidak ada jalur'));
  assert(el('goal').innerHTML.includes('cakupan validasi'));
  fail=true;await el('refresh').handlers.click();
  assert.equal(el('build').disabled,true);
  assert(el('notice').textContent.includes('offline'));
  console.log('Planning UI controller checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

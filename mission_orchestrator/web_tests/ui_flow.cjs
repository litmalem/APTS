// DOM integration test with synthetic responses. No live GSS or target actions.
// Run: npm install --prefix <temp-directory> jsdom
// NODE_PATH=<temp-directory>/node_modules node web_tests/ui_flow.cjs
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const root=path.join(__dirname,'../gss_web/static');
const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'http://127.0.0.1:8802',runScripts:'outside-only'});
const w=dom.window,d=w.document;let authenticated=false,offline=false,posts=[],errors=[];
w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};w.confirm=()=>true;w.URL.createObjectURL=()=> 'blob:synthetic';w.URL.revokeObjectURL=()=>{};
w.addEventListener('error',e=>errors.push(e.error));
const principal={principal_id:'test-admin',roles:['GOVERNANCE_ADMIN','SECURITY_APPROVER'],capabilities:['read','scope','policy','approve','revoke','emergency_activate','emergency_release','retry'],csrf:'test-csrf'};
const scope={scope_contract_id:'scope-1',mission_id:'mission-1',name:'Scope test',policy_set_id:'default-policy',version:1,status:'ACTIVE',targets:[{target_type:'IP',target_value:'192.0.2.10',allowed:1,environment:'LAB',notes:'keep me'}],sources:[{source_id:'nvd-cve',source_type:'CTI',allowed:1,constraints:{read_only:true}}],action_constraints:[{action_class:'CTI_SOURCE_READ',action_name:'*',effect:'ALLOW',max_risk_level:'LOW',requires_approval:0,constraints:{read_only:true,max_pages:1}}],metadata:{existing:'preserved'}};
const approval={approval_request_id:'approval-1',mission_id:'mission-1',risk_level:'HIGH',required_approver_role:'SECURITY_APPROVER',status:'PENDING',effective_status:'PENDING',expires_at:'2099-01-01T00:00:00',reason:'Manual review'};
const policy={policy_set_id:'default-policy',name:'Default',version:1,status:'ACTIVE',description:'Policy'};
const decision={decision_id:'decision-1',mission_id:'mission-1',decision:'ALLOW',decision_status:'ACTIVE'};
const emergency={active:0,version:1,reason:'No stop'};
function response(data,status=200){return {ok:status<400,status,json:async()=>data}}
w.fetch=async(url,options={})=>{const u=new URL(url,w.location.href),p=u.pathname;const body=options.body?JSON.parse(options.body):undefined;
 if(p==='/api/session')return authenticated?response(principal):response({detail:'Login required'},401);
 if(p==='/api/login'){authenticated=true;return response(principal)}
 if(p==='/api/logout'){authenticated=false;return response({status:'ok'})}
 if(offline)return response({detail:'GSS offline'},503);
 if(body!==undefined){posts.push({p,body});if(p.includes('/emergency-stop/')){emergency.active=p.endsWith('activate')?1:0;emergency.version++}return response(p.endsWith('/decision')?{policy_decision:{decision:'DENY',reason_codes:['EMERGENCY_STOP_ACTIVE']}}:{scope_contract:{...scope,version:2},delivered:1})}
 if(p.endsWith('/runtime/status'))return response({database:{status:'ok'},cti_event_api:{status:'reachable'},service:{outbox_worker_running:true},emergency_state:emergency});
 if(p.endsWith('/console/overview'))return response({counts:{pending_approvals:1,active_scopes:1,expiring_scopes:0,failed_events:0}});
 if(p.includes('/console/records/')){let kind=p.split('/').pop(),rows={approvals:[approval],scopes:[scope],policies:[policy],decisions:[decision],audit:[{event_type:'TEST',payload:'<img src=x onerror=alert(1)>',actor_id:'tester'}],'emergency-history':[]}[kind];return response({items:rows,total:rows.length,page:1,limit:20})}
 if(p.includes('/console/approval/'))return response({approval,request:{action_class:'VULNERABILITY_VALIDATION',resource_value:'192.0.2.10',evidence_refs:['evidence-1']},scope,risk:[]});
 if(p.includes('/scope-contracts/'))return response({scope_contract:scope});
 if(p.includes('/console/policy/'))return response({policy,rules:[],obligations:[]});
 if(p.includes('/decisions/'))return response({policy_decision:decision});
 if(p.endsWith('/emergency-stop'))return response({emergency_state:emergency});
 if(p.endsWith('/outbox/status'))return response({stats:{total:1,delivered:1,pending:0,failed:0},recent:[],worker_running:true,destination:'synthetic'});
 return response({status:'ok'});
};
w.eval(fs.readFileSync(path.join(root,'app.js'),'utf8'));
const wait=async(predicate)=>{for(let n=0;n<150;n++){if(predicate())return;await new Promise(r=>setTimeout(r,10))}throw Error('Timeout: '+predicate)};
const click=id=>{assert.ok(d.getElementById(id),'missing '+id);d.getElementById(id).click()};
const navigate=async page=>{d.querySelector(`[data-page="${page}"]`).click();await wait(()=>!d.getElementById('refresh').disabled&&d.getElementById('title').textContent===({approvals:'Human Approvals',scopes:'Scope & RoE',policies:'Policies & Compliance',decisions:'Policy Decisions',audit:'Audit & Mission Trace',emergency:'Emergency Control',outbox:'Integrations & Outbox',overview:'Overview'})[page])};
(async()=>{
 await wait(()=>!d.getElementById('login').hidden);
 d.getElementById('token').value='x'.repeat(48);d.getElementById('loginForm').dispatchEvent(new w.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:d.querySelector('#loginForm button')}));
 await wait(()=>!d.getElementById('shell').hidden&&!d.getElementById('refresh').disabled);
 assert.equal(d.getElementById('token').value,'');assert.ok(d.getElementById('content').textContent.includes('Persetujuan tertunda'));
 await navigate('approvals');d.querySelector('[data-detail]').click();await wait(()=>d.getElementById('approve'));d.getElementById('reason').value='Reviewed evidence';click('approve');await wait(()=>d.getElementById('detailTitle').textContent==='Hasil keputusan GSS');assert.ok(d.getElementById('detailBody').textContent.includes('DENY'));click('closeDetail');
 await navigate('scopes');d.querySelector('[data-detail]').click();await wait(()=>d.getElementById('revise'));click('revise');await wait(()=>d.getElementById('scopeForm'));d.getElementById('scopeReason').value='Revise period';d.getElementById('scopeForm').dispatchEvent(new w.Event('submit',{cancelable:true}));await wait(()=>d.getElementById('detailTitle').textContent==='Kontrak diterbitkan');const write=posts.find(p=>p.p.endsWith('/console/scopes')).body;assert.equal(write.contract.targets[0].notes,'keep me');assert.equal(write.contract.action_constraints[0].constraints.max_pages,1);assert.equal(write.contract.metadata.existing,'preserved');assert.equal(write.previous_id,'scope-1');click('closeDetail');
 await navigate('policies');d.querySelector('[data-detail]').click();await wait(()=>d.getElementById('editPolicy'));click('editPolicy');await wait(()=>d.getElementById('policyForm'));d.getElementById('policyReason').value='Maintenance window';d.getElementById('policyForm').dispatchEvent(new w.Event('submit',{cancelable:true}));await wait(()=>!d.getElementById('detail').open&&!d.getElementById('refresh').disabled);
 await navigate('decisions');d.querySelector('[data-detail]').click();await wait(()=>d.getElementById('revokeDecision'));click('closeDetail');
 await navigate('audit');d.querySelector('[data-detail]').click();await wait(()=>d.getElementById('detail').open);assert.equal(d.querySelector('#detailBody img'),null);assert.ok(d.getElementById('detailBody').textContent.includes('<img'));click('closeDetail');
 await navigate('emergency');click('activate');await wait(()=>d.getElementById('confirmMutation'));d.getElementById('reason').value='Synthetic stop';d.getElementById('confirmAction').checked=true;click('confirmMutation');await wait(()=>!d.getElementById('detail').open&&!d.getElementById('refresh').disabled);assert.equal(emergency.active,1);
 await navigate('outbox');assert.ok(d.getElementById('retry'));await navigate('overview');offline=true;click('refresh');await wait(()=>!d.getElementById('refresh').disabled);assert.ok(d.getElementById('connection').textContent.includes('tidak diketahui'));assert.ok(d.getElementById('content').textContent.includes('Data tidak dapat dimuat'));assert.equal(errors.length,0);
 console.log('PASS: login; eight pages; authoritative approval result; scope revision preservation; policy change; audit escaping; emergency transition; offline state.');
 dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1});

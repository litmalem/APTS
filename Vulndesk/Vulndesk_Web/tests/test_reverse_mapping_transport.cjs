const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const helpers=source.slice(source.indexOf('  const esc ='),source.indexOf('  function toast'));
const rendering=source.slice(source.indexOf('  function cweAttackHTML'),source.indexOf('  async function connectionDialog'));

function setup(api){
 const dialog={open:false,calls:0,showModal(){this.open=true;this.calls++;}};
 const content={innerHTML:''};
 const ctx=vm.createContext({window:{VULNDESK_CONFIG:{mode:'live'},VULNDESK_DEMO:{}},Intl,URL,URLSearchParams,
   api,$:id=>id==='#detail-dialog'?dialog:content,toast:message=>{throw new Error(message);}});
 vm.runInContext(helpers+rendering+';globalThis.ui={openAttackDetail,openDetail};',ctx);
 return {ctx,dialog,content};
}

function data(id){return {attack_id:id,technique:{attack_id:id,name:'Technique '+id},items:[],page:1,limit:10,total:0};}

test('reverse requests retain filters and refresh the same open modal',async()=>{
 const urls=[];const {ctx,dialog,content}=setup(async url=>{urls.push(url);return data('T1190');});
 await ctx.ui.openAttackDetail('T1190',{page:2,limit:25,mapping_kind:'CAPEC',search:'CVE-2024 &'});
 const request=new URL('http://local/'+urls[0]);
 assert.equal(request.pathname,'/attack/T1190/vulnerabilities');
 assert.equal(request.searchParams.get('page'),'2');
 assert.equal(request.searchParams.get('limit'),'25');
 assert.equal(request.searchParams.get('mapping_kind'),'CAPEC');
 assert.equal(request.searchParams.get('search'),'CVE-2024 &');
 await ctx.ui.openAttackDetail('T1190');
 assert.equal(dialog.calls,1);
 assert.ok(content.innerHTML.includes('CVE terkait'));
});

test('late detail response cannot overwrite a newer technique selection',async()=>{
 let resolveFirst;
 const {ctx,content}=setup(url=>url.includes('T1190')?new Promise(resolve=>{resolveFirst=resolve;}):Promise.resolve(data('T1059')));
 const first=ctx.ui.openAttackDetail('T1190');
 await ctx.ui.openAttackDetail('T1059');
 resolveFirst(data('T1190'));
 await first;
 assert.ok(content.innerHTML.includes('Technique T1059'));
 assert.ok(!content.innerHTML.includes('Technique T1190'));
});


test('relation form submission is intercepted instead of navigating the document',()=>{
 let listener,submitted,prevented=false;
 const ctx=vm.createContext({document:{addEventListener:(event,handler)=>{assert.equal(event,'submit');listener=handler;}},submitForm:form=>{submitted=form;}});
 const start=source.indexOf("  document.addEventListener('submit',");
 const end=source.indexOf("\n",start);
 vm.runInContext(source.slice(start,end),ctx);
 const form={id:'attack-relations-form'};
 listener({target:form,preventDefault:()=>{prevented=true;}});
 assert.equal(prevented,true);
 assert.equal(submitted,form);
});

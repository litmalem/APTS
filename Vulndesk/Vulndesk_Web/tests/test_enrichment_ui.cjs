/* Pure rendering/transport checks; no browser or user services are controlled. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const helpers=source.slice(source.indexOf('  const esc ='),source.indexOf('  function toast'));
const enrichment=source.slice(source.indexOf('  async function enrichmentData'),source.indexOf('  function renderMissions'));
const context=vm.createContext({window:{VULNDESK_CONFIG:{mode:'live'},VULNDESK_DEMO:{}},Intl,URLSearchParams});
vm.runInContext(helpers+`
function heading(){return '';}
function button(){return '';}
function tabs(){return '';}
function pagination(){return '';}
function sortButton(){return '';}
function empty(a,b){return a+' '+b;}
function api(url){return url;}
`+enrichment+`
globalThis.ui={renderEnrichment,renderEnrichmentDetail,enrichmentData,state};`,context);
const ui=context.ui;

test('list shows target and technology summary, escaping untrusted evidence',()=>{
  const html=ui.renderEnrichment({total:1,items:[{intake_id:'one',target:{target_value:'https://example.test/<script>'},
    technologies:[{name:'PHP',version:'8.4.27'}],enrichment_version:2,technology_count:1,cpe_candidate_count:0}]});
  assert.ok(html.includes('https://example.test/&lt;script&gt;'));
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('PHP 8.4.27'));
});

test('pipeline uses backend status even with zero vulnerabilities',()=>{
  const html=ui.renderEnrichmentDetail({verified_vulnerability_count:0,evidence_status:'SEALED',
    pipeline_status:{cpe_resolution:'COMPLETED_NO_MATCH',vulnerability_correlation:'COMPLETED'}},'pipeline',[]);
  assert.ok(html.includes('Selesai · tidak ada kecocokan'));
  assert.ok(html.includes('Selesai'));
  assert.ok(!html.includes('Pending'));
});

test('pip assembled without this evidence is not shown as not run',()=>{
  const html=ui.renderEnrichmentDetail({evidence_status:'SEALED',
    pipeline_status:{cpe_resolution:'COMPLETED_WITH_CANDIDATES',vulnerability_correlation:'NOT_RECORDED',pip_assembly:'ASSEMBLED_WITHOUT_EVIDENCE'},
    pipeline_details:{pip_assembly:{latest_revision:1,latest_readiness:'PARTIAL',revision_count:1}}},'pipeline',[]);
  assert.ok(html.includes('Sudah dirakit · belum memuat evidence ini'));
  assert.ok(html.includes('Revisi terbaru 1'));
  assert.ok(html.includes('Belum tercatat untuk misi ini'));
  assert.ok(!html.includes('Belum dijalankan'));
});

test('legacy detail exposes missing data instead of inventing stage status',()=>{
  assert.ok(ui.renderEnrichmentDetail({technology_count:3},'technologies',[]).includes('Evidence lama'));
  const html=ui.renderEnrichmentDetail({},'pipeline',[]);
  assert.ok(html.includes('UNKNOWN'));
  assert.ok(html.includes('Tidak tersedia'));
  assert.ok(!html.includes('SEALED'));
});

test('list request sends ordering and preserves mission/search filters',async()=>{
  ui.state.direction='asc';ui.state.search='example.test';ui.state.enrichmentMission='mission-one';
  const url=await ui.enrichmentData();
  assert.ok(url.includes('direction=asc'));
  assert.ok(url.includes('mission_id=mission-one'));
  assert.ok(url.includes('search=example.test'));
});


test('product candidate clearly separates reference release from unknown target version',()=>{
  const html=ui.renderEnrichmentDetail({technology_resolution:[{name:'nginx',version:'',status:'VERSION_UNKNOWN'}],
    cpe_candidates:[{technology_name:'nginx',technology_version:'',vendor:'f5',product:'nginx',match_level:'PRODUCT',
      cpe23_uri:null,reference_cpe23_uri:'cpe:2.3:a:f5:nginx:1.24.0:*:*:*:*:*:*:*',status:'VERSION_UNKNOWN'}]},'cpe_candidates',[]);
  assert.ok(html.includes('versi target belum diketahui'));
  assert.ok(html.includes('CPE versi target belum ditentukan'));
  assert.ok(html.includes('Referensi dictionary · bukan versi target'));
  assert.ok(html.includes('f5 / nginx'));
});

test('missing product diagnostic stays visible when candidate table is empty',()=>{
  const html=ui.renderEnrichmentDetail({technology_resolution:[{name:'Angular',version:'',status:'PRODUCT_NOT_FOUND'}],cpe_candidates:[]},'cpe_candidates',[]);
  assert.ok(html.includes('PRODUCT_NOT_FOUND'));
  assert.ok(html.includes('Produk belum tersedia di dictionary lokal'));
});

test('intake pipeline shows child lineage and completed empty stages accurately',()=>{
 const html=ui.renderEnrichmentDetail({pipeline:{status:'COMPLETED',pipeline_mission_id:'child-<script>',attempt_count:1},
 pipeline_status:{attack_mapping:'COMPLETED'},pipeline_details:{attack_mapping:{intake_record_count:0}}},'pipeline',[]);
 assert.ok(html.includes('child-&lt;script&gt;'));
 assert.ok(html.includes('0 rekaman untuk intake ini'));
 assert.ok(html.includes('Selesai'));
 assert.ok(!html.includes('<script>'));
});

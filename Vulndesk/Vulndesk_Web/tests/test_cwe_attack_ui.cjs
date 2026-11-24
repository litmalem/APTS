const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const helpers=source.slice(source.indexOf('  const esc ='),source.indexOf('  function toast'));
const rendering=source.slice(source.indexOf('  function cweAttackHTML'),source.indexOf('  async function openDetail'));
const ctx=vm.createContext({window:{VULNDESK_CONFIG:{mode:'live'},VULNDESK_DEMO:{}},Intl,URL,URLSearchParams});
vm.runInContext(helpers+rendering+';globalThis.ui={cweAttackHTML,attackRelationsHTML,detailsHTML};',ctx);

test('detail explains indirect mapping with escaped source, path and rationale',()=>{
  const html=ctx.ui.detailsHTML('vulnerabilities', {cve_id:'CVE-2026-1', attack_mapping_status:'MAPPED_VIA_CWE',
    attack_mappings:[{attack_id:'T1190',technique_name:'Exploit <script>',confidence:0.7,
      paths:[{cwe_id:'CWE-89',cwe_name:'SQL injection',rule_id:40,tactic_name:'Initial Access',
        mapping_source:'seed',confidence:0.7,rationale:'<img src=x onerror=alert(1)>'}]}]});
  assert.ok(html.includes('CVE-2026-1 → CWE-89 → T1190'));
  assert.ok(html.includes('70.0%'));
  assert.ok(html.includes('INFERRED'));
  assert.ok(html.includes('seed'));
  assert.ok(html.includes('bukan bukti eksploitasi'));
  assert.ok(html.includes('&lt;img'));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('<script>'));
});

test('unmapped and unavailable are distinct from a negative security conclusion',()=>{
  const empty=ctx.ui.cweAttackHTML({attack_mapping_status:'NO_CWE_MAPPING',attack_mappings:[]});
  assert.ok(empty.includes('Belum ada aturan'));
  assert.ok(empty.includes('bukan bukti'));
  assert.ok(ctx.ui.cweAttackHTML({}).includes('belum tersedia'));
});

test('direct and CAPEC paths display relationship type, version and evidence links',()=>{
  const html=ctx.ui.cweAttackHTML({cve_id:'CVE-2024-1234',attack_mapping_status:'MAPPED_DIRECT',
    attack_mappings:[{attack_id:'T1190',mapping_status:'CURATED',paths:[
      {mapping_kind:'DIRECT_CVE',source_dataset:'ctid-cve-attack',relationship_type:'exploitation_technique',source_version:'ATT&CK:16.1',source_sha256:'abc',source_url:'https://example.org/data',references_json:'["javascript:alert(1)"]'},
      {mapping_kind:'CAPEC',cwe_id:'CWE-89',capec_id:'CAPEC-100',source_dataset:'mitre-capec'}]}]});
  assert.ok(html.includes('CVE-2024-1234 → T1190'));
  assert.ok(html.includes('CVE-2024-1234 → CWE-89 → CAPEC-100 → T1190'));
  assert.ok(html.includes('Metode eksploitasi'));
  assert.ok(html.includes('ATT&amp;CK:16.1'));
  assert.ok(html.includes('SHA-256: abc'));
  assert.ok(!html.includes('href="javascript:'));
});


test('CVE detail links techniques and reverse detail links CVEs with source evidence',()=>{
 const direct=ctx.ui.cweAttackHTML({cve_id:'CVE-2024-1234',attack_mapping_status:'MAPPED_DIRECT',attack_mappings:[{attack_id:'T1190',paths:[]}]});
 assert.ok(direct.includes('data-attack-relations="T1190"'));
 const html=ctx.ui.attackRelationsHTML({attack_id:'T1190',total:1,page:1,limit:10,items:[{id:5,cve_id:'CVE-2024-1234',description_text:'<script>bad</script>',mapping:{attack_id:'T1190',mapping_status:'CURATED',paths:[{mapping_kind:'DIRECT_CVE',source_dataset:'ctid-cve-attack',source_version:'ATT&CK:16.1',confidence:0.75}]}}]});
 assert.ok(html.includes('data-detail="5"'));
 assert.ok(html.includes('ctid-cve-attack'));
 assert.ok(html.includes('ATT&amp;CK:16.1'));
 assert.ok(html.includes('1 CVE unik'));
 assert.ok(html.includes('bukan bukti eksploitasi'));
 assert.ok(!html.includes('<script>'));
});

test('reverse pagination preserves escaped query and kind without exposing unrelated mappings',()=>{
 const html=ctx.ui.attackRelationsHTML({attack_id:'T1190',total:21,page:2,limit:10,mapping_kind:'CAPEC',search:'"<script>',items:[]});
 assert.ok(html.includes('Halaman 2 / 3'));
 assert.ok(html.includes('data-attack-kind="CAPEC"'));
 assert.ok(html.includes('data-attack-page="3"'));
 assert.ok(html.includes('&quot;&lt;script&gt;'));
 assert.ok(html.includes('Tidak ada relasi yang cocok'));
 assert.ok(!html.includes('<script>'));
});

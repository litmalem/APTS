/* Synthetic fixtures for the clearly labeled preview. These are not findings. */
window.VULNDESK_DEMO = (() => {
 const vulnerabilities = [
  ["CVE-DEMO-0001","Apache HTTP Server","Contoh kelemahan validasi request pada layanan HTTP.","CRITICAL",9.8,"CWE-20"],
  ["CVE-DEMO-0002","OpenSSL","Contoh akses memori di luar batas saat memproses input.","HIGH",8.1,"CWE-125"],
  ["CVE-DEMO-0003","WordPress Plugin","Contoh kontrol akses yang tidak memadai pada plugin.","HIGH",7.5,"CWE-862"],
  ["CVE-DEMO-0004","Linux Kernel","Contoh kesalahan pengelolaan memori pada komponen sistem.","HIGH",7.8,"CWE-416"],
  ["CVE-DEMO-0005","Nginx","Contoh informasi layanan yang dapat terlihat oleh pengguna.","MEDIUM",5.3,"CWE-200"],
  ["CVE-DEMO-0006","PostgreSQL","Contoh pemrosesan input dengan validasi yang tidak lengkap.","MEDIUM",6.5,"CWE-20"],
  ["CVE-DEMO-0007","Spring Framework","Contoh keterbatasan kontrol resource pada aplikasi web.","MEDIUM",5.9,"CWE-400"],
  ["CVE-DEMO-0008","Redis","Contoh konfigurasi informasi diagnostik yang terlalu terbuka.","LOW",3.1,"CWE-200"],
  ["CVE-DEMO-0009","Example API","Contoh validasi authorization pada endpoint administrasi.","CRITICAL",9.1,"CWE-862"],
  ["CVE-DEMO-0010","Example Gateway","Contoh pencatatan informasi sensitif dalam log.","LOW",2.7,"CWE-532"],
 ].map((v,i)=>({id:i+1,cve_id:v[0],product:v[1],description_text:v[2],preferred_base_severity:v[3],preferred_base_score:v[4],cwe_id:v[5],preferred_cvss_version:"3.1",published_at:"2026-09-"+String(28-i).padStart(2,"0"),modified_at:"2026-10-05",cwe_count:1,reference_count:3+i%4,affected_product_count:1+i%3,nvd_url:"",raw_json:JSON.stringify({sample:true,identity:v[0],notice:"Synthetic preview record, not a confirmed vulnerability."},null,2)}));
 const components=[
  ["CTI-A01","cti_subsystem_orchestrator","CTI Subsystem Orchestrator","Agent","Hybrid Reactive-Deliberative","Task proposal / coordination"],
  ["CTI-A02","cti_acquisition_freshness_agent","Acquisition & Freshness","Agent","RAO","Authorized source acquisition"],
  ["CTI-S01","normalization_provenance_service","Normalization & Provenance","Service","Statistical-Symbolic","Normalization only"],
  ["CTI-S02","asset_profiling_cpe_resolution_service","Asset Profiling & CPE Resolution","Service","Rank + symbolic validation","Enrichment only"],
  ["CTI-S03","vulnerability_correlation_service","Vulnerability Correlation","Service","Graph + rules","Applicability only"],
  ["CTI-S04","attack_mapping_service","ATT&CK Mapping","Service","Rules + ontology","Mapping only"],
  ["CTI-A03","attack_path_reasoning_agent","Attack-Path Reasoning","Agent","Graph reasoning","Intelligence paths only"],
  ["CTI-S05","threat_context_service","Threat Context","Service","Context synthesis","Context only"],
  ["CTI-A04","risk_prioritization_agent","Risk Prioritization","Agent","BDI scoring","Priority recommendation"],
  ["CTI-S06","pip_assembly_validation_service","PIP Assembly & Validation","Service","Deterministic validation","Packaging / validation"],
  ["CTI-D01","pentest_intelligence_package","Pentest Intelligence Package","Data Artifact","Immutable artifact","No authority"],
  ["CTI-INF01","pentest_enrichment_api_service","Pentest Enrichment API","Infrastructure Service","HTTP adapter","Transport only"],
  ["CTI-INF02","cti_event_bus","CTI Event Bus","Infrastructure Service","Typed events","Communication only"],
  ["CTI-INF03","cti_event_dispatcher","CTI Event Dispatcher","Infrastructure Service","Event routing","Dispatch only"],
  ["CTI-INF04","cti_source_sync_connector","Source Sync Connector","Infrastructure Service","Source adapter","Authorized acquisition"],
  ["CTI-INF05","governance_client","Governance Client","Infrastructure Service","Policy adapter","aptsGS retains authority"],
 ].map((c,i)=>({id:i+1,component_id:c[0],service_key:c[1],service_name:c[2],component_type:c[3],mechanism:c[4],authority_boundary:c[5],enabled:1,status:c[3]==="Data Artifact"?"available":"idle",last_error:null,optional_component:c[0]==="CTI-A03"}));
 const attack=[{id:1,attack_id:"T1190",name:"Exploit Public-Facing Application",description_text:"Contoh entri katalog ATT&CK untuk pemeriksaan aplikasi publik.",platforms_json:'["Linux","Windows"]',modified_at_source:"2026-09-30"},{id:2,attack_id:"T1059",name:"Command and Scripting Interpreter",description_text:"Contoh teknik penggunaan command interpreter.",platforms_json:'["Linux","Windows","macOS"]',modified_at_source:"2026-09-27"},{id:3,attack_id:"T1078",name:"Valid Accounts",description_text:"Contoh teknik penggunaan akun yang valid.",platforms_json:'["Linux","Windows"]',modified_at_source:"2026-09-25"}];
 const cwe=[{id:1,cwe_id:"CWE-20",cwe_name:"Improper Input Validation",description_text:"Contoh katalog kelemahan validasi input.",abstraction:"Class",status_value:"Stable",likelihood_of_exploit:"High"},{id:2,cwe_id:"CWE-125",cwe_name:"Out-of-bounds Read",description_text:"Contoh katalog pembacaan di luar batas memori.",abstraction:"Base",status_value:"Stable",likelihood_of_exploit:"High"},{id:3,cwe_id:"CWE-862",cwe_name:"Missing Authorization",description_text:"Contoh katalog pemeriksaan otorisasi yang hilang.",abstraction:"Class",status_value:"Stable",likelihood_of_exploit:"High"},{id:4,cwe_id:"CWE-200",cwe_name:"Exposure of Sensitive Information",description_text:"Contoh katalog eksposur informasi.",abstraction:"Class",status_value:"Stable",likelihood_of_exploit:"Medium"}];
 const cpe=[{id:1,vendor:"apache",product:"http_server",version:"2.4.0",cpe23_uri:"cpe:2.3:a:apache:http_server:2.4.0:*:*:*:*:*:*:*",title:"Contoh Apache HTTP Server 2.4.0",deprecated:0,last_synced_at:"2026-10-05"},{id:2,vendor:"openssl",product:"openssl",version:"3.0.0",cpe23_uri:"cpe:2.3:a:openssl:openssl:3.0.0:*:*:*:*:*:*:*",title:"Contoh OpenSSL 3.0.0",deprecated:0,last_synced_at:"2026-10-05"},{id:3,vendor:"nginx",product:"nginx",version:"1.24.0",cpe23_uri:"cpe:2.3:a:nginx:nginx:1.24.0:*:*:*:*:*:*:*",title:"Contoh Nginx 1.24.0",deprecated:0,last_synced_at:"2026-10-04"}];
 const sources=[
  {source_id:'nvd-cve',display_name:'NVD — Kerentanan CVE',adapter_type:'nvd-cve',endpoint_ref:'https://services.nvd.nist.gov/rest/json/cves/2.0',enabled:true,credential_ref:'env:NVD_API_KEY',auth_mode:'api-key',freshness_sla_seconds:86400,criticality:0.95,trust_tier:'AUTHORITATIVE_PUBLIC',max_pages:1,page_size:500,timeout_seconds:90},
  {source_id:'nvd-cpe',display_name:'NVD — Kamus produk CPE',adapter_type:'nvd-cpe',endpoint_ref:'https://services.nvd.nist.gov/rest/json/cpes/2.0',enabled:true,credential_ref:'env:NVD_API_KEY',auth_mode:'api-key',freshness_sla_seconds:86400,criticality:0.9,trust_tier:'AUTHORITATIVE_PUBLIC',max_pages:1,page_size:500,timeout_seconds:90},
  {source_id:'mitre-attack',display_name:'MITRE ATT&CK',adapter_type:'mitre-attack',endpoint_ref:'https://attack-taxii.mitre.org/api/v21',enabled:true,auth_mode:'none',freshness_sla_seconds:604800,criticality:0.9,trust_tier:'AUTHORITATIVE_PUBLIC',timeout_seconds:90},
  {source_id:'community-example',display_name:'Community CTI — contoh',adapter_type:'registry-only',endpoint_ref:'https://cti.example.org/feed',enabled:false,auth_mode:'none',freshness_sla_seconds:86400,criticality:0.5,trust_tier:'EXTERNAL',timeout_seconds:90,description:'Contoh konfigurasi API dengan format yang memerlukan adapter tambahan.'}
 ];
 return {sources,vulnerabilities,components,attack,cwe,cpe,tweets:[{id:1,tweet_text:"Contoh diskusi pembaruan dependensi dan pengelolaan patch aplikasi.",topic_text:"Vulnerability management",uploaded_at:"2026-10-05",file_name:"tweet_topics_example.csv"},{id:2,tweet_text:"Contoh diskusi keterlacakan evidence pada sistem agentic.",topic_text:"Agentic governance",uploaded_at:"2026-10-05",file_name:"tweet_topics_example.csv"}],topics:[{id:1,topic_text:"Vulnerability management",uploaded_at:"2026-10-05"},{id:2,topic_text:"Agentic governance",uploaded_at:"2026-10-05"}],malware:[{id:1,software_id:"S-DEMO-01",name:"Sample software",description_text:"Artefak contoh untuk pratinjau katalog malware.",modified_at_source:"2026-10-04"}],actors:[{id:1,group_id:"G-DEMO-01",name:"Sample threat group",description_text:"Entitas contoh untuk pratinjau katalog threat actor.",modified_at_source:"2026-10-04"}],sync:[{sync_type:"NVD_INCREMENTAL_SAMPLE",started_at:"2026-10-05 09:30:00",status_value:"SAMPLE",total_fetched:10,total_inserted:10,total_updated:0,total_failed:0}]};
})();

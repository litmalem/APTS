/* External CTI source management. All live mutations use the local CSRF-protected adapter. */
window.VulndeskSources = {
  create({$, esc, icon, fmt, date, api, state, samples, isDemo, heading, button, stat, statusBadge, pagination, empty, openAction, toast, render}) {
    const adapters = [
      {id:'nvd-cve',label:'NVD CVE 2.0'}, {id:'nvd-cpe',label:'NVD CPE 2.0'},
      {id:'mitre-attack',label:'MITRE ATT&CK / TAXII 2.1'}, {id:'mitre-cwe',label:'MITRE CWE REST'},
      {id:'ctid-cve-attack',label:'MITRE CTID — CVE / ATT&CK'}, {id:'mitre-capec',label:'MITRE CAPEC — CWE / ATT&CK'},
      {id:'registry-only',label:'Registry saja — adapter belum tersedia'}
    ];
    const presets = [
      {source_id:'nvd-cve',display_name:'NVD — Kerentanan CVE',adapter_type:'nvd-cve',endpoint_ref:'https://services.nvd.nist.gov/rest/json/cves/2.0',credential_ref:'env:NVD_API_KEY',auth_mode:'api-key'},
      {source_id:'nvd-cpe',display_name:'NVD — Kamus produk CPE',adapter_type:'nvd-cpe',endpoint_ref:'https://services.nvd.nist.gov/rest/json/cpes/2.0',credential_ref:'env:NVD_API_KEY',auth_mode:'api-key'},
      {source_id:'mitre-attack',display_name:'MITRE ATT&CK',adapter_type:'mitre-attack',endpoint_ref:'https://attack-taxii.mitre.org/api/v21',auth_mode:'none'},
      {source_id:'mitre-cwe',display_name:'MITRE — Katalog CWE',adapter_type:'mitre-cwe',endpoint_ref:'https://cwe-api.mitre.org/api/v1',auth_mode:'none'}
    ];
    let demoRevision = 0;
    function normalized(row) {
      return {...row, display_name:row.display_name||row.source_id, enabled:!!row.enabled,
        adapter_label:adapters.find(a=>a.id===row.adapter_type)?.label||adapters.find(a=>a.id==='registry-only').label,
        endpoint_url:row.endpoint_ref, endpoint_error:null, acquisition_supported:row.adapter_type!=='registry-only',
        credential_configured:false, revision:'demo-'+(++demoRevision),
        health:row.health||{status:'SIMULASI',failure_count:0,last_success_at:null,circuit_state:'CLOSED'},
        protocol:row.adapter_type==='mitre-attack'?'TAXII_2_1':row.adapter_type==='mitre-capec'?'REST_XML':'REST_JSON',
        created_at:row.created_at||new Date().toISOString(), updated_at:new Date().toISOString()};
    }
    samples.sources = (samples.sources||[]).map(normalized);
    async function load() {
      if (!isDemo()) return api('sources?'+new URLSearchParams({search:state.search,enabled:state.sourceEnabled,adapter_type:state.sourceAdapter,page:state.page,limit:state.limit}));
      const all = samples.sources;
      const query=state.search.toLowerCase();
      const rows=all.filter(r=>(!query||[r.source_id,r.display_name,r.endpoint_url,r.adapter_label,r.description].some(v=>String(v||'').toLowerCase().includes(query))) &&
        (state.sourceEnabled===''||r.enabled===(state.sourceEnabled==='1')) && (!state.sourceAdapter||r.adapter_type===state.sourceAdapter));
      const page=Math.min(state.page,Math.max(1,Math.ceil(rows.length/state.limit)));
      return {items:rows.slice((page-1)*state.limit,page*state.limit),total:rows.length,page,limit:state.limit,adapters,
        stats:{total:all.length,enabled:all.filter(r=>r.enabled).length,supported:all.filter(r=>r.acquisition_supported).length,attention:0},
        templates:presets.filter(p=>!all.some(r=>r.source_id===p.source_id))};
    }
    function options(list, value) {
      return list.map(([id,label])=>`<option value="${esc(id)}" ${id===value?'selected':''}>${esc(label)}</option>`).join('');
    }
    function rowsHTML(rows) {
      return rows.map(r=>`<tr>
        <td class="source-name"><button class="cve-link" data-source-action="view" data-source="${esc(r.source_id)}">${esc(r.display_name)}</button><small class="mono text-muted">${esc(r.source_id)}</small></td>
        <td class="source-endpoint"><span class="mono">${esc(r.endpoint_url||'Endpoint perlu diperbaiki')}</span><small class="text-muted">${esc(r.adapter_label)}</small></td>
        <td>${statusBadge(r.enabled?'AKTIF':'NONAKTIF',r.enabled?'ok':'muted')}<small class="text-muted">${r.acquisition_supported?'Adapter tersedia':'Registry saja'}</small></td>
        <td>${statusBadge(r.health.status,isDemo()?'purple':undefined)}<small class="text-muted">${r.health.last_success_at?'Berhasil '+date(r.health.last_success_at):'Belum ada akuisisi berhasil'}</small><small class="text-muted">Monitor: ${esc(r.monitor?.scheduler_status||'NEW')} · berikutnya ${date(r.monitor?.next_check_at)}</small></td>
        <td><span class="source-auth">${r.auth_mode==='none'?'Tanpa autentikasi':r.credential_ref?esc(r.credential_ref.replace(/^env:/,'')):'Anonim'}</span><small class="text-muted">${r.credential_ref?(isDemo()?'Referensi contoh':r.credential_configured?'Tersedia di server':'Environment belum diatur'):'Tidak ada key tersimpan'}</small></td>
        <td><div class="source-row-actions"><button class="btn source-small" data-source-action="view" data-source="${esc(r.source_id)}" aria-label="Lihat ${esc(r.display_name)}">Lihat</button><button class="btn source-small" data-source-action="edit" data-source="${esc(r.source_id)}" aria-label="Ubah ${esc(r.display_name)}">Ubah</button><button class="icon-button source-delete" data-source-action="delete" data-source="${esc(r.source_id)}" aria-label="Hapus ${esc(r.display_name)}" title="Hapus sumber">${icon('trash',16)}</button></div></td>
      </tr>`).join('');
    }
    function pageHTML(data) {
      const stats=data.stats;
      const list=data.adapters||adapters;
      return heading('API Eksternal','Kelola endpoint sumber data CTI dan konfigurasi akuisisinya.',button('refresh','Perbarui daftar','refresh')+button('source-add','Tambah API','plug',true))+
        `<div class="stats-grid source-stats">${stat('Sumber terdaftar',stats.total,'plug','Konfigurasi dalam registry CTI')}${stat('Sumber aktif',stats.enabled,'activity','Enabled pada registry','green')}${stat('Adapter tersedia',stats.supported,'layers','Format akuisisi yang didukung')}${stat('Perlu diperiksa',stats.attention,'clock','Endpoint atau akuisisi bermasalah','red')}</div>`+
        `<section class="panel"><div class="table-toolbar source-toolbar"><div class="search-box">${icon('search',17)}<input id="search-input" class="input" type="search" placeholder="Cari nama, Source ID, atau endpoint…" aria-label="Cari sumber API" value="${esc(state.search)}" maxlength="200"></div><div class="toolbar-group"><label class="sr-only" for="source-enabled-filter">Filter status aktif</label><select id="source-enabled-filter" class="input">${options([['','Semua status'],['1','Aktif'],['0','Nonaktif']],state.sourceEnabled)}</select><label class="sr-only" for="source-adapter-filter">Filter adapter</label><select id="source-adapter-filter" class="input">${options([['','Semua adapter'],...list.map(a=>[a.id,a.label])],state.sourceAdapter)}</select></div></div>
          <div class="table-wrap"><table class="sources-table"><thead><tr><th>Nama / Source ID</th><th>Endpoint / adapter</th><th>Status aktif</th><th>Kesehatan akuisisi</th><th>Autentikasi</th><th>Aksi</th></tr></thead><tbody>${rowsHTML(data.items)}</tbody></table>${data.items.length?'':empty(stats.total?'Tidak ada sumber yang cocok':'Belum ada API terdaftar',stats.total?'Ubah pencarian atau filter untuk menampilkan sumber.':'Tambahkan API atau daftarkan salah satu API bawaan di bawah.')}</div>${pagination()}</section>`+
        `<p class="source-footnote">Perubahan disimpan pada registry CTI. Kesehatan berasal dari riwayat akuisisi; daftar ini tidak mengirim permintaan ke endpoint eksternal.</p>`+
        (data.templates.length?`<section class="panel source-presets"><div class="panel-heading"><div><h2>API bawaan yang belum terdaftar</h2><p class="metric-sub">Gunakan konfigurasi bawaan sebagai awal, lalu sesuaikan sebelum menyimpan.</p></div><span class="badge muted">${data.templates.length} API</span></div><div class="source-preset-grid">${data.templates.map(t=>`<div class="source-preset-card"><span class="source-preset-icon">${icon('plug',20)}</span><h3>${esc(t.display_name)}</h3><p class="mono">${esc(t.endpoint_ref)}</p><button class="btn" data-source-action="preset" data-source="${esc(t.source_id)}">Daftarkan API ${icon('chevron',14)}</button></div>`).join('')}</div></section>`:'');
    }
    async function detail(id) {
      const row=isDemo()?samples.sources.find(r=>r.source_id===id):await api('sources/'+encodeURIComponent(id));
      if(!row) throw new Error('Sumber API tidak ditemukan. Perbarui daftar.');
      return row;
    }
    function field(label, name, value='', attributes='') {
      return `<div class="field"><label for="source-${name}">${label}</label><input id="source-${name}" name="${name}" class="input" value="${esc(value??'')}" ${attributes}></div>`;
    }
    function adapterFields(kind, row={}) {
      if(['ctid-cve-attack','mitre-capec'].includes(kind)) return '<p class="metric-sub">Impor dataset lengkap. Relasi menyimpan versi, hash sumber, dan jenis hubungan. Gunakan URL resmi CTID JSON atau CAPEC XML.</p>';
      if(kind==='nvd-cve'||kind==='nvd-cpe') return `<div class="source-form-grid">${field('Batas halaman per akuisisi','max_pages',row.max_pages||1,'type="number" min="1" max="100" required')}${field('Entri per halaman','page_size',row.page_size||500,'type="number" min="1" max="2000" required')}</div>`+
        (kind==='nvd-cpe'?field('Keyword produk (opsional)','keyword',row.keyword,'maxlength="200" placeholder="contoh: openssl"')+field('CPE match string (opsional)','match_string',row.match_string,'maxlength="500" placeholder="cpe:2.3:…"'):'')+
        '<p class="metric-sub">Endpoint harus mengembalikan format NVD API 2.0 yang sesuai dengan adapter ini.</p>';
      if(kind==='mitre-attack') return field('Collection ID TAXII','collection_id',row.collection_id||'x-mitre-collection--1f5f1533-f617-4ca8-9ab4-6a02367fa019','maxlength="160" required pattern="[A-Za-z0-9_.:\\-]+"')+
        `<div class="field"><label for="source-sync_mode">Mode sinkronisasi</label><select id="source-sync_mode" name="sync_mode" class="input">${options([['INCREMENTAL','Incremental'],['FULL','Full']],row.sync_mode||'INCREMENTAL')}</select></div><p class="metric-sub">Gunakan API root TAXII 2.1; collection dan path objects ditambahkan oleh adapter.</p>`;
      if(kind==='mitre-cwe') { const m=row.sync_mode||'KNOWN'; return `<div class="field"><label for="source-sync_mode">Mode sinkronisasi CWE</label><select id="source-sync_mode" name="sync_mode" class="input">${options([['SINGLE','Satu CWE'],['KNOWN','Known — perkaya semua CWE yang belum lengkap'],['RANGE','Range ID']],m)}</select></div>`+
        (m==='SINGLE'?field('CWE ID untuk akuisisi','cwe_id',row.cwe_id||'CWE-20','required maxlength="9" pattern="CWE-[1-9][0-9]{0,4}" placeholder="CWE-20"'):'')+
        (m==='RANGE'?field('Awal range','cwe_range_start',row.cwe_range_start||1,'type="number" min="1" max="99999" required')+field('Akhir range','cwe_range_end',row.cwe_range_end||1500,'type="number" min="1" max="99999" required'):'')+
        '<p class="metric-sub">Known mengisi nama, abstraction, status, dan likelihood untuk CWE yang dibuat otomatis saat impor CVE. </p>'; }
      return `<div class="inline-note">API disimpan sebagai sumber registry. Format respons ini memerlukan adapter sebelum dapat dipakai pada misi akuisisi.</div><div class="field"><label for="source-protocol">Protokol sumber</label><select id="source-protocol" name="protocol" class="input">${options([['REST_JSON','REST JSON'],['TAXII_2_1','TAXII 2.1'],['STIX_FEED','STIX feed'],['JSON_FEED','JSON feed']],row.protocol||'REST_JSON')}</select></div>`;
    }
    function updateAuth() {
      const form=$('#source-form');
      if(!form) return;
      const kind=$('#source-adapter_type').value;
      const auth=$('#source-auth_mode');
      const bearer=$('option[value="bearer"]',auth);
      if(bearer) bearer.disabled=kind.startsWith('nvd-');
      if(kind.startsWith('nvd-')&&auth.value==='bearer') auth.value='api-key';
      $('#source-credential_ref').disabled=auth.value==='none';
    }
    function editDialog(row={}, update=false) {
      $('#detail-dialog').close();
      const kind=row.adapter_type||'registry-only';
      openAction(update?'Ubah API eksternal':'Tambah API eksternal',update?'Perbarui endpoint dan konfigurasi sumber CTI.':'Daftarkan sumber baru pada registry CTI.',
        `<form id="source-form" class="action-form source-form" data-operation="${update?'update':'create'}" data-mode="${isDemo()?'demo':'live'}">
          ${isDemo()?'<div class="inline-note">Perubahan hanya berlaku pada data contoh sesi ini.</div>':''}
          <div id="source-form-error" class="source-form-error" role="alert" hidden></div>
          <div class="source-form-grid">${field('Nama API','display_name',row.display_name,'required maxlength="160" placeholder="Nama sumber intelligence"')}${field('Source ID','source_id',row.source_id,`required maxlength="120" pattern="[A-Za-z0-9_.:\\-]+" ${update?'readonly':'placeholder="contoh: nvd-mirror"'}`)}</div>
          ${update?`<input type="hidden" name="expected_revision" value="${esc(row.revision)}"><p class="metric-sub">Source ID tetap digunakan sebagai identitas pada riwayat akuisisi.</p>`:''}
          <div class="field"><label for="source-adapter_type">Format data / adapter</label><select id="source-adapter_type" name="adapter_type" class="input">${options(adapters.map(a=>[a.id,a.label]),kind)}</select></div>
          ${field('Endpoint API (HTTPS)','endpoint_ref',row.endpoint_url||row.endpoint_ref,'type="url" required maxlength="500" placeholder="https://api.example.org/cti"')}
          <p class="metric-sub">Masukkan URL dasar. Parameter akuisisi dan referensi kredensial diatur terpisah.</p>
          <div class="source-form-grid"><div class="field"><label for="source-auth_mode">Autentikasi</label><select id="source-auth_mode" name="auth_mode" class="input">${options([['none','Tanpa autentikasi'],['api-key','API key — header apiKey'],['bearer','Bearer token']],row.auth_mode||'none')}</select></div>${field('Referensi environment','credential_ref',row.credential_ref,'maxlength="110" placeholder="env:NVD_API_KEY" autocomplete="off"')}</div>
          <p class="metric-sub">Isi nama variabel environment yang berakhiran API_KEY atau TOKEN. Nilai rahasia dibaca di server dari environment / .env pada direktori instalasi CTI.</p>
          <div id="source-adapter-fields" class="source-adapter-fields">${adapterFields(kind,row)}</div>
          <div class="field"><label for="source-description">Deskripsi (opsional)</label><textarea id="source-description" name="description" class="input" rows="2" maxlength="1500">${esc(row.description||'')}</textarea></div>
          <details class="source-advanced"><summary>Pengaturan akuisisi lanjutan</summary><div class="source-form-grid">${field('Freshness SLA (detik)','freshness_sla_seconds',row.freshness_sla_seconds||86400,'type="number" min="60" max="31536000" required')}${field('Timeout HTTP (detik)','timeout_seconds',row.timeout_seconds||90,'type="number" min="1" max="300" required')}${field('Criticality (0–1)','criticality',row.criticality??0.5,'type="number" min="0" max="1" step="0.0001" required')}${field('Trust tier','trust_tier',row.trust_tier||'EXTERNAL','maxlength="80" required')}${field('Interval cek minimum (detik)','adaptive_min_interval_seconds',row.adaptive_min_interval_seconds||300,'type="number" min="60" max="31536000" required')}${field('Interval cek maksimum (detik)','adaptive_max_interval_seconds',row.adaptive_max_interval_seconds||43200,'type="number" min="60" max="31536000" required')}${field('Scope contract auto-update','auto_scope_contract_id',row.auto_scope_contract_id||'','maxlength="100" placeholder="opsional jika CTI_AUTONOMOUS_SCOPE_CONTRACT_ID tersedia"')}</div><label class="checkbox-label"><input type="checkbox" name="adaptive_monitor_enabled" ${row.adaptive_monitor_enabled!==false?'checked':''}>Aktifkan pemeriksaan perubahan adaptif</label><label class="checkbox-label"><input type="checkbox" name="auto_update" ${row.auto_update===true?'checked':''}>Otomatis mulai mission CTI ketika perubahan terdeteksi</label><p class="metric-sub">Auto-update tetap melewati governance/GSS; scheduler tidak mengeksekusi connector secara langsung.</p></details>
          <label class="checkbox-label source-enabled"><input type="checkbox" name="enabled" ${row.enabled!==false?'checked':''}>Aktifkan sumber ini pada registry CTI</label>
          <div class="form-actions"><button type="button" class="btn" data-close="action-dialog">Batal</button><button type="submit" class="btn primary">${update?'Simpan perubahan':'Tambah API'}</button></div>
        </form>`);
      updateAuth();
    }
    function deleteDialog(row) {
      $('#detail-dialog').close();
      openAction('Hapus API eksternal','Konfirmasi penghapusan konfigurasi sumber dari registry.',
        `<form id="source-delete-form" class="action-form" data-mode="${isDemo()?'demo':'live'}"><div id="source-form-error" class="source-form-error" role="alert" hidden></div><div class="source-delete-summary"><strong>${esc(row.display_name)}</strong><span class="mono">${esc(row.source_id)}</span><p class="mono">${esc(row.endpoint_url||'Endpoint belum valid')}</p></div><input type="hidden" name="source_id" value="${esc(row.source_id)}"><input type="hidden" name="expected_revision" value="${esc(row.revision)}"><p class="metric-sub">Sumber dihapus dari daftar akuisisi. Data CTI dan riwayat yang sudah tersimpan tetap tersedia.${isDemo()?' Tindakan ini hanya simulasi.':''}</p>${field('Ketik Source ID untuk konfirmasi','confirm_source','','required autocomplete="off"')}<label class="checkbox-label"><input type="checkbox" name="confirm" required>Saya mengonfirmasi penghapusan API ini.</label><div class="form-actions"><button type="button" class="btn" data-close="action-dialog">Batal</button><button type="submit" class="btn danger">Hapus API</button></div></form>`);
    }
    function viewDialog(row) {
      const info=[['Source ID',row.source_id],['Adapter',row.adapter_label],['Protokol',row.protocol],['Status',row.enabled?'Aktif':'Nonaktif'],
        ['Autentikasi',row.auth_mode],['Referensi environment',row.credential_ref||'—'],['Freshness SLA',fmt(row.freshness_sla_seconds)+' detik'],
        ['Timeout',fmt(row.timeout_seconds)+' detik'],['Criticality',row.criticality],['Trust tier',row.trust_tier||'—'],
        ['Akuisisi berhasil terakhir',date(row.health.last_success_at)],['Percobaan terakhir',date(row.health.last_attempt_at)],
        ['Kegagalan berurutan',row.health.failure_count??0],['Circuit state',row.health.circuit_state||'—'],['Detektor perubahan',row.monitor?.detector_strategy||'—'],['Status scheduler',row.monitor?.scheduler_status||'NEW'],['Probe terakhir',date(row.monitor?.last_probe_at)],['Perubahan terakhir',date(row.monitor?.last_change_at)],['Pemeriksaan berikutnya',date(row.monitor?.next_check_at)],['Streak tanpa perubahan',row.monitor?.unchanged_streak??0],['Auto update',row.auto_update?'Aktif':'Nonaktif'],['Mission otomatis terakhir',row.monitor?.last_auto_mission_id||'—']];
      const parameters={};
      for(const key of ['max_pages','page_size','collection_id','sync_mode','keyword','match_string','cwe_id','cwe_range_start','cwe_range_end']) {
        if ((row.adapter_type.startsWith('nvd-')&&['max_pages','page_size'].includes(key)) ||
            (row.adapter_type==='nvd-cpe'&&['keyword','match_string'].includes(key)) ||
            (row.adapter_type==='mitre-attack'&&['collection_id','sync_mode'].includes(key)) ||
            (row.adapter_type==='mitre-cwe'&&['cwe_id','sync_mode','cwe_range_start','cwe_range_end'].includes(key))) parameters[key]=row[key]??'';
      }
      $('#detail-content').innerHTML=`<div class="dialog-header"><div><h2>${esc(row.display_name)}</h2><p>Konfigurasi API eksternal</p></div><button class="icon-button" data-close="detail-dialog" aria-label="Tutup detail">${icon('close')}</button></div><div class="dialog-body"><div class="detail-summary">${statusBadge(row.enabled?'AKTIF':'NONAKTIF',row.enabled?'ok':'muted')}${statusBadge(row.health.status,isDemo()?'purple':undefined)}</div><div class="source-detail-endpoint"><small>Endpoint API</small><p class="mono">${esc(row.endpoint_url||row.endpoint_error)}</p></div><p>${esc(row.description||'Belum ada deskripsi sumber.')}</p>${!row.acquisition_supported?'<div class="inline-note">API ini terdaftar untuk pengelolaan konfigurasi. Adapter akuisisi belum tersedia.</div>':''}<div class="section-label">Konfigurasi dan kesehatan sumber</div><div class="detail-grid">${info.map(([label,value])=>`<div><small>${esc(label)}</small><strong>${esc(value??'—')}</strong></div>`).join('')}</div><div class="section-label">Parameter adapter</div><pre class="detail-json">${esc(JSON.stringify(parameters,null,2))}</pre><div class="form-actions"><button class="btn danger" data-source-action="delete" data-source="${esc(row.source_id)}">${icon('trash',16)}Hapus API</button><button class="btn primary" data-source-action="edit" data-source="${esc(row.source_id)}">Ubah API</button></div></div>`;
      $('#detail-dialog').showModal();
    }
    async function handleAction(action, id) {
      try {
        if(action==='add') return editDialog();
        if(action==='preset') {
          const preset=(state.loaded?.templates||presets).find(p=>p.source_id===id);
          if(!preset) throw new Error('API bawaan sudah terdaftar. Perbarui daftar.');
          return editDialog(preset);
        }
        const row=await detail(id);
        if(action==='view') viewDialog(row);
        else if(action==='edit') editDialog(row,true);
        else if(action==='delete') deleteDialog(row);
      } catch(error) {toast(error.message,true);}
    }
    function fail(message) {
      const error=$('#source-form-error');
      if(error){error.textContent=message;error.hidden=false;error.scrollIntoView?.({block:'nearest'});}
    }
    async function submit(form, fields) {
      if(form.dataset.mode!==(isDemo()?'demo':'live')) throw new Error('Mode data berubah. Tutup dan buka kembali form.');
      try {
        if(form.id==='source-delete-form') {
          if(fields.confirm_source!==fields.source_id) throw new Error('Source ID konfirmasi harus sama dengan sumber yang akan dihapus.');
          if(fields.confirm!=='on') throw new Error('Konfirmasi penghapusan diperlukan.');
          if(isDemo()) samples.sources=samples.sources.filter(r=>r.source_id!==fields.source_id);
          else await api('sources/delete',{source_id:fields.source_id,expected_revision:fields.expected_revision,confirm:true});
          toast('Sumber API dihapus'+(isDemo()?' dalam simulasi.':'.'));
        } else {
          const body={...fields,enabled:fields.enabled==='on',adaptive_monitor_enabled:fields.adaptive_monitor_enabled==='on',auto_update:fields.auto_update==='on',credential_ref:fields.auth_mode==='none'?'':fields.credential_ref||''};
          for(const key of ['timeout_seconds','freshness_sla_seconds','max_pages','page_size','adaptive_min_interval_seconds','adaptive_max_interval_seconds']) if(key in body) body[key]=Number(body[key]);
          body.criticality=Number(body.criticality);
          if(!/^[A-Za-z0-9_.:-]{1,120}$/.test(body.source_id)) throw new Error('Source ID tidak valid.');
          const url=new URL(body.endpoint_ref);
          if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash) throw new Error('Gunakan endpoint HTTPS tanpa kredensial, query, atau fragment.');
          if(body.credential_ref&&!/^(?:(?:env:|secret-ref:))?[A-Z][A-Z0-9_]{0,100}(?:API_KEY|TOKEN)$/.test(body.credential_ref)) throw new Error('Referensi environment harus berakhiran API_KEY atau TOKEN.');
          const update=form.dataset.operation==='update';
          if(isDemo()) {
            const index=samples.sources.findIndex(r=>r.source_id.toLowerCase()===body.source_id.toLowerCase());
            if(!update&&index>=0) throw new Error('Source ID sudah digunakan. Pilih ID baru atau gunakan Ubah.');
            if(update&&index<0) throw new Error('Sumber API tidak ditemukan.');
            const saved=normalized({...body,created_at:update?samples.sources[index].created_at:undefined});
            if(update) samples.sources[index]=saved; else samples.sources.push(saved);
          } else await api('sources/'+(update?'update':'create'),body);
          toast((update?'Konfigurasi API diperbarui':'Sumber API ditambahkan')+(isDemo()?' dalam simulasi.':'.'));
        }
        $('#action-dialog').close();
        await render();
      } catch(error) {fail(error.message);throw error;}
    }
    async function changed(target) {
      if(target.id==='source-enabled-filter'||target.id==='source-adapter-filter') {
        state[target.id==='source-enabled-filter'?'sourceEnabled':'sourceAdapter']=target.value;state.page=1;await render();return true;
      }
      if(target.id==='source-adapter_type') {
        const row=Object.fromEntries(new FormData($('#source-form')));
        $('#source-adapter-fields').innerHTML=adapterFields(target.value,row);updateAuth();return true;
      }
      if(target.id==='source-sync_mode'&&$('#source-adapter_type')?.value==='mitre-cwe') {
        const row=Object.fromEntries(new FormData($('#source-form')));
        $('#source-adapter-fields').innerHTML=adapterFields('mitre-cwe',row);return true;
      }
      if(target.id==='source-auth_mode'){updateAuth();return true;}
      return false;
    }
    async function acquisitionSources() {
      if(isDemo()) return samples.sources.filter(r=>r.enabled&&r.acquisition_supported&&!r.endpoint_error);
      const sources=[];let page=1,total=1;
      while(sources.length<total) {
        const response=await api('sources?enabled=1&limit=100&page='+page++);
        sources.push(...response.items);total=response.total;
        if(!response.items.length)break;
      }
      return sources.filter(r=>r.acquisition_supported&&!r.endpoint_error);
    }
    return {load,pageHTML,handleAction,submit,changed,acquisitionSources};
  }
};

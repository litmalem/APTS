'use strict';
const $ = id => document.getElementById(id);
let jobs = [], selected = null, refreshing = false;
function message(text) { $('message').textContent = text; $('message').hidden = !text; }
async function api(path, method = 'GET', data) {
  const response = await fetch(path, {method, headers: {'Content-Type': 'application/json'}, body: data === undefined ? undefined : JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}
function cell(row, value) { const td = document.createElement('td'); td.textContent = value ?? '—'; row.append(td); return td; }
function action(parent, title, fn) { const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = title; button.addEventListener('click', async () => { button.disabled = true; try { await fn(); } catch (e) { message(e.message); } finally { button.disabled = false; } }); parent.append(button); }
function empty(body, count, text) { const row = body.insertRow(); const td = cell(row, text); td.colSpan = count; }
function detail(job) {
  selected = job.job_id; $('detail').hidden = false;
  const result = job.result || {}, metrics = result.scan_metrics || {};
  const lines = [`${job.target} · ${job.status}`, `Job: ${job.job_id}`, `Mission: ${job.mission_id || '—'} / Task: ${job.task_id || '—'}`, `Respons: ${metrics.responses_received ?? '—'} / ${metrics.requests_planned ?? '—'} · Durasi: ${job.scan_duration_ms ?? result.scan_timing?.duration_ms ?? '—'} ms`, `Teknologi: ${(result.technology_claims || []).map(x => typeof x === 'string' ? x : `${x.technology} (${x.confidence || '—'})`).join(', ') || 'Belum ada hasil signature'}`, `TLS: ${result.tls_status || '—'} · Favicon: ${result.favicon_status || '—'}`];
  if (job.error) lines.push(`Kesalahan: ${job.error}`);
  $('summary').replaceChildren(...lines.map(text => { const p = document.createElement('p'); p.textContent = text; return p; }));
  $('result').textContent = JSON.stringify(job, null, 2);
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const [health, ledger, inbox, allowlist] = await Promise.all([api('/api/health'), api('/api/jobs'), api('/api/governed-intakes'), api('/api/remote-allowlist')]);
    $('health').textContent = `Layanan aktif · Dispatch APTS ${health.apts_dispatch_configured ? 'terkonfigurasi' : 'belum terkonfigurasi'} · Inbox Mission ${health.mission_inbox_configured ? 'terkonfigurasi' : 'belum terkonfigurasi'}`;
    jobs = ledger.jobs; $('jobs').replaceChildren();
    for (const job of jobs) {
      const row = $('jobs').insertRow();
      cell(row, new Date(job.created_at).toLocaleString('id-ID')); cell(row, job.target); cell(row, `${job.execution_mode || 'GOVERNED'} / ${job.mode}`); cell(row, job.status); cell(row, `Recon: ${job.recon_status} / Enum: ${job.enum_status}`);
      const actions = cell(row, ''); action(actions, 'Detail', () => { detail(job); $('detail').scrollIntoView({behavior: 'smooth', block: 'start'}); });
      if ((job.execution_mode || 'GOVERNED') === 'GOVERNED' && ['PROPOSED','BLOCKED_CONFIGURATION'].includes(job.status)) action(actions, 'Dispatch', async () => { const result = await api(`/api/jobs/${encodeURIComponent(job.job_id)}/dispatch`, 'POST', {}); message(`Status: ${result.status}`); await refresh(); });
    }
    if (!jobs.length) empty($('jobs'), 6, 'Belum ada job.');
    if (selected) { const job = jobs.find(j => j.job_id === selected); if (job) detail(job); }
    $('intakes').replaceChildren();
    for (const item of inbox.intakes) { const row = $('intakes').insertRow(); cell(row, item.target_value || item.target_url || item.target); cell(row, `${item.mission_id} / ${item.task_id}`); cell(row, item.profile); cell(row, item.status); }
    if (!inbox.intakes.length) empty($('intakes'), 4, 'Belum ada target dari Mission.');
    $('entries').replaceChildren();
    for (const item of allowlist.entries) { const li = document.createElement('li'); li.textContent = `${item.entry} (${item.source}) `; if (item.removable) action(li, 'Hapus', async () => { await api('/api/remote-allowlist', 'DELETE', {entry: item.entry}); await refresh(); }); $('entries').append(li); }
    if (!allowlist.entries.length) { const li = document.createElement('li'); li.textContent = 'Allowlist kosong.'; $('entries').append(li); }
  } catch (e) { $('health').textContent = 'Layanan perlu diperiksa'; message(e.message); } finally { refreshing = false; }
}
$('execution').addEventListener('change', () => {
  const standalone = $('execution').value === 'STANDALONE';
  $('governed').hidden = standalone; $('standalone').hidden = !standalone;
  $('scan').elements.mission_id.required = !standalone;
  $('scan').elements.local_authorized.required = standalone;
  $('submit').textContent = standalone ? 'Jalankan scan mandiri' : 'Simpan proposal';
  $('scan-note').textContent = standalone ? 'Scan berjalan setelah konfirmasi kewenangan dicentang.' : 'Simpan proposal, kemudian kirim melalui Governance / Stage 6.';
});
$('scan').addEventListener('submit', async event => {
  event.preventDefault(); message(''); $('submit').disabled = true;
  try { const data = Object.fromEntries(new FormData(event.target)); data.local_authorized = event.target.elements.local_authorized.checked; data.remote_authorized = event.target.elements.remote_authorized.checked; const result = await api('/api/jobs', 'POST', data); message(result.note || `Status: ${result.job.status}`); await refresh(); detail(result.job); } catch (e) { message(e.message); } finally { $('submit').disabled = false; }
});
$('allowlist').addEventListener('submit', async event => { event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true; try { const result = await api('/api/remote-allowlist', 'POST', Object.fromEntries(new FormData(event.target))); message(result.message); event.target.reset(); await refresh(); } catch (e) { message(e.message); } finally { button.disabled = false; } });
$('refresh').addEventListener('click', refresh);
refresh(); setInterval(refresh, 5000);

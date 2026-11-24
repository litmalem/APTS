'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const app = $('#app');
const pageTitle = $('#pageTitle');
const globalHealth = $('#globalHealth');
const controlVersion = $('#controlVersion');
const terminalStates = new Set(['COMPLETED', 'FAILED', 'ABORTED', 'EXPIRED']);
const PHASE2_COMMANDS = ['START', 'PAUSE', 'RESUME', 'REPLAN', 'BEGIN_CLEANUP', 'ABORT'];
const COMMAND_INFO = {
  START: { label: 'Start / Return to RUNNING', tone: 'primary', description: 'Activate RUNNING from an eligible planning/waiting/replanning state.' },
  PAUSE: { label: 'Pause Mission', tone: 'secondary', description: 'Contain the mission in PAUSED while preserving canonical lineage.' },
  RESUME: { label: 'Resume Mission', tone: 'primary', description: 'Resume a PAUSED mission to a guard-approved canonical target.' },
  REPLAN: { label: 'Request Replan', tone: 'warning', description: 'Move the mission into REPLANNING through the canonical lifecycle guard.' },
  BEGIN_CLEANUP: { label: 'Begin Cleanup', tone: 'warning', description: 'Enter CLEANING_UP through the canonical lifecycle command contract.' },
  ABORT: { label: 'Abort Mission', tone: 'danger', description: 'Irreversibly terminate the mission as ABORTED.' },
};

const state = {
  route: 'dashboard',
  params: [],
  dashboard: null,
  missions: null,
  missionTab: 'overview',
  filters: { q: '', state: '', source: '', visibility: 'ACTIVE' },
  activeEventSource: null,
  liveEvents: [],
};

class ApiError extends Error {
  constructor(message, status, code, data) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]));
}
function fmtTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}
function ago(value) {
  if (!value) return '—';
  const ms = Date.now() - new Date(value).getTime();
  if (ms < 60000) return `${Math.max(0, Math.floor(ms / 1000))}s ago`;
  if (ms < 3600000) return `${Math.floor(ms / 60000)}m ago`;
  if (ms < 86400000) return `${Math.floor(ms / 3600000)}h ago`;
  return `${Math.floor(ms / 86400000)}d ago`;
}
function objectiveText(obj) {
  if (!obj) return '—';
  if (typeof obj === 'string') return obj;
  return obj.goal || obj.description || [obj.type, obj.target_ref].filter(Boolean).join(' · ') || JSON.stringify(obj);
}
function stateBadge(s) {
  return `<span class="state ${escapeHtml(s || 'UNKNOWN')}">${escapeHtml(s || 'UNKNOWN')}</span>`;
}
function jsonBlock(o) {
  return `<pre class="json">${escapeHtml(JSON.stringify(o ?? {}, null, 2))}</pre>`;
}
function info(label, value) {
  return `<div class="info"><label>${escapeHtml(label)}</label><div>${escapeHtml(value == null ? '—' : value)}</div></div>`;
}
function uuid() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}
function parseEvidenceRefs(text) {
  return String(text || '').split(/[\n,]+/).map(v => v.trim()).filter(Boolean).filter((v, i, a) => a.indexOf(v) === i);
}

function stopLiveStream() {
  if (state.activeEventSource) {
    try { state.activeEventSource.close(); } catch (_) {}
    state.activeEventSource = null;
  }
}

async function requestJson(path, { optional = false, method = 'GET', body = undefined, extraHeaders = {} } = {}) {
  try {
    const headers = { Accept: 'application/json', ...extraHeaders };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const res = await fetch(path, {
      method,
      headers,
      cache: 'no-store',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (optional && (res.status === 404 || res.status === 409)) return null;
      throw new ApiError(data.message || data.detail || data.code || `${res.status} ${res.statusText}`, res.status, data.code, data);
    }
    return data;
  } catch (err) {
    if (optional && !(err instanceof ApiError)) return null;
    throw err;
  }
}
const api = (path, optional = false) => requestJson(path, { optional });
const apiPost = (path, body) => requestJson(path, { method: 'POST', body });
function archiveDetailsDialog(mid, operation = 'archive') {
  const restoring = operation === 'restore';
  const title = restoring ? 'Restore Mission' : 'Archive Mission';
  const description = restoring
    ? `This restores <strong>${escapeHtml(mid)}</strong> to active mission lists. Its lifecycle state, lineage, and evidence remain unchanged.`
    : `This archives <strong>${escapeHtml(mid)}</strong> from active lists. It will not delete lineage, evidence, or change the canonical lifecycle state.`;
  return new Promise(resolve => {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = `
      <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="archiveDialogTitle">
        <div class="modal-head"><div><div class="eyebrow">ADMINISTRATIVE VISIBILITY</div><h2 id="archiveDialogTitle">${title}</h2></div><button type="button" class="modal-close" id="archiveDialogClose" aria-label="Close">×</button></div>
        <form id="archiveForm">
          <div class="modal-body">
            <p class="modal-description">${description}</p>
            <label class="form-label" for="archiveReason">Audit reason (at least 8 characters)</label>
            <textarea id="archiveReason" class="form-input" rows="3" maxlength="1000" required placeholder="${restoring ? 'Why should this mission return to active lists?' : 'Why should this terminal mission be archived?'}"></textarea>
            <label class="form-label" for="archiveToken">Administrative mission token</label>
            <input id="archiveToken" type="password" class="form-input" autocomplete="off" required placeholder="MISSION_ARCHIVE_ADMIN_TOKEN" />
            <p class="form-help">The token is sent only to the local Mission API and is not stored in browser storage.</p>
            <p id="archiveDialogError" class="command-error" style="display:none"></p>
          </div>
          <div class="modal-actions"><button type="button" class="action-button secondary" id="archiveDialogCancel">Cancel</button><button type="submit" class="action-button ${restoring ? 'primary' : 'warning'}">${title}</button></div>
        </form>
      </div>`;
    document.body.appendChild(modal);
    const reasonEl = $('#archiveReason', modal);
    const tokenEl = $('#archiveToken', modal);
    const dismiss = payload => { tokenEl.value = ''; modal.remove(); resolve(payload); };
    $('#archiveDialogClose', modal).addEventListener('click', () => dismiss(null));
    $('#archiveDialogCancel', modal).addEventListener('click', () => dismiss(null));
    $('#archiveForm', modal).addEventListener('submit', event => {
      event.preventDefault();
      const reason = reasonEl.value.trim();
      const token = tokenEl.value;
      if (reason.length < 8 || !token) {
        const err = $('#archiveDialogError', modal);
        err.textContent = 'Please enter a reason of at least 8 characters and the archive token.';
        err.style.display = 'block';
        return;
      }
      dismiss({ reason, token });
    });
    reasonEl.focus();
  });
}
async function archiveMission(mid, version) {
  const details = await archiveDetailsDialog(mid, 'archive');
  if (!details) return;
  try {
    const result = await requestJson(`/api/missions/${encodeURIComponent(mid)}/archive`, {
      method: 'POST',
      extraHeaders: { 'X-Mission-Archive-Token': details.token },
      body: { expected_state_version: Number(version), reason: details.reason, idempotency_key: uuid() },
    });
    toast(`Mission archived: ${result.mission_id}`, 'success');
    state.dashboard = null;
    if (state.route === 'mission') location.hash = '#missions';
    else renderCurrent();
  } catch (e) { toast(e.message || String(e), 'error', 7500); }
}
async function restoreMission(mid, version) {
  const details = await archiveDetailsDialog(mid, 'restore');
  if (!details) return;
  try {
    const result = await requestJson(`/api/missions/${encodeURIComponent(mid)}/restore`, {
      method: 'POST',
      extraHeaders: { 'X-Mission-Archive-Token': details.token },
      body: { expected_state_version: Number(version), reason: details.reason, idempotency_key: uuid() },
    });
    toast(`Mission restored: ${result.mission_id}`, 'success');
    state.dashboard = null;
    if (state.route === 'mission') location.hash = '#missions';
    else renderCurrent();
  } catch (e) { toast(e.message || String(e), 'error', 7500); }
}
function bindArchiveActions() {
  $$('.archive-mission').forEach(btn => btn.addEventListener('click', event => {
    event.preventDefault(); event.stopPropagation();
    archiveMission(btn.dataset.mid, btn.dataset.version);
  }));
  $$('.restore-mission').forEach(btn => btn.addEventListener('click', event => {
    event.preventDefault(); event.stopPropagation();
    restoreMission(btn.dataset.mid, btn.dataset.version);
  }));
}


function toast(message, tone = 'info', timeout = 4800) {
  const existing = $('#missionToast');
  if (existing) existing.remove();
  const node = document.createElement('div');
  node.id = 'missionToast';
  node.className = `toast ${tone}`;
  node.textContent = message;
  document.body.appendChild(node);
  requestAnimationFrame(() => node.classList.add('show'));
  setTimeout(() => {
    node.classList.remove('show');
    setTimeout(() => node.remove(), 250);
  }, timeout);
}

function setNav(route) {
  $$('#nav a').forEach(a => a.classList.toggle('active', a.dataset.route === route));
}
function parseRoute() {
  stopLiveStream();
  const raw = (location.hash || '#dashboard').slice(1).split('/').filter(Boolean);
  state.route = raw[0] || 'dashboard';
  state.params = raw.slice(1);
  setNav(state.route === 'mission' ? 'missions' : state.route);
  renderCurrent();
}

async function refreshGlobalHealth() {
  try {
    const h = await api('/health');
    globalHealth.className = 'health-pill good';
    globalHealth.innerHTML = '<span class="dot"></span><span>ORCHESTRATOR HEALTHY</span>';
    controlVersion.textContent = h.control_version || h.stage_control_version || 'stage3.9.10';
  } catch (e) {
    globalHealth.className = 'health-pill bad';
    globalHealth.innerHTML = '<span class="dot"></span><span>ORCHESTRATOR UNAVAILABLE</span>';
  }
}
function renderError(err) {
  app.innerHTML = `<div class="error-box"><strong>Console request failed.</strong><br>${escapeHtml(err.message || String(err))}</div>`;
}

async function renderDashboard() {
  pageTitle.textContent = 'Mission Operations Dashboard';
  app.innerHTML = '<div class="loading-card">Loading authoritative mission read-models…</div>';
  try {
    const [summary, missions, attention] = await Promise.all([
      api('/api/dashboard/summary'),
      api('/api/missions?visibility=ACTIVE&limit=12'),
      api('/api/operator/attention?limit=10'),
    ]);
    state.dashboard = summary;
    const c = summary.mission_counts || {};
    const by = c.by_state || {};
    const att = summary.attention || {};
    const kpis = [
      ['TOTAL', c.total || 0, `${c.archived || 0} archived · ${c.historical_total || c.total || 0} historical`, 'accent'],
      ['RUNNING', by.RUNNING || 0, 'currently executing', 'good'],
      ['PLANNING', by.PLANNING || 0, 'building or validating plan', 'accent'],
      ['WAITING', (att.waiting_approval || 0) + (att.waiting_evidence || 0), 'approval / evidence', 'warn'],
      ['REPLANNING', by.REPLANNING || 0, 'adaptive replans', 'warn'],
      ['FAILED', by.FAILED || 0, 'terminal failures', 'danger'],
    ];
    app.innerHTML = `
      <div class="grid kpis">${kpis.map(([l, v, s, cl]) => `<div class="kpi ${cl}"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${s}</div></div>`).join('')}</div>
      <div class="two-col">
        <div class="panel flush"><div class="panel-head"><div><div class="panel-title">MISSION ACTIVITY</div><div class="panel-sub">Newest authoritative missions</div></div><a class="back-link" href="#missions">View all →</a></div><div class="panel-body">${missionTable(missions.missions || [])}</div></div>
        <div class="panel"><div class="panel-head"><div><div class="panel-title">REQUIRES ATTENTION</div><div class="panel-sub">Operator queue</div></div></div><div class="panel-body">${attentionList(attention.items || [])}</div></div>
      </div>
      <div class="spacer"></div>
      <div class="two-col">
        <div class="panel"><div class="panel-head"><div><div class="panel-title">MISSION STATE DISTRIBUTION</div><div class="panel-sub">Current canonical state projection</div></div></div><div class="panel-body">${stateBars(by, c.total || 1)}</div></div>
        <div class="panel"><div class="panel-head"><div><div class="panel-title">SOURCE SYSTEMS</div><div class="panel-sub">Operational and acceptance sources stay distinguishable</div></div></div><div class="panel-body">${sourceBars(summary.source_counts || {})}</div></div>
      </div>`;
    bindMissionRows();
    bindArchiveActions();
  } catch (e) {
    renderError(e);
  }
}

function missionTable(items) {
  if (!items.length) return '<div class="empty-state"><h3>No missions</h3><p>No matching missions were found.</p></div>';
  return `<div class="table-wrap"><table><thead><tr><th>MISSION ID</th><th>OBJECTIVE</th><th>STATE</th><th>PLAN</th><th>TASKS</th><th>SOURCE</th><th>LAST EVENT</th><th>ACTION</th></tr></thead><tbody>${items.map(m => `<tr class="clickable mission-row" data-mid="${escapeHtml(m.mission_id)}"><td><div class="mission-id">${escapeHtml(m.mission_id)}</div></td><td><div class="objective">${escapeHtml(objectiveText(m.objective))}</div></td><td>${stateBadge(m.state)}${m.archived ? ' <span class="badge amber">ARCHIVED</span>' : ''}</td><td>${m.active_plan_version == null ? '—' : `v${m.active_plan_version}`}</td><td>${m.completed_task_count ? `${m.completed_task_count}/${m.planned_task_count || 0}` : (m.planned_task_count || 0)}</td><td>${escapeHtml(m.source_system || '—')}</td><td>${escapeHtml(m.latest_event?.event_type || '—')}<div class="muted tiny">${ago(m.latest_event?.occurred_at)}</div></td><td>${m.archived ? `<button class="action-button primary restore-mission" data-mid="${escapeHtml(m.mission_id)}" data-version="${m.state_version}">Restore</button>` : (terminalStates.has(m.state) ? `<button class="action-button secondary archive-mission" data-mid="${escapeHtml(m.mission_id)}" data-version="${m.state_version}">Archive</button>` : '<span class="muted tiny">—</span>')}</td></tr>`).join('')}</tbody></table></div>`;
}
function bindMissionRows() {
  $$('.mission-row').forEach(row => row.addEventListener('click', e => {
    if (e.target.closest('.archive-mission, .restore-mission')) return;
    state.missionTab = 'overview';
    location.hash = `#mission/${encodeURIComponent(row.dataset.mid)}`;
  }));
}
function attentionList(items) {
  if (!items.length) return '<div class="muted tiny">No missions currently require operator attention.</div>';
  return `<div class="attention-list">${items.map(m => `<div class="attention-item"><div class="row">${stateBadge(m.attention_reason)}<span class="tiny muted">${ago(m.updated_at)}</span></div><div class="mid"><a href="#mission/${encodeURIComponent(m.mission_id)}">${escapeHtml(m.mission_id)}</a></div></div>`).join('')}</div>`;
}
function stateBars(by, total) {
  const entries = Object.entries(by).sort((a, b) => b[1] - a[1]);
  return `<div class="source-bars">${entries.map(([k, v]) => `<div class="source-row"><span>${stateBadge(k)}</span><div class="bar"><i style="width:${Math.round(v / Math.max(1, total) * 100)}%"></i></div><b>${v}</b></div>`).join('')}</div>`;
}
function sourceBars(src) {
  const entries = Object.entries(src).slice(0, 10);
  const max = Math.max(1, ...entries.map(x => x[1]));
  return `<div class="source-bars">${entries.map(([k, v]) => `<div class="source-row"><span class="mono tiny">${escapeHtml(k)}</span><div class="bar"><i style="width:${Math.round(v / max * 100)}%"></i></div><b>${v}</b></div>`).join('')}</div>`;
}

async function renderMissions() {
  pageTitle.textContent = 'Missions';
  app.innerHTML = '<div class="loading-card">Loading mission registry…</div>';
  try {
    const summary = state.dashboard || await api('/api/dashboard/summary');
    const params = new URLSearchParams({ limit: '100' });
    if (state.filters.q) params.set('q', state.filters.q);
    if (state.filters.state) params.set('state', state.filters.state);
    if (state.filters.source) params.set('source_system', state.filters.source);
    params.set('visibility', state.filters.visibility);
    const data = await api('/api/missions?' + params.toString());
    state.missions = data;
    const states = Object.keys(summary.mission_counts?.by_state || {}).sort();
    const sources = Object.keys(summary.source_counts || {}).sort();
    app.innerHTML = `<div class="filters"><select id="visibilityFilter" aria-label="Archive visibility"><option value="ACTIVE" ${state.filters.visibility === 'ACTIVE' ? 'selected' : ''}>Active missions</option><option value="ARCHIVED" ${state.filters.visibility === 'ARCHIVED' ? 'selected' : ''}>Archived missions</option><option value="ALL" ${state.filters.visibility === 'ALL' ? 'selected' : ''}>All missions</option></select><input id="missionSearch" placeholder="Search mission ID, objective, source…" value="${escapeHtml(state.filters.q)}"><select id="stateFilter"><option value="">All states</option>${states.map(s => `<option ${s === state.filters.state ? 'selected' : ''}>${s}</option>`).join('')}</select><select id="sourceFilter"><option value="">All sources</option>${sources.map(s => `<option ${s === state.filters.source ? 'selected' : ''}>${escapeHtml(s)}</option>`).join('')}</select><span class="count">${data.mission_count} missions</span></div><div class="panel flush"><div class="panel-head"><div><div class="panel-title">GLOBAL MISSION REGISTRY</div><div class="panel-sub">Canonical identity + state + plan projection</div></div><span class="badge cyan">PHASE 2</span></div><div class="panel-body">${missionTable(data.missions || [])}</div></div>`;
    let timer;
    $('#missionSearch').addEventListener('input', e => {
      clearTimeout(timer);
      timer = setTimeout(() => { state.filters.q = e.target.value.trim(); renderMissions(); }, 260);
    });
    $('#visibilityFilter').addEventListener('change', e => { state.filters.visibility = e.target.value; renderMissions(); });
    $('#stateFilter').addEventListener('change', e => { state.filters.state = e.target.value; renderMissions(); });
    $('#sourceFilter').addEventListener('change', e => { state.filters.source = e.target.value; renderMissions(); });
    bindMissionRows();
    bindArchiveActions();
  } catch (e) {
    renderError(e);
  }
}

async function renderMission(mid) {
  pageTitle.textContent = 'Mission Workspace';
  app.innerHTML = '<div class="loading-card">Reconstructing mission read-model and operator controls…</div>';
  const enc = encodeURIComponent(mid);
  try {
    const endpoints = {
      mission: `/api/missions/${enc}`,
      archive: `/api/missions/${enc}/archive`,
      envelope: `/api/missions/${enc}/envelope`,
      state: `/api/missions/${enc}/state`,
      plans: `/api/missions/${enc}/plan-versions`,
      tasks: `/api/missions/${enc}/planned-tasks`,
      graph: `/api/missions/${enc}/task-dependency-graph`,
      timeline: `/api/missions/${enc}/observability-timeline`,
      diagnostics: `/api/missions/${enc}/observability-diagnostics`,
      metrics: `/api/missions/${enc}/observability-metrics-health`,
      versionVector: `/api/missions/${enc}/version-vector`,
      lifecycleContract: `/api/missions/${enc}/lifecycle-command-contract`,
      commands: `/api/missions/${enc}/commands`,
    };
    const keys = Object.keys(endpoints);
    const results = await Promise.all(keys.map(k => api(endpoints[k], true)));
    const d = Object.fromEntries(keys.map((k, i) => [k, results[i]]));
    if (!d.mission) throw new Error('Mission not found');

    const m = d.mission.mission || {};
    const env = d.envelope?.envelope || {};
    const st = d.state?.mission_state || {};
    const report = d.metrics?.report || {};
    const health = report.observability_health?.status || 'UNAVAILABLE';
    const diag = d.diagnostics?.diagnostics || {};
    const terminal = terminalStates.has(st.state);
    const archived = !!d.archive?.archive?.archived;
    app.innerHTML = `<a class="back-link" href="#missions">← Back to missions</a><div class="mission-head"><div><h2>${escapeHtml(env.mission?.mission_kind || 'GLOBAL MISSION')}</h2><div class="id">${escapeHtml(mid)}</div><div class="head-meta" style="margin-top:11px">${stateBadge(st.state)}<span class="badge">state v${st.state_version ?? '—'}</span><span class="badge cyan">plan ${d.plans?.active_head?.active_plan_version ? `v${d.plans.active_head.active_plan_version}` : '—'}</span><span class="badge ${health === 'HEALTHY' ? 'green' : 'amber'}">OBS ${escapeHtml(health)}</span><span class="badge ${diag.status === 'PASS' ? 'green' : 'amber'}">INTEGRITY ${escapeHtml(diag.status || 'N/A')}</span></div></div><div class="readonly-note ${terminal ? 'terminal-note' : 'interactive-note'}">${archived ? `<span>ARCHIVED · READ ONLY</span><button class="action-button primary restore-mission" data-mid="${escapeHtml(mid)}" data-version="${st.state_version}">Restore Mission</button>` : (terminal ? 'TERMINAL · READ ONLY' : 'PHASE 3 · ADVANCED OPERATIONS')}${terminal && !archived ? `<button class="action-button secondary archive-mission" data-mid="${escapeHtml(mid)}" data-version="${st.state_version}">Archive Mission</button>` : ''}</div></div>
      <div class="tabs">
        <button class="tab" data-tab="overview">Overview</button>
        <button class="tab" data-tab="controls">Controls</button>
        <button class="tab" data-tab="governance">Governance</button>
        <button class="tab" data-tab="plan">Plan & Tasks</button>
        <button class="tab" data-tab="live">Live Events</button>
        <button class="tab" data-tab="timeline">Timeline</button>
        <button class="tab" data-tab="causal">Causal Graph</button>
        <button class="tab" data-tab="evidence">Evidence</button>
        <button class="tab" data-tab="forensics">Forensics</button>
        <button class="tab" data-tab="diagnostics">Diagnostics</button>
        <button class="tab" data-tab="raw">Raw Read-Model</button>
      </div><div id="missionTab"></div>`;

    bindArchiveActions();
    const ctx = { mid, m, env, st, ...d, governanceVisibility: undefined };
    const show = async name => {
      stopLiveStream();
      state.missionTab = name;
      $$('.tab').forEach(x => x.classList.toggle('active', x.dataset.tab === name));
      const host = $('#missionTab');
      if (name === 'governance') {
        host.innerHTML = '<div class="loading-card">Reading Mission ↔ aptsGSS governance visibility…</div>';
        if (ctx.governanceVisibility === undefined) {
          ctx.governanceVisibility = await api(`/api/missions/${enc}/governance-visibility`, true);
        }
        host.innerHTML = governanceTab(ctx);
        return;
      }
      if (name === 'plan') {
        host.innerHTML = planTab(ctx);
        await bindPlanDiff(ctx);
        return;
      }
      if (name === 'live') {
        host.innerHTML = liveEventsTab(ctx);
        startLiveEvents(ctx);
        return;
      }
      if (name === 'causal') {
        host.innerHTML = '<div class="loading-card">Building deterministic causal graph…</div>';
        const causal = await api(`/api/missions/${enc}/observability-causal-graph`, true);
        host.innerHTML = causalGraphTab(causal);
        bindCausalGraph(causal);
        return;
      }
      if (name === 'evidence') {
        host.innerHTML = '<div class="loading-card">Loading forensic evidence index…</div>';
        const evidence = await api(`/api/missions/${enc}/evidence-browser?limit=500`, true);
        host.innerHTML = evidenceTab(evidence);
        bindEvidenceBrowser(evidence);
        return;
      }
      if (name === 'forensics') {
        host.innerHTML = '<div class="loading-card">Reconstructing mission from immutable evidence…</div>';
        const [reconstruction, bundle] = await Promise.all([
          api(`/api/missions/${enc}/forensic-reconstruction`, true),
          api(`/api/missions/${enc}/forensic-evidence-bundle`, true),
        ]);
        host.innerHTML = forensicsTab(reconstruction, bundle);
        return;
      }
      host.innerHTML = missionTab(name, ctx);
      if (name === 'controls') bindControls(ctx);
    };
    $$('.tab').forEach(b => b.addEventListener('click', () => show(b.dataset.tab).catch(renderError)));
    const allowedTabs = new Set(['overview', 'controls', 'governance', 'plan', 'live', 'timeline', 'causal', 'evidence', 'forensics', 'diagnostics', 'raw']);
    await show(allowedTabs.has(state.missionTab) ? state.missionTab : 'overview');
  } catch (e) {
    renderError(e);
  }
}

function lifecycleHtml(st) {
  const current = st.state || 'CREATED';
  const base = ['CREATED', 'PIP_BOUND', 'PLANNING', 'RUNNING', 'CLEANING_UP', 'COMPLETED'];
  const branch = new Set(['WAITING_EVIDENCE', 'WAITING_APPROVAL', 'REPLANNING', 'PAUSED']);
  let seq = [...base];
  if (branch.has(current)) seq = ['CREATED', 'PIP_BOUND', 'PLANNING', 'RUNNING', current, 'CLEANING_UP', 'COMPLETED'];
  if (['FAILED', 'ABORTED', 'EXPIRED'].includes(current)) seq = ['CREATED', 'PIP_BOUND', 'PLANNING', 'RUNNING', current];
  const currentIdx = seq.indexOf(current);
  return `<div class="lifecycle">${seq.map((s, i) => `<div class="life-step ${s === current ? 'current' : (i < currentIdx ? 'done' : '')}"><div class="life-dot"></div><div class="life-name">${s}</div>${s === current ? `<div class="life-version">v${st.state_version ?? '—'}</div>` : ''}</div>`).join('')}</div>`;
}

function missionTab(name, c) {
  if (name === 'overview') {
    const mm = c.env.mission || {};
    const b = mm.budgets || {};
    const bind = c.env.bindings || {};
    return `<div class="panel"><div class="panel-head"><div><div class="panel-title">LIFECYCLE</div><div class="panel-sub">Canonical mission state machine projection</div></div></div><div class="panel-body">${lifecycleHtml(c.st)}</div></div><div class="spacer"></div><div class="two-col"><div class="panel"><div class="panel-head"><div class="panel-title">MISSION CONTRACT</div></div><div class="panel-body"><div class="info-grid">${info('Objective', objectiveText(mm.objective))}${info('Mission Kind', mm.mission_kind)}${info('Required Subsystems', (mm.required_subsystems || []).join(', '))}${info('Risk Ceiling', b.risk_ceiling)}${info('Action Budget', b.max_actions)}${info('Time Budget', b.time_seconds ? `${b.time_seconds} sec` : '—')}</div><div class="spacer"></div><div class="panel-sub">Success criteria</div>${jsonBlock(mm.success_criteria || [])}</div></div><div class="panel"><div class="panel-head"><div class="panel-title">BINDINGS & PROVENANCE</div></div><div class="panel-body"><div class="info-grid" style="grid-template-columns:1fr">${info('Source System', c.m.source_system)}${info('Created By', c.m.created_by)}${info('Created At', fmtTime(c.m.created_at))}${info('PIP', bind.pip?.pip_id)}${info('Scope Contract', bind.scope?.scope_contract_id)}${info('Governance Authority', bind.governance?.authority)}</div></div></div></div>`;
  }
  if (name === 'controls') return controlsTab(c);
  if (name === 'plan') return planTab(c);
  if (name === 'timeline') return timelineTab(c);
  if (name === 'diagnostics') return diagnosticsTab(c);
  return `<div class="two-col"><div class="panel"><div class="panel-head"><div class="panel-title">MISSION</div></div><div class="panel-body">${jsonBlock(c.mission)}</div></div><div class="panel"><div class="panel-head"><div class="panel-title">ENVELOPE</div></div><div class="panel-body">${jsonBlock(c.envelope)}</div></div></div>`;
}

function controlsTab(c) {
  const st = c.st || {};
  const lc = c.lifecycleContract || {};
  const eligible = new Set(lc.guard_eligible_commands || []);
  const resumeTargets = lc.guard_eligible_resume_targets || [];
  const vv = c.versionVector || {};
  const vectorComplete = vv.version_vector_complete === true;
  const terminal = terminalStates.has(st.state);
  const actor = localStorage.getItem('aptsMissionOperatorActor') || 'mission-web-operator';
  const available = PHASE2_COMMANDS.filter(cmd => eligible.has(cmd));
  const commandRows = (c.commands?.commands || []).filter(x => x.operation === 'LIFECYCLE_COMMAND').slice(-12).reverse();

  const commandButtons = PHASE2_COMMANDS.map(cmd => {
    const meta = COMMAND_INFO[cmd];
    const enabled = !terminal && vectorComplete && eligible.has(cmd);
    const extra = cmd === 'RESUME' && enabled ? `<div class="control-target tiny">Targets: ${resumeTargets.map(escapeHtml).join(', ') || '—'}</div>` : '';
    return `<button class="control-action ${meta.tone}" data-command="${cmd}" ${enabled ? '' : 'disabled'}><span>${escapeHtml(meta.label)}</span><small>${escapeHtml(meta.description)}</small>${extra}</button>`;
  }).join('');

  return `<div class="phase2-callout"><div><strong>Human Interaction is guarded, not authoritative.</strong><span>Every mutation goes through the existing canonical lifecycle command endpoint with state-version + mission-version-vector guards. No command is automatically retried.</span></div><span class="badge amber">aptsGSS remains authorization authority</span></div>
    <div class="two-col controls-layout">
      <div class="panel"><div class="panel-head"><div><div class="panel-title">MISSION CONTROLS</div><div class="panel-sub">Only the bounded Phase-2 command set is exposed</div></div><span class="badge ${vectorComplete ? 'green' : 'red'}">VECTOR ${vectorComplete ? 'COMPLETE' : 'INCOMPLETE'}</span></div><div class="panel-body"><div class="control-grid">${commandButtons}</div>${available.length ? '' : '<div class="empty-state compact"><h3>No Phase-2 operator command is currently eligible</h3><p>The canonical state/guard contract does not permit Start, Pause, Resume, Replan, Cleanup, or Abort from this projection.</p></div>'}</div></div>
      <div class="panel"><div class="panel-head"><div><div class="panel-title">OPERATOR CONTEXT</div><div class="panel-sub">Audit attribution for lifecycle commands</div></div></div><div class="panel-body"><label class="form-label" for="operatorActor">Actor ID</label><input id="operatorActor" class="form-input" maxlength="128" value="${escapeHtml(actor)}"><div class="form-help">Saved locally in this browser. This value is attribution metadata; it is not authentication and cannot grant Governance approval.</div><div class="spacer"></div><div class="info-grid" style="grid-template-columns:1fr">${info('Current State', `${st.state || '—'} · v${st.state_version ?? '—'}`)}${info('Version SHA-256', vv.version_sha256 || '—')}${info('Governance Authority', lc.governance_authorization_authority || 'EXTERNAL_APTS_GSS')}</div></div></div>
    </div>
    <div class="spacer"></div>
    <div class="panel"><div class="panel-head"><div><div class="panel-title">LIFECYCLE COMMAND JOURNAL</div><div class="panel-sub">Latest canonical guarded mutations</div></div><span class="badge cyan">${commandRows.length} shown</span></div><div class="panel-body">${commandHistory(commandRows)}</div></div>`;
}

function commandHistory(rows) {
  if (!rows.length) return '<div class="muted tiny">No lifecycle commands have been journaled for this mission.</div>';
  return `<div class="table-wrap"><table class="compact-table"><thead><tr><th>COMMAND</th><th>STATUS</th><th>ACTOR</th><th>STATE CHANGE</th><th>UPDATED</th></tr></thead><tbody>${rows.map(row => {
    const result = row.result || {};
    const tr = result.transition || {};
    const cmd = row.metadata?.lifecycle_command || result.lifecycle_guard?.command || 'LIFECYCLE_COMMAND';
    return `<tr><td><span class="mono">${escapeHtml(cmd)}</span></td><td><span class="badge ${row.command_status === 'COMPLETED' ? 'green' : 'amber'}">${escapeHtml(row.command_status || row.status || '—')}</span></td><td>${escapeHtml(row.submitted_by || '—')}</td><td>${escapeHtml(tr.from_state || '—')} → ${escapeHtml(tr.to_state || '—')}</td><td>${fmtTime(row.updated_at)}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}

function bindControls(c) {
  const actor = $('#operatorActor');
  if (actor) actor.addEventListener('change', () => {
    const value = actor.value.trim();
    if (value) localStorage.setItem('aptsMissionOperatorActor', value);
  });
  $$('.control-action[data-command]').forEach(button => {
    button.addEventListener('click', () => openControlModal(c, button.dataset.command));
  });
}

function openControlModal(c, command) {
  const meta = COMMAND_INFO[command];
  if (!meta) return;
  const actor = (localStorage.getItem('aptsMissionOperatorActor') || $('#operatorActor')?.value || 'mission-web-operator').trim();
  const lc = c.lifecycleContract || {};
  const resumeTargets = lc.guard_eligible_resume_targets || [];
  const snapshotStateVersion = Number(c.st?.state_version || 0);
  const snapshotVectorHash = c.versionVector?.version_sha256 || '';
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  const resumeHtml = command === 'RESUME' ? `<label class="form-label" for="cmdTarget">Resume target</label><select id="cmdTarget" class="form-input">${resumeTargets.map(x => `<option>${escapeHtml(x)}</option>`).join('')}</select>` : '';
  const waitingReturn = command === 'START' && ['WAITING_EVIDENCE', 'WAITING_APPROVAL'].includes(c.st?.state);
  const replanningReturn = command === 'START' && c.st?.state === 'REPLANNING';
  const activeDependency = lc.waiting_dependency?.active_dependency || {};
  const requestSpecificHtml = waitingReturn
    ? `<div class="request-specific-note"><strong>Waiting dependency resolution required.</strong><br>Dependency: <code>${escapeHtml(activeDependency.dependency_id || 'UNAVAILABLE')}</code> · kind ${escapeHtml(activeDependency.kind || '—')}<br>The console will submit <code>metadata.dependency_resolution.status=SATISFIED</code> and bind the Actor ID as <code>resolved_by</code>. At least one evidence ref is required.</div>`
    : (replanningReturn ? `<div class="request-specific-note"><strong>Replan readiness evidence required.</strong><br>At least one evidence ref must be supplied before returning the mission to RUNNING.</div>` : '');
  const evidenceRequirement = waitingReturn || replanningReturn ? 'required' : 'optional';
  const abortHtml = command === 'ABORT' ? `<div class="danger-confirm"><strong>Terminal action.</strong> ABORT is irreversible for the canonical mission state. Type <code>ABORT</code> to continue.</div><label class="form-label" for="dangerText">Confirmation</label><input id="dangerText" class="form-input" autocomplete="off" placeholder="ABORT">` : '';
  overlay.innerHTML = `<div class="modal-card" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="eyebrow">PHASE 2 · HUMAN INTERACTION</div><h2>${escapeHtml(meta.label)}</h2></div><button class="modal-close" aria-label="Close">×</button></div><div class="modal-body"><div class="command-summary"><span>${stateBadge(c.st?.state)}</span><span class="mono">state v${snapshotStateVersion}</span><span class="mono hash-chip">${escapeHtml(snapshotVectorHash.slice(0, 16))}…</span></div><p class="modal-description">${escapeHtml(meta.description)}</p>${requestSpecificHtml}<label class="form-label" for="cmdActor">Actor ID</label><input id="cmdActor" class="form-input" maxlength="128" value="${escapeHtml(actor)}"><label class="form-label" for="cmdReasonCode">Reason code</label><input id="cmdReasonCode" class="form-input" maxlength="80" value="UI_${command}"><label class="form-label" for="cmdReason">Reason</label><textarea id="cmdReason" class="form-input" rows="4" maxlength="2000" placeholder="Explain why the operator is issuing this lifecycle command."></textarea><label class="form-label" for="cmdEvidence">Evidence refs <span class="muted">(${evidenceRequirement}, comma or line separated)</span></label><textarea id="cmdEvidence" class="form-input" rows="2" placeholder="evidence:..."></textarea>${resumeHtml}${abortHtml}<div id="commandError" class="command-error" hidden></div><div class="preflight-note"><strong>Preflight:</strong> the console re-reads state, lifecycle eligibility, and the mission version vector immediately before submission. A stale view is rejected and never auto-retried.</div></div><div class="modal-actions"><button class="ghost-button modal-cancel">Cancel</button><button id="submitCommand" class="action-button ${meta.tone}">Confirm ${escapeHtml(meta.label)}</button></div></div>`;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  $('.modal-close', overlay).addEventListener('click', close);
  $('.modal-cancel', overlay).addEventListener('click', close);
  overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
  $('#submitCommand', overlay).addEventListener('click', async () => {
    const errorBox = $('#commandError', overlay);
    const submit = $('#submitCommand', overlay);
    const actorValue = $('#cmdActor', overlay).value.trim();
    const reasonCode = $('#cmdReasonCode', overlay).value.trim().toUpperCase();
    const reason = $('#cmdReason', overlay).value.trim();
    const evidenceRefs = parseEvidenceRefs($('#cmdEvidence', overlay).value);
    const target = command === 'RESUME' ? $('#cmdTarget', overlay)?.value : undefined;
    if (!actorValue || !reasonCode || !reason) {
      errorBox.hidden = false;
      errorBox.textContent = 'Actor ID, reason code, and reason are required by the Phase-2 operator UI.';
      return;
    }
    if ((waitingReturn || replanningReturn) && evidenceRefs.length === 0) {
      errorBox.hidden = false;
      errorBox.textContent = 'At least one evidence ref is required to return from a waiting or replanning state.';
      return;
    }
    if (waitingReturn && !activeDependency.dependency_id) {
      errorBox.hidden = false;
      errorBox.textContent = 'The active waiting dependency could not be resolved from the canonical lifecycle contract.';
      return;
    }
    if (command === 'ABORT' && $('#dangerText', overlay).value.trim() !== 'ABORT') {
      errorBox.hidden = false;
      errorBox.textContent = 'Type ABORT exactly to confirm the terminal action.';
      return;
    }

    submit.disabled = true;
    submit.textContent = 'Running preflight…';
    errorBox.hidden = true;
    try {
      const enc = encodeURIComponent(c.mid);
      const [freshState, freshVector, freshContract] = await Promise.all([
        api(`/api/missions/${enc}/state`),
        api(`/api/missions/${enc}/version-vector`),
        api(`/api/missions/${enc}/lifecycle-command-contract`),
      ]);
      const currentState = freshState.mission_state || {};
      const eligible = new Set(freshContract.guard_eligible_commands || []);
      const sameState = Number(currentState.state_version) === snapshotStateVersion;
      const sameVector = freshVector.version_sha256 === snapshotVectorHash;
      const resumeOkay = command !== 'RESUME' || (freshContract.guard_eligible_resume_targets || []).includes(target);
      if (!sameState || !sameVector || !eligible.has(command) || !resumeOkay || freshVector.version_vector_complete !== true) {
        throw new ApiError('Mission changed or the command is no longer eligible. No mutation was submitted. Close this dialog and refresh the Mission Workspace.', 409, 'MISSION_UI_PREFLIGHT_CONFLICT', {});
      }

      submit.textContent = 'Submitting guarded command…';
      const commandId = `ui-${command.toLowerCase().replaceAll('_', '-')}-${uuid()}`;
      const payload = {
        command_id: commandId,
        idempotency_key: commandId,
        command,
        expected_version_sha256: freshVector.version_sha256,
        expected_state_version: Number(currentState.state_version),
        actor: actorValue,
        reason_code: reasonCode,
        reason,
        evidence_refs: evidenceRefs,
        metadata: {
          source: 'MISSION_WEB_PHASE2',
          interaction_mode: 'HUMAN_OPERATOR',
          console_route: `/ui/#mission/${c.mid}`,
          submitted_at: new Date().toISOString(),
        },
      };
      if (waitingReturn) {
        payload.metadata.dependency_resolution = {
          dependency_id: activeDependency.dependency_id,
          status: 'SATISFIED',
          resolved_by: actorValue,
        };
      }
      if (command === 'RESUME') payload.target_state = target;
      localStorage.setItem('aptsMissionOperatorActor', actorValue);
      const result = await apiPost(`/api/missions/${enc}/lifecycle/commands`, payload);
      close();
      toast(`${command} committed: ${result.transition?.from_state || c.st.state} → ${result.transition?.to_state || result.resolved_target_state || 'updated'}`, 'success');
      state.missionTab = 'controls';
      await renderMission(c.mid);
    } catch (err) {
      submit.disabled = false;
      submit.textContent = `Confirm ${meta.label}`;
      errorBox.hidden = false;
      if (err instanceof ApiError && err.status === 409) {
        errorBox.innerHTML = `<strong>Version / lifecycle conflict.</strong><br>${escapeHtml(err.message)}<br><span class="tiny">The console did not retry the mutation.</span>`;
      } else {
        errorBox.textContent = err.message || String(err);
      }
    }
  });
}

function governanceTab(c) {
  const g = c.governanceVisibility;
  if (!g) return '<div class="error-box"><strong>Governance visibility unavailable.</strong><br>The Mission console could not materialize the read-only Governance projection.</div>';
  const local = g.local || {};
  const ext = g.external_authority || {};
  const snapshot = ext.correlation_snapshot || {};
  const requests = snapshot.authorization_requests || [];
  const decisions = snapshot.policy_decisions || [];
  const requestById = Object.fromEntries(requests.map(x => [x.request_id, x]));
  const approvals = ext.approval_requests || [];
  const binding = local.current_governance_binding;
  const extTone = ext.status === 'AVAILABLE' ? 'green' : 'amber';
  return `<div class="phase2-callout governance-callout"><div><strong>Governance is visible here but remains externally authoritative.</strong><span>This tab is read-only. It cannot issue ALLOW/DENY/REVIEW decisions and cannot approve a human-approval request.</span></div><span class="badge ${extTone}">aptsGSS ${escapeHtml(ext.status || 'UNKNOWN')}</span></div>
    <div class="grid health-grid"><div class="health-card"><label>AUTHORITY</label><strong style="font-size:14px">EXTERNAL_APTS_GSS</strong><small>${escapeHtml(ext.base_url || '—')}</small></div><div class="health-card"><label>LOCAL AUTH BINDINGS</label><strong>${local.authorization_binding_count ?? 0}</strong><small>persisted Mission-side binding records</small></div><div class="health-card"><label>PENDING HUMAN APPROVALS</label><strong class="${(ext.pending_approval_count || 0) ? 'status-warn' : 'status-pass'}">${ext.pending_approval_count || 0}</strong><small>read from authoritative Governance when available</small></div></div>
    <div class="spacer"></div>
    <div class="two-col"><div class="panel"><div class="panel-head"><div><div class="panel-title">CURRENT GOVERNANCE BINDING</div><div class="panel-sub">Mission-side immutable binding</div></div></div><div class="panel-body">${binding ? jsonBlock(binding) : '<div class="muted tiny">No Mission governance binding is currently persisted.</div>'}</div></div><div class="panel"><div class="panel-head"><div><div class="panel-title">AUTHORITATIVE CORRELATION</div><div class="panel-sub">aptsGSS read-side snapshot; no new authorization request is created</div></div></div><div class="panel-body">${ext.status === 'AVAILABLE' ? `<div class="info-grid" style="grid-template-columns:1fr 1fr">${info('Scopes', snapshot.counts?.scope_contracts ?? (snapshot.scope_contracts || []).length)}${info('Authorization Requests', snapshot.counts?.authorization_requests ?? requests.length)}${info('Policy Decisions', snapshot.counts?.policy_decisions ?? decisions.length)}${info('Governance Events', snapshot.counts?.events ?? (snapshot.events || []).length)}</div>` : `<div class="error-box">${escapeHtml(ext.error || 'Authoritative Governance is not reachable from Mission Orchestrator.')}</div>`}</div></div></div>
    <div class="spacer"></div>
    <div class="panel"><div class="panel-head"><div><div class="panel-title">POLICY DECISIONS</div><div class="panel-sub">Latest authoritative decision lineage visible to this mission</div></div><span class="badge cyan">READ ONLY</span></div><div class="panel-body">${policyDecisionTable(decisions, requestById)}</div></div>
    <div class="spacer"></div>
    <div class="panel"><div class="panel-head"><div><div class="panel-title">HUMAN APPROVAL REQUESTS</div><div class="panel-sub">Approval decisions must be made in the authenticated Governance plane</div></div><span class="badge amber">NO APPROVE/DENY CONTROL HERE</span></div><div class="panel-body">${approvalTable(approvals)}</div></div>`;
}

function policyDecisionTable(decisions, requestById) {
  if (!decisions.length) return '<div class="muted tiny">No authoritative policy decisions were found for this mission.</div>';
  return `<div class="table-wrap"><table><thead><tr><th>DECISION</th><th>ACTION</th><th>RESOURCE</th><th>REQUEST</th><th>HUMAN APPROVAL</th><th>VALID UNTIL</th></tr></thead><tbody>${decisions.slice().reverse().slice(0, 50).map(d => {
    const r = requestById[d.request_id] || {};
    const tone = d.decision === 'ALLOW' ? 'green' : (d.decision === 'DENY' ? 'red' : 'amber');
    return `<tr><td><span class="badge ${tone}">${escapeHtml(d.decision || '—')}</span></td><td>${escapeHtml(r.action_class || '—')}<div class="tiny muted">${escapeHtml(r.action_name || '')}</div></td><td>${escapeHtml(r.resource_type || '—')}<div class="tiny mono muted">${escapeHtml(r.resource_value || '')}</div></td><td><span class="mono tiny">${escapeHtml(d.request_id || '—')}</span></td><td>${d.requires_human_approval ? `<span class="badge amber">${escapeHtml(d.approval_request_id || 'REQUIRED')}</span>` : '—'}</td><td>${fmtTime(d.valid_until)}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}

function approvalTable(approvals) {
  if (!approvals.length) return '<div class="muted tiny">No human-approval requests are referenced by the current Governance correlation snapshot.</div>';
  return `<div class="table-wrap"><table><thead><tr><th>APPROVAL REQUEST</th><th>RISK</th><th>STATUS</th><th>ROLE</th><th>REASON</th><th>EXPIRES</th></tr></thead><tbody>${approvals.map(a => `<tr><td><span class="mono tiny">${escapeHtml(a.approval_request_id || '—')}</span></td><td>${escapeHtml(a.risk_level || '—')}</td><td><span class="badge ${a.status === 'APPROVED' ? 'green' : a.status === 'DENIED' ? 'red' : 'amber'}">${escapeHtml(a.status || 'UNKNOWN')}</span></td><td>${escapeHtml(a.required_approver_role || '—')}</td><td>${escapeHtml(a.reason || a.visibility_error || '—')}</td><td>${fmtTime(a.expires_at)}</td></tr>`).join('')}</tbody></table></div>`;
}

function planTab(c) {
  const versions = c.plans?.plan_versions || [];
  const tasks = c.tasks?.planned_tasks || [];
  const g = c.graph?.task_dependency_graph?.graph;
  const sortedVersions = versions.slice().sort((a, b) => Number(a.plan_version) - Number(b.plan_version));
  const diffControls = sortedVersions.length >= 2 ? `<div class="diff-controls"><label>From <select id="planDiffFrom" class="form-input compact-select">${sortedVersions.map((v, i) => `<option value="${v.plan_version}" ${i === sortedVersions.length - 2 ? 'selected' : ''}>v${v.plan_version}</option>`).join('')}</select></label><label>To <select id="planDiffTo" class="form-input compact-select">${sortedVersions.map((v, i) => `<option value="${v.plan_version}" ${i === sortedVersions.length - 1 ? 'selected' : ''}>v${v.plan_version}</option>`).join('')}</select></label><button id="runPlanDiff" class="ghost-button">Compare plans</button></div>` : '<div class="muted tiny">At least two immutable plan versions are required for a diff.</div>';
  return `<div class="two-col"><div class="panel"><div class="panel-head"><div><div class="panel-title">TASK DEPENDENCY DAG</div><div class="panel-sub">${g ? `${g.node_count} nodes · ${g.edge_count} edges · ${g.status}` : 'No graph materialized'}</div></div></div><div class="panel-body">${g ? taskGraph(g, tasks) : '<div class="empty-state"><h3>No task graph</h3><p>This mission has no materialized dependency graph.</p></div>'}</div></div><div class="panel"><div class="panel-head"><div><div class="panel-title">PLAN LINEAGE</div><div class="panel-sub">Immutable version history</div></div></div><div class="panel-body">${versions.length ? versions.map(v => `<div class="attention-item"><div class="row"><strong>v${v.plan_version} · ${escapeHtml(v.activation_type)}</strong><span class="badge ${v.effective_status === 'ACTIVE' ? 'green' : ''}">${escapeHtml(v.effective_status)}</span></div><div class="mid mono">${escapeHtml((v.canonical_sha256 || '').slice(0, 18))}…</div><div class="tiny muted">${fmtTime(v.created_at)}</div></div>`).join('') : '<div class="muted tiny">No plan versions.</div>'}</div></div></div><div class="spacer"></div><div class="panel"><div class="panel-head"><div><div class="panel-title">PLAN VERSION DIFF</div><div class="panel-sub">Semantic comparison of immutable candidate-plan content</div></div><span class="badge cyan">READ ONLY</span></div><div class="panel-body">${diffControls}<div id="planDiffResult" class="diff-result"></div></div></div><div class="spacer"></div><div class="panel"><div class="panel-head"><div class="panel-title">PLANNED TASKS</div><div class="panel-sub">Canonical task contracts</div></div><div class="panel-body"><div class="task-grid">${tasks.map(t => `<div class="task-card"><div class="row"><span class="task-key">${escapeHtml(t.task_key)}</span>${stateBadge(t.task_status)}</div><div class="task-body"><b>${escapeHtml(t.required_subsystem)}</b> · <span class="mono">${escapeHtml(t.required_capability)}</span><br>Task #${t.task_index} · plan v${t.plan_version}</div></div>`).join('') || '<div class="muted tiny">No planned tasks.</div>'}</div></div></div>`;
}
function taskGraph(g, tasks) {
  const order = g.topological_task_keys || g.nodes?.map(n => n.task_key) || [];
  const map = Object.fromEntries(tasks.map(t => [t.task_key, t]));
  return `<div class="task-graph">${order.map((k, i) => {
    const t = map[k] || g.nodes.find(n => n.task_key === k) || {};
    return `${i ? '<div class="graph-arrow">↓</div>' : ''}<div class="task-node"><div class="top"><strong>${escapeHtml(k)}</strong>${stateBadge(t.task_status || 'DEFINED')}</div><div class="meta"><span>${escapeHtml(t.required_subsystem || '—')}</span><span class="cap">${escapeHtml(t.required_capability || '—')}</span><span>#${t.task_index ?? '—'}</span></div></div>`;
  }).join('')}</div>`;
}

async function bindPlanDiff(c) {
  const button = $('#runPlanDiff');
  if (!button) return;
  const run = async () => {
    const fromVersion = $('#planDiffFrom')?.value;
    const toVersion = $('#planDiffTo')?.value;
    const host = $('#planDiffResult');
    if (!fromVersion || !toVersion || fromVersion === toVersion) {
      host.innerHTML = '<div class="error-box">Select two different plan versions.</div>';
      return;
    }
    host.innerHTML = '<div class="loading-card compact-loading">Computing deterministic plan diff…</div>';
    try {
      const d = await api(`/api/missions/${encodeURIComponent(c.mid)}/plan-diff?from=${encodeURIComponent(fromVersion)}&to=${encodeURIComponent(toVersion)}`);
      host.innerHTML = renderPlanDiff(d);
    } catch (e) {
      host.innerHTML = `<div class="error-box">${escapeHtml(e.message || String(e))}</div>`;
    }
  };
  button.addEventListener('click', run);
  await run();
}

function renderPlanDiff(d) {
  const x = d.summary || {};
  const modified = d.tasks?.modified || [];
  const added = d.tasks?.added || [];
  const removed = d.tasks?.removed || [];
  const depsAdded = d.dependencies?.added || [];
  const depsRemoved = d.dependencies?.removed || [];
  const taskLines = [
    ...added.map(v => `<div class="diff-line add"><span>+ TASK</span><code>${escapeHtml(v.task_key)}</code></div>`),
    ...removed.map(v => `<div class="diff-line remove"><span>− TASK</span><code>${escapeHtml(v.task_key)}</code></div>`),
    ...modified.map(v => `<div class="diff-block"><div class="diff-line modify"><span>Δ TASK</span><code>${escapeHtml(v.task_key)}</code></div>${v.changes.map(ch => `<div class="field-change"><b>${escapeHtml(ch.field)}</b><div><span class="before">${escapeHtml(JSON.stringify(ch.before))}</span><span class="arrow">→</span><span class="after">${escapeHtml(JSON.stringify(ch.after))}</span></div></div>`).join('')}</div>`),
  ].join('');
  const depLines = [
    ...depsAdded.map(v => `<div class="diff-line add"><span>+ EDGE</span><code>${escapeHtml(v.from_task_key)} → ${escapeHtml(v.to_task_key)}</code></div>`),
    ...depsRemoved.map(v => `<div class="diff-line remove"><span>− EDGE</span><code>${escapeHtml(v.from_task_key)} → ${escapeHtml(v.to_task_key)}</code></div>`),
  ].join('');
  return `<div class="diff-summary"><span class="badge ${x.plan_content_equal ? 'green' : 'amber'}">${x.plan_content_equal ? 'CONTENT IDENTICAL' : 'CONTENT CHANGED'}</span><span>+${x.added_task_count || 0} tasks</span><span>−${x.removed_task_count || 0} tasks</span><span>Δ${x.modified_task_count || 0} tasks</span><span>+${x.added_dependency_count || 0}/−${x.removed_dependency_count || 0} edges</span></div><div class="two-col diff-columns"><div><div class="panel-sub">Task changes</div>${taskLines || '<div class="muted tiny">No task-level changes.</div>'}</div><div><div class="panel-sub">Dependency changes</div>${depLines || '<div class="muted tiny">No dependency changes.</div>'}</div></div>`;
}

function liveEventsTab(c) {
  const entries = c.timeline?.timeline?.entries || [];
  const cursor = entries.length ? entries[entries.length - 1].source_event_id : null;
  return `<div class="phase3-callout"><div><strong>Live event stream</strong><span>Server-Sent Events follow the canonical mission event log. The stream is read-only and auto-reconnects after rotation.</span></div><span id="liveStatus" class="badge amber">CONNECTING</span></div><div class="panel"><div class="panel-head"><div><div class="panel-title">LIVE MISSION EVENTS</div><div class="panel-sub">Baseline cursor: <span class="mono">${escapeHtml(cursor || 'from registration')}</span></div></div><button id="clearLiveEvents" class="ghost-button">Clear view</button></div><div class="panel-body"><div id="liveEventList" class="live-event-list"><div class="muted tiny">Waiting for new canonical events…</div></div></div></div>`;
}

function startLiveEvents(c) {
  stopLiveStream();
  state.liveEvents = [];
  const entries = c.timeline?.timeline?.entries || [];
  const last = entries.length ? entries[entries.length - 1].source_event_id : '';
  const url = `/api/missions/${encodeURIComponent(c.mid)}/events/stream${last ? `?after=${encodeURIComponent(last)}` : ''}`;
  const status = $('#liveStatus');
  const source = new EventSource(url);
  state.activeEventSource = source;
  const updateStatus = (text, tone) => {
    if (!status) return;
    status.className = `badge ${tone || 'amber'}`;
    status.textContent = text;
  };
  source.addEventListener('stream_ready', () => updateStatus('LIVE', 'green'));
  source.addEventListener('mission_event', ev => {
    try {
      const item = JSON.parse(ev.data);
      state.liveEvents.push(item);
      if (state.liveEvents.length > 100) state.liveEvents.shift();
      renderLiveEventList();
      updateStatus('LIVE', 'green');
    } catch (_) {}
  });
  source.addEventListener('stream_rotate', () => updateStatus('RECONNECTING', 'amber'));
  source.addEventListener('stream_error', ev => {
    let message = 'STREAM ERROR';
    try { message = JSON.parse(ev.data).message || message; } catch (_) {}
    updateStatus(message.slice(0, 48), 'red');
  });
  source.onerror = () => updateStatus('RECONNECTING', 'amber');
  $('#clearLiveEvents')?.addEventListener('click', () => { state.liveEvents = []; renderLiveEventList(); });
}

function renderLiveEventList() {
  const host = $('#liveEventList');
  if (!host) return;
  if (!state.liveEvents.length) {
    host.innerHTML = '<div class="muted tiny">Waiting for new canonical events…</div>';
    return;
  }
  host.innerHTML = state.liveEvents.slice().reverse().map(e => `<div class="live-event"><div class="event-top"><span class="event-type">${escapeHtml(e.event_type || 'EVENT')}</span><span class="event-time">${fmtTime(e.occurred_at)}</span>${e.state_version != null ? `<span class="badge">state v${e.state_version}</span>` : ''}${e.plan_version ? `<span class="badge cyan">plan ${escapeHtml(e.plan_version)}</span>` : ''}</div><div class="event-meta">${escapeHtml(e.source_component || '—')} · <span class="mono">${escapeHtml(e.event_id || '—')}</span></div><div class="event-payload">${escapeHtml(JSON.stringify(e.payload || {}))}</div></div>`).join('');
}

function causalGraphTab(response) {
  const g = response?.graph;
  if (!g) return '<div class="empty-state"><h3>No causal graph</h3><p>The causal lineage graph is unavailable for this mission.</p></div>';
  return `<div class="phase3-callout"><div><strong>Interactive causal lineage</strong><span>Click a node to inspect its canonical event identity, causation and integrity hash.</span></div><span class="badge ${response.integrity_status === 'PASS' ? 'green' : 'amber'}">${escapeHtml(response.integrity_status || 'UNKNOWN')}</span></div><div class="causal-layout"><div class="panel"><div class="panel-head"><div><div class="panel-title">CAUSAL GRAPH</div><div class="panel-sub">${g.node_count} nodes · ${g.edge_count} edges · trace ${escapeHtml(response.trace_id || '—')}</div></div></div><div id="causalGraphCanvas" class="causal-canvas"></div></div><div class="panel"><div class="panel-head"><div class="panel-title">NODE INSPECTOR</div></div><div id="causalInspector" class="panel-body"><div class="muted tiny">Select a node.</div></div></div></div>`;
}

function bindCausalGraph(response) {
  const g = response?.graph;
  const host = $('#causalGraphCanvas');
  if (!g || !host) return;
  const nodes = g.nodes || [];
  const edges = g.edges || [];
  const byId = Object.fromEntries(nodes.map(n => [n.node_id, n]));
  const indegree = Object.fromEntries(nodes.map(n => [n.node_id, 0]));
  const out = Object.fromEntries(nodes.map(n => [n.node_id, []]));
  edges.forEach(e => {
    if (indegree[e.target_node_id] != null) indegree[e.target_node_id]++;
    if (out[e.source_node_id]) out[e.source_node_id].push(e.target_node_id);
  });
  const level = {};
  const q = nodes.filter(n => !indegree[n.node_id]).map(n => n.node_id);
  q.forEach(id => level[id] = 0);
  const work = q.slice();
  while (work.length) {
    const id = work.shift();
    for (const target of out[id] || []) {
      level[target] = Math.max(level[target] || 0, (level[id] || 0) + 1);
      indegree[target]--;
      if (indegree[target] === 0) work.push(target);
    }
  }
  nodes.forEach((n, i) => { if (level[n.node_id] == null) level[n.node_id] = i; });
  const groups = {};
  nodes.forEach(n => (groups[level[n.node_id]] ||= []).push(n));
  const maxLevel = Math.max(0, ...Object.keys(groups).map(Number));
  const width = 1040;
  const nodeW = 230, nodeH = 58, yGap = 92;
  const height = Math.max(260, 50 + (maxLevel + 1) * yGap);
  const pos = {};
  Object.entries(groups).forEach(([lv, items]) => {
    const gap = width / (items.length + 1);
    items.forEach((n, i) => pos[n.node_id] = { x: gap * (i + 1) - nodeW / 2, y: 25 + Number(lv) * yGap });
  });
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('class', 'causal-svg');
  const defs = document.createElementNS(ns, 'defs');
  defs.innerHTML = '<marker id="causalArrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" class="causal-arrow"/></marker>';
  svg.appendChild(defs);
  edges.forEach(e => {
    const a = pos[e.source_node_id], b = pos[e.target_node_id];
    if (!a || !b) return;
    const line = document.createElementNS(ns, 'line');
    line.setAttribute('x1', String(a.x + nodeW / 2));
    line.setAttribute('y1', String(a.y + nodeH));
    line.setAttribute('x2', String(b.x + nodeW / 2));
    line.setAttribute('y2', String(b.y));
    line.setAttribute('class', 'causal-edge');
    line.setAttribute('marker-end', 'url(#causalArrow)');
    svg.appendChild(line);
  });
  nodes.forEach(n => {
    const p = pos[n.node_id];
    const group = document.createElementNS(ns, 'g');
    group.setAttribute('class', `causal-node ${n.node_type === 'MISSION_ROOT' ? 'root' : ''}`);
    group.setAttribute('transform', `translate(${p.x},${p.y})`);
    const rect = document.createElementNS(ns, 'rect');
    rect.setAttribute('width', String(nodeW)); rect.setAttribute('height', String(nodeH)); rect.setAttribute('rx', '8');
    const title = document.createElementNS(ns, 'text');
    title.setAttribute('x', '12'); title.setAttribute('y', '22'); title.setAttribute('class', 'causal-title');
    title.textContent = n.event_type || n.node_type || 'NODE';
    const sub = document.createElementNS(ns, 'text');
    sub.setAttribute('x', '12'); sub.setAttribute('y', '41'); sub.setAttribute('class', 'causal-sub');
    sub.textContent = (n.source_event_id || n.node_id || '').slice(0, 28);
    group.append(rect, title, sub);
    group.addEventListener('click', () => {
      $$('.causal-node', svg).forEach(x => x.classList.remove('selected'));
      group.classList.add('selected');
      const inspector = $('#causalInspector');
      if (inspector) inspector.innerHTML = jsonBlock({ node: n, incoming: edges.filter(e => e.target_node_id === n.node_id), outgoing: edges.filter(e => e.source_node_id === n.node_id) });
    });
    svg.appendChild(group);
  });
  host.innerHTML = '';
  host.appendChild(svg);
}

function evidenceTab(d) {
  if (!d) return '<div class="empty-state"><h3>No evidence index</h3><p>Forensic evidence projection is unavailable.</p></div>';
  const counts = d.category_counts || {};
  const categories = Object.keys(counts);
  return `<div class="phase3-callout"><div><strong>Evidence browser</strong><span>Evidence is projected from the deterministic forensic bundle. No evidence is mutated or re-attested by this console.</span></div><span class="badge ${d.bundle_status === 'VERIFIED' ? 'green' : 'amber'}">${escapeHtml(d.bundle_status || 'UNKNOWN')}</span></div><div class="evidence-toolbar"><select id="evidenceFilter" class="form-input compact-select"><option value="">All evidence</option>${categories.map(k => `<option value="${escapeHtml(k)}">${escapeHtml(k)} (${counts[k]})</option>`).join('')}</select><span class="tiny muted">${d.evidence_count || 0} indexed records · bundle <span class="mono">${escapeHtml(d.bundle_id || '—')}</span></span></div><div class="evidence-layout"><div id="evidenceList" class="evidence-list"></div><div class="panel evidence-inspector"><div class="panel-head"><div class="panel-title">EVIDENCE INSPECTOR</div></div><div id="evidenceInspector" class="panel-body"><div class="muted tiny">Select an evidence record.</div></div></div></div>`;
}

function bindEvidenceBrowser(d) {
  const items = d?.items || [];
  const render = () => {
    const filter = $('#evidenceFilter')?.value || '';
    const visible = filter ? items.filter(x => x.category === filter) : items;
    const host = $('#evidenceList');
    if (!host) return;
    host.innerHTML = visible.map((x, i) => `<button class="evidence-card" data-eidx="${items.indexOf(x)}"><div class="row"><span class="badge cyan">${escapeHtml(x.category)}</span><span class="tiny muted">${fmtTime(x.timestamp)}</span></div><div class="evidence-id mono">${escapeHtml(x.record_id || '—')}</div><div class="tiny muted">task ${escapeHtml(x.task_ref || '—')}</div>${x.canonical_sha256 ? `<div class="event-hash">${escapeHtml(x.canonical_sha256)}</div>` : ''}</button>`).join('') || '<div class="empty-state compact"><h3>No matching evidence</h3></div>';
    $$('.evidence-card', host).forEach(btn => btn.addEventListener('click', () => {
      $$('.evidence-card', host).forEach(x => x.classList.remove('selected'));
      btn.classList.add('selected');
      const item = items[Number(btn.dataset.eidx)];
      const inspector = $('#evidenceInspector');
      if (inspector) inspector.innerHTML = jsonBlock(item?.record || {});
    }));
  };
  $('#evidenceFilter')?.addEventListener('change', render);
  render();
}

function forensicsTab(reconstruction, bundleResponse) {
  if (!reconstruction) return '<div class="empty-state"><h3>Forensic reconstruction unavailable</h3></div>';
  const r = reconstruction.result || {};
  const rec = r.reconstruction || {};
  const d = r.diagnostics || {};
  const bundle = bundleResponse?.bundle || {};
  const counts = bundle.record_counts || {};
  return `<div class="phase3-callout"><div><strong>Deterministic forensic reconstruction</strong><span>The reconstruction is rebuilt from persisted canonical evidence and remains read-only.</span></div><span class="badge ${r.status === 'VERIFIED' ? 'green' : 'amber'}">${escapeHtml(r.status || 'UNKNOWN')}</span></div><div class="grid health-grid"><div class="health-card"><label>RECONSTRUCTION</label><strong class="${r.status === 'VERIFIED' ? 'status-pass' : 'status-warn'}">${escapeHtml(r.status || '—')}</strong><small>${escapeHtml(r.reason_code || 'sources verified')}</small></div><div class="health-card"><label>EVENTS REBUILT</label><strong>${rec.event_count ?? '—'}</strong><small>head ${escapeHtml((rec.head_event_sha256 || '').slice(0, 18))}…</small></div><div class="health-card"><label>BLOCKING FINDINGS</label><strong>${d.blocking_finding_count ?? '—'}</strong><small>${d.finding_count ?? 0} total diagnostics findings</small></div></div><div class="spacer"></div><div class="two-col"><div class="panel"><div class="panel-head"><div><div class="panel-title">RECONSTRUCTED STATE</div><div class="panel-sub">State, active plan, outcomes and replan lineage</div></div></div><div class="panel-body">${jsonBlock({ mission_state: rec.mission_state, active_plan_version: rec.active_plan_version, execution_attempts: rec.execution_attempts, task_outcomes: rec.task_outcomes, replan_commits: rec.replan_commits })}</div></div><div class="panel"><div class="panel-head"><div><div class="panel-title">FORENSIC BUNDLE</div><div class="panel-sub">${escapeHtml(bundle.bundle_id || '—')}</div></div></div><div class="panel-body"><div class="info-grid" style="grid-template-columns:1fr 1fr">${info('Bundle status', bundle.status)}${info('Bundle SHA-256', r.bundle_sha256)}${info('Mission events', counts.mission_events ?? 0)}${info('Execution attempts', counts.execution_attempts ?? 0)}${info('Evidence bindings', counts.evidence_binding_verifications ?? 0)}${info('Task outcomes', counts.task_outcomes ?? 0)}</div></div></div></div><div class="spacer"></div><div class="panel"><div class="panel-head"><div class="panel-title">RECONSTRUCTION DETAIL</div><span class="badge cyan">READ ONLY</span></div><div class="panel-body">${jsonBlock(rec)}</div></div>`;
}

function timelineTab(c) {
  const t = c.timeline?.timeline || {};
  const entries = t.entries || t.timeline_entries || [];
  if (!entries.length) return '<div class="empty-state"><h3>No deterministic timeline</h3><p>Observability timeline is unavailable for this mission.</p></div>';
  return `<div class="panel"><div class="panel-head"><div><div class="panel-title">DETERMINISTIC MISSION TIMELINE</div><div class="panel-sub">${entries.length} ordered events · trace ${escapeHtml(c.timeline.trace_id || '—')}</div></div></div><div class="panel-body"><div class="timeline">${entries.map(e => `<div class="event ${e.event_type === 'MISSION_STATE_TRANSITIONED' ? 'statechange' : (e.decision_trace_categories || []).length ? 'decision' : ''}"><div class="event-top"><span class="event-type">${escapeHtml(e.event_type)}</span><span class="event-time">${fmtTime(e.occurred_at_utc)}</span>${e.state_version != null ? `<span class="badge">state v${e.state_version}</span>` : ''}${e.plan_version ? `<span class="badge cyan">plan ${escapeHtml(e.plan_version)}</span>` : ''}</div><div class="event-meta">${escapeHtml(e.source_component || '—')} · causation ${escapeHtml(e.causation_resolution || '—')}</div><div class="event-hash">${escapeHtml(e.source_event_sha256 || '')}</div></div>`).join('')}</div></div></div>`;
}
function diagnosticsTab(c) {
  const d = c.diagnostics?.diagnostics || {};
  const r = c.metrics?.report || {};
  const m = r.metrics || {};
  const h = r.observability_health || {};
  const op = r.operator_diagnostics || {};
  const ss = d.source_status || {};
  return `<div class="grid health-grid"><div class="health-card"><label>OBSERVABILITY HEALTH</label><strong class="${h.status === 'HEALTHY' ? 'status-pass' : 'status-warn'}">${escapeHtml(h.status || 'UNAVAILABLE')}</strong><small>${escapeHtml(h.reason_code || '—')}</small></div><div class="health-card"><label>DIAGNOSTICS</label><strong class="${d.status === 'PASS' ? 'status-pass' : 'status-warn'}">${escapeHtml(d.status || 'UNAVAILABLE')}</strong><small>${d.blocking_finding_count ?? '—'} blocking findings</small></div><div class="health-card"><label>EVENTS</label><strong>${m.event_count ?? '—'}</strong><small>${m.causal_node_count ?? '—'} causal nodes · ${m.causal_edge_count ?? '—'} edges</small></div></div><div class="spacer"></div><div class="panel"><div class="panel-head"><div class="panel-title">OBSERVABILITY SOURCES</div></div><div class="panel-body"><div class="diagnostic-sources">${Object.entries(ss).map(([k, v]) => `<div class="diag-source"><b>${escapeHtml(k.replaceAll('_', ' '))}</b><span class="${v === 'PASS' ? 'status-pass' : 'status-warn'}">${escapeHtml(v)}</span></div>`).join('') || '<div class="muted tiny">No source diagnostics.</div>'}</div></div></div><div class="spacer"></div><div class="panel"><div class="panel-head"><div><div class="panel-title">FINDINGS</div><div class="panel-sub">Information and blocking findings from integrity diagnostics</div></div></div><div class="panel-body"><ul class="findings">${(op.items || d.findings || []).slice(0, 80).map(f => `<li><code>${escapeHtml(f.code)}</code><span>${escapeHtml(f.reference || '—')}</span><span class="badge ${f.impact === 'BLOCKING' ? 'red' : ''}">${escapeHtml(f.impact || f.category || 'INFO')}</span></li>`).join('') || '<li><span class="status-pass">No findings.</span></li>'}</ul></div></div>`;
}

async function renderSubsystems() {
  pageTitle.textContent = 'Subsystem Registry';
  app.innerHTML = '<div class="loading-card">Loading canonical subsystem registry…</div>';
  try {
    const d = await api('/api/subsystems');
    const list = d.subsystems || [];
    const cards = await Promise.all(list.map(async s => {
      const id = s.identity?.subsystem_id;
      const caps = await api(`/api/subsystems/${encodeURIComponent(id)}/capabilities`, true);
      return { s, caps };
    }));
    app.innerHTML = `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(330px,1fr))">${cards.map(({ s, caps }) => {
      const id = s.identity?.subsystem_id;
      return `<div class="panel"><div class="panel-head"><div><div class="panel-title">${escapeHtml(id)}</div><div class="panel-sub">${escapeHtml(s.classification?.description || '')}</div></div><span class="badge green">${escapeHtml(s.registration?.status || 'REGISTERED')}</span></div><div class="panel-body"><div class="info-grid" style="grid-template-columns:1fr 1fr">${info('Type', s.classification?.subsystem_type)}${info('Runtime Health', s.registration?.runtime_health_probed ? 'PROBED' : 'NOT PROBED')}${info('Execution Authority', s.authority?.execution_authority)}${info('Target Actuation', String(s.authority?.target_actuation))}</div><div class="spacer"></div><div class="panel-sub">Capabilities</div>${jsonBlock((caps?.capabilities || []).map(c => ({ capability_id: c.identity?.capability_id, status: c.registration?.status })))}</div></div>`;
    }).join('')}</div>`;
  } catch (e) {
    renderError(e);
  }
}
async function renderCompare() {
  pageTitle.textContent = 'Mission Comparison';
  stopLiveStream();
  app.innerHTML = '<div class="loading-card">Loading missions for comparison…</div>';
  try {
    const missions = await api('/api/missions?limit=200');
    const items = missions.missions || [];
    if (items.length < 2) {
      app.innerHTML = '<div class="empty-state"><h3>Need at least two missions</h3><p>Mission comparison requires two registered mission identities.</p></div>';
      return;
    }
    const opts = items.map((m, i) => `<option value="${escapeHtml(m.mission_id)}">${escapeHtml(m.mission_id)} · ${escapeHtml(m.state || '—')}</option>`).join('');
    app.innerHTML = `<div class="phase3-callout"><div><strong>Side-by-side mission comparison</strong><span>Compares authoritative read-models only: state, plan/task progression, execution, replanning and observability.</span></div><span class="badge cyan">READ ONLY</span></div><div class="panel"><div class="panel-body"><div class="compare-controls"><label>Left mission<select id="compareLeft" class="form-input">${opts}</select></label><div class="compare-arrow">⇄</div><label>Right mission<select id="compareRight" class="form-input">${opts}</select></label><button id="runCompare" class="action-button">Compare</button></div></div></div><div class="spacer"></div><div id="compareResult"></div>`;
    const left = $('#compareLeft');
    const right = $('#compareRight');
    if (right && items[1]) right.value = items[1].mission_id;
    const run = async () => {
      if (!left?.value || !right?.value) return;
      const host = $('#compareResult');
      host.innerHTML = '<div class="loading-card">Comparing canonical mission projections…</div>';
      try {
        const d = await api(`/api/mission-comparison?left=${encodeURIComponent(left.value)}&right=${encodeURIComponent(right.value)}`);
        host.innerHTML = renderMissionComparison(d);
      } catch (e) {
        host.innerHTML = `<div class="error-box">${escapeHtml(e.message || String(e))}</div>`;
      }
    };
    $('#runCompare')?.addEventListener('click', run);
    await run();
  } catch (e) {
    renderError(e);
  }
}

function renderMissionComparison(d) {
  const l = d.left || {}, r = d.right || {}, cmp = d.comparison || {};
  const deltas = cmp.deltas_right_minus_left || {};
  const rows = [
    ['State', l.state, r.state, cmp.same_state ? 'same' : 'different'],
    ['State version', l.state_version, r.state_version, deltas.state_version],
    ['Active plan', l.active_plan_version == null ? '—' : `v${l.active_plan_version}`, r.active_plan_version == null ? '—' : `v${r.active_plan_version}`, deltas.active_plan_version],
    ['Plan versions', l.plan_version_count, r.plan_version_count, deltas.plan_version_count],
    ['Planned tasks', l.planned_task_count, r.planned_task_count, deltas.planned_task_count],
    ['Completed tasks', l.completed_task_count, r.completed_task_count, deltas.completed_task_count],
    ['Events', l.event_count, r.event_count, deltas.event_count],
    ['Execution attempts', l.execution_attempt_count, r.execution_attempt_count, deltas.execution_attempt_count],
    ['Replan commits', l.replan_commit_count, r.replan_commit_count, deltas.replan_commit_count],
    ['Observability', l.observability_health, r.observability_health, cmp.same_observability_health ? 'same' : 'different'],
    ['Blocking findings', l.blocking_finding_count, r.blocking_finding_count, deltas.blocking_finding_count],
  ];
  return `<div class="comparison-head"><div class="comparison-mission"><span class="tiny-label">LEFT</span><a href="#mission/${encodeURIComponent(l.mission_id || '')}">${escapeHtml(l.mission_id || '—')}</a><div>${stateBadge(l.state)}</div><div class="tiny muted">${escapeHtml(objectiveText(l.objective))}</div></div><div class="comparison-vs">VS</div><div class="comparison-mission"><span class="tiny-label">RIGHT</span><a href="#mission/${encodeURIComponent(r.mission_id || '')}">${escapeHtml(r.mission_id || '—')}</a><div>${stateBadge(r.state)}</div><div class="tiny muted">${escapeHtml(objectiveText(r.objective))}</div></div></div><div class="spacer"></div><div class="panel"><div class="panel-head"><div><div class="panel-title">COMPARISON MATRIX</div><div class="panel-sub">Delta is right minus left for numeric fields</div></div></div><div class="panel-body"><div class="table-wrap"><table class="compare-table"><thead><tr><th>METRIC</th><th>LEFT</th><th>RIGHT</th><th>Δ / RELATION</th></tr></thead><tbody>${rows.map(([k,a,b,delta]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(a ?? '—')}</td><td>${escapeHtml(b ?? '—')}</td><td>${escapeHtml(delta ?? '—')}</td></tr>`).join('')}</tbody></table></div></div></div>`;
}

function advancedAttentionList(items) {
  if (!items.length) return '<div class="empty-state compact"><h3>No prioritized attention items</h3><p>No mission in the bounded attention states requires operator inspection.</p></div>';
  return `<div class="attention-advanced">${items.map(x => `<div class="attention-advanced-card severity-${String(x.severity || 'LOW').toLowerCase()}"><div class="row"><div><span class="badge ${x.severity === 'CRITICAL' ? 'red' : x.severity === 'HIGH' ? 'amber' : 'cyan'}">${escapeHtml(x.severity || 'LOW')}</span> ${stateBadge(x.state || x.attention_reason)}</div><span class="tiny muted">${ago(x.updated_at || x.created_at)}</span></div><a class="attention-mission" href="#mission/${encodeURIComponent(x.mission_id)}">${escapeHtml(x.mission_id)}</a><div class="attention-action">${escapeHtml(x.recommended_operator_action || 'Inspect mission.')}</div><div class="attention-signals">${(x.reason_codes || []).map(r => `<span class="badge">${escapeHtml(r)}</span>`).join('')} ${x.blocking_finding_count ? `<span class="badge red">${x.blocking_finding_count} BLOCKING</span>` : ''}</div><div class="tiny muted">Observability: ${escapeHtml(x.observability_health || 'UNAVAILABLE')} · Diagnostics: ${escapeHtml(x.diagnostics_status || 'UNAVAILABLE')}</div></div>`).join('')}</div>`;
}

async function renderDiagnostics() {
  pageTitle.textContent = 'Operator Attention';
  stopLiveStream();
  app.innerHTML = '<div class="loading-card">Prioritizing operator attention from mission state and observability…</div>';
  try {
    const att = await api('/api/operator/attention/advanced?limit=100');
    const sc = att.severity_counts || {};
    app.innerHTML = `<div class="grid kpis"><div class="kpi danger"><div class="label">CRITICAL</div><div class="value">${sc.CRITICAL || 0}</div><div class="sub">terminal failure / blocking integrity</div></div><div class="kpi warn"><div class="label">HIGH</div><div class="value">${sc.HIGH || 0}</div><div class="sub">approval, evidence or health</div></div><div class="kpi accent"><div class="label">MEDIUM</div><div class="value">${sc.MEDIUM || 0}</div><div class="sub">paused / replanning</div></div><div class="kpi"><div class="label">TOTAL</div><div class="value">${att.attention_count || 0}</div><div class="sub">prioritized missions</div></div></div><div class="panel"><div class="panel-head"><div><div class="panel-title">PRIORITIZED OPERATOR ATTENTION</div><div class="panel-sub">State signals enriched with read-only observability diagnostics</div></div><span class="badge cyan">NO AUTHORITY CHANGE</span></div><div class="panel-body">${advancedAttentionList(att.items || [])}</div></div>`;
  } catch (e) {
    renderError(e);
  }
}
async function renderHealth() {
  pageTitle.textContent = 'System Health';
  app.innerHTML = '<div class="loading-card">Reading Mission Orchestrator health contract…</div>';
  try {
    const h = await api('/health');
    app.innerHTML = `<div class="grid health-grid"><div class="health-card"><label>STATUS</label><strong class="status-pass">${escapeHtml(h.status || 'HEALTHY')}</strong><small>Mission Orchestrator service</small></div><div class="health-card"><label>COMPONENT</label><strong>${escapeHtml(h.component_id || 'APTS-MO01')}</strong><small>${escapeHtml(h.component_name || 'Global Mission Orchestrator')}</small></div><div class="health-card"><label>CONTROL VERSION</label><strong style="font-size:12px" class="mono">${escapeHtml(h.control_version || '—')}</strong><small>Authoritative runtime contract</small></div></div><div class="spacer"></div><div class="panel"><div class="panel-head"><div class="panel-title">HEALTH PAYLOAD</div><span class="badge cyan">READ ONLY</span></div><div class="panel-body">${jsonBlock(h)}</div></div>`;
  } catch (e) {
    renderError(e);
  }
}

async function renderCurrent() {
  refreshGlobalHealth();
  switch (state.route) {
    case 'dashboard': return renderDashboard();
    case 'missions': return renderMissions();
    case 'mission': return renderMission(decodeURIComponent(state.params[0] || ''));
    case 'subsystems': return renderSubsystems();
    case 'compare': return renderCompare();
    case 'diagnostics': return renderDiagnostics();
    case 'health': return renderHealth();
    default: location.hash = '#dashboard';
  }
}

window.addEventListener('hashchange', parseRoute);
$('#refreshButton').addEventListener('click', () => renderCurrent());
parseRoute();
setInterval(refreshGlobalHealth, 15000);

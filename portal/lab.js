'use strict';
// The lab's working half: setup, downloads, assistant and My lab. It talks only to the Lab Helper on this laptop
// (same origin), and only when the helper opened this site with its launch token. On the public site it does nothing.
(function () {
const onLaptop = ['127.0.0.1', 'localhost'].includes(location.hostname);

// The helper puts a one-time token in the URL (#t=...). Keep it for reloads, then hide it.
const TOKEN = (() => {
  const m = location.hash.match(/^#t=([\w-]+)$/);
  if (m && onLaptop) {
    try { sessionStorage.setItem('labToken', m[1]); } catch (e) { /* private mode */ }
    history.replaceState(null, '', location.pathname + '#deploy');
    return m[1];
  }
  try { return sessionStorage.getItem('labToken'); } catch (e) { return null; }
})();
// A newly launched helper may reuse the same port. Pasting its new launch link
// into an open tab is a hash-only navigation, so reload with the new token. This runs in the website
// version too, so a tab showing the website switches to the lab instead of staying as it was.
window.addEventListener('hashchange', () => {
  const match = location.hash.match(/^#t=([\w-]+)$/);
  if (!match || !onLaptop) return;
  try { sessionStorage.setItem('labToken', match[1]); } catch (_) { /* private mode */ }
  history.replaceState(null, '', location.pathname + '#deploy');
  location.reload();
});

if (!onLaptop || !TOKEN) return;
document.documentElement.dataset.mode = 'lab';

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const sleep = ms => new Promise(r => setTimeout(r, ms));
const isMac = /Mac/.test(navigator.platform || navigator.userAgent);

async function api(path, body) {
  const opts = { method: body === undefined ? 'GET' : 'POST', headers: { 'X-Lab-Token': TOKEN || '' } };
  if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  let r;
  try { r = await fetch('/api/' + path, opts); }
  catch (_) {
    $('#connection-lost').hidden = false;
    throw new Error('Cannot reach the local Lab Helper. If its terminal says "Stopped.", restart it from agent/ and open the new private link printed there. Your model download and saved results are still on this laptop.');
  }
  const j = await r.json().catch(() => ({ error: `Unexpected response (${r.status})` }));
  if (!r.ok) {
    if (r.status === 401) {
      $('#connection-lost').hidden = false;
      throw new Error('This tab belongs to an earlier Lab Helper session. Open the new private link printed when you restarted the helper.');
    }
    throw new Error(j.error || r.statusText);
  }
  $('#connection-lost').hidden = true;
  return j;
}

// Start an approved action and poll it until it finishes; onUpdate gets each snapshot.
async function runJob(action, args, onUpdate) {
  let job = await api('jobs', { action, args });
  onUpdate(job);
  while (job.status === 'running') {
    await sleep(700);
    job = await api('jobs/' + job.id);
    onUpdate(job);
  }
  return job;
}

const savedLevel = (() => { try { return sessionStorage.getItem('labLevel'); } catch (_) { return null; } })();
const state = { status: null, hw: null, goal: null, rec: null, model: null, plan: null, safety: true, chatBusy: false, predict: { running: false },
  locations: {}, folder: null, proposals: {}, apps: null, appPlan: null, receipt: null, level: savedLevel === 'experienced' ? 'experienced' : 'beginner', compat: null, context: 2048, runningAll: false };
const isExperienced = () => state.level === 'experienced';

// ------------------------------------------------------------------ shared bits
const toolChip = (name, note) => `<div class="tool">tool <b>${esc(name)}</b>${note ? ' · ' + esc(note) : ''}</div>`;
const fact = (k, v, s) => `<div class="fact"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div>${s ? `<div class="s">${esc(s)}</div>` : ''}</div>`;

function setPill(kind, text) { const p = $('#pill'); p.className = 'lab-status lab-only ' + kind; p.textContent = text; }

async function refreshStatus() {
  try { state.status = await api('status'); }
  catch (e) { setPill('bad', 'Lab Helper not reachable'); renderAssistantState(); return null; }
  const rt = state.status.runtime;
  const n = rt.lab_models.length;
  const gone = (rt.broken_models || []).length;
  // "lab model" means the file is really on disk; a model Ollama lists without its file is counted separately.
  if (rt.running) setPill(gone ? 'warn' : 'ok', `Ollama running · ${n} lab model${n === 1 ? '' : 's'}${gone ? ` · ${gone} missing ${gone === 1 ? 'its file' : 'files'}` : ''}`);
  else if (rt.installed) setPill('warn', 'Ollama installed, not running');
  else setPill('warn', 'Ollama not installed');
  renderAssistantState();
  return state.status;
}

function diagnosisHtml(d) {
  if (!d) return '';
  const fix = Array.isArray(d.fix) ? `<ol>${d.fix.map(f => `<li>${esc(f)}</li>`).join('')}</ol>` : `<p>${esc(d.fix)}</p>`;
  return `<div class="diag">${toolChip('read_logs', 'matched a known error')}<h4>${esc(d.title)}</h4>
    <p><strong>Why:</strong> ${esc(d.cause)}</p><strong>Safe fix:</strong>${fix}
    <p class="small muted"><strong>Concept to learn:</strong> ${esc(d.learn)}</p></div>`;
}

function errorHtml(err, diagnosis) {
  return `<div class="note bad"><strong>Something went wrong.</strong> ${esc(err)}</div>${diagnosisHtml(diagnosis)}
    <div class="row-actions"><button class="btn small" data-ask="${esc('I got this error in the lab: ' + err)}">Ask the assistant about this</button>
      <button class="btn small" data-goto="mylab">Health check and help report</button></div>`;
}

// What a step costs, in the same six words on every card, before anything runs.
function riskHtml(risk) {
  if (!risk) return '';
  return `<dl class="risk" aria-label="What this step costs">${Object.values(risk).map(r => `<div class="${esc(r.level)}"><dt>${esc(r.label)}</dt><dd>${esc(r.value)}</dd></div>`).join('')}</dl>`;
}

// One approval card: why, what changes on the laptop, the command it replaces, then progress/log/errors.
function stepCard(s, active) {
  const [cls, label] = s.done ? (s.partial ? ['run', 'Recorded with limitations'] : ['ok', 'Done']) : s.running ? ['run', 'Running'] : s.error ? ['bad', 'Needs attention']
    : active ? ['ask', s.offer || 'Your next step'] : ['', 'Waiting'];
  const open = (active || s.error) && !s.done && !s.running;
  const canType = s.command && s.kind !== 'manual' && s.id !== 'check_hardware';
  let buttons = '';
  if (open) {
    if (s.kind === 'manual') {
      buttons = `${s.link ? `<a class="btn primary" href="${esc(s.link)}" target="_blank" rel="noopener noreferrer">Official download page</a>` : ''}
         <button class="btn" data-recheck>I finished this step; check again</button>`;
    } else if (s.selfMode) {
      buttons = `<button class="btn primary" ${s.action === 'first_prompt' ? `data-self-done="${esc(s.id)}"` : 'data-recheck'}>I ran it; ${s.action === 'first_prompt' ? 'mark it done' : 'check my work'}</button>
         <button class="btn" data-self="${esc(s.id)}">Run it for me instead</button>`;
    } else {
      buttons = `<button class="btn primary" data-approve="${esc(s.id)}">${s.error ? 'Try again' : ['check_hardware', 'check_install'].includes(s.action) ? 'Run this check' : 'Approve and run'}</button>
         ${canType ? `<button class="btn" data-self="${esc(s.id)}">I'll type it myself</button>` : ''}`;
    }
  }
  // Steps marked "api" go through Ollama's local connection; the command shown does exactly the same thing.
  const commandLabel = s.selfMode ? 'Type this in a terminal' : s.how === 'api' ? 'Does the same as typing' : 'The command behind this step';
  const body = (open || s.running) ? `${riskHtml(s.risk)}<dl>${s.what ? `<dt>What this is</dt><dd>${esc(s.what)}</dd>` : ''}
      <dt>Why you need it</dt><dd>${esc(s.why)}</dd>
      <dt>What changes on your laptop</dt><dd>${esc(s.does)}</dd>
      ${s.undo ? `<dt>How to undo it</dt><dd>${esc(s.undo)}</dd>` : ''}
      ${s.command ? `<dt>${commandLabel}</dt><dd><code class="cmd">${esc(s.command)}</code> <button class="btn small" data-copy-command="${esc(s.command)}">Copy command</button></dd>` : ''}</dl>` : '';
  const progress = s.running ? `<div class="progress ${s.progress == null ? 'indeterminate' : ''}"><span data-w="${s.progress == null ? 30 : Math.round(s.progress * 100)}"></span></div>
      ${s.detail ? `<div class="small muted">${esc(s.detail)}</div>` : ''}` : '';
  return `<article class="card step ${active && !s.done ? 'active' : ''}" id="step-${esc(s.id)}">
    <header><span class="badge ${cls}">${label}</span><h3>${esc(s.title)}</h3></header>
    ${body}${progress}
    ${s.log && s.log.length && !(s.done && s.summary) ? `<pre class="log">${esc(s.log.join('\n'))}</pre>` : ''}
    ${s.error ? errorHtml(s.error, s.diagnosis) : ''}${s.warning ? `<p class="note warn">${esc(s.warning)}</p>` : ''}
    ${s.done && s.summary ? `<p class="small muted mt">${esc(s.summary)}</p>` : ''}
    ${s.done && s.evidence ? `<ul class="evidence">${s.evidence.map(x => `<li class="${x.ok ? 'ok' : 'bad'}">${esc(x.text)}</li>`).join('')}</ul>` : ''}
    ${!open && !s.running && s.done && s.command ? `<div class="small muted">Command: <code class="cmd">${esc(s.command)}</code></div>` : ''}
    ${s.id === 'pull_model' && s.done && state.model ? `<div class="mt" data-location="${esc(state.model)}">${showButton(state.model)}<div class="location-slot">${locationHtml(state.model)}</div></div>` : ''}
    <div class="actions">${buttons}</div>
  </article>`;
}

// Run one step's action, keeping its card updated.
async function runStep(s, rerender) {
  Object.assign(s, { running: true, error: null, diagnosis: null, log: [], progress: null, detail: '' });
  rerender();
  try {
    const job = await runJob(s.action, s.args || {}, j => { Object.assign(s, { log: j.log, progress: j.progress, detail: j.detail }); rerender(); });
    s.running = false;
    s.result = job.result;
    s.warning = job.warning;
    s.partial = job.status === 'partial';
    if (job.status === 'done' || job.status === 'partial') { s.done = true; }
    else { s.error = job.error; s.diagnosis = job.diagnosis; }
  } catch (e) { s.running = false; s.error = e.message; }
  rerender();
  return s.done;
}

// ------------------------------------------------------------------ deploy: 1 laptop
const hwStep = {
  id: 'check_hardware', action: 'check_hardware', kind: 'action', title: "Let the assistant read your laptop's specs",
  why: 'To suggest a model that fits, it needs your system, chip, memory and free disk space.',
  does: 'Reads system information. Changes nothing, and nothing leaves your laptop.',
  command: isMac ? 'system_profiler SPHardwareDataType' : 'systeminfo',
};

function renderLaptop() {
  if (!state.hw) { $('#laptop-body').innerHTML = stepCard(hwStep, true); return; }
  const hw = state.hw;
  $('#laptop-body').innerHTML = `<div class="facts">
      ${fact('System', `${hw.os} ${hw.os_version}`)}
      ${fact('Chip', hw.cpu_model, `${hw.cpu_cores_physical} cores · ${hw.arch}`)}
      ${fact('Memory (RAM)', `${hw.total_ram_gb} GiB`, `${hw.available_ram_gb} GiB free right now`)}
      ${fact('Free disk', `${hw.free_disk_gb} GiB`, '10 GiB project cap: lab, runtime and one selected model')}
      ${fact('Graphics', hw.gpu)}
    </div>${toolChip('check_hardware', 'read only')}
    ${hw.supported_stop ? `<p class="note warn">${esc(hw.supported_stop)}</p>` : ''}
    ${compatHtml()}`;
}

const VERDICTS = { yes: ['ok', 'Ready now'], close_apps: ['warn', 'Close some apps first'], no: ['bad', "Won't fit right now"] };

function compatHtml() {
  if (!state.compat) return '<p class="muted">Checking which models fit…</p>';
  const groups = Object.keys(VERDICTS).map(v => [v, state.compat.models.filter(m => m.verdict === v)]).filter(([, list]) => list.length);
  const usable = state.compat.models.filter(m => m.verdict !== 'no').length;
  return `<div class="compat"><h3>Will it work on this laptop?</h3>
    <p>${usable ? `Yes. ${usable} of our ${state.compat.models.length} approved models can run here.` : 'Not right now. Free up memory or disk, then check again.'}</p>
    ${groups.map(([v, list]) => `<div class="verdict"><span class="badge ${VERDICTS[v][0]}">${VERDICTS[v][1]}</span>
      <ul class="fit-list">${list.map(m => `<li><strong>${esc(m.name)}</strong>${m.installed ? ' (downloaded)' : ''} <span class="small muted">${esc(m.reason)}</span></li>`).join('')}</ul></div>`).join('')}
    ${toolChip('check_hardware', 'compared with our approved model list')}</div>`;
}

async function loadCompat() {
  try { state.compat = await api('compatibility'); } catch (_) { state.compat = null; }
}

async function afterLaptopCheck() {
  await loadCompat();
  renderLaptop();
  applyLevel();
}

function applyLevel() {
  document.querySelectorAll('[data-level]').forEach(b => b.classList.toggle('active', b.dataset.level === state.level));
  $('#stage-goal').hidden = isExperienced();
  $('#stage-model').hidden = isExperienced();
  $('#steps-title').textContent = isExperienced() ? 'Your setup plan' : 'Set it up';
  $('#lab-setup .stages').classList.toggle('unnumbered', isExperienced());
  if (!state.hw) return;
  if (isExperienced()) {
    const models = state.compat ? state.compat.models : [];
    if (!state.model) {
      // Start small, like the public page: a downloaded model, else the first that's ready and at least 1.5B.
      const ready = models.filter(m => m.verdict !== 'no');
      const params = n => ((window.LocalLabCatalog.models.find(m => m.ollama_tag === n) || {}).params_b || 0);
      const pick = ready.find(m => m.installed) || ready.find(m => m.verdict === 'yes' && params(m.name) >= 1.5) || ready.find(m => m.verdict === 'yes') || ready[0];
      state.model = pick ? pick.name : null;
    }
    if (state.model) loadPlan();
    else $('#steps-body').innerHTML = '<p class="note warn">No approved model fits this laptop right now.</p>';
    unlock('stage-steps');
  } else {
    unlock('stage-goal');
    renderGoals();
    if (state.plan) renderSteps();
  }
}

// ------------------------------------------------------------------ what changed + undo
const changeRow = c => `<div class="change ${c.undone ? 'undone' : ''}">
      <div><div>${esc(c.what)}</div><div class="small muted">${esc(c.when)}${c.undone ? ' · undone' : ''}</div></div>
      ${c.undo_model && !c.undone ? `<button class="btn small" data-undo="${esc(c.undo_model)}">Undo</button>` : ''}
      ${c.undo_app && !c.undone ? `<button class="btn small" data-undo-app="${esc(c.undo_app)}">Undo</button>` : ''}</div>`;

// ------------------------------------------------------------------ apps: the second provider, same cards
async function renderApps() {
  try { state.apps = await api('apps'); } catch (e) { $('#apps-body').innerHTML = errorHtml(e.message); return; }
  const m = state.apps.manager;
  $('#apps-body').innerHTML = `<p class="note ${m.installed ? 'ok' : 'warn'}">${m.installed
      ? `<strong>${esc(m.name)} is on this laptop</strong>, so the lab can run the install for you. ${esc(m.note)}`
      : `<strong>${esc(m.name)} isn't on this laptop.</strong> ${esc(m.note)} Without it, each app becomes a step you do yourself from the official page. The lab won't install ${esc(m.name)}, because its installer asks for a password.`}</p>
    <div class="cards">${state.apps.apps.map(a => `<div class="card change wrap" data-app-card="${esc(a.id)}"><div><strong>${esc(a.name)}</strong> <span class="small muted">about ${a.size_gb} GB</span>
        <p class="small">${esc(a.what)}</p>
        <p class="small muted">${a.installed ? `Installed${a.by_lab ? ' by this lab' : ' already'} at <code class="cmd">${esc(a.path)}</code>` : 'Not on this laptop.'}</p></div>
        <div class="row-actions"><button class="btn ${a.installed ? '' : 'primary'} small" data-setup-app="${esc(a.id)}">${a.installed ? 'Check it' : 'Set it up'}</button>
          ${a.by_lab ? `<button class="btn small" data-undo-app="${esc(a.id)}">Undo install</button>` : ''}</div></div>`).join('')}</div>`;
}

async function loadAppPlan(app) {
  $('#app-plan').innerHTML = `<p class="muted">Checking what's already in place…</p>`;
  try {
    const plan = await api('plan_app', { app });
    const old = state.appPlan && state.appPlan.app.id === app ? Object.fromEntries(state.appPlan.steps.map(s => [s.id, s])) : {};
    plan.steps = plan.steps.map(s => (s.kind !== 'manual' && old[s.id] && old[s.id].done ? old[s.id] : s));
    state.appPlan = plan;
    renderAppSteps();
    $('#app-plan').scrollIntoView({ block: 'start' });
  } catch (e) { $('#app-plan').innerHTML = errorHtml(e.message); }
}

function renderAppSteps() {
  const steps = state.appPlan.steps;
  const first = steps.findIndex(s => !s.done);
  steps.forEach(summarize);
  $('#app-plan').innerHTML = `<h2>${esc(state.appPlan.app.name)}</h2>${steps.map((s, i) => stepCard(s, i === first)).join('')}
    ${first === -1 ? `<p class="note ok">${esc(state.appPlan.app.name)} is in place. It's listed in My lab, with Undo if this lab installed it.</p>` : ''}`;
}

// ------------------------------------------------------------------ recipes: a reviewed list of the same cards
const reviewHtml = review => (review.by ? `<p class="small muted">Reviewed by ${esc(review.by)} on ${esc(review.on)}.</p>` : '');

async function loadRecipePlan(recipe, scroll = true) {
  $('#recipe-plan').innerHTML = `<p class="muted">Checking what's already in place…</p>`;
  try {
    const plan = await api('plan_recipe', { recipe });
    const old = state.recipePlan && state.recipePlan.recipe.id === recipe ? Object.fromEntries(state.recipePlan.steps.map(s => [s.id, s])) : {};
    plan.steps = plan.steps.map(s => (s.kind !== 'manual' && old[s.id] && old[s.id].done ? old[s.id] : s));
    state.recipePlan = plan;
    renderRecipeSteps();
    if (scroll) $('#recipe-plan').scrollIntoView({ block: 'start' });
  } catch (e) { $('#recipe-plan').innerHTML = errorHtml(e.message); }
}

function renderRecipeSteps() {
  const p = state.recipePlan, steps = p.steps, first = steps.findIndex(s => !s.done), t = p.totals;
  steps.forEach(summarize);
  $('#recipe-plan').innerHTML = `<h2>${esc(p.recipe.title)}</h2>${reviewHtml(p.recipe.review)}
    <div class="card"><h3>What all of this costs</h3><dl class="risk">${[['Steps', t.steps], ['Space', t.space], ['Internet', t.internet], ['Password', t.password], ['Money', t.money]]
      .map(([k, v]) => `<div class="${v === 'No' || v === 'None' || v === 'Free' ? 'none' : 'note'}"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
      <p class="small muted">You approve each step below, one at a time. Each one appears in My lab, with Undo where it can be undone.</p></div>
    ${p.warnings.map(w => `<p class="note warn">${esc(w)}</p>`).join('')}
    ${steps.map((s, i) => stepCard(s, i === first)).join('')}
    ${first === -1 ? `<p class="note ok">${esc(p.recipe.title)} is in place. Everything it added is listed in My lab.</p><div class="actions"><button class="btn primary" data-goto="use">Use it</button></div>` : ''}`;
}

async function undoApp(button, app) {
  if (!button.dataset.confirm) {
    button.dataset.confirm = '1';
    button.textContent = 'Remove it from this laptop';
    return;
  }
  button.disabled = true;
  button.textContent = 'Removing…';
  try {
    const job = await runJob('remove_app', { app }, () => {});
    if (job.status !== 'done') throw new Error(job.error);
  } catch (e) { (button.closest('.change') || $('#changes-body')).insertAdjacentHTML('beforeend', errorHtml(e.message)); return; }
  if (state.appPlan && state.appPlan.app.id === app) state.appPlan = null, $('#app-plan').innerHTML = '';
  await renderChanges();
  if (!$('#view-catalog').hidden) renderApps();
  if (!$('#view-mylab').hidden) renderMyLab();
}

// ------------------------------------------------------------------ health check and help report
function repairCards(c) {
  const cards = [...(c.repair ? [c.repair] : []), ...(c.repairs || [])];
  return cards.map(card => {
    const s = { ...card, id: 'proposal-' + (++proposalSeq), offer: c.status === 'optional' ? 'Optional' : 'A repair you can approve' };
    state.proposals[s.id] = s;
    return `<div class="proposal">${stepCard(s, true)}</div>`;
  }).join('');
}

function healthRows(report) {
  const icon = { ok: 'ok', bad: 'bad', warn: 'warn', optional: 'optional' };
  return `<p class="note ${report.problems ? 'warn' : 'ok'}"><strong>${report.problems ? `${report.problems} to look at.` : 'Nothing to fix.'}</strong> Checked ${esc(report.when)}. This only read your laptop and changed nothing.</p>
    <ul class="health">${report.checks.map(c => `<li class="${icon[c.status]}"><strong>${esc(c.label)}.</strong> ${esc(c.detail)}
      ${c.goto ? `<button class="btn small" data-goto="${esc(c.goto)}">Go there</button>` : ''}${repairCards(c)}</li>`).join('')}</ul>`;
}

async function runHealth(button) {
  const box = $('#mylab-health-out');
  if (button) button.disabled = true;
  box.innerHTML = '<p class="muted">Checking…</p>';
  try { box.innerHTML = healthRows(await api('health')); }
  catch (e) { box.innerHTML = errorHtml(e.message); }
  if (button) button.disabled = false;
}

function helpCard() {
  const r = state.helpPacket;
  return `<div class="card"><p>Stuck? This makes one page for your TA: this laptop, the health check, and the steps that failed. Nothing is sent. You read it, add what you were trying to do, and choose whether to share it.</p>
    <p class="small muted">It leaves out anything you typed, any model's replies, your files, your name and your measurements.</p>
    <div class="row-actions"><button class="btn primary small" data-help-download>Download help report</button><button class="btn small" data-help-preview>${r && r.shown ? 'Hide' : 'Preview'}</button></div>
    ${r && r.shown ? `<div class="receipt mt">${md(r.markdown)}</div>` : ''}</div>`;
}

async function helpPacket(mode) {
  try { state.helpPacket = { ...(await api('help_packet')), shown: state.helpPacket ? state.helpPacket.shown : false }; }
  catch (e) { $('#mylab-help').innerHTML = errorHtml(e.message); return; }
  if (mode === 'download') saveText(state.helpPacket.markdown, state.helpPacket.filename);
  if (mode === 'preview') state.helpPacket.shown = !state.helpPacket.shown;
  $('#mylab-help').innerHTML = helpCard();
}

function saveText(text, filename) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown' }));
  const a = Object.assign(document.createElement('a'), { href: url, download: filename });
  document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}

// ------------------------------------------------------------------ receipt: one page the learner keeps
function receiptCard() {
  const r = state.receipt;
  return `<div class="card" data-receipt><p>One page with everything the lab added to this laptop, where it is, how much space it takes, and how to remove each item. Keep it, or hand it to whoever asks what this lab did.</p>
    <div class="row-actions"><button class="btn primary small" data-receipt-download>Download receipt</button><button class="btn small" data-receipt-preview>${r && r.shown ? 'Hide' : 'Preview'}</button></div>
    ${r && r.shown ? `<div class="receipt mt">${md(r.markdown)}</div>` : ''}</div>`;
}

async function receipt(mode) {
  try { state.receipt = { ...(await api('receipt')), shown: state.receipt ? state.receipt.shown : false }; }
  catch (e) { $('#mylab-receipt').innerHTML = errorHtml(e.message); return; }
  if (mode === 'download') saveText(state.receipt.markdown, state.receipt.filename);
  if (mode === 'preview') state.receipt.shown = !state.receipt.shown;
  $('#mylab-receipt').innerHTML = receiptCard();
}

async function renderChanges() {
  let items = [];
  try { items = (await api('changes')).changes; } catch (_) { return; }
  const changed = items.filter(c => (c.kind || 'change') === 'change');
  $('#changes-body').innerHTML = (changed.length ? changed.slice().reverse().map(changeRow).join('')
    : '<p class="muted">Nothing yet. Approved steps that change your laptop appear here.</p>')
    + `<div class="actions"><button class="btn small" data-goto="mylab">See everything in My lab</button></div>`;
}

// Where a model really is, once the learner has asked. Ollama's file name is a code, so say that plainly.
const fileApp = isMac ? 'Finder' : 'File Explorer';
function locationHtml(model) {
  const l = state.locations[model];
  if (!l) return '';
  return `<div class="location"><p class="small"><strong>${l.opened ? `Opened in ${fileApp}.` : `We couldn't open ${fileApp}, so here is the location.`}</strong> ${esc(model)} is this ${esc(l.size_gb)} GB file on your laptop:</p>
    <code class="cmd">${esc(l.path)}</code> <button class="btn small" data-copy-command="${esc(l.path)}">Copy location</button>
    <p class="small muted mt">Ollama names files by a code, not the model's name. Don't rename or move it, or Ollama won't find it. To remove it, use Undo or <code>ollama rm ${esc(model)}</code>.</p></div>`;
}
const showButton = model => `<button class="btn small" data-show-model="${esc(model)}">Show on my laptop</button>`;

// The one folder every model lives in, named up front so nobody has to search for it.
function folderCard(rt) {
  if (!rt || !rt.models_dir) return '';
  const result = state.folder;
  return `<div class="card" data-folder><p><strong>Where every model lives.</strong> Ollama keeps all of its models in one folder on this laptop:</p>
    <code class="cmd">${esc(rt.models_dir)}</code>
    <div class="row-actions mt">${rt.models_dir_exists ? `<button class="btn small" data-show-folder>Open folder</button>` : ''}<button class="btn small" data-copy-command="${esc(rt.models_dir)}">Copy location</button>
      ${result ? `<span class="small">${result.opened ? `Opened in ${fileApp}.` : `We couldn't open ${fileApp}; copy the location above instead.`}</span>` : ''}</div>
    <p class="small muted mt">${rt.models_dir_exists
      ? 'Inside, <b>blobs</b> holds the model files, named by a code instead of the model\'s name, and <b>manifests</b> is the list that tells Ollama which file belongs to which name. Don\'t move or rename anything in there. <b>Show on my laptop</b> below opens one model\'s own file.'
      : 'Ollama creates this folder on the first download.'}</p></div>`;
}

async function showFolder(button) {
  button.disabled = true;
  try { state.folder = await api('show_models_folder', {}); }
  catch (e) { state.folder = { opened: false }; }
  button.disabled = false;
  const card = button.closest('[data-folder]');
  if (card && state.status) card.outerHTML = folderCard(state.status.runtime);
}

// Models Ollama still lists whose file is gone: say so plainly, and offer the fix (download again).
function brokenHtml(broken, compat) {
  if (!broken.length) return '';
  const lab = broken.filter(m => compat.models.some(x => x.name === m));
  return `<div class="note bad"><strong>Listed, but the file is gone:</strong> ${broken.map(esc).join(', ')}.
    Ollama still lists ${broken.length === 1 ? 'this model' : 'these models'}, but the model file is missing from the folder above, so it can't run.
    Download it again to restore it, or take it off the list with <code>ollama rm NAME</code>.
    ${lab.map(m => `<button class="btn small" data-setup-model="${esc(m)}">Download ${esc(m)} again</button>`).join(' ')}</div>`;
}

async function showModel(button, model) {
  button.disabled = true;
  try { state.locations[model] = await api('show_model', { model }); }
  catch (e) { state.locations[model] = null; button.closest('[data-location]').querySelector('.location-slot').innerHTML = errorHtml(e.message); button.disabled = false; return; }
  document.querySelectorAll(`[data-location="${CSS.escape(model)}"] .location-slot`).forEach(n => { n.innerHTML = locationHtml(model); });
  button.disabled = false;
}

// Same format as the helper's own log (local time, to the minute).
const when = iso => { const d = new Date(iso); const z = n => String(n).padStart(2, '0'); return Number.isNaN(d.getTime()) ? String(iso).slice(0, 16) : `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())} ${z(d.getHours())}:${z(d.getMinutes())}`; };
const ACTIVITY_LABEL = { change: 'Changed your laptop', check: 'Checked or measured', assistant: 'Assistant' };

async function renderMyLab() {
  try {
    const [compat, log, results, apps] = await Promise.all([api('compatibility'), api('changes'), api('results'), api('apps')]);
    state.compat = compat;
    state.apps = apps;
    const byLab = apps.apps.filter(a => a.by_lab);
    $('#mylab-apps').innerHTML = byLab.length ? `<div class="card">${byLab.map(a => `<div class="change wrap"><div><strong>${esc(a.name)}</strong>
        <div class="small muted">About ${a.size_gb} GB · <code class="cmd">${esc(a.path)}</code></div></div>
        <div class="row-actions"><button class="btn small" data-undo-app="${esc(a.id)}">Undo install</button></div></div>`).join('')}</div>`
      : `<div class="card"><p class="muted">None yet. ${apps.apps.filter(a => a.installed).length ? 'Apps that were already here are not listed, because the lab didn\'t add them.' : ''}</p><button class="btn" data-goto="catalog">See the apps</button></div>`;
    $('#mylab-receipt').innerHTML = receiptCard();
    $('#mylab-help').innerHTML = helpCard();
    const items = log.changes.slice().reverse();
    const undoable = new Set(log.changes.filter(c => c.undo_model && !c.undone).map(c => c.undo_model));
    const installed = compat.models.filter(m => m.installed);
    const rt = state.status ? state.status.runtime : null;
    const others = rt ? rt.models.filter(m => !compat.models.some(x => x.name === m)) : [];
    $('#mylab-models').innerHTML = folderCard(rt) + brokenHtml(rt ? rt.broken_models || [] : [], compat) + (installed.length ? `<div class="card">${installed.map(m => `<div class="change wrap" data-location="${esc(m.name)}"><div><strong>${esc(m.name)}</strong>
        <div class="small muted">About ${m.size_gb} GB · ${esc(m.reason)}</div></div>
        <div class="row-actions">${showButton(m.name)}${undoable.has(m.name) ? `<button class="btn small" data-undo="${esc(m.name)}">Undo download</button>` : '<span class="small muted">You already had this</span>'}</div>
        <div class="location-slot">${locationHtml(m.name)}</div></div>`).join('')}
        ${others.length ? `<p class="small muted mt">Also in Ollama, outside the lab's list: ${others.map(esc).join(', ')}.</p>` : ''}</div>`
      : `<div class="card"><div class="lab-figure lab-state-figure" data-figure="drawer" data-label="An empty cabinet"></div><p>No lab models yet.</p><button class="btn primary" data-goto="deploy">Set one up</button></div>`);
    $('#mylab-results').innerHTML = results.models.length ? `<div class="card table-wrap"><table>
        <thead><tr><th>Model</th><th class="num">Tokens/s</th><th class="num">First text</th><th class="num">Peak memory</th><th class="num">Runs</th></tr></thead>
        <tbody>${results.models.slice(0, 8).map(m => `<tr><td>${esc(m.model)}<div class="small muted">${esc(when(m.last_run))}</div></td><td class="num">${m.median_tps != null ? Math.round(m.median_tps) : '–'}</td>
          <td class="num">${m.median_ttft_ms != null ? Math.round(m.median_ttft_ms) + ' ms' : '–'}</td><td class="num">${m.peak_ram_mb != null ? (m.peak_ram_mb / 1024).toFixed(1) + ' GiB' : '–'}</td><td class="num">${m.valid_runs}/${m.runs}</td></tr>`).join('')}</tbody></table></div>
        <p class="small muted mt">Tokens/s: how fast the reply appears (tokens are pieces of words). First text: the wait before the first word. Peak memory: the most memory the model used.</p>
        <div class="actions"><button class="btn" data-goto="measure">See the charts</button></div>`
      : `<div class="card"><p>No measurements yet.</p><button class="btn" data-goto="measure">Measure a model</button></div>`;
    $('#mylab-activity').innerHTML = items.length ? `<div class="card">${items.slice(0, 60).map(c => `<div class="change ${c.undone ? 'undone' : ''}"><div><div>${esc(c.what)}</div>
        <div class="small muted">${esc(c.when)} · ${esc(ACTIVITY_LABEL[c.kind || 'change'] || '')}${c.undone ? ' · undone' : ''}</div></div></div>`).join('')}</div>`
      : '<div class="card"><p class="muted">Nothing yet. Steps you run and tools the assistant uses appear here.</p></div>';
  } catch (e) { $('#mylab-activity').innerHTML = errorHtml(e.message); }
}

async function undoModel(button, model) {
  if (!button.dataset.confirm) {
    button.dataset.confirm = '1';
    button.textContent = `Remove ${model} from this laptop`;
    return;
  }
  button.disabled = true;
  button.textContent = 'Removing…';
  try {
    const job = await runJob('remove_model', { model }, () => {});
    if (job.status !== 'done') throw new Error(job.error);
  } catch (e) { (button.closest('.change') || $('#changes-body')).insertAdjacentHTML('beforeend', errorHtml(e.message)); return; }
  delete state.locations[model];
  await refreshStatus();
  await loadCompat();
  renderLaptop();
  await renderChanges();
  if (state.rec) renderModel();
  if (state.model === model) { resetTry(); state.plan = null; await loadPlan(); }
  if (!$('#view-mylab').hidden) renderMyLab();
}

function resetTry() {
  $('#try-body').innerHTML = '<p class="muted">Finish setup first.</p>';
  $('#stage-try').classList.add('locked');
}

// ------------------------------------------------------------------ deploy: 2 goal, 3 model
function renderGoals() {
  const goals = state.status ? state.status.goals : {};
  $('#goals').innerHTML = Object.entries(goals).map(([k, g]) =>
    `<button class="goal ${state.goal === k ? 'selected' : ''}" data-goal="${esc(k)}" ${state.hw ? '' : 'disabled'}><strong>${esc(g.label)}</strong><span>${esc(g.detail)}</span></button>`).join('');
}

async function chooseGoal(goal) {
  state.goal = goal;
  renderGoals();
  unlock('stage-model');
  $('#model-body').innerHTML = `<p class="muted">Finding a model that fits…</p>`;
  try {
    state.rec = await api('recommend', { goal });
    state.model = state.rec.pick ? state.rec.pick.name : null;
    renderModel();
  } catch (e) { $('#model-body').innerHTML = errorHtml(e.message); }
}

function renderModel() {
  const r = state.rec;
  const budgetNote = `<p class="small muted">Free memory right now: ${esc(r.free_ram_now_gb)} GiB, and we plan for up to ${esc(r.planning_ram_gb)} GiB once you close apps. The lab, Python and Ollama use ${esc(r.budget.non_model_gib)} GiB, which leaves ${esc(r.project_headroom_gib)} GiB for one model under the 10 GiB limit. Other Ollama models you already have (${esc(r.budget.installed_models_gib)} GiB) aren't counted.</p>`;
  if (!r.pick) { $('#model-body').innerHTML = `<p class="note warn">${esc(r.explanation)}</p>${budgetNote}`; return; }
  const have = new Set(state.status.runtime.lab_models);
  const installed = [...have].sort();
  const opts = r.options.map(o => `<label class="option ${o.name === state.model ? 'selected' : ''}">
      <input type="radio" name="model" value="${esc(o.name)}" ${o.name === state.model ? 'checked' : ''}>
      <div><div><strong>${esc(o.name)}</strong>${o.name === r.pick.name ? '<span class="tag">Suggested</span>' : ''}${have.has(o.name) ? '<span class="tag ok">Already downloaded</span>' : ''}</div>
        <div class="small muted">${o.params_billion} billion learned numbers · about ${o.download_file_size_gb} GB to download · needs about ${o.needs_free_ram_gb} GB of free memory</div></div></label>`).join('');
  $('#model-body').innerHTML = `<p>${esc(r.goal_why)}</p>
    ${installed.length ? `<div class="note">You already have <strong>${installed.map(esc).join(', ')}</strong>. <button class="btn small" data-goto="measure">Measure one of these</button></div>` : ''}
    <div class="options">${opts}</div>
    ${r.before_you_run ? `<p class="note warn">${esc(r.before_you_run)}</p>` : ''}
    <details><summary>How we worked this out</summary>
      ${budgetNote}<p class="small muted">We always keep 2 GiB of disk free for your system. Sizes and memory figures are estimates until you measure them in Predict &amp; Run.</p></details>
    ${toolChip('recommend_model', 'uses your RAM, free disk and our approved model list')}
    <div class="actions"><button class="btn primary" data-use-model>Continue with ${esc(state.model)}</button></div>`;
}

// ------------------------------------------------------------------ deploy: 4 steps, 5 try
async function loadPlan() {
  unlock('stage-steps');
  $('#steps-body').innerHTML = `<p class="muted">Checking what's already set up…</p>`;
  try {
    const plan = await api('plan', { model: state.model });
    // keep logs/results of steps that already ran in this session
    const old = state.plan && state.plan.model.name === plan.model.name ? Object.fromEntries(state.plan.steps.map(s => [s.id, s])) : {};
    plan.steps = plan.steps.map(s => {
      if (s.kind !== 'manual' && old[s.id] && old[s.id].done && s.id !== 'pull_model') return old[s.id];
      if (old[s.id]) s.selfMode = old[s.id].selfMode;
      return s;
    });
    state.plan = plan;
    if (plan.supported_stop) { $('#steps-body').innerHTML = `<p class="note warn">${esc(plan.supported_stop)}</p>`; return; }
    renderSteps();
  } catch (e) { $('#steps-body').innerHTML = errorHtml(e.message); }
}

// One line of evidence once a step is done, whether it came from the plan or from the assistant.
function summarize(s) {
  if (!(s.done && s.result) || s.summary) return;
  const r = s.result;
  s.summary = s.action === 'first_prompt' ? `Replied in ${r.seconds} s: "${r.reply}"`
    : s.action === 'start_runtime' ? 'Ollama is running on this laptop, at port 11434.'
    : s.action === 'benchmark' ? `Measured ${r.median_tps} tokens/s, peak memory ${r.peak_ram_mb != null ? (r.peak_ram_mb / 1024).toFixed(1) + ' GiB' : '?'}. See the Measure page.`
    : s.action === 'pull_model' ? 'Downloaded. It appears under What changed on your laptop, with Undo.'
    : s.action === 'remove_model' ? 'Removed from this laptop.'
    : s.action === 'install_app' ? (r.already ? `Already installed at ${r.path}.` : `Installed in ${r.seconds} s at ${r.path}. It appears in My lab, with Undo.`)
    : s.action === 'remove_app' ? 'Removed from this laptop.' : '';
  if (['check_install', 'check_app', 'check_recipe'].includes(s.action) && Array.isArray(r.steps)) s.evidence = r.steps.map(x => ({ ok: x.ok, text: x.detail }));
}

// A step by id, wherever it lives: the setup plan, an app plan, or a card the assistant proposed.
const findStep = id => (state.plan && state.plan.steps.find(x => x.id === id)) || (state.appPlan && state.appPlan.steps.find(x => x.id === id))
  || (state.recipePlan && state.recipePlan.steps.find(x => x.id === id)) || state.proposals[id];
const inRecipePlan = s => state.recipePlan && state.recipePlan.steps.includes(s);
const inAppPlan = s => state.appPlan && state.appPlan.steps.includes(s);
function redraw(s) {
  if (inAppPlan(s)) { renderAppSteps(); return; }
  if (inRecipePlan(s)) { renderRecipeSteps(); return; }
  if (!state.proposals[s.id]) { renderSteps(); return; }
  summarize(s);
  const el = document.getElementById('step-' + s.id);
  if (el) el.outerHTML = stepCard(s, true);
}

function renderSteps() {
  const steps = state.plan.steps;
  const first = steps.findIndex(s => !s.done);
  steps.forEach(summarize);
  if (isExperienced()) {
    renderPlanEditor(steps, first);
    if (first === -1) { unlock('stage-try'); renderTry(); }
    return;
  }
  $('#steps-body').innerHTML = steps.map((s, i) => stepCard(s, i === first)).join('');
  if (first === -1) { unlock('stage-try'); renderTry(); }
}

// The same steps for experienced users: one screen, editable, run together, every command still visible.
function renderPlanEditor(steps, first) {
  const models = state.compat ? state.compat.models : [];
  const remaining = steps.filter(s => !s.done);
  const blocked = remaining.length && remaining[0].kind === 'manual';
  const verdictOf = m => (m.verdict === 'yes' ? 'ready' : m.verdict === 'close_apps' ? 'close apps' : "won't fit") + (m.installed ? ', downloaded' : '');
  $('#steps-body').innerHTML = `<div class="card"><div class="plan-options">
      <label class="field"><span class="lbl">Model</span><select id="plan-model">${models.map(m => `<option value="${esc(m.name)}" ${m.name === state.model ? 'selected' : ''} ${m.verdict === 'no' ? 'disabled' : ''}>${esc(m.name)} · ${m.quant} · ${m.size_gb} GB · ${verdictOf(m)}</option>`).join('')}</select></label>
      <label class="field"><span class="lbl">Context size (Try it)</span><select id="plan-context">${[2048, 4096, 8192].map(c => `<option ${c === state.context ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
    </div>
    <p class="small muted">Measure keeps fixed settings, so results stay comparable.</p>
    ${steps.map((s, i) => `<div class="plan-row"><span class="badge ${s.done ? 'ok' : s.running ? 'run' : s.error ? 'bad' : i === first ? 'ask' : ''}">${s.done ? 'Done' : s.running ? 'Running' : s.error ? 'Failed' : 'To do'}</span>
      <div class="plan-main"><strong>${esc(s.title)}</strong> <span class="small muted">${esc(s.brief || '')}</span>
        ${s.command ? `<div><code class="cmd">${esc(s.command)}</code> <button class="btn small" data-copy-command="${esc(s.command)}">Copy command</button></div>` : ''}
        ${s.running ? `<div class="progress ${s.progress == null ? 'indeterminate' : ''}"><span data-w="${s.progress == null ? 30 : Math.round(s.progress * 100)}"></span></div>${s.detail ? `<div class="small muted">${esc(s.detail)}</div>` : ''}` : ''}
        ${s.error ? errorHtml(s.error, s.diagnosis) : ''}
        ${s.done && s.summary ? `<div class="small muted">${esc(s.summary)}</div>` : ''}
        <details><summary class="small">Why, what it changes, and what it costs</summary><p class="small">${esc(s.why)} ${esc(s.does)} ${esc(s.undo || '')}</p>${riskHtml(s.risk)}</details></div></div>`).join('')}
    <div class="actions">${blocked
      ? `<a class="btn primary" href="${esc(remaining[0].link)}" target="_blank" rel="noopener noreferrer">Official download page</a><button class="btn" data-recheck>I installed it; check again</button>`
      : remaining.length ? `<button class="btn primary" data-run-all ${state.runningAll ? 'disabled' : ''}>${state.runningAll ? 'Running…' : `Run ${remaining.length} remaining step${remaining.length === 1 ? '' : 's'}`}</button>` : ''}
    </div></div>`;
}

async function runAll() {
  state.runningAll = true;
  for (const s of state.plan.steps.filter(x => !x.done && x.kind !== 'manual')) {
    if (!await runStep(s, renderSteps)) break;
    await refreshStatus();
    renderChanges();
  }
  state.runningAll = false;
  await loadCompat();
  renderLaptop();
  renderSteps();
}

function renderTry() {
  if ($('#try-input')) return;
  $('#try-body').innerHTML = `<p>${esc(state.model)} is running on this laptop. Ask it anything; nothing leaves your computer.</p>
    <div class="row"><textarea id="try-input" rows="2" placeholder="Explain what RAM is in two sentences."></textarea>
      <button class="btn primary" data-try>Send</button></div>
    <div id="try-out"></div>
    <div class="actions"><button class="btn primary" data-goto="use">Keep talking: open Use it</button><button class="btn" data-goto="measure">Measure its speed</button></div>`;
}

async function tryModel() {
  const input = $('#try-input');
  const text = input.value.trim() || input.placeholder;
  $('#try-out').innerHTML = `<p class="muted answer">Thinking…</p>`;
  try {
    const r = await api('try', { model: state.model, message: text, context_tokens: isExperienced() ? state.context : 2048 });
    $('#try-out').innerHTML = `<div class="card answer">${md(r.text)}</div>
      <div class="stats"><span>First response text after <b>${r.ttft_s ?? '?'} s</b></span><span><b>${r.tps ?? '?'}</b> tokens per second</span><span>${r.tokens ?? '?'} tokens</span></div>`;
  } catch (e) { $('#try-out').innerHTML = errorHtml(e.message); }
}

function unlock(id) { $('#' + id).classList.remove('locked'); }

// ------------------------------------------------------------------ predict & run
function renderPredict() {
  if (state.predict.running) return;
  const models = state.status ? state.status.runtime.lab_models : [];
  if (!models.length) {
    $('#predict-body').innerHTML = `<div class="card"><p>Download a model first, then come back to measure it.</p>
      <button class="btn primary" data-goto="deploy">Go to Set up</button></div>`;
    return;
  }
  const p = state.predict;
  const model = models.includes(p.model) ? p.model : (models.includes(state.model) ? state.model : models[0]);
  p.model = model;
  $('#predict-body').innerHTML = `<div class="card">
      <label class="field" for="pr-model"><span class="lbl">Model</span>
        <select id="pr-model">${models.map(m => `<option ${m === model ? 'selected' : ''}>${esc(m)}</option>`).join('')}</select></label>
      <label class="field" for="pr-tps"><span class="lbl">Your guess: speed <output id="o-tps">${p.tps ?? 20} tokens/s</output></span>
        <input type="range" id="pr-tps" min="1" max="100" step="1" value="${p.tps ?? 20}">
        <span class="hint">Tokens are pieces of words, so this is how fast the reply appears.</span></label>
      <label class="field" for="pr-ram"><span class="lbl">Your guess: memory <output id="o-ram">${(p.ram ?? 2).toFixed(1)} GiB</output></span>
        <input type="range" id="pr-ram" min="0.5" max="10" step="0.1" value="${p.ram ?? 2}">
        <span class="hint">Hint: start from the download size, then add a little for the conversation.</span></label>
    </div>
    <div id="pr-step"></div><div id="pr-result"></div>`;
  renderPredictStep();
  if (p.result) renderPrediction(p.result);
}

function predictStep() {
  const p = state.predict;
  p.step = p.step && p.step.args.model === p.model ? p.step : {
    id: 'benchmark', action: 'benchmark', kind: 'action', title: `Measure ${p.model}`,
    why: 'Shows how fast this model really is here. It runs one warm-up, then three fixed questions three times each.',
    does: 'Keeps your processor and memory busy, which can take a few minutes. Saves the nine results in a file on this laptop, with no name in it.',
    command: null, args: { model: p.model, repeats: 3 }, risk: state.benchmarkRisk,
  };
  return p.step;
}

function renderPredictStep() { $('#pr-step').innerHTML = stepCard(predictStep(), true); }

async function runPrediction() {
  const p = state.predict;
  const s = predictStep();
  s.done = false; s.result = null;
  s.args = { model: p.model, repeats: 3, guess_tps: p.tps ?? 20, guess_ram_gb: p.ram ?? 2 };
  p.running = true;
  $('#pr-result').innerHTML = '';
  await runStep(s, renderPredictStep);
  p.running = false;
  if (s.result) { p.result = s.result; renderPrediction(s.result); s.done = false; renderPredictStep(); refreshStatus(); }
}

function compareBars(title, c, unit) {
  if (!c) return '';
  const max = Math.max(c.guess, c.actual) || 1;
  const off = c.off_by_percent;
  const verdict = Math.abs(off) <= 15 ? 'Within 15%: good intuition.' : `Your guess was ${Math.abs(off)}% too ${off > 0 ? 'high' : 'low'}.`;
  return `<div class="compare"><div class="lbl"><span>${esc(title)}</span><span class="small muted">${esc(verdict)}</span></div>
    <div class="bar"><span>Guess</span><div class="track"><div class="fill" data-w="${c.guess / max * 100}"></div></div><span class="num">${c.guess} ${unit}</span></div>
    <div class="bar actual"><span>Actual</span><div class="track"><div class="fill" data-w="${c.actual / max * 100}"></div></div><span class="num">${c.actual} ${unit}</span></div></div>`;
}

function renderPrediction(r) {
  const pc = r.prediction_check || {};
  const q = `I guessed ${pc.tps ? pc.tps.guess : '?'} tokens/s and ${pc.ram_gb ? pc.ram_gb.guess : '?'} GiB for ${r.model}. ` +
    `It measured ${r.median_tps} tokens/s and ${pc.ram_gb ? pc.ram_gb.actual : '?'} GiB. Why was my guess off?`;
  $('#pr-result').innerHTML = `<div class="card"><h3>${r.failed_runs === r.runs && r.runs > 0 ? 'Every run failed' : 'Your guess and the real numbers'}: ${esc(r.model)}</h3>
    ${(r.failed_runs || r.partial_runs) ? `<p class="note warn">${r.valid_runs ?? 0} complete, ${r.partial_runs ?? 0} partial, ${r.failed_runs ?? 0} failed. Treat these numbers with care, because some runs did not finish.</p>` : ''}
    ${compareBars('Speed', pc.tps, 'tok/s')}${compareBars('Memory', pc.ram_gb, 'GB')}
    <div class="kpis">${fact('Wait for the first word', r.median_ttft_ms == null ? 'Unavailable' : `${r.median_ttft_ms} ms`, 'the middle of the runs')}${fact('Warm-up reply', r.warmup_round_trip_s == null ? 'Unavailable' : `${r.warmup_round_trip_s} s`)}
      ${fact('CPU', r.median_cpu_percent == null ? 'Unavailable' : `${r.median_cpu_percent}%`, 'how busy the processor was; the graphics chip is not counted')}${fact('Peak memory', r.peak_ram_mb == null ? 'Unavailable' : `${Math.round(r.peak_ram_mb)} MiB`)}</div>
    ${r.note ? `<p class="small muted mt">${esc(r.note)}</p>` : ''}
    ${toolChip('run_benchmark', 'saved, and charted below')}
    <div class="actions"><button class="btn" data-ask="${esc(q)}">Ask the assistant why</button><button class="btn" data-goto="measure">See all results</button></div></div>`;
}

// ------------------------------------------------------------------ results
async function loadResults() {
  try {
    const r = await fetch('/api/results.json', { headers: { 'X-Lab-Token': TOKEN || '' } });
    if (!r.ok) {
      $('#results-body').innerHTML = `<div class="card lab-note"><div class="lab-figure lab-state-figure" data-figure="plot" data-label="An empty bar chart"></div><p>No measurements yet.</p><button class="btn primary" data-goto="measure">Measure a model</button></div>`;
      return;
    }
    window.LocalLabPortal.showSession(await r.text());
    $('#results-body').innerHTML = `<div class="card lab-note"><p>Your latest measurement from this laptop is in the charts below. It stays on your laptop.</p>
      <p class="small muted">Want to help other students see what a laptop like yours can do? Download the file and send it to the team. It has no name, account or folder path in it, and the lab never sends it for you.</p>
      <div class="actions"><button class="btn" data-download>Download JSON</button><button class="btn" data-goto="mylab">See all measurements</button></div></div>`;
  } catch (e) { $('#results-body').innerHTML = errorHtml(e.message); }
}

async function downloadJson() {
  try {
    const r = await fetch('/api/results.json', { headers: { 'X-Lab-Token': TOKEN || '' } });
    if (!r.ok) { const out = await r.json(); throw new Error(out.error || 'Download failed.'); }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await r.blob());
    a.download = 'local-ai-lab-session.json';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  } catch (e) { $('#results-body').insertAdjacentHTML('beforeend', errorHtml(e.message)); }
}

// ------------------------------------------------------------------ assistant
function md(src) {
  const parts = String(src || '').split(/```[\w-]*\n?([\s\S]*?)```/g);
  return parts.map((p, i) => i % 2 ? `<pre><code>${esc(p.trim())}</code></pre>` : blocks(p)).join('');
}
function inline(t) {
  return esc(t).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
}
function blocks(text) {
  return text.split(/\n{2,}/).map(b => b.trim()).filter(Boolean).map(b => {
    const lines = b.split('\n');
    if (lines.every(l => /^\s*[-*•]\s+/.test(l))) return `<ul>${lines.map(l => `<li>${inline(l.replace(/^\s*[-*•]\s+/, ''))}</li>`).join('')}</ul>`;
    if (lines.every(l => /^\s*\d+[.)]\s+/.test(l))) return `<ol>${lines.map(l => `<li>${inline(l.replace(/^\s*\d+[.)]\s+/, ''))}</li>`).join('')}</ol>`;
    const heading = lines.length === 1 && /^(#{1,3})\s+(.+)$/.exec(lines[0]);
    if (heading) return `<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`;
    return `<p>${lines.map(inline).join('<br>')}</p>`;
  }).join('');
}

function addMsg(kind, html) {
  const el = document.createElement('div');
  el.className = 'msg ' + kind;
  el.innerHTML = html;
  $('#msgs').appendChild(el);
  $('#msgs').scrollTop = $('#msgs').scrollHeight;
  return el;
}

let greeted = false;
let proposalSeq = 0;
function renderAssistantState() {
  const a = state.status && state.status.assistant;
  $('#a-model').textContent = a ? (a.ready ? `Thinks with ${a.model} on this laptop` : 'Answers from fixed rules until a model is downloaded') : 'Lab Helper not connected';
  if (greeted || !a) return;
  greeted = true;
  addMsg('bot', `<p>Hi! I'm the lab assistant. Ask about this laptop and I'll check it for real, then tell you what I read. Other questions go to the model on this laptop, and I'll tell you when it wrote the answer, because it can be wrong.</p>
    ${a.ready ? '<p>You can also paste an error.</p>' : '<p>No model is downloaded yet, so for now I answer from checks and the lab\'s notes. You can also paste an error.</p>'}`);
  $('#suggest').innerHTML = ['Is my model working?', 'Where are my models saved?', 'What is it good for?', 'How do I open this again tomorrow?']
    .map(s => `<button class="chip" data-ask="${esc(s)}">${esc(s)}</button>`).join('');
}

function traceHtml(trace) {
  return trace.map(t => `<details class="trace"><summary>tool <b>${esc(t.tool)}</b> · ${t.chosen_by === 'router' ? 'picked by a rule' : 'picked by the AI'}</summary><pre>${esc(t.result)}</pre></details>`).join('');
}

async function ask(text, openQuestion = false) {
  text = (text || '').trim();
  if (!text || state.chatBusy) return;
  state.chatBusy = true;
  $('#a-send').disabled = true;
  $('#suggest').innerHTML = '';
  addMsg('user', esc(text));
  const ready = state.status && state.status.assistant.ready;
  const pending = addMsg('bot thinking', ready ? 'Thinking locally… duration depends on your device' : 'Checking our catalog of known errors…');
  try {
    {
      const r = await api('chat', { message: text, guardrails: true, ...(openQuestion ? { open: true } : {}) });
      pending.innerHTML = traceHtml(r.trace) + md(r.text)
        + (r.mode === 'checked' ? `<div class="source checked">Checked on this laptop just now${(r.checked || []).length ? `: ${esc(r.checked.join(', '))}` : ''}. ${r.picked_by ? `${esc(r.picked_by)} chose this check, and code wrote the answer.` : 'No AI model wrote this.'}</div>` : '')
        + (r.mode === 'notes' ? `<div class="source notes">From the lab's reviewed notes. ${r.picked_by ? `${esc(r.picked_by)} chose this note, and no model wrote it.` : 'No AI model wrote this.'}</div>` : '')
        + ((r.mode === 'checked' || r.mode === 'notes') && state.status && state.status.assistant.ready ? `<button class="btn small mt" data-ask-open="${esc(text)}">Not what I asked: ask the model</button>` : '')
        + (r.mode === 'local_model' ? `<div class="source model">Written by ${esc(r.model)} on this laptop. It can be wrong, so check anything important.</div>` : '')
        + (r.mode === 'static_bootstrap' || r.mode === 'rule_only' ? '<div class="note small">Answered from fixed rules. No AI model wrote this.</div>' : '')
        + ((r.links || []).length ? `<div class="actions">${r.links.map(l => `<button class="btn small" data-goto="${esc(l.goto)}">${esc(l.label)}</button>`).join('')}</div>` : '')
        + (r.retry ? `<button class="btn small mt" data-ask="${esc(text)}">Try again</button>` : '')
        + (r.guardrail_intervened ? '<div class="note ok small">The safety layer rewrote an unsafe draft of this answer.</div>' : '')
        + (!r.guardrails && r.flagged.length ? `<div class="note bad small">With the safety layer on, this would have been blocked: ${esc(r.flagged.join(', '))}</div>` : '');
      // The assistant can only propose a registered step; it runs when the learner approves this card.
      (r.proposals || []).forEach(p => {
        const s = { ...p, id: 'proposal-' + (++proposalSeq) };
        state.proposals[s.id] = s;
        pending.insertAdjacentHTML('beforeend', `<div class="proposal"><p class="small muted">The assistant proposes a step. Nothing happens until you approve it.</p>${stepCard(s, true)}</div>`);
      });
    }
    pending.classList.remove('thinking');
  } catch (e) {
    pending.classList.remove('thinking');
    pending.innerHTML = `<div class="note bad small">${esc(e.message)}</div><button class="btn small mt" data-ask="${esc(text)}">Try again</button>`;
  }
  state.chatBusy = false;
  $('#a-send').disabled = false;
  $('#msgs').scrollTop = $('#msgs').scrollHeight;
}

// ------------------------------------------------------------------ use it: a real conversation, and two models side by side
const GOAL_PROMPTS = {
  try: ['Explain what RAM is in two sentences.', 'Give me three ideas for a short study break.', "What are you not good at? Be honest."],
  study: ["Explain recursion to me as if I'm new to programming.", 'Quiz me on supply and demand. Ask one question at a time and wait for my answer.', 'Explain opportunity cost in two sentences, then give one example.'],
  write: ['Rewrite this to sound more polite: Send me the notes by tonight.', 'Give me three subject lines for an email asking for an extension.', 'Make this shorter: I am writing to let you know that I will not be able to attend the meeting.'],
  code: ['Explain this error: IndexError: list index out of range', 'Write a Python function that reverses a string, then explain each line.', "What's the difference between a list and a tuple in Python?"],
};
const GOAL_NAMES = { try: 'Just trying it', study: 'Study help', write: 'Writing', code: 'Coding help' };
// Each weakness comes with a prompt that shows it, so a student sees it happen instead of being told.
const WEAKNESSES = [
  ['It invents facts and sources', "It predicts likely words and doesn't look anything up, so a made-up reference can look real.", 'Give me three peer-reviewed papers about sleep, with authors and years.', 'Try this, then search for the papers. Some may not exist.'],
  ['It gets arithmetic wrong', "It's guessing what the answer looks like, not calculating.", 'What is 4827 × 391?', 'The right answer is 1,887,357.'],
  ["It doesn't know recent events", "It can't browse the web, and it only knows what it learned before it was released.", 'What happened in the news today?', "A good answer says it can't know."],
  ['It sounds sure when it is wrong', "Its tone doesn't change with how likely it is to be right, so confidence tells you nothing.", 'Explain something you know well, and point out any mistakes you make.', 'Ask about your own field, where you can spot errors.'],
];
const COMPARE_QUESTIONS = [
  { q: 'What is 17 × 23?', right: 'The right answer is 391.' },
  { q: 'Which is larger, 9.11 or 9.9?', right: 'The right answer is 9.9.' },
  { q: 'Explain what RAM is in two sentences for someone new to computers.', right: 'No single right answer. Is it correct, and would a beginner follow it?' },
  { q: 'Write a polite two-line email asking for a deadline extension.', right: 'No single right answer. Would you send it as it is?' },
];
state.use = { info: null, model: null, goal: null, messages: [], talk: null, compare: { a: null, b: null, q: '', right: null, results: [], running: false, pick: null } };

const talkStats = t => [
  t.load_s != null && t.load_s >= 0.5 ? `Loading into memory: <b>${t.load_s} s</b>` : '',
  t.ttft_s != null ? `First word after <b>${t.ttft_s} s</b>` : '',
  t.tps != null ? `<b>${t.tps}</b> tokens per second` : '',
  t.tokens != null ? `${t.tokens} tokens` : '',
].filter(Boolean).map(x => `<span>${x}</span>`).join('');

function talkNotes(t) {
  const notes = [];
  if (t.status === 'stopped') notes.push('<p class="small muted mt">You stopped this reply.</p>');
  if (t.cut_off) notes.push('<p class="small muted mt">It reached the lab\'s length limit. Ask it to continue if you want more.</p>');
  if (t.flagged) notes.push('<p class="note warn small">This reply mentions a command or step the lab wouldn\'t suggest. The lab never runs what a model writes, so check it before you try it.</p>');
  if (t.prompt_tokens != null && t.context_tokens && t.prompt_tokens > t.context_tokens * 0.8) notes.push('<p class="note small">This conversation is close to what the model can hold, so it will start to forget the beginning. Start a new conversation for a new topic.</p>');
  return notes.join('');
}

function bubble(m) {
  if (m.role === 'user') return `<div class="talk-msg me">${esc(m.content)}</div>`;
  if (m.error) return `<div class="talk-msg them"><div class="note bad small">${esc(m.error)}</div></div>`;
  const body = m.content ? md(m.content) : `<p class="muted">${m.t && m.t.load_s == null ? 'Loading the model and reading your message…' : 'Thinking…'}</p>`;
  return `<div class="talk-msg them"><div class="small muted who">${esc(m.model)}</div>${body}${m.t && !m.pending ? `<div class="stats">${talkStats(m.t)}</div>${talkNotes(m.t)}` : ''}</div>`;
}

function drawTalk() {
  const u = state.use, log = $('#talk-log');
  if (!log) return;
  const following = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  const last = u.messages[u.messages.length - 1];
  if (last && last.pending && log.children.length === u.messages.length) log.lastElementChild.outerHTML = bubble(last);
  else log.innerHTML = u.messages.length ? u.messages.map(bubble).join('') : '<p class="muted">Pick a starter below, or type your own question.</p>';
  if (following) log.scrollTop = log.scrollHeight;
  const busy = !!u.talk;
  $('#talk-send').hidden = busy;
  $('#talk-stop').hidden = !busy;
  $('#talk-model').disabled = busy;
}

// Ask for one reply and follow it until it finishes, so the words appear as the model writes them.
async function followTalk(body, onUpdate) {
  let t = await api('talk', body);
  onUpdate(t);
  while (t.status === 'running') {
    await sleep(200);
    t = await api('talk/' + t.id);
    onUpdate(t);
  }
  return t;
}

async function sendTalk(text) {
  const u = state.use;
  text = (text || '').trim();
  if (!text || u.talk) return;
  u.messages.push({ role: 'user', content: text });
  const reply = { role: 'assistant', content: '', model: u.model, pending: true };
  const history = u.messages.filter(m => !m.error).map(({ role, content }) => ({ role, content })).slice(-39);
  while (history[0].role !== 'user') history.shift();
  u.messages.push(reply);
  u.talk = 'starting';
  drawTalk();
  try {
    await followTalk({ model: u.model, messages: history }, t => {
      u.talk = t.status === 'running' ? t.id : null;
      Object.assign(reply, { content: t.text, t, pending: t.status === 'running', error: t.status === 'failed' ? t.error : null });
      drawTalk();
    });
    if (!reply.content && !reply.error) reply.error = 'The model returned no words. Try again, or try a different model.';
  } catch (e) { reply.error = e.message; }
  reply.pending = false;
  u.talk = null;
  drawTalk();
}

function compareBody() {
  const u = state.use, c = u.compare, models = u.info.models;
  if (models.length < 2) {
    return `<p>This needs two models on your laptop, and you have ${models.length === 1 ? 'one' : 'none'}. Download a second model, ideally a different size, then come back.</p>
      <button class="btn" data-goto="catalog">See the models</button>`;
  }
  const select = (id, value) => `<select id="${id}" ${c.running ? 'disabled' : ''}>${models.map(m => `<option ${m.name === value ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}</select>`;
  return `<div class="plan-options"><label class="field"><span class="lbl">Model A</span>${select('cmp-a', c.a)}</label><label class="field"><span class="lbl">Model B</span>${select('cmp-b', c.b)}</label></div>
    <div class="chips">${COMPARE_QUESTIONS.map((x, i) => `<button class="chip" data-cmp-q="${i}" ${c.running ? 'disabled' : ''}>${esc(x.q)}</button>`).join('')}</div>
    <label class="field" for="cmp-q"><span class="lbl">The question for both</span><textarea id="cmp-q" rows="2" placeholder="Pick one above, or type your own.">${esc(c.q)}</textarea></label>
    <div class="actions"><button class="btn primary" data-cmp-run ${c.running ? 'disabled' : ''}>${c.running ? 'Asking one at a time…' : 'Ask both'}</button></div>
    <div id="cmp-out">${compareResults()}</div>`;
}

function compareResults() {
  const c = state.use.compare;
  if (!c.results.length) return '';
  const cards = c.results.map((r, i) => `<div class="card cmp-card"><h3><span class="muted">${'AB'[i]}</span> ${esc(r.model)}</h3>
    ${r.error ? `<div class="note bad small">${esc(r.error)}</div>` : r.t && r.t.text ? md(r.t.text) : `<p class="muted">${r.t ? 'Loading the model and reading the question…' : 'Waiting for its turn, so the two never share memory.'}</p>`}
    ${r.t && r.t.status !== 'running' ? `<div class="stats">${talkStats(r.t)}</div>${talkNotes(r.t)}` : ''}</div>`).join('');
  let verdict = '';
  const finished = c.results.every(r => r.t && r.t.status === 'done');
  if (finished && !c.running) {
    const [a, b] = c.results;
    const faster = a.t.tps != null && b.t.tps != null && a.t.tps !== b.t.tps ? (a.t.tps > b.t.tps ? 0 : 1) : null;
    verdict = `<div class="card mt"><h3>Which answer would you use?</h3>
      ${c.right ? `<p>${esc(c.right)}</p>` : '<p>Is it correct? Did it answer what you asked? You can judge this, and a speed number can\'t.</p>'}
      <div class="actions"><button class="btn ${c.pick === 0 ? 'primary' : ''}" data-cmp-pick="0">A</button><button class="btn ${c.pick === 1 ? 'primary' : ''}" data-cmp-pick="1">B</button><button class="btn ${c.pick === 2 ? 'primary' : ''}" data-cmp-pick="2">Neither</button></div>
      ${c.pick === 2 ? '<p class="mt">Good to know. Neither is good enough for this, which is a real result. Try a larger model, or use it only where you can check the answer.</p>'
        : c.pick != null ? `<p class="mt">${faster == null ? 'They ran at about the same speed, so that\'s purely your judgement of the answer.' : c.pick === faster ? 'You picked the faster one. On a different question, the slower one may win.' : 'You picked the slower one. The extra wait bought you an answer you preferred.'} Try a few more questions before you decide which model to keep.</p>` : ''}
    </div>`;
  }
  return `<div class="cmp-grid">${cards}</div>${verdict}
    <p class="small muted mt">Both get the same question and fixed settings, one at a time, with nothing else in memory. These are your own results for one question, not a ranking.</p>`;
}

function drawCompare() { const box = $('#cmp-out'); if (box) box.innerHTML = compareResults(); }

async function runCompare() {
  const c = state.use.compare, input = $('#cmp-q');
  const q = (input ? input.value : c.q).trim();
  if (c.running) return;
  if (!q) { input.focus(); return; }
  const known = COMPARE_QUESTIONS.find(x => x.q === q);
  Object.assign(c, { q, right: known ? known.right : null, pick: null, running: true, results: [{ model: c.a }, { model: c.b }] });
  $('#cmp-body').innerHTML = compareBody();
  for (const r of c.results) {
    try {
      r.t = await followTalk({ model: r.model, messages: [{ role: 'user', content: q }], fair: true }, t => { r.t = t; drawCompare(); });
      if (r.t.status === 'failed') r.error = r.t.error;
    } catch (e) { r.error = e.message; }
    drawCompare();
  }
  c.running = false;
  $('#cmp-body').innerHTML = compareBody();
}

async function renderUse() {
  const u = state.use;
  const body = $('#use-body');
  let info;
  try { info = await api('use_info'); } catch (e) { body.innerHTML = errorHtml(e.message); return; }
  u.info = info;
  if (!info.models.length) {
    body.innerHTML = `<div class="card"><h3>${info.running ? 'Download a model first' : info.installed ? 'Start Ollama first' : 'Set up first'}</h3>
      <p>${info.running ? 'Ollama is running, but no model has its file on this laptop yet.' : 'This page talks to a model through Ollama, and Ollama isn\'t running.'}</p>
      <div class="actions"><button class="btn primary" data-goto="deploy">Go to Set up</button></div></div>`;
    return;
  }
  const names = info.models.map(m => m.name);
  if (!names.includes(u.model)) u.model = names.includes(state.model) ? state.model : info.starting_model || names[0];
  if (!u.goal) u.goal = state.goal && GOAL_PROMPTS[state.goal] ? state.goal : 'try';
  const c = u.compare;
  if (!names.includes(c.a)) c.a = names[0];
  if (!names.includes(c.b) || c.b === c.a) c.b = names[names.length - 1];
  const keep = $('#talk-input') ? $('#talk-input').value : '';
  body.innerHTML = `
    <div class="card talk">
      <label class="field" for="talk-model"><span class="lbl">Talking with</span><select id="talk-model">${info.models.map(m => `<option ${m.name === u.model ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}</select></label>
      <div id="talk-log" class="talk-log" aria-live="polite"></div>
      <p class="note small course-note"><strong>Check your course's AI rules first.</strong> Each course sets its own, and running a model on your laptop doesn't change them. If AI is allowed, say that you used it.</p>
      <div class="use-goals" role="group" aria-label="Starter prompts for">${Object.entries(GOAL_NAMES).map(([k, v]) => `<button class="btn small ${k === u.goal ? 'primary' : ''}" data-talk-goal="${k}">${esc(v)}</button>`).join('')}</div>
      <div class="chips" id="talk-starters">${GOAL_PROMPTS[u.goal].map(p => `<button class="chip" data-talk-prompt="${esc(p)}">${esc(p)}</button>`).join('')}</div>
      <form id="talk-form" class="row talk-form"><textarea id="talk-input" rows="2" maxlength="${8000}" placeholder="Ask anything. Nothing leaves your laptop." aria-label="Message to the model">${esc(keep)}</textarea>
        <button class="btn primary" id="talk-send">Send</button><button type="button" class="btn" id="talk-stop" data-talk-stop hidden>Stop</button></form>
      <div class="actions"><button class="btn small" data-talk-new>New conversation</button><button class="btn small" data-talk-copy>Copy conversation</button></div>
      <p class="small muted">Nothing here is saved. It stays in this tab, and closing the tab clears it. The lab adds one instruction to each conversation: write in plain text.</p>
    </div>

    <h2>Compare two models</h2>
    <p>Ask both the same question. Speed is the easy part to measure. Only you can say which answer is better.</p>
    <div class="card" id="cmp-body">${compareBody()}</div>

    <h2>What small models get wrong</h2>
    <p>Knowing this is most of using one well. Each card has a prompt that shows the problem.</p>
    <div class="cards">${WEAKNESSES.map(([title, why, prompt, check]) => `<div class="card"><h3>${esc(title)}</h3><p>${esc(why)}</p>
      <p class="small muted">${esc(check)}</p><button class="btn small" data-talk-prompt="${esc(prompt)}">Try: ${esc(prompt)}</button></div>`).join('')}</div>

    <h2>Coming back tomorrow</h2>
    <div class="card"><p>Your models stay on this laptop, so you won't download anything again. Ollama and the Lab Helper stop when you close them, so restart both:</p>
      <ol><li>Open the Ollama app. On a Mac it's in Applications; on Windows it's in the Start menu.</li>
        <li>Double-click <strong>${esc(info.launcher)}</strong> in this folder. It opens this site with a new private link.
          <div><code class="cmd">${esc(info.folder)}</code> <button class="btn small" data-copy-command="${esc(info.folder)}">Copy location</button></div></li></ol>
      <p class="mt">You can also talk to a model without this site. With Ollama open, type this in a terminal, and type <code>/bye</code> to finish:</p>
      ${info.models.map(m => `<div><code class="cmd">${esc(m.command)}</code> <button class="btn small" data-copy-command="${esc(m.command)}">Copy command</button></div>`).join('')}
    </div>`;
  drawTalk();
  $('#talk-form').addEventListener('submit', e => { e.preventDefault(); const box = $('#talk-input'); const v = box.value; box.value = ''; sendTalk(v); });
  $('#talk-input').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#talk-form').requestSubmit(); } });
}

// ------------------------------------------------------------------ navigation + events
function onView() {
  const asked = location.hash.slice(1);
  const view = { models: 'catalog', apps: 'catalog', predict: 'measure', results: 'measure' }[asked] || asked;
  if (view === 'measure') { refreshStatus().then(renderPredict); loadResults(); }
  if (view === 'mylab') refreshStatus().then(renderMyLab);
  if (view === 'catalog') { refreshStatus().then(renderApps); showModelFit(); }
  if (view === 'use') refreshStatus().then(renderUse);
  if (view === 'deploy' || !view) renderChanges();
}

// The Catalog's model cards show real verdicts for this laptop instead of asking for its memory.
async function showModelFit() {
  await loadCompat();
  const results = await api('results').catch(() => ({ models: [] }));
  if (state.compat) window.LocalLabGuide.showLabFit(state.compat.models, results.models);
}

// Stage 3 must never contradict stage 4: when the model is chosen on Models or in the plan, say so there.
function modelChosenElsewhere(model, where) {
  state.model = model;
  state.rec = null;
  state.goal = null;
  renderGoals();
  unlock('stage-model');
  $('#model-body').innerHTML = `<div class="note">You chose <strong>${esc(model)}</strong> ${esc(where)}. Pick a goal above if you'd like a suggestion instead.</div>`;
}

async function setUpModel(model) {
  modelChosenElsewhere(model, 'in the Catalog');
  resetTry();
  location.hash = 'deploy';
  await loadPlan();
  $('#stage-steps').scrollIntoView({ block: 'start' });
}

function setAssistant(open) {
  document.documentElement.classList.toggle('assistant-open', open);
  try { sessionStorage.setItem('labAssistant', open ? '1' : '0'); } catch (_) { /* private mode */ }
}

document.addEventListener('click', async e => {
  const t = e.target.closest('button, [data-goto]');
  if (!t) return;
  const d = t.dataset;
  if (d.goto) { location.hash = d.goto; return; }
  if ('assistantToggle' in d) { setAssistant(!document.documentElement.classList.contains('assistant-open')); return; }
  if (d.setupModel) { setUpModel(d.setupModel); return; }
  if (d.level) {
    state.level = d.level;
    try { sessionStorage.setItem('labLevel', d.level); } catch (_) { /* private mode */ }
    applyLevel();
    return;
  }
  if (d.showModel) { showModel(t, d.showModel); return; }
  if ('showFolder' in d) { showFolder(t); return; }
  if (d.undo) { undoModel(t, d.undo); return; }
  if (d.undoApp) { undoApp(t, d.undoApp); return; }
  if (d.setupApp) { loadAppPlan(d.setupApp); return; }
  if (d.setupRecipe) { loadRecipePlan(d.setupRecipe); return; }
  if ('runHealth' in d) { runHealth(t); return; }
  if ('helpDownload' in d) { helpPacket('download'); return; }
  if ('helpPreview' in d) { helpPacket('preview'); return; }
  if ('receiptDownload' in d) { receipt('download'); return; }
  if ('receiptPreview' in d) { receipt('preview'); return; }
  if ('runAll' in d) { runAll(); return; }
  if (d.talkGoal) { state.use.goal = d.talkGoal; renderUse(); return; }
  if (d.talkPrompt) { const box = $('#talk-input'); if (box) { box.value = d.talkPrompt; box.focus(); box.scrollIntoView({ block: 'center' }); } return; }
  if ('talkStop' in d) { if (state.use.talk && state.use.talk !== 'starting') api(`talk/${state.use.talk}/stop`, {}).catch(() => {}); return; }
  if ('talkNew' in d) { if (!state.use.talk) { state.use.messages = []; drawTalk(); } return; }
  if ('talkCopy' in d) {
    const text = state.use.messages.map(m => `${m.role === 'user' ? 'You' : m.model}: ${m.error || m.content}`).join('\n\n');
    try { await navigator.clipboard.writeText(text); t.textContent = 'Copied'; setTimeout(() => { t.textContent = 'Copy conversation'; }, 1800); } catch (_) { t.textContent = "Couldn't copy"; }
    return;
  }
  if (d.cmpQ) { state.use.compare.q = COMPARE_QUESTIONS[+d.cmpQ].q; $('#cmp-q').value = state.use.compare.q; return; }
  if ('cmpRun' in d) { runCompare(); return; }
  if (d.cmpPick) { state.use.compare.pick = +d.cmpPick; drawCompare(); return; }
  if (d.self) {
    const s = findStep(d.self);
    if (s) { s.selfMode = !s.selfMode; redraw(s); }
    return;
  }
  if (d.selfDone) {
    const s = findStep(d.selfDone);
    if (s) { s.done = true; s.summary = 'You ran this one yourself.'; redraw(s); }
    return;
  }
  if (d.goal) { chooseGoal(d.goal); return; }
  if (d.copyCommand) {
    const label = t.textContent;
    try { await navigator.clipboard.writeText(d.copyCommand); t.textContent = 'Copied'; setTimeout(() => { t.textContent = label; }, 1800); }
    catch (_) { t.textContent = 'Select the command above to copy'; }
    return;
  }
  if ('useModel' in d) { loadPlan(); return; }
  if ('recheck' in d) { await refreshStatus(); if (t.closest('#app-plan') && state.appPlan) loadAppPlan(state.appPlan.app.id); else if (t.closest('#recipe-plan') && state.recipePlan) loadRecipePlan(state.recipePlan.recipe.id, false); else loadPlan(); return; }
  if ('try' in d) { tryModel(); return; }
  if ('download' in d) { downloadJson(); return; }
  if (d.ask) { ask(d.ask); return; }
  if (d.askOpen) { ask(d.askOpen, true); return; }
  if (d.approve === 'check_hardware') {
    if (await runStep(hwStep, renderLaptop)) { state.hw = hwStep.result; renderLaptop(); await afterLaptopCheck(); }
    return;
  }
  if (d.approve === 'benchmark') { runPrediction(); return; }
  if (d.approve) {
    const s = findStep(d.approve);
    if (!s) return;
    const ok = await runStep(s, () => redraw(s));
    if (ok) { await refreshStatus(); renderChanges(); if (state.proposals[s.id]) { await loadCompat(); renderLaptop(); if (state.plan) loadPlan(); } if (inRecipePlan(s) && s.action !== 'check_recipe') { await loadRecipePlan(state.recipePlan.recipe.id, false); renderApps(); return; } if (inAppPlan(s) || ['install_app', 'remove_app'].includes(s.action)) { if (!$('#view-catalog').hidden) renderApps(); } }
    redraw(s);
  }
});

document.addEventListener('change', e => {
  if (e.target.name === 'model') { state.model = e.target.value; renderModel(); }
  if (e.target.id === 'plan-model') { modelChosenElsewhere(e.target.value, 'in your setup plan'); resetTry(); loadPlan(); }
  if (e.target.id === 'plan-context') { state.context = +e.target.value; }
  if (e.target.id === 'talk-model') { state.use.model = e.target.value; }
  if (e.target.id === 'cmp-a') { state.use.compare.a = e.target.value; }
  if (e.target.id === 'cmp-b') { state.use.compare.b = e.target.value; }
  if (e.target.id === 'pr-model') { state.predict.model = e.target.value; state.predict.result = null; renderPredict(); }
  if (e.target.id === 'safety') {
    state.safety = e.target.checked;
    $('#safety-off').hidden = state.safety;
  }
});

document.addEventListener('input', e => {
  if (e.target.id === 'pr-tps') { state.predict.tps = +e.target.value; $('#o-tps').textContent = `${e.target.value} tokens/s`; }
  if (e.target.id === 'pr-ram') { state.predict.ram = +e.target.value; $('#o-ram').textContent = `${(+e.target.value).toFixed(1)} GiB`; }
});

document.addEventListener('DOMContentLoaded', async () => {
  new MutationObserver(() => document.querySelectorAll('.lab-app [data-w]').forEach(n => { n.style.width = n.dataset.w + '%'; }))
    .observe($('#main'), { childList: true, subtree: true });
  $('#a-form').addEventListener('submit', e => { e.preventDefault(); const v = $('#a-input').value; $('#a-input').value = ''; ask(v); });
  $('#a-input').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#a-form').requestSubmit(); } });
  window.addEventListener('hashchange', onView);
  let saved = null;
  try { saved = sessionStorage.getItem('labAssistant'); } catch (_) { /* private mode */ }
  setAssistant(innerWidth >= 1180 && (saved ? saved === '1' : true));
  renderLaptop();
  api('risks').then(r => { hwStep.risk = r.check_hardware; state.benchmarkRisk = r.benchmark; if (!state.hw) renderLaptop(); }).catch(() => {});
  await refreshStatus();
  renderGoals();
  applyLevel();
  onView();
  setInterval(() => { if (!document.hidden) refreshStatus(); }, 15000);
});
})();

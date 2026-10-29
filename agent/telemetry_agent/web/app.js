'use strict';
// Local AI Lab page. Talks only to the Lab Helper running on this laptop (same origin).

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const sleep = ms => new Promise(r => setTimeout(r, ms));
const isMac = /Mac/.test(navigator.platform || navigator.userAgent);

// The helper puts a one-time token in the URL (#t=...). Keep it for reloads, then hide it.
const TOKEN = (() => {
  const m = location.hash.match(/t=([\w-]+)/);
  if (m) {
    try { sessionStorage.setItem('labToken', m[1]); } catch (e) { /* private mode */ }
    history.replaceState(null, '', location.pathname);
    return m[1];
  }
  try { return sessionStorage.getItem('labToken'); } catch (e) { return null; }
})();

async function api(path, body) {
  const opts = { method: body === undefined ? 'GET' : 'POST', headers: { 'X-Lab-Token': TOKEN || '' } };
  if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const r = await fetch('/api/' + path, opts);
  const j = await r.json().catch(() => ({ error: `Unexpected response (${r.status})` }));
  if (!r.ok) throw new Error(j.error || r.statusText);
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

const state = { status: null, hw: null, goal: null, rec: null, model: null, plan: null, safety: true, chatBusy: false, predict: { running: false } };

// ------------------------------------------------------------------ shared bits
const toolChip = (name, note) => `<div class="tool">tool <b>${esc(name)}</b>${note ? ' · ' + esc(note) : ''}</div>`;
const fact = (k, v, s) => `<div class="fact"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div>${s ? `<div class="s">${esc(s)}</div>` : ''}</div>`;

function setPill(kind, text) { const p = $('#pill'); p.className = 'pill ' + kind; p.textContent = text; }

async function refreshStatus() {
  try { state.status = await api('status'); }
  catch (e) { setPill('bad', 'Lab Helper not reachable'); renderAssistantState(); return null; }
  const rt = state.status.runtime;
  const n = rt.lab_models.length;
  if (rt.running) setPill('ok', `Ollama running · ${n} lab model${n === 1 ? '' : 's'}`);
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
    <button class="btn small" data-ask="${esc('I got this error in the lab: ' + err)}">Ask the assistant about this</button>`;
}

// One approval card: why, what changes on the laptop, the command it replaces, then progress/log/errors.
function stepCard(s, active) {
  const [cls, label] = s.done ? ['ok', 'Done'] : s.running ? ['run', 'Running'] : s.error ? ['bad', 'Needs attention']
    : active ? ['ask', 'Needs your OK'] : ['', 'Waiting'];
  const open = (active || s.error) && !s.done && !s.running;
  let buttons = '';
  if (open) {
    buttons = s.kind === 'manual'
      ? `<a class="btn primary" href="${esc(s.link)}" target="_blank" rel="noopener">Open download page</a>
         <button class="btn" data-recheck>I've installed it, check again</button>`
      : `<button class="btn primary" data-approve="${esc(s.id)}">${s.error ? 'Try again' : 'Approve and run'}</button>`;
  }
  const body = (open || s.running) ? `<p>${esc(s.why)}</p><dl><dt>What happens on your laptop</dt><dd>${esc(s.does)}</dd>
      ${s.command ? `<dt>Same as typing in a terminal</dt><dd><code class="cmd">${esc(s.command)}</code></dd>` : ''}</dl>` : '';
  const progress = s.running ? `<div class="progress ${s.progress == null ? 'indeterminate' : ''}"><span style="width:${s.progress == null ? 30 : Math.round(s.progress * 100)}%"></span></div>
      ${s.detail ? `<div class="small muted">${esc(s.detail)}</div>` : ''}` : '';
  return `<article class="card step ${active && !s.done ? 'active' : ''}" id="step-${esc(s.id)}">
    <header><span class="badge ${cls}">${label}</span><h3>${esc(s.title)}</h3></header>
    ${body}${progress}
    ${s.log && s.log.length && !(s.done && s.summary) ? `<pre class="log">${esc(s.log.join('\n'))}</pre>` : ''}
    ${s.error ? errorHtml(s.error, s.diagnosis) : ''}
    ${s.done && s.summary ? `<p class="small muted" style="margin-top:8px">${esc(s.summary)}</p>` : ''}
    ${!open && !s.running && s.done && s.command ? `<div class="small muted">Same as: <code class="cmd">${esc(s.command)}</code></div>` : ''}
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
    if (job.status === 'done') { s.done = true; s.result = job.result; }
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
      ${fact('Memory (RAM)', `${hw.total_ram_gb} GB`, `${hw.available_ram_gb} GB free right now`)}
      ${fact('Free disk', `${hw.free_disk_gb} GB`, 'the lab uses 10 GB at most')}
      ${fact('Graphics', hw.gpu)}
    </div>${toolChip('check_hardware', 'read only')}
    ${hw.warning ? `<p class="note warn">${esc(hw.warning)}</p>` : ''}`;
}

// ------------------------------------------------------------------ deploy: 2 goal, 3 model
function renderGoals() {
  const goals = state.status ? state.status.goals : {};
  $('#goals').innerHTML = Object.entries(goals).map(([k, g]) =>
    `<button class="goal ${state.goal === k ? 'selected' : ''}" data-goal="${esc(k)}"><strong>${esc(g.label)}</strong><span>${esc(g.detail)}</span></button>`).join('');
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
  if (!r.pick) { $('#model-body').innerHTML = `<p class="note warn">${esc(r.explanation)}</p>`; return; }
  const have = new Set(state.status.runtime.lab_models);
  const opts = r.options.map(o => `<label class="option ${o.name === state.model ? 'selected' : ''}">
      <input type="radio" name="model" value="${esc(o.name)}" ${o.name === state.model ? 'checked' : ''}>
      <div><div><strong>${esc(o.name)}</strong>${o.name === r.pick.name ? '<span class="tag">Best for your goal</span>' : ''}${have.has(o.name) ? '<span class="tag ok">Already downloaded</span>' : ''}</div>
        <div class="small muted">${o.params_billion}B parameters · ${o.download_file_size_gb} GB download · needs about ${o.needs_free_ram_gb} GB free RAM</div>
        <div class="small">${esc(o.good_for)}</div></div></label>`).join('');
  $('#model-body').innerHTML = `<p>${esc(r.goal_why)}</p><div class="options">${opts}</div>
    ${r.before_you_run ? `<p class="note warn">${esc(r.before_you_run)}</p>` : ''}
    <details><summary>Why these fit your laptop</summary><p class="small" style="margin-top:6px">${esc(r.explanation)}</p>
      <p class="small muted">Planning with ${r.planning_ram_gb} GB of RAM and at most ${r.disk_cap_gb} GB of disk.</p></details>
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
    plan.steps = plan.steps.map(s => old[s.id] && old[s.id].done ? old[s.id] : s);
    state.plan = plan;
    renderSteps();
  } catch (e) { $('#steps-body').innerHTML = errorHtml(e.message); }
}

function renderSteps() {
  const steps = state.plan.steps;
  const first = steps.findIndex(s => !s.done);
  steps.forEach(s => {
    if (s.done && s.result && !s.summary) {
      s.summary = s.id === 'first_prompt' ? `Replied in ${s.result.seconds} s: "${s.result.reply}"` : '';
    }
  });
  $('#steps-body').innerHTML = steps.map((s, i) => stepCard(s, i === first)).join('');
  if (first === -1) { unlock('stage-try'); renderTry(); }
}

function renderTry() {
  if ($('#try-input')) return;
  $('#try-body').innerHTML = `<p>${esc(state.model)} is running on this laptop. Ask it anything; nothing leaves your computer.</p>
    <div class="row"><textarea id="try-input" rows="2" placeholder="Explain what RAM is in two sentences."></textarea>
      <button class="btn primary" data-try>Send</button></div>
    <div id="try-out"></div>
    <div class="actions"><button class="btn" data-goto="predict">Next: predict its speed</button></div>`;
}

async function tryModel() {
  const input = $('#try-input');
  const text = input.value.trim() || input.placeholder;
  $('#try-out').innerHTML = `<p class="muted answer">Thinking…</p>`;
  try {
    const r = await api('try', { model: state.model, message: text });
    $('#try-out').innerHTML = `<div class="card answer">${md(r.text)}</div>
      <div class="stats"><span>First word after <b>${r.ttft_s ?? '?'} s</b></span><span><b>${r.tps ?? '?'}</b> tokens per second</span><span>${r.tokens ?? '?'} tokens</span></div>`;
  } catch (e) { $('#try-out').innerHTML = errorHtml(e.message); }
}

function unlock(id) { $('#' + id).classList.remove('locked'); }

// ------------------------------------------------------------------ predict & run
function renderPredict() {
  if (state.predict.running) return;
  const models = state.status ? state.status.runtime.lab_models : [];
  if (!models.length) {
    $('#predict-body').innerHTML = `<div class="card"><p>Download a model first, then come back to measure it.</p>
      <button class="btn primary" data-goto="deploy">Go to Deploy</button></div>`;
    return;
  }
  const p = state.predict;
  const model = models.includes(p.model) ? p.model : (models.includes(state.model) ? state.model : models[0]);
  p.model = model;
  $('#predict-body').innerHTML = `<div class="card">
      <label class="field"><span class="lbl">Model</span>
        <select id="pr-model">${models.map(m => `<option ${m === model ? 'selected' : ''}>${esc(m)}</option>`).join('')}</select></label>
      <label class="field"><span class="lbl">Your guess: speed <output id="o-tps">${p.tps ?? 20} tokens/s</output></span>
        <input type="range" id="pr-tps" min="1" max="100" step="1" value="${p.tps ?? 20}">
        <span class="hint">A token is about three quarters of a word. People read about 5 tokens per second.</span></label>
      <label class="field"><span class="lbl">Your guess: memory <output id="o-ram">${(p.ram ?? 2).toFixed(1)} GB</output></span>
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
    why: 'Runs a warm-up and 3 prompts (short, medium, long) and times them, like the team does on every laptop.',
    does: 'Uses your processor and memory for about 30 seconds. Saves the numbers in the lab folder on this laptop only.',
    command: `ollama run ${p.model} --verbose`, args: { model: p.model },
  };
  return p.step;
}

function renderPredictStep() { $('#pr-step').innerHTML = stepCard(predictStep(), true); }

async function runPrediction() {
  const p = state.predict;
  const s = predictStep();
  s.done = false; s.result = null;
  s.args = { model: p.model, guess_tps: p.tps ?? 20, guess_ram_gb: p.ram ?? 2 };
  p.running = true;
  $('#pr-result').innerHTML = '';
  await runStep(s, renderPredictStep);
  p.running = false;
  if (s.done) { p.result = s.result; renderPrediction(s.result); s.done = false; renderPredictStep(); refreshStatus(); }
}

function compareBars(title, c, unit) {
  if (!c) return '';
  const max = Math.max(c.guess, c.actual) || 1;
  const off = c.off_by_percent;
  const verdict = Math.abs(off) <= 15 ? 'Within 15%: good intuition.' : `Your guess was ${Math.abs(off)}% too ${off > 0 ? 'high' : 'low'}.`;
  return `<div class="compare"><div class="lbl"><span>${esc(title)}</span><span class="small muted">${esc(verdict)}</span></div>
    <div class="bar"><span>Guess</span><div class="track"><div class="fill" style="width:${c.guess / max * 100}%"></div></div><span class="num">${c.guess} ${unit}</span></div>
    <div class="bar actual"><span>Actual</span><div class="track"><div class="fill" style="width:${c.actual / max * 100}%"></div></div><span class="num">${c.actual} ${unit}</span></div></div>`;
}

function renderPrediction(r) {
  const pc = r.prediction_check || {};
  const q = `I guessed ${pc.tps ? pc.tps.guess : '?'} tokens/s and ${pc.ram_gb ? pc.ram_gb.guess : '?'} GB for ${r.model}. ` +
    `It measured ${r.median_tps} tokens/s and ${pc.ram_gb ? pc.ram_gb.actual : '?'} GB. Why was my guess off?`;
  $('#pr-result').innerHTML = `<div class="card"><h3>Guess vs. reality: ${esc(r.model)}</h3>
    ${compareBars('Speed', pc.tps, 'tok/s')}${compareBars('Memory', pc.ram_gb, 'GB')}
    <div class="kpis">${fact('Time to first token', `${r.median_ttft_ms} ms`, 'median')}${fact('Load time', `${r.load_time_s} s`)}
      ${fact('CPU', `${r.median_cpu_percent}%`, 'of the whole machine')}${fact('Peak memory', `${Math.round(r.peak_ram_mb)} MB`)}</div>
    ${r.note ? `<p class="small muted" style="margin-top:10px">${esc(r.note)}</p>` : ''}
    ${toolChip('run_benchmark', 'saved for the Results tab')}
    <div class="actions"><button class="btn" data-ask="${esc(q)}">Ask the assistant why</button><button class="btn" data-goto="results">See all results</button></div></div>`;
}

// ------------------------------------------------------------------ results
async function loadResults() {
  $('#results-body').innerHTML = `<p class="muted">Loading…</p>`;
  try {
    const r = await api('results');
    if (!r.models.length) { $('#results-body').innerHTML = `<div class="card"><p>No measurements yet. Run one in Predict &amp; Run.</p></div>`; return; }
    $('#results-body').innerHTML = `<div class="card table-wrap"><table>
      <thead><tr><th>Model</th><th>Laptop</th><th class="num">Runs</th><th class="num">Tokens/s</th><th class="num">First token</th><th class="num">Peak RAM</th></tr></thead>
      <tbody>${r.models.map(m => `<tr><td>${esc(m.model)}</td><td>${esc(m.machine)}</td><td class="num">${m.runs}</td>
        <td class="num">${m.median_tps ?? '–'}</td><td class="num">${m.median_ttft_ms != null ? m.median_ttft_ms + ' ms' : '–'}</td>
        <td class="num">${m.peak_ram_mb != null ? (m.peak_ram_mb / 1024).toFixed(2) + ' GB' : '–'}</td></tr>`).join('')}</tbody></table>
      <p class="small muted" style="margin-top:10px">Medians over ${r.rows} measured prompts.</p></div>
      <div class="actions"><button class="btn primary" data-download>Download runs.csv for the dashboard</button></div>`;
  } catch (e) { $('#results-body').innerHTML = errorHtml(e.message); }
}

async function downloadCsv() {
  const r = await fetch('/api/results.csv', { headers: { 'X-Lab-Token': TOKEN || '' } });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(await r.blob());
  a.download = 'runs.csv';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
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
function renderAssistantState() {
  const a = state.status && state.status.assistant;
  $('#a-model').textContent = a ? (a.ready ? `Thinks with ${a.model} on this laptop` : 'Error help only, until a model is downloaded') : 'Lab Helper not connected';
  if (greeted || !a) return;
  greeted = true;
  addMsg('bot', `<p>Hi! I'm the lab assistant. I use 5 tools to check your laptop, pick a model, read errors and measure speed. I never suggest admin commands or deleting files.</p>
    ${a.ready ? '<p>Ask me anything, or paste an error.</p>' : '<p>My "brain" is a local model, and none is downloaded yet. Until you finish Deploy, I can still diagnose any error you paste.</p>'}`);
  $('#suggest').innerHTML = ['Which model fits my laptop?', 'What does tokens per second mean?', 'zsh: bad CPU type in executable: ./llama-server']
    .map(s => `<button class="chip" data-ask="${esc(s)}">${esc(s)}</button>`).join('');
}

function traceHtml(trace) {
  return trace.map(t => `<details class="trace"><summary>tool <b>${esc(t.tool)}</b> · ${t.chosen_by === 'router' ? 'picked by the router' : 'picked by the AI'}</summary><pre>${esc(t.result)}</pre></details>`).join('');
}

async function ask(text) {
  text = (text || '').trim();
  if (!text || state.chatBusy) return;
  state.chatBusy = true;
  $('#a-send').disabled = true;
  $('#suggest').innerHTML = '';
  addMsg('user', esc(text));
  const ready = state.status && state.status.assistant.ready;
  const pending = addMsg('bot thinking', ready ? 'Thinking… (5–20 s, it runs on your laptop)' : 'Checking our catalog of known errors…');
  try {
    if (!ready) {
      const d = await api('diagnose', { text });
      pending.innerHTML = d.matches.length ? d.matches.slice(0, 1).map(diagnosisHtml).join('') : `<p>${esc(d.advice)}</p>`;
    } else {
      const r = await api('chat', { message: text, guardrails: state.safety });
      pending.innerHTML = traceHtml(r.trace) + md(r.text)
        + (r.guardrail_intervened ? '<div class="note ok small">The safety layer rewrote an unsafe draft of this answer.</div>' : '')
        + (!r.guardrails && r.flagged.length ? `<div class="note bad small">With the safety layer on, this would have been blocked: ${esc(r.flagged.join(', '))}</div>` : '');
    }
    pending.classList.remove('thinking');
  } catch (e) {
    pending.classList.remove('thinking');
    pending.innerHTML = `<div class="note bad small">${esc(e.message)}</div>`;
  }
  state.chatBusy = false;
  $('#a-send').disabled = false;
  $('#msgs').scrollTop = $('#msgs').scrollHeight;
}

// ------------------------------------------------------------------ navigation + events
function show(view) {
  document.querySelectorAll('.tabs button').forEach(b => b.classList.toggle('active', b.dataset.goto === view));
  document.querySelectorAll('.view').forEach(v => { v.hidden = v.id !== 'view-' + view; });
  if (view === 'predict') refreshStatus().then(renderPredict);
  if (view === 'results') loadResults();
  window.scrollTo({ top: 0 });
}

document.addEventListener('click', async e => {
  const t = e.target.closest('button, [data-goto]');
  if (!t) return;
  const d = t.dataset;
  if (d.goto) { show(d.goto); return; }
  if (d.goal) { chooseGoal(d.goal); return; }
  if ('useModel' in d) { loadPlan(); return; }
  if ('recheck' in d) { await refreshStatus(); loadPlan(); return; }
  if ('try' in d) { tryModel(); return; }
  if ('download' in d) { downloadCsv(); return; }
  if (d.ask) { ask(d.ask); return; }
  if (d.approve === 'check_hardware') {
    if (await runStep(hwStep, renderLaptop)) { state.hw = hwStep.result; renderLaptop(); unlock('stage-goal'); renderGoals(); }
    return;
  }
  if (d.approve === 'benchmark') { runPrediction(); return; }
  if (d.approve && state.plan) {
    const s = state.plan.steps.find(x => x.id === d.approve);
    if (s && await runStep(s, renderSteps)) { await refreshStatus(); renderSteps(); }
  }
});

document.addEventListener('change', e => {
  if (e.target.name === 'model') { state.model = e.target.value; renderModel(); }
  if (e.target.id === 'pr-model') { state.predict.model = e.target.value; state.predict.result = null; renderPredict(); }
  if (e.target.id === 'safety') {
    state.safety = e.target.checked;
    $('#safety-off').hidden = state.safety;
  }
});

document.addEventListener('input', e => {
  if (e.target.id === 'pr-tps') { state.predict.tps = +e.target.value; $('#o-tps').textContent = `${e.target.value} tokens/s`; }
  if (e.target.id === 'pr-ram') { state.predict.ram = +e.target.value; $('#o-ram').textContent = `${(+e.target.value).toFixed(1)} GB`; }
});

$('#a-form').addEventListener('submit', e => { e.preventDefault(); const v = $('#a-input').value; $('#a-input').value = ''; ask(v); });
$('#a-input').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#a-form').requestSubmit(); } });

(async function init() {
  if (!TOKEN) { $('#no-token').hidden = false; setPill('bad', 'Lab Helper not connected'); return; }
  renderLaptop();
  await refreshStatus();
  renderGoals();
  setInterval(refreshStatus, 15000);
})();

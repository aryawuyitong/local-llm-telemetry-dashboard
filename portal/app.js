/* Public learning portal: local files in, no telemetry or localhost requests out. */
(function () {
  'use strict';
  const D = window.LocalLabData;
  const $ = (id) => document.getElementById(id);
  const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
  const state = { sessions: [], prediction: null, quiz: { pre: null, post: null }, phase: 'pre', consent: false, importGeneration: 0 };
  const STORAGE_KEY = 'local-ai-lab.learning.v1';
  const format = (n, digits = 1) => n === null || n === undefined || !Number.isFinite(n) ? '—' : n.toLocaleString('en-US', { maximumFractionDigits: digits });
  const unknown = (s) => s === null || s === undefined ? 'Not recorded' : String(s);
  let toastTimer;
  function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4500); }

  function route() {
    const candidate = location.hash.slice(1);
    const view = ['learn', 'deploy', 'predict', 'results'].includes(candidate) ? candidate : 'learn';
    document.querySelectorAll('.view').forEach(node => { node.hidden = node.id !== 'view-' + view; });
    document.querySelectorAll('[data-view]').forEach(node => { if (node.dataset.view === view) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current'); });
    document.title = ['Local AI Lab', { learn: 'Learn', deploy: 'Deploy', predict: 'Predict & Run', results: 'Results' }[view]].join(' · ');
  }
  window.addEventListener('hashchange', () => { route(); $('main').focus({ preventScroll: true }); window.scrollTo(0, 0); });

  function safeLearningRecord(value) {
    if (!value || value.version !== 1 || value.consent !== true) return null;
    const clean = { prediction: null, quiz: { pre: null, post: null } };
    if (value.prediction && Number.isFinite(value.prediction.tps) && value.prediction.tps >= 0 && value.prediction.tps <= 1000000 && Number.isFinite(value.prediction.ram_gib) && value.prediction.ram_gib >= 0 && value.prediction.ram_gib <= 1048576) clean.prediction = { tps: value.prediction.tps, ram_gib: value.prediction.ram_gib };
    for (const phase of ['pre', 'post']) {
      const q = value.quiz && value.quiz[phase];
      if (q && Array.isArray(q.answers) && q.answers.length === 10 && q.answers.every(a => Number.isInteger(a) && a >= 0 && a <= 3) && typeof q.completed_at === 'string' && Number.isFinite(Date.parse(q.completed_at))) clean.quiz[phase] = { answers: q.answers, completed_at: q.completed_at, score: q.answers.filter((a, i) => a === QUIZ[i].correct).length };
    }
    return clean;
  }
  function learningRecord() { return { version: 1, consent: state.consent, instrument: 'local-ai-lab-knowledge-check-v1', note: 'Anonymous learning exercise; not a validated instrument. No imported benchmark data, free-text reflections, or identity fields are included.', prediction: state.prediction, quiz: state.quiz }; }
  function persistLearning() {
    try { if (state.consent) localStorage.setItem(STORAGE_KEY, JSON.stringify(learningRecord())); else localStorage.removeItem(STORAGE_KEY); }
    catch (_) { state.consent = false; $('remember-learning').checked = false; toast('Browser storage is unavailable. Your learning record remains in this tab only.'); }
    renderHistory();
  }
  function downloadJSON(value, name) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + '\n'], { type: 'application/json' }));
    const link = el('a'); link.href = url; link.download = name; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function renderHistory() {
    const box = $('quiz-history'); box.replaceChildren();
    for (const phase of ['pre', 'post']) if (state.quiz[phase]) box.append(el('p', (phase === 'pre' ? 'Pre-lab: ' : 'Post-lab: ') + state.quiz[phase].score + ' / 10'));
    if (state.quiz.pre && state.quiz.post) box.append(el('p', 'Change: ' + (state.quiz.post.score - state.quiz.pre.score >= 0 ? '+' : '') + (state.quiz.post.score - state.quiz.pre.score) + ' points. Repeated questions can create a practice effect.'));
  }
  const QUIZ = [
    { q: 'What is the main job of a model runtime?', choices: ['Store your browser history', 'Load model weights and execute inference', 'Train a new model every time you ask', 'Upload all prompts to a cloud service'], correct: 1, why: 'The runtime executes the model. The model weights and the program that runs them are separate components.' },
    { q: 'What does “1.5B” in a model name usually describe?', choices: ['About 1.5 billion learned parameters', 'A guaranteed 1.5 GiB memory requirement', '1.5 billion requests per second', 'The number of users it can support'], correct: 0, why: 'Parameter count describes learned numbers. Quantization, context, runtime, and hardware also affect memory needs.' },
    { q: 'What is a typical benefit and trade-off of lower-bit quantization?', choices: ['Higher disk use with no quality change', 'Guaranteed better answers', 'Lower weight storage, with a possible quality cost', 'Elimination of all working memory'], correct: 2, why: 'Fewer bits per weight can reduce storage and memory. Answer quality and speed depend on the specific model, runtime, and hardware.' },
    { q: 'The client-observed TTFT proxy in this lab measures…', choices: ['Total time to finish the answer', 'Time to download model weights', 'How many words fit in memory', 'Time from request start to the first non-empty response text'], correct: 3, why: 'This first-response-text latency includes prompt processing. It approximates the initial wait but does not establish a true token boundary, and is distinct from output generation speed.' },
    { q: 'Which calculation best represents generation TPS in this lab?', choices: ['Prompt words divided by RAM', 'Output token count divided by runtime decode duration', 'Total wall time divided by output tokens', 'CPU utilization multiplied by model size'], correct: 1, why: 'Decode TPS uses the runtime output token count and decode duration. It excludes the input prompt-processing phase.' },
    { q: 'A model generates quickly but CPU use is low. Which explanation is plausible?', choices: ['The measurement proves no computation happened', 'The model must be using the internet', 'A GPU may be doing much of the inference', 'The answers must be correct'], correct: 2, why: 'CPU utilization is not GPU utilization. Accelerator offload is a possible explanation, but should be checked against the recorded environment.' },
    { q: 'What does peak process RSS tell you?', choices: ['Observed resident memory of the attributed processes', 'Exact dedicated GPU memory', 'The model’s total training dataset size', 'A guaranteed total system-memory requirement'], correct: 0, why: 'RSS is a sampled process-memory measure. It omits dedicated GPU memory and can double-count shared pages when summed across processes.' },
    { q: 'Why exclude the warm-up request from steady-state comparisons?', choices: ['It always has the best answer', 'It removes the need to report errors', 'It makes every laptop identical', 'Initial loading can add time that is different from warmed inference'], correct: 3, why: 'Warm-up helps separate loading from steady-state behavior. Caching, heat, and background workloads can still affect later runs.' },
    { q: 'Which comparison is most defensible?', choices: ['Any two TPS numbers from the internet', 'Repeated runs with matching prompt, model digest, and generation settings', 'The fastest run on one device versus the slowest on another', 'A missing metric treated as zero'], correct: 1, why: 'Control the conditions, report repeats and range, and retain failed or unavailable measurements. A speed comparison does not establish answer quality.' },
    { q: 'An installation error suggests disabling a security feature or using administrator commands. What should you do?', choices: ['Paste credentials into the assistant', 'Disable the protection and continue', 'Stop and seek a user-account alternative or team guidance', 'Delete unknown system files'], correct: 2, why: 'Keep the lab within a normal user account and preserve security protections. Ask for help when your device policy prevents installation.' }
  ];
  function openQuiz(phase) {
    state.phase = phase;
    if (location.hash !== '#learn') location.hash = 'learn';
    $('quiz-section').hidden = false;
    $('quiz-title').textContent = phase === 'pre' ? 'Pre-lab knowledge check' : 'Post-lab knowledge check';
    $('quiz-feedback').replaceChildren();
    const form = $('quiz-form'); form.replaceChildren();
    QUIZ.forEach((item, i) => {
      const field = el('fieldset', undefined, 'quiz-question');
      field.append(el('legend', String(i + 1).padStart(2, '0') + ' / ' + item.q));
      const choices = el('div', undefined, 'quiz-options');
      item.choices.forEach((choice, j) => {
        const label = el('label', undefined, 'quiz-option'), input = el('input'); input.type = 'radio'; input.name = 'q' + i; input.value = String(j); input.required = true;
        label.append(input, el('span', choice)); choices.append(label);
      });
      field.append(choices); form.append(field);
    });
    const submit = el('button', 'Submit knowledge check', 'button primary'); submit.type = 'submit'; form.append(submit);
    requestAnimationFrame(() => { $('quiz-section').scrollIntoView({ block: 'start' }); $('quiz-title').focus({ preventScroll: true }); });
  }
  $('start-pre').addEventListener('click', () => openQuiz('pre'));
  $('start-post').addEventListener('click', () => openQuiz('post'));
  $('close-quiz').addEventListener('click', () => { $('quiz-section').hidden = true; $('start-pre').focus(); });
  $('quiz-form').addEventListener('submit', event => {
    event.preventDefault();
    const form = event.currentTarget, answers = QUIZ.map((_, i) => Number(new FormData(form).get('q' + i)));
    const score = answers.filter((a, i) => a === QUIZ[i].correct).length;
    state.quiz[state.phase] = { score, answers, completed_at: new Date().toISOString() };
    form.querySelectorAll('.quiz-answer').forEach(n => n.remove());
    form.querySelectorAll('fieldset').forEach((field, i) => {
      const right = answers[i] === QUIZ[i].correct;
      field.append(el('p', (right ? 'Correct. ' : 'Review: ' + QUIZ[i].choices[QUIZ[i].correct] + '. ') + QUIZ[i].why, 'quiz-answer ' + (right ? 'correct' : 'incorrect')));
    });
    const result = el('div', undefined, 'quiz-result'); result.append(el('h3', score + ' / 10'), el('p', 'Review the explanations above. ' + (state.consent ? 'Your latest result is saved in this browser.' : 'Your result stays in this tab unless you choose to save or export it.')));
    if (state.quiz.pre && state.quiz.post) result.append(el('p', 'Pre-lab ' + state.quiz.pre.score + ' → post-lab ' + state.quiz.post.score + '. This repeated-question check can show practice effects; it is not proof of a causal learning gain.'));
    $('quiz-feedback').replaceChildren(result); persistLearning(); result.scrollIntoView({ block: 'center' });
  });
  $('remember-learning').addEventListener('change', event => { state.consent = event.target.checked; persistLearning(); toast(state.consent ? 'Quiz results and numeric predictions will be saved in this browser.' : 'Saved learning data removed. Current results remain in this tab.'); });
  $('export-learning').addEventListener('click', () => { downloadJSON(learningRecord(), 'local-ai-lab-learning.json'); toast('Anonymous learning record exported.'); });
  $('clear-learning').addEventListener('click', () => {
    state.consent = false; state.prediction = null; state.quiz = { pre: null, post: null }; $('remember-learning').checked = false;
    $('prediction-form').reset(); $('prediction-summary').hidden = true; $('prediction-status').textContent = ''; $('quiz-section').hidden = true;
    persistLearning(); renderResults(); toast('Saved learning data and this tab’s quiz results cleared.');
  });
  function displayPrediction() {
    if (!state.prediction) return;
    $('prediction-tps').value = state.prediction.tps; $('prediction-ram').value = state.prediction.ram_gib;
    $('prediction-summary').hidden = false;
    $('prediction-summary').replaceChildren(el('p', 'Recorded: ' + format(state.prediction.tps) + ' tokens/s and ' + format(state.prediction.ram_gib, 2) + ' GiB. Enter the same values in the helper before running the experiment.', 'fine-print'));
  }
  $('prediction-form').addEventListener('submit', event => {
    event.preventDefault();
    const tps = $('prediction-tps').valueAsNumber, ram = $('prediction-ram').valueAsNumber;
    if (!Number.isFinite(tps) || !Number.isFinite(ram) || tps < 0 || ram < 0 || tps > 1000000 || ram > 1048576) { $('prediction-status').textContent = 'Enter finite, non-negative values within the displayed range.'; return; }
    state.prediction = { tps, ram_gib: ram }; persistLearning(); displayPrediction(); renderResults();
    $('prediction-status').textContent = 'Prediction recorded ' + (state.consent ? 'and saved in this browser.' : 'in this tab.');
  });

  function setPlatform(platform) {
    const mac = platform === 'macos';
    document.querySelectorAll('[data-platform]').forEach(node => { const active = node.dataset.platform === platform; node.classList.toggle('active', active); node.setAttribute('aria-pressed', String(active)); });
    $('platform-requirements').textContent = mac ? 'Ollama currently documents macOS 14 or newer; Apple Silicon supports CPU/GPU inference, while Intel Macs use CPU inference. Start with a working user-accessible Python and runtime.' : 'Ollama currently documents Windows 10 22H2 or newer. Its standard installer uses your account without administrator rights. Managed computers may restrict installing Python or a runtime; ask the team if they do.';
    $('runtime-instructions').textContent = mac ? 'For a user-account setup, place Ollama.app in a folder you own, such as ~/Applications, and open it there. Decline a request to move it to the system Applications folder or create a system-wide command link. The app bundle contains its own CLI at Ollama.app/Contents/Resources/ollama; the helper can use that path.' : 'Use the official Ollama installer and keep the default per-user location. Open Ollama, then open a new ordinary terminal so it sees the user PATH. Do not choose “Run as administrator.”';
    $('runtime-docs').href = mac ? 'https://docs.ollama.com/macos' : 'https://docs.ollama.com/windows';
    $('shell-label').textContent = mac ? 'TERMINAL · INSIDE AGENT/' : 'POWERSHELL · INSIDE AGENT/';
    $('bootstrap-command').textContent = mac ? 'python3 -m venv .venv\n.venv/bin/python -m pip install -r requirements.txt' : 'py -3 -m venv .venv\n.venv\\Scripts\\python.exe -m pip install -r requirements.txt';
    $('helper-command').textContent = mac ? '.venv/bin/python -m telemetry_agent.helper' : '.venv\\Scripts\\python.exe -m telemetry_agent.helper';
  }
  document.querySelectorAll('[data-platform]').forEach(node => node.addEventListener('click', () => setPlatform(node.dataset.platform)));
  document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($(button.dataset.copy).textContent); toast('Commands copied. Read them before running them in your terminal.'); }
    catch (_) { toast('Copy is unavailable here. Select and copy the visible commands manually.'); }
  }));

  function importMessage(name, result) {
    const item = el('div', undefined, 'import-message' + (result.errors.length ? ' error' : ''));
    item.append(el('strong', name + (result.errors.length ? ' — not imported' : ' — imported')));
    (result.errors.length ? result.errors.slice(0, 6) : result.warnings).forEach(message => item.append(el('p', message)));
    if (result.errors.length > 6) item.append(el('p', 'And ' + (result.errors.length - 6) + ' more validation errors. Re-export this session from the current helper.'));
    $('import-messages').append(item);
  }
  async function importFiles(files) {
    const generation = ++state.importGeneration;
    $('import-messages').replaceChildren();
    if (files.length > 30) { importMessage('Selection', { errors: ['Choose no more than 30 files at once.'], warnings: [] }); return; }
    for (const file of files) {
      if (!/\.json$/i.test(file.name)) { importMessage(file.name, { errors: ['Choose a .json session export. CSV and learning-record exports are not benchmark sessions.'], warnings: [] }); continue; }
      if (file.size > D.MAX_FILE_BYTES) { importMessage(file.name, { errors: ['File exceeds the 5 MiB limit.'], warnings: [] }); continue; }
      try {
        const text = await file.text();
        if (generation !== state.importGeneration) return;
        let result = D.parseSession(text, file.size);
        if (result.session) result = D.addSession(state.sessions, result.session);
        if (result.session) state.sessions.push(result.session);
        importMessage(file.name, result);
      } catch (_) { if (generation !== state.importGeneration) return; importMessage(file.name, { errors: ['Could not read this local file. Try exporting it again.'], warnings: [] }); }
    }
    updateFilters(); renderResults();
  }
  $('session-files').addEventListener('change', async event => { await importFiles(Array.from(event.target.files)); event.target.value = ''; });
  $('import-json').addEventListener('click', () => $('session-files').click());
  async function loadExamples() {
    const generation = ++state.importGeneration;
    $('import-messages').replaceChildren();
    $('load-examples').disabled = true; $('hero-example').disabled = true;
    for (const file of ['synthetic-macos.json', 'synthetic-windows.json']) {
      try {
        const response = await fetch('examples/' + file, { credentials: 'omit', cache: 'no-store' });
        if (!response.ok) throw new Error('example unavailable');
        const text = await response.text();
        if (generation !== state.importGeneration) break;
        let result = D.parseSession(text);
        if (result.session && result.session.data_kind !== 'synthetic') result = { session: null, errors: ['Bundled examples must be labeled synthetic.'], warnings: [] };
        if (result.session) result = D.addSession(state.sessions, result.session);
        if (result.session) state.sessions.push(result.session);
        importMessage(file, result);
      } catch (_) { if (generation === state.importGeneration) importMessage(file, { errors: ['The example could not load. Serve the portal over HTTP, or import the files from portal/examples manually.'], warnings: [] }); }
    }
    $('load-examples').disabled = false; $('hero-example').disabled = false;
    updateFilters(); renderResults();
  }
  $('load-examples').addEventListener('click', loadExamples);
  $('hero-example').addEventListener('click', () => { location.hash = 'results'; loadExamples(); });
  $('clear-results').addEventListener('click', () => { ++state.importGeneration; state.sessions = []; $('import-messages').replaceChildren(); $('filter-kind').value = ''; updateFilters(); renderResults(); toast('Imported sessions removed from this tab.'); });
  function updateSelect(id, values, label) {
    const select = $(id), current = select.value; select.replaceChildren();
    const all = el('option', label); all.value = ''; select.append(all);
    for (const value of [...new Set(values)].sort()) { const option = el('option', value); option.value = value; select.append(option); }
    if (values.includes(current)) select.value = current;
  }
  function updateFilters() {
    updateSelect('filter-device', state.sessions.map(s => s.device.alias), 'All devices');
    updateSelect('filter-model', state.sessions.map(s => s.model.name), 'All models');
    updateSelect('filter-prompt', state.sessions.flatMap(s => s.runs.map(r => r.prompt_id)), 'All prompts');
  }
  function filters() { return { device: $('filter-device').value, model: $('filter-model').value, prompt: $('filter-prompt').value, kind: $('filter-kind').value }; }
  for (const id of ['filter-device', 'filter-model', 'filter-prompt', 'filter-kind']) $(id).addEventListener('change', renderResults);
  function metricCards(summary) {
    $('metric-cards').replaceChildren();
    for (const [key, metric] of Object.entries(D.METRICS)) {
      const value = summary.metrics[key], card = el('article', undefined, 'metric-card');
      card.append(el('div', metric.short + ' · MEDIAN', 'metric-label'));
      const number = el('div', format(value.median), 'metric-value'); number.append(el('span', metric.unit)); card.append(number);
      card.append(el('div', value.count ? format(value.min) + '–' + format(value.max) + ' ' + metric.unit + ' · n=' + value.count : 'No valid values', 'metric-range'));
      card.append(el('p', metric.note, 'metric-note')); $('metric-cards').append(card);
    }
  }
  const SVG_NS = 'http://www.w3.org/2000/svg';
  function svgNode(tag, attrs, text) { const node = document.createElementNS(SVG_NS, tag); for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, String(value)); if (text !== undefined) node.textContent = text; return node; }
  function renderCharts(rows) {
    const sessions = state.sessions.filter(s => rows.some(r => r.session === s)); $('charts').replaceChildren();
    for (const [key, metric] of Object.entries(D.METRICS)) {
      const series = sessions.map(session => ({ session, stats: D.aggregate(rows.filter(r => r.session === session)).metrics[key] }));
      const card = el('article', undefined, 'chart-card'); card.append(el('h3', metric.label), el('p', metric.unit + ' · range with median marker'));
      const h = 55 + series.length * 48, svg = svgNode('svg', { viewBox: '0 0 480 ' + h, role: 'img', 'aria-label': metric.label + ' comparison; full values are listed below the chart' });
      const top = 28, left = 140, width = 290, max = Math.max(1, ...series.map(s => s.stats.max || 0)) * 1.08;
      for (let t = 0; t <= 4; t++) {
        const x = left + width * t / 4;
        svg.append(svgNode('line', { x1: x, y1: 15, x2: x, y2: h - 22, stroke: '#e3e8db', 'stroke-dasharray': t ? '2 4' : '0' }));
        svg.append(svgNode('text', { x, y: h - 3, 'font-size': 8, 'text-anchor': 'middle' }, format(max * t / 4, max < 10 ? 1 : 0)));
      }
      const details = el('details', undefined, 'chart-data'); details.append(el('summary', 'Read exact chart values')); const list = el('ul');
      series.forEach(({ session, stats }, i) => {
        const y = top + i * 48, name = session.device.alias.length > 20 ? session.device.alias.slice(0, 18) + '…' : session.device.alias;
        const label = svgNode('text', { x: 0, y: y + 2, 'font-size': 10, 'font-weight': 600 }, name); label.append(svgNode('title', {}, session.device.alias)); svg.append(label);
        svg.append(svgNode('text', { x: 0, y: y + 16, 'font-size': 7.5 }, session.data_kind.toUpperCase() + ' · ' + session.created_at.slice(0, 10)));
        const color = session.data_kind === 'synthetic' ? '#a78432' : '#2f6b55';
        if (stats.count) {
          const x = n => left + width * n / max;
          svg.append(svgNode('rect', { x: left, y: y - 7, width: x(stats.median) - left, height: 15, rx: 2, fill: color, opacity: '.14' }));
          svg.append(svgNode('line', { x1: x(stats.min), y1: y, x2: x(stats.max), y2: y, stroke: color, 'stroke-width': 2 }));
          for (const v of [stats.min, stats.max]) svg.append(svgNode('line', { x1: x(v), y1: y - 4, x2: x(v), y2: y + 4, stroke: color, 'stroke-width': 1.3 }));
          svg.append(svgNode('circle', { cx: x(stats.median), cy: y, r: 4, fill: color }));
          list.append(el('li', session.device.alias + ' / ' + session.session_id + ' (' + session.data_kind + '): median ' + format(stats.median) + ' ' + metric.unit + ', range ' + format(stats.min) + '–' + format(stats.max) + ', n=' + stats.count + '.'));
        } else {
          svg.append(svgNode('text', { x: left + 10, y: y + 3, 'font-size': 10 }, 'Unavailable'));
          list.append(el('li', session.device.alias + ' / ' + session.session_id + ': no valid ' + metric.short + ' values.'));
        }
      });
      details.append(list); card.append(svg, details); $('charts').append(card);
    }
  }
  function addMeta(dl, title, value) { const group = el('div'); group.append(el('dt', title), el('dd', value)); dl.append(group); }
  function renderSessions(rows) {
    $('session-list').replaceChildren();
    const sessions = state.sessions.filter(s => rows.some(r => r.session === s));
    for (const session of sessions) {
      const record = el('details', undefined, 'session-record'), summary = el('summary'), title = el('span', session.device.alias + ' / ' + session.model.name), badge = el('span', session.data_kind.toUpperCase(), 'kind-badge ' + session.data_kind);
      title.append(badge); summary.append(title); record.append(summary);
      const dl = el('dl', undefined, 'session-meta');
      addMeta(dl, 'Session / created', session.session_id + ' · ' + session.created_at);
      addMeta(dl, 'Device', session.device.os + ' ' + session.device.os_version + ' · ' + session.device.arch);
      addMeta(dl, 'CPU / RAM', session.device.cpu_model + ' · ' + session.device.logical_cores + ' logical cores · ' + format(session.device.total_ram_gib, 2) + ' GiB');
      addMeta(dl, 'GPU / acceleration', session.device.gpu + ' · ' + session.model.acceleration);
      addMeta(dl, 'Runtime / quantization', session.runtime.name + ' ' + unknown(session.runtime.version) + ' · ' + unknown(session.model.quantization));
      addMeta(dl, 'Model digest', unknown(session.model.digest));
      addMeta(dl, 'Settings', 'temperature ' + session.config.temperature + ' · output cap ' + session.config.max_output_tokens + ' · context ' + unknown(session.config.context_tokens) + ' · repeats ' + session.config.repeats);
      addMeta(dl, 'Warm-up', format(session.warmup_round_trip_s, 3) + ' s round trip · excluded from summaries');
      record.append(dl);
      const sourceDetails = el('details'); sourceDetails.append(el('summary', 'Source methods and quality flags'));
      const evidence = session.runs.filter(run => rows.some(r => r.run === run)).map(run => ({ run_id: run.run_id, prompt: run.prompt_id, status: run.status, sources: run.sources, quality_flags: run.quality_flags, error: run.error }));
      sourceDetails.append(el('pre', JSON.stringify(evidence, null, 2))); record.append(sourceDetails); $('session-list').append(record);
    }
  }
  function predictionComparisons(rows) {
    const box = $('prediction-comparison'); box.replaceChildren();
    const sessions = state.sessions.filter(s => rows.some(r => r.session === s));
    const comparable = sessions.filter(s => s.predictions.tps !== null || s.predictions.ram_gib !== null || (s.data_kind === 'measured' && state.prediction));
    box.hidden = !comparable.length; if (!comparable.length) return;
    box.append(el('p', 'PREDICTION → OBSERVATION', 'eyebrow'), el('h2', 'What surprised you?'));
    const wrap = el('div', undefined, 'table-wrap'), table = el('table', undefined, 'prediction-table'), head = el('thead'), tr = el('tr');
    for (const name of ['Session', 'Predicted TPS', 'Actual TPS', 'Predicted GiB', 'Actual RSS GiB']) { const th = el('th', name); th.scope = 'col'; tr.append(th); } head.append(tr); table.append(head);
    const body = el('tbody');
    for (const session of comparable) {
      const stats = D.aggregate(rows.filter(r => r.session === session)), fallback = session.data_kind === 'measured' ? state.prediction : null;
      const prediction = { tps: session.predictions.tps ?? fallback?.tps ?? null, ram_gib: session.predictions.ram_gib ?? fallback?.ram_gib ?? null };
      const row = el('tr'), label = el('td', session.device.alias + ' · ' + session.data_kind);
      if ((session.predictions.tps === null || session.predictions.ram_gib === null) && fallback) label.append(el('small', 'Uses current tab prediction for missing exported guesses'));
      row.append(label, el('td', format(prediction.tps)), el('td', format(stats.metrics.decode_tps.median)), el('td', format(prediction.ram_gib, 2)), el('td', stats.metrics.peak_rss_mib.median === null ? '—' : format(stats.metrics.peak_rss_mib.median / 1024, 2))); body.append(row);
    }
    table.append(body); wrap.append(table); box.append(wrap, el('p', 'Actual values are medians of available selected runs. Actual RAM is the median of per-run RSS peaks, converted from MiB to GiB (÷1024). A difference is a question to investigate, not a score for prediction accuracy.', 'fine-print'));
  }
  function renderResults() {
    const rows = D.filterRuns(state.sessions, filters()), summary = D.aggregate(rows);
    $('clear-results').disabled = !state.sessions.length;
    $('empty-results').hidden = rows.length > 0; $('results-content').hidden = rows.length === 0;
    $('synthetic-banner').hidden = !rows.some(r => r.session.data_kind === 'synthetic');
    if (!rows.length) {
      $('empty-results').querySelector('h2').textContent = state.sessions.length ? 'No runs match these filters.' : 'Your next discovery starts here.';
      $('empty-results').querySelector('p').textContent = state.sessions.length ? 'Try another device, model, prompt, or data type.' : 'Import a helper export, or explore clearly labeled synthetic examples to learn how to read the charts.';
      return;
    }
    const counts = $('run-counts'); counts.replaceChildren();
    for (const [label, value] of [['total runs', summary.total], ['complete', summary.ok], ['partial', summary.partial], ['failed', summary.failed]]) { const span = el('span'); span.append(el('b', String(value)), document.createTextNode(label)); counts.append(span); }
    const conditions = new Set(rows.map(r => [r.session.device.alias, r.session.model.digest || r.session.model.name, r.session.runtime.version, JSON.stringify(r.session.config), r.session.data_kind].join('|')));
    $('comparison-caution').textContent = conditions.size > 1 ? 'Multiple conditions are selected. Pooled medians below are descriptive only; use session charts and filters for fair comparisons. Synthetic and measured values must not be combined as evidence.' : 'Summary statistics are recomputed from run records. Imported summary numbers are not trusted. Nulls and failed runs are excluded per metric; zero is retained as a valid recorded value.';
    metricCards(summary); renderCharts(rows); renderSessions(rows); predictionComparisons(rows);
    const body = $('runs-table'); body.replaceChildren();
    for (const { session, run } of rows) {
      const row = el('tr'), label = el('td', session.device.alias + ' / ' + run.prompt_id + ' #' + run.repeat_index); label.append(el('small', session.data_kind.toUpperCase() + ' · ' + run.run_id));
      const status = el('td'); status.append(el('span', run.status, 'status-badge ' + run.status));
      row.append(label, status); for (const metric of Object.keys(D.METRICS)) row.append(el('td', run.status === 'error' ? '—' : format(run.measurements[metric]))); body.append(row);
    }
  }

  try {
    const saved = safeLearningRecord(JSON.parse(localStorage.getItem(STORAGE_KEY)));
    if (saved) { state.prediction = saved.prediction; state.quiz = saved.quiz; state.consent = true; $('remember-learning').checked = true; }
  } catch (_) { /* Storage may be disabled. The entire lab remains usable in memory. */ }
  route(); setPlatform('macos'); renderHistory(); displayPrediction(); renderResults();
})();

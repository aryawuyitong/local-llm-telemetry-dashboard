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
  const glossary = {
    ttft_ms: 'The wait from sending a request until the first visible response text. This is a proxy, not the exact first-token time.',
    decode_tps: 'Tokens per second: how quickly the model generates text after prompt processing.',
    cpu_percent_normalized: 'The observed runtime CPU use divided by logical core count. GPU work is not included.',
    peak_rss_mib: 'Resident Set Size: sampled memory held by the runtime processes. Shared pages can be counted twice; this is not GPU memory.'
  };
  function termHelp(label, metric) {
    const details = el('details', undefined, 'term-help');
    const summary = el('summary');
    summary.append(document.createTextNode(label + ' '), el('span', 'ⓘ', 'term-icon'));
    details.append(summary, el('span', glossary[metric], 'term-definition'));
    return details;
  }
  let toastTimer;
  function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4500); }

  // Old links still work: Models and Apps are now the Catalog, and measuring is one page.
  const ALIAS = { models: 'catalog', apps: 'catalog', predict: 'measure' };
  const PARTS = { measure: ['predict', 'results'] };
  const TITLES = { browser: 'Browser lab', learn: 'Learn', preview: 'Demo', start: 'Start guide', catalog: 'Catalog', use: 'Use it', measure: 'Measure', results: 'Results', mylab: 'My lab' };
  function route() {
    const lab = document.documentElement.dataset.mode === 'lab';
    const asked = location.hash.slice(1);
    let view = ALIAS[asked] || asked;
    if (view !== 'deploy' && !TITLES[view]) view = 'deploy';
    // The website and desktop lab each have a dedicated benchmark view.
    if (lab && view === 'results') view = 'measure';
    if (lab && (view === 'preview' || view === 'start' || view === 'browser')) view = 'deploy';
    if (!lab && view === 'measure') view = 'results';
    if (!lab && (view === 'use' || view === 'mylab')) view = 'deploy';
    const parts = PARTS[view] || [view];
    document.querySelectorAll('.view').forEach(node => { node.hidden = !parts.includes(node.id.slice(5)); });
    document.querySelectorAll('[data-view]').forEach(node => { if (node.dataset.view === view) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current'); });
    document.title = ['Local AI Lab', view === 'deploy' ? (lab ? 'Set up' : 'Home') : TITLES[view]].join(' · ');
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
    { q: 'You type a question into a model running on your laptop. Where do your words go?', choices: ['To the company that made the model, which sends an answer back', 'Nowhere else. They stay on your laptop', 'To Ollama’s website, which does the thinking', 'To the cloud, but only while you have internet'], correct: 1, why: 'A local model runs on your own laptop, so your words never leave it. A cloud service like ChatGPT sends them to someone else’s computers and back.' },
    { q: 'What is the difference between Ollama and the model file you download?', choices: ['Ollama is the engine that runs models; the model is a file of learned numbers', 'They are the same thing with two names', 'Ollama is the model; the file is a backup of its settings', 'The model file is the program; Ollama is just the folder it sits in'], correct: 0, why: 'Ollama is the engine. The model is a file of learned numbers. A downloaded model does nothing on its own until an engine loads it.' },
    { q: 'Your laptop has 8 GB of memory. Which of these should you start with?', choices: ['The biggest model, because bigger is always better', 'A small model, about 1 to 2 billion parameters', 'Any model. Memory only changes the download time', 'None. No model runs on 8 GB'], correct: 1, why: 'Start small. A model needs free memory to load, and a bigger model needs more. On 8 GB, a 1–2B model fits with room left for your other apps.' },
    { q: 'What does the “Download a model” step add to your laptop, and how do you undo it?', choices: ['One model file in Ollama’s folder. Click Undo, or run ollama rm', 'A new app in Applications. Drag it to the Trash', 'Changes to system settings. Reinstall your system to undo them', 'Files in many folders. It cannot be undone'], correct: 0, why: 'The download adds one model file inside Ollama’s models folder. Undo in the lab, or ollama rm with the model’s name, removes it again.' },
    { q: 'A setup step asks for your admin password, or to turn off a security setting. What do you do?', choices: ['Type it in. Setup usually needs it', 'Turn security off for a minute, then turn it back on', 'Stop. This lab never needs it. Ask the team', 'Skip that step and carry on with the next one'], correct: 2, why: 'Nothing in this lab needs your password or a security change. If a step asks for one, something is off: stop and ask the team.' },
    { q: 'A local model gives a confident answer that turns out to be wrong. Why can that happen?', choices: ['It predicts the next likely token. It does not look facts up', 'It lost internet, so it could not check', 'The download was damaged on the way', 'Small models give wrong answers on purpose'], correct: 0, why: 'The model predicts which token likely comes next, again and again. That is prediction, not looking things up, so a reply can sound sure and still be wrong.' },
    { q: 'The lab reports “18 tokens per second”. In plain words, what does that tell you?', choices: ['How fast the reply appears. Tokens are pieces of words', 'How many questions you can ask each second', 'How much memory the model is using', 'How accurate the answers are'], correct: 0, why: 'Tokens are pieces of words. Tokens per second is how quickly the reply appears on your screen. It says nothing about whether the answer is right.' },
    { q: 'Before measuring, the lab asks you to guess the speed and memory. Why guess first?', choices: ['Your guess is used to set the model up', 'A guess gives the measurement something to teach you', 'The lab needs a number to start its timer', 'A good guess earns a higher quiz score'], correct: 1, why: 'If you guess first, the real number can surprise you, and a surprise is where learning happens. Without a guess, it is just a number.' },
    { q: 'The model runs, but each reply crawls out very slowly. What is the most likely reason?', choices: ['Your internet connection is slow', 'Too little free memory for its size, often because other apps are open', 'The model file did not download properly', 'The model needs a license before it runs at full speed'], correct: 1, why: 'A local model does not use the internet to reply. Slow replies usually mean the model is too big for the free memory, often because other apps are open.' },
    { q: 'You click “Show on my laptop” for a downloaded model. What opens, and what should you not do?', choices: ['Ollama’s models folder, with a file named by a code. Don’t move or rename it', 'A text file of the model’s past answers. Don’t share it', 'A file named after the model. Rename it to anything you like', 'The Ollama app’s settings. Don’t change them'], correct: 0, why: 'Models live in Ollama’s models folder, in files named by a code rather than the model’s name. If you move or rename one, Ollama can’t find it.' }
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
    // The pre-lab check shows only the score, so the post-lab check asks the same questions fresh.
    const showFeedback = state.phase === 'post';
    if (showFeedback) form.querySelectorAll('fieldset').forEach((field, i) => {
      const right = answers[i] === QUIZ[i].correct;
      field.append(el('p', (right ? 'Correct. ' : 'Review: ' + QUIZ[i].choices[QUIZ[i].correct] + '. ') + QUIZ[i].why, 'quiz-answer ' + (right ? 'correct' : 'incorrect')));
    });
    const result = el('div', undefined, 'quiz-result'); result.append(el('h3', score + ' / 10'), el('p', (showFeedback ? 'Review the explanations above. ' : 'You’ll see the explanations after the post-lab quiz. ') + (state.consent ? 'Your latest result is saved in this browser.' : 'Your result stays in this tab unless you choose to save or export it.')));
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

  // The manual 7-step walkthrough now lives in the README, so these elements are usually absent. Each write is guarded.
  const setText = (id, text) => { const node = $(id); if (node) node.textContent = text; };
  function setPlatform(platform) {
    const mac = platform === 'macos';
    document.querySelectorAll('[data-platform]').forEach(node => { const active = node.dataset.platform === platform; node.classList.toggle('active', active); node.setAttribute('aria-pressed', String(active)); });
    setText('platform-requirements', mac ? 'On macOS, use Terminal or the VS Code terminal. Check Ollama’s current system requirements on its official page before installing.' : 'On Windows, use PowerShell or the VS Code terminal. Check Ollama’s current system requirements on its official page before installing.');
    setText('runtime-instructions', mac ? 'For a user-account setup, place Ollama.app in a folder you own, such as ~/Applications, and open it there. Decline a request to move it to the system Applications folder or create a system-wide command link. The app bundle contains its own CLI at Ollama.app/Contents/Resources/ollama; the helper can use that path.' : 'Use the official Ollama installer and keep the default per-user location. Open Ollama, then open a new ordinary terminal so it sees the user PATH. Do not choose “Run as administrator.”');
    const docs = $('runtime-docs'); if (docs) docs.href = mac ? 'https://docs.ollama.com/macos' : 'https://docs.ollama.com/windows';
    setText('python-check-command', mac ? 'python3 --version' : 'py -3 --version');
    setText('shell-label', mac ? 'MACOS TERMINAL · START IN PROJECT FOLDER' : 'WINDOWS POWERSHELL · START IN PROJECT FOLDER');
    setText('bootstrap-command', mac ? 'cd agent\npython3 -m venv .venv\n.venv/bin/python -m pip install -r requirements.txt' : 'cd agent\npy -3 -m venv .venv\n.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt');
    setText('helper-command', mac ? 'AGENT_MODEL=qwen2.5:1.5b .venv/bin/python -m telemetry_agent.helper' : '$env:AGENT_MODEL = "qwen2.5:1.5b"\n.\\.venv\\Scripts\\python.exe -m telemetry_agent.helper');
  }
  document.querySelectorAll('[data-platform]').forEach(node => node.addEventListener('click', () => setPlatform(node.dataset.platform)));
  document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    try { const source = $(button.dataset.copy); if (!source) throw new Error('missing'); await navigator.clipboard.writeText(source.textContent); toast('Commands copied. Read them before running them in your terminal.'); }
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
  // These measured sessions come from the token-protected local helper.
  window.LocalLabPortal = {
    showLocalSessions(sessionTexts) {
      if (document.documentElement.dataset.mode !== 'lab') return;
      state.sessions = [];
      $('import-messages').replaceChildren();
      for (const sessionText of sessionTexts) {
        if (sessionText.length > D.MAX_FILE_BYTES) continue;
        let result = D.parseSession(sessionText);
        if (result.session) result = D.addSession(state.sessions, result.session);
        if (result.session) state.sessions.push(result.session);
        if (result.errors?.length) importMessage('This laptop', result);
      }
      updateFilters(); renderResults();
    },
  };
  async function loadExamples() {
    const generation = ++state.importGeneration;
    $('import-messages').replaceChildren();
    $('load-examples').disabled = true;
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
    $('load-examples').disabled = false;
    updateFilters(); renderResults();
  }
  $('load-examples').addEventListener('click', loadExamples);
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
      const heading = el('div', undefined, 'metric-label');
      heading.append(termHelp(metric.short, key), el('span', 'MEDIAN'));
      card.append(heading);
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
        svg.append(svgNode('text', { x, y: h - 3, 'font-size': 10, 'text-anchor': 'middle' }, format(max * t / 4, max < 10 ? 1 : 0)));
      }
      const details = el('details', undefined, 'chart-data'); details.append(el('summary', 'Read exact chart values')); const list = el('ul');
      series.forEach(({ session, stats }, i) => {
        const y = top + i * 48, name = session.model.name.length > 20 ? session.model.name.slice(0, 18) + '…' : session.model.name;
        const label = svgNode('text', { x: 0, y: y + 2, 'font-size': 10, 'font-weight': 600 }, name); label.append(svgNode('title', {}, session.model.name + ' · ' + session.device.alias)); svg.append(label);
        svg.append(svgNode('text', { x: 0, y: y + 16, 'font-size': 10 }, session.data_kind.toUpperCase() + ' · ' + session.created_at.slice(0, 10)));
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
      addMeta(dl, 'GPU / Ollama offload', session.device.gpu + ' · ' + (session.model.acceleration === 'gpu-assisted' ? 'GPU-assisted (runtime report)' : session.model.acceleration === 'cpu' ? 'CPU-only (runtime report)' : 'Not verified') + '; GPU utilization not measured');
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
    for (const name of ['Session', 'Your speed guess', 'Measured speed', 'Your memory guess (GiB)', 'Measured memory (GiB)']) { const th = el('th', name); th.scope = 'col'; tr.append(th); } head.append(tr); table.append(head);
    const body = el('tbody');
    for (const session of comparable) {
      const stats = D.aggregate(rows.filter(r => r.session === session)), fallback = session.data_kind === 'measured' ? state.prediction : null;
      const prediction = { tps: session.predictions.tps ?? fallback?.tps ?? null, ram_gib: session.predictions.ram_gib ?? fallback?.ram_gib ?? null };
      const row = el('tr'), label = el('td', session.device.alias + ' · ' + session.data_kind);
      if ((session.predictions.tps === null || session.predictions.ram_gib === null) && fallback) label.append(el('small', 'Uses current tab prediction for missing exported guesses'));
      row.append(label, el('td', format(prediction.tps)), el('td', format(stats.metrics.decode_tps.median)), el('td', format(prediction.ram_gib, 2)), el('td', stats.metrics.peak_rss_mib.median === null ? '—' : format(stats.metrics.peak_rss_mib.median / 1024, 2))); body.append(row);
    }
    table.append(body); wrap.append(table); box.append(wrap, el('p', 'Measured values are the middle result of the selected runs. A difference is a question to investigate, not a score.', 'fine-print'));
  }
  function renderResults() {
    const rows = D.filterRuns(state.sessions, filters()), summary = D.aggregate(rows);
    $('clear-results').disabled = !state.sessions.length;
    $('empty-results').hidden = rows.length > 0; $('results-content').hidden = rows.length === 0;
    $('synthetic-banner').hidden = !rows.some(r => r.session.data_kind === 'synthetic');
    if (!rows.length) {
      $('empty-results').querySelector('h2').textContent = state.sessions.length ? 'No runs match these filters.' : 'Your next discovery starts here.';
      $('empty-results').querySelector('p').textContent = state.sessions.length ? 'Try another device, model, prompt, or data type.' : 'Run a model on your laptop and bring in the file it saved to see your charts. Made-up examples appear only when you choose them above.';
      return;
    }
    const counts = $('run-counts'); counts.replaceChildren();
    for (const [label, value] of [['total runs', summary.total], ['complete', summary.ok], ['partial', summary.partial], ['failed', summary.failed]]) { const span = el('span'); span.append(el('b', String(value)), document.createTextNode(label)); counts.append(span); }
    const conditions = new Set(rows.map(r => [r.session.device.alias, r.session.model.digest || r.session.model.name, r.session.runtime.version, JSON.stringify(r.session.config), r.session.data_kind].join('|')));
    $('comparison-caution').textContent = conditions.size > 1 ? 'You have more than one setup selected, so the numbers below mix them together. They give you a rough picture, not a fair comparison. Use the filters to look at one setup at a time, and never mix made-up example data with real measurements.' : 'These numbers are worked out fresh from the individual runs, not copied from the file. Runs that failed, or values that were never recorded, are left out. A real zero still counts.';
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
  const runHeaders = $('runs-table').closest('table').querySelectorAll('thead th');
  [['ttft_ms', 2], ['decode_tps', 3], ['cpu_percent_normalized', 4], ['peak_rss_mib', 5]].forEach(([key, index]) => {
    const label = runHeaders[index].textContent;
    runHeaders[index].replaceChildren(termHelp(label, key));
  });
  route(); setPlatform('macos'); renderHistory(); displayPrediction(); renderResults();
})();

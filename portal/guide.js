/* Start and Models page helpers: everything runs in this browser, and nothing typed here is sent anywhere. */
(function (root) {
  'use strict';
  // Change this to the release download once one is published.
  const DOWNLOAD_URL = 'https://github.com/aryawuyitong/local-llm-telemetry-dashboard/archive/refs/heads/main.zip';
  const REPO = 'https://github.com/aryawuyitong/local-llm-telemetry-dashboard.git';
  const DISK_RESERVE_GIB = 2;
  // Real runs only: built from the anonymous results in evaluation/measurements (see measured-data.js). Never type a number in here.
  const MEASURED = {};
  for (const kind of (root.LocalLabMeasured || { kinds: [] }).kinds) for (const m of kind.models) {
    (MEASURED[m.model] = MEASURED[m.model] || []).push({ device: kind.device, ram_gb: kind.ram_gb, peakMib: m.peak_mib, runs: m.runs,
      tps: m.tps_low === m.tps_high ? `${Math.round(m.tps)}` : `${Math.round(m.tps_low)}–${Math.round(m.tps_high)}` });
  }
  // Laptops like yours first: the same memory, then anything measured.
  const measuredRun = (tag, memory) => (MEASURED[tag] || []).slice().sort((x, y) => (y.ram_gb === memory) - (x.ram_gb === memory))[0];

  function modelFit(model, memoryGib, diskGib) {
    if (diskGib - model.size_gb < DISK_RESERVE_GIB) return { verdict: 'no', label: "Won't fit", reason: `About ${model.size_gb} GB to download, and we keep ${DISK_RESERVE_GIB} GB free for your system.` };
    if (model.min_ram_gb <= memoryGib * 0.5) return { verdict: 'yes', label: 'Should fit', reason: `Needs about ${model.min_ram_gb} GB of free memory.` };
    if (model.min_ram_gb <= memoryGib * 0.75) return { verdict: 'tight', label: 'Tight', reason: `Needs about ${model.min_ram_gb} GB free, so close other apps first.` };
    return { verdict: 'no', label: "Won't fit", reason: `Needs about ${model.min_ram_gb} GB free, which is too much for ${memoryGib} GB in total.` };
  }

  function matchErrors(text, errors) {
    const scored = [];
    for (const entry of errors) {
      const hits = entry.patterns.filter(pattern => new RegExp(pattern, 'i').test(text)).length;
      if (hits) scored.push([hits, entry]);
    }
    return scored.sort((a, b) => b[0] - a[0]).slice(0, 3).map(item => item[1]);
  }

  function directCommands(mac) {
    return mac
      ? `git clone ${REPO}\ncd local-llm-telemetry-dashboard/agent\npython3 -m venv .venv\n.venv/bin/python -m pip install -r requirements.txt\n.venv/bin/python -m telemetry_agent.helper`
      : `git clone ${REPO}\ncd local-llm-telemetry-dashboard\\agent\npy -3 -m venv .venv\n.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt\n.\\.venv\\Scripts\\python.exe -m telemetry_agent.helper`;
  }

  // Start small, by the helper's rule: the first ungated model of 1.5B or more that should fit, else anything
  // smaller that should fit. A tight 1.5B is the last resort, so this page never promises more than the helper will.
  function startingModel(models, memoryGib) {
    const usable = models.filter(m => !m.license_gate).map(m => [m, modelFit(m, memoryGib, 100).verdict]);
    const ready = usable.filter(x => x[1] === 'yes').map(x => x[0]);
    const tight = usable.find(x => x[1] === 'tight' && x[0].params_b >= 1.5);
    return ready.find(m => m.params_b >= 1.5) || ready[0] || (tight ? tight[0] : null);
  }

  const api = { DOWNLOAD_URL, MEASURED, measuredRun, modelFit, matchErrors, directCommands, startingModel };
  root.LocalLabGuide = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined' || !document.getElementById('answer')) return;

  const $ = s => document.querySelector(s);
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const { models, errors } = root.LocalLabCatalog;
  const mac = !/Win/i.test(navigator.platform || navigator.userAgent);
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  $('#mem-help').textContent = mac ? 'Not sure? Apple menu → About This Mac.' : 'Not sure? Settings → System → About.';

  function cell(key, value, note) {
    const box = el('div'); box.append(el('dt', key));
    const dd = el('dd', value); if (note) dd.append(el('small', note)); box.append(dd);
    return box;
  }
  function renderAnswer(memory) {
    const box = $('#answer'); box.replaceChildren();
    const model = startingModel(models, memory);
    if (!model) { box.append(el('p', 'Not yet.', 'lab-verdict no'), el('p', 'Our smallest suitable model needs more free memory than this laptop usually has.', 'lab-sub')); return; }
    const fit = modelFit(model, memory, 100), run = measuredRun(model.ollama_tag, memory);
    const fitting = models.filter(m => modelFit(m, memory, 100).verdict === 'yes').length;
    const sub = el('p', 'Start with ', 'lab-sub'); sub.append(el('code', model.ollama_tag));
    sub.append(document.createTextNode(fitting > 1 ? `. ${fitting} of our ${models.length} approved models should fit. ` : '. '));
    const link = el('a', 'See them all'); link.href = '#models'; sub.append(link);
    const cells = el('dl', undefined, 'lab-cells');
    cells.append(cell('Download', `${model.size_gb} GB`, 'estimate'),
      run ? cell('Memory in use', `${(run.peakMib / 1024).toFixed(1)} GB`, 'measured peak') : cell('Free memory', `${model.min_ram_gb} GB`, 'estimate'),
      run ? cell('Speed', `${run.tps} tok/s`, 'measured on ' + run.device) : cell('Speed', 'Not yet', 'you measure it'));
    const acts = el('div', undefined, 'lab-acts');
    const download = el('a', `Download for ${mac ? 'Mac' : 'Windows'}`, 'button primary'); download.href = DOWNLOAD_URL; download.rel = 'noopener noreferrer';
    // The download starts, then the start guide takes over, so nobody is left alone with a ZIP file.
    if (mac) download.addEventListener('click', () => setTimeout(() => { location.hash = 'start'; }, 700));
    acts.append(download, el('span', 'No Python? The launcher offers to add a private copy (about 25 MB).', 'lab-quiet'));
    box.append(el('p', fit.verdict === 'yes' ? 'Yes.' : 'Yes, if you close some apps.', 'lab-verdict ' + fit.verdict), sub, cells, acts);
  }
  // When the helper serves this site, verdicts come from this laptop rather than a memory button.
  let labFit = null, labRuns = [];
  const LAB_VERDICT = { yes: ['yes', 'Ready now'], close_apps: ['tight', 'Close some apps first'], no: ['no', "Won't fit right now"] };
  function renderModels(memory) {
    const grid = $('#model-grid'); grid.replaceChildren();
    for (const model of models) {
      const here = labFit && labFit.find(m => m.name === model.ollama_tag);
      const fit = here ? { verdict: LAB_VERDICT[here.verdict][0], label: LAB_VERDICT[here.verdict][1] } : memory ? modelFit(model, memory, 100) : null, run = measuredRun(model.ollama_tag, memory);
      const mine = labRuns.find(r => r.model === model.ollama_tag && r.median_tps != null);
      const card = el('article', undefined, 'lab-model' + (fit ? ' fit-' + fit.verdict : ''));
      const top = el('div', undefined, 'lab-model-top');
      top.append(el('span', model.family, 'lab-label'));
      if (fit) top.append(el('span', fit.label, 'fit-badge fit-' + fit.verdict));
      card.append(top, el('h3', model.ollama_tag), el('p', model.about));
      const facts = el('dl', undefined, 'lab-cells');
      facts.append(cell('Download', `${model.size_gb} GB`, 'estimate'), cell('Free memory', `${model.min_ram_gb} GB`, 'estimate'),
        mine ? cell('Speed', `${Math.round(mine.median_tps)} tok/s`, 'measured on this laptop')
          : run ? cell('Speed', `${run.tps} tok/s`, 'measured on ' + run.device) : cell('Speed', 'Not yet', 'not measured'));
      card.append(facts, el('code', `ollama pull ${model.ollama_tag}`, 'lab-cmd'));
      if (model.license_gate) card.append(el('p', 'Has its own license terms. Read them before you rely on it.', 'fine-print'));
      if (here && here.verdict !== 'no') {
        const go = el('button', here.installed ? 'Downloaded · open its setup' : 'Set up this model', 'button secondary lab-model-go');
        go.dataset.setupModel = model.ollama_tag;
        card.append(go);
      }
      grid.append(card);
    }
  }
  function setMemory(memory) {
    document.querySelectorAll('[data-mem]').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.mem) === memory)));
    renderAnswer(memory); renderModels(memory);
  }
  document.querySelectorAll('[data-mem]').forEach(b => b.addEventListener('click', () => setMemory(Number(b.dataset.mem))));
  renderModels(null);
  api.showLabFit = (list, runs) => { labFit = list; labRuns = runs || []; renderModels(null); };
  $('#direct-command').textContent = directCommands(mac);
  if (!mac) document.querySelector('[data-platform="windows"]')?.click();  // the switch only exists on pages that still have the manual steps

  $('#err-form').addEventListener('submit', event => {
    event.preventDefault();
    const out = $('#err-out'), text = $('#err').value; out.replaceChildren();
    if (!text.trim()) { out.append(el('p', 'Paste the error text first.', 'lab-error')); return; }
    const hit = matchErrors(text, errors)[0];
    if (!hit) { out.append(el('p', "That's not on our list of known errors, so we won't guess. Ask the helper's assistant, or send it to your team with names and passwords removed.")); return; }
    const steps = el('ol'); [].concat(hit.fix).forEach(step => steps.append(el('li', step)));
    out.append(el('h3', hit.title), el('p', hit.cause), steps);
  });

  // The thin progress line under the header: one transform, updated on scroll.
  const page = document.documentElement, prog = $('#prog'), glow = $('#glow');
  let pageSpan = 1;
  const onScroll = () => { prog.style.transform = `scaleX(${Math.min(1, scrollY / pageSpan).toFixed(4)})`; };
  const measure = () => { pageSpan = Math.max(1, page.scrollHeight - innerHeight); onScroll(); };
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', measure);
  addEventListener('hashchange', () => { requestAnimationFrame(measure); });
  new ResizeObserver(measure).observe(document.body);
  measure();

  if (still) return;
  page.classList.add('motion');
  let glowX = 0, glowY = 0, wantX = 0, wantY = 0, glowFrame = 0, pointerX = 0, pointerY = 0;
  // The Download button leans toward a nearby pointer. Like the glow, this only runs while the pointer is moving.
  function leanButton() {
    const button = $('#answer .button.primary');
    if (!button) return;
    const box = button.getBoundingClientRect(), now = new DOMMatrixReadOnly(getComputedStyle(button).transform);
    const dx = pointerX - (box.left - now.m41 + box.width / 2), dy = pointerY - (box.top - now.m42 + box.height / 2);
    button.style.transform = Math.hypot(dx, dy) < 120 ? `translate3d(${(dx * 0.25).toFixed(1)}px,${(dy * 0.25).toFixed(1)}px,0)` : '';
  }
  function moveGlow() {
    glowX += (wantX - glowX) * 0.18; glowY += (wantY - glowY) * 0.18;
    glow.style.transform = `translate3d(${glowX.toFixed(1)}px,${glowY.toFixed(1)}px,0)`;
    leanButton();
    glowFrame = Math.abs(wantX - glowX) + Math.abs(wantY - glowY) > 0.5 ? requestAnimationFrame(moveGlow) : 0;
  }
  addEventListener('pointermove', e => {
    pointerX = e.clientX; pointerY = e.clientY;
    wantX = pointerX - 260; wantY = pointerY - 260;
    if (!glowFrame) glowFrame = requestAnimationFrame(moveGlow);
  }, { passive: true });
})(typeof globalThis !== 'undefined' ? globalThis : this);

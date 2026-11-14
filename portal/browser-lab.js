const byId = id => document.getElementById(id);
const models = [
  { id: 'smol-135', name: 'SmolLM2 135M', detail: 'Fastest to set up', estimate: '118–182 MB' },
  { id: 'smol-360', name: 'SmolLM2 360M', detail: 'Larger comparison model', estimate: '273–388 MB' }
];

function element(tag, value, cls) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (cls) node.className = cls;
  return node;
}

function median(values) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function textMetric(value, unit) {
  return Number.isFinite(value) ? `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} ${unit}` : 'Unavailable';
}

function installBrowserLab() {
  if (document.documentElement.dataset.mode === 'lab') return;
  const form = byId('browser-models');
  const run = byId('browser-run');
  const stop = byId('browser-stop');
  const mode = byId('browser-mode');
  const device = byId('browser-device');
  const status = byId('browser-status');
  const progress = byId('browser-progress');
  const errors = byId('browser-errors');
  const download = byId('browser-export');
  const workerUrl = new URL('./browser-lab-worker.mjs', import.meta.url);
  const supported = window.isSecureContext && !['file:', 'data:'].includes(location.protocol) && typeof Worker === 'function' && typeof WebAssembly === 'object';
  const results = [];
  let worker = null;

  for (const model of models) {
    const field = element('label', undefined, 'browser-model');
    const option = element('input');
    option.type = 'checkbox';
    option.value = model.id;
    option.checked = model.id === 'smol-135';
    const copy = element('span');
    copy.append(element('strong', model.name), element('small', `${model.detail} · ${model.estimate} weights`));
    field.append(option, copy);
    form.append(field);
  }
  const choices = Array.from(form.querySelectorAll('input'));
  const selected = () => choices.filter(option => option.checked).map(option => option.value);

  function updateControls() {
    const running = worker !== null;
    for (const input of [...choices, device, mode]) input.disabled = running || !supported;
    run.disabled = !supported || running || selected().length === 0;
    stop.hidden = !running;
    byId('browser-estimate').textContent = selected().length === 2
      ? 'Two models selected. First-run weights total about 391–570 MB, plus browser runtime files. Cached files can reduce transfers.'
      : 'Weight estimates vary by processor. The first run also retrieves browser runtime files.';
  }

  function renderResults() {
    const root = byId('browser-comparison');
    root.replaceChildren();
    byId('browser-empty').hidden = results.length > 0;
    download.hidden = results.length === 0;
    if (!results.length) return;
    const body = element('div', undefined, 'browser-metrics');
    const metrics = [
      ['Model preparation', 's', r => r.prepMs / 1000],
      ['Median first visible text', 'ms', r => median(r.runs.map(item => item.ttftMs))],
      ['Median generation speed', 'tokens/s', r => median(r.runs.map(item => item.tps))]
    ];
    for (const [title, unit, read] of metrics) {
      const panel = element('section', undefined, 'browser-metric');
      panel.append(element('h3', title));
      const values = results.map(read);
      const maximum = Math.max(1, ...values.filter(Number.isFinite));
      results.forEach((result, i) => {
        const row = element('div', undefined, 'browser-metric-row');
        const value = values[i];
        row.append(element('span', result.name), element('strong', textMetric(value, unit)));
        if (Number.isFinite(value)) {
          const bar = element('meter');
          bar.min = 0;
          bar.max = maximum;
          bar.value = value;
          bar.setAttribute('aria-label', `${result.name}: ${title}`);
          row.append(bar);
        }
        panel.append(row);
      });
      body.append(panel);
    }
    root.append(body);
    for (const result of results) {
      const details = element('details', undefined, 'browser-readout');
      details.append(element('summary', `${result.name} · ${result.device === 'webgpu' ? 'WebGPU' : 'CPU'} · ${result.dtype} · ${result.runs.length} completed ${result.runs.length === 1 ? 'run' : 'runs'}`));
      for (const record of result.runs) {
        const runDetails = element('div', undefined, 'browser-run-detail');
        runDetails.append(element('strong', record.prompt), element('p', record.output || 'No visible text returned.'), element('small', `${record.outputTokens} output tokens · ${textMetric(record.ttftMs, 'ms')} to first text · ${textMetric(record.tps, 'tokens/s')}`));
        details.append(runDetails);
      }
      root.append(details);
    }
    root.append(element('p', 'Bars are scaled separately for each metric. A longer preparation or first-text bar means a longer wait.', 'fine-print'));
  }

  function addError(model, message) {
    const entry = models.find(item => item.id === model);
    errors.append(element('p', entry ? `${entry.name}: ${message}` : message));
    errors.hidden = false;
  }

  function finish(message) {
    worker?.terminate();
    worker = null;
    progress.hidden = true;
    status.textContent = message;
    updateControls();
  }

  form.addEventListener('change', updateControls);
  run.addEventListener('click', () => {
    if (!selected().length || worker || !supported) return;
    results.length = 0;
    renderResults();
    errors.replaceChildren();
    errors.hidden = true;
    status.textContent = 'Starting the local benchmark…';
    try {
      worker = new Worker(workerUrl, { type: 'module' });
      worker.onmessage = event => {
        const data = event.data;
        if (data.type === 'progress') {
          const title = models.find(item => item.id === data.model)?.name;
          status.textContent = [title, data.message].filter(Boolean).join(' · ');
          progress.hidden = data.phase !== 'download';
          if (Number.isFinite(data.total) && data.total > 0 && Number.isFinite(data.loaded)) {
            progress.max = data.total;
            progress.value = data.loaded;
          } else progress.removeAttribute('value');
        } else if (data.type === 'result') {
          results.push(data.result);
          renderResults();
        } else if (data.type === 'error') {
          addError(data.model, data.message);
        } else if (data.type === 'done') {
          finish(results.length ? `Benchmark finished. ${results.length} model(s) measured.` : 'No models completed. Review the message above or open the recorded demo.');
        }
      };
      worker.onerror = () => {
        addError(null, 'This browser could not start the lab. Reload this page and check your network connection.');
        finish('Benchmark stopped.');
      };
      worker.postMessage({ type: 'run', models: selected(), device: device.value, mode: mode.value });
      updateControls();
    } catch {
      addError(null, 'This browser could not start the lab.');
      finish('Benchmark stopped.');
    }
  });
  stop.addEventListener('click', () => finish('Benchmark stopped. Completed measurements remain visible.'));
  download.addEventListener('click', () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ format: 'local-ai-lab-browser-v1', results }, null, 2)], { type: 'application/json' }));
    const link = element('a');
    link.href = url;
    link.download = 'local-ai-lab-browser-results.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  if (!navigator.gpu) device.querySelector('[value="webgpu"]').disabled = true;
  status.textContent = supported
    ? (navigator.gpu ? 'Ready. Automatic mode checks WebGPU first.' : 'Ready to run on CPU.')
    : 'Open this site over HTTPS or localhost in a browser with WebAssembly and web worker support.';
  updateControls();
}

installBrowserLab();

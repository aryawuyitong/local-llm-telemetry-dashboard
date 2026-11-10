/* The catalog: everything the lab can set up, with every step, command, cost and undo, readable before anyone trusts it.
   It also draws the public table of what real laptops measured.
   Both come from generated files: catalog-data.js (the action registry and recipes.json) and measured-data.js
   (anonymous results people chose to share). Nothing here talks to a laptop. */
(function (root) {
  'use strict';

  // ---------------------------------------------------------------- pure helpers, shared with the tests
  function totals(recipe, platform) {
    const steps = recipe.steps[platform];
    const yours = steps.filter(s => s.kind === 'manual').length;
    return [['Steps', `${steps.length}, each one approved by you`], ['Space', `About ${recipe.adds_gb.toFixed(1)} GB, plus Ollama`], ['Internet', 'Yes, for the downloads'],
      ['Password', yours ? "The lab never asks. An installer you run yourself might" : 'No'], ['Money', 'Free']];
  }
  const costLine = risk => Object.values(risk).map(r => `${r.label}: ${r.value}`);
  // "Laptops like yours": the same memory first, then anything measured.
  function measuredFor(measured, model, memoryGb) {
    const rows = [];
    for (const kind of measured.kinds) for (const m of kind.models) if (m.model === model) rows.push({ ...m, device: kind.device, ram_gb: kind.ram_gb });
    return rows.sort((a, b) => (b.ram_gb === memoryGb) - (a.ram_gb === memoryGb));
  }
  const speedText = m => (m.tps_low === m.tps_high ? `${Math.round(m.tps)}` : `${Math.round(m.tps_low)}–${Math.round(m.tps_high)}`);
  const api = { totals, costLine, measuredFor, speedText };
  root.LocalLabCatalogPage = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined' || !document.getElementById('catalog-recipes')) return;

  const data = root.LocalLabCatalogSetups, measured = root.LocalLabMeasured;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const inLab = () => document.documentElement.dataset.mode === 'lab';
  let platform = /Win/i.test(navigator.platform || navigator.userAgent) ? 'windows' : 'mac';
  const open = new Set();

  function stepHtml(s, i) {
    return `<li><strong>${i + 1}. ${esc(s.title)}</strong>${s.kind === 'manual' ? ' <span class="badge">You do this one yourself</span>' : ''}
      <p>${esc(s.does)}</p>
      ${s.command ? `<p><code class="cmd">${esc(s.command)}</code></p>` : s.link ? `<p class="small muted">No command: you run the official installer from ${esc(s.link.replace('https://', ''))}.</p>` : ''}
      <p class="small muted">${costLine(s.risk).map(esc).join(' · ')}</p>
      ${s.undo ? `<p class="small muted">Undo: ${esc(s.undo)}</p>` : ''}</li>`;
  }

  function recipeHtml(r) {
    return `<article class="card cat-recipe"><h3>${esc(r.title)}</h3><p>${esc(r.why)}</p><p class="small muted">For: ${esc(r.for)}.</p>
      ${r.review.by ? `<p class="small muted">Reviewed by ${esc(r.review.by)} on ${esc(r.review.on)}.</p>` : ''}
      <dl class="risk">${totals(r, platform).map(([k, v]) => `<div class="${v === 'No' || v === 'Free' ? 'none' : 'note'}"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
      <details data-cat-recipe="${esc(r.id)}" ${open.has(r.id) ? 'open' : ''}><summary>See every step and its exact command</summary><ol class="cat-steps">${r.steps[platform].map(stepHtml).join('')}</ol></details>
      <div class="row-actions">${inLab() ? `<button class="btn primary small" data-setup-recipe="${esc(r.id)}">Set this up on this laptop</button>`
        : '<a class="btn small" href="#preview">See it happen in the demo</a><a class="btn small" href="#deploy">Get the lab</a>'}</div></article>`;
  }

  function appHtml(a) {
    const card = a.install[platform];
    return `<article class="card"><h3>${esc(a.name)} <span class="small muted">about ${a.size_gb} GB</span></h3><p>${esc(a.what)}</p>
      <p><code class="cmd">${esc(card.command)}</code></p><p class="small muted">${costLine(card.risk).map(esc).join(' · ')}</p>
      <p class="small muted">Undo: <code class="cmd">${esc(a.remove[platform])}</code></p></article>`;
  }

  function render() {
    document.querySelectorAll('[data-cat-os]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.catOs === platform)));
    document.getElementById('catalog-recipes').innerHTML = `<div class="cards">${data.recipes.map(recipeHtml).join('')}</div>`;
    document.getElementById('catalog-apps').innerHTML = `<div class="cards">${data.apps.map(appHtml).join('')}</div>
      <p class="small muted">On a laptop without ${platform === 'mac' ? 'Homebrew' : 'winget'}, these become steps you do yourself from each app's official page.</p>`;
  }

  document.getElementById('view-catalog').addEventListener('click', e => {
    const os = e.target.closest('[data-cat-os]');
    if (os) { platform = os.dataset.catOs; render(); }
  });
  document.getElementById('catalog-recipes').addEventListener('toggle', e => {
    const id = e.target.dataset && e.target.dataset.catRecipe;
    if (id) { if (e.target.open) open.add(id); else open.delete(id); }
  }, true);
  render();

  // ---------------------------------------------------------------- real results from real laptops
  const box = document.getElementById('real-results');
  if (!box) return;
  const kinds = measured.kinds.length;
  box.innerHTML = kinds ? `<p><strong>${measured.sessions} measurement sessions from ${kinds} kind${kinds === 1 ? '' : 's'} of laptop so far.</strong> Each was shared by someone who ran the lab. A results file doesn't say who sent it, so laptops are grouped by chip and memory.</p>
    <div class="card table-wrap"><table><caption class="sr-only">What real laptops measured</caption>
      <thead><tr><th scope="col">Laptop</th><th scope="col">Model</th><th scope="col" class="num">Speed (tokens/s)</th><th scope="col" class="num">First word</th><th scope="col" class="num">Peak memory</th><th scope="col" class="num">Runs</th><th scope="col">Latest</th></tr></thead>
      <tbody>${measured.kinds.map(k => k.models.map(m => `<tr><td>${esc(k.device)}<div class="small muted">${esc(k.os)}</div></td><td>${esc(m.model)}</td><td class="num">${esc(speedText(m))}</td>
        <td class="num">${m.ttft_ms == null ? '–' : m.ttft_ms + ' ms'}</td><td class="num">${m.peak_mib == null ? '–' : (m.peak_mib / 1024).toFixed(1) + ' GiB'}</td><td class="num">${m.runs}</td><td>${esc(m.last)}</td></tr>`).join('')).join('')}</tbody></table></div>
    <p class="small muted">Speed is the middle result of each session; a range means sessions differed. These are a few people's laptops, not a benchmark, so yours may differ.</p>
    <details class="cat-share"><summary>Add your laptop</summary><p>Run a measurement in the lab's <strong>Measure</strong> page, then press <strong>Download JSON</strong>. The file has no name, account or folder path in it. Open it to check, then send it to the team. The lab never sends anything for you.</p>
      <p><a href="https://github.com/aryawuyitong/local-llm-telemetry-dashboard/tree/main/evaluation/measurements" target="_blank" rel="noopener noreferrer">How shared results are checked and added</a></p></details>`
    : '<p>No one has shared a measurement yet.</p>';
})(typeof globalThis !== 'undefined' ? globalThis : this);

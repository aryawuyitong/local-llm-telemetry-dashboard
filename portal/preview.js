/* The public demo: click through the lab with recorded results. Nothing here talks to a laptop.
   Card words, commands and costs come from the lab's own registry (preview-data.js is generated from it),
   and every reply and number was recorded from a real run. */
(function (root) {
  'use strict';
  const VERDICTS = { yes: 'Ready now', close_apps: 'Close some apps first', no: "Won't fit right now" };

  // Pure helpers, shared with the tests.
  function fitGroups(fit) {
    return Object.entries(VERDICTS).map(([key, label]) => ({ label, models: fit.filter(m => m.verdict === key).map(m => m.name) })).filter(g => g.models.length);
  }
  function changeLog(done, data) {
    const rows = [];
    if (done.start_runtime) rows.push({ what: 'Started Ollama. Quit it from its menu bar or system tray icon.' });
    if (done.pull_model) rows.push({ what: `Downloaded ${data.model}, about ${data.size_gb.toFixed(1)} GB, to Ollama's models folder.`, undo: true });
    return rows;
  }
  function statLine(t) {
    return [t.load_s >= 0.5 ? `Loading into memory: ${t.load_s} s` : '', `First word after ${t.ttft_s} s`, `${t.tps} tokens per second`, `${t.tokens} tokens`].filter(Boolean);
  }
  const api = { fitGroups, changeLog, statLine };
  root.LocalLabPreviewDemo = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined' || !document.getElementById('preview-body')) return;

  const data = root.LocalLabPreview, S = data.samples;
  const mac = !/Win/i.test(navigator.platform || navigator.userAgent);
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const body = document.getElementById('preview-body');
  const source = `Recorded on a real ${S.recorded.device} laptop. Yours will differ.`;
  let state, timers = [];

  function reset() {
    timers.forEach(clearInterval); timers = [];
    state = { cards: JSON.parse(JSON.stringify(data.cards[mac ? 'mac' : 'windows'])), done: {}, chats: [], playing: false, compare: null, pick: null, undone: false, confirmUndo: false };
    card('install_runtime').summary = "Already installed in this demo. On your own laptop, you install Ollama yourself from its official page.";
  }
  const card = id => state.cards.find(c => c.id === id);
  const later = (ms, fn) => { const t = setTimeout(fn, still ? 0 : ms); timers.push(t); };

  function riskHtml(risk) {
    return `<dl class="risk" aria-label="What this step costs">${Object.values(risk).map(r => `<div class="${esc(r.level)}"><dt>${esc(r.label)}</dt><dd>${esc(r.value)}</dd></div>`).join('')}</dl>`;
  }

  // The same card the lab draws: cost, what, why, what changes, undo, the command, then Approve.
  function cardHtml(s, active) {
    const [cls, label] = s.done ? ['ok', 'Done'] : s.running ? ['run', 'Running'] : active ? ['ask', 'Your next step'] : ['', 'Waiting'];
    const open = active && !s.done && !s.running;
    const details = (open || s.running) ? `${riskHtml(s.risk)}<dl>${s.what ? `<dt>What this is</dt><dd>${esc(s.what)}</dd>` : ''}
      <dt>Why you need it</dt><dd>${esc(s.why)}</dd><dt>What changes on your laptop</dt><dd>${esc(s.does)}</dd>
      ${s.undo ? `<dt>How to undo it</dt><dd>${esc(s.undo)}</dd>` : ''}
      ${s.command ? `<dt>${s.how === 'api' ? 'Does the same as typing' : 'The command behind this step'}</dt><dd><code class="cmd">${esc(s.command)}</code></dd>` : ''}</dl>` : '';
    return `<article class="card step ${open ? 'active' : ''}"><header><span class="badge ${cls}">${label}</span><h3>${esc(s.title)}</h3></header>
      ${details}
      ${s.running ? `<div class="progress ${s.progress == null ? 'indeterminate' : ''}"><span data-pv-bar></span></div><div class="small muted" data-pv-detail>${esc(s.detail || '')}</div>` : ''}
      ${s.done && s.summary ? `<p class="small muted mt">${esc(s.summary)}</p>` : ''}
      ${s.done && s.evidence ? `<ul class="evidence">${s.evidence.map(x => `<li class="ok">${esc(x)}</li>`).join('')}</ul>` : ''}
      ${s.done && s.command ? `<div class="small muted">Command: <code class="cmd">${esc(s.command)}</code></div>` : ''}
      ${open ? `<div class="actions"><button class="btn primary" data-pv-approve="${esc(s.id)}">${s.id === 'check_hardware' ? 'Run this check' : 'Approve and run'}</button></div>` : ''}</article>`;
  }

  function stage(n, title, inner, locked) {
    return `<li class="stage ${locked ? 'locked' : ''}"><h2><span class="n">${n}</span>${esc(title)}</h2>${locked ? `<p class="muted">${esc(locked)}</p>` : inner}</li>`;
  }

  function bubble(c) {
    const shown = c.shown ?? c.text;
    return `<div class="talk-msg me">${esc(c.question)}</div>
      <div class="talk-msg them"><div class="small muted who">${esc(c.model)}</div><p>${esc(shown) || '<span class="muted">Thinking…</span>'}</p>
        ${c.finished ? `<div class="stats">${statLine(c).map(x => `<span>${esc(x)}</span>`).join('')}</div><p class="note small ${/wrong/i.test(c.note) ? 'warn' : ''}">${esc(c.note)}</p>` : ''}</div>`;
  }

  function compareHtml() {
    const c = S.compare, st = state.compare;
    if (!st) return `<p>Both models get the same question: <strong>${esc(c.question)}</strong></p>
      <div class="actions"><button class="btn primary" data-pv-compare>Ask both</button></div>`;
    const cards = c.answers.map((a, i) => {
      const v = st[i];
      return `<div class="card cmp-card"><h3><span class="muted">${'AB'[i]}</span> ${esc(a.model)}</h3>
        <p>${v ? esc(v.shown) || '<span class="muted">Loading the model…</span>' : '<span class="muted">Waiting for its turn, so the two never share memory.</span>'}</p>
        ${v && v.finished ? `<div class="stats">${statLine(a).map(x => `<span>${esc(x)}</span>`).join('')}</div>` : ''}</div>`;
    }).join('');
    const finished = st.length === 2 && st.every(v => v && v.finished);
    const faster = c.answers[0].tps > c.answers[1].tps ? 0 : 1;
    return `<p>The question: <strong>${esc(c.question)}</strong></p><div class="cmp-grid">${cards}</div>
      ${finished ? `<div class="card mt"><h3>Which answer would you use?</h3>
        <div class="actions">${['A', 'B', 'Neither'].map((l, i) => `<button class="btn ${state.pick === i ? 'primary' : ''}" data-pv-pick="${i}">${l}</button>`).join('')}</div>
        ${state.pick != null ? `<p class="mt">${esc(c.right)} ${state.pick === 2 ? 'One of them did get it right, so look again.' : state.pick === faster ? 'You picked the faster one, and it was wrong. Speed says nothing about whether an answer is good.' : 'You picked the slower one, and it was right. The extra wait bought a correct answer.'}</p>` : ''}</div>` : ''}`;
  }

  function render() {
    const setup = ['install_runtime', 'start_runtime', 'pull_model', 'first_prompt'].map(card);
    const next = setup.findIndex(s => !s.done);
    const ready = state.done.first_prompt && !state.undone;
    const log = changeLog(state.done, data);
    const groups = fitGroups(S.fit);
    body.innerHTML = `<ol class="stages">
      ${stage(1, 'Your laptop', cardHtml(card('check_hardware'), true)
        + (state.done.check_hardware ? `<div class="card"><h3>What this laptop can run</h3>${groups.map(g => `<p><strong>${esc(g.label)}:</strong> ${g.models.map(m => `<code class="cmd">${esc(m)}</code>`).join(' ')}</p>`).join('')}
          <p class="small muted">The demo continues with ${esc(data.model)}, the lab's starting model.</p></div>` : ''))}
      ${stage(2, 'Set it up', setup.map((s, i) => cardHtml(s, i === next)).join(''), state.done.check_hardware ? '' : 'Check the laptop first.')}
      ${stage(3, 'Talk to it', `<div class="card talk"><div class="talk-log pv-log">${state.chats.length ? state.chats.map(bubble).join('') : '<p class="muted">Pick a question below.</p>'}</div>
          <div class="chips pv-chips">${S.chats.map((c, i) => `<button class="chip" data-pv-chat="${i}" ${state.playing ? 'disabled' : ''}>${esc(c.question)}</button>`).join('')}</div>
          <p class="small muted">In the demo you can only pick these questions. In the real lab you type anything, and nothing leaves your laptop.</p></div>`,
        ready ? '' : state.undone ? 'You removed the model, so there is nothing to talk to. Start the demo again to bring it back.' : 'Finish setup first.')}
      ${stage(4, 'Compare two models', `<div class="card">${compareHtml()}</div>`, ready ? '' : state.undone ? 'This needs the model you removed.' : 'Finish setup first.')}
      ${stage(5, 'What changed on your laptop', `<div class="card">${log.length ? log.map(r => `<div class="change ${r.undo && state.undone ? 'undone' : ''}"><div>${esc(r.what)}</div>
            ${r.undo && !state.undone ? `<button class="btn small" data-pv-undo>${state.confirmUndo ? 'Remove it from this laptop' : 'Undo'}</button>` : ''}</div>`).join('') : '<p class="muted">Nothing yet. Every step that changes the laptop is listed here, with Undo where it can be undone.</p>'}
          ${state.undone ? `<div class="change"><div>Removed ${esc(data.model)} (undo).</div></div>` : ''}</div>`)}
    </ol>
    ${state.done.first_prompt ? `<div class="card pv-end"><h3>That was the demo.</h3><p>The real lab does all of this on your own laptop, with your own questions, and checks your real memory and disk first.</p>
      <div class="actions"><a class="btn primary" href="#deploy">Get it on your laptop</a><button class="btn" data-pv-restart>Start the demo again</button></div></div>` : ''}`;
    const bar = body.querySelector('[data-pv-bar]');
    const running = state.cards.find(c => c.running);
    if (bar && running && running.progress != null) bar.style.width = Math.round(running.progress * 100) + '%';
    const logBox = body.querySelector('.pv-log');
    if (logBox) logBox.scrollTop = logBox.scrollHeight;
  }

  function finish(s, extra) { Object.assign(s, { running: false, done: true }, extra); state.done[s.id] = true; render(); }

  function approve(id) {
    const s = card(id);
    if (!s || s.done || s.running) return;
    s.running = true;
    const h = S.hardware;
    if (id === 'check_hardware') {
      render();
      later(700, () => finish(s, { evidence: [`${h.os} ${h.os_version}, ${h.cpu_model}`, `${h.total_ram_gb} GB of memory, ${h.available_ram_gb} GB free right now`, `${h.free_disk_gb} GB of free disk`] }));
    } else if (id === 'start_runtime') {
      render();
      later(900, () => finish(s, { summary: 'Ollama is running on this laptop, at port 11434.' }));
    } else if (id === 'pull_model') {
      s.progress = 0; s.detail = `0.00 of ${data.size_gb.toFixed(2)} GB`;
      render();
      const total = still ? 1 : 24;
      let i = 0;
      const t = setInterval(() => {
        i += 1; s.progress = i / total; s.detail = `${(data.size_gb * s.progress).toFixed(2)} of ${data.size_gb.toFixed(2)} GB`;
        const bar = body.querySelector('[data-pv-bar]'), detail = body.querySelector('[data-pv-detail]');
        if (bar) bar.style.width = Math.round(s.progress * 100) + '%';
        if (detail) detail.textContent = s.detail;
        if (i >= total) { clearInterval(t); finish(s, { summary: 'Downloaded. It appears under What changed on your laptop, with Undo.' }); }
      }, 100);
      timers.push(t);
    } else if (id === 'first_prompt') {
      render();
      later(S.hello.seconds * 1000, () => finish(s, { summary: `Replied in ${S.hello.seconds} s: "${S.hello.reply}"` }));
    }
  }

  // Reveal recorded words a few at a time, so it reads like a model writing. The words and the speed shown are the recorded ones.
  function play(target, text, onDone) {
    const words = text.split(/(\s+)/);
    if (still) { target.shown = text; target.finished = true; onDone(); return; }
    let i = 0;
    target.shown = '';
    const t = setInterval(() => {
      i = Math.min(words.length, i + 3); target.shown = words.slice(0, i).join('');
      if (i >= words.length) { clearInterval(t); target.finished = true; onDone(); } else render();
    }, 45);
    timers.push(t);
  }

  function chat(i) {
    if (state.playing) return;
    const c = { ...S.chats[i], shown: '', finished: false };
    state.chats.push(c); state.playing = true; render();
    later(300, () => play(c, c.text, () => { state.playing = false; render(); }));
  }

  function compare() {
    if (state.compare) return;
    const [a, b] = S.compare.answers;
    state.compare = [{ shown: '', finished: false }]; render();
    later(a.ttft_s * 700, () => play(state.compare[0], a.text, () => {
      state.compare.push({ shown: '', finished: false }); render();
      later(b.ttft_s * 700, () => play(state.compare[1], b.text, render));
    }));
  }

  body.addEventListener('click', e => {
    const t = e.target.closest('button');
    if (!t) return;
    const d = t.dataset;
    if (d.pvApprove) approve(d.pvApprove);
    else if (d.pvChat) chat(+d.pvChat);
    else if ('pvCompare' in d) compare();
    else if (d.pvPick) { state.pick = +d.pvPick; render(); }
    else if ('pvUndo' in d) { if (state.confirmUndo) state.undone = true; else state.confirmUndo = true; render(); }
    else if ('pvRestart' in d) { reset(); render(); document.getElementById('view-preview').scrollIntoView({ block: 'start' }); }
  });

  document.getElementById('preview-source').textContent = source;
  reset(); render();
})(typeof globalThis !== 'undefined' ? globalThis : this);

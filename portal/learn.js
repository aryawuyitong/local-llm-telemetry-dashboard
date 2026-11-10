/* How it works: four small tools to learn by trying, in the order a student meets each idea.
   Each opens with a guess, then shows the answer. Nothing is scored or saved.
   The fit rule is the site's own (guide.js), the card comes from the lab's registry, and the replies
   and speeds were recorded from a real run (both in preview-data.js). */
(function (root) {
  'use strict';

  // ---------------------------------------------------------------- pure helpers, shared with the tests
  // A recorded reply cut into as many pieces as the model produced tokens. Real tokens differ in length, so this is approximate.
  function tokenPieces(text, tokens) {
    const n = Math.max(1, Math.min(tokens, text.length)), pieces = [];
    for (let i = 0; i < n; i++) pieces.push(text.slice(Math.round(i * text.length / n), Math.round((i + 1) * text.length / n)));
    return pieces;
  }
  const secondsFor = (tokens, rate) => Math.round(tokens / rate * 10) / 10;
  // Where a model sits on a laptop's memory bar, by the same rule the Start page uses.
  function fitView(model, memoryGib, modelFit) {
    const fit = modelFit(model, memoryGib, 100);
    return { verdict: fit.verdict, label: fit.label, reason: fit.reason, needs: model.min_ram_gb, share: Math.min(1, model.min_ram_gb / memoryGib) };
  }
  // The speeds really measured in the recorded run, slowest first, plus one slow laptop for contrast.
  function speedChoices(samples) {
    const seen = new Map();
    for (const r of [...samples.compare.answers, ...samples.chats]) if (!seen.has(r.model)) seen.set(r.model, Math.round(r.tps));
    const measured = [...seen].map(([model, rate]) => ({ rate, label: `${rate}`, note: `${model}, as recorded` })).sort((a, b) => a.rate - b.rate);
    return [{ rate: 10, label: '10', note: 'a slow laptop' }, ...measured];
  }
  const STOPS = [
    { name: 'You', where: 'Your browser tab', does: 'You type a question. The page itself comes from your own laptop: its address starts with 127.0.0.1, which means "this computer".',
      detail: 'The public website only teaches. It never connects to your laptop.' },
    { name: 'Lab Helper', where: 'A small program on your laptop', does: 'It checks the request came from your own page, removes anything that looks like a password or key, and passes your question on.',
      detail: 'You start it by double-clicking Start Lab Helper. It only runs steps you approve, and it never runs a command that a model wrote.' },
    { name: 'Ollama', where: 'The engine, on your laptop', does: 'It loads the model\'s file from disk into memory, then runs it. The first question after a break waits for that loading.',
      detail: 'It listens only on your laptop, at port 11434. After a few quiet minutes it frees the memory again.' },
    { name: 'The model', where: 'A file of learned numbers', does: 'It splits your question into tokens, which are pieces of words. Then it works out which token is likely to come next, adds it, and repeats.',
      detail: 'It predicts text and doesn\'t look anything up. That is why it can sound sure and still be wrong.' },
    { name: 'The reply', where: 'Back in your browser tab', does: 'Each new token travels straight back to your page, so the words appear one piece at a time. The page shows how fast they came.',
      detail: 'Your conversation isn\'t saved anywhere. Closing the tab clears it.' },
  ];
  const CARD_PARTS = [
    { id: 'risk', label: 'The cost', text: 'Six facts before anything runs: how long it takes, how much space it uses, whether it needs the internet, a password or money, and whether you can undo it. Every card must state all six, or the lab refuses to show it.' },
    { id: 'what', label: 'What this is', text: 'What the step is, in plain words, so you never approve something you can\'t describe.' },
    { id: 'why', label: 'Why you need it', text: 'The reason for the step. If the reason doesn\'t apply to you, you can stop here.' },
    { id: 'does', label: 'What changes', text: 'Exactly what will be different on your laptop afterwards, and what won\'t.' },
    { id: 'undo', label: 'How to undo it', text: 'How to take the step back. The lab also lists it in My lab, with an Undo button.' },
    { id: 'command', label: 'The command', text: 'The real command behind the button. Experienced users type it; beginners can read it and learn what a download really is. The lab only ever shows commands from its own reviewed list.' },
    { id: 'buttons', label: 'Your choice', text: 'Nothing happens until you press Approve and run. You can also type the command yourself, and the lab then checks your work.' },
  ];
  const api = { tokenPieces, secondsFor, fitView, speedChoices, STOPS, CARD_PARTS };
  root.LocalLabLearn = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined' || !document.getElementById('how-body')) return;

  // ---------------------------------------------------------------- the page
  const { models } = root.LocalLabCatalog, { modelFit } = root.LocalLabGuide, demo = root.LocalLabPreview, S = demo.samples;
  const mac = !/Win/i.test(navigator.platform || navigator.userAgent);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const body = document.getElementById('how-body');
  const sorted = [...models].sort((a, b) => a.min_ram_gb - b.min_ram_gb);
  const reply = S.chats[0], pieces = tokenPieces(reply.text, reply.tokens), speeds = speedChoices(S);
  const big = sorted[sorted.length - 1];
  const pull = demo.cards[mac ? 'mac' : 'windows'].find(c => c.id === 'pull_model');
  const state = { guess: {}, memory: 8, model: sorted.findIndex(m => m.ollama_tag === demo.model), rate: null, shown: 0, elapsed: 0, timer: 0, stop: 0, part: 'risk' };

  const GUESSES = {
    fit: { q: `Guess first: ${big.ollama_tag} is a ${big.size_gb} GB download. Will it run on a laptop with 8 GB of memory?`, options: ['Yes', 'Only if I close other apps', 'No'], right: 2,
      why: `No. It needs about ${big.min_ram_gb} GB of free memory, which is more than the whole laptop has. A model needs more memory than its download size, because it also has to hold your conversation. Try the sliders.` },
    speed: { q: `Guess first: a reply is ${reply.tokens} tokens long. How long does it take at 10 tokens per second?`, options: ['About 1 second', `About ${Math.round(secondsFor(reply.tokens, 10))} seconds`, 'About 30 seconds'], right: 1,
      why: `About ${secondsFor(reply.tokens, 10)} seconds: ${reply.tokens} tokens divided by 10 each second. Press a speed below to feel the difference.` },
    path: { q: 'Guess first: your question passes through five stops. How many of them are on the internet?', options: ['None', 'One', 'Three'], right: 0,
      why: 'None. Every stop is on your own laptop, so your question never leaves it. You only need the internet to download things.' },
    card: { q: 'Guess first: a card offers to download a model, and you close the page without pressing Approve. What happens?', options: ['The download starts anyway', 'Nothing', 'It asks again later'], right: 1,
      why: 'Nothing. The lab only acts when you approve a card. Click each part of the card below to see what it tells you.' },
  };

  function guessHtml(id) {
    const g = GUESSES[id], picked = state.guess[id];
    return `<div class="how-guess"><p><strong>${esc(g.q)}</strong></p>
      <div class="actions">${g.options.map((o, i) => `<button class="btn small ${picked === i ? (i === g.right ? 'primary' : 'picked') : ''}" data-how-guess="${id}:${i}">${esc(o)}</button>`).join('')}</div>
      ${picked != null ? `<p class="note ${picked === g.right ? 'ok' : 'warn'}">${picked === g.right ? 'Right. ' : 'Not quite. '}${esc(g.why)}</p>` : ''}</div>`;
  }

  function fitHtml() {
    const model = sorted[state.model], v = fitView(model, state.memory, modelFit);
    return `${guessHtml('fit')}
      <label class="field" for="how-memory"><span class="lbl">Your laptop's memory <output>${state.memory} GB</output></span>
        <input type="range" id="how-memory" min="4" max="32" step="2" value="${state.memory}"></label>
      <label class="field" for="how-model"><span class="lbl">The model <output>${esc(model.ollama_tag)}</output></span>
        <input type="range" id="how-model" min="0" max="${sorted.length - 1}" step="1" value="${state.model}">
        <span class="hint">${esc(model.about)}</span></label>
      <div class="how-bar" role="img" aria-label="${esc(model.ollama_tag)} needs about ${v.needs} GB of ${state.memory} GB">
        <span class="how-bar-fill ${v.verdict}" data-how-share="${v.share}"></span><i class="how-mark half"></i><i class="how-mark three"></i></div>
      <div class="how-bar-key small muted"><span>0</span><span>half: fits easily below here</span><span>three quarters: tight</span><span>${state.memory} GB</span></div>
      <p><span class="fit-badge fit-${v.verdict}">${esc(v.label)}</span> ${esc(v.reason)} The download is ${model.size_gb} GB.</p>
      <p class="small muted">These needs are planning estimates. The real lab checks your laptop's actual free memory before any download.</p>`;
  }

  function speedHtml() {
    const done = state.rate && state.shown >= pieces.length;
    return `${guessHtml('speed')}
      <p>The same recorded reply, written at different speeds. Three of these are what real models managed on one laptop.</p>
      <div class="actions">${speeds.map(s => `<button class="btn small ${state.rate === s.rate ? 'primary' : ''}" data-how-rate="${s.rate}"><strong>${esc(s.label)}</strong>&nbsp;tokens/s · ${esc(s.note)}</button>`).join('')}</div>
      <div class="how-reply" aria-live="off"><p class="small muted">${esc(reply.question)}</p><p id="how-words">${state.rate ? esc(pieces.slice(0, state.shown).join('')) : '<span class="muted">Pick a speed.</span>'}</p></div>
      <p class="small muted" id="how-clock">${state.rate ? `${state.shown} of ${pieces.length} tokens · ${state.elapsed.toFixed(1)} s${done ? ` · finished at ${state.rate} tokens per second` : ''}` : `${pieces.length} tokens. Each piece shown is roughly one token.`}</p>
      <p class="small muted">Most people read about four words a second, so above roughly 10 tokens per second a model writes faster than you read. Faster isn't better, though: the fastest model here gave a wrong answer in the demo.</p>`;
  }

  function pathHtml() {
    const s = STOPS[state.stop];
    return `${guessHtml('path')}
      <ol class="how-stops">${STOPS.map((x, i) => `<li><button class="how-stop ${i === state.stop ? 'on' : ''}" data-how-stop="${i}" aria-pressed="${i === state.stop}"><b>${i + 1}</b>${esc(x.name)}</button></li>`).join('')}</ol>
      <div class="card how-stop-card"><p class="small muted">${esc(s.where)}</p><h3>${state.stop + 1}. ${esc(s.name)}</h3><p>${esc(s.does)}</p><p class="small muted">${esc(s.detail)}</p>
        <p class="small"><span class="badge ok">Stays on your laptop</span></p>
        <div class="actions"><button class="btn small" data-how-stop="${state.stop - 1}" ${state.stop === 0 ? 'disabled' : ''}>Back</button>
          <button class="btn small primary" data-how-stop="${state.stop + 1}" ${state.stop === STOPS.length - 1 ? 'disabled' : ''}>Next stop</button></div></div>`;
  }

  function cardHtml() {
    const on = id => (state.part === id ? 'on' : '');
    const part = CARD_PARTS.find(p => p.id === state.part);
    const row = (id, title, value) => `<button class="how-part ${on(id)}" data-how-part="${id}"><span class="how-part-title">${esc(title)}</span><span>${value}</span></button>`;
    return `${guessHtml('card')}
      <div class="how-card-layout"><article class="card step active how-card"><header><span class="badge ask">Your next step</span><h3>${esc(pull.title)}</h3></header>
        <button class="how-part ${on('risk')}" data-how-part="risk"><span class="risk">${Object.values(pull.risk).map(r => `<span class="${esc(r.level)}"><span class="how-part-title">${esc(r.label)}</span>${esc(r.value)}</span>`).join('')}</span></button>
        ${row('what', 'What this is', esc(pull.what))}${row('why', 'Why you need it', esc(pull.why))}${row('does', 'What changes on your laptop', esc(pull.does))}
        ${row('undo', 'How to undo it', esc(pull.undo))}${row('command', 'Does the same as typing', `<code class="cmd">${esc(pull.command)}</code>`)}
        <button class="how-part ${on('buttons')}" data-how-part="buttons"><span class="how-fake-btn primary">Approve and run</span><span class="how-fake-btn">I'll type it myself</span></button></article>
        <div class="card how-explain" aria-live="polite"><p class="small muted">You clicked</p><h3>${esc(part.label)}</h3><p>${esc(part.text)}</p>
          <p class="small muted">This is the real card for ${esc(demo.model)}, exactly as the lab shows it. Here it's only for reading.</p></div></div>`;
  }

  const TOOLS = [
    ['fit', 'Will it fit?', 'Memory decides which models your laptop can run.', fitHtml],
    ['speed', 'Feel the speed', 'What "tokens per second" really feels like.', speedHtml],
    ['path', 'Follow one question', 'Where your words go, and what each piece does.', pathHtml],
    ['card', 'Read an approval card', 'What you\'ll be looking at before every step.', cardHtml],
  ];

  function draw(id) {
    const tool = TOOLS.find(t => t[0] === id);
    document.getElementById('how-' + id).innerHTML = tool[3]();
    if (id === 'fit') {
      const fill = body.querySelector('[data-how-share]');
      fill.style.width = (fill.dataset.howShare * 100).toFixed(1) + '%';
    }
  }

  body.innerHTML = TOOLS.map(([id, title, lede], i) => `<section class="how-tool" aria-labelledby="how-${id}-title">
      <h2 id="how-${id}-title"><span class="n">${i + 1}</span>${esc(title)}</h2><p class="how-lede">${esc(lede)}</p><div class="card" id="how-${id}"></div></section>`).join('');
  TOOLS.forEach(t => draw(t[0]));

  function playAt(rate) {
    clearInterval(state.timer);
    Object.assign(state, { rate, shown: 0, elapsed: 0 });
    draw('speed');
    const start = performance.now(), words = document.getElementById('how-words'), clock = document.getElementById('how-clock');
    // One tick can add several tokens, so fast speeds stay accurate without redrawing the whole tool.
    state.timer = setInterval(() => {
      state.elapsed = (performance.now() - start) / 1000;
      state.shown = Math.min(pieces.length, Math.floor(state.elapsed * rate) + 1);
      words.textContent = pieces.slice(0, state.shown).join('');
      clock.textContent = `${state.shown} of ${pieces.length} tokens · ${state.elapsed.toFixed(1)} s`;
      if (state.shown >= pieces.length) { clearInterval(state.timer); state.elapsed = pieces.length / rate; draw('speed'); }
    }, 40);
  }

  body.addEventListener('click', e => {
    const t = e.target.closest('button');
    if (!t || t.disabled) return;
    const d = t.dataset;
    if (d.howGuess) { const [id, i] = d.howGuess.split(':'); state.guess[id] = +i; draw(id); }
    else if (d.howRate) playAt(+d.howRate);
    else if (d.howStop) { state.stop = Math.max(0, Math.min(STOPS.length - 1, +d.howStop)); draw('path'); const now = body.querySelector('.how-stop.on'); if (now && t.classList.contains('how-stop')) now.focus(); }
    else if (d.howPart) { state.part = d.howPart; draw('card'); const now = body.querySelector(`[data-how-part="${d.howPart}"]`); if (now) now.focus(); }
  });
  body.addEventListener('input', e => {
    if (e.target.id !== 'how-memory' && e.target.id !== 'how-model') return;
    const id = e.target.id;
    if (id === 'how-memory') state.memory = +e.target.value; else state.model = +e.target.value;
    draw('fit');
    document.getElementById(id).focus();
  });
})(typeof globalThis !== 'undefined' ? globalThis : this);

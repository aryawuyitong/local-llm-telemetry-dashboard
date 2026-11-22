/* The start guide: from the Download button to the lab opening, one screen at a time, on a Mac or on Windows.
   Both use the same ZIP; only the start file differs. Each step draws what the student will see, and
   "I see something else" opens the fixes for that step. Window text is the launchers' own words
   (Start Lab on Mac.command, Start Lab on Windows.py and agent/Start Lab Helper.command). */
(function (root) {
  'use strict';

  // ---------------------------------------------------------------- pure helpers, shared with the tests
  // GitHub names the unzipped folder after the repository and the branch, with any slash turned into a dash.
  function folderName(downloadUrl) {
    const found = /github\.com\/[^/]+\/([^/]+)\/archive\/refs\/heads\/(.+)\.zip$/.exec(downloadUrl);
    return found ? `${found[1]}-${found[2].replace(/\//g, '-')}` : 'local-llm-telemetry-dashboard-main';
  }
  const LAUNCHER = 'Start Lab on Mac.command';
  const WIN_LAUNCHER = 'Start Lab on Windows.py';
  // Which guide to open first. Anything that isn't Windows gets the Mac guide, with the switch to change it.
  const pickSystem = platform => (/win/i.test(platform || '') ? 'windows' : 'mac');
  // Starts the file that was just downloaded. It never downloads and runs anything in one go.
  const startLine = downloadUrl => `bash ~/Downloads/${folderName(downloadUrl)}/"${LAUNCHER}"`;

  const STEPS = [
    { id: 'download', title: 'Download the lab', mock: 'download',
      say: ['Press the button. Your browser saves one ZIP file to your Downloads folder.', 'It holds the lab only: no model and no Ollama yet. You add those later, one approved step at a time.'],
      done: 'It downloaded',
      other: [['Nothing seems to happen', 'Look in your Downloads folder in Finder. Some browsers save the file without showing anything. If it isn\'t there, press the button again.'],
        ['My browser asks whether to allow downloads from this site', 'Allowing it is fine. It only saves the one ZIP file.']] },
    { id: 'unzip', title: 'Unzip it', mock: 'finder',
      say: ['Open Finder and go to Downloads. Safari unzips the file for you, so you may already see a folder. In other browsers, double-click the ZIP once.', 'Open the folder. Find the file called Start Lab on Mac, but don\'t double-click it: your Mac will block it. Keep this Finder window open for the next step.'],
      done: 'I see the folder',
      other: [['I only see a file ending in .zip', 'Double-click it once. A folder with the same name appears next to it.'],
        ['My folder\'s name ends in a number, like "2"', 'You downloaded it more than once. That\'s fine: the next step works with any folder name, anywhere.'],
        ['I can\'t find Start Lab on Mac in the folder', 'You have an older copy of the lab, from before this file was added. Move that folder to the Trash, then go back to step 1 and download it again. The new folder has Start Lab on Mac next to README.md.']] },
    { id: 'start', title: 'Start it from Terminal', mock: 'drag',
      say: ['Open Terminal: press Command and Space together, type Terminal, and press Return.'],
      todo: ['In Terminal, type bash and then a space. Don\'t press Return yet.', 'Drag Start Lab on Mac from your Finder window into the Terminal window. Its full location appears after bash.', 'Press Return.'],
      why: 'Why Terminal? Your Mac blocks double-clicking files from developers it doesn\'t know, and this lab isn\'t signed yet. Starting it this way changes no security setting. The file is plain text, so you can open it and read it first.',
      done: 'I pressed Return',
      other: [['I double-clicked the file and my Mac says "Not Opened"', 'That\'s expected, and nothing is wrong with your file. Click Done, not Move to Trash. Then follow the three steps above.', 'dialog'],
        ['Terminal says "No such file or directory"', 'Check there is a space after bash, and drag the Start Lab on Mac file itself, not the folder. Then press Return again.'],
        ['Terminal says "command not found"', 'The word bash is missing at the start. Type bash and a space first, then drag the file in.'],
        ['I pasted a web address into Terminal', 'Web addresses go in your browser\'s address bar. Terminal only needs bash, a space, and the dragged file.'],
        ['I can\'t find Terminal', 'Open Finder, then Applications, then Utilities. Terminal is in there.']] },
    { id: 'first-run', title: 'Let it set itself up', mock: 'terminal-run',
      say: ['The first run takes about a minute. It makes a private Python environment inside the lab\'s own folder and nothing anywhere else.', 'When it\'s ready, Terminal prints a private link and your browser opens by itself.'],
      done: 'My browser opened',
      other: [['It says this Mac doesn\'t have Python, and asks me to press Return', 'That\'s the lab offering a private copy of Python, about 25 MB, inside its own folder. It shows where it comes from and checks it before using it. Press Return to agree, or close the window to stop.'],
        ['It says "Setup failed" or "The download failed"', 'Check your internet connection and do step 3 again. If it fails twice, copy the text in the Terminal window and send it to the team.'],
        ['My browser didn\'t open', 'Find the line in Terminal that starts with http://127.0.0.1 and copy all of it into your browser\'s address bar. Don\'t share that link: it\'s private to your laptop.'],
        ['Something else is on the screen', 'Paste what Terminal says into the box below.', 'error-box']] },
    { id: 'opened', title: 'Check that it\'s the lab', mock: 'lab',
      say: ['Look at the top of the new browser tab. The lab version has a green strip under the menu, and its menu starts with Set up.', 'Keep the Terminal window open while you use the lab. Closing it stops the lab; your models and results stay on your laptop.'],
      done: 'I see the green strip',
      other: [['The strip is yellow and says "Website version"', 'That tab is the website, not the lab. Go back to Terminal, copy the line that starts with http://127.0.0.1, and paste it into your browser\'s address bar.'],
        ['The page says it cannot reach the Lab Helper', 'The Terminal window was closed, or the lab stopped. Do step 3 again. It opens a new private link.']] },
  ];
  const WIN_STEPS = [
    { id: 'download', title: 'Download the lab', mock: 'win-download',
      say: ['Press the button. Your browser saves one ZIP file to your Downloads folder.', 'It holds the lab only: no model and no Ollama yet. You add those later, one approved step at a time.'],
      done: 'It downloaded',
      other: [['Nothing seems to happen', 'Open File Explorer and look in Downloads. Some browsers save the file without showing anything. If it isn\'t there, press the button again.'],
        ['My browser asks whether to allow downloads from this site', 'Allowing it is fine. It only saves the one ZIP file.']] },
    { id: 'unzip', title: 'Extract it', mock: 'extract',
      say: ['Open File Explorer and go to Downloads. Right-click the ZIP file, choose Extract All, then press Extract.', 'A new folder opens with one folder inside it, with the same name. Double-click that inner folder. The lab can\'t start from inside the ZIP, so always use this extracted folder.'],
      done: 'I opened the inner folder',
      other: [['I see only one folder, with the same name as the ZIP', 'That\'s expected. Double-click it: the lab\'s files, like agent and portal, are inside.'],
        ['I double-clicked the ZIP and I see files', 'That\'s a look inside the ZIP, not a real folder, and the lab can\'t start from there. Go back to Downloads, right-click the ZIP and choose Extract All.'],
        ['I can\'t find Extract All', 'Right-click the ZIP file itself, not the empty space next to it. On some laptops it\'s under Show more options.'],
        ['My folder\'s name ends in a number, like "(1)"', 'You downloaded it more than once. That\'s fine: use the folder that just opened.']] },
    { id: 'python', title: 'Find the Start file', mock: 'explorer',
      say: ['In this folder there are two files called Start Lab on Windows. Use the one whose Type starts with Python: it says Python File, or Python Source File on some laptops. The other one is a Windows Batch File.', 'If neither starts with Python (for example it says PY File), this laptop doesn\'t have Python yet. Install it from python.org with the normal options, then look again: the Type changes to Python File.'],
      why: 'Why Python? The lab is written in Python. The installer comes from the Python project and is signed, so Windows trusts it, and you only install it once.',
      done: 'I found the Python File',
      other: [['I can\'t see a Type column', 'In File Explorer, choose View, then Details. The Type column appears next to the names.'],
        ['I see the names with .py and .bat at the end', 'That\'s fine: your laptop shows file endings. Use Start Lab on Windows.py.'],
        ['The Python installer asks for an administrator password', 'Stop there. The lab never needs one. If this is a school or work laptop, ask whoever manages it to install Python for you.'],
        ['I can\'t find Start Lab on Windows in the folder', 'First check you opened the inner folder from the last step: you should see agent, portal and README here. If you do and the file still isn\'t there, you have an older copy of the lab. Delete that folder, then go back to step 1 and download it again.']] },
    { id: 'start', title: 'Double-click it', mock: 'win-start',
      say: ['Double-click Start Lab on Windows, the one whose Type starts with Python. A black window opens.'],
      why: 'Why this file? Windows can block downloaded .bat files, but this one opens with Python, which Windows trusts. It changes no settings. It\'s plain text, so you can open it in Notepad and read it first.',
      done: 'A black window opened',
      other: [['Windows asks how to open the file, or it opens in Notepad', 'This laptop doesn\'t have Python yet. Go back a step and install it, then double-click the file again.'],
        ['Windows blocked Start Lab on Windows.bat', 'That\'s the other file with the same name. Use the one whose Type starts with Python.'],
        ['The window says "The lab needs Python 3.11 or newer"', 'Your Python is too old for the lab. Install the latest one from python.org, then double-click the file again.'],
        ['A blue "Windows protected your PC" box appears', 'Choose Don\'t run, and tell the team. Don\'t turn off any protection to get past it.']] },
    { id: 'first-run', title: 'Let it set itself up', mock: 'win-run',
      say: ['The first run takes about a minute. It makes a private Python environment inside the lab\'s agent folder and nothing anywhere else.', 'When it\'s ready, the black window prints a private link and your browser opens by itself.'],
      done: 'My browser opened',
      other: [['It says "Installing the lab\'s package failed" or "Setup failed"', 'Check your internet connection, delete the .venv folder inside the agent folder, then double-click the Start file again. If it fails twice, copy the window\'s text and send it to the team.'],
        ['My browser didn\'t open', 'In the black window, select the line that starts with http://127.0.0.1, press Ctrl+C, and paste it into your browser\'s address bar. Don\'t share that link: it\'s private to your laptop.'],
        ['Something else is on the screen', 'Paste what the window says into the box below.', 'error-box']] },
    { id: 'opened', title: 'Check that it\'s the lab', mock: 'lab',
      say: ['Look at the top of the new browser tab. The lab version has a green strip under the menu, and its menu starts with Set up.', 'Keep the black window open while you use the lab. Closing it stops the lab; your models and results stay on your laptop.'],
      done: 'I see the green strip',
      other: [['The strip is yellow and says "Website version"', 'That tab is the website, not the lab. In the black window, copy the line that starts with http://127.0.0.1 and paste it into your browser\'s address bar.'],
        ['The page says it cannot reach the Lab Helper', 'The black window was closed, or the lab stopped. Double-click the Start file again. It opens a new private link.']] },
  ];
  // Everything in the downloaded folder, the way each system lists it, so the drawings match what students really see.
  // Finder sorts by name; File Explorer puts folders first and hides file endings, so it shows each file's Type instead.
  const FOLDER = [['agent', true], ['benchmark_telemetry.py'], ['docs', true], ['evaluation', true], ['package.json'], ['portal', true],
    ['README.md'], ['scripts', true], [LAUNCHER], ['Start Lab on Windows.bat'], [WIN_LAUNCHER]];
  const TYPES = { py: 'Python File', json: 'JSON File', md: 'MD File', command: 'COMMAND File', bat: 'Windows Batch File' };
  const WIN_FOLDER = [...FOLDER.filter(([, dir]) => dir), ...FOLDER.filter(([, dir]) => !dir)].map(([n, dir]) => {
    const dot = n.lastIndexOf('.');
    return dir ? { file: n, shown: n, type: 'File folder' } : { file: n, shown: n.slice(0, dot), type: TYPES[n.slice(dot + 1)] };
  });
  const GUIDES = { mac: { label: 'Mac', steps: STEPS }, windows: { label: 'Windows', steps: WIN_STEPS } };
  const api = { STEPS, WIN_STEPS, GUIDES, LAUNCHER, WIN_LAUNCHER, FOLDER, WIN_FOLDER, folderName, startLine, pickSystem };
  root.LocalLabStart = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined' || !document.getElementById('start-body')) return;

  // ---------------------------------------------------------------- the page
  const guide = root.LocalLabGuide, errors = root.LocalLabCatalog.errors;
  const url = guide.DOWNLOAD_URL, folder = folderName(url), line = startLine(url);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const body = document.getElementById('start-body');
  const store = { get: () => { try { return localStorage.getItem('lab-start-os'); } catch (_) { return null; } },
    set: v => { try { localStorage.setItem('lab-start-os', v); } catch (_) { /* private window: just don't remember */ } } };
  const saved = store.get();
  const state = { os: GUIDES[saved] ? saved : pickSystem((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || navigator.userAgent),
    step: 0, finished: false, other: false, diagnosis: '' };
  const steps = () => GUIDES[state.os].steps;
  const winBar = (title, inner, cls = '') => `<div class="mock win ${cls}" aria-hidden="true"><div class="mock-bar"><span>${esc(title)}</span><em>–</em><em>▢</em><em>✕</em></div>${inner}</div>`;
  const winRow = (f, on) => `<div class="mock-row${on ? ' on' : ''}"><b class="mock-icon ${f.type === 'File folder' ? 'dir' : f.type === 'Python File' ? 'py' : 'file'}"></b>${esc(f.shown)}<small>${esc(f.type)}${on ? ' · this one' : ''}</small></div>`;

  const windowHtml = (title, inner, cls = '') => `<div class="mock ${cls}" aria-hidden="true"><div class="mock-bar"><i></i><i></i><i></i><span>${esc(title)}</span></div>${inner}</div>`;
  const MOCKS = {
    download: () => windowHtml('Downloads', `<div class="mock-row on"><b class="mock-icon zip"></b>${esc(folder)}.zip<small>about 1 MB</small></div>`),
    finder: () => windowHtml(folder, FOLDER.map(([n, dir]) => n === LAUNCHER
      ? `<div class="mock-row on"><b class="mock-icon file"></b>${esc(n)}<small>this one</small></div>`
      : `<div class="mock-row"><b class="mock-icon ${dir ? 'dir' : 'file'}"></b>${esc(n)}</div>`).join('')),
    drag: () => `<div class="mock-drag" aria-hidden="true">${windowHtml(folder, `<div class="mock-row"><b class="mock-icon file"></b>README.md</div><div class="mock-row"><b class="mock-icon dir"></b>scripts</div>
        <div class="mock-row on"><b class="mock-icon file"></b>${esc(LAUNCHER)}</div>`, 'drag-from')}
      <span class="drag-chip"><b class="mock-icon file"></b>${esc(LAUNCHER)}</span>
      ${windowHtml('Terminal', `<pre class="mock-term"><span class="dim">you@Mac ~ %</span> bash <span class="drag-path">~/Downloads/${esc(folder)}/Start\\ Lab\\ on\\ Mac.command</span><span class="mock-caret"></span></pre>`, 'dark drag-to')}</div>`,
    'terminal-start': () => windowHtml('Terminal', `<pre class="mock-term"><span class="dim">you@Mac ~ %</span> ${esc(line)}<span class="mock-caret"></span></pre>`, 'dark'),
    'terminal-run': () => windowHtml('Terminal', `<pre class="mock-term">First run: creating the lab's private Python environment in this folder (about 20 seconds).
This only adds a .venv folder here. Delete the folder to undo it.
Local AI Lab helper is running on this laptop only.
Keep this window open. Nothing changes on your laptop until you approve a step.
Open this private launch link (do not share its token):
  <span class="hi">http://127.0.0.1:8765/#t=…</span></pre>`, 'dark'),
    lab: () => windowHtml('Local AI Lab · Set up', `<div class="mock-nav"><b>Set up</b><span>Catalog</span><span>Use it</span><span>Measure</span><span>My lab</span><span>Learn</span></div>
      <div class="mock-strip">Lab version, running on this laptop.</div><div class="mock-page">Run AI on <em>your laptop.</em></div>`),
    'win-download': () => winBar('Downloads', `<div class="mock-row on"><b class="mock-icon zip"></b>${esc(folder)}<small>Compressed (zipped) Folder</small></div>`),
    extract: () => winBar('Downloads', `<div class="mock-row on"><b class="mock-icon zip"></b>${esc(folder)}<small>Compressed (zipped) Folder</small></div>
      <div class="mock-menu"><span>Open</span><span class="pick">Extract All…</span><span>Copy</span><span>Show more options</span></div>`)
      + winBar(folder, `<div class="mock-row on"><b class="mock-icon dir"></b>${esc(folder)}<small>File folder · open this one</small></div>`),
    explorer: () => winBar(folder, WIN_FOLDER.map(f => winRow(f, f.file === WIN_LAUNCHER)).join('')),
    'win-start': () => winBar(folder, WIN_FOLDER.filter(f => f.file.startsWith('Start Lab on Windows')).map(f => winRow(f, f.file === WIN_LAUNCHER)).join('')
      + '<p class="mock-hint">Double-click the Python File</p>'),
    'win-run': () => winBar('Start Lab on Windows', `<pre class="mock-term">First run: creating the lab's private Python environment in this folder.
This only adds a .venv folder in the agent folder. Delete that folder to undo it.
Local AI Lab helper is running on this laptop only.
Keep this window open. Nothing changes on your laptop until you approve a step.
Open this private launch link (do not share its token):
  <span class="hi">http://127.0.0.1:8765/#t=…</span></pre>`, 'dark'),
    dialog: () => `<div class="mock mock-dialog" aria-hidden="true"><div class="mock-warn">!</div><strong>“${esc(LAUNCHER)}” Not Opened</strong>
      <p>Apple could not verify “${esc(LAUNCHER)}” is free of malware that may harm your Mac or compromise your privacy.</p>
      <span class="mock-btn">Move to Trash</span><span class="mock-btn pick">Done</span></div>`,
  };

  function otherHtml(step) {
    return `<div class="start-other">${step.other.map(([q, a, extra]) => `<details><summary>${esc(q)}</summary><p>${esc(a)}</p>
      ${extra === 'dialog' ? MOCKS.dialog() : ''}
      ${extra === 'error-box' ? `<form id="start-err-form"><textarea id="start-err" rows="3" aria-label="What the window says" placeholder="Paste the text from the window here. It's checked in your browser and sent nowhere."></textarea>
        <button class="btn small" type="submit">Check it</button><div id="start-err-out" aria-live="polite">${state.diagnosis}</div></form>` : ''}</details>`).join('')}
      <p class="small muted">Still stuck? Copy what you see and <a href="https://github.com/aryawuyitong/local-llm-telemetry-dashboard/issues/new" target="_blank" rel="noopener noreferrer">tell the team</a>. Don't turn off any security setting to get past a step.</p></div>`;
  }

  function osHtml() {
    return `<div class="start-os" role="group" aria-label="Your computer"><span class="small muted">Your computer:</span>${Object.entries(GUIDES).map(([k, g]) =>
      `<button class="btn small" data-start-os="${k}" aria-pressed="${k === state.os}">${g.label}</button>`).join('')}</div>`;
  }
  function render() {
    document.getElementById('start-eyebrow').textContent = `START GUIDE · ${GUIDES[state.os].label.toUpperCase()}`;
    document.getElementById('start-intro').textContent = `${steps().length} short steps. Each one shows what you should see, so you always know whether it worked.`;
    if (state.finished) {
      body.innerHTML = `<div class="card start-done"><span class="badge ok">You're in</span><h2>The lab is running on your laptop.</h2>
        <p>Carry on in the lab's own tab. Start with <strong>Set up</strong>, step 1: press <strong>Run this check</strong>. Every step after that shows its command and its cost, and waits for your approval.</p>
        <p><strong>To come back another day,</strong> open Ollama, then ${state.os === 'windows'
          ? 'double-click Start Lab on Windows (the Python File) in the lab\'s folder again.'
          : 'do step 3 again: in Terminal type <code class="cmd">bash</code> and a space, drag in Start Lab on Mac, and press Return.'}</p>
        <div class="actions"><button class="btn" data-start-go="0">Go through the guide again</button><a class="btn" href="#learn">Learn how it works</a></div></div>`;
      return;
    }
    const list = steps(), s = list[state.step], n = list.length;
    body.innerHTML = `${osHtml()}<ol class="start-dots" aria-label="Steps">${list.map((x, i) => `<li><button class="${i === state.step ? 'on' : i < state.step ? 'done' : ''}" data-start-go="${i}" aria-current="${i === state.step ? 'step' : 'false'}"><b>${i < state.step ? '✓' : i + 1}</b><span>${esc(x.title)}</span></button></li>`).join('')}</ol>
      <div class="card start-step"><div class="start-text"><p class="small muted">Step ${state.step + 1} of ${n}</p><h2>${esc(s.title)}</h2>
          ${s.say.map(p => `<p>${esc(p)}</p>`).join('')}
          ${s.id === 'download' ? `<p><a class="btn primary" href="${esc(url)}" rel="noopener noreferrer">Download for ${GUIDES[state.os].label}</a></p>
            <p class="small muted">It's the same ZIP for Mac and Windows; only the start file differs.</p>` : ''}
          ${s.id === 'python' ? '<p><a class="btn small" href="https://www.python.org/downloads/" target="_blank" rel="noopener noreferrer">Get Python from python.org</a></p>' : ''}
          ${s.todo ? `<ol class="start-todo">${s.todo.map(t => `<li>${esc(t)}</li>`).join('')}</ol>` : ''}
          ${s.id === 'start' && state.os === 'mac' ? `<details class="start-shortcut"><summary>Shortcut if your folder is in Downloads with its usual name</summary>
            <p>Copy this line, paste it into Terminal, and press Return. If Terminal says "No such file or directory", use the three steps above instead.</p>
            <p><code class="cmd start-line">${esc(line)}</code> <button class="btn small" data-start-copy>Copy</button></p></details>
            ` : ''}
          ${s.why ? `<p class="small muted">${esc(s.why)}</p>` : ''}
          <div class="actions"><button class="btn primary" data-start-next>${esc(s.done)}</button>
            <button class="btn" data-start-other aria-expanded="${state.other}">I see something else</button>
            ${state.step ? '<button class="btn" data-start-back>Back</button>' : ''}</div></div>
        <div class="start-mock"><p class="small muted">What you should see</p>${MOCKS[s.mock]()}</div>
        ${state.other ? otherHtml(s) : ''}</div>`;
  }

  function go(step) { Object.assign(state, { step: Math.max(0, Math.min(steps().length - 1, step)), finished: false, other: false, diagnosis: '' }); render(); body.querySelector('h2').scrollIntoView({ block: 'center' }); }

  body.addEventListener('click', async e => {
    const t = e.target.closest('button');
    if (!t) return;
    const d = t.dataset;
    if (d.startOs) { state.os = d.startOs; store.set(d.startOs); go(0); }
    else if ('startNext' in d) { if (state.step === steps().length - 1) { state.finished = true; render(); } else go(state.step + 1); }
    else if ('startBack' in d) go(state.step - 1);
    else if (d.startGo) go(+d.startGo);
    else if ('startOther' in d) { state.other = !state.other; render(); }
    else if ('startCopy' in d) {
      try { await navigator.clipboard.writeText(line); t.textContent = 'Copied'; } catch (_) { t.textContent = 'Select the line to copy it'; }
      setTimeout(() => { t.textContent = 'Copy'; }, 1800);
    }
  });
  body.addEventListener('submit', e => {
    if (e.target.id !== 'start-err-form') return;
    e.preventDefault();
    const text = document.getElementById('start-err').value;
    const hit = text.trim() ? guide.matchErrors(text, errors)[0] : null;
    state.diagnosis = !text.trim() ? '<p class="note warn small">Paste the text first.</p>'
      : hit ? `<div class="note small"><strong>${esc(hit.title)}.</strong> ${esc(hit.cause)}<ol>${[].concat(hit.fix).map(f => `<li>${esc(f)}</li>`).join('')}</ol></div>`
        : '<p class="note small">That isn\'t on our list of known problems, so we won\'t guess. Copy it and tell the team.</p>';
    document.getElementById('start-err-out').innerHTML = state.diagnosis;
  });
  render();
})(typeof globalThis !== 'undefined' ? globalThis : this);

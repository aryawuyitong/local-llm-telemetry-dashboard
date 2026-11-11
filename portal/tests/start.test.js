'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
require('../lab-data.js');
require('../measured-data.js');
const G = require('../guide.js');
const S = require('../start.js');
const repo = path.join(__dirname, '..', '..');

test('the folder name follows the download link, whatever the branch', () => {
  assert.equal(S.folderName('https://github.com/a/local-llm-telemetry-dashboard/archive/refs/heads/main.zip'), 'local-llm-telemetry-dashboard-main');
  assert.equal(S.folderName('https://github.com/a/local-llm-telemetry-dashboard/archive/refs/heads/proposal/transparent-agent.zip'), 'local-llm-telemetry-dashboard-proposal-transparent-agent');
});

test('the line starts the downloaded file and never downloads and runs in one go', () => {
  const line = S.startLine(G.DOWNLOAD_URL);
  assert.equal(line, `bash ~/Downloads/${S.folderName(G.DOWNLOAD_URL)}/"${S.LAUNCHER}"`);
  assert.doesNotMatch(line, /curl|wget|\||sudo|http/);
});

test('the file the guide names exists, can be run, and only opens the real launcher', () => {
  const file = path.join(repo, S.LAUNCHER);
  assert.ok(fs.statSync(file).mode & 0o111, 'executable');
  const text = fs.readFileSync(file, 'utf8');
  assert.match(text, /exec bash "\.\/Start Lab Helper\.command"/);
  assert.doesNotMatch(text, /curl|sudo|xattr|spctl/);
  assert.ok(fs.existsSync(path.join(repo, 'agent', 'Start Lab Helper.command')));
});

test('the Terminal drawing uses the launcher\'s own words', () => {
  const launcher = fs.readFileSync(path.join(repo, 'agent', 'Start Lab Helper.command'), 'utf8');
  const helper = fs.readFileSync(path.join(repo, 'agent', 'telemetry_agent', 'helper.py'), 'utf8');
  const page = fs.readFileSync(path.join(__dirname, '..', 'start.js'), 'utf8');
  for (const words of ["First run: creating the lab's private Python environment in this folder (about 20 seconds).", 'This only adds a .venv folder here. Delete the folder to undo it.']) {
    assert.ok(launcher.includes(words) && page.includes(words), words);
  }
  for (const words of ['Keep this window open. Nothing changes on your laptop until you approve a step.', 'Open this private launch link (do not share its token):']) {
    assert.ok(helper.includes(words) && page.includes(words), words);
  }
});

test('every step says what to do, what counts as done, and what to do otherwise', () => {
  assert.deepEqual(S.STEPS.map(s => s.id), ['download', 'unzip', 'start', 'first-run', 'opened']);
  for (const s of S.STEPS) {
    assert.ok(s.title && s.say.length && s.done && s.mock, s.id);
    assert.ok(s.other.length >= 2 && s.other.every(o => o[0] && o[1]), s.id);
  }
  const advice = JSON.stringify(S.STEPS);
  assert.doesNotMatch(advice, /Open Anyway|System Settings|xattr|disable/i);  // never a way round the Mac's protection
});

test('the folder drawing lists every top-level item the download really has', () => {
  const root = path.join(__dirname, '..', '..');
  const ignored = fs.readFileSync(path.join(root, '.gitignore'), 'utf8').split('\n').map(l => l.trim().replace(/\/$/, ''));
  const shipped = fs.readdirSync(root).filter(n => !n.startsWith('.') && !ignored.includes(n)).sort();
  assert.deepEqual(S.FOLDER.map(([n]) => n).sort(), shipped);
});

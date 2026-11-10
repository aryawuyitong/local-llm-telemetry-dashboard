'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
require('../preview-data.js');
require('../lab-data.js');
const P = require('../preview.js');
const data = globalThis.LocalLabPreview;

test('the demo cards come from the registry, with a cost on every one', () => {
  for (const platform of ['mac', 'windows']) {
    const cards = data.cards[platform];
    assert.deepEqual(cards.map(c => c.id), ['check_hardware', 'install_runtime', 'start_runtime', 'pull_model', 'first_prompt']);
    for (const c of cards) {
      assert.deepEqual(Object.keys(c.risk), ['time', 'space', 'internet', 'password', 'money', 'undo'], c.id);
      for (const key of ['title', 'what', 'why', 'does']) assert.ok(c[key], `${c.id} ${key}`);
    }
    assert.equal(cards.find(c => c.id === 'pull_model').command, 'ollama pull ' + data.model);
  }
  assert.equal(data.cards.windows[0].command, 'systeminfo');
});

test('the demo model is on the approved list, at the size the catalog gives', () => {
  const model = globalThis.LocalLabCatalog.models.find(m => m.ollama_tag === data.model);
  assert.equal(model.size_gb, data.size_gb);
});

test('every sample says where it was recorded and holds nothing personal', () => {
  const s = data.samples;
  assert.ok(s.recorded.device && /^\d{4}-\d{2}-\d{2}$/.test(s.recorded.on));
  for (const reply of [...s.chats, ...s.compare.answers]) {
    assert.ok(reply.text && reply.tps > 0 && reply.tokens > 0, reply.question);
    assert.ok(globalThis.LocalLabCatalog.models.some(m => m.ollama_tag === reply.model));
  }
  assert.ok(s.chats.every(c => c.note));
  assert.doesNotMatch(JSON.stringify(data), /\/Users\/|\/home\/|[A-Za-z]:\\\\Users/);
});

test('the log lists only what changed, and only the download can be undone', () => {
  assert.deepEqual(P.changeLog({}, data), []);
  const rows = P.changeLog({ start_runtime: true, pull_model: true }, data);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map(r => !!r.undo), [false, true]);
  assert.match(rows[1].what, new RegExp(data.model));
});

test('fit groups keep the lab\'s wording and drop empty groups', () => {
  const groups = P.fitGroups([{ name: 'a', verdict: 'yes' }, { name: 'b', verdict: 'no' }]);
  assert.deepEqual(groups, [{ label: 'Ready now', models: ['a'] }, { label: "Won't fit right now", models: ['b'] }]);
});

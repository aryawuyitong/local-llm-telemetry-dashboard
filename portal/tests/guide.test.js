'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
require('../lab-data.js');
require('../measured-data.js');
const G = require('../guide.js');
const catalog = globalThis.LocalLabCatalog;
const model = tag => catalog.models.find(m => m.ollama_tag === tag);

test('every catalog pattern compiles in the browser', () => {
  for (const entry of catalog.errors) for (const pattern of entry.patterns) assert.doesNotThrow(() => new RegExp(pattern, 'i'), entry.id);
});

test('pasted errors match the same entries the agent would use, and unknown text matches nothing', () => {
  assert.equal(G.matchErrors('OSError: [Errno 28] No space left on device', catalog.errors)[0].id, 'disk_full');
  assert.deepEqual(G.matchErrors('the weather is nice today', catalog.errors), []);
});

test('fit follows memory and keeps the disk reserve', () => {
  assert.equal(G.modelFit(model('qwen2.5:1.5b'), 8, 20).verdict, 'yes');
  assert.equal(G.modelFit(model('qwen2.5:3b'), 8, 20).verdict, 'tight');
  assert.equal(G.modelFit(model('qwen2.5:7b'), 8, 20).verdict, 'no');
  assert.equal(G.modelFit(model('qwen2.5:1.5b'), 32, 2.5).verdict, 'no');
});

test('measured numbers only name models on the approved list', () => {
  for (const tag of Object.keys(G.MEASURED)) assert.ok(model(tag), tag);
});

test('direct commands fit each platform and never elevate', () => {
  assert.match(G.directCommands(true), /\.venv\/bin\/python -m telemetry_agent\.helper/);
  assert.match(G.directCommands(false), /Scripts\\python\.exe -m telemetry_agent\.helper/);
  assert.doesNotMatch(G.directCommands(true) + G.directCommands(false), /sudo|runas/i);
});

test('the starting model is small, has no license step and respects memory', () => {
  assert.equal(G.startingModel(catalog.models, 16).ollama_tag, 'qwen2.5:1.5b');
  assert.equal(G.startingModel(catalog.models, 4).ollama_tag, 'qwen2.5:0.5b');  // same as the helper: 1.5B would be a squeeze
  assert.equal(G.startingModel(catalog.models, 2), null);
  assert.ok(catalog.models.every(m => m.about && m.family));
});

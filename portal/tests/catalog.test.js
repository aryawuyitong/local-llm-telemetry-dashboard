'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
require('../lab-data.js');
require('../catalog-data.js');
require('../measured-data.js');
const G = require('../guide.js');
const C = require('../catalog.js');
const setups = globalThis.LocalLabCatalogSetups, measured = globalThis.LocalLabMeasured, catalog = globalThis.LocalLabCatalog;
const RISKS = ['time', 'space', 'internet', 'password', 'money', 'undo'];

test('every setup shows every step, with a cost on each, and ends in one check', () => {
  assert.ok(setups.recipes.length >= 3);
  for (const r of setups.recipes) for (const platform of ['mac', 'windows']) {
    const steps = r.steps[platform];
    assert.equal(steps[steps.length - 1].title, 'Check that everything is in place', r.id);
    for (const s of steps) {
      assert.deepEqual(Object.keys(s.risk), RISKS, `${r.id} ${s.title}`);
      assert.ok(s.title && s.does, `${r.id} ${s.title}`);
      assert.ok(s.command || s.kind === 'manual' || /^Check/.test(s.title), `${r.id}: ${s.title} shows a command or says you do it yourself`);
    }
    assert.ok(steps.some(s => /^ollama pull /.test(s.command || '')), r.id);
  }
});

test('the space a setup adds is the sum of what it downloads', () => {
  const size = tag => catalog.models.find(m => m.ollama_tag === tag).size_gb;
  const starter = setups.recipes.find(r => r.id === 'try-local-ai');
  assert.equal(starter.adds_gb, size('qwen2.5:1.5b'));
  const coding = setups.recipes.find(r => r.id === 'coding-starter');
  assert.equal(coding.adds_gb, Math.round((size('qwen2.5:1.5b') + setups.apps.find(a => a.id === 'vscode').size_gb) * 10) / 10);
});

test('mac and windows get their own commands, and every app says how to undo it', () => {
  for (const a of setups.apps) {
    assert.match(a.install.mac.command, /^brew install --cask /);
    assert.match(a.install.windows.command, /^winget install --id /);
    assert.match(a.remove.mac, /^brew uninstall --cask /);
    assert.match(a.remove.windows, /^winget uninstall --id /);
  }
});

test('totals say when an installer the student runs might ask for a password', () => {
  const rows = Object.fromEntries(C.totals(setups.recipes[0], 'mac'));
  assert.match(rows.Password, /lab never asks/);
  assert.equal(rows.Money, 'Free');
  assert.match(rows.Space, /GB/);
});

test('measured results name only approved models and carry real counts', () => {
  assert.ok(measured.sessions >= 1);
  for (const kind of measured.kinds) for (const m of kind.models) {
    assert.ok(catalog.models.some(x => x.ollama_tag === m.model), m.model);
    assert.ok(m.tps_low <= m.tps && m.tps <= m.tps_high && m.runs >= 1 && m.sessions >= 1);
  }
  assert.doesNotMatch(JSON.stringify(measured), /\/Users\/|alias|device-[0-9a-f]{8}/);
});

test('laptops like yours come first, and the picker uses the same numbers', () => {
  const some = measured.kinds[0], model = some.models[0].model;
  assert.equal(C.measuredFor(measured, model, some.ram_gb)[0].device, some.device);
  assert.deepEqual(C.measuredFor(measured, 'not-a-model', 8), []);
  assert.equal(G.measuredRun(model, some.ram_gb).tps, C.speedText(some.models[0]));
  assert.equal(G.measuredRun('not-a-model', 8), undefined);
});

'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
require('../lab-data.js');
require('../preview-data.js');
const G = require('../guide.js');
const L = require('../learn.js');
const catalog = globalThis.LocalLabCatalog, samples = globalThis.LocalLabPreview.samples;
const model = tag => catalog.models.find(m => m.ollama_tag === tag);

test('token pieces rebuild the reply exactly, one piece per token', () => {
  for (const reply of samples.chats) {
    const pieces = L.tokenPieces(reply.text, reply.tokens);
    assert.equal(pieces.join(''), reply.text);
    assert.equal(pieces.length, Math.min(reply.tokens, reply.text.length));
  }
  assert.deepEqual(L.tokenPieces('ab', 5), ['a', 'b']);
});

test('time is tokens divided by speed', () => {
  assert.equal(L.secondsFor(46, 10), 4.6);
  assert.equal(L.secondsFor(46, 165), 0.3);
});

test('the fit tool uses the same rule as the Start page', () => {
  for (const memory of [4, 8, 16, 32]) for (const m of catalog.models) {
    const view = L.fitView(m, memory, G.modelFit);
    assert.equal(view.verdict, G.modelFit(m, memory, 100).verdict, `${m.ollama_tag} at ${memory}`);
    assert.ok(view.share > 0 && view.share <= 1);
  }
  assert.equal(L.fitView(model('qwen2.5:7b'), 8, G.modelFit).verdict, 'no');  // the guess the tool opens with
  assert.equal(L.fitView(model('qwen2.5:1.5b'), 8, G.modelFit).verdict, 'yes');
});

test('the speeds offered are the recorded ones, plus one slow laptop', () => {
  const choices = L.speedChoices(samples);
  assert.equal(choices[0].rate, 10);
  const recorded = [...samples.compare.answers, ...samples.chats].map(r => Math.round(r.tps));
  for (const c of choices.slice(1)) assert.ok(recorded.includes(c.rate), String(c.rate));
  assert.deepEqual(choices.slice(1).map(c => c.rate), [...choices.slice(1).map(c => c.rate)].sort((a, b) => a - b));
});

test('the journey has five stops and the card explains every part', () => {
  assert.equal(L.STOPS.length, 5);
  assert.ok(L.STOPS.every(s => s.name && s.where && s.does && s.detail));
  assert.deepEqual(L.CARD_PARTS.map(p => p.id), ['risk', 'what', 'why', 'does', 'undo', 'command', 'buttons']);
});

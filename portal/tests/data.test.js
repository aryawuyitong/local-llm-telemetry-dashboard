'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const D = require('../data.js');
const fixture = name => JSON.parse(fs.readFileSync(path.join(__dirname, '../examples/', name), 'utf8'));
const valid = () => fixture('synthetic-macos.json');

test('both bundled examples satisfy the portal contract and remain explicitly synthetic', () => {
  for (const name of ['synthetic-macos.json', 'synthetic-windows.json']) {
    const result = D.validateSession(fixture(name));
    assert.deepEqual(result.errors, []);
    assert.equal(result.session.data_kind, 'synthetic');
    assert.ok(result.warnings.some(w => w.includes('invented')));
  }
});

test('one unavailable CPU sample stays missing rather than lowering the median', () => {
  const data = fixture('synthetic-windows.json');
  const rows = D.filterRuns([data]);
  const expected = data.runs.filter(r => r.status !== 'error' && r.measurements.cpu_percent_normalized !== null).map(r => r.measurements.cpu_percent_normalized);
  const summary = D.aggregate(rows);
  assert.equal(summary.metrics.cpu_percent_normalized.count, expected.length);
  assert.equal(summary.metrics.cpu_percent_normalized.missing, data.runs.length - expected.length);
  assert.equal(summary.metrics.cpu_percent_normalized.median, D.median(expected));
  assert.equal(summary.partial, 1);
});

test('failed runs do not contaminate a median; real zero is retained', () => {
  const data = valid();
  data.runs = data.runs.slice(0, 3);
  data.runs[0].measurements.decode_tps = 0;
  data.runs[1].measurements.decode_tps = 10;
  data.runs[2].measurements.decode_tps = 999999;
  data.runs[2].status = 'error'; data.runs[2].error = 'Runtime unavailable';
  assert.equal(D.aggregate(D.filterRuns([data])).metrics.decode_tps.median, 5);
  assert.equal(D.aggregate(D.filterRuns([data])).failed, 1);
});

test('filters isolate sessions and prompts without mutating the inputs', () => {
  const a = valid(), b = fixture('synthetic-windows.json');
  const snapshot = JSON.stringify([a, b]);
  const rows = D.filterRuns([a, b], { device: b.device.alias, model: b.model.name, prompt: 'long', kind: 'synthetic' });
  assert.equal(rows.length, 3);
  assert.ok(rows.every(r => r.session === b && r.run.prompt_id === 'long'));
  assert.equal(D.filterRuns([a, b], { kind: 'measured' }).length, 0);
  assert.equal(JSON.stringify([a, b]), snapshot);
});

test('malformed JSON, null sessions, missing keys, unknown fields, wrong versions and oversized files fail clearly', () => {
  assert.match(D.parseSession('{').errors[0], /Invalid JSON/);
  assert.ok(D.validateSession(null).errors.length);
  assert.ok(D.validateSession([]).errors.length);
  const missing = valid(); delete missing.runs[0].measurements.ttft_ms;
  assert.ok(D.validateSession(missing).errors.some(e => /ttft_ms.*required/.test(e)));
  const extra = valid(); extra.unexpected = true;
  assert.ok(D.validateSession(extra).errors.some(e => e.includes('unexpected')));
  const wrong = valid(); wrong.protocol_version = 'local-llm-lab/2';
  assert.ok(D.validateSession(wrong).errors.some(e => e.includes('protocol_version')));
  assert.match(D.parseSession('{}', D.MAX_FILE_BYTES + 1).errors[0], /5 MiB/);
  assert.match(D.parseSession(' '.repeat(D.MAX_FILE_BYTES + 1)).errors[0], /5 MiB/);
});

test('negative, infinite, stringified, and out-of-range metric values are rejected', () => {
  for (const bad of [-1, Infinity, NaN, '22']) {
    const data = valid(); data.runs[0].measurements.decode_tps = bad;
    assert.ok(D.validateSession(data).errors.some(e => e.includes('decode_tps')));
  }
  const data = valid(); data.runs[0].measurements.cpu_percent_normalized = 100.01;
  assert.ok(D.validateSession(data).errors.some(e => e.includes('cpu_percent_normalized')));
  const summary = valid(); summary.summary.nested = { value: Infinity };
  assert.ok(D.validateSession(summary).errors.some(e => e.includes('non-finite')));
});

test('duplicate IDs and duplicate prompt/repeat pairs are rejected', () => {
  const data = valid();
  data.runs[1].run_id = data.runs[0].run_id;
  assert.ok(D.validateSession(data).errors.some(e => e.includes('duplicate run')));
  const pair = valid(); pair.runs[1].repeat_index = pair.runs[0].repeat_index;
  assert.ok(D.validateSession(pair).errors.some(e => e.includes('duplicate prompt/repeat')));
  assert.match(D.addSession([valid()], valid()).errors[0], /Duplicate session/);
  const cross = fixture('synthetic-windows.json'); cross.runs[0].run_id = valid().runs[0].run_id;
  assert.match(D.addSession([valid()], cross).errors[0], /run ID duplicates/);
});

test('status and source requirements distinguish success, partial data, and errors', () => {
  const success = valid(); success.runs[0].measurements.ttft_ms = null;
  assert.ok(D.validateSession(success).errors.some(e => e.includes('ok requires')));
  success.runs[0].status = 'partial';
  assert.deepEqual(D.validateSession(success).errors, []);
  success.runs[0].sources.decode_duration_s = 0;
  assert.ok(D.validateSession(success).errors.some(e => e.includes('decode_duration_s')));
  const failed = valid(); failed.runs[0].status = 'error';
  assert.ok(D.validateSession(failed).errors.some(e => e.includes('must explain')));
  const old = valid(); old.runtime.version = null;
  assert.deepEqual(D.validateSession(old).errors, []);
  const provenance = valid(); provenance.runs[0].sources.decode_tps = null;
  assert.ok(D.validateSession(provenance).errors.some(e => e.includes('must record its source')));
  const partial = valid(); partial.runs[0].status = 'partial'; partial.runs[0].quality_flags = [];
  assert.ok(D.validateSession(partial).errors.some(e => e.includes('quality flag')));
});

test('unsupported prompts, bad UTC dates, personal aliases, and non-standard settings are rejected', () => {
  for (const mutate of [
    d => { d.runs[0].prompt_id = 'custom'; },
    d => { d.created_at = '2026-02-31T12:00:00Z'; },
    d => { d.created_at = '2026-10-30'; },
    d => { d.device.alias = 'Full Real Name'; },
    d => { d.config.repeats = 4; },
    d => { d.config.max_output_tokens = 256; },
    d => { d.runs[0].sources.prompt_hash = 'not-a-hash'; }
  ]) { const data = valid(); mutate(data); assert.ok(D.validateSession(data).errors.length); }
});

test('client recomputes statistics even when imported summary makes a false claim', () => {
  const data = valid(); data.summary.median_tps = 999999;
  const expected = D.median(data.runs.map(r => r.measurements.decode_tps));
  assert.equal(D.aggregate(D.filterRuns([data])).metrics.decode_tps.median, expected);
  assert.notEqual(expected, 999999);
});

test('summary structure cannot smuggle arbitrary raw logs, metadata, or malformed ranges', () => {
  for (const mutate of [
    data => { data.summary.raw_logs = 'private diagnostic text'; },
    data => { delete data.summary.method; },
    data => { data.summary.per_prompt.short.metadata = { path: '/private/path' }; },
    data => { data.summary.ttft_ms_range = [10, 1]; },
    data => { data.summary.valid_runs = 'nine'; }
  ]) { const data = valid(); mutate(data); assert.ok(D.validateSession(data).errors.some(e => e.startsWith('summary'))); }
});

test('empty metrics report null and no observations, never zero', () => {
  const empty = D.aggregate([]);
  assert.equal(empty.total, 0);
  assert.deepEqual(empty.metrics.ttft_ms, { median: null, min: null, max: null, count: 0, missing: 0 });
  assert.equal(D.median([null, NaN]), null);
  assert.equal(D.median([4, 1, 3, 2]), 2.5);
});

test('data model has no storage, DOM insertion, or network side effects', () => {
  const source = fs.readFileSync(path.join(__dirname, '../data.js'), 'utf8');
  assert.doesNotMatch(source, /fetch\(|localStorage|innerHTML|document\./);
  const app = fs.readFileSync(path.join(__dirname, '../app.js'), 'utf8');
  assert.doesNotMatch(app, /innerHTML|outerHTML|insertAdjacentHTML|eval\(|127\.0\.0\.1|localhost:/);
});

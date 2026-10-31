/* Local-only data model. No DOM, storage, or network side effects. */
(function (root) {
  'use strict';
  const MAX_FILE_BYTES = 5 * 1024 * 1024;
  const MAX_SESSIONS = 30;
  const METRICS = Object.freeze({
    ttft_ms: { label: 'TTFT proxy · first response text', short: 'TTFT proxy', unit: 'ms', max: 86400000, note: 'Client-observed request start to first non-empty response text. Includes prompt processing; not a verified token boundary.' },
    decode_tps: { label: 'Generation speed', short: 'TPS', unit: 'tokens/s', max: 1000000, note: 'Output tokens divided by runtime-reported decode duration; excludes prompt processing.' },
    cpu_percent_normalized: { label: 'CPU utilization', short: 'CPU', unit: '%', max: 100, note: 'Process CPU divided by logical core count. This is not GPU utilization.' },
    peak_rss_mib: { label: 'Peak process memory', short: 'RAM', unit: 'MiB', max: 104857600, note: 'Observed peak resident memory of attributable runtime processes; not GPU memory or total system memory.' }
  });
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const object = (x) => x !== null && typeof x === 'object' && !Array.isArray(x) && Object.getPrototypeOf(x) === Object.prototype;
  const finite = (x) => typeof x === 'number' && Number.isFinite(x);
  const str = (x, max = 500) => typeof x === 'string' && x.length > 0 && x.length <= max;
  function validateSession(value) {
    const errors = [], warnings = [];
    const fail = (p, why) => errors.push(p + ': ' + why);
    function record(x, path, required, optional = []) {
      if (!object(x)) { fail(path, 'must be an object'); return false; }
      for (const key of required) if (!own(x, key)) fail(path + '.' + key, 'is required');
      const allowed = new Set(required.concat(optional));
      for (const key of Object.keys(x)) if (!allowed.has(key)) fail(path + '.' + key, 'is not part of schema 1.0');
      return true;
    }
    function text(x, p, nullable = false) { if (!(nullable && x === null) && !str(x, 180)) fail(p, 'must be a non-empty string (up to 180 characters)' + (nullable ? ' or null' : '')); }
    function number(x, p, min, max, nullable = false, integer = false) {
      if (nullable && x === null) return;
      if (!finite(x) || x < min || x > max || (integer && !Number.isInteger(x))) fail(p, 'must be ' + (integer ? 'an integer' : 'a finite number') + ' from ' + min + ' to ' + max + (nullable ? ', or null' : ''));
    }
    function date(x, p) { if (!str(x, 60) || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(x) || !Number.isFinite(Date.parse(x)) || new Date(x).toISOString().slice(0, 19) !== x.slice(0, 19)) fail(p, 'must be a valid UTC ISO timestamp'); }
    function id(x, p) { if (typeof x !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/.test(x)) fail(p, 'must be a short, anonymous ID using letters, numbers, dots, underscores, or hyphens'); }
    if (!record(value, 'session', ['schema_version', 'protocol_version', 'data_kind', 'session_id', 'created_at', 'device', 'runtime', 'model', 'config', 'warmup_round_trip_s', 'predictions', 'runs', 'summary'])) return { errors, warnings, session: null };
    if (value.schema_version !== '1.0') fail('schema_version', 'unsupported version; expected 1.0');
    if (value.protocol_version !== 'local-llm-lab/1') fail('protocol_version', 'expected local-llm-lab/1');
    if (!['measured', 'synthetic'].includes(value.data_kind)) fail('data_kind', 'must be measured or synthetic');
    id(value.session_id, 'session_id'); date(value.created_at, 'created_at');
    if (record(value.device, 'device', ['alias', 'os', 'os_version', 'cpu_model', 'logical_cores', 'total_ram_gib', 'gpu', 'arch'])) {
      for (const k of ['alias', 'os', 'os_version', 'cpu_model', 'arch']) text(value.device[k], 'device.' + k);
      if (typeof value.device.alias !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$/.test(value.device.alias)) fail('device.alias', 'must be a short anonymous alias using letters, numbers, underscores, or hyphens');
      text(value.device.gpu, 'device.gpu');
      number(value.device.logical_cores, 'device.logical_cores', 1, 4096, false, true);
      number(value.device.total_ram_gib, 'device.total_ram_gib', 0, 1048576);
    }
    if (record(value.runtime, 'runtime', ['name', 'version'])) { text(value.runtime.name, 'runtime.name'); text(value.runtime.version, 'runtime.version', true); }
    if (record(value.model, 'model', ['name', 'digest', 'quantization', 'acceleration'])) {
      text(value.model.name, 'model.name');
      for (const k of ['digest', 'quantization']) text(value.model[k], 'model.' + k, true);
      text(value.model.acceleration, 'model.acceleration');
    }
    if (record(value.config, 'config', ['temperature', 'max_output_tokens', 'repeats', 'context_tokens'])) {
      number(value.config.temperature, 'config.temperature', 0, 2);
      number(value.config.max_output_tokens, 'config.max_output_tokens', 1, 128, false, true);
      number(value.config.repeats, 'config.repeats', 1, 3, false, true);
      number(value.config.context_tokens, 'config.context_tokens', 1, 10000000, true, true);
    }
    number(value.warmup_round_trip_s, 'warmup_round_trip_s', 0, 86400, true);
    if (record(value.predictions, 'predictions', ['tps', 'ram_gib'])) {
      number(value.predictions.tps, 'predictions.tps', 0, 1000000, true);
      number(value.predictions.ram_gib, 'predictions.ram_gib', 0, 1048576, true);
    }
    const countKeys = ['runs', 'valid_runs', 'partial_runs', 'failed_runs', 'ttft_ms_valid_count', 'decode_tps_valid_count', 'cpu_percent_normalized_valid_count', 'peak_rss_mib_valid_count'];
    const medianKeys = ['median_ttft_ms', 'median_tps', 'median_cpu_percent', 'peak_ram_mb'];
    const rangeKeys = ['ttft_ms_range', 'decode_tps_range', 'cpu_percent_normalized_range', 'peak_rss_mib_range'];
    const statKeys = [...countKeys, ...medianKeys, ...rangeKeys];
    function summaryStats(stats, p, top) {
      if (!record(stats, p, top ? [...statKeys, 'per_prompt', 'method'] : statKeys, top ? ['model', 'runtime', 'machine_label', 'warmup_round_trip_s', 'note', 'quality_flags'] : [])) return;
      for (const k of countKeys) number(stats[k], p + '.' + k, 0, 9, false, true);
      for (const k of medianKeys) number(stats[k], p + '.' + k, 0, Number.MAX_VALUE, true);
      for (const k of rangeKeys) {
        if (stats[k] === null) continue;
        if (!Array.isArray(stats[k]) || stats[k].length !== 2 || stats[k].some(n => !finite(n) || n < 0) || stats[k][0] > stats[k][1]) fail(p + '.' + k, 'must be an ordered finite non-negative pair or null');
      }
      if (!top) return;
      if (typeof stats.method !== 'string' || stats.method.length < 1 || stats.method.length > 600) fail(p + '.method', 'must be a short method description');
      for (const k of ['model', 'runtime']) if (own(stats, k)) text(stats[k], p + '.' + k);
      if (own(stats, 'machine_label') && (typeof stats.machine_label !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$/.test(stats.machine_label))) fail(p + '.machine_label', 'must be an anonymous device alias');
      if (own(stats, 'warmup_round_trip_s')) number(stats.warmup_round_trip_s, p + '.warmup_round_trip_s', 0, 86400, true);
      if (own(stats, 'note') && (typeof stats.note !== 'string' || stats.note.length > 300)) fail(p + '.note', 'must be a short note');
      if (own(stats, 'quality_flags') && (!Array.isArray(stats.quality_flags) || stats.quality_flags.length > 40 || stats.quality_flags.some(v => typeof v !== 'string' || !/^[a-z][a-z0-9_]{0,79}$/.test(v)) || new Set(stats.quality_flags).size !== stats.quality_flags.length)) fail(p + '.quality_flags', 'must be unique short machine-readable flags');
      if (record(stats.per_prompt, p + '.per_prompt', [], ['short', 'medium', 'long'])) for (const [prompt, values] of Object.entries(stats.per_prompt)) summaryStats(values, p + '.per_prompt.' + prompt, false);
    }
    summaryStats(value.summary, 'summary', true);
    if (!Array.isArray(value.runs) || value.runs.length < 1 || value.runs.length > 9) fail('runs', 'must contain 1–9 runs');
    else {
      const ids = new Set(), promptRepeats = new Set();
      value.runs.forEach((run, i) => {
        const p = 'runs[' + i + ']';
        if (!record(run, p, ['run_id', 'prompt_id', 'repeat_index', 'timestamp', 'status', 'measurements', 'sources', 'quality_flags', 'error'])) return;
        id(run.run_id, p + '.run_id');
        if (!['short', 'medium', 'long'].includes(run.prompt_id)) fail(p + '.prompt_id', 'must be short, medium, or long');
        date(run.timestamp, p + '.timestamp');
        if (ids.has(run.run_id)) fail(p + '.run_id', 'duplicate run ID'); ids.add(run.run_id);
        number(run.repeat_index, p + '.repeat_index', 1, 3, false, true);
        if (value.config && run.repeat_index > value.config.repeats) fail(p + '.repeat_index', 'exceeds the session repeat count');
        const pair = run.prompt_id + ':' + run.repeat_index;
        if (promptRepeats.has(pair)) fail(p, 'duplicate prompt/repeat pair'); promptRepeats.add(pair);
        if (!['ok', 'partial', 'error'].includes(run.status)) fail(p + '.status', 'must be ok, partial, or error');
        if (record(run.measurements, p + '.measurements', Object.keys(METRICS))) {
          for (const [k, m] of Object.entries(METRICS)) number(run.measurements[k], p + '.measurements.' + k, 0, m.max, true);
          if (run.status === 'ok' && Object.values(run.measurements).some(v => v === null)) fail(p + '.status', 'ok requires all four metrics; use partial when a metric is unavailable');
          if (run.status === 'partial' && Object.values(run.measurements).every(v => v === null)) fail(p + '.status', 'partial requires at least one available metric; use error for a completely failed run');
        }
        if (record(run.sources, p + '.sources', [...Object.keys(METRICS), 'output_tokens', 'decode_duration_s', 'sample_interval_s', 'process_count', 'process_attribution', 'cache_policy', 'prompt_hash'])) {
          for (const k of Object.keys(METRICS)) text(run.sources[k], p + '.sources.' + k, true);
          number(run.sources.output_tokens, p + '.sources.output_tokens', 0, 1000000, true, true);
          number(run.sources.decode_duration_s, p + '.sources.decode_duration_s', Number.MIN_VALUE, 86400, true);
          number(run.sources.sample_interval_s, p + '.sources.sample_interval_s', Number.MIN_VALUE, 60);
          number(run.sources.process_count, p + '.sources.process_count', 0, 100000, false, true);
          if (!['endpoint_owner_and_children', 'unavailable'].includes(run.sources.process_attribution)) fail(p + '.sources.process_attribution', 'must identify endpoint processes or be unavailable');
          text(run.sources.cache_policy, p + '.sources.cache_policy');
          if (typeof run.sources.prompt_hash !== 'string' || !/^[a-f0-9]{64}$/.test(run.sources.prompt_hash)) fail(p + '.sources.prompt_hash', 'must be a SHA-256 hex digest');
        }
        if (!Array.isArray(run.quality_flags) || run.quality_flags.length > 40 || run.quality_flags.some(v => typeof v !== 'string' || !/^[a-z][a-z0-9_]{0,79}$/.test(v)) || new Set(run.quality_flags).size !== run.quality_flags.length) fail(p + '.quality_flags', 'must be up to 40 unique machine-readable flags');
        if (run.status === 'partial' && Array.isArray(run.quality_flags) && !run.quality_flags.length) fail(p + '.quality_flags', 'a partial run must explain its limitations with a quality flag');
        if (object(run.measurements) && object(run.sources)) for (const metric of Object.keys(METRICS)) {
          if (run.measurements[metric] !== null && run.sources[metric] === null) fail(p + '.sources.' + metric, 'an available measurement must record its source');
        }
        if (run.error !== null && !str(run.error, 240)) fail(p + '.error', 'must be a short error string or null');
        if (run.status === 'ok' && run.error !== null) fail(p + '.error', 'an ok run cannot contain an error');
        if (run.status === 'error' && run.error === null) fail(p + '.error', 'an error run must explain the failure');
      });
    }
    const stack = [[value.summary, 0]];
    while (stack.length) {
      const [node, depth] = stack.pop();
      if (depth > 15) { fail('summary', 'nested data exceeds the safe depth limit'); break; }
      if (typeof node === 'number' && !finite(node)) { fail('summary', 'non-finite numbers are invalid'); break; }
      if (node && typeof node === 'object') for (const child of Object.values(node)) stack.push([child, depth + 1]);
    }
    if (value.data_kind === 'synthetic') warnings.push('Synthetic example: these values are invented for interface demonstration, not experimental evidence.');
    if (value.data_kind === 'measured') warnings.push('This file declares measured data. The portal checks structure and recomputes statistics, but cannot independently verify its origin or measurement accuracy.');
    return { errors, warnings, session: errors.length ? null : value };
  }
  function parseSession(text, byteLength) {
    const size = byteLength === undefined ? new TextEncoder().encode(text).byteLength : byteLength;
    if (size > MAX_FILE_BYTES) return { session: null, errors: ['File exceeds the 5 MiB limit.'], warnings: [] };
    try { return validateSession(JSON.parse(text)); } catch (_) { return { session: null, errors: ['Invalid JSON. Export a new session from the Lab Helper.'], warnings: [] }; }
  }
  function median(values) {
    const sorted = values.filter(finite).slice().sort((a, b) => a - b);
    const n = sorted.length; return n ? (n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2) : null;
  }
  function filterRuns(sessions, filters = {}) {
    return sessions.flatMap(session => session.runs.filter(run =>
      (!filters.device || session.device.alias === filters.device) &&
      (!filters.model || session.model.name === filters.model) &&
      (!filters.prompt || run.prompt_id === filters.prompt) &&
      (!filters.kind || session.data_kind === filters.kind)
    ).map(run => ({ session, run })));
  }
  function aggregate(rows) {
    const result = { total: rows.length, ok: rows.filter(r => r.run.status === 'ok').length, partial: rows.filter(r => r.run.status === 'partial').length, failed: rows.filter(r => r.run.status === 'error').length, metrics: {} };
    for (const metric of Object.keys(METRICS)) {
      const values = rows.filter(r => r.run.status !== 'error').map(r => r.run.measurements[metric]).filter(finite);
      result.metrics[metric] = { median: median(values), min: values.length ? Math.min(...values) : null, max: values.length ? Math.max(...values) : null, count: values.length, missing: rows.length - values.length };
    }
    return result;
  }
  function addSession(sessions, candidate) {
    const checked = validateSession(candidate);
    if (checked.errors.length) return checked;
    if (sessions.length >= MAX_SESSIONS) return { session: null, errors: ['The portal holds up to 30 sessions. Clear results before importing more.'], warnings: [] };
    if (sessions.some(s => s.session_id === candidate.session_id)) return { session: null, errors: ['Duplicate session ID. This session is already loaded.'], warnings: [] };
    const ids = new Set(sessions.flatMap(s => s.runs.map(r => r.run_id)));
    if (candidate.runs.some(r => ids.has(r.run_id))) return { session: null, errors: ['A run ID duplicates a run in another loaded session.'], warnings: [] };
    return checked;
  }
  const api = { MAX_FILE_BYTES, MAX_SESSIONS, METRICS, validateSession, parseSession, median, filterRuns, aggregate, addSession };
  root.LocalLabData = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);

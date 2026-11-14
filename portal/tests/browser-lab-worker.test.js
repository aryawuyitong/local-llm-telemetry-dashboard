const test = require('node:test');
const assert = require('node:assert/strict');

const worker = import('../browser-lab-worker.mjs');

function fixture() {
  let clock = 0;
  let id = 0;
  const calls = [];
  const env = { backends: { onnx: { wasm: {} } } };

  class TextStreamer {
    constructor(_tokenizer, callbacks) {
      this.callbacks = callbacks;
    }
  }

  async function pipeline(task, repository, options) {
    calls.push([task, repository, options.device, options.dtype, options.revision]);
    clock += 15;
    options.progress_callback({ file: 'onnx/model.onnx', status: 'progress', loaded: 500, total: 1000 });
    const pipe = async ([message], options) => {
      calls.push(['run', message.content, options.max_new_tokens]);
      const sink = options.streamer.callbacks;
      clock += 10;
      sink.token_callback_function([1n]);
      sink.callback_function(' ');
      clock += 10;
      sink.token_callback_function([2n]);
      sink.callback_function('The CPU ');
      clock += 10;
      sink.token_callback_function([3n]);
      sink.callback_function('executes instructions.');
      clock += 1;
    };
    pipe.dispose = async () => calls.push(['dispose', repository]);
    return pipe;
  }

  return {
    calls,
    options: {
      loadRuntime: async () => ({ pipeline, env, TextStreamer }),
      requestAdapter: async () => null,
      now: () => clock,
      makeId: () => `test-${++id}`,
    },
  };
}

test('runs two models on one device in order and measures the actual output tokens', async () => {
  const { createBrowserLabRunner } = await worker;
  const { calls, options } = fixture();
  const run = createBrowserLabRunner(options);
  const events = [];
  assert.deepEqual(calls, []);
  await run({ type: 'run', models: ['smol-135', 'smol-360'], device: 'auto', mode: 'quick' }, event => events.push(event));

  const results = events.filter(event => event.type === 'result').map(event => event.result);
  assert.deepEqual(results.map(result => [result.model, result.device, result.dtype]), [
    ['smol-135', 'wasm', 'q8'], ['smol-360', 'wasm', 'q8'],
  ]);
  assert.deepEqual(calls.map(call => call[0]), [
    'text-generation', 'run', 'run', 'dispose', 'text-generation', 'run', 'run', 'dispose',
  ]);
  assert.deepEqual(calls.filter(call => call[0] === 'run').map(call => call[2]), [8, 32, 8, 32]);
  assert.equal(calls[2][1], calls[6][1]);
  assert.deepEqual(results.map(result => result.prepMs), [15, 15]);
  for (const { runs: [record] } of results) {
    assert.equal(record.ttftMs, 20);
    assert.equal(record.tps, 100);
    assert.equal(record.outputTokens, 3);
    assert.equal(record.cpuPercent, null);
    assert.equal(record.gpuPercent, null);
    assert.equal(record.ramMiB, null);
  }
  assert(events.some(event => event.phase === 'download' && event.loaded === 500 && event.total === 1000));
  assert.equal(events.at(-1).type, 'done');
});

test('standard WebGPU measurements keep the fixed workload and exclude warmup', async () => {
  const { createBrowserLabRunner } = await worker;
  const { calls, options } = fixture();
  const run = createBrowserLabRunner({
    ...options, requestAdapter: async () => ({ features: new Set(['shader-f16']) }),
  });
  const events = [];
  await run({ type: 'run', models: ['smol-135'], device: 'webgpu', mode: 'standard' }, event => events.push(event));
  const data = events.find(event => event.type === 'result').result;
  assert.equal(data.device, 'webgpu');
  assert.equal(data.dtype, 'q4f16');
  assert.deepEqual(data.runs.map(record => [record.promptId, record.repeat]), [
    ['short', 1], ['short', 2], ['short', 3],
    ['medium', 1], ['medium', 2], ['medium', 3],
    ['long', 1], ['long', 2], ['long', 3],
  ]);
  assert.deepEqual(calls.filter(call => call[0] === 'run').map(call => call[2]), [8, ...Array(9).fill(64)]);
});

test('does not load a runtime for unavailable requested WebGPU or invalid selections', async () => {
  const { createBrowserLabRunner } = await worker;
  const run = createBrowserLabRunner({
    requestAdapter: async () => null,
    loadRuntime() { assert.fail('the runtime should not be loaded'); },
  });
  for (const models of [['smol-135'], ['smol-135', 'smol-135']]) {
    const events = [];
    await run({ type: 'run', models, device: 'webgpu', mode: 'quick' }, event => events.push(event));
    assert.equal(events[0].type, 'error');
    assert.equal(events[1].type, 'done');
  }
});

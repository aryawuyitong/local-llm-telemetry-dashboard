const RUNTIME_VERSION = '3.8.1';
const TRANSFORMERS_MODULE = `https://cdn.jsdelivr.net/npm/@huggingface/transformers@${RUNTIME_VERSION}/dist/transformers.web.js`;

const MODELS = {
  'smol-135': {
    name: 'SmolLM2 135M Instruct',
    repository: 'HuggingFaceTB/SmolLM2-135M-Instruct',
    revision: 'a91318be21aeaf0879874faa161dcb40c68847e9',
  },
  'smol-360': {
    name: 'SmolLM2 360M Instruct',
    repository: 'HuggingFaceTB/SmolLM2-360M-Instruct',
    revision: '6849e9f43f1a64e4604f0ef9d23adc8af4b4508f',
  },
};

const PROMPTS = {
  short: 'In one sentence, what does a CPU do?',
  medium: 'In about 80 words, explain why a quantized model uses less memory than the original.',
  long: 'Summarize this note in three bullet points. A local language model runs on your laptop. '
    + 'The runtime loads the model weights, splits the prompt into tokens, and generates one token '
    + 'at a time. The runtime first processes the whole prompt. Then it generates tokens at a rate '
    + 'that depends on the model size, quantization and whether the GPU can help. Bigger models '
    + 'usually need more memory. Once prepared, a local model can work offline. Your hardware '
    + 'and the other software running on it affect both speed and available memory.',
};

const MODES = {
  quick: { prompts: ['short'], repeats: 1, maxTokens: 32 },
  standard: { prompts: Object.keys(PROMPTS), repeats: 3, maxTokens: 64 },
};

const CPU = { device: 'wasm', dtype: 'q8' };
const UNKNOWN = { cpuPercent: null, gpuPercent: null, ramMiB: null };

function progress(emit, model, phase, message, loaded = null, total = null) {
  emit({ type: 'progress', model, phase, message, loaded, total });
}

function error(emit, model, phase, cause) {
  const message = cause instanceof Error ? cause.message : String(cause);
  emit({ type: 'error', model, phase, message });
}

function validate(request) {
  if (!Array.isArray(request.models) || request.models.length < 1 || request.models.length > 2
      || new Set(request.models).size !== request.models.length
      || request.models.some(model => typeof model !== 'string' || !Object.hasOwn(MODELS, model))) {
    throw new Error('Choose one or two different models to test.');
  }
  if (!['auto', 'webgpu', 'wasm'].includes(request.device) || !['quick', 'standard'].includes(request.mode)) {
    throw new Error('Choose a supported device and benchmark length.');
  }
}

async function chooseBackend(device, requestAdapter) {
  if (device === 'wasm') return CPU;
  let adapter = null;
  try {
    adapter = await requestAdapter();
  } catch {
    // Some browsers expose WebGPU but cannot provide an adapter to a worker.
  }
  if (!adapter || adapter.info?.isFallbackAdapter) {
    if (device === 'webgpu') {
      throw new Error('This browser could not find a WebGPU device. Choose CPU to continue.');
    }
    return CPU;
  }
  if (adapter.features.has('shader-f16')) return { device: 'webgpu', dtype: 'q4f16' };
  // The q8 CPU weights are smaller than q4 WebGPU weights for both models.
  return device === 'webgpu' ? { device: 'webgpu', dtype: 'q4' } : CPU;
}

async function measure(pipe, TextStreamer, prompt, maxTokens, now) {
  let firstTextAt = null;
  let firstTokenAt = null;
  let lastTokenAt = null;
  let outputTokens = 0;
  let text = '';
  const streamer = new TextStreamer(pipe.tokenizer, {
    skip_prompt: true,
    skip_special_tokens: true,
    callback_function(chunk) {
      if (firstTextAt === null && chunk.trim()) firstTextAt = now();
      text += chunk;
    },
    token_callback_function(tokens) {
      if (!tokens.length) return;
      const tokenTime = now();
      firstTokenAt ??= tokenTime;
      lastTokenAt = tokenTime;
      outputTokens += tokens.length;
    },
  });
  const started = now();
  await pipe([{ role: 'user', content: prompt }], {
    do_sample: false,
    max_new_tokens: maxTokens,
    streamer,
  });
  const elapsed = now() - started;
  return {
    output: text.trim(), outputTokens, wallMs: elapsed,
    ttftMs: firstTextAt === null ? null : firstTextAt - started,
    tps: outputTokens > 1 && lastTokenAt > firstTokenAt
      ? (outputTokens - 1) * 1000 / (lastTokenAt - firstTokenAt) : null,
    ...UNKNOWN,
  };
}

export function createBrowserLabRunner({
  loadRuntime = () => import(TRANSFORMERS_MODULE),
  requestAdapter = () => globalThis.navigator?.gpu?.requestAdapter(),
  now = () => performance.now(),
  makeId = () => crypto.randomUUID(),
} = {}) {
  let busy = false;

  return async function run(request, emit) {
    if (request?.type !== 'run') return;
    if (busy) return;
    busy = true;
    try {
      validate(request);
      const backend = await chooseBackend(request.device, requestAdapter);
      const first = request.models[0];
      progress(emit, first, 'preparing', 'Starting the browser model runner.');
      const runtimeStarted = now();
      const { pipeline, TextStreamer, env } = await loadRuntime();
      const runtimeMs = now() - runtimeStarted;
      env.allowLocalModels = false;
      // Transformers.js reuses CacheStorage when the browser makes it available.
      env.useBrowserCache = typeof caches !== 'undefined';
      // GitHub Pages has no cross-origin isolation, so keep the WASM runner single threaded.
      if (!globalThis.crossOriginIsolated && env.backends.onnx.wasm) {
        env.backends.onnx.wasm.numThreads = 1;
      }

      const spec = MODES[request.mode];
      for (const [index, model] of request.models.entries()) {
        const { name, repository, revision } = MODELS[model];
        const prepStarted = now();
        let pipe;
        let phase = 'preparing';
        let lastProgress = -Infinity;
        try {
          progress(emit, model, 'preparing', `Preparing ${name} on ${backend.device === 'webgpu' ? 'WebGPU' : 'CPU'}.`);
          pipe = await pipeline('text-generation', repository, {
            revision, device: backend.device, dtype: backend.dtype,
            progress_callback(info) {
              if (!info.file?.endsWith('.onnx') || info.status !== 'progress') return;
              // The library reports reads from the network or cache using the same events.
              const loaded = Number.isFinite(info.loaded) ? info.loaded : null;
              const total = Number.isFinite(info.total) && info.total > 0 ? info.total : null;
              const received = now();
              if (received - lastProgress < 100 && (total === null || loaded !== total)) return;
              lastProgress = received;
              progress(emit, model, 'download', 'Reading model weights from the network or browser cache.', loaded, total);
            },
          });
          const prepMs = now() - prepStarted;
          phase = 'benchmark';
          progress(emit, model, phase, 'Warming up. This reply will be excluded from the benchmark.');
          await measure(pipe, TextStreamer, PROMPTS.short, 8, now);
          const runs = [];
          const count = spec.prompts.length * spec.repeats;
          for (const promptId of spec.prompts) {
            for (let repeat = 1; repeat <= spec.repeats; repeat++) {
              progress(emit, model, phase, `Running test ${runs.length + 1} of ${count}.`);
              const prompt = PROMPTS[promptId];
              const record = await measure(pipe, TextStreamer, prompt, spec.maxTokens, now);
              if (!record.output) throw new Error('The model returned no visible text for this test.');
              runs.push({ prompt, promptId, repeat, ...record });
            }
          }
          emit({ type: 'result', result: {
            id: makeId(), model, name, repository, revision, device: backend.device, dtype: backend.dtype,
            runtime: 'transformers.js', runtimeVersion: RUNTIME_VERSION, protocol: 'browser-llm-lab/1',
            mode: request.mode, prepMs, runtimeMs: index === 0 ? runtimeMs : 0, runs,
            ...UNKNOWN,
            throughputMethod: 'Generated token intervals after the first token (includes streamer overhead).',
            firstTextMethod: 'Time from request to first nonblank text emitted by the tokenizer streamer.',
          } });
        } catch (cause) {
          if (backend.device === 'webgpu') {
            const detail = cause instanceof Error ? cause.message : String(cause);
            error(emit, model, phase, new Error(`${detail} Start a new run with CPU if WebGPU fails on this device.`));
          } else {
            error(emit, model, phase, cause);
          }
          // ONNX runtime initialization or inference failure can poison this worker's session.
          break;
        } finally {
          if (pipe) await pipe.dispose();
        }
      }
    } catch (cause) {
      error(emit, null, 'preparing', cause);
    } finally {
      busy = false;
      emit({ type: 'done' });
    }
  };
}

if (typeof WorkerGlobalScope !== 'undefined' && globalThis instanceof WorkerGlobalScope) {
  const run = createBrowserLabRunner();
  globalThis.onmessage = event => run(event.data, message => globalThis.postMessage(message));
}

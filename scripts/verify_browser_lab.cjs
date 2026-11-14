// Run against the real static portal and pinned browser models.
// npm install --no-save --package-lock=false playwright@1.61.0
// npx playwright install chromium
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '../portal');
const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
  '.mjs': 'text/javascript', '.json': 'application/json', '.woff2': 'font/woff2' };

async function verify() {
  const server = http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url, 'http://localhost');
      const file = path.resolve(root, '.' + (url.pathname === '/' ? '/index.html' : url.pathname));
      if (!file.startsWith(root + path.sep)) throw new Error('Outside portal');
      const content = await fs.readFile(file);
      response.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
      response.end(content);
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch();
    const page = await browser.newPage();
    page.on('pageerror', error => console.error('Browser error:', error.message));
    const downloaded = [];
    page.on('request', request => {
      const url = new URL(request.url());
      if (url.hostname === 'huggingface.co' && url.pathname.includes('/onnx/')) downloaded.push(url.pathname);
    });

    await page.goto(`http://127.0.0.1:${server.address().port}/#browser`);
    await page.getByRole('heading', { name: 'Run a model in your browser.' }).waitFor();
    assert.deepEqual(downloaded, [], 'Opening the website must not request model weights.');
    await page.locator('#browser-device').selectOption('wasm');
    await page.getByRole('checkbox', { name: /360M/ }).check();
    await page.getByRole('button', { name: 'Run benchmark' }).click();
    await page.waitForFunction(() => {
      const status = document.getElementById('browser-status').textContent;
      return /^(Benchmark finished|Benchmark stopped|No models completed)/.test(status);
    }, null, { timeout: 9 * 60 * 1000 });
    const status = await page.locator('#browser-status').innerText();
    const errors = await page.locator('#browser-errors').innerText();
    assert.equal(status, 'Benchmark finished. 2 model(s) measured.', errors);
    assert.equal(await page.locator('.browser-readout').count(), 2);
    assert(downloaded.some(p => p.includes('SmolLM2-135M-Instruct')), 'The 135M model weights were requested.');
    assert(downloaded.some(p => p.includes('SmolLM2-360M-Instruct')), 'The 360M model weights were requested.');
    const exported = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Save browser results' }).click();
    const result = JSON.parse(await fs.readFile(await (await exported).path(), 'utf8'));
    assert.equal(result.results.length, 2);
    for (const session of result.results) {
      assert.equal(session.device, 'wasm');
      assert.equal(session.runs.length, 1);
      const sample = session.runs[0];
      assert(sample.output.trim().length > 0 && sample.outputTokens > 0);
      assert(sample.ttftMs >= 0);
      assert.equal(sample.gpuPercent, null);
      console.log(`${session.name}: prepared in ${Math.round(session.prepMs)} ms, emitted ${sample.outputTokens} tokens`);
    }
  } finally {
    if (browser) await browser.close();
    server.close();
  }
}

verify().catch(error => {
  console.error(error);
  process.exitCode = 1;
});

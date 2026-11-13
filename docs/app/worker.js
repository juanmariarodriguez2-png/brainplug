// Runs the whole analysis off the main thread, so the page stays responsive.
// Nothing here touches the network: files are read from disk, analysed in memory
// and the result is posted back to the page.
import { build } from './engine/index.js';

let nextId = 1;
const waiting = new Map();

// PDFs are read by pdf.js on the page; the worker asks for the text and waits.
const pdfText = (bytes, name) => new Promise((resolve, reject) => {
  const id = nextId++, copy = bytes.slice();
  waiting.set(id, { resolve, reject });
  postMessage({ type: 'pdf', id, name, bytes: copy }, [copy.buffer]);
});

onmessage = async (event) => {
  const msg = event.data;
  if (msg.type === 'pdf-result') {
    const job = waiting.get(msg.id);
    waiting.delete(msg.id);
    if (job) (msg.error ? job.reject(new Error(msg.error)) : job.resolve(msg.result));
    return;
  }
  if (msg.type === 'ping') { postMessage({ type: 'pong' }); return; }  // the page checks that everything has loaded
  if (msg.type !== 'build') return;
  try {
    let last = 0;
    const progress = (stage, detail = '') => {
      const now = Date.now();
      if (stage !== 'file' || now - last > 60) { last = now; postMessage({ type: 'progress', stage, detail }); }
    };
    const { payload, notes } = await build(msg.inputs, { ...msg.options, pdfText, progress });
    postMessage({ type: 'done', payload, notes });
  } catch (err) {
    postMessage({ type: 'error', message: String((err && err.message) || err) });
  }
};

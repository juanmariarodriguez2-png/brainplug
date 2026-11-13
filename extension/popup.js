const APP = 'https://brainplug.app/app/';
const NAMES = { chatgpt: 'ChatGPT', claude: 'Claude', gemini: 'Gemini', copilot: 'Copilot', perplexity: 'Perplexity' };
const es = (navigator.language || 'en').toLowerCase().startsWith('es');
const T = es ? {
  say: n => (n === 1 ? '1 mensaje guardado' : `${n.toLocaleString('es')} mensajes guardados`),
  sub: 'Lo que tú escribes a la IA, guardado solo en este navegador.', none: 'Escribe en ChatGPT, Claude o Gemini y aparecerá aquí.',
  on: 'Guardar lo que escribo', open: 'Crear mi Brainplug', save: 'Guardar archivo', clear: 'Borrar todo lo guardado',
  sure: 'Pulsa otra vez para borrarlo todo', foot: 'No se envía nada a ningún sitio. Las respuestas de la IA no se guardan.',
} : {
  say: n => (n === 1 ? '1 message saved' : `${n.toLocaleString('en')} messages saved`),
  sub: 'What you type to an AI, kept in this browser only.', none: 'Type in ChatGPT, Claude or Gemini and it will show up here.',
  on: 'Save what I type', open: 'Make my Brainplug', save: 'Save as a file', clear: 'Delete everything saved',
  sure: 'Press again to delete it all', foot: 'Nothing is sent anywhere. The AI’s answers are not saved.',
};
const $ = id => document.getElementById(id);
document.documentElement.lang = es ? 'es' : 'en';
$('onLabel').textContent = T.on; $('open').textContent = T.open; $('save').textContent = T.save;
$('clear').textContent = T.clear; $('foot').textContent = T.foot;

async function items() {
  const got = await chrome.storage.local.get(null);
  return Object.keys(got).filter(k => k.startsWith('m:')).sort().flatMap(k => got[k]);
}
async function draw() {
  const all = await items();
  const paused = !!(await chrome.storage.local.get('paused')).paused;
  $('say').textContent = T.say(all.length);
  $('sub').textContent = all.length ? T.sub : T.none;
  const counts = {};
  for (const row of all) counts[row.site] = (counts[row.site] || 0) + 1;
  $('sites').replaceChildren(...Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([site, n]) => {
    const li = document.createElement('li'), name = document.createElement('span'), count = document.createElement('span');
    name.textContent = NAMES[site] || site; count.textContent = n.toLocaleString(es ? 'es' : 'en');
    li.append(name, count);
    return li;
  }));
  $('on').checked = !paused;
  $('save').disabled = $('clear').disabled = !all.length;
  $('clear').hidden = !all.length;
}
$('on').onchange = () => chrome.storage.local.set({ paused: !$('on').checked });
$('open').onclick = () => chrome.tabs.create({ url: APP + (es ? '?lang=es' : '') });
$('save').onclick = async () => {
  const data = { format: 'brainplug-capture', version: 1, exported: new Date().toISOString(), items: await items() };
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([JSON.stringify(data)], { type: 'application/json' }));
  link.download = 'brainplug-capture.json';
  link.click();
};
$('clear').onclick = async () => {
  if (!$('clear').classList.contains('sure')) { $('clear').classList.add('sure'); $('clear').textContent = T.sure; return; }
  const got = await chrome.storage.local.get(null);
  await chrome.storage.local.remove(Object.keys(got).filter(k => k.startsWith('m:')));
  $('clear').classList.remove('sure'); $('clear').textContent = T.clear;
  draw();
};
chrome.storage.onChanged.addListener(draw);
draw();

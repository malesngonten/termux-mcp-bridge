// Smoke test panel UI di jsdom: navigasi onboarding, render status, start/stop, uji koneksi.
// Pakai: npm i jsdom (di folder mana saja), lalu: JSDOM_PATH=/path/ke/node_modules/jsdom node tools/ui_smoke.js
const fs = require('fs');
const { JSDOM, VirtualConsole } = require(process.env.JSDOM_PATH || 'jsdom');

const html = fs.readFileSync(require('path').join(__dirname, '..', 'src', 'termux_mcp', 'ui.html'), 'utf8').replace(/__NONCE__/g, 'n0nce');

const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', (e) => errors.push('jsdomError: ' + e.message));
vc.on('error', (e) => errors.push('console.error: ' + e));

let status = {
  running: false, starting: false, provider: null, url: null, port: 8000, port_busy: false, token_stale: false, log: '',
  ngrok: { installed: true, authtoken: true, domain: 'demo.ngrok-free.dev' },
  cloudflare: { installed: true },
  install: { cloudflare: 'pkg install cloudflared', ngrok: 'https://ngrok.com/download' },
};
const calls = [];
let testResult = {
  ok: true, message: 'Koneksi aman, membalas dalam 120 ms.',
  local: { ok: true, ms: 8, status: 200, detail: '' }, public: { ok: true, ms: 120, status: 200, detail: '' },
};

function fakeFetch(path, opt) {
  opt = opt || {};
  calls.push((opt.method || 'GET') + ' ' + path + (opt.body ? ' ' + opt.body : ''));
  let code = 200, data = {};
  if (path === '/api/status') data = status;
  else if (path === '/api/token') data = { token: 'tok_secret_123' };
  else if (path === '/api/start') { status = Object.assign({}, status, { running: true, starting: false, provider: JSON.parse(opt.body).tunnel, url: 'https://demo.example.dev/mcp' }); data = status; }
  else if (path === '/api/stop') { status = Object.assign({}, status, { running: false, provider: null, url: null }); data = status; }
  else if (path === '/api/token/new') { status = Object.assign({}, status, { token_stale: status.running }); data = status; }
  else if (path === '/api/ngrok') data = status;
  else if (path === '/api/test') data = testResult;
  else { code = 404; data = { error: 'x' }; }
  return Promise.resolve({ status: code, ok: code < 400, json: () => Promise.resolve(data) });
}

const dom = new JSDOM(html, {
  url: 'http://127.0.0.1:8787/', runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc,
  beforeParse(w) { w.fetch = fakeFetch; w.scrollTo = () => {}; },
});
const w = dom.window, d = w.document;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const $ = (s) => d.querySelector(s);
const screens = () => Array.from(d.querySelectorAll('.screen'));
const visible = () => screens().map((s, i) => (s.hidden ? null : i)).filter((i) => i !== null);
let failed = 0;
function check(name, cond, extra) { if (!cond) { failed++; console.log('GAGAL: ' + name + (extra ? ' -> ' + extra : '')); } else console.log('ok: ' + name); }

(async () => {
  await sleep(150);
  check('6 layar & 6 titik', screens().length === 6 && d.querySelectorAll('.dot-nav').length === 6);
  check('layar awal = 0', JSON.stringify(visible()) === '[0]', JSON.stringify(visible()));
  check('hero globe & orb dirender', d.querySelectorAll('.hero svg').length === 5, String(d.querySelectorAll('.hero svg').length));
  check('tombol back tersembunyi di langkah 1', $('#back').classList.contains('invisible'));

  $('.screen [data-next]').click(); await sleep(30);
  check('Mulai -> layar 1', JSON.stringify(visible()) === '[1]');
  check('tombol back muncul', !$('#back').classList.contains('invisible'));

  $('#tok-show').click(); await sleep(60);
  check('token tampil setelah Tampilkan', $('#token-v').textContent === 'tok_secret_123', $('#token-v').textContent);
  $('#tok-show').click(); await sleep(30);
  check('token disembunyikan lagi', $('#token-v').textContent.startsWith('•'));

  d.querySelectorAll('.dot-nav')[2].click(); await sleep(30);
  check('titik 3 -> layar tunnel', JSON.stringify(visible()) === '[2]');
  check('default cloudflare/ngrok terpilih', !!$('#seg button.on'));
  $('#seg button[data-p="ngrok"]').click(); await sleep(20);
  check('panel ngrok tampil', !$('#pn-ngrok').hidden && $('#pn-cloudflare').hidden);
  check('status ngrok terbaca', $('#ng-state').textContent.includes('demo.ngrok-free.dev'), $('#ng-state').textContent);
  $('#seg button[data-p="cloudflare"]').click(); await sleep(20);

  d.querySelectorAll('.dot-nav')[3].click(); await sleep(30);
  check('layar server', JSON.stringify(visible()) === '[3]');
  check('judul awal', $('#p-title').textContent === 'Nyalakan Server', $('#p-title').textContent);
  check('CTA lanjut nonaktif saat mati', $('#cta-power').disabled === true);
  $('#power').click(); await sleep(120);
  check('start dipanggil dengan tunnel terpilih', calls.some((c) => c.startsWith('POST /api/start') && c.includes('"cloudflare"')), calls.join(' | '));
  check('judul Server Aktif', $('#p-title').textContent === 'Server Aktif', $('#p-title').textContent);
  check('URL tampil', !$('#p-url').hidden && $('#p-url-v').textContent === 'https://demo.example.dev/mcp');
  check('power berstatus on', $('#power').classList.contains('on'));
  check('CTA lanjut aktif', $('#cta-power').disabled === false);
  check('URL di panduan terisi', $('#f-url').textContent === 'https://demo.example.dev/mcp');

  d.querySelectorAll('.dot-nav')[5].click(); await sleep(30);
  check('layar uji', JSON.stringify(visible()) === '[5]');
  check('judul uji idle', $('#t-title').textContent === 'Uji Koneksi');
  $('#tester').click(); await sleep(120);
  check('judul Koneksi Aman', $('#t-title').textContent === 'Koneksi Aman', $('#t-title').textContent);
  check('dua baris hasil', d.querySelectorAll('#checks li').length === 2 && !$('#checks').hidden);
  check('tester berstatus ok', $('#tester').classList.contains('ok'));

  testResult = { ok: false, message: 'Server lokal normal, tapi jalur publik gagal: token ditolak.',
    local: { ok: true, ms: 8, status: 200, detail: '' }, public: { ok: false, ms: null, status: 401, detail: 'token ditolak.' } };
  $('#tester').click(); await sleep(120);
  check('judul Ada Masalah', $('#t-title').textContent === 'Ada Masalah', $('#t-title').textContent);
  check('pesan error tampil', $('#t-lead').textContent.includes('jalur publik gagal'));
  check('baris gagal bertanda bad', !!$('#checks li.bad'));

  d.querySelectorAll('.dot-nav')[3].click(); await sleep(30);
  $('#power').click(); await sleep(120);
  check('stop dipanggil', calls.some((c) => c.startsWith('POST /api/stop')));
  check('judul kembali Nyalakan Server', $('#p-title').textContent === 'Nyalakan Server', $('#p-title').textContent);

  d.querySelectorAll('.dot-nav')[5].click(); await sleep(30);
  $('#tester').click(); await sleep(60);
  check('uji saat mati mengarahkan ke langkah server', JSON.stringify(visible()) === '[3]', JSON.stringify(visible()));

  check('onboarded tersimpan', w.localStorage.getItem('onboarded') === '1');
  check('tanpa error JS', errors.length === 0, errors.join(' | '));
  console.log(failed ? `\n${failed} GAGAL` : '\nSEMUA LOLOS');
  process.exit(failed ? 1 : 0);
})();

// Smoke test panel UI di jsdom: navigasi onboarding 5 langkah, prefill ngrok, token di layar Pasang, start/stop, uji koneksi.
// Pakai: npm i jsdom (di folder mana saja), lalu: JSDOM_PATH=/path/ke/node_modules/jsdom node tools/ui_smoke.js
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require(process.env.JSDOM_PATH || 'jsdom');

const html = fs.readFileSync(path.join(__dirname, '..', 'src', 'termux_mcp', 'ui.html'), 'utf8').replace(/__NONCE__/g, 'n0nce');

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
let ngrokSaved = { authtoken: 'ngtok_saved_123', domain: 'demo.ngrok-free.dev' };
const calls = [];
let testResult = {
  ok: true, message: 'Koneksi aman, membalas dalam 120 ms.',
  local: { ok: true, ms: 8, status: 200, detail: '' }, public: { ok: true, ms: 120, status: 200, detail: '' },
};

function fakeFetch(url, opt) {
  opt = opt || {};
  const method = opt.method || 'GET';
  calls.push(method + ' ' + url + (opt.body ? ' ' + opt.body : ''));
  let code = 200, data = {};
  if (url === '/api/status') data = status;
  else if (url === '/api/token') data = { token: 'tok_secret_123' };
  else if (url === '/api/ngrok' && method === 'GET') data = ngrokSaved;
  else if (url === '/api/ngrok') { const b = JSON.parse(opt.body); ngrokSaved = { authtoken: b.authtoken || ngrokSaved.authtoken, domain: b.domain || ngrokSaved.domain }; data = status; }
  else if (url === '/api/start') { status = Object.assign({}, status, { running: true, provider: JSON.parse(opt.body).tunnel, url: 'https://demo.example.dev/mcp' }); data = status; }
  else if (url === '/api/stop') { status = Object.assign({}, status, { running: false, provider: null, url: null }); data = status; }
  else if (url === '/api/token/new') { status = Object.assign({}, status, { token_stale: status.running }); data = status; }
  else if (url === '/api/test') data = testResult;
  else { code = 404; data = { error: 'x' }; }
  return Promise.resolve({ status: code, ok: code < 400, json: () => Promise.resolve(data) });
}

const dom = new JSDOM(html, {
  url: 'http://127.0.0.1:8787/', runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc,
  beforeParse(w) { w.fetch = fakeFetch; w.scrollTo = () => {}; w.confirm = () => true; },
});
const w = dom.window, d = w.document;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const $ = (s) => d.querySelector(s);
const screens = () => Array.from(d.querySelectorAll('.screen'));
const visible = () => screens().map((s, i) => (s.hidden ? null : i)).filter((i) => i !== null);
const dot = (i) => d.querySelectorAll('.dot-nav')[i].click();
let failed = 0;
function check(name, cond, extra) { if (!cond) { failed++; console.log('GAGAL: ' + name + (extra ? ' -> ' + extra : '')); } else console.log('ok: ' + name); }

(async () => {
  await sleep(150);
  check('5 layar & 5 titik', screens().length === 5 && d.querySelectorAll('.dot-nav').length === 5);
  check('layar awal = 0', JSON.stringify(visible()) === '[0]', JSON.stringify(visible()));
  check('4 ilustrasi dirender', d.querySelectorAll('.hero svg').length === 4, String(d.querySelectorAll('.hero svg').length));
  check('tidak ada layar Token', !/Amankan Akses/.test(d.body.textContent));
  check('tombol back & Lanjut tersembunyi di awal', $('#back').classList.contains('invisible') && $('#next').classList.contains('invisible'));
  check('brand terlihat di layar awal', !$('#brand').classList.contains('dim'));

  $('.screen [data-next]').click(); await sleep(80);
  check('Mulai -> layar tunnel', JSON.stringify(visible()) === '[1]');
  check('judul Pilih Jalur', screens()[1].querySelector('h1').textContent === 'Pilih Jalur');
  check('brand disamarkan di layar tengah', $('#brand').classList.contains('dim'));
  check('Lanjut muncul', !$('#next').classList.contains('invisible'));
  check('ngrok tersimpan terpilih otomatis', $('#seg button.on').getAttribute('data-p') === 'ngrok');
  check('authtoken tersimpan terisi di input', $('#ng-token').value === 'ngtok_saved_123', $('#ng-token').value);
  check('domain tersimpan terisi di input', $('#ng-domain').value === 'demo.ngrok-free.dev', $('#ng-domain').value);
  check('input authtoken tersembunyi (password)', $('#ng-token').type === 'password');
  $('[data-eye="ng-token"]').click(); await sleep(20);
  check('ikon mata membuka authtoken', $('#ng-token').type === 'text');
  $('[data-eye="ng-token"]').click(); await sleep(20);
  check('ikon mata menyembunyikan lagi', $('#ng-token').type === 'password');
  check('tombol Simpan tampil untuk ngrok', !$('#ng-actions').hidden);

  $('#ng-save').click(); await sleep(60);
  check('notifikasi muncul (Tidak ada perubahan)', $('#toast').classList.contains('show') && $('#toast').textContent === 'Tidak ada perubahan', $('#toast').textContent);
  check('tidak ada POST /api/ngrok tanpa perubahan', !calls.some((c) => c.startsWith('POST /api/ngrok')));
  $('#ng-domain').value = 'baru.ngrok-free.dev'; $('#ng-domain').oninput(); 
  $('#ng-save').click(); await sleep(120);
  const saveCall = calls.find((c) => c.startsWith('POST /api/ngrok')) || '';
  check('simpan hanya mengirim yang berubah', saveCall.includes('"domain":"baru.ngrok-free.dev"') && saveCall.includes('"authtoken":""'), saveCall);
  check('input domain memuat nilai tersimpan baru', $('#ng-domain').value === 'baru.ngrok-free.dev');

  $('#seg button[data-p="cloudflare"]').click(); await sleep(20);
  check('panel cloudflare tampil & tombol Simpan hilang', !$('#pn-cloudflare').hidden && $('#ng-actions').hidden);

  $('#next').click(); await sleep(40);
  check('Lanjut -> layar server', JSON.stringify(visible()) === '[2]');
  check('judul awal', $('#p-title').textContent === 'Nyalakan Server', $('#p-title').textContent);
  check('Lanjut nonaktif saat server mati', $('#next').disabled === true);
  $('#power').click(); await sleep(150);
  check('start dipanggil dengan tunnel terpilih', calls.some((c) => c.startsWith('POST /api/start') && c.includes('"cloudflare"')), calls.join(' | '));
  check('judul Server Aktif', $('#p-title').textContent === 'Server Aktif', $('#p-title').textContent);
  check('URL tampil di input', !$('#p-url').hidden && $('#p-url-v').value === 'https://demo.example.dev/mcp');
  check('power berstatus on', $('#power').classList.contains('on'));
  check('Lanjut aktif', $('#next').disabled === false);
  $('#log-open').click();
  check('log sheet terbuka', !$('#logsheet').hidden);
  $('#log-close').click();
  check('log sheet tertutup', $('#logsheet').hidden);

  $('#next').click(); await sleep(120);
  check('Lanjut -> layar Pasang di Claude', JSON.stringify(visible()) === '[3]');
  check('judul Pasang di Claude', screens()[3].querySelector('h1').textContent === 'Pasang di Claude');
  check('URL di input', $('#in-url').value === 'https://demo.example.dev/mcp');
  check('token terisi tapi tersembunyi', $('#in-token').value === 'tok_secret_123' && $('#in-token').type === 'password');
  $('[data-eye="in-token"]').click(); await sleep(20);
  check('mata membuka token', $('#in-token').type === 'text');
  $('[data-eye="in-token"]').click(); await sleep(20);
  check('mata menyembunyikan token', $('#in-token').type === 'password');
  $('[data-copy="token"]').click(); await sleep(60);
  check('salin token memberi notifikasi', $('#toast').classList.contains('show'));
  $('#tok-new').click(); await sleep(150);
  check('buat token baru memanggil API', calls.some((c) => c.startsWith('POST /api/token/new')));
  check('banner token basi tampil', !$('#stale').hidden);

  $('#next').click(); await sleep(40);
  check('Lanjut -> layar uji', JSON.stringify(visible()) === '[4]');
  check('Lanjut tersembunyi di layar uji', $('#next').classList.contains('invisible'));
  check('brand terlihat lagi', !$('#brand').classList.contains('dim'));
  check('judul uji idle', $('#t-title').textContent === 'Uji Koneksi');
  $('#tester').click(); await sleep(150);
  check('judul Koneksi Aman', $('#t-title').textContent === 'Koneksi Aman', $('#t-title').textContent);
  check('dua baris hasil', d.querySelectorAll('#checks li').length === 2 && !$('#checks').hidden);
  testResult = { ok: false, message: 'Server lokal normal, tapi jalur publik gagal: token ditolak.',
    local: { ok: true, ms: 8, status: 200, detail: '' }, public: { ok: false, ms: null, status: 401, detail: 'token ditolak.' } };
  $('#tester').click(); await sleep(150);
  check('judul Ada Masalah', $('#t-title').textContent === 'Ada Masalah', $('#t-title').textContent);
  check('baris gagal bertanda bad', !!$('#checks li.bad'));

  $('#back').click(); await sleep(40);
  check('back -> layar Pasang', JSON.stringify(visible()) === '[3]');
  dot(2); await sleep(40);
  $('#power').click(); await sleep(150);
  check('stop dipanggil & judul kembali', calls.some((c) => c.startsWith('POST /api/stop')) && $('#p-title').textContent === 'Nyalakan Server', $('#p-title').textContent);
  dot(4); await sleep(40);
  $('#tester').click(); await sleep(60);
  check('uji saat mati mengarahkan ke layar server', JSON.stringify(visible()) === '[2]', JSON.stringify(visible()));

  check('onboarded tersimpan', w.localStorage.getItem('onboarded') === '1');
  check('tanpa error JS', errors.length === 0, errors.join(' | '));
  console.log(failed ? `\n${failed} GAGAL` : '\nSEMUA LOLOS');
  process.exit(failed ? 1 : 0);
})();

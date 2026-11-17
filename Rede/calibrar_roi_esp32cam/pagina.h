// Interface web do calibrar_roi_esp32cam (servida em "/").
// Tudo roda no navegador: o ESP32 so entrega o quadro cru (/frame) e guarda a ROI (/roi).
#pragma once

static const char PAGINA_HTML[] = R"rawliteral(<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Calibrar ROI</title>
<style>
:root{--bg:#121212;--card:#1e1e1e;--fg:#ececec;--mut:#9a9a9a;--ac:#2d8cff;--roi:#00e676;--fat:#ffd600;--salva:#40c4ff;--err:#ff5252;--borda:#333}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:10px 16px;border-bottom:1px solid var(--borda);display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
header h1{font-size:16px;margin:0}
header small{color:var(--mut)}
main{max-width:1180px;margin:auto;padding:12px 16px;display:grid;gap:14px;grid-template-columns:minmax(0,800px) minmax(260px,1fr)}
@media(max-width:900px){main{grid-template-columns:1fr}}
#c{width:100%;aspect-ratio:4/3;image-rendering:pixelated;touch-action:none;background:#000;border-radius:6px;display:block;cursor:crosshair}
.card{background:var(--card);border:1px solid var(--borda);border-radius:8px;padding:12px;margin-bottom:12px}
.card h2{font-size:13px;margin:0 0 8px;color:var(--mut);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.campos{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}
.campos label{display:flex;flex-direction:column;font-size:12px;color:var(--mut)}
input[type=number]{width:100%;min-width:0;background:#111;color:var(--fg);border:1px solid var(--borda);border-radius:4px;padding:5px 4px;font:inherit;-moz-appearance:textfield}
input[type=number]::-webkit-inner-spin-button,input[type=number]::-webkit-outer-spin-button{-webkit-appearance:none;margin:0}
.bts{display:flex;flex-wrap:wrap;gap:6px}
button{background:#2a2a2a;color:var(--fg);border:1px solid #444;border-radius:5px;padding:7px 10px;font:inherit;cursor:pointer}
button:hover{border-color:#777}
button.pri{background:var(--ac);border-color:var(--ac);color:#fff}
button.on{background:#ffab00;border-color:#ffab00;color:#000}
#status{min-height:1.4em;margin-top:8px}
#status.err{color:var(--err)}
#barra{display:flex;justify-content:space-between;color:var(--mut);font-size:12px;margin-top:6px;gap:8px;flex-wrap:wrap}
#fatias{display:flex;flex-wrap:wrap;gap:6px}
#fatias figure{margin:0;text-align:center;font-size:11px;color:var(--mut)}
#fatias canvas{width:56px;height:56px;image-rendering:pixelated;border:1px solid var(--borda);display:block}
pre{background:#111;border:1px solid var(--borda);border-radius:4px;padding:8px;margin:6px 0;white-space:pre-wrap;word-break:break-all;font-size:12px;user-select:all}
.dica{color:var(--mut);font-size:12px;margin:6px 0 0}
.leg{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
#naoSalvo{color:#ffab00;display:none}
</style>
</head>
<body>
<header>
  <h1>Calibrar ROI do hidrômetro</h1>
  <small>quadro 160×120 cinza, os mesmos pixels que o OCR recebe</small>
</header>
<main>
  <section>
    <canvas id="c"></canvas>
    <div id="barra">
      <span id="fps">conectando…</span>
      <span><span class="leg" style="background:var(--roi)"></span>ROI atual
        &nbsp;<span class="leg" style="background:var(--fat)"></span>fatias
        &nbsp;<span class="leg" style="background:var(--salva)"></span>ROI salva</span>
      <span id="cursor"></span>
    </div>
    <p class="dica">Arraste no vídeo para desenhar a caixa. Arraste dentro dela para mover, pelos cantos para redimensionar.
      Setas movem 1 px; Shift+setas mudam o tamanho. Gire o hidrômetro ou a câmera até os dígitos ficarem paralelos às bordas da caixa
      e cada dígito caber inteiro na sua fatia.</p>
  </section>

  <aside>
    <div class="card">
      <h2>Caixa (pixels do quadro)</h2>
      <div class="campos">
        <label>x0<input type="number" id="x0" min="0" max="160"></label>
        <label>y0<input type="number" id="y0" min="0" max="120"></label>
        <label>x1<input type="number" id="x1" min="0" max="160"></label>
        <label>y1<input type="number" id="y1" min="0" max="120"></label>
        <label>dígitos<input type="number" id="n" min="1" max="10"></label>
      </div>
      <p class="dica" id="tam"></p>
    </div>

    <div class="card">
      <h2>Vídeo</h2>
      <div class="bts">
        <button id="btCongelar">Congelar</button>
        <button id="btFlash">Flash</button>
        <button id="btFoto">Baixar foto (PNG)</button>
      </div>
      <p class="dica">O firmware de OCR captura sem flash. Use o flash só para enxergar melhor ao posicionar.</p>
    </div>

    <div class="card">
      <h2>Salvar</h2>
      <div class="bts">
        <button class="pri" id="btSalvar">Salvar no ESP32</button>
        <button id="btRestaurar">Voltar à salva</button>
        <button id="btJson">Baixar JSON</button>
        <button id="btApagar">Apagar salva</button>
      </div>
      <div id="status"></div>
      <div id="naoSalvo">Alterações não salvas.</div>
    </div>

    <div class="card">
      <h2>Entrada do classificador (28×28 por fatia)</h2>
      <div id="fatias"></div>
    </div>

    <div class="card">
      <h2>Para colar no código</h2>
      <pre id="trecho"></pre>
      <button id="btCopiar">Copiar</button>
    </div>
  </aside>
</main>

<script>
const W = 160, H = 120, S = 4, D = 28;   // quadro, escala do canvas, entrada do classificador
const cv = document.getElementById('c'), ctx = cv.getContext('2d');
cv.width = W * S; cv.height = H * S;
const off = document.createElement('canvas'); off.width = W; off.height = H;
const octx = off.getContext('2d');
const img = octx.createImageData(W, H);
const $ = id => document.getElementById(id);

let gray = new Uint8Array(W * H);
let roi = {x0: 20, y0: 45, x1: 140, y1: 75, n: 6};
let salva = null;          // ROI gravada no ESP32 (ou null)
let congelado = false, flash = false;
let quadros = 0, tFps = performance.now();

// ---------- estado / normalizacao ----------
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
function normalizar(r) {
  let {x0, y0, x1, y1, n} = r;
  n = clamp(Math.round(n) || 1, 1, 10);
  if (x0 > x1) [x0, x1] = [x1, x0];
  if (y0 > y1) [y0, y1] = [y1, y0];
  x0 = clamp(Math.round(x0), 0, W); x1 = clamp(Math.round(x1), 0, W);
  y0 = clamp(Math.round(y0), 0, H); y1 = clamp(Math.round(y1), 0, H);
  if (x1 - x0 < n) { x1 = Math.min(W, x0 + n); x0 = x1 - n; }
  if (y1 - y0 < 2) { y1 = Math.min(H, y0 + 2); y0 = y1 - 2; }
  return {x0, y0, x1, y1, n};
}
const igual = (a, b) => a && b && ['x0','y0','x1','y1','n'].every(k => a[k] === b[k]);

// Mesmo fatiamento inteiro do lerDigitos() do firmware.
function fatias(r) {
  const out = [], larg = r.x1 - r.x0;
  for (let i = 0; i < r.n; i++)
    out.push([r.x0 + Math.floor(larg * i / r.n), r.x0 + Math.floor(larg * (i + 1) / r.n)]);
  return out;
}

function mudou(nova, deCampo) {
  roi = normalizar(nova);
  if (!deCampo) atualizarCampos();
  atualizarTextos();
  desenhar();
}

// ---------- desenho ----------
function desenhar() {
  const d = img.data;
  for (let i = 0; i < W * H; i++) { const v = gray[i]; d[4*i] = d[4*i+1] = d[4*i+2] = v; d[4*i+3] = 255; }
  octx.putImageData(img, 0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(off, 0, 0, W * S, H * S);

  const {x0, y0, x1, y1} = roi;
  // escurece fora da caixa
  ctx.fillStyle = 'rgba(0,0,0,.5)';
  ctx.fillRect(0, 0, W*S, y0*S);
  ctx.fillRect(0, y1*S, W*S, (H - y1)*S);
  ctx.fillRect(0, y0*S, x0*S, (y1 - y0)*S);
  ctx.fillRect(x1*S, y0*S, (W - x1)*S, (y1 - y0)*S);

  // ROI salva (se diferente da atual)
  if (salva && !igual(salva, roi)) {
    ctx.setLineDash([6, 4]); ctx.strokeStyle = cssVar('--salva'); ctx.lineWidth = 2;
    ctx.strokeRect(salva.x0*S, salva.y0*S, (salva.x1 - salva.x0)*S, (salva.y1 - salva.y0)*S);
    ctx.setLineDash([]);
  }

  // divisoes das fatias
  ctx.strokeStyle = cssVar('--fat'); ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
  const fs = fatias(roi);
  for (let i = 1; i < fs.length; i++) {
    const x = fs[i][0] * S + .5;
    ctx.beginPath(); ctx.moveTo(x, y0*S); ctx.lineTo(x, y1*S); ctx.stroke();
  }
  ctx.setLineDash([]);

  // caixa + alcas
  ctx.strokeStyle = cssVar('--roi'); ctx.lineWidth = 2;
  ctx.strokeRect(x0*S, y0*S, (x1 - x0)*S, (y1 - y0)*S);
  ctx.fillStyle = cssVar('--roi');
  for (const [cx, cy] of [[x0,y0],[x1,y0],[x0,y1],[x1,y1]]) ctx.fillRect(cx*S - 5, cy*S - 5, 10, 10);

  desenharFatias(fs);
}

// O que o classificador recebe: vizinho mais proximo, igual ao classificarFatia().
function desenharFatias(fs) {
  const box = $('fatias');
  if (box.children.length !== fs.length) {
    box.innerHTML = '';
    fs.forEach((_, i) => {
      const f = document.createElement('figure');
      const c = document.createElement('canvas'); c.width = D; c.height = D;
      const cap = document.createElement('figcaption'); cap.textContent = 'd' + i;
      f.append(c, cap); box.append(f);
    });
  }
  const alt = Math.max(roi.y1 - roi.y0, 1);
  fs.forEach(([sx0, sx1], i) => {
    const c = box.children[i].firstChild, cc = c.getContext('2d');
    const id = cc.createImageData(D, D), larg = Math.max(sx1 - sx0, 1);
    for (let y = 0; y < D; y++) {
      const ys = clamp(roi.y0 + Math.floor(y * alt / D), 0, H - 1);
      for (let x = 0; x < D; x++) {
        const xs = clamp(sx0 + Math.floor(x * larg / D), 0, W - 1);
        const v = gray[ys * W + xs], k = 4 * (y * D + x);
        id.data[k] = id.data[k+1] = id.data[k+2] = v; id.data[k+3] = 255;
      }
    }
    cc.putImageData(id, 0, 0);
  });
}

const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// ---------- campos e textos ----------
function atualizarCampos() {
  for (const k of ['x0','y0','x1','y1','n']) if (document.activeElement !== $(k)) $(k).value = roi[k];
}
function atualizarTextos() {
  const {x0, y0, x1, y1, n} = roi;
  $('tam').textContent = `Tamanho ${x1 - x0}×${y1 - y0} px, ~${((x1 - x0) / n).toFixed(1)} px por dígito.`;
  $('trecho').textContent =
`// ROI calibrada no quadro ${W}x${H} (calibrar_roi_esp32cam)
static const int ROI_X0 = ${x0}, ROI_Y0 = ${y0}, ROI_X1 = ${x1}, ROI_Y1 = ${y1};
static const int N_FATIAS = ${n};
// caixa (formato de roi_manual.csv): "${x0},${y0},${x1},${y1}"`;
  $('naoSalvo').style.display = igual(salva, roi) ? 'none' : 'block';
}
for (const k of ['x0','y0','x1','y1','n']) {
  $(k).addEventListener('input', () => {
    const v = parseInt($(k).value, 10);
    if (!Number.isNaN(v)) mudou({...roi, [k]: v}, true);
  });
  $(k).addEventListener('change', atualizarCampos);
}

// ---------- mouse / toque ----------
let arraste = null;
function pos(e) {
  const r = cv.getBoundingClientRect();
  return {x: (e.clientX - r.left) * W / r.width, y: (e.clientY - r.top) * H / r.height,
          tol: 8 * W / r.width};   // 8 px de tela em unidades do quadro
}
function cantoEm(p) {
  const {x0, y0, x1, y1} = roi;
  const cs = [[x0,y0,x1,y1],[x1,y0,x0,y1],[x0,y1,x1,y0],[x1,y1,x0,y0]];  // [canto, oposto]
  for (const [cx, cy, ox, oy] of cs)
    if (Math.abs(p.x - cx) <= p.tol && Math.abs(p.y - cy) <= p.tol) return {ax: ox, ay: oy};
  return null;
}
const dentro = p => p.x > roi.x0 && p.x < roi.x1 && p.y > roi.y0 && p.y < roi.y1;

cv.addEventListener('pointerdown', e => {
  cv.setPointerCapture(e.pointerId);
  const p = pos(e), c = cantoEm(p);
  if (c) arraste = {modo: 'caixa', ...c};
  else if (dentro(p)) arraste = {modo: 'mover', px: p.x, py: p.y, r0: {...roi}};
  else arraste = {modo: 'caixa', ax: p.x, ay: p.y};
});
cv.addEventListener('pointermove', e => {
  const p = pos(e);
  $('cursor').textContent = `x=${Math.floor(clamp(p.x,0,W-1))} y=${Math.floor(clamp(p.y,0,H-1))}`;
  if (!arraste) {
    cv.style.cursor = cantoEm(p) ? 'nwse-resize' : dentro(p) ? 'move' : 'crosshair';
    return;
  }
  if (arraste.modo === 'mover') {
    const r = arraste.r0, w = r.x1 - r.x0, h = r.y1 - r.y0;
    const nx = clamp(Math.round(r.x0 + p.x - arraste.px), 0, W - w);
    const ny = clamp(Math.round(r.y0 + p.y - arraste.py), 0, H - h);
    mudou({...roi, x0: nx, y0: ny, x1: nx + w, y1: ny + h});
  } else {
    mudou({...roi, x0: arraste.ax, y0: arraste.ay, x1: p.x, y1: p.y});
  }
});
const soltar = () => { arraste = null; };
cv.addEventListener('pointerup', soltar);
cv.addEventListener('pointercancel', soltar);

document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return;
  const dx = {ArrowLeft: -1, ArrowRight: 1}[e.key] || 0, dy = {ArrowUp: -1, ArrowDown: 1}[e.key] || 0;
  if (!dx && !dy) return;
  e.preventDefault();
  if (e.shiftKey) mudou({...roi, x1: roi.x1 + dx, y1: roi.y1 + dy});
  else {
    const w = roi.x1 - roi.x0, h = roi.y1 - roi.y0;
    const nx = clamp(roi.x0 + dx, 0, W - w), ny = clamp(roi.y0 + dy, 0, H - h);
    mudou({...roi, x0: nx, y0: ny, x1: nx + w, y1: ny + h});
  }
});

// ---------- rede ----------
function status(msg, erro) { $('status').textContent = msg; $('status').className = erro ? 'err' : ''; }
const espera = ms => new Promise(r => setTimeout(r, ms));

async function loopVideo() {
  for (;;) {
    if (congelado) { await espera(200); continue; }
    try {
      const r = await fetch('/frame', {cache: 'no-store'});
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const b = new Uint8Array(await r.arrayBuffer());
      if (b.length === W * H) {
        gray = b; quadros++; desenhar();
        const t = performance.now();
        if (t - tFps > 1000) { $('fps').textContent = `ao vivo, ${(quadros * 1000 / (t - tFps)).toFixed(1)} quadros/s`; quadros = 0; tFps = t; }
      }
    } catch (err) {
      $('fps').textContent = 'sem vídeo (' + err.message + '), tentando de novo…';
      await espera(1000);
    }
  }
}

function aplicarResposta(j) {
  salva = j.valida ? {x0: j.caixa[0], y0: j.caixa[1], x1: j.caixa[2], y1: j.caixa[3], n: j.n_digitos} : null;
}

async function carregar() {
  try {
    const j = await (await fetch('/roi', {cache: 'no-store'})).json();
    aplicarResposta(j);
    if (salva) { mudou({...salva}); status('ROI salva carregada do ESP32.'); }
    else { mudou(roi); status('Nenhuma ROI salva ainda: desenhe uma e clique em Salvar.'); }
  } catch (e) { mudou(roi); status('Não consegui ler a ROI salva: ' + e.message, true); }
}

$('btSalvar').onclick = async () => {
  try {
    const r = await fetch('/roi', {method: 'POST', body: new URLSearchParams(Object.entries(roi).map(([k, v]) => [k, String(v)]))});
    if (!r.ok) throw new Error(await r.text());
    aplicarResposta(await r.json());
    atualizarTextos(); desenhar();
    status(`Salva no ESP32 (NVS): ${roi.x0},${roi.y0},${roi.x1},${roi.y1}, ${roi.n} dígitos.`);
  } catch (e) { status('Falha ao salvar: ' + e.message, true); }
};
$('btRestaurar').onclick = () => {
  if (salva) { mudou({...salva}); status('Voltou para a ROI salva.'); }
  else status('Não há ROI salva.', true);
};
$('btApagar').onclick = async () => {
  if (!confirm('Apagar a ROI salva no ESP32?')) return;
  try {
    aplicarResposta(await (await fetch('/roi/apagar', {method: 'POST'})).json());
    atualizarTextos(); desenhar(); status('ROI salva apagada.');
  } catch (e) { status('Falha ao apagar: ' + e.message, true); }
};

$('btCongelar').onclick = () => {
  congelado = !congelado;
  $('btCongelar').textContent = congelado ? 'Continuar' : 'Congelar';
  $('btCongelar').classList.toggle('on', congelado);
  if (congelado) $('fps').textContent = 'congelado';
};
$('btFlash').onclick = async () => {
  try {
    const j = await (await fetch('/flash?on=' + (flash ? 0 : 1), {method: 'POST'})).json();
    flash = j.on; $('btFlash').classList.toggle('on', flash);
  } catch (e) { status('Falha no flash: ' + e.message, true); }
};

function carimbo() { return new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15); }
function baixar(blob, nome) {
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = nome;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
$('btJson').onclick = () => {
  const j = {caixa: [roi.x0, roi.y0, roi.x1, roi.y1], n_digitos: roi.n, quadro: [W, H],
             formato: 'GRAYSCALE QQVGA', fatias: fatias(roi), salva_no_esp32: igual(salva, roi),
             gerado_em: new Date().toISOString()};
  baixar(new Blob([JSON.stringify(j, null, 1)], {type: 'application/json'}), `roi_${carimbo()}.json`);
};
$('btFoto').onclick = () => off.toBlob(b => baixar(b, `quadro_${carimbo()}.png`), 'image/png');
$('btCopiar').onclick = async () => {
  const t = $('trecho').textContent;
  try { await navigator.clipboard.writeText(t); status('Trecho copiado.'); }
  catch { // http sem HTTPS: clipboard bloqueado, usa selecao
    const s = getSelection(), rg = document.createRange(); rg.selectNodeContents($('trecho'));
    s.removeAllRanges(); s.addRange(rg); document.execCommand('copy'); status('Trecho copiado.');
  }
};

carregar().then(loopVideo);
</script>
</body>
</html>
)rawliteral";

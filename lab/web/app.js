// DC Lab viewer. Every picture is a Cycles path-traced render. A second "ID" render of the same view
// tells the app which part each pixel belongs to, so parts are clickable and can be lit from lab state.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { TRAY_PARTS, RACK_PARTS, TAG_QUESTIONS, NUMBERS, ACTION_PART } from './parts.js';
import { WORK_ORDERS } from './workorders.js';

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const token = new URLSearchParams(location.search).get('t') || '';
const canvas = $('#gl');
const TAU = Math.PI * 2;

// ---------------------------------------------------------------- ids
const RACK_IDS = { ct: [], sw: [], pt: [], inv: [36, 37], cap: [38], cc: [39, 40, 41, 42], rbus: [43], rman: [44], frame: [45] };
for (let n = 1; n <= 18; n++) RACK_IDS.ct.push(n, 100 + n, 140 + n, 160 + n);
for (let n = 1; n <= 9; n++) RACK_IDS.sw.push(18 + n, 120 + n, 180 + n);
for (let n = 1; n <= 8; n++) RACK_IDS.pt.push(27 + n);
const TAG_IDS = {
  '^TAG_rack_': [46, 47, 48], '^TAG_cartridge_': [49], '^TAG_power_': [50],
  ct_tag: Array.from({ length: 18 }, (_, i) => 101 + i), sw_tag: Array.from({ length: 9 }, (_, i) => 121 + i),
};
const tagIds = (q) => (q.under ? TAG_IDS[/CT/.test(q.under.source) ? 'ct_tag' : 'sw_tag'] : TAG_IDS[q.targets.source]) || [];
const rackGroupOfId = (id) => Object.keys(RACK_IDS).find((g) => RACK_IDS[g].includes(id)) || null;
let TRAY_IDS = {};                 // gid -> id (from manifest)
let TRAY_GID = {};                 // id -> gid
let MAN = null;
let CENT = { pano: {}, tray: {} }; // a point inside every id, and its area, for every image

// ---------------------------------------------------------------- renderer: one quad, one shader
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.NoToneMapping;
const scene = new THREE.Scene();
const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
const stateData = new Float32Array(256 * 4);
const glowData = new Float32Array(256 * 4);
const tState = new THREE.DataTexture(stateData, 256, 1, THREE.RGBAFormat, THREE.FloatType);
const tGlow = new THREE.DataTexture(glowData, 256, 1, THREE.RGBAFormat, THREE.FloatType);
for (const t of [tState, tGlow]) { t.minFilter = t.magFilter = THREE.NearestFilter; t.needsUpdate = true; }
const black = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1);
black.needsUpdate = true;
const U = {
  tBeauty: { value: black }, tPrev: { value: black }, uMix: { value: 1 }, tId: { value: black }, tState: { value: tState }, tGlow: { value: tGlow },
  uMode: { value: 0 }, uYaw: { value: Math.PI / 2 }, uPitch: { value: 0 }, uTan: { value: 0.6 }, uAspect: { value: 1.6 },
  uImgAspect: { value: 16 / 9 }, uZoom: { value: 1 }, uPan: { value: new THREE.Vector2(0, 0) }, uPulse: { value: 1 },
  uDim: { value: 1 }, uFade: { value: 1 }, uTint: { value: new THREE.Vector3(1, 1, 1) }, uWide: { value: 1 }, uTime: { value: 0 },
};
const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
  uniforms: U, depthTest: false,
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
  fragmentShader: `
    precision highp float;
    varying vec2 vUv;
    uniform sampler2D tBeauty, tPrev, tId, tState, tGlow;
    uniform float uMix;
    uniform int uMode;
    uniform float uYaw, uPitch, uTan, uAspect, uImgAspect, uZoom, uPulse, uDim, uFade, uWide, uTime;
    uniform vec2 uPan;
    uniform vec3 uTint;
    const float PI = 3.141592653589793;
    void main() {
      vec2 n = vec2(vUv.x * 2.0 * uWide - 1.0, vUv.y * 2.0 - 1.0);
      vec2 uv;
      bool inside = true;
      if (uMode == 0) {
        vec3 f = vec3(cos(uPitch) * cos(uYaw), cos(uPitch) * sin(uYaw), sin(uPitch));
        vec3 r = vec3(sin(uYaw), -cos(uYaw), 0.0);
        vec3 u = cross(r, f);
        vec3 d = normalize(f + r * n.x * uTan * uAspect + u * n.y * uTan);
        uv = vec2(0.5 - atan(d.y, d.x) / (2.0 * PI), 0.5 + asin(clamp(d.z, -1.0, 1.0)) / PI);
      } else {
        vec2 s = uAspect > uImgAspect ? vec2(uAspect / uImgAspect, 1.0) : vec2(1.0, uImgAspect / uAspect);
        uv = (n * s / uZoom + uPan) * 0.5 + 0.5;
        inside = uv.x >= 0.0 && uv.x <= 1.0 && uv.y >= 0.0 && uv.y <= 1.0;
      }
      vec3 col = inside ? texture2D(tBeauty, uv).rgb : vec3(0.62, 0.635, 0.66) * (1.0 - 0.22 * length(vUv - 0.5));
      if (uMode == 0 && uMix < 1.0) col = mix(texture2D(tPrev, uv).rgb, col, uMix);     // step between viewpoints
      float id = inside ? floor(texture2D(tId, uv).r * 255.0 + 0.5) : 0.0;
      vec2 lu = vec2((id + 0.5) / 256.0, 0.5);
      vec4 st = texture2D(tState, lu);
      vec4 gl = texture2D(tGlow, lu);
      col = mix(col, st.rgb, st.a);
      float lit = step(0.001, gl.r + gl.g + gl.b);
      col *= mix(uDim, 1.0, lit);
      col += gl.rgb * (gl.a > 0.5 ? uPulse : 1.0);
      vec2 q = vUv - 0.5;
      col *= 1.0 - 0.3 * dot(q, q);                                   // lens vignette
      col += (fract(sin(dot(gl_FragCoord.xy + uTime, vec2(12.9898, 78.233))) * 43758.5453) - 0.5) * 0.014;   // sensor grain
      gl_FragColor = vec4(col * uTint * uFade, 1.0);
    }`,
}));
scene.add(quad);
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, cam));
const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.22, 0.5, 0.96);
composer.addPass(bloom);
composer.addPass(new OutputPass());

// ---------------------------------------------------------------- images
const loader = new THREE.TextureLoader();
const cache = new Map();       // name -> { p, pair, t }
const KEEP = 11;
const missing = new Map();   // viewpoint -> time we last found it not rendered
function loadPair(name) {
  const hit = cache.get(name);
  if (hit) { hit.t = performance.now(); return hit.p; }
  const entry = { t: performance.now(), pair: null };
  entry.p = Promise.all([loader.loadAsync(`img/${name}.jpg`), loader.loadAsync(`img/${name}_id.png`)]).then(([b, i]) => {
    b.colorSpace = THREE.SRGBColorSpace;
    b.minFilter = THREE.LinearFilter;
    b.generateMipmaps = false;
    b.wrapS = THREE.RepeatWrapping;
    i.colorSpace = THREE.NoColorSpace;
    i.minFilter = i.magFilter = THREE.NearestFilter;
    i.generateMipmaps = false;
    i.wrapS = THREE.RepeatWrapping;
    const c = document.createElement('canvas');
    c.width = i.image.width;
    c.height = i.image.height;
    const g = c.getContext('2d', { willReadFrequently: true });
    g.drawImage(i.image, 0, 0);
    entry.pair = { beauty: b, id: i, read: (u, v) => g.getImageData(Math.min(c.width - 1, Math.max(0, Math.floor(u * c.width))),
      Math.min(c.height - 1, Math.max(0, Math.floor((1 - v) * c.height))), 1, 1).data[0] };
    return entry.pair;
  });
  entry.p.catch(() => { cache.delete(name); missing.set(name.replace('pano_', ''), performance.now()); });
  cache.set(name, entry);
  if (cache.size > KEEP) {                       // drop the views visited longest ago
    const old = [...cache.entries()].filter(([, e]) => e.pair && e.pair !== V.cur).sort((a, b) => a[1].t - b[1].t);
    while (cache.size > KEEP && old.length) { const [k, e] = old.shift(); e.pair.beauty.dispose(); e.pair.id.dispose(); cache.delete(k); }
  }
  return entry.p;
}
const V = { kind: 'pano', station: null, frame: 24, cur: null, yaw: Math.PI / 2, pitch: 0, fov: 62, zoom: 1, pan: [0, 0], goal: null, kick: 0 };
const ST = {};                 // viewpoints: name -> { pos, title, hero, nb: [neighbour names] }
function buildGraph() {
  for (const [k, s] of Object.entries(MAN.stations)) ST[k] = { ...s, nb: [] };
  const names = Object.keys(ST);
  for (const a of names) for (const b of names) {
    if (a !== b && Math.hypot(ST[a].pos[0] - ST[b].pos[0], ST[a].pos[1] - ST[b].pos[1]) < 1.95) ST[a].nb.push(b);
  }
}
const frameName = (k) => `tray_${String(k).padStart(2, '0')}`;
let fade = 1;
async function show(kind, which, instant = false) {
  let pair;
  try { pair = await loadPair(kind === 'pano' ? `pano_${which}` : frameName(which)); } catch {
    if (kind === 'pano') toast('That spot is still rendering. Try another direction.', true, 2600);
    return false;
  }
  const step = !instant && kind === 'pano' && V.kind === 'pano' && V.cur && V.cur !== pair;
  if (step) { U.tPrev.value = V.cur.beauty; U.uMix.value = 0; } else U.uMix.value = 1;
  V.kind = kind;
  if (kind === 'pano') V.station = which; else V.frame = which;
  V.cur = pair;
  U.tBeauty.value = pair.beauty;
  U.tId.value = pair.id;
  U.uMode.value = kind === 'pano' ? 0 : 1;
  if (!instant && !step) fade = 0.3;
  $$('#views button').forEach((b) => b.classList.toggle('on', kind === 'pano' ? b.dataset.view === which : b.dataset.view === 'bench'));
  $('#where').textContent = kind === 'pano' ? (ST[which] || {}).title || ''
    : (which === MAN.tray_top ? 'Bench: compute tray from above. Drag or use the arrow keys to turn it.' : 'Bench: compute tray. Drag or use the arrow keys to turn it.');
  if (kind === 'tray') for (const k of [(which + 1) % 24, (which + 23) % 24]) loadPair(frameName(k)).catch(() => {});
  else for (const n of (ST[which] || { nb: [] }).nb) loadPair(`pano_${n}`).catch(() => {});
  $('#map').style.display = kind === 'pano' ? 'block' : 'none';
  $('#hint').style.display = kind === 'pano' ? '' : 'none';
}
function station(name) {
  V.zoom = 1; V.pan = [0, 0];
  if ((V.kind !== 'pano' || V.station !== name) && ST[name] && ST[name].hero) {
    V.yaw = name === 'rear' ? -Math.PI / 2 : name === 'hall' ? 2.56 : Math.PI / 2;
    V.pitch = name === 'hall' ? 0.04 : -0.02;
    V.fov = name === 'hall' ? 80 : 70;
    V.goal = null;
  }
  return show('pano', name);
}
function bench(frame) { V.zoom = 1; V.pan = [0, 0]; V.goal = null; return show('tray', frame === undefined ? MAN.tray_top : frame); }
function view(name) { return name === 'bench' ? bench() : station(name === 'rack' ? 'front' : name); }

// ---- walking: one step to the nearest viewpoint in the direction you face
function walk(dir) {
  if (V.kind !== 'pano' || !ST[V.station]) return false;
  const here = ST[V.station].pos;
  const yaw = V.yaw + (dir < 0 ? Math.PI : 0);
  let best = null, bestA = 1.1;
  for (const n of ST[V.station].nb) {
    if (missing.has(n) && performance.now() - missing.get(n) < 45000) continue;
    const p = ST[n].pos;
    let a = Math.atan2(p[1] - here[1], p[0] - here[0]) - yaw;
    a = Math.abs(((((a + Math.PI) % TAU) + TAU) % TAU) - Math.PI);
    if (a < bestA) { bestA = a; best = n; }
  }
  $('#hint').classList.add('off');
  if (!best) return false;
  V.goal = null;
  show('pano', best).then(() => { V.kick = dir > 0 ? 0.1 : -0.07; });
  return true;
}
function turn(sign) {
  $('#hint').classList.add('off');
  if (V.kind === 'tray') { const k = V.frame === MAN.tray_top ? 0 : (((V.frame + sign) % 24) + 24) % 24; return show('tray', k, true); }
  V.goal = { yaw: (V.goal ? V.goal.yaw : V.yaw) - sign * (Math.PI / 6), pitch: V.pitch };
  return null;
}

// ---- floor plan
let mapT = 0;
const MAPB = { x0: -9.2, x1: 13.2, y0: -12.4, y1: 3.4 };
function mapXY(x, y) {
  const c = $('#map');
  const k = Math.min((c.width - 24) / (MAPB.x1 - MAPB.x0), (c.height - 24) / (MAPB.y1 - MAPB.y0));
  return [12 + (x - MAPB.x0) * k, 12 + (MAPB.y1 - y) * k, k];
}
function drawMap() {
  const c = $('#map');
  if (V.kind !== 'pano' || !MAN || !MAN.plan) return;
  const g = c.getContext('2d');
  g.clearRect(0, 0, c.width, c.height);
  const P = MAN.plan;
  const rect = (x0, y0, x1, y1, fill) => { const [ax, ay] = mapXY(x0, y1); const [bx, by] = mapXY(x1, y0); g.fillStyle = fill; g.fillRect(ax, ay, bx - ax, by - ay); };
  const [, wy] = mapXY(0, P.wall_y);
  g.fillStyle = 'rgba(60,64,70,.28)';
  g.fillRect(0, 0, c.width, wy);                                   // rock behind the row
  rect(P.row[0], P.row[1], P.row[2], P.row[3], 'rgba(255,255,255,.9)');
  rect(P.r12[0], P.r12[1], P.r12[2], P.r12[3], '#0a84ff');
  const [px, py, k] = mapXY(P.pod[0], P.pod[1]);
  g.strokeStyle = 'rgba(40,44,50,.55)'; g.lineWidth = 2;
  g.beginPath(); g.arc(px, py, P.pod[2] * k, 0, TAU); g.stroke();
  rect(P.bench[0] - 0.55, P.bench[1] - 0.6, P.bench[0] + 0.55, P.bench[1] + 0.6, 'rgba(10,60,120,.5)');
  for (const [n, s] of Object.entries(ST)) {
    const [x, y] = mapXY(s.pos[0], s.pos[1]);
    g.fillStyle = n === V.station ? '#0a84ff' : missing.has(n) ? 'rgba(40,44,50,.14)' : 'rgba(40,44,50,.38)';
    g.beginPath(); g.arc(x, y, n === V.station ? 7 : 3, 0, TAU); g.fill();
  }
  const s = ST[V.station];
  if (s) {
    const [x, y] = mapXY(s.pos[0], s.pos[1]);
    const a = -V.yaw, w = 0.5;
    g.fillStyle = 'rgba(10,132,255,.28)';
    g.beginPath(); g.moveTo(x, y); g.arc(x, y, 34, a - w, a + w); g.closePath(); g.fill();
  }
}
$('#map').addEventListener('click', (e) => {
  const c = $('#map');
  const r = c.getBoundingClientRect();
  const mx = ((e.clientX - r.left) / r.width) * c.width, my = ((e.clientY - r.top) / r.height) * c.height;
  let best = null, bd = 26;
  for (const [n, s] of Object.entries(ST)) { const [x, y] = mapXY(s.pos[0], s.pos[1]); const d = Math.hypot(x - mx, y - my); if (d < bd) { bd = d; best = n; } }
  if (best) { V.goal = null; missing.delete(best); show('pano', best); }
});

// ---------------------------------------------------------------- geometry: screen <-> image
// The scene fills the window. Its optical centre sits in the part the side panel does not cover.
function visW() {
  const p = document.querySelector('body.mode-live #live, body.mode-quiz #quiz');
  const left = p ? p.getBoundingClientRect().left : canvas.clientWidth;
  return Math.max(320, left - 14);
}
function size() { const r = canvas.getBoundingClientRect(); const wv = visW(); return { r, wv, a: wv / r.height }; }
function basis() {
  const cp = Math.cos(V.pitch), sp = Math.sin(V.pitch), cy = Math.cos(V.yaw), sy = Math.sin(V.yaw);
  const f = [cp * cy, cp * sy, sp], rt = [sy, -cy, 0];
  return { f, rt, up: [rt[1] * f[2] - rt[2] * f[1], rt[2] * f[0] - rt[0] * f[2], rt[0] * f[1] - rt[1] * f[0]] };
}
function flatScale(a) { const ia = 16 / 9; return a > ia ? [a / ia, 1] : [1, ia / a]; }
function uvAt(clientX, clientY) {
  const { r, wv, a } = size();
  const nx = ((clientX - r.left) / wv) * 2 - 1;
  const ny = -(((clientY - r.top) / r.height) * 2 - 1);
  if (V.kind === 'pano') {
    const t = Math.tan((V.fov * Math.PI) / 360);
    const { f, rt, up } = basis();
    const d = [0, 1, 2].map((i) => f[i] + rt[i] * nx * t * a + up[i] * ny * t);
    return [(((0.5 - Math.atan2(d[1], d[0]) / TAU) % 1) + 1) % 1, 0.5 + Math.asin(d[2] / Math.hypot(...d)) / Math.PI];
  }
  const s = flatScale(a);
  return [((nx * s[0]) / U.uZoom.value + U.uPan.value.x) * 0.5 + 0.5, ((ny * s[1]) / U.uZoom.value + U.uPan.value.y) * 0.5 + 0.5];
}
function screenAt(u, v) {
  const { r, wv, a } = size();
  let nx, ny;
  if (V.kind === 'pano') {
    const lon = (0.5 - u) * TAU, lat = (v - 0.5) * Math.PI;
    const d = [Math.cos(lat) * Math.cos(lon), Math.cos(lat) * Math.sin(lon), Math.sin(lat)];
    const { f, rt, up } = basis();
    const dot = (p, q) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2];
    const z = dot(d, f);
    if (z <= 0.05) return null;
    const t = Math.tan((V.fov * Math.PI) / 360);
    nx = dot(d, rt) / z / (t * a);
    ny = dot(d, up) / z / t;
  } else {
    const s = flatScale(a);
    nx = (((u - 0.5) * 2 - U.uPan.value.x) * U.uZoom.value) / s[0];
    ny = (((v - 0.5) * 2 - U.uPan.value.y) * U.uZoom.value) / s[1];
  }
  if (Math.abs(nx) > 0.97 || Math.abs(ny) > 0.97) return null;
  return { x: r.left + ((nx + 1) / 2) * wv, y: r.top + ((1 - ny) / 2) * r.height };
}
function lookAt(u, v) { V.goal = { yaw: (0.5 - u) * TAU, pitch: THREE.MathUtils.clamp((v - 0.5) * Math.PI, -1.2, 1.2) }; }

// ---------------------------------------------------------------- pointer: look around / turn the tray / click
let drag = null;
canvas.addEventListener('pointerdown', (e) => {
  drag = { x: e.clientX, y: e.clientY, sx: e.clientX, moved: 0, frame0: V.frame };
  canvas.focus();
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener('pointermove', (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  drag.moved += Math.abs(dx) + Math.abs(dy);
  drag.x = e.clientX; drag.y = e.clientY;
  const h = canvas.clientHeight;
  if (V.kind === 'pano') {
    const k = (2 * Math.tan((V.fov * Math.PI) / 360)) / h;
    V.goal = null;
    V.yaw += dx * k;
    V.pitch = THREE.MathUtils.clamp(V.pitch + dy * k, -1.25, 1.25);
  } else if (V.zoom > 1.05) {
    V.pan[0] -= ((dx / h) * 2) / V.zoom;
    V.pan[1] += ((dy / h) * 2) / V.zoom;
  } else if (Math.abs(e.clientX - drag.sx) > 24) {
    const start = drag.frame0 === MAN.tray_top ? 0 : drag.frame0;
    const k = (((start - Math.round((e.clientX - drag.sx) / 30)) % 24) + 24) % 24;
    if (k !== V.frame) show('tray', k, true);
  }
});
canvas.addEventListener('pointerup', (e) => {
  const d = drag;
  drag = null;
  if (!d || d.moved > 6 || !V.cur) return;
  const [u, v] = uvAt(e.clientX, e.clientY);
  if (u < 0 || u > 1 || v < 0 || v > 1) return;
  onPick(V.cur.read(u, v));
});
canvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  if (V.kind === 'pano') V.fov = THREE.MathUtils.clamp(V.fov * (e.deltaY > 0 ? 1.08 : 0.925), 16, 95);
  else { V.zoom = THREE.MathUtils.clamp(V.zoom * (e.deltaY > 0 ? 0.9 : 1.11), 1, 4.5); if (V.zoom === 1) V.pan = [0, 0]; }
}, { passive: false });

// ---------------------------------------------------------------- highlight + label
const HL = { ids: [], label: '' };
function idsOf(model, gid) {
  if (model === 'tray') return gid === 'busbar' ? [TRAY_IDS.busbar, 201, 202, 203] : (TRAY_IDS[gid] ? [TRAY_IDS[gid]] : []);
  return RACK_IDS[gid] || [];
}
const T = (model, gids) => ({ model, ids: [].concat(gids).flatMap((g) => (typeof g === 'number' ? [g] : idsOf(model, g))) });
function highlight(target, color = 0x3fd0ff, label = '', dim = 0.45) {
  clearHL();
  const c = new THREE.Color(color);
  for (const id of target.ids) glowData.set([c.r * 0.85, c.g * 0.85, c.b * 0.85, 1], id * 4);
  tGlow.needsUpdate = true;
  HL.ids = target.ids; HL.label = label;
  U.uDim.value = target.ids.length ? dim : 1;
}
function clearHL() {
  glowData.fill(0);
  tGlow.needsUpdate = true;
  HL.ids = []; HL.label = '';
  U.uDim.value = 1;
  $('#label').style.display = 'none';
}
function centroid(ids, key) {
  const table = (key.startsWith('pano') ? CENT.pano : CENT.tray)[key] || {};
  let best = null;
  for (const id of ids) { const c = table[id]; if (c && (!best || c[2] > best[2])) best = c; }
  return best;
}
// Bring a target into view (right station or tray frame). Returns its point in that image.
async function focus(target, opts = {}) {
  if (!target.ids.length) return null;
  if (target.model === 'tray') {
    let k = V.kind === 'tray' ? V.frame : MAN.tray_top;
    let c = centroid(target.ids, frameName(k));
    if (!c || c[2] < (opts.minArea || 260)) {
      let bestA = c ? c[2] : 0;
      for (let i = 0; i <= MAN.tray_top; i++) { const ci = centroid(target.ids, frameName(i)); if (ci && ci[2] > bestA * 1.5) { bestA = ci[2]; k = i; } }
      c = centroid(target.ids, frameName(k));
    }
    if (V.kind !== 'tray' || V.frame !== k) await show('tray', k);
    V.zoom = 1; V.pan = [0, 0];
    return c;
  }
  let st = V.kind === 'pano' && V.station !== 'hall' ? V.station : 'front';
  let c = centroid(target.ids, `pano_${st}`);
  for (const s of ['front', 'rear']) { const ci = centroid(target.ids, `pano_${s}`); if (ci && (!c || ci[2] > c[2] * 2)) { c = ci; st = s; } }
  if (!c) return null;
  if (V.kind !== 'pano' || V.station !== st) await station(st);
  if (!opts.still) lookAt(c[0], c[1]);
  return c;
}
const settled = () => !V.goal && fade >= 0.999 && U.uMix.value >= 1 && Math.abs(U.uZoom.value - V.zoom) < 0.01;

// ---------------------------------------------------------------- live rack state
let lastState = null, lastActT = 0, seenViol = -1, seenPass = -1, benchName, flash = 0, flashUv = 0, hudCt = null;
function toast(msg, good = false, ms = 6000) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'glass' + (good ? ' good' : ''); t.style.display = 'block';
  clearTimeout(toast.h);
  toast.h = setTimeout(() => { t.style.display = 'none'; }, ms);
}
const LED = { green: [0.12, 2.6, 0.5, 1], amber: [3.0, 1.1, 0.0, 1], blue: [0.2, 0.8, 3.0, 1], off: [0.006, 0.008, 0.006, 1] };
const GONE = [0.004, 0.004, 0.005, 0.96];
const setS = (id, rgba) => stateData.set(rgba, id * 4);
function paintState(s) {
  stateData.fill(0);
  const blink = Math.floor(performance.now() / 350) % 2 === 0;
  for (let n = 1; n <= 18; n++) {
    const ct = s.cts[`CT${String(n).padStart(2, '0')}`];
    if (!ct) continue;
    if (!(ct.rack === 'production' && ct.location === 'rack')) { for (const id of [n, 100 + n, 140 + n, 160 + n]) setS(id, GONE); continue; }
    const on = ct.power === 'on';
    setS(140 + n, on ? LED.green : LED.off);
    setS(160 + n, !on ? LED.off : ct.amber ? (blink ? LED.amber : LED.off) : (ct.in_job && Math.random() < 0.3 ? LED.blue : LED.green));
  }
  for (let n = 1; n <= 9; n++) {
    const occ = Object.values(s.switches).find((w) => w.slot === n && !['removed', 'boxed'].includes(w.state));
    if (!occ) { for (const id of [18 + n, 120 + n, 180 + n]) setS(id, GONE); continue; }
    setS(180 + n, occ.state === 'online' ? LED.green : (blink || occ.state === 'offline' ? LED.amber : LED.off));
  }
  tState.needsUpdate = true;
}
function applyState(s) {
  lastState = s;
  const live = document.body.classList.contains('mode-live');
  $('#rackname').textContent = s.rack;
  const fab = s.fabric === 'ok';
  $('#status').innerHTML = `<span class="pill ${fab ? 'ok' : 'down'}">NVLink fabric: ${fab ? 'ok' : s.fabric}</span><span>${s.passed.length}/${s.total} tickets passed</span>`;
  const tk = $('#ticket');
  if (s.ticket) { tk.querySelector('.tid').textContent = s.ticket.id; tk.querySelector('.ttl').textContent = s.ticket.title; }
  tk.querySelector('.prog').textContent = `${s.passed.length}/${s.total}`;
  paintState(s);
  if (live) {
    const onBench = Object.keys(s.cts).find((k) => s.cts[k].location === 'bench') || null;
    if (onBench !== benchName) {
      const first = benchName === undefined;
      benchName = onBench;
      if (onBench) { bench(); toast(`${onBench} is on the bench.`, true, 3200); } else if (!first) station('front');
    }
    if (onBench && V.kind === 'tray') $('#where').textContent = `Bench: ${onBench} (${s.cts[onBench].tag}), lid ${s.cts[onBench].lid}. Drag to turn it.`;
    const a = s.last;
    if (a && a.t > lastActT) { const fresh = lastActT > 0; lastActT = a.t; if (fresh) actionFx(a); } else if (!lastActT) lastActT = 1;
    const sig = `${s.ticket ? s.ticket.id : ''}:${s.passed.length}`;
    if (sig !== applyState.sig) { applyState.sig = sig; if (!$('#board').hidden) loadTickets(); }
  }
  if (seenViol >= 0 && s.violations.length > seenViol && live) { toast('Violation: ' + s.violations[s.violations.length - 1]); flash = 1; }
  seenViol = s.violations.length;
  if (seenPass >= 0 && s.passed.length > seenPass && live) toast('Ticket passed. Now say it out loud: dclab speak', true);
  seenPass = s.passed.length;
  if (hudCt && s.cts[hudCt]) showHud(hudCt);
}
async function actionFx(a) {
  if (a.k === 'uv') { flashUv = 1; return; }
  let gids = null;
  if (a.k === 'clean' || a.k === 'ziptie') gids = ['leak' + String(a.sensor || '').replace(/\D/g, '')];
  else if (a.k === 'inspect' && a.area === 'leak-sensors') gids = ['leak00', 'leak01', 'leak10', 'leak11'];
  else { const g = ACTION_PART[`${a.k}:${a.part || a.fru || a.target || a.area}`]; if (g) gids = [g]; }
  if (!gids || V.kind !== 'tray') return;
  const t = T('tray', gids);
  const part = TRAY_PARTS.find((p) => p.id === gids[0]);
  await focus(t);
  highlight(t, a.k === 'replace' ? 0x37d67a : 0x3fd0ff, gids.length > 1 ? 'Leak sensors' : (part ? part.name : ''), 0.55);
  clearTimeout(actionFx.h);
  actionFx.h = setTimeout(clearHL, 3400);
}
function showHud(name) {
  const ct = lastState && lastState.cts[name];
  if (!ct) return;
  hudCt = name;
  $('#hint').classList.add('off');
  const h = $('#hud');
  h.style.display = 'block';
  h.innerHTML = `<b>${name}</b> <span class="k">tag</span> ${ct.tag} <span class="k">BMC</span> ${ct.ip} <span class="k">power</span> ${ct.power} `
    + `<span class="k">where</span> ${ct.location}${ct.rack === 'hospital' ? ' (hospital)' : ''} <span class="k">in job</span> ${ct.in_job ? 'yes' : 'no'}`
    + `${ct.sol ? ' <span class="k">SOL</span> open' : ''}${ct.usb ? ' <span class="k">USB</span> in' : ''}`;
}
function livePick(id) {
  if (V.kind === 'tray') {
    const g = TRAY_GID[id] || (id > 200 ? 'busbar' : null);
    const p = TRAY_PARTS.find((q) => q.id === g);
    if (p) { highlight(T('tray', g), 0x3fd0ff, p.name, 0.6); clearTimeout(actionFx.h); actionFx.h = setTimeout(clearHL, 2600); }
    return;
  }
  const n = id >= 1 && id <= 18 ? id : [100, 140, 160].map((b) => id - b).find((x) => x >= 1 && x <= 18) || 0;
  if (!n) return;
  const name = `CT${String(n).padStart(2, '0')}`;
  showHud(name);
  highlight(T('rack', [n]), 0x3fd0ff, name, 0.8);
  clearTimeout(actionFx.h);
  actionFx.h = setTimeout(clearHL, 1800);
}
async function poll() {
  try {
    const s = await (await fetch('/api/state')).json();
    if (!s.error && MAN) applyState(s);
  } catch { /* lab server not running: the quiz still works */ }
  setTimeout(poll, 450);
}

// ---------------------------------------------------------------- terminals
const terms = [];
function makeTerm(el, n) {
  const term = new window.Terminal({ fontSize: 13, fontFamily: '"SF Mono", "Cascadia Mono", Consolas, monospace', cursorBlink: true, scrollback: 6000,
    allowTransparency: true,
    theme: { background: 'rgba(0,0,0,0)', foreground: '#eceff3', cursor: '#ffffff', selectionBackground: 'rgba(120,170,255,.35)',
      black: '#1c1e22', red: '#ff6b62', green: '#5fd08a', yellow: '#dfe3e8', blue: '#6fb1ff', magenta: '#b9a4ff', cyan: '#86d3f7', white: '#e6e9ee',
      brightBlack: '#8a9099', brightRed: '#ff8a82', brightGreen: '#7be0a2', brightYellow: '#ffffff', brightBlue: '#93c5ff',
      brightMagenta: '#cdbdff', brightCyan: '#a8e1fb', brightWhite: '#ffffff' } });
  const fit = new window.FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(el);
  const ws = new WebSocket(`ws://${location.host}/ws/term?t=${encodeURIComponent(token)}&n=${n}`);
  ws.binaryType = 'arraybuffer';
  const sizeIt = () => { try { fit.fit(); } catch { /* hidden */ } if (ws.readyState === 1) ws.send(JSON.stringify({ resize: [term.cols, term.rows] })); };
  ws.onopen = sizeIt;
  ws.onmessage = (e) => term.write(new Uint8Array(e.data));
  ws.onclose = () => term.write('\r\n\x1b[33m[terminal closed. Reload the page to reconnect.]\x1b[0m\r\n');
  term.onData((d) => { if (ws.readyState === 1) ws.send(new TextEncoder().encode(d)); });
  new ResizeObserver(sizeIt).observe(el);
  terms.push({ term, ws, fit });
}

// ---------------------------------------------------------------- quiz
const store = {
  get() { try { return JSON.parse(localStorage.getItem('dclab.quiz.v2')) || {}; } catch { return {}; } },
  set(v) { try { localStorage.setItem('dclab.quiz.v2', JSON.stringify(v)); } catch { /* private window */ } },
};
const Q = { model: 'tray', mode: 'wo', queue: [], cur: null, i: 0, right: 0, asked: 0, streak: 0, done: false, misses: 0, mastery: store.get() };
const norm = (s) => String(s).toLowerCase().replace(/[^a-z0-9]/g, '');
const shuffle = (a) => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const partsOf = (model) => (model === 'tray' ? TRAY_PARTS : RACK_PARTS);
const nameOf = (model, g) => { const p = partsOf(model).find((q) => q.id === g); return p ? p.name : 'not a named part'; };
const trayGroupOfId = (id) => TRAY_GID[id] || (id > 200 ? 'busbar' : null);
function setOf() { return Q.mode === 'wo' ? WORK_ORDERS : Q.mode === 'tags' ? TAG_QUESTIONS : Q.mode === 'numbers' ? NUMBERS : partsOf(Q.model); }
function mkey(item) { return `${Q.mode === 'tour' ? 'name' : Q.mode}:${item.id}`; }
function startQuiz() {
  if (!MAN) return;
  clearHL();
  if (Q.mode === 'tags') Q.model = 'rack';
  $$('#qmodel button').forEach((b) => b.classList.toggle('on', b.dataset.model === Q.model));
  $('#qmodel').style.visibility = ['tags', 'numbers', 'wo'].includes(Q.mode) ? 'hidden' : 'visible';
  const items = [...setOf()];
  Q.queue = Q.mode === 'tour' ? items : shuffle(items).sort((a, b) => (Q.mastery[mkey(a)] || 0) - (Q.mastery[mkey(b)] || 0));
  Q.i = 0;
  ask();
}
function stats() {
  const items = setOf();
  const solid = items.filter((it) => (Q.mastery[mkey(it)] || 0) >= 2).length;
  $('#qbar').style.width = `${(100 * solid) / items.length}%`;
  $('#qstats').innerHTML = `<span>${Q.right}/${Q.asked} right this session &nbsp; streak ${Q.streak}</span><span>${solid}/${items.length} solid</span>`;
}
function card(prompt, small, body, nav = '') {
  $('#qprompt').innerHTML = `<small>${small}</small>${prompt}`;
  $('#qbody').innerHTML = body;
  $('#qfeedback').innerHTML = '';
  $('#qnav').innerHTML = nav;
}
const chips = (p) => `<div class="chips">${p.fru ? '<span class="chip fru">FRU</span>' : ''}${p.slide ? `<span class="chip">slide: ${p.slide}</span>` : ''}</div>`;
async function showPart(model, gid, label, color = 0x3fd0ff) {
  const t = T(model, gid);
  await focus(t);
  highlight(t, color, label);
}
async function ask() {
  Q.done = false; Q.misses = 0;
  const it = Q.cur = Q.queue[Q.i % Q.queue.length];
  const n = `${(Q.i % Q.queue.length) + 1} / ${Q.queue.length}`;
  stats();
  if (Q.mode === 'wo') return askWO(it, n);
  if (Q.mode === 'tour') {
    card(it.name, `Tour ${n}`, `${chips(it)}<div class="fact">${it.fact}</div><div class="chip">Say the name and one fact out loud.</div>`,
      '<button id="qprev">Back</button><button id="qnext" class="on">Next</button>');
    $('#qprev').onclick = () => { Q.i = (Q.i - 1 + Q.queue.length) % Q.queue.length; ask(); };
    $('#qnext').onclick = next;
    return showPart(Q.model, it.id, it.name);
  }
  if (Q.mode === 'name') {
    const opts = shuffle([it, ...shuffle(partsOf(Q.model).filter((p) => p.id !== it.id)).slice(0, 3)]);
    card('What is the glowing part?', `Name it ${n}`, opts.map((o, i) => `<button class="opt" data-id="${o.id}"><b>${i + 1}</b>${o.name}</button>`).join(''));
    $$('#qbody .opt').forEach((b) => { b.onclick = () => {
      if (Q.done) return;
      const ok = b.dataset.id === it.id;
      b.classList.add(ok ? 'right' : 'wrong');
      if (!ok) $$('#qbody .opt').find((x) => x.dataset.id === it.id).classList.add('right');
      finish(ok, it);
    }; });
    return showPart(Q.model, it.id, '');
  }
  if (Q.mode === 'find') {
    clearHL();
    card(`Click the: ${it.name}`, `Find it ${n}`, `<div class="chip">${Q.model === 'tray' ? 'Drag to turn the tray. Scroll to zoom.' : 'Drag to look around. Use Front / Rear.'}</div>`);
    return Q.model === 'tray' ? (V.kind === 'tray' ? null : bench()) : (V.kind === 'pano' && V.station !== 'hall' ? null : station('front'));
  }
  if (Q.mode === 'type') {
    card('Type the name of the glowing part.', `Type it ${n}`, '<input id="qin" autocomplete="off" spellcheck="false" placeholder="name, then Enter">');
    const inp = $('#qin');
    inp.focus();
    inp.onkeydown = (e) => {
      if (e.key !== 'Enter' || Q.done) return;
      e.stopPropagation();
      const v = norm(inp.value);
      finish(v.length > 1 && [it.name, ...(it.aka || [])].some((a) => norm(a) === v || (v.length > 3 && norm(a).includes(v))), it);
    };
    return showPart(Q.model, it.id, '');
  }
  if (Q.mode === 'tags') {
    clearHL();
    if (it.options) {
      card(it.q, `Tag hunt ${n}`, it.options.map((o, i) => `<button class="opt" data-i="${i}"><b>${i + 1}</b>${o}</button>`).join(''));
      $$('#qbody .opt').forEach((b) => { b.onclick = () => {
        if (Q.done) return;
        const ok = +b.dataset.i === it.answer;
        b.classList.add(ok ? 'right' : 'wrong');
        if (!ok) $$('#qbody .opt')[it.answer].classList.add('right');
        finish(ok, it);
      }; });
      return null;
    }
    card(it.q, `Tag hunt ${n}`, '<div class="chip">Click the spot. Use Front / Rear to walk around the rack. Scroll to zoom.</div>');
    return station(it.view === 'rear' ? 'rear' : 'front');
  }
  card(it.q, `Numbers ${n}`, '<input id="qin" inputmode="numeric" autocomplete="off" placeholder="number, then Enter">');
  const inp = $('#qin');
  inp.focus();
  inp.onkeydown = (e) => {
    if (e.key !== 'Enter' || Q.done) return;
    e.stopPropagation();
    finish(Number(inp.value.replace(/[^0-9.]/g, '')) === it.a, it);
  };
  return showPart(it.hl[0], it.hl[1], '');
}
function finish(ok, it) {
  Q.done = true; Q.asked++;
  if (ok) { Q.right++; Q.streak++; } else Q.streak = 0;
  const k = mkey(it);
  Q.mastery[k] = ok ? Math.min(3, (Q.mastery[k] || 0) + 1) : 0;
  store.set(Q.mastery);
  const ans = it.name || (it.options ? it.options[it.answer] : (it.a !== undefined ? String(it.a) : ''));
  $('#qfeedback').innerHTML = `<span class="${ok ? 'yes' : 'no'}">${ok ? 'Correct.' : 'Not yet.'}</span> ${ans ? `<b>${ans}</b>. ` : ''}${it.fact || ''}`;
  $('#qnav').innerHTML = '<button id="qnext" class="on">Next (Enter)</button>';
  $('#qnext').onclick = next;
  if (it.nodes || it.match) showPart(Q.model, it.id, it.name, ok ? 0x37d67a : 0x3fd0ff);
  if (!ok) Q.queue.splice(Math.min(Q.queue.length, (Q.i % Q.queue.length) + 4), 0, it);
  stats();
}
function next() { Q.i++; ask(); }
function quizPick(id) {
  if (Q.done) return;
  const it = Q.cur;
  const inTray = V.kind === 'tray';
  if (Q.mode === 'find') {
    if ((Q.model === 'tray') !== inTray) return;
    const g = inTray ? trayGroupOfId(id) : rackGroupOfId(id);
    if (g === it.id || (it.id === 'bianca' && ['gpu', 'cpu', 'mezz', 'manifold', 'leak00', 'leak01', 'leak10', 'leak11'].includes(g))) return finish(true, it);
    Q.misses++;
    $('#qfeedback').innerHTML = `<span class="no">That is ${g ? 'the ' + nameOf(Q.model, g) : 'not a named part'}.</span> Try again.`;
    if (Q.misses >= 2) finish(false, it);
  } else if (Q.mode === 'tags' && it.targets) {
    if (inTray) return;
    const ids = tagIds(it);
    if (ids.includes(id)) { highlight(T('rack', ids), 0x37d67a, 'Service tag'); return finish(true, it); }
    Q.misses++;
    $('#qfeedback').innerHTML = '<span class="no">No label there.</span> Look somewhere else.';
    if (Q.misses >= 3) { const t = T('rack', ids); focus(t).then(() => highlight(t, 0x3fd0ff, 'Service tag')); finish(false, it); }
  }
}

// ---- work orders: ticket -> ID the part -> DO the operation
let W = null;
const SEC = { back: 201, front: 202, middle: 203 };
async function askWO(wo, n) {
  W = { wo, si: 0, clean: true, picked: new Set(), seqi: 0, ord: [], misses: 0, locked: false };
  Q.model = wo.model;
  $('#qprompt').innerHTML = `<small>Work order ${n}</small>${wo.title}`;
  await (wo.model === 'tray' ? bench() : station(wo.view === 'rear' ? 'rear' : 'front'));
  woStep();
}
function woStep() {
  const { wo } = W;
  const st = wo.steps[W.si];
  W.picked = new Set(); W.seqi = 0; W.ord = []; W.misses = 0; W.locked = false;
  clearHL();
  const dots = wo.steps.map((s, i) => `<i class="${i < W.si ? 'done' : i === W.si ? 'now' : ''}">${s.label}</i>`).join('');
  let body = `<div class="wo">${wo.text}</div><div class="dots">${dots}</div><div class="step"><b>${st.label}</b> ${st.prompt}</div>`;
  if (st.type === 'choice' || st.type === 'multi') {
    body += shuffle(st.options.map((_, i) => i)).map((i, k) => `<button class="opt" data-i="${i}"><b>${k + 1}</b>${st.options[i]}</button>`).join('');
    if (st.type === 'multi') body += '<button id="woconfirm" class="on">Confirm</button>';
  } else if (st.type === 'order') {
    body += shuffle(st.items.map((_, i) => i)).map((i) => `<button class="opt ord" data-i="${i}"><b>?</b>${st.items[i]}</button>`).join('');
  } else if (st.type === 'num') {
    body += '<input id="qin" inputmode="decimal" autocomplete="off" placeholder="number, then Enter">';
  } else {
    body += `<div class="chip">${st.type === 'busbar' ? 'Click the screws on the busbar, one pair at a time.' : (wo.model === 'tray' ? 'Click it on the tray. Drag to turn it, scroll to zoom.' : 'Click it on the rack. Drag to look around, scroll to zoom.')}</div>`;
  }
  $('#qbody').innerHTML = body;
  $('#qfeedback').innerHTML = '';
  $('#qnav').innerHTML = '';
  if (st.type === 'busbar') {
    show('tray', MAN.tray_top).then(() => {
      const c = centroid([TRAY_IDS.busbar], frameName(MAN.tray_top));
      V.zoom = 2.2;
      if (c) V.pan = [(c[0] - 0.5) * 2, (c[1] - 0.5) * 2];
    });
  } else if (st.view) station(st.view);
  if (st.type === 'choice') {
    $$('#qbody .opt').forEach((b) => { b.onclick = () => {
      if (W.locked) return;
      const ok = +b.dataset.i === st.answer;
      b.classList.add(ok ? 'right' : 'wrong');
      if (!ok) $$('#qbody .opt').find((x) => +x.dataset.i === st.answer).classList.add('right');
      woDone(ok);
    }; });
  } else if (st.type === 'multi') {
    $$('#qbody .opt').forEach((b) => { b.onclick = () => { if (!W.locked) b.classList.toggle('sel'); }; });
    $('#woconfirm').onclick = () => {
      if (W.locked) return;
      const sel = $$('#qbody .opt.sel').map((b) => +b.dataset.i).sort();
      const ok = JSON.stringify(sel) === JSON.stringify([...st.answers].sort());
      $$('#qbody .opt').forEach((b) => { if (st.answers.includes(+b.dataset.i)) b.classList.add('right'); else if (b.classList.contains('sel')) b.classList.add('wrong'); });
      woDone(ok);
    };
  } else if (st.type === 'order') {
    $$('#qbody .opt').forEach((b) => { b.onclick = () => {
      if (W.locked || b.classList.contains('right')) return;
      if (+b.dataset.i === W.ord.length) {
        W.ord.push(+b.dataset.i);
        b.classList.add('right');
        b.querySelector('b').textContent = W.ord.length;
        if (W.ord.length === st.items.length) woDone(true);
      } else {
        b.classList.add('wrong');
        $$('#qbody .opt').forEach((x) => { x.querySelector('b').textContent = +x.dataset.i + 1; });
        woDone(false, 'Right order: ' + st.items.map((t, i) => `${i + 1}. ${t}`).join('  '));
      }
    }; });
  } else if (st.type === 'num') {
    const inp = $('#qin');
    inp.focus();
    inp.onkeydown = (e) => {
      if (e.key !== 'Enter' || W.locked) return;
      e.stopPropagation();
      const ok = Math.abs(Number(inp.value.replace(/[^0-9.]/g, '')) - st.answer) < 1e-6;
      woDone(ok, ok ? '' : `Answer: ${st.answer}`);
    };
  }
}
function woDone(ok, note = '') {
  W.locked = true;
  if (!ok) W.clean = false;
  const last = W.si === W.wo.steps.length - 1;
  $('#qfeedback').innerHTML = `<span class="${ok ? 'yes' : 'no'}">${ok ? 'Right.' : 'Not yet.'}</span> ${note}`;
  const go = () => { W.go = null; if (last) woClose(); else { W.si++; woStep(); } };
  if (ok && !last) return setTimeout(go, 750);
  $('#qnav').innerHTML = `<button id="qnext" class="on">${last ? 'Close the work order' : 'Continue'} (Enter)</button>`;
  $('#qnext').onclick = go;
  W.go = go;
}
function woClose() {
  const { wo } = W;
  Q.done = true; Q.asked++;
  if (W.clean) { Q.right++; Q.streak++; } else Q.streak = 0;
  const k = mkey(wo);
  Q.mastery[k] = W.clean ? Math.min(3, (Q.mastery[k] || 0) + 1) : 0;
  store.set(Q.mastery);
  clearHL();
  V.zoom = 1; V.pan = [0, 0];
  $('#qbody').innerHTML = `<div class="wo">${wo.text}</div><div class="fact">${wo.fact}</div><div class="chip">Say it out loud: what the part is, and what you do with it.</div>`;
  $('#qfeedback').innerHTML = W.clean ? '<span class="yes">Work order closed clean.</span>' : '<span class="no">Closed with misses.</span> It comes back in a few tickets.';
  $('#qnav').innerHTML = '<button id="qnext" class="on">Next work order (Enter)</button>';
  $('#qnext').onclick = next;
  if (!W.clean) Q.queue.splice(Math.min(Q.queue.length, (Q.i % Q.queue.length) + 4), 0, wo);
  stats();
}
function woPick(id) {
  if (!W || W.locked) return;
  const st = W.wo.steps[W.si];
  if (!['pick', 'picktag', 'busbar'].includes(st.type)) return;
  const inTray = V.kind === 'tray';
  if ((W.wo.model === 'tray') !== inTray) return;
  const model = W.wo.model;
  const g = inTray ? trayGroupOfId(id) : rackGroupOfId(id);
  const what = g ? 'the ' + nameOf(model, g) : 'not a named part';
  const miss = (msg, t, label) => {
    W.misses++;
    $('#qfeedback').innerHTML = `<span class="no">${msg}</span> Try again.`;
    if (W.misses >= 2) { focus(t).then(() => highlight(t, 0x3fd0ff, label)); woDone(false); }
  };
  if (st.type === 'picktag') {
    const ids = TAG_IDS[st.targets.source] || [];
    if (ids.includes(id)) { highlight(T('rack', ids), 0x37d67a, 'Service tag'); return woDone(true); }
    return miss('No label there.', T('rack', ids), 'Service tag');
  }
  if (st.type === 'busbar') {
    const sec = { 201: 'back', 202: 'front', 203: 'middle' }[id];
    if (!sec) {
      if (g !== 'busbar') miss(`That is ${what}.`, T('tray', 'busbar'), 'Internal busbar');
      else $('#qfeedback').innerHTML = 'Click the screws themselves (three pairs along the busbar).';
      return;
    }
    if (sec !== st.seq[W.seqi]) return woDone(false, `You clicked ${sec}. The order is back, front, middle.`);
    W.seqi++;
    const done = st.seq.slice(0, W.seqi);
    highlight(T('tray', done.map((d) => SEC[d])), 0x37d67a, `${done.join(' → ')}  (20 in-lb)`, 0.75);
    if (W.seqi === st.seq.length) woDone(true, 'Back, front, middle.');
    else $('#qfeedback').innerHTML = `<span class="yes">${sec} torqued.</span> Next pair.`;
    return;
  }
  const hit = st.accept.find((a) => a === g || (a === 'bianca' && ['gpu', 'cpu', 'mezz', 'manifold'].includes(g)));
  if (!hit) return miss(`That is ${what}.`, T(model, st.accept), st.accept.map((a) => nameOf(model, a)).join(' + '));
  W.picked.add(hit);
  const got = [...W.picked];
  highlight(T(model, got), 0x37d67a, got.map((a) => nameOf(model, a)).join(' + '), 0.7);
  if (!st.all || W.picked.size === st.accept.length) woDone(true, st.all ? `${got.map((a) => nameOf(model, a)).join(', ')}.` : `${nameOf(model, hit)}.`);
  else $('#qfeedback').innerHTML = `<span class="yes">${nameOf(model, hit)}.</span> ${st.accept.length - W.picked.size} more.`;
}
function onPick(id) {
  if (document.body.classList.contains('mode-quiz')) return Q.mode === 'wo' ? woPick(id) : quizPick(id);
  livePick(id);
}
addEventListener('keydown', (e) => {
  const quiz = document.body.classList.contains('mode-quiz');
  if (quiz && Q.mode === 'wo' && e.key === 'Enter' && W && W.go && W.locked) { e.preventDefault(); return W.go(); }
  if (!quiz) return;
  if (e.target.tagName === 'INPUT') { if (e.key === 'Enter' && Q.done) next(); return; }
  if (e.key === 'Enter' && (Q.done || Q.mode === 'tour')) next();
  const n = +e.key;
  if (n >= 1 && n <= 5) { const b = $$('#qbody .opt')[n - 1]; if (b) b.click(); }
});

// ---------------------------------------------------------------- modes, tabs, ticket board, keys
const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
function setMode(m) {
  document.body.className = `mode-${m}`;
  $$('#modes button').forEach((b) => b.classList.toggle('on', b.dataset.mode === m));
  clearHL();
  $('#hud').style.display = 'none';
  hudCt = null;
  resize();
  if (m === 'quiz') startQuiz();
  else { benchName = undefined; station('front'); if (!terms.length && token) { makeTerm($('#term1'), 1); makeTerm($('#term2'), 2); } }
}
$$('#modes button').forEach((b) => { b.onclick = () => setMode(b.dataset.mode); });
$$('#views button').forEach((b) => { b.onclick = () => view(b.dataset.view); });
$$('#qmodel button').forEach((b) => { b.onclick = () => { Q.model = b.dataset.model; startQuiz(); }; });
$$('#qmode button').forEach((b) => { b.onclick = () => { Q.mode = b.dataset.qm; $$('#qmode button').forEach((x) => x.classList.toggle('on', x === b)); startQuiz(); }; });

let TK = null;
function setTab(name) {
  $$('#ltabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
  $('#console').hidden = name !== 'console';
  $('#console').style.display = name === 'console' ? 'flex' : 'none';
  $('#board').hidden = name !== 'board';
  if (name === 'board') { closeTicket(); loadTickets(); } else terms.forEach((t) => { try { t.fit.fit(); } catch { /* hidden */ } });
}
$$('#ltabs button').forEach((b) => { b.onclick = () => setTab(b.dataset.tab); });
async function loadTickets() {
  try { TK = await (await fetch('/api/tickets')).json(); renderBoard(); } catch { $('#jirabar').textContent = 'Start the lab with START-DCLAB.ps1 to see the tickets.'; }
}
function renderBoard() {
  if (!TK) return;
  const j = TK.jira;
  $('#jirabar').innerHTML = j.linked ? `<b>Jira</b> linked: ${esc(j.site)}, project ${esc(j.project)}. Each ticket below carries its Jira key.`
    : '<b>Jira</b> is not linked yet. Create a free Jira Cloud site with a project keyed DCOPS and an API token, then in a window run <code>dclab jira setup</code> and <code>dclab jira push</code>.';
  $('#tlist').innerHTML = [['inprogress', 'In progress'], ['todo', 'To do'], ['done', 'Done']].map(([s, label]) => {
    const rows = TK.tickets.filter((t) => t.status === s);
    return rows.length ? `<div class="tgroup">${label} &middot; ${rows.length}</div>` + rows.map((t) => `<div class="trow ${s}" data-id="${t.id}"><span class="key">${esc(t.jira || t.id)}</span>`
      + `<span class="t">${esc(t.title)}</span><span class="track">${esc(t.track)}</span></div>`).join('') : '';
  }).join('');
  $$('#tlist .trow').forEach((r) => { r.onclick = () => openTicket(r.dataset.id); });
}
function closeTicket() { $('#tdetail').hidden = true; $('#tlist').hidden = false; $('#jirabar').hidden = false; }
function typeIn(n, text) { const t = terms[n]; if (t && t.ws.readyState === 1) { t.ws.send(new TextEncoder().encode(text)); t.term.focus(); } }
async function openTicket(id) {
  const t = await (await fetch(`/api/ticket?id=${encodeURIComponent(id)}`)).json();
  const meta = TK.tickets.find((x) => x.id === id) || {};
  const jl = TK.jira.linked && meta.jira ? `<a href="${esc(TK.jira.site)}/browse/${esc(meta.jira)}" target="_blank" rel="noopener"><button>Open ${esc(meta.jira)} in Jira</button></a>` : '';
  $('#tdetail').innerHTML = `<button id="tback">&lsaquo; All tickets</button><h2>${esc(t.title)}</h2>`
    + `<div class="meta">${meta.jira ? esc(meta.jira) + ' &middot; ' : ''}${esc(t.id)} &middot; ${esc(t.track)} &middot; ${meta.status === 'done' ? 'Done' : meta.status === 'inprogress' ? 'In progress' : 'To do'}</div>`
    + `<div class="wo">${esc(t.body)}</div><div class="acts"><button class="primary" id="tstart">Start in Window 1</button>${jl}</div>`
    + `<h3>Teach</h3><ol>${t.teach.map((x) => `<li>${esc(x)}</li>`).join('')}</ol><h3>Do</h3><ol>${t.do.map((x) => `<li>${esc(x)}</li>`).join('')}</ol>`;
  $('#tlist').hidden = true; $('#jirabar').hidden = true; $('#tdetail').hidden = false;
  $('#tback').onclick = closeTicket;
  $('#tstart').onclick = () => { setTab('console'); typeIn(0, `dclab start ${t.id.slice(6)}\r`); };
}

addEventListener('keydown', (e) => {
  const el = document.activeElement;
  if (el && el !== canvas && el !== document.body && el.tagName !== 'BUTTON') return;      // typing in a terminal or a box
  const k = e.key.toLowerCase();
  const act = { arrowup: () => walk(1), w: () => walk(1), arrowdown: () => walk(-1), s: () => walk(-1),
    arrowleft: () => turn(-1), a: () => turn(-1), arrowright: () => turn(1), d: () => turn(1) }[k];
  if (!act) return;
  e.preventDefault();
  act();
});

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h, false);
  composer.setSize(w, h);
  const wv = visW();
  U.uAspect.value = wv / h;
  U.uWide.value = w / wv;
}
addEventListener('resize', resize);

let lastT = 0;
function tick(t) {
  requestAnimationFrame(tick);
  const dt = Math.min((t - lastT) / 1000 || 0.016, 0.5);
  lastT = t;
  const ease = 1 - Math.exp(-dt * 5);
  if (V.goal) {
    let dy = V.goal.yaw - V.yaw;
    dy = ((((dy + Math.PI) % TAU) + TAU) % TAU) - Math.PI;
    V.yaw += dy * ease;
    V.pitch += (V.goal.pitch - V.pitch) * ease;
    if (Math.abs(dy) < 0.004 && Math.abs(V.goal.pitch - V.pitch) < 0.004) V.goal = null;
  }
  if (U.uMix.value < 1) U.uMix.value = Math.min(1, U.uMix.value + dt / 0.38);
  fade += (1 - fade) * (1 - Math.exp(-dt * 7));
  if (fade > 0.999) fade = 1;
  flash = Math.max(0, flash - dt * 0.8);
  flashUv = Math.max(0, flashUv - dt * 0.4);
  U.uTint.value.set(1 - flashUv * 0.55, 1 - flash * 0.6 - flashUv * 0.7, 1 - flash * 0.7 + flashUv * 0.5);
  V.kick *= Math.exp(-dt * 6);
  if (Math.abs(V.kick) < 0.001) V.kick = 0;
  U.uYaw.value = V.yaw; U.uPitch.value = V.pitch; U.uTan.value = Math.tan((V.fov * Math.PI) / 360) * (1 + V.kick);
  if (t - mapT > 90) { mapT = t; drawMap(); }
  U.uZoom.value += (V.zoom - U.uZoom.value) * ease;
  U.uPan.value.x += (V.pan[0] - U.uPan.value.x) * ease;
  U.uPan.value.y += (V.pan[1] - U.uPan.value.y) * ease;
  U.uPulse.value = 0.55 + 0.45 * Math.sin(t / 170);
  U.uTime.value = (t % 1000) * 0.37;
  U.uFade.value = fade;
  if (lastState && Math.floor(t / 350) !== Math.floor((t - dt * 1000) / 350)) paintState(lastState);
  const el = $('#label');
  const c = HL.label && HL.ids.length && V.cur ? centroid(HL.ids, V.kind === 'pano' ? `pano_${V.station}` : frameName(V.frame)) : null;
  const p = c && screenAt(c[0], c[1]);
  el.style.display = p ? 'block' : 'none';
  if (p) { el.textContent = HL.label; el.style.left = `${p.x}px`; el.style.top = `${p.y}px`; }
  composer.render();
}

// ---------------------------------------------------------------- boot
MAN = await (await fetch('img/manifest.json')).json();
CENT = await (await fetch('img/ids.json')).json();
TRAY_IDS = MAN.tray_ids;
TRAY_GID = Object.fromEntries(Object.entries(TRAY_IDS).filter(([, v]) => v < 200).map(([k, v]) => [v, k]));
buildGraph();
resize();
await show('pano', 'front', true);
$('#loading').style.display = 'none';
setMode(token && new URLSearchParams(location.search).get('mode') !== 'quiz' ? 'live' : 'quiz');
poll();
requestAnimationFrame(tick);

// helpers for automated tests and the demo recording
async function screenOf(model, gid, sub) {
  const ids = typeof gid === 'number' ? [gid] : Array.isArray(gid) ? gid : sub ? [SEC[sub.replace('screw_', '')]] : idsOf(model, gid).filter((i) => i < 200);
  const keep = model === 'tray' && V.kind === 'tray' && V.zoom > 1.2;
  const c = keep ? centroid(ids, frameName(V.frame)) : await focus({ model, ids }, { minArea: 120 });
  if (!c) return null;
  for (let i = 0; i < 80 && !settled(); i++) await new Promise((r) => setTimeout(r, 50));
  const p = screenAt(c[0], c[1]);
  return p && { x: Math.round(p.x), y: Math.round(p.y) };
}
window.dclab = { setMode, view, station, bench, Q, startQuiz, ask, next, screenOf, settled, V, TAG_IDS, walk, turn, ST, setTab,
  go(id) { const i = Q.queue.findIndex((w) => w.id === id); if (i >= 0) { Q.i = i; ask(); } return i; } };

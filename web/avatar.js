import * as THREE from 'three';

const params = new URLSearchParams(location.search);
if (params.get('transparent')) document.body.classList.add('transparent');
const $ = (id) => document.getElementById(id);

// ---------- сцена ----------
const renderer = new THREE.WebGLRenderer({ canvas: $('c'), antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
scene.add(new THREE.AmbientLight(0xffffff, 1.1));
const sun = new THREE.DirectionalLight(0xffffff, 2.2);
sun.position.set(1.5, 2, 3);
scene.add(sun);
function resize() {
  renderer.setSize(innerWidth, innerHeight, false);
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
}
addEventListener('resize', resize);
resize();

// ---------- состояние ----------
const S = { state: 'idle', emotion: 'neutral', talking: false, impulse: 0, vis: 0, lookX: 0, lookY: 0 };
const EMO = {
  neutral:   { brow: 0,     browY: 0,    eye: 1,    smile: 0.3,  blush: 0.1, base: 0 },
  happy:     { brow: -0.05, browY: 0.04, eye: 0.78, smile: 1,    blush: 0.7, base: 0 },
  sad:       { brow: -0.45, browY: -0.01, eye: 0.85, smile: -0.7, blush: 0,   base: 0 },
  angry:     { brow: 0.5,   browY: -0.03, eye: 0.9,  smile: -0.5, blush: 0.1, base: 0 },
  surprised: { brow: 0,     browY: 0.1,  eye: 1.25, smile: 0,    blush: 0.1, base: 0.4 },
  thinking:  { brow: 0.15,  browY: 0.03, eye: 0.9,  smile: 0,    blush: 0,   base: 0 },
};
const cur = { ...EMO.neutral, yaw: 0, pitch: 0, roll: 0, lookX: 0, lookY: 0, open: 0, blink: 0 };
const lerp = (a, b, k) => a + (b - a) * k;

addEventListener('pointermove', (e) => {
  S.lookX = (e.clientX / innerWidth - 0.5) * 2;
  S.lookY = -(e.clientY / innerHeight - 0.5) * 2;
});

// ---------- встроенный персонаж ----------
function buildPlaceholder() {
  const g = new THREE.Group();
  scene.add(g);
  camera.position.set(0, 0, 7);
  camera.lookAt(0, -0.35, 0);

  const std = (c, o = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.7, metalness: 0, ...o });
  const basic = (c, o = {}) => new THREE.MeshBasicMaterial({ color: c, ...o });
  const skin = std(0xffe0cf), hairM = std(0x3b2a6b, { roughness: 0.5, side: THREE.DoubleSide });

  // тело
  const torso = new THREE.Mesh(new THREE.SphereGeometry(1.25, 40, 24), std(0x2d3a6b));
  torso.position.set(0, -2.3, 0); torso.scale.set(1.05, 0.7, 0.6); g.add(torso);
  const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.34, 1.2, 24), skin);
  neck.position.set(0, -1.2, 0); g.add(neck);

  // голова
  const head = new THREE.Group(); g.add(head);
  const face = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 32), skin);
  face.scale.set(1, 1.05, 0.95); head.add(face);

  // волосы: задняя половина + шапочка + чёлка
  const back = new THREE.Mesh(new THREE.SphereGeometry(1.08, 40, 28, Math.PI, Math.PI), hairM);
  back.scale.set(1.02, 1.12, 1.02); back.position.y = 0.06; head.add(back);
  const cap = new THREE.Mesh(new THREE.SphereGeometry(1.06, 40, 20, 0, Math.PI * 2, 0, Math.PI * 0.36), hairM);
  cap.scale.set(1, 1.07, 0.98); head.add(cap);
  for (const x of [-0.6, -0.3, 0, 0.3, 0.6]) {
    const y = 0.44;
    const z = 0.97 * Math.sqrt(Math.max(0, 1 - x * x - (y / 1.05) ** 2)) + 0.02;
    const b = new THREE.Mesh(new THREE.SphereGeometry(0.16, 16, 12), hairM);
    b.scale.set(1, 1.7, 0.5); b.position.set(x, y - 0.02, z); head.add(b);
  }

  // глаза
  const eyes = [], irises = [];
  for (const sx of [-1, 1]) {
    const eg = new THREE.Group(); eg.position.set(sx * 0.38, 0.02, 0.875); head.add(eg);
    const white = new THREE.Mesh(new THREE.SphereGeometry(0.15, 24, 16), std(0xffffff, { roughness: 0.3 }));
    white.scale.set(1, 1.15, 0.35); eg.add(white);
    const ig = new THREE.Group(); ig.position.z = 0.055; eg.add(ig);
    const iris = new THREE.Mesh(new THREE.CircleGeometry(0.105, 24), basic(0x38c8ff)); ig.add(iris);
    const pupil = new THREE.Mesh(new THREE.CircleGeometry(0.05, 20), basic(0x101030)); pupil.position.z = 0.002; ig.add(pupil);
    const hl = new THREE.Mesh(new THREE.CircleGeometry(0.03, 12), basic(0xffffff)); hl.position.set(0.04, 0.04, 0.004); ig.add(hl);
    const lash = new THREE.Mesh(new THREE.BoxGeometry(0.32, 0.03, 0.02), basic(0x2a1a3a));
    lash.position.set(0, 0.16, 0.05); eg.add(lash);
    eyes.push(eg); irises.push(ig);
  }

  // брови
  const brows = [];
  for (const sx of [-1, 1]) {
    const bp = new THREE.Group(); bp.position.set(sx * 0.38, 0.3, 0.86); head.add(bp);
    bp.add(new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.032, 0.03), basic(0x2a1f55)));
    brows.push({ bp, side: sx });
  }

  // румянец
  const blush = [];
  for (const sx of [-1, 1]) {
    const m = new THREE.Mesh(new THREE.CircleGeometry(0.13, 20), basic(0xff7a9c, { transparent: true, opacity: 0.1 }));
    m.position.set(sx * 0.58, -0.18, 0.77); m.rotation.y = sx * 0.7; head.add(m); blush.push(m);
  }

  // рот: улыбка/грусть (дуга) + раскрытие (эллипс)
  const mouth = new THREE.Group(); mouth.position.set(0, -0.42, 0.865); head.add(mouth);
  const arcG = new THREE.Group(); arcG.position.y = 0.03; mouth.add(arcG);
  const arc = new THREE.Mesh(new THREE.TorusGeometry(0.14, 0.012, 8, 24, Math.PI), basic(0x7a3a4a, { side: THREE.DoubleSide }));
  arc.rotation.z = Math.PI; arcG.add(arc);
  const hole = new THREE.Mesh(new THREE.SphereGeometry(0.1, 20, 14), basic(0x8a2a3a));
  hole.scale.set(1.2, 0.01, 0.3); mouth.add(hole);

  return {
    update(c, t) {
      head.rotation.set(c.pitch, c.yaw, c.roll);
      g.position.y = Math.sin(t * 1.3) * 0.015;
      torso.scale.y = 0.7 + Math.sin(t * 1.3) * 0.008;
      for (const { bp, side } of brows) { bp.position.y = 0.3 + c.browY; bp.rotation.z = c.brow * side; }
      const open = Math.max(0.05, c.eye * (1 - 0.93 * c.blink));
      for (const e of eyes) e.scale.y = open;
      for (const ig of irises) ig.position.set(c.lookX * 0.045, c.lookY * 0.04, 0.055);
      for (const m of blush) m.material.opacity = c.blush * 0.55;
      hole.scale.y = 0.01 + c.open * 0.16;
      hole.scale.x = 1.2 + c.open * 0.15;
      arcG.scale.y = c.smile * 0.35;
      arc.visible = c.open < 0.3;
    },
  };
}

// ---------- VRM-модель ----------
async function buildVrm() {
  let has = false;
  try { has = (await (await fetch('/has_model')).json()).vrm; } catch { /* нет */ }
  if (!has) return null;
  const [{ GLTFLoader }, { VRMLoaderPlugin, VRMUtils }] = await Promise.all([
    import('three/addons/loaders/GLTFLoader.js'),
    import('@pixiv/three-vrm'),
  ]);
  const loader = new GLTFLoader();
  loader.register((p) => new VRMLoaderPlugin(p));
  const gltf = await loader.loadAsync('/model.vrm');
  const vrm = gltf.userData.vrm;
  VRMUtils.rotateVRM0(vrm);
  scene.add(vrm.scene);
  const hum = vrm.humanoid, bone = (n) => hum.getNormalizedBoneNode(n);
  if (bone('leftUpperArm')) bone('leftUpperArm').rotation.z = -1.2;   // опускаем руки из T-позы
  if (bone('rightUpperArm')) bone('rightUpperArm').rotation.z = 1.2;
  vrm.update(0);
  const hp = new THREE.Vector3(); bone('head').getWorldPosition(hp);
  camera.position.set(0, hp.y - 0.1, 1.7);
  camera.lookAt(0, hp.y - 0.12, 0);

  const emoMap = { happy: 'happy', sad: 'sad', angry: 'angry', surprised: 'surprised', thinking: 'relaxed' };
  const W = { happy: 0, sad: 0, angry: 0, surprised: 0, relaxed: 0 };
  const VIS = ['aa', 'ih', 'ou', 'ee', 'oh'];
  const em = vrm.expressionManager;
  const set = (n, v) => { try { em.setValue(n, v); } catch { /* нет такого выражения */ } };

  return {
    update(c, t, dt) {
      const target = emoMap[S.emotion];
      for (const k of Object.keys(W)) W[k] = lerp(W[k], k === target ? 0.8 : 0, 1 - Math.exp(-dt * 6));
      for (const k of Object.keys(W)) set(k, W[k]);
      set('blink', c.blink);
      const main = VIS[S.vis % VIS.length];
      for (const v of VIS) set(v, 0);
      set(main, Math.min(1, c.open * 1.1));
      if (main !== 'aa') set('aa', c.open * 0.35);
      const head = bone('head'), neck = bone('neck'), spine = bone('spine');
      if (head) head.rotation.set(c.pitch * 0.6, c.yaw * 0.6, c.roll * 0.6);
      if (neck) neck.rotation.set(c.pitch * 0.4, c.yaw * 0.4, c.roll * 0.4);
      if (spine) spine.rotation.x = Math.sin(t * 1.3) * 0.012;
      vrm.update(dt);
    },
  };
}

// ---------- события от Акиры ----------
const dot = $('dot'), stext = $('stext');
const LABEL = { idle: 'ожидание', listening: 'слушает', thinking: 'думает', speaking: 'говорит', working: 'выполняет' };
let hideTimer = null;
function setState(s) {
  S.state = s; S.talking = s === 'speaking';
  dot.className = s; stext.textContent = LABEL[s] || s;
  clearTimeout(hideTimer);
  $('sub').style.opacity = 1;
  if (s === 'idle') hideTimer = setTimeout(() => { $('sub').style.opacity = 0; }, 6000);
}
function handle(ev) {
  switch (ev.type) {
    case 'state': setState(ev.state); break;
    case 'emotion': if (EMO[ev.emotion]) S.emotion = ev.emotion; break;
    case 'word': S.impulse = Math.min(1, 0.55 + (ev.len || 4) * 0.06 + Math.random() * 0.25); S.vis = (S.vis + 1 + Math.floor(Math.random() * 3)) % 5; break;
    case 'user': $('user').textContent = 'Вы: ' + ev.text; $('akira').textContent = ''; break;
    case 'reply_start': $('akira').textContent = ''; $('tool').textContent = ''; break;
    case 'tool': $('tool').textContent = '⚙ ' + ev.name; break;
    case 'confirm': showConfirm(ev); break;
    case 'notice': showNotice(ev.text); break;
    case 'confirm_done': $('confirm').style.display = 'none'; break;
    case 'token': $('akira').textContent += ev.text; break;
  }
}
let noticeTimer = null;
function showNotice(text) {
  const n = $('notice');
  n.textContent = '🔔 ' + text; n.style.display = 'block';
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { n.style.display = 'none'; }, 8000);
}
let confirmId = null;
function showConfirm(ev) {
  confirmId = ev.id;
  $('ctext').textContent = ev.text;
  $('confirm').style.display = 'block';
}
function answer(ok) {
  $('confirm').style.display = 'none';
  fetch('/confirm', { method: 'POST', headers: { 'X-Akira-Token': window.AKIRA_TOKEN }, body: JSON.stringify({ id: confirmId, approved: ok }) }).catch(() => {});
}
$('yes').onclick = () => answer(true);
$('no').onclick = () => answer(false);

function connect() {
  const es = new EventSource('/events');
  es.onopen = () => { if (stext.textContent === 'подключение…' || stext.textContent.startsWith('нет связи')) stext.textContent = LABEL[S.state]; };
  es.onmessage = (e) => handle(JSON.parse(e.data));
  es.onerror = () => { stext.textContent = 'нет связи с Акирой'; dot.className = ''; };
}

// ---------- главный цикл ----------
let avatar = null;
let nextBlink = 2, blinkT = -1;
const clock = new THREE.Clock();
function frame() {
  const dt = Math.min(clock.getDelta(), 0.1), t = clock.elapsedTime;
  const k = 1 - Math.exp(-dt * 8);
  const tg = EMO[S.emotion] || EMO.neutral;
  for (const key of ['brow', 'browY', 'eye', 'smile', 'blush', 'base']) cur[key] = lerp(cur[key], tg[key], k);

  // моргание
  if (blinkT < 0 && t > nextBlink) blinkT = 0;
  if (blinkT >= 0) {
    blinkT += dt;
    cur.blink = Math.sin(Math.min(1, blinkT / 0.16) * Math.PI);
    if (blinkT > 0.16) { blinkT = -1; cur.blink = 0; nextBlink = t + 2 + Math.random() * 4; }
  }

  // рот
  S.impulse = Math.max(0, S.impulse - dt * 2.5);
  let openT = cur.base;
  if (S.talking) openT = Math.max(openT, 0.1 + 0.5 * (0.5 + 0.5 * Math.sin(t * 11)) * (0.35 + 0.65 * S.impulse));
  cur.open = lerp(cur.open, openT, 1 - Math.exp(-dt * 18));

  // взгляд и поза
  let ly = S.lookY, lx = S.lookX, roll = 0, eyeBoost = 1;
  if (S.state === 'thinking') { ly = 0.6; lx = 0.5; roll = -0.06; }
  if (S.state === 'listening') { roll = 0.05; eyeBoost = 1.08; }
  cur.lookX = lerp(cur.lookX, lx, k * 0.6);
  cur.lookY = lerp(cur.lookY, ly, k * 0.6);
  cur.yaw = Math.sin(t * 0.5) * 0.05 + cur.lookX * 0.22;
  cur.pitch = Math.sin(t * 0.7) * 0.025 + cur.lookY * 0.12 + S.impulse * 0.03;
  cur.roll = lerp(cur.roll, roll, k * 0.5);
  const c = { ...cur, eye: cur.eye * eyeBoost };

  if (avatar) avatar.update(c, t, dt);
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

// ---------- чат-ввод ----------
const chatForm = $('chat-dock');
if (chatForm) {
  chatForm.onsubmit = (ev) => {
    ev.preventDefault();
    const inp = $('chat-input');
    const txt = inp.value.trim();
    if (!txt) return;
    inp.value = '';
    fetch('/chat', {
      method: 'POST',
      headers: {
        'X-Akira-Token': window.AKIRA_TOKEN,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ text: txt }),
    }).catch((err) => console.error('Ошибка отправки:', err));
  };
}

(async () => {
  try { avatar = await buildVrm(); }
  catch (e) { console.error('VRM не загрузился, использую встроенного персонажа:', e); avatar = null; }
  if (!avatar) avatar = buildPlaceholder();
  connect();
  frame();
})();

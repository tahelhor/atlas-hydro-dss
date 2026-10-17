// Atlas basin story - animated, narrated 3D view of the drought scenario (Three.js).
// Mounted once by Streamlit (components v2). Each rerun calls the default export again with
// new `data`; the scene is kept and animated towards the new state instead of being rebuilt.

const THREE_VERSION = '0.180.0';
const URLS = [
  `https://cdn.jsdelivr.net/npm/three@${THREE_VERSION}/+esm`,
  `https://cdn.jsdelivr.net/npm/three@${THREE_VERSION}/examples/jsm/controls/OrbitControls.js/+esm`,
  `https://cdn.jsdelivr.net/npm/three@${THREE_VERSION}/examples/jsm/renderers/CSS2DRenderer.js/+esm`,
];
let libsPromise = null;
const loadLibs = () => (libsPromise ||= Promise.all(URLS.map((u) => import(u))));

const REDUCED = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
// tap-water hours/day ramp (same encoding as the monthly calendar heatmap)
// diverging: red (few hours) -> neutral grey (18 h) -> blue (24 h), interpolated without hue drift
// neutral grey sits at 20.5 h: anything below ~20 h of water a day reads as a problem (red)
const STOPS = [[12, '#d03b3b'], [17, '#e66767'], [20.5, '#8d8a84'], [22.5, '#6da7ec'], [24, '#2a78d6']];
const NEUTRAL = '#33414a';
const DURATIONS = { basin: 7500, drought: 16500, who: 9500, flows: 10500, change: 10000 };
const LEVER_STEP = 3400;
const STORE_KEY = 'atlas-basin-story-v1';

export default function (component) {
  const { data, parentElement } = component;
  const root = parentElement.querySelector('.atlas-story');
  if (!root || !data) return undefined;
  if (!root.__app) {
    root.__app = createApp(root, data).catch((err) => {
      console.error('Atlas basin story failed:', err);
      showError(root, data);
      return null;
    });
  }
  root.__app.then((app) => app && app.update(data));
  return () => {
    const pending = root.__app;
    root.__app = null;
    if (pending) pending.then((app) => app && app.dispose());
  };
}

function showError(root, data) {
  root.querySelector('.loading')?.classList.add('gone');
  const box = root.querySelector('.error');
  if (box) { box.textContent = data?.copy?.error || '3D view unavailable.'; box.style.display = 'block'; }
}

async function createApp(root, firstData) {
  root.querySelector('.loading-text').textContent = firstData.copy.loading;
  const [THREE, { OrbitControls }, { CSS2DRenderer, CSS2DObject }] = await loadLibs();
  const $ = (sel) => root.querySelector(sel);
  const stage = $('.stage');

  // ------------------------------------------------------------------ renderer & scene
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  stage.appendChild(renderer.domElement);
  const labelRenderer = new CSS2DRenderer();
  labelRenderer.domElement.className = 'labels';
  stage.appendChild(labelRenderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x121211, 950, 1900);
  const camera = new THREE.PerspectiveCamera(38, 1, 1, 4000);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, renderer.domElement);
  Object.assign(controls, { enableDamping: true, dampingFactor: 0.07, minDistance: 140, maxDistance: 1400,
    minPolarAngle: 0.2, maxPolarAngle: 1.3, autoRotateSpeed: 0.4 });

  scene.add(new THREE.HemisphereLight(0xdfe9f3, 0x15191a, 1.35));
  const sun = new THREE.DirectionalLight(0xffffff, 2.1);
  sun.position.set(-260, -320, 520);
  scene.add(sun);
  const rim = new THREE.DirectionalLight(0x4b9eae, 0.8);
  rim.position.set(280, 260, 240);
  scene.add(rim);
  const ground = new THREE.Mesh(new THREE.CircleGeometry(1600, 72),
    new THREE.MeshStandardMaterial({ color: 0x15191a, roughness: 1 }));
  ground.position.z = -0.5;
  scene.add(ground);
  const grid = new THREE.GridHelper(1600, 64, 0x22282b, 0x1a1f21);
  grid.rotation.x = Math.PI / 2;
  grid.position.z = -0.4;
  scene.add(grid);

  // ------------------------------------------------------------------ state
  const S = { data: null, hash: null, chapter: 0, playing: !REDUCED, chapterT0: 0, pausedAt: 0,
    view: 'before', month: -1, focus: null, leverIdx: -1, card: null, visible: true, disposed: false,
    timers: [], lastMonthStep: -2 };
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORE_KEY) || 'null');
    if (saved && Number.isInteger(saved.chapter)) {
      Object.assign(S, { chapter: saved.chapter, view: saved.view || 'before', playing: false });
    }
  } catch { /* storage unavailable: start the story from the beginning */ }
  const persist = () => {
    try { sessionStorage.setItem(STORE_KEY, JSON.stringify({ chapter: S.chapter, view: S.view })); } catch { /* ignore */ }
  };

  // ------------------------------------------------------------------ projection (lon/lat -> scene)
  let P = null;
  const polysOf = (g) => (g.type === 'Polygon' ? [g.coordinates] : g.coordinates);
  function setupProjection(d) {
    let minX = Infinity; let maxX = -Infinity; let minY = Infinity; let maxY = -Infinity;
    for (const p of d.provinces) for (const poly of polysOf(p.geometry)) for (const [x, y] of poly[0]) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    const cLat = (minY + maxY) / 2;
    const k = 180;
    const kx = k * Math.cos((cLat * Math.PI) / 180);
    P = { cLon: (minX + maxX) / 2, cLat, k, kx, w: (maxX - minX) * kx, h: (maxY - minY) * k };
  }
  const pt = (lon, lat, z = 0) => new THREE.Vector3((lon - P.cLon) * P.kx, (lat - P.cLat) * P.k, z);
  const toLonLat = (v) => [v.x / P.kx + P.cLon, v.y / P.k + P.cLat];
  function inRing(lon, lat, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i]; const [xj, yj] = ring[j];
      if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  const provinceAt = (lon, lat) => {
    for (const p of S.data.provinces) if (polysOf(p.geometry).some((poly) => inRing(lon, lat, poly[0]))) return p.id;
    return null;
  };

  // ------------------------------------------------------------------ animation helpers
  const anims = new Map();
  function animate(key, dur, apply, delay = 0) {
    if (REDUCED || dur <= 0) { apply(1); anims.delete(key); return; }
    anims.set(key, { t0: performance.now() + delay, dur, apply });
  }
  function stepAnims(now) {
    for (const [key, a] of anims) {
      const k = clamp((now - a.t0) / a.dur, 0, 1);
      a.apply(ease(k));
      if (k >= 1) anims.delete(key);
    }
  }
  const schedule = (ms, fn) => S.timers.push({ at: performance.now() + (REDUCED ? 0 : ms), fn });
  const followers = [];
  const follow = (obj, lon, lat, off, tag = '') => followers.push({ obj, pid: provinceAt(lon, lat), off, tag });
  const heightOf = (pid) => (pid ? provs.get(pid).group.scale.z : 0);
  const heightAt = (lon, lat) => heightOf(provinceAt(lon, lat));
  function disposeObject(obj) {
    obj.traverse((o) => {
      o.geometry?.dispose?.();
      const mats = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
      mats.forEach((m) => m.dispose?.());
    });
  }
  function clearGroup(group) {
    for (const child of [...group.children]) { group.remove(child); disposeObject(child); }
  }
  const label = (cls, parent, z) => {
    const el = document.createElement('div');
    el.className = `lbl ${cls}`;
    const obj = new CSS2DObject(el);
    obj.position.z = z;
    parent.add(obj);
    return { el, obj };
  };
  const rampColor = (h) => {
    if (h == null) return new THREE.Color(NEUTRAL);
    const v = clamp(h, 12, 24);
    for (let i = 1; i < STOPS.length; i++) {
      if (v <= STOPS[i][0]) {
        const [h0, c0] = STOPS[i - 1]; const [h1, c1] = STOPS[i];
        return new THREE.Color(c0).lerp(new THREE.Color(c1), (v - h0) / (h1 - h0));
      }
    }
    return new THREE.Color(STOPS[STOPS.length - 1][1]);
  };
  const heightFor = (h) => (h == null ? 3 : 2 + clamp((h - 12) / 12, 0, 1) * 7);

  // ------------------------------------------------------------------ provinces
  const provs = new Map();
  const pickables = [];
  function shapeFrom(poly) {
    const v2 = ([x, y]) => { const v = pt(x, y); return new THREE.Vector2(v.x, v.y); };
    const shape = new THREE.Shape(poly[0].slice(0, -1).map(v2));
    for (const hole of poly.slice(1)) shape.holes.push(new THREE.Path(hole.slice(0, -1).map(v2)));
    return shape;
  }
  function buildProvinces(d) {
    for (const p of d.provinces) {
      const group = new THREE.Group();
      group.scale.z = 3;
      const mat = new THREE.MeshStandardMaterial({ color: NEUTRAL, roughness: 0.78, metalness: 0.04 });
      for (const poly of polysOf(p.geometry)) {
        const mesh = new THREE.Mesh(new THREE.ExtrudeGeometry(shapeFrom(poly), { depth: 1, bevelEnabled: false, curveSegments: 1 }), mat);
        mesh.userData = { kind: 'province', id: p.id };
        group.add(mesh);
        pickables.push(mesh);
        const edge = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(poly[0].slice(0, -1).map(([x, y]) => pt(x, y, 1.003))),
          new THREE.LineBasicMaterial({ color: 0xa3aca5, transparent: true, opacity: 0.5 }));
        group.add(edge);
      }
      scene.add(group);
      const pin = new THREE.Mesh(new THREE.SphereGeometry(1.5, 18, 14),
        new THREE.MeshStandardMaterial({ color: 0xf0c96a, emissive: 0xf0c96a, emissiveIntensity: 0.55 }));
      pin.position.copy(pt(p.lon, p.lat));
      pin.userData = { kind: 'province', id: p.id };
      scene.add(pin);
      pickables.push(pin);
      const anchor = new THREE.Object3D();
      anchor.position.copy(pt(p.lon, p.lat));
      scene.add(anchor);
      const lbl = label('', anchor, 0);
      provs.set(p.id, { p, group, mat, pin, anchor, el: lbl.el, dim: 0 });
    }
    for (const o of provs.values()) { follow(o.pin, o.p.lon, o.p.lat, 1.2); follow(o.anchor, o.p.lon, o.p.lat, 4.2); }
  }
  function provinceHours(p, view, month) {
    if (view === 'neutral') return null;
    return month < 0 ? p[view].annual : p[view].monthly[month];
  }
  function paintProvinces(view, month, dur = 900) {
    for (const [id, o] of provs) {
      const h = provinceHours(o.p, view, month);
      const toC = rampColor(h);
      if (o.dim) toC.multiplyScalar(0.4);
      const fromC = o.mat.color.clone();
      const fromH = o.group.scale.z;
      const toH = heightFor(h);
      animate(`prov-${id}`, dur, (k) => { o.mat.color.copy(fromC).lerp(toC, k); o.group.scale.z = fromH + (toH - fromH) * k; });
      o.el.innerHTML = esc(o.p.name) + (h == null ? '' : `<span class="v">${h.toFixed(1)} h</span>`);
      o.el.classList.toggle('dim', !!o.dim);
      o.el.classList.toggle('focus', S.focus === id);
    }
  }

  // ------------------------------------------------------------------ reservoirs
  const dams = new Map();
  function buildDams(d) {
    for (const r of d.reservoirs) {
      const radius = 3 + Math.sqrt(r.capacity) / 9;
      const H = 16;
      const group = new THREE.Group();
      group.position.copy(pt(r.lon, r.lat));
      const glassGeo = new THREE.CylinderGeometry(radius, radius, 1, 48, 1, true);
      glassGeo.rotateX(Math.PI / 2); glassGeo.translate(0, 0, 0.5);
      const glass = new THREE.Mesh(glassGeo, new THREE.MeshStandardMaterial({ color: 0xbcd8ea, transparent: true,
        opacity: 0.17, roughness: 0.1, metalness: 0.1, side: THREE.DoubleSide, depthWrite: false }));
      glass.scale.z = H;
      const ring = new THREE.Mesh(new THREE.TorusGeometry(radius, 0.35, 8, 56),
        new THREE.MeshStandardMaterial({ color: 0x9fb8c8, metalness: 0.45, roughness: 0.3 }));
      ring.position.z = H;
      const waterGeo = new THREE.CylinderGeometry(radius * 0.94, radius * 0.94, 1, 48);
      waterGeo.rotateX(Math.PI / 2); waterGeo.translate(0, 0, 0.5);
      const water = new THREE.Mesh(waterGeo, new THREE.MeshStandardMaterial({ color: 0x3987e5, emissive: 0x0f3460,
        emissiveIntensity: 0.65, roughness: 0.22, transparent: true, opacity: 0.93 }));
      water.scale.z = 0.01;
      glass.userData = water.userData = { kind: 'dam', id: r.id };
      group.add(glass, ring, water);
      scene.add(group);
      pickables.push(glass, water);
      const lbl = label('dam', group, H + 5);
      dams.set(r.id, { r, group, water, H, radius, el: lbl.el, lbl: lbl.obj, fill: 0 });
      follow(group, r.lon, r.lat, 0);
    }
  }
  function damFill(r, view, month) {
    if (view === 'neutral') return r.start;
    return month < 0 ? r[view][11] : r[view][month];
  }
  function setDams(view, month, dur = 900) {
    for (const [id, o] of dams) {
      const to = clamp(damFill(o.r, view, month), 0, 100);
      const from = o.fill;
      animate(`dam-${id}`, dur, (k) => { o.fill = from + (to - from) * k; o.water.scale.z = Math.max(0.01, (o.H * o.fill) / 100); });
      o.el.innerHTML = `${esc(o.r.name)}<span class="v">${to.toFixed(0)}%</span>`;
    }
  }

  // ------------------------------------------------------------------ rivers (animated dotted glow)
  let river = null;
  function buildRivers(d) {
    const positions = []; const meta = [];
    for (const line of d.rivers) {
      const curve = new THREE.CatmullRomCurve3(line.map(([x, y]) => pt(x, y, 0)));
      const n = Math.max(20, Math.round(curve.getLength() / 1.5));
      for (let i = 0; i <= n; i++) {
        const v = curve.getPointAt(i / n);
        positions.push(v.x, v.y, 0);
        const [lon, lat] = toLonLat(v);
        meta.push({ pid: provinceAt(lon, lat), s: i / n });
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(meta.length * 3), 3));
    const mat = new THREE.PointsMaterial({ size: 3.4, sizeAttenuation: false, vertexColors: true, transparent: true,
      opacity: 0.95, depthWrite: false });
    river = { geo, meta, obj: new THREE.Points(geo, mat), reveal: 1 };
    scene.add(river.obj);
  }
  function stepRiver(t) {
    const pos = river.geo.attributes.position; const col = river.geo.attributes.color;
    for (let i = 0; i < river.meta.length; i++) {
      const m = river.meta[i];
      pos.setZ(i, heightOf(m.pid) + 0.7);
      const w = 0.5 + 0.5 * Math.sin(m.s * 46 - t * 3.2);
      col.setXYZ(i, 0.2 + 0.3 * w, 0.5 + 0.3 * w, 0.92);
    }
    pos.needsUpdate = true; col.needsUpdate = true;
    river.geo.setDrawRange(0, Math.floor(river.meta.length * river.reveal));
  }

  // ------------------------------------------------------------------ places: Tadla plain, downstream coast
  const places = new THREE.Group();
  scene.add(places);
  let tadlaLbl = null; let coastLbl = null;
  function buildPlaces(d) {
    const tadla = new THREE.Group();
    tadla.position.copy(pt(d.tadla.lon, d.tadla.lat));
    const disc = new THREE.Mesh(new THREE.RingGeometry(22, 26, 64),
      new THREE.MeshBasicMaterial({ color: 0x8fc96b, transparent: true, opacity: 0.55, side: THREE.DoubleSide }));
    disc.scale.set(1.5, 0.95, 1);
    const fill = new THREE.Mesh(new THREE.CircleGeometry(22, 64),
      new THREE.MeshBasicMaterial({ color: 0x8fc96b, transparent: true, opacity: 0.12, side: THREE.DoubleSide, depthWrite: false }));
    fill.scale.set(1.5, 0.95, 1);
    tadla.add(disc, fill);
    places.add(tadla);
    follow(tadla, d.tadla.lon, d.tadla.lat, 0.25);
    tadlaLbl = label('tag', tadla, 3);
    const coast = new THREE.Group();
    coast.position.copy(pt(d.coast.lon, d.coast.lat, 0));
    const cone = new THREE.Mesh(new THREE.ConeGeometry(4.5, 11, 24), new THREE.MeshStandardMaterial({ color: 0xd95926, emissive: 0x5a2410 }));
    cone.rotation.z = Math.PI / 2;
    cone.position.z = 3;
    const waves = new THREE.Mesh(new THREE.RingGeometry(9, 10.2, 48),
      new THREE.MeshBasicMaterial({ color: 0x6da7ec, transparent: true, opacity: 0.45, side: THREE.DoubleSide }));
    coast.add(cone, waves);
    places.add(coast);
    coastLbl = label('tag', coast, 9);
    coastLbl.obj.position.y = -16;
  }

  // ------------------------------------------------------------------ rain
  let rain = null;
  function buildRain() {
    const N = 2200; const pos = new Float32Array(N * 3); const speed = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      pos[i * 3] = (Math.random() - 0.5) * P.w * 1.05;
      pos[i * 3 + 1] = (Math.random() - 0.5) * P.h * 1.05;
      pos[i * 3 + 2] = 20 + Math.random() * 170;
      speed[i] = 60 + Math.random() * 60;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const obj = new THREE.Points(geo, new THREE.PointsMaterial({ color: 0x9ec5f4, size: 1.8, sizeAttenuation: false,
      transparent: true, opacity: 0.55, depthWrite: false }));
    obj.visible = false;
    scene.add(obj);
    rain = { obj, geo, speed, N };
  }
  function stepRain(dt) {
    if (!rain.obj.visible) return;
    const p = rain.geo.attributes.position;
    for (let i = 0; i < rain.N; i++) {
      let z = p.getZ(i) - rain.speed[i] * dt;
      if (z < 6) z = 190;
      p.setZ(i, z);
    }
    p.needsUpdate = true;
    const mm = S.month >= 0 ? S.data.rainMonthly[S.month] : 0;
    rain.geo.setDrawRange(0, Math.floor(rain.N * clamp(mm / 90, 0.02, 1)));
  }

  // ------------------------------------------------------------------ flows (dams -> towns / Tadla / downstream)
  const flowGroup = new THREE.Group();
  scene.add(flowGroup);
  const flowPick = [];
  const particles = [];
  const particleGeo = new THREE.SphereGeometry(1, 10, 8);
  const placeName = (id) => {
    if (dams.has(id)) return dams.get(id).r.name;
    if (provs.has(id)) return provs.get(id).p.name;
    return { TADLA: S.data.copy.tadla, COAST: S.data.copy.downstream, AQUIFER_TADLA: S.data.copy.aquifer }[id] || id;
  };
  function endpoint(id) {
    if (dams.has(id)) { const o = dams.get(id); return pt(o.r.lon, o.r.lat, heightAt(o.r.lon, o.r.lat) + o.H * (o.fill / 100) + 1); }
    if (id === 'TADLA' || id === 'AQUIFER_TADLA') return pt(S.data.tadla.lon, S.data.tadla.lat, heightAt(S.data.tadla.lon, S.data.tadla.lat) + 1.5);
    if (id === 'COAST') return pt(S.data.coast.lon, S.data.coast.lat, 3);
    const o = provs.get(id);
    return pt(o.p.lon, o.p.lat, o.group.scale.z + 2.5);
  }
  function arc(A, B) {
    const lift = Math.max(16, A.distanceTo(B) * 0.24);
    const top = Math.max(A.z, B.z) + lift;
    const c1 = A.clone().lerp(B, 0.25); c1.z = top;
    const c2 = A.clone().lerp(B, 0.75); c2.z = top;
    return new THREE.CubicBezierCurve3(A, c1, c2, B);
  }
  function buildFlows(view, month) {
    clearGroup(flowGroup); flowPick.length = 0; particles.length = 0;
    if (view === 'neutral') return;
    const yearly = month < 0;
    for (const f of S.data.flows) {
      if (f.source === 'AQUIFER_TADLA' && f.destination === 'TADLA') continue;
      const vol = yearly ? f[view].reduce((a, b) => a + b, 0) : f[view][month];
      const annualised = yearly ? vol : vol * 12;
      if (annualised < 2) continue;
      const curve = arc(endpoint(f.source), endpoint(f.destination));
      const r = clamp(0.55 + Math.sqrt(annualised) * 0.075, 0.55, 4.2);
      const color = f.kind === 'export' ? 0xd95926 : f.source === 'AQUIFER_TADLA' ? 0x199e70 : 0x3987e5;
      const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 56, r, 8, false), new THREE.MeshStandardMaterial({
        color, emissive: color, emissiveIntensity: 0.55, transparent: true, opacity: 0.72, roughness: 0.3, depthWrite: false }));
      const total = tube.geometry.index.count;
      tube.geometry.setDrawRange(0, 0);
      animate(`flow-${f.source}-${f.destination}-${f.kind}`, 1300, (k) => tube.geometry.setDrawRange(0, Math.floor((total * k) / 3) * 3));
      tube.userData = { tip: `${placeName(f.source)} → ${placeName(f.destination)}\n${vol.toFixed(1)} Mm³ · ${yearly ? S.data.copy.year : S.data.months[month]}` };
      flowGroup.add(tube);
      flowPick.push(tube);
      const n = clamp(Math.round(annualised / 45), 2, 10);
      const pm = new THREE.MeshBasicMaterial({ color: f.kind === 'export' ? 0xffc2a3 : 0xd4ecff });
      for (let i = 0; i < n; i++) {
        const s = new THREE.Mesh(particleGeo, pm);
        s.scale.setScalar(r * 1.15);
        flowGroup.add(s);
        particles.push({ s, curve, phase: i / n });
      }
    }
  }
  function stepParticles(t) {
    for (const p of particles) p.s.position.copy(p.curve.getPointAt((t * 0.09 + p.phase) % 1));
  }

  // ------------------------------------------------------------------ solution assets
  const leverGroup = new THREE.Group();
  scene.add(leverGroup);
  const leverUnits = new Map();
  let leverSig = null;
  const mat = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.45, metalness: 0.2, ...extra });
  function nearestDam(lon, lat) {
    let best = null;
    for (const o of dams.values()) {
      const dist = (o.r.lon - lon) ** 2 + (o.r.lat - lat) ** 2;
      if (o.r.inRegion && (!best || dist < best.dist)) best = { o, dist };
    }
    return best.o;
  }
  function unit(list, parent, lon, lat, dx = 0, dy = 0, off = 0) {
    const g = new THREE.Group();
    const base = pt(lon, lat);
    g.position.set(base.x + dx, base.y + dy, 0);
    parent.add(g);
    followers.push({ obj: g, pid: provinceAt(...toLonLat(g.position)), off, tag: 'lever' });
    list.push(g);
    return g;
  }
  function tank(g, color = 0x43c9a2, r = 2.6, h = 7) {
    const body = new THREE.CylinderGeometry(r * 0.92, r, h, 20); body.rotateX(Math.PI / 2); body.translate(0, 0, h / 2);
    const water = new THREE.CylinderGeometry(r * 0.85, r * 0.85, h * 0.45, 20); water.rotateX(Math.PI / 2); water.translate(0, 0, h * 0.25);
    g.add(new THREE.Mesh(body, mat(0xaab9b5, { metalness: 0.55, roughness: 0.32 })),
      new THREE.Mesh(water, mat(color, { emissive: color, emissiveIntensity: 0.45, transparent: true, opacity: 0.9 })));
  }
  function house(g) {
    const home = new THREE.Mesh(new THREE.BoxGeometry(3.6, 3.4, 3), mat(0xd9d2ba, { roughness: 0.85, metalness: 0 }));
    home.position.z = 1.5;
    const roof = new THREE.Mesh(new THREE.ConeGeometry(2.9, 2.2, 4), mat(0xd95926, { roughness: 0.8, metalness: 0 }));
    roof.rotation.x = Math.PI / 2; roof.rotation.y = Math.PI / 4; roof.position.z = 4.1;
    const tap = new THREE.Mesh(new THREE.SphereGeometry(0.7, 10, 8), mat(0x43c9a2, { emissive: 0x199e70, emissiveIntensity: 0.6 }));
    tap.position.set(2.1, -1.9, 1);
    g.add(home, roof, tap);
  }
  function buildAsset(l, holder) {
    const units = [];
    const pipes = [];
    const d = S.data;
    const cities = d.provinces;
    const T = d.tadla;
    const tag = { userData: { lever: l.key } };
    if (l.anchor === 'cities' && l.key === 'storage_autonomy_h') {
      for (const c of cities) tank(unit(units, holder, c.lon, c.lat, -9, 4, 0));
    } else if (l.anchor === 'cities') {
      for (const c of cities) {
        const g = unit(units, holder, c.lon, c.lat, 9, -4, 0);
        const box = new THREE.Mesh(new THREE.BoxGeometry(4.4, 3.2, 1.4), mat(0xe6a94c, { metalness: 0.5 }));
        box.position.z = 0.8;
        const ring = new THREE.Mesh(new THREE.TorusGeometry(3.4, 0.3, 8, 28), new THREE.MeshBasicMaterial({ color: 0xf0c96a }));
        ring.position.z = 2;
        g.add(box, ring);
      }
    } else if (l.anchor === 'homes') {
      for (const c of cities) for (const [dx, dy] of [[-12, -8], [-6, -12], [2, -11]]) house(unit(units, holder, c.lon, c.lat, dx, dy, 0));
    } else if (l.anchor === 'drops') {
      for (const c of cities) {
        for (const dx of [-3.5, 0, 3.5]) {
          const g = unit(units, holder, c.lon, c.lat, dx, 7, 7 + Math.abs(dx) * 0.3);
          const drop = new THREE.Mesh(new THREE.SphereGeometry(1.3, 14, 10), mat(0x43c9a2, { emissive: 0x199e70, emissiveIntensity: 0.5 }));
          drop.scale.set(0.75, 0.75, 1.6);
          g.add(drop);
        }
      }
    } else if (l.anchor === 'pipes_all' || l.anchor === 'pipes_mountain') {
      const targets = l.anchor === 'pipes_all' ? cities : cities.filter((c) => ['KHENIFRA', 'AZILAL', 'BENI_MELLAL'].includes(c.id));
      const color = l.anchor === 'pipes_all' ? 0xf0c96a : 0x6da7ec;
      for (const c of targets) {
        const dam = nearestDam(c.lon, c.lat);
        const A = endpoint(dam.r.id); A.z += 1;
        const B = pt(c.lon, c.lat, provs.get(c.id).group.scale.z + 1.5);
        const side = l.anchor === 'pipes_all' ? -6 : 6;
        const curve = arc(A, B);
        const offset = new THREE.Vector3(-(B.y - A.y), B.x - A.x, 0).normalize().multiplyScalar(side);
        curve.v1.add(offset); curve.v2.add(offset);
        const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 60, l.anchor === 'pipes_all' ? 1.0 : 1.5, 10, false),
          mat(color, { emissive: color, emissiveIntensity: 0.35 }));
        tube.userData = tag.userData;
        holder.add(tube);
        pipes.push(tube);
      }
    } else if (l.anchor === 'tadla_drip') {
      for (let row = 0; row < 4; row++) for (let col = 0; col < 7; col++) {
        const g = unit(units, holder, T.lon, T.lat, (col - 3) * 7.4, (row - 1.5) * 5.2, 0.3);
        const plot = new THREE.Mesh(new THREE.BoxGeometry(6.4, 4, 0.7), mat(0xa6c96b, { emissive: 0x4f7a2e, emissiveIntensity: 0.25, metalness: 0 }));
        const line = new THREE.Mesh(new THREE.BoxGeometry(6.4, 0.3, 0.3), new THREE.MeshBasicMaterial({ color: 0xd4e3a2 }));
        line.position.z = 0.55;
        g.add(plot, line);
      }
    } else if (l.anchor === 'tadla_plant') {
      const g = unit(units, holder, T.lon, T.lat, 30, 16, 0);
      const base = new THREE.Mesh(new THREE.BoxGeometry(22, 13, 1.6), mat(0x426d6a, { metalness: 0 }));
      base.position.z = 0.8;
      g.add(base);
      for (let i = 0; i < 3; i++) {
        const t = new THREE.Group(); t.position.set(-6 + i * 6, 0, 1.6); tank(t, 0x8fd3c0, 2.4, 5); g.add(t);
      }
    } else if (l.anchor === 'tadla_wells') {
      for (const [dx, dy] of [[-26, -10], [-14, 14], [22, -14]]) {
        const g = unit(units, holder, T.lon, T.lat, dx, dy, 0);
        const well = new THREE.CylinderGeometry(1.1, 1.5, 8, 14); well.rotateX(Math.PI / 2); well.translate(0, 0, 4);
        const ring = new THREE.Mesh(new THREE.TorusGeometry(3, 0.4, 8, 24), new THREE.MeshBasicMaterial({ color: 0xa7ddff }));
        ring.position.z = 8.5;
        g.add(new THREE.Mesh(well, mat(0x65b7d6, { metalness: 0.6 })), ring);
      }
    } else if (l.anchor === 'coast') {
      const g = new THREE.Group();
      g.position.copy(pt(d.coast.lon, d.coast.lat, 0));
      g.position.y += 14;
      holder.add(g);
      units.push(g);
      const hall = new THREE.Mesh(new THREE.BoxGeometry(12, 7, 4), mat(0xc3c2b7, { metalness: 0.3 }));
      hall.position.z = 2;
      g.add(hall);
      for (const dx of [-9, 9]) { const t = new THREE.Group(); t.position.set(dx, 0, 0); tank(t, 0x6da7ec, 2.6, 6); g.add(t); }
    }
    for (const u of units) u.traverse((o) => { if (o.isMesh) o.userData = tag.userData; });
    return { units, pipes };
  }
  function rebuildLevers() {
    const sig = S.data.levers.map((l) => `${l.key}:${l.valueLabel}`).join('|');
    if (sig === leverSig) return false;
    leverSig = sig;
    clearGroup(leverGroup);
    leverUnits.clear();
    for (let i = followers.length - 1; i >= 0; i--) if (followers[i].tag === 'lever') followers.splice(i, 1);
    S.data.levers.forEach((l, idx) => {
      const holder = new THREE.Group();
      leverGroup.add(holder);
      const built = buildAsset(l, holder);
      leverUnits.set(l.key, built);
      built.units.forEach((u) => u.scale.setScalar(0.001));
      built.pipes.forEach((p) => p.geometry.setDrawRange(0, 0));
    });
    return true;
  }
  function growLevers(delayStep = 260) {
    S.data.levers.forEach((l, idx) => {
      const built = leverUnits.get(l.key);
      if (!built) return;
      built.units.forEach((u, j) => animate(`lv-${l.key}-${j}`, 800, (k) => u.scale.setScalar(Math.max(0.001, k)), idx * delayStep + j * 35));
      built.pipes.forEach((p, j) => {
        const total = p.geometry.index.count;
        animate(`lvp-${l.key}-${j}`, 1400, (k) => p.geometry.setDrawRange(0, Math.floor((total * k) / 3) * 3), idx * delayStep);
      });
    });
  }
  function pulseLever(t) {
    const cur = S.leverIdx >= 0 ? S.data.levers[S.leverIdx % Math.max(S.data.levers.length, 1)] : null;
    for (const [key, built] of leverUnits) {
      const on = cur && cur.key === key && chapterId() === 'plan';
      for (const u of built.units) if (!anims.has(`lv-${key}-0`)) u.scale.setScalar(on ? 1 + 0.12 * Math.sin(t * 5) : 1);
    }
  }

  // ------------------------------------------------------------------ static copy & UI
  const card = $('.card');
  const narr = $('.narr');
  const monthInput = $('.month');
  function fillStaticCopy(d) {
    const c = d.copy;
    $('.l-service').textContent = c.legend_service;
    $('.l-dam').textContent = c.legend_dam;
    $('.l-flow').textContent = c.legend_flow;
    $('.l-schematic').textContent = c.legend_schematic;
    $('.prev').setAttribute('aria-label', c.prev); $('.prev').title = c.prev;
    $('.next').setAttribute('aria-label', c.next); $('.next').title = c.next;
    const [b, a] = root.querySelectorAll('.seg button');
    b.textContent = c.before; a.textContent = c.after;
    tadlaLbl.el.textContent = c.tadla;
    coastLbl.el.textContent = c.downstream;
    renderDots();
    updatePlayButton();
    updateMonthUI();
  }
  const chapterId = () => S.data.chapters[S.chapter].id;
  function renderNarration(animated = true) {
    const ch = S.data.chapters[S.chapter];
    const write = () => {
      $('.kicker').textContent = S.data.copy.chapter.replace('{i}', S.chapter + 1).replace('{n}', S.data.chapters.length);
      $('.title').textContent = ch.title;
      $('.text').textContent = ch.text;
      $('.stats').innerHTML = ch.stats.map((s) => `<div class="stat ${esc(s.tone)}"><b>${esc(s.value)}</b><span>${esc(s.label)}</span></div>`).join('');
      narr.classList.remove('swap');
    };
    if (!animated || REDUCED) { write(); return; }
    narr.classList.add('swap');
    setTimeout(write, 260);
  }
  function renderDots() {
    const dots = $('.dots');
    if (dots.children.length !== S.data.chapters.length) {
      dots.innerHTML = S.data.chapters.map((c, i) => `<button type="button" role="tab" data-i="${i}"><span class="fill"></span></button>`).join('');
      dots.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => goTo(Number(b.dataset.i))));
    }
    dots.querySelectorAll('button').forEach((b, i) => {
      b.title = S.data.chapters[i].title;
      b.setAttribute('aria-label', S.data.chapters[i].title);
      b.setAttribute('aria-selected', String(i === S.chapter));
      b.classList.toggle('done', i < S.chapter);
      b.classList.toggle('on', i === S.chapter);
      b.querySelector('.fill').style.width = i < S.chapter ? '100%' : '0%';
    });
  }
  function updatePlayButton() {
    const btn = $('.play');
    const last = S.chapter === S.data.chapters.length - 1;
    btn.textContent = S.playing ? '❚❚' : last ? '↺' : '▶';
    const lab = S.playing ? S.data.copy.pause : last ? S.data.copy.replay : S.data.copy.play;
    btn.title = lab; btn.setAttribute('aria-label', lab);
    $('.hint').textContent = S.playing ? '' : S.data.copy.drag;
  }
  function updateMonthUI() {
    monthInput.value = String(S.month);
    const id = chapterId();
    monthInput.disabled = S.playing && id === 'drought';
    const name = S.month < 0 ? S.data.copy.year : S.data.months[S.month];
    $('.month-label').textContent = name;
    const badge = $('.monthbadge');
    badge.classList.toggle('on', S.month >= 0);
    if (S.month >= 0) {
      const year = Number(String(S.data.chapters[1].title).match(/\d{4}/)?.[0] || 0);
      const y = S.month < 4 ? year - 1 : year;
      badge.innerHTML = `<small>${esc(S.view === 'after' && id !== 'drought' ? S.data.copy.after : S.data.copy.before)}</small>${esc(name)} ${y || ''}`;
    }
    root.querySelectorAll('.seg button').forEach((b) => b.classList.toggle('on', b.dataset.view === S.view));
  }

  // ------------------------------------------------------------------ cards
  function showCard(html) { card.innerHTML = html; card.classList.add('on'); }
  function hideCard() { card.classList.remove('on'); S.card = null; }
  function leverCard() {
    const L = S.data.levers;
    const c = S.data.copy;
    if (!L.length) { showCard(`<div class="c-eyebrow">${esc(S.data.chapters[S.chapter].title)}</div><p class="c-build">${esc(c.no_levers_card)}</p>`); return; }
    const i = ((S.leverIdx % L.length) + L.length) % L.length;
    const l = L[i];
    showCard(`<div class="c-eyebrow">${esc(l.icon)} ${esc(l.title)} · ${esc(l.valueLabel)}</div>
      <div class="c-title">${esc(l.component)}</div><div class="c-where">${esc(l.location)}</div>
      <p class="c-build">${esc(l.build)}</p>
      <div class="c-impact"><span>${esc(l.metric)} · ${esc(c.before)}</span><b>${esc(l.before)}</b>
        <span>${esc(c.own_effect)}</span><b class="${l.improves ? 'good' : ''}">${esc(l.own)}</b>
        <span>${esc(c.package)}</span><b>${esc(l.package)}</b></div>
      <div class="c-progress">${L.map((_, j) => `<i class="${j === i ? 'on' : ''}"></i>`).join('')}</div>`);
  }
  function provinceCard(id) {
    const o = provs.get(id); if (!o) return;
    const p = o.p; const c = S.data.copy;
    const row = (lab, b, a, unit = '', dec = 1) => `<span>${esc(lab)}</span><b>${Number(b).toFixed(dec)}${unit} → <span style="color:#43c9a2">${Number(a).toFixed(dec)}${unit}</span></b>`;
    S.card = id;
    showCard(`<div class="c-eyebrow">📍 ${esc(p.capital)}</div><div class="c-title">${esc(p.name)}</div>
      <div class="c-where">${Number(p.population).toLocaleString()} ${esc(c.residents)} · ${p.localShare}% ${esc(c.local_sources)}</div>
      <div class="c-impact">${row(c.hours, p.before.annual, p.after.annual)}${row(c.worst, p.before.worst, p.after.worst, ' h', 0)}
      ${row(c.breakdowns, p.before.breakdown, p.after.breakdown)}<span>${esc(c.no_tap)}</span><b>${Math.round(p.before.noTap / 1000)}k → <span style="color:#43c9a2">${Math.round(p.after.noTap / 1000)}k</span></b></div>`);
  }

  // ------------------------------------------------------------------ chapters
  function viewFor(id) {
    if (id === 'basin') return 'neutral';
    if (id === 'change') return 'after';
    if (id === 'explore') return S.view;
    return 'before';
  }
  function preset(id) {
    const fit = fitDistance();
    const overview = { target: new THREE.Vector3(-P.w * 0.22, -P.h * 0.08, 0), dist: fit * 1.04, dir: new THREE.Vector3(0.05, -0.66, 0.75) };
    if (id === 'who') {
      const p = provs.get(S.data.worst).p;
      return { target: pt(p.lon, p.lat, 4).add(new THREE.Vector3(-P.w * 0.1, P.h * 0.02, 0)), dist: fit * 0.62, dir: new THREE.Vector3(0.3, -0.62, 0.73) };
    }
    if (id === 'flows') return { target: new THREE.Vector3(-P.w * 0.42, -P.h * 0.06, 0), dist: fit * 1.18, dir: new THREE.Vector3(-0.12, -0.68, 0.72) };
    if (id === 'plan') return { target: new THREE.Vector3(-P.w * 0.08, P.h * 0.06, 0), dist: fit * 0.92, dir: new THREE.Vector3(0.1, -0.64, 0.76) };
    if (id === 'drought') return { ...overview, dir: new THREE.Vector3(-0.25, -0.6, 0.76) };
    return overview;
  }
  function fitDistance() {
    const aspect = Math.max(stage.clientWidth, 1) / Math.max(stage.clientHeight, 1);
    const half = THREE.MathUtils.degToRad(camera.fov / 2);
    return clamp(Math.max((P.h * 0.44) / Math.tan(half), (P.w * 0.43) / (Math.tan(half) * aspect)), 300, 1100);
  }
  function flyTo(pr, dur = 2300) {
    const fromP = camera.position.clone(); const fromT = controls.target.clone();
    const toT = pr.target.clone();
    const toP = toT.clone().add(pr.dir.clone().normalize().multiplyScalar(pr.dist));
    animate('camera', dur, (k) => { controls.target.copy(fromT).lerp(toT, k); camera.position.copy(fromP).lerp(toP, k); });
  }
  function applyVisuals(id, dur) {
    const view = viewFor(id);
    S.focus = id === 'who' ? S.data.worst : null;
    for (const [pid, o] of provs) o.dim = id === 'who' && pid !== S.data.worst ? 1 : 0;
    paintProvinces(view, S.month, dur);
    setDams(view, S.month, dur);
    flowGroup.visible = ['flows', 'change', 'explore'].includes(id);
    if (flowGroup.visible) buildFlows(view, S.month); else clearGroup(flowGroup);
    leverGroup.visible = ['plan', 'change', 'explore'].includes(id);
    places.children[1].visible = ['flows', 'change', 'explore'].includes(id);
    tadlaLbl.obj.visible = ['flows', 'plan'].includes(id);
    // CSS2DRenderer rewrites element.style.display every frame: toggle the label objects instead
    for (const o of dams.values()) o.lbl.visible = !(id === 'basin' || id === 'who');
    rain.obj.visible = (id === 'drought' || id === 'explore') && S.month >= 0;
    $('.seg').style.visibility = ['change', 'explore'].includes(id) ? 'visible' : 'hidden';
    controls.autoRotate = id === 'drought' && S.playing && !REDUCED;
    if (id === 'plan') { if (S.leverIdx < 0) S.leverIdx = 0; leverCard(); }
    else if (S.card && provs.has(S.card)) provinceCard(S.card);
    else hideCard();
    updateMonthUI();
  }
  function goTo(i, { fly = true } = {}) {
    const n = S.data.chapters.length;
    S.chapter = clamp(i, 0, n - 1);
    S.chapterT0 = performance.now();
    S.pausedAt = 0;
    S.timers = [];
    S.leverIdx = -1;
    S.lastMonthStep = -2;
    S.card = null;
    const id = chapterId();
    if (id === 'drought') S.month = S.playing ? 0 : (S.month < 0 ? 0 : S.month);
    else if (id !== 'explore') S.month = -1;
    if (id === 'change') {
      S.view = 'after';
      applyVisuals('flows', 600);
      paintProvinces('before', -1, 600);
      schedule(1700, () => { if (chapterId() === 'change') applyVisuals('change', 2600); });
    } else {
      if (id === 'explore' && S.chapter === n - 1 && S.view !== 'before') S.view = 'after';
      applyVisuals(id, 1100);
    }
    if (id === 'basin') { river.reveal = 0; animate('river', 3600, (k) => { river.reveal = k; }, 400); }
    if (id === 'plan' || (id === 'change' && leverUnits.size)) growLevers(id === 'plan' ? 420 : 120);
    if (fly) flyTo(preset(id));
    if (id === 'explore') S.playing = false;
    renderNarration(true);
    renderDots();
    updatePlayButton();
    persist();
  }
  function chapterDuration(id) {
    if (id === 'plan') return Math.max(5200, LEVER_STEP * Math.max(S.data.levers.length, 1) + 1200);
    return DURATIONS[id] || null;
  }
  function stepStory(now) {
    for (let i = S.timers.length - 1; i >= 0; i--) if (now >= S.timers[i].at) { const t = S.timers.splice(i, 1)[0]; t.fn(); }
    if (!S.playing) return;
    const id = chapterId();
    const elapsed = now - S.chapterT0;
    if (id === 'drought') {
      const m = clamp(Math.floor((elapsed - 1300) / 1200), 0, 11);
      if (elapsed > 1300 && m !== S.lastMonthStep) {
        S.lastMonthStep = m; S.month = m;
        paintProvinces('before', m, 950); setDams('before', m, 950);
        rain.obj.visible = true;
        updateMonthUI();
      }
    }
    if (id === 'plan' && S.data.levers.length) {
      const idx = Math.floor(Math.max(0, elapsed - 900) / LEVER_STEP);
      if (idx !== S.leverIdx && idx < S.data.levers.length) { S.leverIdx = idx; leverCard(); }
    }
    const dur = chapterDuration(id);
    const fill = root.querySelector(`.dots button[data-i="${S.chapter}"] .fill`);
    if (fill && dur) fill.style.width = `${clamp((elapsed / dur) * 100, 0, 100)}%`;
    if (dur && elapsed >= dur) goTo(S.chapter + 1);
  }
  function setPlaying(on) {
    const now = performance.now();
    if (on && S.chapter === S.data.chapters.length - 1) { S.playing = true; goTo(0); return; }
    if (on && !S.playing) S.chapterT0 = now - (S.pausedAt || 0);
    if (!on && S.playing) S.pausedAt = now - S.chapterT0;
    S.playing = on;
    controls.autoRotate = on && chapterId() === 'drought' && !REDUCED;
    updatePlayButton();
    updateMonthUI();
  }

  // ------------------------------------------------------------------ interaction
  $('.play').addEventListener('click', () => setPlaying(!S.playing));
  $('.prev').addEventListener('click', () => goTo(S.chapter - 1));
  $('.next').addEventListener('click', () => goTo(S.chapter + 1));
  root.querySelectorAll('.seg button').forEach((b) => b.addEventListener('click', () => {
    S.view = b.dataset.view;
    persist();
    applyVisuals(chapterId() === 'change' ? 'explore' : chapterId(), 900);
  }));
  monthInput.addEventListener('input', () => {
    if (S.playing) setPlaying(false);
    S.month = Number(monthInput.value);
    const id = chapterId();
    const view = viewFor(id) === 'neutral' ? 'before' : viewFor(id);
    paintProvinces(view, S.month, 450); setDams(view, S.month, 450);
    if (flowGroup.visible) buildFlows(view, S.month);
    rain.obj.visible = (id === 'drought' || id === 'explore') && S.month >= 0;
    updateMonthUI();
  });
  root.addEventListener('keydown', (e) => {
    if (e.target === monthInput) return;
    if (e.key === 'ArrowRight') { goTo(S.chapter + 1); e.preventDefault(); }
    if (e.key === 'ArrowLeft') { goTo(S.chapter - 1); e.preventDefault(); }
    if (e.key === ' ') { setPlaying(!S.playing); e.preventDefault(); }
  });
  controls.addEventListener('start', () => {
    anims.delete('camera');
    if (S.playing) setPlaying(false);
  });
  const tooltip = $('.tooltip');
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let hoverQueued = null;
  function pick(ev) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const objs = [...pickables, ...(flowGroup.visible ? flowPick : []), ...(leverGroup.visible ? leverGroup.children : [])];
    return { hit: raycaster.intersectObjects(objs, true)[0], rect };
  }
  function tipFor(obj) {
    const u = obj.userData || {};
    const c = S.data.copy;
    const view = viewFor(chapterId()) === 'neutral' ? 'before' : viewFor(chapterId());
    if (u.kind === 'province') {
      const p = provs.get(u.id).p;
      return `${p.name} · ${p.capital}\n${c.before}: ${p.before.annual.toFixed(1)} ${c.hours}\n${c.after}: ${p.after.annual.toFixed(1)} ${c.hours}`;
    }
    if (u.kind === 'dam') {
      const o = dams.get(u.id);
      return `${o.r.name}${o.r.inRegion ? '' : ` (${c.outside})`}\n${c.legend_dam}: ${o.fill.toFixed(0)}% · ${view === 'after' ? c.after : c.before}`;
    }
    if (u.tip) return u.tip;
    if (u.lever) { const l = S.data.levers.find((x) => x.key === u.lever); return l ? `${l.icon} ${l.component}\n${l.location}` : ''; }
    return '';
  }
  renderer.domElement.addEventListener('pointermove', (ev) => {
    if (hoverQueued) return;
    hoverQueued = requestAnimationFrame(() => {
      hoverQueued = null;
      const { hit, rect } = pick(ev);
      const text = hit ? tipFor(hit.object) : '';
      if (text) {
        tooltip.textContent = text;
        tooltip.style.display = 'block';
        tooltip.style.left = `${clamp(ev.clientX - rect.left + 14, 8, rect.width - 270)}px`;
        tooltip.style.top = `${clamp(ev.clientY - rect.top + 14, 8, rect.height - 90)}px`;
      } else tooltip.style.display = 'none';
    });
  });
  renderer.domElement.addEventListener('pointerleave', () => { tooltip.style.display = 'none'; });
  renderer.domElement.addEventListener('click', (ev) => {
    const { hit } = pick(ev);
    const u = hit?.object?.userData || {};
    if (u.kind === 'province') { if (S.playing) setPlaying(false); provinceCard(u.id); }
    else if (u.lever && chapterId() !== 'plan') {
      const i = S.data.levers.findIndex((l) => l.key === u.lever);
      if (i >= 0) { S.leverIdx = i; leverCard(); }
    } else if (!hit && chapterId() !== 'plan') hideCard();
  });

  // ------------------------------------------------------------------ lifecycle
  function resize() {
    const w = Math.max(root.clientWidth, 1); const h = Math.max(root.clientHeight, 1);
    renderer.setSize(w, h, false);
    labelRenderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(root);
  const io = new IntersectionObserver((entries) => { S.visible = entries.some((e) => e.isIntersecting); });
  io.observe(root);
  let raf = 0; let last = performance.now();
  const t0 = performance.now();
  function loop(now) {
    raf = requestAnimationFrame(loop);
    if (!S.visible || document.hidden) { last = now; return; }
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    const t = (now - t0) / 1000;
    stepStory(now);
    stepAnims(now);
    for (const f of followers) f.obj.position.z = heightOf(f.pid) + f.off;
    stepRiver(t);
    stepParticles(t);
    stepRain(dt);
    pulseLever(t);
    controls.update();
    renderer.render(scene, camera);
    labelRenderer.render(scene, camera);
  }

  function update(d) {
    if (!d || d.hash === S.hash) return;
    const first = !S.data;
    S.hash = d.hash;
    S.data = d;
    if (first) {
      setupProjection(d);
      buildProvinces(d);
      buildDams(d);
      buildRivers(d);
      buildPlaces(d);
      buildRain();
      rebuildLevers();
      fillStaticCopy(d);
      resize();
      S.chapter = clamp(S.chapter, 0, d.chapters.length - 1);
      const startAt = S.chapter;
      const pr = preset(chapterId());
      camera.position.copy(pr.target.clone().add(pr.dir.clone().normalize().multiplyScalar(pr.dist * 1.35)));
      controls.target.copy(pr.target);
      goTo(startAt);
      root.querySelector('.loading').classList.add('gone');
      raf = requestAnimationFrame(loop);
      return;
    }
    // new scenario or solutions: keep the chapter, animate everything to the new numbers.
    // Scene objects keep references to their data rows - point them at the new rows first.
    for (const p of d.provinces) if (provs.has(p.id)) provs.get(p.id).p = p;
    for (const r of d.reservoirs) if (dams.has(r.id)) dams.get(r.id).r = r;
    fillStaticCopy(d);
    const changedLevers = rebuildLevers();
    const id = chapterId();
    renderNarration(false);
    applyVisuals(id, 900);
    if (changedLevers && ['plan', 'change', 'explore'].includes(id)) growLevers(120);
    if (id === 'plan') { S.leverIdx = Math.max(0, Math.min(S.leverIdx, d.levers.length - 1)); leverCard(); }
  }

  function dispose() {
    S.disposed = true;
    cancelAnimationFrame(raf);
    ro.disconnect(); io.disconnect();
    controls.dispose();
    disposeObject(scene);
    renderer.dispose();
    renderer.domElement.remove();
    labelRenderer.domElement.remove();
  }

  return { update, dispose };
}

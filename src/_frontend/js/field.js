/* Shared WebGL particle field for the homepage and dashboard.
   Particles morph between named shapes; the first is the GitHub mark sampled from its SVG path.
   Pages drive it through window.AgentField: set `progress` (index into the sequence, fractional = mid-morph),
   `energy` (0–1, drift and spin) and `error` (0/1, tints part of the field red).
   Plain WebGL, no libraries: the dashboard server's CSP only allows same-origin scripts. */
(() => {
  'use strict';
  const GITHUB_MARK = 'M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const field = window.AgentField = { progress: 0, energy: .15, error: 0, offsetX: 0, scale: 1 };
  const canvas = document.getElementById('gl');
  if (!canvas) return;
  const gl = canvas.getContext('webgl', { antialias: true, alpha: true, premultipliedAlpha: false });
  if (!gl) { canvas.remove(); return; }

  const N = innerWidth < 700 ? 9000 : 20000;
  const rnd = new Float32Array(N);
  for (let i = 0; i < N; i++) rnd[i] = Math.random();

  function logo() {
    const S = 240, c = document.createElement('canvas'); c.width = c.height = S;
    const x = c.getContext('2d'); x.scale(S / 24, S / 24); x.fill(new Path2D(GITHUB_MARK));
    const px = x.getImageData(0, 0, S, S).data, filled = [];
    for (let y = 0; y < S; y++) for (let xx = 0; xx < S; xx++) if (px[(y * S + xx) * 4 + 3] > 128) filled.push(xx, y);
    const out = new Float32Array(N * 3), n = filled.length / 2;
    for (let i = 0; i < N; i++) {
      const j = Math.floor(Math.random() * n) * 2;
      out.set([(filled[j] / S - .5) * 7.2 + (Math.random() - .5) * .03, -(filled[j + 1] / S - .5) * 7.2 + (Math.random() - .5) * .03, (Math.random() - .5) * .5], i * 3);
    }
    return out;
  }
  const gen = {
    logo,
    sphere: (i, t, r) => { const phi = Math.acos(1 - 2 * t), th = Math.PI * (1 + Math.sqrt(5)) * i, R = 3.2 + (Math.random() - .5) * .25; return [R * Math.sin(phi) * Math.cos(th), R * Math.sin(phi) * Math.sin(th), R * Math.cos(phi)]; },
    grid: (i, t, r) => { const cols = 70, cx = i % cols, cy = Math.floor(i / cols) % 40; return [(cx / cols - .5) * 12, (cy / 40 - .5) * 7, Math.sin(cx * .35) * Math.cos(cy * .3) * .7 + (r - .5) * .3]; },
    helix: (i, t, r) => { const a = t * Math.PI * 14 + (i % 3) * 2.094; return [Math.cos(a) * 1.7 + (r - .5) * .2, (t - .5) * 10, Math.sin(a) * 1.7 + (Math.random() - .5) * .2]; },
    ribbon: (i, t, r) => { const u = t * Math.PI * 6; return [(t - .5) * 14, Math.sin(u) * 1.2 + (r - .5) * .9, Math.cos(u * .5) * 1.5 + (Math.random() - .5) * .6]; },
    knot: (i, t, r) => { const k = t * Math.PI * 6, rr = 2 + Math.cos(k); return [rr * Math.cos(2 * k / 3) * 1.1 + (r - .5) * .35, rr * Math.sin(2 * k / 3) * 1.1 + (Math.random() - .5) * .35, -Math.sin(k) * 1.4]; },
  };
  const names = (canvas.dataset.shapes || 'logo,sphere,helix,grid,knot').split(',').map(s => s.trim());
  const shapes = names.map(name => {
    if (name === 'logo') return logo();
    const out = new Float32Array(N * 3), g = gen[name] || gen.sphere;
    for (let i = 0; i < N; i++) out.set(g(i, i / N, rnd[i]), i * 3);
    return out;
  });
  field.names = names;

  const vs = `
    attribute vec3 aFrom; attribute vec3 aTo; attribute float aRnd;
    uniform float uTime, uMix, uPx, uEnergy, uAspect, uZ, uOffset, uBoost; uniform vec2 uMouse; uniform mat3 uRot;
    varying float vR; varying float vDepth;
    vec3 drift(vec3 p){ return vec3(sin(p.y*1.3+uTime*.6), sin(p.z*1.1+uTime*.5), sin(p.x*1.2+uTime*.7)); }
    void main(){
      float d = clamp((uMix - aRnd*.35)/.65, 0., 1.);
      float e = d*d*(3.-2.*d);
      vec3 p = mix(aFrom, aTo, e);
      p += drift(p*.6 + aRnd*6.) * (.03 + uEnergy*.22 + sin(e*3.1416)*.9);
      p = uRot * p;
      vec2 m = uMouse*vec2(6.,4.) - vec2(uOffset, 0.);
      p.xy += normalize(p.xy - m + 1e-4) * smoothstep(2.2, 0., length(p.xy - m)) * .7;
      p.x += uOffset;
      float z = uZ - p.z;
      float f = 1.0 / tan(radians(27.5));
      gl_Position = vec4(p.x*f/uAspect, p.y*f, (z-.1)/100., z);
      gl_PointSize = (1.4 + aRnd*2.6) * uPx * (9./z) * (1. + uBoost*.35);
      vR = aRnd; vDepth = clamp((z-5.)/8., 0., 1.);
    }`;
  const fs = `
    precision mediump float;
    uniform vec3 uA, uB, uC, uErr; uniform float uError;
    varying float vR; varying float vDepth;
    void main(){
      float d = length(gl_PointCoord-.5); if(d>.5) discard;
      vec3 col = mix(mix(uA,uB,smoothstep(.0,.6,vR)), uC, smoothstep(.85,1.,vR));
      col = mix(col, uErr, uError*step(.7, vR));
      gl_FragColor = vec4(col, smoothstep(.5,0.,d)*(.85-vDepth*.6));
    }`;
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) console.error(gl.getShaderInfoLog(s)); return s; };
  const prog = gl.createProgram();
  gl.attachShader(prog, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(prog); gl.useProgram(prog);
  const buf = (data, name, size) => {
    const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
    const loc = gl.getAttribLocation(prog, name); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
    return b;
  };
  const bFrom = buf(shapes[0], 'aFrom', 3), bTo = buf(shapes[Math.min(1, shapes.length - 1)], 'aTo', 3); buf(rnd, 'aRnd', 1);
  const U = n => gl.getUniformLocation(prog, n);
  const u = Object.fromEntries(['uTime', 'uMix', 'uPx', 'uEnergy', 'uAspect', 'uMouse', 'uRot', 'uZ', 'uError', 'uOffset', 'uBoost'].map(n => [n, U(n)]));
  gl.uniform3f(U('uA'), .388, .4, .945); gl.uniform3f(U('uB'), .22, .741, .973); gl.uniform3f(U('uC'), .063, .725, .506); gl.uniform3f(U('uErr'), .957, .247, .369);
  gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE); gl.disable(gl.DEPTH_TEST);

  let px = 1;
  const resize = () => { px = Math.min(devicePixelRatio || 1, 2); canvas.width = canvas.clientWidth * px; canvas.height = canvas.clientHeight * px; gl.viewport(0, 0, canvas.width, canvas.height); };
  addEventListener('resize', resize); resize();
  const mouse = [9, 9], mEase = [9, 9];
  addEventListener('pointermove', e => { const r = canvas.getBoundingClientRect(); mouse[0] = (e.clientX - r.left) / r.width * 2 - 1; mouse[1] = -((e.clientY - r.top) / r.height * 2 - 1); });

  // Intro: the field starts scattered and assembles into the first shape.
  let intro = reduce ? 1 : 0;
  const scatter = new Float32Array(N * 3).map(() => (Math.random() - .5) * 26);
  let seg = -2, eased = field.progress, energy = field.energy, errEased = 0, spin = 0, last = performance.now();
  const t0 = last;
  function frame(now) {
    const dt = Math.min((now - last) / 1000, .05); last = now;
    const t = reduce ? 0 : (now - t0) / 1000;
    const maxP = shapes.length - 1;
    eased += (Math.min(Math.max(field.progress, 0), maxP) - eased) * (reduce ? 1 : Math.min(dt * 4, 1));
    energy += (field.energy - energy) * .03; errEased += (field.error - errEased) * .05;
    let from, to, mixv, k;
    if (intro < 1) {
      intro = Math.min(intro + dt / 2.2, 1);
      k = -1; from = scatter; to = shapes[0]; mixv = intro;
    } else {
      k = Math.min(Math.floor(eased), Math.max(maxP - 1, 0)); from = shapes[k]; to = shapes[Math.min(k + 1, maxP)]; mixv = eased - k;
    }
    if (k !== seg) {
      seg = k;
      gl.bindBuffer(gl.ARRAY_BUFFER, bFrom); gl.bufferData(gl.ARRAY_BUFFER, from, gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, bTo); gl.bufferData(gl.ARRAY_BUFFER, to, gl.DYNAMIC_DRAW);
    }
    mEase[0] += (mouse[0] - mEase[0]) * .06; mEase[1] += (mouse[1] - mEase[1]) * .06;
    // The logo holds still facing the viewer; other shapes turn.
    const logoHold = names[0] === 'logo' ? Math.max(0, 1 - eased) : 0;
    if (!reduce) spin += dt * (.04 + energy * .25) * (1 - logoHold);
    const ry = spin * (1 - logoHold) + eased * .9 + Math.sin(t * .5) * .12 * logoHold, rx = Math.sin(eased * 1.3) * .25 + Math.sin(t * .4) * .06 * logoHold;
    const cy = Math.cos(ry), sy = Math.sin(ry), cx = Math.cos(rx), sx = Math.sin(rx);
    gl.uniformMatrix3fv(u.uRot, false, [cy, sx * sy, -cx * sy, 0, cx, sx, sy, -sx * cy, cx * cy]);
    gl.uniform1f(u.uTime, t); gl.uniform1f(u.uMix, mixv); gl.uniform1f(u.uPx, px); gl.uniform1f(u.uEnergy, energy);
    gl.uniform1f(u.uAspect, canvas.clientWidth / Math.max(canvas.clientHeight, 1)); gl.uniform2f(u.uMouse, mEase[0], mEase[1]);
    gl.uniform1f(u.uZ, (9 - Math.sin(Math.min(eased / Math.max(maxP, 1), 1) * Math.PI) * 1.5) / field.scale);
    gl.uniform1f(u.uError, errEased); gl.uniform1f(u.uBoost, logoHold); gl.uniform1f(u.uOffset, field.offsetX);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.POINTS, 0, N);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();

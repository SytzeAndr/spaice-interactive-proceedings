// Interactive figures and tables. Each widget is render(el, ctx) and owns its element.
// Everything is computed in the browser from the paper's own definitions or table values;
// toy data is labelled as such.

const NS = "http://www.w3.org/2000/svg";
const cssv = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const col = () => ({ s1: cssv("--s1"), s2: cssv("--s2"), s3: cssv("--s3"), ink: cssv("--ink"), ink2: cssv("--ink-2"), ink3: cssv("--ink-3"),
  rule: cssv("--rule"), grid: cssv("--grid"), sheet: cssv("--sheet"), act: cssv("--act"), add: cssv("--add") });
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const fmt = (v, d = 3) => String(+(Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(d)));
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function onTheme(fn) {
  document.addEventListener("themechange", fn);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", fn);
}
function svg(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  parent?.append(e);
  return e;
}
function canvas(parent, aspect = 1) {
  const c = document.createElement("canvas");
  parent.append(c);
  const fit = () => {
    const w = c.clientWidth || parent.clientWidth || 300, dpr = devicePixelRatio || 1;
    c.width = Math.round(w * dpr); c.height = Math.round(w * aspect * dpr);
    c.style.height = `${w * aspect}px`;
    const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { g, w, h: w * aspect };
  };
  return { c, fit };
}
function tipFor(host) {
  host.classList.add("rel");
  const t = document.createElement("div"); t.className = "tip"; t.hidden = true; host.append(t);
  return {
    show(html, x, y) { t.innerHTML = html; t.hidden = false; const w = host.clientWidth; t.style.left = `${Math.min(Math.max(0, x + 12), w - t.offsetWidth - 4)}px`; t.style.top = `${Math.max(0, y - t.offsetHeight - 10)}px`; },
    hide() { t.hidden = true; },
  };
}

/* ---------- sequences ---------- */
const PRIMES = [2, 3, 5, 7, 11, 13, 17, 19];
function vdc(i, b) { let f = 1, r = 0; while (i > 0) { f /= b; r += f * (i % b); i = Math.floor(i / b); } return r; }
const halton = (i, d) => Array.from({ length: d }, (_, k) => vdc(i, PRIMES[k]));
function sobol2(n) { // first two Sobol dimensions (Gray-code construction), skipping the origin
  const out = []; let x = 0, y = 0;
  const v1 = [], v2 = [];
  for (let k = 0; k < 32; k++) { v1[k] = 2 ** (31 - k); v2[k] = k === 0 ? 2 ** 31 : (v2[k - 1] ^ (v2[k - 1] >>> 1)) >>> 0; }
  for (let i = 1; i <= n; i++) {
    let c = 0, m = i - 1; while (m & 1) { m >>= 1; c++; }
    x = (x ^ v1[c]) >>> 0; y = (y ^ v2[c]) >>> 0;
    out.push([x / 2 ** 32, y / 2 ** 32]);
  }
  return out;
}
function rng(seed) { return () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
function l2star(pts) { // Warnock's formula for the L2-star discrepancy in [0,1]^d
  const n = pts.length, d = pts[0].length;
  let a = 0, b = 0;
  for (const p of pts) a += p.reduce((s, x) => s * (1 - x * x), 1);
  for (const p of pts) for (const q of pts) { let s = 1; for (let k = 0; k < d; k++) s *= 1 - Math.max(p[k], q[k]); b += s; }
  return Math.sqrt(3 ** -d - (2 ** (1 - d) / n) * a + b / (n * n));
}
function montgomery(n, d, base = "halton") { // Algorithm 2, verbatim
  const out = []; let i = 0;
  const sob = base === "sobol" && d === 3 ? sobol2(n * 40) : null;
  while (out.length < n && i < n * 1000) {
    const x = sob ? sob[i] : halton(i + 1, d - 1);
    const s = 1 - x.reduce((a, b) => a + b, 0);
    if (s >= 0) out.push([...x, s]);
    i++;
  }
  return out;
}
const FACE = { yaw: Math.PI / 4, pitch: Math.atan(1 / Math.SQRT2) };
const normalize = (p) => { const s = p.reduce((a, b) => a + b, 0); return p.map((x) => x / s); };

/* ---------- tiny SVG chart frame ---------- */
function frame(host, { w = 560, h = 300, m = { t: 14, r: 14, b: 40, l: 52 }, x, y, xlabel, ylabel }) {
  const s = svg("svg", { viewBox: `0 0 ${w} ${h}`, role: "img" });
  host.append(s);
  const sc = (ax, a, b) => ax.log ? (v) => a + (Math.log10(v) - Math.log10(ax.domain[0])) / (Math.log10(ax.domain[1]) - Math.log10(ax.domain[0])) * (b - a)
                                  : (v) => a + (v - ax.domain[0]) / (ax.domain[1] - ax.domain[0]) * (b - a);
  const sx = sc(x, m.l, w - m.r), sy = sc(y, h - m.b, m.t);
  const g = svg("g", { class: "axis" }, s);
  const ticks = (ax) => ax.ticks || (ax.log ? [] : niceTicks(ax.domain[0], ax.domain[1], 5));
  for (const t of ticks(y)) {
    svg("line", { x1: m.l, x2: w - m.r, y1: sy(t), y2: sy(t), class: "gridl" }, g);
    svg("text", { x: m.l - 6, y: sy(t) + 4, "text-anchor": "end", "font-size": 11 }, g).textContent = y.tf ? y.tf(t) : fmt(t);
  }
  for (const t of ticks(x)) {
    svg("line", { x1: sx(t), x2: sx(t), y1: h - m.b, y2: h - m.b + 4 }, g);
    svg("text", { x: sx(t), y: h - m.b + 16, "text-anchor": "middle", "font-size": 11 }, g).textContent = x.tf ? x.tf(t) : fmt(t);
  }
  svg("line", { x1: m.l, x2: w - m.r, y1: h - m.b, y2: h - m.b }, g);
  if (xlabel) svg("text", { x: (m.l + w - m.r) / 2, y: h - 6, "text-anchor": "middle", "font-size": 11.5 }, g).textContent = xlabel;
  if (ylabel) svg("text", { x: 12, y: (m.t + h - m.b) / 2, "text-anchor": "middle", "font-size": 11.5, transform: `rotate(-90 12 ${(m.t + h - m.b) / 2})` }, g).textContent = ylabel;
  return { s, sx, sy, w, h, m, plot: svg("g", {}, s) };
}
function niceTicks(a, b, n) {
  const step0 = (b - a) / n, mag = 10 ** Math.floor(Math.log10(step0)), r = step0 / mag;
  const step = (r < 1.5 ? 1 : r < 3 ? 2 : r < 7 ? 5 : 10) * mag, out = [];
  for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
const legend = (items) => `<div class="legend">${items.map(([c, l, dash]) => `<span class="${dash ? "dash" : ""}" style="--c:${c}">${l}</span>`).join("")}</div>`;
function marker(parent, shape, x, y, r, fill, stroke) {
  if (shape === "square") return svg("rect", { x: x - r, y: y - r, width: 2 * r, height: 2 * r, rx: 2, fill, stroke, "stroke-width": 2 }, parent);
  if (shape === "diamond") return svg("path", { d: `M${x} ${y - r * 1.3}L${x + r * 1.3} ${y}L${x} ${y + r * 1.3}L${x - r * 1.3} ${y}Z`, fill, stroke, "stroke-width": 2 }, parent);
  return svg("circle", { cx: x, cy: y, r, fill, stroke, "stroke-width": 2 }, parent);
}

/* ======================= Figure 1: low-discrepancy vs uniform ======================= */
function sampling2d(el) {
  el.innerHTML = `<div class="controls">
      <label>Points <input type="range" min="10" max="2000" step="10" value="1000" aria-label="Number of points"> <b class="nv">1000</b></label>
      <button type="button" class="btn play">Play</button>
      <button type="button" class="btn quiet gaps" aria-pressed="false">Show empty cells</button>
      <button type="button" class="btn quiet redraw">New random draw</button>
    </div><div class="grid3"></div>
    <p class="readout">Same axes as the original (Distr2 0–40, Clients_N 0–1500). With “Show empty cells”, the plot is cut into a 20 × 20 grid and cells with no point are shaded: random sampling leaves far more holes.</p>`;
  const N = 2000;
  let seed = 7;
  const seqs = {
    Sobol: sobol2(N),
    Halton: Array.from({ length: N }, (_, i) => halton(i + 1, 2)),
    Uniform: null,
  };
  const draw = () => { const r = rng(seed); seqs.Uniform = Array.from({ length: N }, () => [r(), r()]); };
  draw();
  const cells = Object.keys(seqs).map((name) => {
    const d = document.createElement("div"); d.className = "cell";
    d.innerHTML = `<h5>${name.toLowerCase()} <span></span></h5>`;
    el.querySelector(".grid3").append(d);
    return { name, d, cv: canvas(d, 0.9), info: d.querySelector("span") };
  });
  let n = 1000, gaps = false;
  const render = () => {
    const C = col();
    for (const { name, cv, info } of cells) {
      const { g, w, h } = cv.fit();
      const L = 34, B = 20, T = 4, R = 6, pw = w - L - R, ph = h - B - T;
      g.clearRect(0, 0, w, h);
      g.font = "10px system-ui"; g.fillStyle = C.ink3; g.strokeStyle = C.grid;
      for (const v of [0, 500, 1000, 1500]) { const y = T + ph - (v / 1500) * ph; g.beginPath(); g.moveTo(L, y); g.lineTo(L + pw, y); g.stroke(); g.textAlign = "right"; g.fillText(v, L - 4, y + 3); }
      for (const v of [0, 10, 20, 30, 40]) { g.textAlign = "center"; g.fillText(v, L + (v / 40) * pw, h - 6); }
      const pts = seqs[name].slice(0, n);
      let empty = 0;
      if (gaps) {
        const K = 20, occ = new Uint8Array(K * K);
        for (const [x, y] of pts) occ[Math.min(K - 1, Math.floor(x * K)) * K + Math.min(K - 1, Math.floor(y * K))] = 1;
        g.fillStyle = C.s2; g.globalAlpha = 0.22;
        for (let i = 0; i < K; i++) for (let j = 0; j < K; j++) if (!occ[i * K + j]) { empty++; g.fillRect(L + (i / K) * pw, T + ph - ((j + 1) / K) * ph, pw / K, ph / K); }
        g.globalAlpha = 1;
      }
      g.fillStyle = C.s1;
      const r = n > 1200 ? 1.3 : n > 400 ? 1.7 : 2.4;
      for (const [x, y] of pts) { g.beginPath(); g.arc(L + x * pw, T + ph - y * ph, r, 0, 7); g.fill(); }
      info.textContent = gaps ? `${empty} empty cells` : `n = ${n}`;
    }
  };
  const slider = el.querySelector("input"), nv = el.querySelector(".nv");
  slider.oninput = () => { n = +slider.value; nv.textContent = n; render(); };
  el.querySelector(".gaps").onclick = (e) => { gaps = !gaps; e.target.setAttribute("aria-pressed", gaps); render(); };
  el.querySelector(".redraw").onclick = () => { seed++; draw(); render(); };
  let anim;
  el.querySelector(".play").onclick = (e) => {
    if (anim) { cancelAnimationFrame(anim); anim = null; e.target.textContent = "Play"; return; }
    const target = +slider.value, t0 = performance.now(); e.target.textContent = "Pause";
    const step = (t) => {
      n = reduce ? target : Math.max(10, Math.round(target * Math.min(1, (t - t0) / 5000) ** 1.5));
      nv.textContent = n; render();
      if (n < target) anim = requestAnimationFrame(step); else { anim = null; e.target.textContent = "Play"; }
    };
    anim = requestAnimationFrame(step);
  };
  new ResizeObserver(render).observe(el);
  onTheme(render);
}

/* ======================= Figure 2: workflow + components ======================= */
function workflow(el, ctx) {
  const steps = [
    ["Obtain/create simulation model", "s3", "Start from a simulator that represents the enterprise. How to build one is outside the paper’s scope."],
    ["Gather simulation data", "s3-1", "Run the simulator many times with different inputs and record the outputs."],
    ["Train NN on data", "s3-1", "Fit a small neural network that predicts the simulator’s outputs from its inputs. It becomes a fast stand-in (a meta-model)."],
    ["Embed business goals in CP model", "s3-2", "Write what the decision maker wants as constraints and objectives in a readable constraint model (see Algorithm 1)."],
    ["Embed the trained NN in the CP model", "appB", "Translate every neuron into a constraint, so the solver can reason about predicted outcomes (Appendix B shows real ones)."],
    ["Generate objective weights", "alg2", "Choose many weightings of the objectives. Montgomery sampling spreads them evenly while keeping their sum at one."],
    ["Define a set of problem instances", "s3-3", "Each weighting gives one version of the problem, asking for a different trade-off."],
    ["Solve the problem instances", "s4", "A solver (Gurobi or JaCoP in the experiments) solves each version without calling the simulator."],
    ["Approximate a pareto front", "s3-3", "Keep the solutions that no other solution beats on every objective: the menu of best trade-offs."],
  ];
  el.innerHTML = `<div class="controls"><span style="flex:1;color:var(--ink-2)">(a) Workflow: from simulation model to pareto front. Tap a step, or play it.</span>
      <button type="button" class="btn play">Play</button></div>
    <ol class="steps">${steps.map(([t], i) => `<li><button type="button" data-i="${i}">${t}</button></li>`).join("")}</ol>
    <div class="stepinfo" aria-live="polite"><span style="color:var(--ink-3)">The step’s explanation appears here.</span></div>
    <p style="margin:1.4rem 0 .5rem;color:var(--ink-2)">(b) Overview of the various components of this article and how they interact. Tap a box.</p>
    <div class="comp"></div><p class="toy">Step and box explanations were written for this site.</p>`;
  const info = el.querySelector(".stepinfo");
  const select = (i) => {
    el.querySelectorAll(".steps button").forEach((b) => b.classList.toggle("on", +b.dataset.i === i));
    const [t, sec, d] = steps[i];
    info.innerHTML = `<b>${i + 1}. ${t}</b><br>${d} <a href="#${sec}" class="go">Read in the paper</a>`;
    info.querySelector(".go").onclick = (e) => { e.preventDefault(); ctx.jump(sec); };
  };
  el.querySelector(".steps").onclick = (e) => { const b = e.target.closest("button"); if (b) { stop(); select(+b.dataset.i); } };
  let timer, cur = -1;
  const btn = el.querySelector(".play");
  const stop = () => { clearInterval(timer); timer = null; btn.textContent = "Play"; };
  btn.onclick = () => {
    if (timer) return stop();
    btn.textContent = "Pause";
    const tick = () => { cur = (cur + 1) % steps.length; select(cur); if (cur === steps.length - 1) stop(); };
    cur = -1; tick(); timer = setInterval(tick, reduce ? 3500 : 2200);
  };

  // (b) components, laid out for a phone-width viewBox
  const nodes = {
    ent: [65, 40, "Enterprise", "The real organization being managed."],
    sim: [320, 40, "Simulation Model", "Represents the enterprise and generates data. Assumed given."],
    dat: [320, 140, "Simulation Data", "Input/output examples from many simulator runs."],
    nn: [320, 240, "Neural Network", "Trained on the simulation data; then embedded in the CP model as constraints."],
    prob: [65, 240, "Problem", "What the decision maker wants solved: goals, limits, preferences."],
    cp: [192, 335, "CP Model", "Combines the problem and the network in one declarative model."],
    sol: [192, 430, "Solution", "Values for the decisions, found by the solver."],
  };
  const W = 116, H = 36;
  // [from, to, label, label x, label y, anchor, path override]
  const edges = [
    ["sim", "ent", "Represents", 192, 33, "middle"],
    ["sim", "dat", "Generates", 328, 94, "start"],
    ["nn", "dat", "Trained on", 328, 194, "start"],
    ["nn", "cp", "Embedded in", 268, 300, "start"],
    ["prob", "cp", "Embedded in", 116, 300, "end"],
    ["cp", "sol", "Solved by solver to obtain", 200, 386, "start"],
    ["sol", "prob", "Provides solution to", 0, 0, "middle", "M134 430 Q65 430 65 262"],
  ];
  const s = svg("svg", { viewBox: "0 0 390 460", style: "max-width:30rem;margin:0 auto" }, el.querySelector(".comp"));
  const defs = svg("defs", {}, s);
  const mk = svg("marker", { id: "arw", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, defs);
  svg("path", { d: "M0 0L10 5L0 10z", fill: "context-stroke" }, mk);
  const clip = (a, b) => { // segment between the two box borders
    const [x1, y1] = nodes[a], [x2, y2] = nodes[b], dx = x2 - x1, dy = y2 - y1;
    const t = Math.min(Math.abs((W / 2 + 3) / (dx || 1e-9)), Math.abs((H / 2 + 3) / (dy || 1e-9)));
    return [[x1 + dx * t, y1 + dy * t], [x2 - dx * t, y2 - dy * t]];
  };
  const eg = edges.map(([a, b, l, lx, ly, anchor, d]) => {
    const g = svg("g", { class: "edge" }, s);
    const [[x1, y1], [x2, y2]] = clip(a, b);
    svg("path", { d: d || `M${x1} ${y1}L${x2} ${y2}`, "marker-end": "url(#arw)" }, g);
    const t = d ? svg("text", { x: 0, y: 0, "text-anchor": "middle", transform: "translate(50 385) rotate(-90)" }, g)
                : svg("text", { x: lx, y: ly, "text-anchor": anchor }, g);
    t.textContent = l;
    return { a, b, g };
  });
  const ng = Object.entries(nodes).map(([k, [x, y, t]]) => {
    const g = svg("g", { class: "node", tabindex: 0, role: "button", "aria-label": t }, s);
    svg("rect", { x: x - W / 2, y: y - H / 2, width: W, height: H, rx: 8 }, g);
    svg("text", { x, y: y + 4, "text-anchor": "middle" }, g).textContent = t;
    const act = () => {
      ng.forEach((o) => o.g.classList.toggle("on", o.k === k));
      eg.forEach((e) => e.g.classList.toggle("on", e.a === k || e.b === k));
      info2.innerHTML = `<b>${t}</b><br>${nodes[k][3]}`;
    };
    g.onclick = act; g.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(); } };
    return { k, g };
  });
  const info2 = document.createElement("div"); info2.className = "stepinfo"; info2.setAttribute("aria-live", "polite");
  info2.innerHTML = `<span style="color:var(--ink-3)">Tap a box to see what it is and how it connects.</span>`;
  el.querySelector(".comp").append(info2);
}

/* ======================= Figure 3: activation functions ======================= */
function activations(el) {
  const F = [
    ["sigmoid", (x) => 1 / (1 + Math.exp(-x)), "s1", ""],
    ["power2", (x) => 1 / (1 + x * x), "s2", "7 5"],
    ["taylor1", (x) => 1 / (1 + Math.max(0, x)), "s3", "9 4 2 4"],
  ];
  el.innerHTML = `<div class="controls">
     <label>Range ±<input type="range" min="2" max="20" value="10" class="rg" aria-label="x range"> <b class="rv">10</b></label>
     <label>Output level <input type="range" min="1" max="100" value="60" class="lv" aria-label="Output level for the injectivity test"> <b class="lvv">0.60</b></label>
     <span class="seg" role="group" aria-label="Show functions">${F.map(([n], i) => `<button type="button" aria-pressed="true" data-i="${i}">${n}</button>`).join("")}</span>
   </div><div class="plot"></div>
   ${legend(F.map(([n, , c, d]) => [cssv("--" + c), n, d]))}
   <p class="readout inj" aria-live="polite"></p><p class="readout hov">Move over the plot to read all three values at one input.</p>`;
  const on = [true, true, true];
  let R = 10, lv = 0.6, hx = null;
  const host = el.querySelector(".plot");
  const render = () => {
    const C = col();
    host.innerHTML = "";
    const f = frame(host, { w: 560, h: 320, x: { domain: [-R, R] }, y: { domain: [0, 1.05], ticks: [0, 0.2, 0.4, 0.6, 0.8, 1] }, xlabel: "x", ylabel: "f(x)" });
    // injectivity line
    svg("line", { x1: f.sx(-R), x2: f.sx(R), y1: f.sy(lv), y2: f.sy(lv), stroke: C.ink3, "stroke-dasharray": "2 4" }, f.plot);
    F.forEach(([, fn, c, dash], i) => {
      if (!on[i]) return;
      let d = "";
      for (let k = 0; k <= 400; k++) { const x = -R + (2 * R * k) / 400; d += `${k ? "L" : "M"}${f.sx(x).toFixed(1)} ${f.sy(fn(x)).toFixed(1)}`; }
      svg("path", { d, fill: "none", stroke: C[c], "stroke-width": 2, "stroke-dasharray": dash }, f.plot);
    });
    // solutions of f(x) = level
    const sols = [[Math.log(lv / (1 - lv))], lv < 1 ? [-Math.sqrt(1 / lv - 1), Math.sqrt(1 / lv - 1)] : [0], lv < 1 ? [1 / lv - 1] : null];
    sols.forEach((xs, i) => { if (!on[i] || !xs) return; xs.forEach((x) => { if (Math.abs(x) <= R) marker(f.plot, "circle", f.sx(x), f.sy(lv), 4.5, C.sheet, C[F[i][2]]); }); });
    if (hx !== null) {
      svg("line", { x1: f.sx(hx), x2: f.sx(hx), y1: f.sy(0), y2: f.sy(1.05), stroke: C.ink3 }, f.plot);
      F.forEach(([, fn, c], i) => on[i] && marker(f.plot, "circle", f.sx(hx), f.sy(fn(hx)), 4, C[c], C.sheet));
    }
    const rect = svg("rect", { x: f.m.l, y: f.m.t, width: f.w - f.m.l - f.m.r, height: f.h - f.m.t - f.m.b, fill: "transparent" }, f.s);
    const move = (e) => {
      const p = f.s.createSVGPoint(); p.x = e.clientX; p.y = e.clientY;
      const q = p.matrixTransform(f.s.getScreenCTM().inverse());
      hx = -R + ((q.x - f.m.l) / (f.w - f.m.l - f.m.r)) * 2 * R;
      el.querySelector(".hov").innerHTML = `x = <b>${hx.toFixed(2)}</b>: ` + F.map(([n, fn], i) => on[i] ? `${n} <b>${fn(hx).toFixed(3)}</b>` : "").filter(Boolean).join(", ");
      render();
    };
    rect.addEventListener("pointermove", move);
    rect.addEventListener("pointerdown", move);
    const n = (xs) => xs === null ? "every x ≤ 0 (infinitely many)" : xs.length === 1 ? "1 input" : `${xs.length} inputs (x = ±${Math.abs(xs[0]).toFixed(2)})`;
    el.querySelector(".inj").innerHTML = lv >= 1
      ? `Output 1.00: sigmoid never reaches it; power2 only at x = 0; taylor1 at <b>every x ≤ 0</b>. Only the sigmoid is injective: each output comes from exactly one input.`
      : `Output ${lv.toFixed(2)} is produced by — sigmoid: <b>${n(sols[0])}</b>, power2: <b>${n(sols[1])}</b>, taylor1: <b>${n(sols[2])}</b>. Only the sigmoid is injective: each output comes from exactly one input.`;
  };
  el.querySelector(".rg").oninput = (e) => { R = +e.target.value; el.querySelector(".rv").textContent = R; hx = null; render(); };
  el.querySelector(".lv").oninput = (e) => { lv = +e.target.value / 100; el.querySelector(".lvv").textContent = lv.toFixed(2); render(); };
  el.querySelector(".seg").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; on[b.dataset.i] = !on[b.dataset.i]; b.setAttribute("aria-pressed", on[b.dataset.i]); render(); };
  render();
  onTheme(render);
}

/* ======================= Figure 4: Montgomery sampling in 3D ======================= */
function scatter3d(parent, getPts, view) {
  const cv = canvas(parent, 0.85);
  cv.c.classList.add("rot");
  cv.c.setAttribute("aria-label", "3D scatter plot; drag to rotate");
  const draw = () => {
    const C = col(), { g, w, h } = cv.fit(), pts = getPts();
    const { yaw, pitch } = view;
    const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
    const S = w * 0.42;
    const P = ([x, y, z]) => { x -= 0.5; y -= 0.5; z -= 0.5; const X = x * cy - y * sy, Y = x * sy + y * cy; return [w / 2 + X * S, h / 2 + 0.06 * h - (z * cp - Y * sp) * S, Y * cp + z * sp]; };
    g.clearRect(0, 0, w, h);
    g.strokeStyle = C.grid; g.lineWidth = 1;
    const E = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 1, 1]];
    for (const [a, b] of [[0, 1], [0, 2], [0, 3], [1, 4], [2, 4], [1, 5], [3, 5], [2, 6], [3, 6], [4, 7], [5, 7], [6, 7]]) { const p = P(E[a]), q = P(E[b]); g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); g.stroke(); }
    g.strokeStyle = C.ink3; g.setLineDash([4, 4]); g.beginPath();
    [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 0]].forEach((v, i) => { const p = P(v); i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]); }); g.stroke(); g.setLineDash([]);
    g.fillStyle = C.ink3; g.font = "10px system-ui";
    [["x", [1.08, 0, 0]], ["y", [0, 1.08, 0]], ["z", [0, 0, 1.08]]].forEach(([l, v]) => { const p = P(v); g.fillText(l, p[0], p[1]); });
    const pr = pts.map((p) => P(p)).sort((a, b) => a[2] - b[2]);
    const zs = pr.map((p) => p[2]), lo = Math.min(...zs), hi = Math.max(...zs);
    for (const [x, y, z] of pr) {
      g.globalAlpha = 0.45 + 0.55 * ((z - lo) / (hi - lo || 1));
      g.fillStyle = C.s1; g.strokeStyle = C.sheet; g.lineWidth = 1.5;
      g.beginPath(); g.arc(x, y, 4, 0, 7); g.fill(); g.stroke();
    }
    g.globalAlpha = 1;
  };
  let drag = null;
  cv.c.addEventListener("pointerdown", (e) => { drag = [e.clientX, e.clientY, view.yaw, view.pitch]; cv.c.setPointerCapture(e.pointerId); });
  cv.c.addEventListener("pointermove", (e) => { if (!drag) return; view.yaw = drag[2] - (e.clientX - drag[0]) / 120; view.pitch = Math.max(-1.5, Math.min(1.5, drag[3] + (e.clientY - drag[1]) / 120)); view.sync(); });
  cv.c.addEventListener("pointerup", () => (drag = null));
  return draw;
}
function montgomery3d(el) {
  el.innerHTML = `<div class="controls">
     <label>Points <input type="range" min="8" max="160" step="4" value="32" aria-label="Number of points"> <b class="nv">32</b></label>
     <label>Montgomery base <select aria-label="Low-discrepancy sequence used by Montgomery sampling"><option value="halton">Halton</option><option value="sobol">Sobol</option></select></label>
     <button type="button" class="btn quiet face">Face-on view</button><button type="button" class="btn quiet redraw">New random draw</button>
   </div><div class="grid3"></div>
   <p class="readout">Drag any plot to rotate all three. Every point satisfies x + y + z = 1, so it lies on the dashed triangle. L2* discrepancy is computed live in your browser (lower is more even). The absolute values differ from the paper’s, which does not state its exact sequence settings (such as scrambling or start index); compare the ranking instead. A new random draw changes only the uniform panel.</p>`;
  let n = 32, base = "halton", seed = 3;
  const view = { yaw: 0.8, pitch: 0.45, sync: () => draws.forEach((d) => d()) };
  const sets = {
    "(a) Normalized Halton": { paper: 0.135, gen: () => Array.from({ length: n }, (_, i) => normalize(halton(i + 1, 3))) },
    "(b) Normalized Uniform": { paper: 0.155, gen: () => { const r = rng(seed); return Array.from({ length: n }, () => normalize([r(), r(), r()])); } },
    "(c) Montgomery": { paper: 0.119, gen: () => montgomery(n, 3, base) },
  };
  const draws = [], cells = [];
  for (const [name, s] of Object.entries(sets)) {
    const d = document.createElement("div"); d.className = "cell";
    d.innerHTML = `<h5>${name}</h5><div></div><p class="readout" style="margin:.2rem 0 0"></p>`;
    el.querySelector(".grid3").append(d);
    s.out = d.querySelector("p");
    draws.push(scatter3d(d.querySelector("div"), () => s.pts, view));
    cells.push(s);
  }
  const update = () => {
    for (const s of cells) { s.pts = s.gen(); s.out.innerHTML = `L2* <b>${l2star(s.pts).toFixed(3)}</b>${n === 32 ? ` <span style="color:var(--ink-3)">(paper ${s.paper})</span>` : ""}`; }
    view.sync();
  };
  el.querySelector("input").oninput = (e) => { n = +e.target.value; el.querySelector(".nv").textContent = n; update(); };
  el.querySelector("select").onchange = (e) => { base = e.target.value; update(); };
  el.querySelector(".redraw").onclick = () => { seed++; update(); };
  el.querySelector(".face").onclick = () => { // look straight down (1,1,1): yaw 45°, pitch = atan(1/√2)
    view.yaw = FACE.yaw; view.pitch = FACE.pitch; view.sync();
  };
  update();
  new ResizeObserver(() => view.sync()).observe(el);
  onTheme(() => view.sync());
}

/* ======================= Algorithm 2: step through ======================= */
function montgomerystep(el, ctx) {
  const alg = ctx.paper.blocks.find((b) => b.id === "alg2");
  el.innerHTML = `<div class="controls">
     <label>n <input type="range" min="3" max="24" value="8" aria-label="Number of points to sample"> <b class="nv">8</b></label>
     <button type="button" class="btn step">Step</button><button type="button" class="btn play">Play</button><button type="button" class="btn quiet reset">Reset</button>
   </div>
   <div class="grid3" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr);max-width:34rem"><div class="cell"><h5>Halton points (x₁, x₂)</h5><div class="sq"></div></div>
   <div class="cell"><h5>Accepted weights</h5><div class="tri"></div></div></div>
   <div class="vars" aria-live="polite"></div>
   <div class="algo mini" style="font-size:.85rem;padding:.4rem 0">${alg.lines.map(([ind, l], i) => `<div class="row" data-i="${i}" style="grid-template-columns:1fr"><div style="padding-left:${ind * 1.2}rem">${ctx.math(l)}</div></div>`).join("")}</div>
   <p class="toy">Runs Algorithm 2 for d = 3 one line at a time. Points with x₁ + x₂ ≤ 1 are kept (blue); the rest are discarded (grey cross).</p>`;
  const d = 3;
  let n = 8, st;
  const sub = Array.from({ length: 400 }, (_, i) => halton(i + 1, d - 1));
  const reset = () => { st = { line: 4, i: 0, H: [], x: null, s: null, tried: [], done: false }; draw(); };
  const stepOnce = () => {
    if (st.done) return;
    const L = st.line;
    if (L === 4 || L === 12) st.line = 5;
    else if (L === 5) st.line = st.H.length < n ? 6 : 13;
    else if (L === 6) { st.x = sub[st.i]; st.s = null; st.line = 7; }
    else if (L === 7) { st.s = 1 - st.x[0] - st.x[1]; st.line = 8; }
    else if (L === 8) { st.tried.push([st.x, st.s >= 0]); st.line = st.s >= 0 ? 9 : 11; }
    else if (L === 9) st.line = 10;
    else if (L === 10) { st.H.push([...st.x, st.s]); st.line = 11; }
    else if (L === 11) st.line = 12, st.i++;
    else if (L === 13) st.line = 14;
    else if (L === 14) st.done = true;
    if (st.line === 12) { /* i ← i + 1 shown */ }
    draw();
  };
  const sq = canvas(el.querySelector(".sq"), 1), tri = canvas(el.querySelector(".tri"), 1);
  const draw = () => {
    const C = col();
    { const { g, w } = sq.fit(), p = 18, S = w - 2 * p;
      g.clearRect(0, 0, w, w); g.strokeStyle = C.rule; g.strokeRect(p, p, S, S);
      g.strokeStyle = C.ink3; g.setLineDash([4, 4]); g.beginPath(); g.moveTo(p, p); g.lineTo(p + S, p + S); g.stroke(); g.setLineDash([]);
      g.fillStyle = C.ink3; g.font = "10px system-ui"; g.fillText("x₁ + x₂ = 1", p + S * 0.55, p + S * 0.45);
      for (const [[a, b], ok] of st.tried) {
        const X = p + a * S, Y = p + S - b * S;
        if (ok) { g.fillStyle = C.s1; g.beginPath(); g.arc(X, Y, 4, 0, 7); g.fill(); }
        else { g.strokeStyle = C.ink3; g.lineWidth = 1.5; g.beginPath(); g.moveTo(X - 3.5, Y - 3.5); g.lineTo(X + 3.5, Y + 3.5); g.moveTo(X + 3.5, Y - 3.5); g.lineTo(X - 3.5, Y + 3.5); g.stroke(); }
      }
      if (st.x && !st.done) { g.strokeStyle = C.act; g.lineWidth = 2; g.beginPath(); g.arc(p + st.x[0] * S, p + S - st.x[1] * S, 8, 0, 7); g.stroke(); g.lineWidth = 1; }
    }
    { const { g, w } = tri.fit(), p = 22, A = [w / 2, p], B = [p, w - p * 1.6], Cc = [w - p, w - p * 1.6];
      g.clearRect(0, 0, w, w); g.strokeStyle = C.rule; g.beginPath(); g.moveTo(...A); g.lineTo(...B); g.lineTo(...Cc); g.closePath(); g.stroke();
      g.fillStyle = C.ink3; g.font = "10px system-ui"; g.textAlign = "center";
      g.fillText("s = 1", A[0], A[1] - 6); g.fillText("x₁ = 1", Cc[0] - 8, Cc[1] + 14); g.fillText("x₂ = 1", B[0] + 8, B[1] + 14);
      for (const [a, b, s] of st.H) { const X = a * Cc[0] + b * B[0] + s * A[0], Y = a * Cc[1] + b * B[1] + s * A[1]; g.fillStyle = C.s1; g.beginPath(); g.arc(X, Y, 4.5, 0, 7); g.fill(); }
    }
    el.querySelectorAll(".mini .row").forEach((r) => r.classList.toggle("on", +r.dataset.i === st.line));
    el.querySelector(".vars").innerHTML = `<span>i = <b>${st.i}</b></span><span>x = <b>${st.x ? `(${st.x[0].toFixed(3)}, ${st.x[1].toFixed(3)})` : "–"}</b></span><span>s = <b>${st.s === null ? "–" : st.s.toFixed(3)}</b></span><span>|Hᵐ| = <b>${st.H.length}</b> of ${n}</span>${st.done ? "<span><b>Done.</b></span>" : ""}`;
  };
  let timer;
  const playBtn = el.querySelector(".play");
  const stop = () => { clearInterval(timer); timer = null; playBtn.textContent = "Play"; };
  el.querySelector(".step").onclick = () => { stop(); stepOnce(); };
  playBtn.onclick = () => { if (timer) return stop(); playBtn.textContent = "Pause"; timer = setInterval(() => { stepOnce(); if (st.done) stop(); }, reduce ? 600 : 260); };
  el.querySelector(".reset").onclick = () => { stop(); reset(); };
  el.querySelector("input").oninput = (e) => { n = +e.target.value; el.querySelector(".nv").textContent = n; stop(); reset(); };
  reset();
  new ResizeObserver(draw).observe(el);
  onTheme(draw);
}

/* ======================= Section 3.3 explainer: weighted composite objective (toy) ======================= */
function composite(el) {
  // toy restaurant: buy amount b in [0,1]; success rises then saturates, spoilage grows; plus some dominated strategies
  const r = rng(11), C0 = [];
  for (let k = 0; k < 26; k++) { const b = k / 25; C0.push({ succ: 0.25 + 0.72 * (1 - Math.exp(-3.2 * b)), spoil: 0.04 + 0.6 * b * b, front: true }); }
  for (let k = 0; k < 34; k++) { const b = r(); C0.push({ succ: 0.25 + 0.72 * (1 - Math.exp(-3.2 * b)) - 0.05 - 0.2 * r(), spoil: 0.04 + 0.6 * b * b + 0.04 * r(), front: false }); }
  el.innerHTML = `<p style="margin:.2rem 0 .8rem">A pretend restaurant can choose among 60 buying strategies (dots). The solver maximizes
     <b>success × w − spoilage × (1 − w)</b>. Move the weight to see which strategy wins, then generate several problem instances to see why
     evenly spread weights find more of the best trade-offs.</p>
    <div class="controls"><label>Success weight w <input type="range" class="wv" min="0" max="100" value="50" aria-label="Success weight"> <b class="wo">0.50</b></label></div>
    <div class="plot"></div>
    <div class="controls" style="margin-top:.6rem"><label>Problem instances <input type="range" class="kv" min="2" max="16" value="6" aria-label="Number of problem instances"> <b class="ko">6</b></label>
      <span class="seg" role="group" aria-label="Weight sampler"><button type="button" data-s="uniform" aria-pressed="false">Uniform random</button><button type="button" data-s="montgomery" aria-pressed="true">Montgomery</button></span>
      <button type="button" class="btn quiet again">New random draw</button></div>
    <p class="readout out" aria-live="polite"></p>
    <p class="toy">Illustrative toy data, not from the paper. Front occupation (FO) counts distinct best trade-offs found; front spread (FS) is the largest distance between them (Table 4).</p>`;
  let w = 0.5, k = 6, sampler = "montgomery", seed = 1;
  const best = (w) => C0.reduce((a, c) => (c.succ * w - c.spoil * (1 - w) > a.succ * w - a.spoil * (1 - w) ? c : a));
  const host = el.querySelector(".plot");
  const render = () => {
    const C = col();
    const ws = sampler === "montgomery" ? Array.from({ length: k }, (_, i) => vdc(i + 1, 2)) : (() => { const r = rng(seed); return Array.from({ length: k }, () => r()); })();
    const found = [...new Set(ws.map(best))];
    let fs = 0; for (const a of found) for (const b of found) fs = Math.max(fs, Math.hypot(a.succ - b.succ, a.spoil - b.spoil));
    host.innerHTML = "";
    const f = frame(host, { w: 560, h: 300, x: { domain: [0, 0.75] }, y: { domain: [0, 1] }, xlabel: "Spoilage (lower is better)", ylabel: "Success (higher is better)" });
    for (const c of C0) marker(f.plot, "circle", f.sx(c.spoil), f.sy(c.succ), 3.5, c.front ? C.ink3 : C.rule, "none");
    for (const c of found) marker(f.plot, "circle", f.sx(c.spoil), f.sy(c.succ), 6.5, "none", C.s3);
    const b = best(w);
    // iso-line of the objective through the winner: succ*w - spoil*(1-w) = const
    const val = b.succ * w - b.spoil * (1 - w), line = (sp) => (val + sp * (1 - w)) / (w || 1e-9);
    if (w > 0.02) svg("line", { x1: f.sx(0), y1: f.sy(Math.max(-1, Math.min(2, line(0)))), x2: f.sx(0.75), y2: f.sy(Math.max(-1, Math.min(2, line(0.75)))), stroke: C.s1, "stroke-dasharray": "5 4", "clip-path": "none" }, f.plot);
    marker(f.plot, "diamond", f.sx(b.spoil), f.sy(b.succ), 6, C.s1, C.sheet);
    el.querySelector(".out").innerHTML = `With w = ${w.toFixed(2)} the solver picks the <span style="color:var(--s1)">◆</span> strategy (success ${b.succ.toFixed(2)}, spoilage ${b.spoil.toFixed(2)}).
      ${k} instances with ${sampler === "montgomery" ? "Montgomery" : "uniform random"} weights found <b>FO = ${found.length}</b> distinct best trade-offs (green rings), <b>FS = ${fs.toFixed(2)}</b>.`;
  };
  el.querySelector(".wv").oninput = (e) => { w = +e.target.value / 100; el.querySelector(".wo").textContent = w.toFixed(2); render(); };
  el.querySelector(".kv").oninput = (e) => { k = +e.target.value; el.querySelector(".ko").textContent = k; render(); };
  el.querySelector(".seg").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; sampler = b.dataset.s; el.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-pressed", x === b)); render(); };
  el.querySelector(".again").onclick = () => { seed++; render(); };
  render();
  onTheme(render);
}

/* ======================= Table 5 chart ======================= */
function table5chart(el, ctx) {
  const T = ctx.paper.blocks.find((b) => b.id === "tab5").rows;
  const S = ["Uniform", "Montgomery–Sobol", "Montgomery–Halton"], key = ["s2", "s1", "s3"];
  el.innerHTML = `<div class="controls"><span class="seg" role="group" aria-label="Metric">${[["FO", "Front occupation"], ["FS", "Front spread"], ["Runtime", "Runtime"]].map(([k, l], i) => `<button type="button" data-k="${k}" aria-pressed="${i === 0}">${l}</button>`).join("")}</span></div>
    <div class="plot"></div>${legend(S.map((s, i) => [cssv("--" + key[i]), s]))}<p class="readout note"></p>`;
  let metric = "FO";
  const host = el.querySelector(".plot"), tip = tipFor(host);
  const render = () => {
    const C = col();
    const ci = { FO: 3, FS: 4, Runtime: 5 }[metric];
    const val = (r) => parseFloat(r[ci]), sd = (r) => metric === "Runtime" ? parseFloat(r[ci].split("±")[1]) : 0;
    const max = Math.max(...T.map((r) => val(r) + sd(r)));
    host.querySelectorAll("svg").forEach((s) => s.remove());
    const f = frame(host, { x: { domain: [1.7, 6.3], ticks: [2, 3, 4, 5, 6] }, y: { domain: [0, max * 1.08] }, xlabel: "Number of objectives",
      ylabel: { FO: "Front occupation (higher is better)", FS: "Front spread (higher is better)", Runtime: "Runtime per instance (s, ± sd)" }[metric] });
    S.forEach((s, i) => {
      const rows = T.filter((r) => r[0] === s), off = (i - 1) * 0.08;
      svg("path", { d: rows.map((r, j) => `${j ? "L" : "M"}${f.sx(+r[1] + off)} ${f.sy(val(r))}`).join(""), fill: "none", stroke: C[key[i]], "stroke-width": 2 }, f.plot);
      for (const r of rows) {
        const x = f.sx(+r[1] + off), y = f.sy(val(r));
        if (sd(r)) svg("line", { x1: x, x2: x, y1: f.sy(Math.max(0, val(r) - sd(r))), y2: f.sy(val(r) + sd(r)), stroke: C[key[i]], "stroke-width": 1.2, opacity: 0.7 }, f.plot);
        const m = marker(f.plot, ["circle", "square", "diamond"][i], x, y, 4.5, C[key[i]], C.sheet);
        const hit = svg("circle", { cx: x, cy: y, r: 14, fill: "transparent" }, f.plot);
        hit.addEventListener("pointerenter", () => tip.show(`<b>${s}</b>, ${r[1]} objectives<br>FO ${r[3]} · FS ${r[4]} · runtime ${r[5]} s<br>${r[2]} repetitions`, x / f.w * host.clientWidth, y / f.h * host.clientWidth * f.h / f.w));
        hit.addEventListener("pointerleave", () => tip.hide());
        hit.addEventListener("pointerdown", () => tip.show(`<b>${s}</b>, ${r[1]} objectives<br>FO ${r[3]} · FS ${r[4]} · runtime ${r[5]} s`, x / f.w * host.clientWidth, y / f.h * host.clientWidth * f.h / f.w));
      }
    });
    el.querySelector(".note").textContent = metric === "Runtime"
      ? "Runtimes overlap heavily: the error bars (one standard deviation) are as large as the differences."
      : `Values from Table 5. For every number of objectives, both Montgomery variants reach ${metric === "FO" ? "a higher front occupation" : "an equal or higher front spread"} than uniform sampling.`;
  };
  el.querySelector(".seg").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; metric = b.dataset.k; el.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-pressed", x === b)); render(); };
  render(); onTheme(render);
}

/* ======================= Table 6 chart ======================= */
function table6chart(el, ctx) {
  const T = ctx.paper.blocks.find((b) => b.id === "tab6").rows;
  const A = ["Sigmoid", "Pow2", "Taylor1"], key = ["s1", "s2", "s3"];
  el.innerHTML = `<div class="controls"><span>Vertical axis</span><span class="seg" role="group" aria-label="Vertical axis">${[["MSE", "MSE"], ["FO", "Front occupation"], ["FS", "Front spread"]].map(([k, l], i) => `<button type="button" data-k="${k}" aria-pressed="${i === 0}">${l}</button>`).join("")}</span></div>
    <div class="plot"></div>${legend(A.map((a, i) => [cssv("--" + key[i]), a]))}
    <p class="readout" style="margin-top:0">Circles: Gurobi. Squares: JaCoP. Labels give hidden layers × layer width. Runtime is on a log scale.</p><p class="readout note"></p>`;
  let metric = "MSE";
  const host = el.querySelector(".plot"), tip = tipFor(host);
  const render = () => {
    const C = col();
    const ci = { MSE: 6, FO: 7, FS: 8 }[metric];
    host.querySelectorAll("svg").forEach((s) => s.remove());
    const ys = T.map((r) => +r[ci]);
    const yax = metric === "MSE" ? { domain: [0.0005, 0.005], log: true, ticks: [0.0005, 0.001, 0.002, 0.005], tf: (v) => String(v) } : { domain: [0, Math.max(...ys) * 1.15] };
    const f = frame(host, { m: { t: 14, r: 18, b: 40, l: 58 }, x: { domain: [0.3, 300], log: true, ticks: [0.3, 1, 3, 10, 30, 100, 300], tf: (v) => String(v) }, y: yax,
      xlabel: "Runtime per instance (s, log scale)", ylabel: { MSE: "MSE (log, lower is better)", FO: "Front occupation", FS: "Front spread" }[metric] });
    const P = T.map((r) => [f.sx(+r[5]), f.sy(+r[ci])]);
    T.forEach((r, k) => {
      const i = A.indexOf(r[2]), [x, y] = P[k];
      marker(f.plot, r[1] === "Gurobi" ? "circle" : "square", x, y, 5.5, C[key[i]], C.sheet);
      const crowded = P.some(([x2, y2], j) => j !== k && x2 > x && x2 - x < 48 && Math.abs(y2 - y) < 12);
      svg("text", crowded ? { x, y: y - 10, "font-size": 10, "text-anchor": "middle" } : { x: x + 8, y: y + 3.5, "font-size": 10 }, f.plot).textContent = `${r[3]}×${r[4]}`;
      const hit = svg("circle", { cx: x, cy: y, r: 14, fill: "transparent" }, f.plot);
      const show = () => tip.show(`<b>${r[2]}</b> on ${r[1]}, ${r[3]} layers × ${r[4]}<br>runtime ${r[5]} s · MSE ${r[6]}<br>FO ${r[7]} · FS ${r[8]} · ${r[0]} repetitions`, x / f.w * host.clientWidth, y / f.w * host.clientWidth);
      hit.addEventListener("pointerenter", show); hit.addEventListener("pointerdown", show); hit.addEventListener("pointerleave", () => tip.hide());
    });
    el.querySelector(".note").textContent = { MSE: "Bottom-left is best: fast and accurate. Gurobi runs (circles) are one to two orders of magnitude faster than JaCoP (squares); the sigmoid only runs on JaCoP.",
      FO: "Higher is better. The largest Pow2 network on Gurobi found the most Pareto-optimal solutions.", FS: "Higher means more diverse solutions. Taylor1 is fast but its spread stays modest, the trade-off the paper describes." }[metric];
  };
  el.querySelector(".seg").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; metric = b.dataset.k; el.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-pressed", x === b)); render(); };
  render(); onTheme(render);
}

/* ======================= Table 7 chart ======================= */
function table7chart(el, ctx) {
  const T = ctx.paper.blocks.find((b) => b.id === "tab7").rows;
  const outs = [["Strength", 2], ["Mortality rate", 4], ["Proactive aggression", 6]];
  el.innerHTML = `<div class="controls"><span class="seg" role="group" aria-label="Output">${outs.map(([l], i) => `<button type="button" data-i="${i}" aria-pressed="${i === 0}">${l}</button>`).join("")}</span></div>
    <div class="plot"></div>${legend([[cssv("--s1"), "CP model’s prediction"], [cssv("--s2"), "Simulation result (mean ± sd)"]])}
    <p class="readout note"></p>
    <h5 style="margin:1.2rem 0 .2rem;font:600 .85rem var(--sans)">The two inputs of the same six solutions</h5><div class="plot2"></div>
    <p class="readout">Lower is cheaper on both axes. The solutions form a curve: a higher collaboration bonus lets the max age drop, and the other way round, which is the paper’s point that the same outcome can be reached in several ways.</p>`;
  let oi = 0;
  const host = el.querySelector(".plot"), tip = tipFor(host);
  const render = () => {
    const C = col(), c = outs[oi][1];
    host.querySelectorAll("svg").forEach((s) => s.remove());
    const sim = T.map((r) => r[c + 1].split("±").map(parseFloat));
    const lo = Math.min(...T.map((r, i) => Math.min(+r[c], sim[i][0] - sim[i][1]))), hi = Math.max(...T.map((r, i) => Math.max(+r[c], sim[i][0] + sim[i][1])));
    const pad = (hi - lo) * 0.15;
    const f = frame(host, { h: 280, m: { t: 14, r: 14, b: 52, l: 52 }, x: { domain: [0.4, 6.6], ticks: [1, 2, 3, 4, 5, 6], tf: (v) => `#${v}` }, y: { domain: [lo - pad, hi + pad] },
      xlabel: "Solution (in table order)", ylabel: outs[oi][0] });
    let gap = 0;
    T.forEach((r, i) => {
      const x = f.sx(i + 1), [m, s] = sim[i];
      svg("line", { x1: x + 7, x2: x + 7, y1: f.sy(m - s), y2: f.sy(m + s), stroke: C.s2, "stroke-width": 1.6 }, f.plot);
      marker(f.plot, "circle", x + 7, f.sy(m), 4.5, C.s2, C.sheet);
      marker(f.plot, "diamond", x - 7, f.sy(+r[c]), 4.5, C.s1, C.sheet);
      if (Math.abs(+r[c] - m) <= s) gap++;
      const hit = svg("rect", { x: x - 20, y: f.m.t, width: 40, height: f.h - f.m.t - f.m.b, fill: "transparent" }, f.plot);
      const show = () => tip.show(`<b>Solution ${i + 1}</b>: bonus ${r[0]}, max age ${r[1]}<br>CP ${r[c]} · SIM ${r[c + 1]}`, x / f.w * host.clientWidth, f.sy(m) / f.w * host.clientWidth);
      hit.addEventListener("pointerenter", show); hit.addEventListener("pointerdown", show); hit.addEventListener("pointerleave", () => tip.hide());
    });
    el.querySelector(".note").textContent = `For ${gap} of 6 solutions the CP model’s prediction falls within one standard deviation of what the simulation produced.`;
  };
  // inputs plot (static)
  const C = col(), h2 = el.querySelector(".plot2");
  const drawInputs = () => {
    const C = col(); h2.innerHTML = "";
    const f = frame(h2, { h: 240, x: { domain: [3, 5.2] }, y: { domain: [100, 290] }, xlabel: "Collaboration bonus", ylabel: "Max age" });
    svg("path", { d: T.map((r, i) => `${i ? "L" : "M"}${f.sx(+r[0])} ${f.sy(+r[1])}`).join(""), fill: "none", stroke: C.ink3, "stroke-dasharray": "3 3" }, f.plot);
    const groups = [];
    T.forEach((r, i) => {
      const x = f.sx(+r[0]), y = f.sy(+r[1]);
      marker(f.plot, "circle", x, y, 5, C.s1, C.sheet);
      const g = groups.find((g) => Math.hypot(g.x - x, g.y - y) < 14);
      g ? g.ids.push(i + 1) : groups.push({ x, y, ids: [i + 1] });
    });
    for (const g of groups) svg("text", { x: g.x + 8, y: g.y - 7, "font-size": 10 }, f.plot).textContent = g.ids.map((i) => `#${i}`).join(", ");
  };
  el.querySelector(".seg").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; oi = +b.dataset.i; el.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-pressed", x === b)); render(); };
  render(); drawInputs(); onTheme(() => { render(); drawInputs(); });
}

/* ======================= Appendix A: improved algorithm, live ======================= */
function appendixA(el) {
  const Md = (d) => {
    const M = Array.from({ length: d }, () => Array(d).fill(0)), s = (k) => (k * (k + 1)) / 2;
    for (let k = 1; k < d; k++) for (let i = 1; i <= d; i++) M[i - 1][k - 1] = i === k + 1 ? k / Math.sqrt(2 * s(k)) : i <= k ? -1 / Math.sqrt(2 * s(k)) : 0;
    for (let i = 0; i < d; i++) M[i][d - 1] = 1 / Math.sqrt(d);
    return M;
  };
  const improved = (n, d) => {
    const M = Md(d), out = []; let tried = 0;
    for (let j = 1; out.length < n && j < 200000; j++) {
      tried++;
      const h = [...halton(j, d - 1), 0];
      const t = M.map((row, i) => Math.SQRT2 * row.reduce((a, m, k) => a + m * h[k], 0) + (i === 0 ? 1 : 0));
      if (t.every((v) => v >= -1e-12 && v <= 1 + 1e-12)) out.push(t.map((v) => Math.min(1, Math.max(0, v))));
    }
    return { out, tried };
  };
  el.innerHTML = `<div class="controls"><label>Dimensions d <select class="dv" aria-label="Dimensions">${[3, 4, 5, 6, 7].map((d) => `<option ${d === 3 ? "selected" : ""}>${d}</option>`).join("")}</select></label>
     <label>Points <input type="range" class="nv" min="8" max="160" step="4" value="32" aria-label="Number of points"> <b class="no">32</b></label></div>
    <div class="matrix"></div><p class="readout check"></p>
    <div class="grid3" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)"><div class="cell"><h5>Montgomery (Alg. 2)</h5><div class="a"></div><p class="readout la"></p></div>
    <div class="cell"><h5>Improved (App. A)</h5><div class="b"></div><p class="readout lb"></p></div></div>
    <p class="toy">This comparison is not in the paper, which leaves evaluating the improved algorithm to future work. Plots show d = 3 (drag to rotate); numbers update for the chosen d.</p>`;
  let d = 3, n = 32;
  const view = { ...FACE, sync: () => draws.forEach((f) => f()) };
  const S = { a: [], b: [] };
  const draws = [scatter3d(el.querySelector(".a"), () => S.a, view), scatter3d(el.querySelector(".b"), () => S.b, view)];
  const update = () => {
    const M = Md(d);
    let err = 0;
    for (let i = 0; i < d; i++) for (let j = 0; j < d; j++) err = Math.max(err, Math.abs(M.reduce((a, r) => a + r[i] * r[j], 0) - (i === j ? 1 : 0)));
    el.querySelector(".matrix").innerHTML = `<table aria-label="Matrix M${d}">${M.map((r) => `<tr>${r.map((v) => `<td>${v.toFixed(3)}</td>`).join("")}</tr>`).join("")}</table>`;
    const imp = improved(n, d), mon = montgomery(n, d);
    const fact = [1, 1, 2, 6, 24, 120, 720, 5040][d];
    el.querySelector(".check").innerHTML = `M<sub>${d}</sub> columns orthonormal: largest deviation of MᵀM from I is <b>${err.toExponential(1)}</b>. Kept ${imp.out.length} of ${imp.tried} transformed Halton points: <b>${(100 * imp.out.length / imp.tried).toFixed(1)}%</b> (the paper estimates roughly 1/d! = ${(100 / fact).toFixed(1)}%). Every kept point sums to 1.`;
    el.querySelector(".la").innerHTML = `L2* ${l2star(mon).toFixed(3)} (d = ${d})`;
    el.querySelector(".lb").innerHTML = `L2* ${l2star(imp.out).toFixed(3)} (d = ${d})`;
    S.a = montgomery(n, 3); S.b = improved(n, 3).out;
    view.sync();
  };
  el.querySelector(".dv").onchange = (e) => { d = +e.target.value; update(); };
  el.querySelector(".nv").oninput = (e) => { n = +e.target.value; el.querySelector(".no").textContent = n; update(); };
  update();
  new ResizeObserver(() => view.sync()).observe(el);
  onTheme(() => view.sync());
}

/* ======================= Appendix B: the embedded network ======================= */
function nnembed(el, ctx) {
  const code = ctx.paper.blocks.find((b) => b.id === "appBcode").lines;
  const neurons = {};
  code.forEach((l, i) => {
    const m = l.match(/^constraint \((n_(\d)_(\d+))\S* = (max\(\(|\()(.*?)\)(?:, 0\))?\);$/);
    if (!m) return;
    const terms = m[5].split(" + ").map((t) => t.trim());
    const bias = terms.length && !terms.at(-1).includes("*") ? parseFloat(terms.pop()) : 0;
    neurons[`${m[2]}_${m[3]}`] = { line: i + 1, relu: m[4].startsWith("max"), bias,
      w: terms.map((t) => { const [a, b] = t.split(" * "); return [parseFloat(a), b.replace(/Supply_Chain_Supply_Chain_halton_pow2$/, "").replace(/^n_(\d)_(\d+)$/, "$1_$2")]; }) };
  });
  const inputs = neurons["0_0"].w.map(([, n]) => n);
  const outs = ["lost_ratio_sales_ret", "lost_ratio_sales_dis", "lost_ratio_sales_fac"];
  const layers = [inputs.map((n) => ({ id: n, label: n })), ...[[0, 12], [1, 12], [2, 3]].map(([L, k]) => Array.from({ length: k }, (_, j) => ({ id: `${L}_${j}`, label: `n_${L}_${j}` }))), outs.map((o, j) => ({ id: o, label: o, out: j }))];
  el.innerHTML = `<p style="margin:.2rem 0 .8rem">The supply-chain network as the solver sees it: ${inputs.length} simulation inputs, two hidden layers of 12 units, 3 output units, and 3 predicted lost-sales ratios.
     Units whose constraint is printed in the appendix are solid; the appendix elides the rest (“…”). Tap a solid unit.</p>
    <div class="net"></div>${legend([[cssv("--s1"), "positive weight"], [cssv("--s2"), "negative weight"]])}
    <div class="stepinfo" aria-live="polite"><span style="color:var(--ink-3)">Line thickness shows the size of each weight.</span></div>`;
  const W = 360, H = 430, ys = [30, 125, 220, 315, 400];
  const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, style: "max-width:30rem;margin:0 auto" }, el.querySelector(".net"));
  const pos = {};
  layers.forEach((L, li) => L.forEach((u, j) => { pos[u.id] = [20 + ((W - 40) * (j + 0.5)) / L.length, ys[li]]; }));
  const names = ["inputs", "layer 0 · ReLU", "layer 1 · ReLU", "layer 2 · linear", "outputs · power2"];
  
  const edgeG = svg("g", {}, s), nodeG = svg("g", {}, s);
  const labelG = svg("g", {}, s);
  let sel;
  const draw = () => {
    const C = col();
    edgeG.innerHTML = ""; nodeG.innerHTML = "";
    const nr = sel && neurons[sel];
    if (nr) for (const [w, from] of nr.w) {
      const a = pos[from], b = pos[sel]; if (!a) continue;
      svg("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: w >= 0 ? C.s1 : C.s2, "stroke-width": 0.5 + Math.abs(w) * 7, opacity: 0.8 }, edgeG);
    }
    if (sel?.startsWith("lost")) { const j = outs.indexOf(sel), a = pos[`2_${j}`], b = pos[sel]; svg("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: C.act, "stroke-width": 2.5 }, edgeG); }
    labelG.innerHTML = "";
    ys.forEach((y, i) => (svg("text", { x: 4, y: y - 13, "font-size": 10, stroke: C.sheet, "stroke-width": 4, "paint-order": "stroke" }, labelG).textContent = names[i]));
    layers.forEach((L) => L.forEach((u) => {
      const [x, y] = pos[u.id], known = neurons[u.id] || u.out !== undefined || !u.id.includes("_") || inputs.includes(u.id);
      const isSel = u.id === sel;
      const c = svg("circle", { cx: x, cy: y, r: isSel ? 7 : 5, fill: neurons[u.id] || u.out !== undefined ? (isSel ? C.act : C.ink2) : known ? C.ink3 : C.sheet,
        stroke: isSel ? C.act : C.ink3, "stroke-width": 1.4, tabindex: known ? 0 : -1, role: "button", "aria-label": u.label, style: "cursor:pointer" }, nodeG);
      c.onclick = () => pick(u.id); c.onkeydown = (e) => { if (e.key === "Enter") pick(u.id); };
    }));
  };
  const info = el.querySelector(".stepinfo");
  const pick = (id) => {
    sel = id; draw();
    const nr = neurons[id];
    const goto = (line) => `<a href="#appB-l${line}" class="go">Show line ${line} of the code</a>`;
    if (nr) {
      const top = [...nr.w].sort((a, b) => Math.abs(b[0]) - Math.abs(a[0])).slice(0, 3).map(([w, n]) => `${n.includes("_") && /^\d_\d+$/.test(n) ? "n_" + n : n} (${w.toFixed(3)})`).join(", ");
      info.innerHTML = `<b>n_${id}</b> = ${nr.relu ? "max(weighted sum, 0)" : "weighted sum"} of ${nr.w.length} values plus bias ${nr.bias.toFixed(3)}.<br>Strongest weights: ${top}.<br>${goto(nr.line)}`;
    } else if (id.startsWith("lost")) {
      const j = outs.indexOf(id);
      info.innerHTML = `<b>${id}</b> · (1 + n_2_${j}²) = 1, which is the same as ${id} = 1 / (1 + n_2_${j}²): the power2 activation of Equation (2) written as a constraint. ${goto(21 + j)}`;
    } else if (inputs.includes(id)) info.innerHTML = `<b>${esc(id)}</b> is a simulation input (a decision the solver can choose), feeding every unit in layer 0.`;
    else info.innerHTML = `<b>n_${id}</b>: its constraint is elided in the appendix (“…”), but it has the same form as its neighbours.`;
    info.querySelector(".go")?.addEventListener("click", (e) => { e.preventDefault(); ctx.jump(e.target.getAttribute("href").slice(1)); });
  };
  pick("0_0");
  onTheme(draw);
}


/* ======================= Any proceedings table with numbers: bar chart per column ======================= */
const isNumCell = (v) => /^[-+−±~≈<>]?\s*\d[\d.,]*\s*(%|×|x|e[-−]?\d+)?(\s*±\s*[\d.,]+)?\s*$/i.test(String(v).trim());
const numOf = (v) => parseFloat(String(v).replace(/−/g, "-").replace(/,(?=\d{3}\b)/g, "").split("±")[0].replace(/[^\d.eE+-]/g, ""));
const errOf = (v) => { const m = String(v).split("±")[1]; return m ? parseFloat(m.replace(/[^\d.eE+-]/g, "")) : 0; };

function tablechart(el, ctx) {
  const b = ctx.paper.blocks.find((x) => x.id === el.dataset.table);
  const rows = b.rows, ncol = b.head.length;
  const numCols = [...Array(ncol).keys()].filter((j) => rows.filter((r) => isNumCell(r[j])).length >= Math.max(2, rows.length * 0.6));
  const labelCols = [...Array(ncol).keys()].filter((j) => !numCols.includes(j));
  // carry labels down (merged cells in the PDF leave the cell below empty)
  const label = (i) => labelCols.map((j) => { for (let k = i; k >= 0; k--) if (rows[k][j]) return k === i ? rows[k][j] : ""; return ""; })
    .filter(Boolean).join(" · ") || `Row ${i + 1}`;
  const full = (i) => labelCols.map((j) => { for (let k = i; k >= 0; k--) if (rows[k][j]) return rows[k][j]; return ""; }).filter(Boolean).join(", ") || `Row ${i + 1}`;
  el.innerHTML = `<div class="controls"><label>Column <select aria-label="Column to chart">${numCols.map((j) => `<option value="${j}">${esc(b.head[j] || `Column ${j + 1}`)}</option>`).join("")}</select></label>
    <button type="button" class="btn quiet sort" aria-pressed="false">Sort by value</button></div>
    <div class="plot"></div><p class="toy">Drawn from the table data read out of the PDF. Hover or tap a bar for its row.</p>`;
  let cj = numCols[0], sorted = false;
  const host = el.querySelector(".plot"), tip = tipFor(host);
  const render = () => {
    const C = col();
    host.querySelectorAll("svg").forEach((x) => x.remove());
    let items = rows.map((r, i) => ({ i, v: numOf(r[cj]), e: errOf(r[cj]), raw: r[cj], lab: full(i) })).filter((d) => isFinite(d.v));
    if (sorted) items = [...items].sort((a, b) => b.v - a.v);
    const H = 22, top = 8, left = 150, W = 560, h = top + items.length * H + 34;
    const lo = Math.min(0, ...items.map((d) => d.v - d.e)), hi = Math.max(0, ...items.map((d) => d.v + d.e)) || 1;
    const s = svg("svg", { viewBox: `0 0 ${W} ${h}`, role: "img", "aria-label": `Bar chart of ${b.head[cj]}` });
    host.append(s);
    const sx = (v) => left + ((v - lo) / (hi - lo)) * (W - left - 16);
    for (const t of niceTicks(lo, hi, 5)) {
      svg("line", { x1: sx(t), x2: sx(t), y1: top, y2: h - 26, class: "gridl" }, s);
      svg("text", { x: sx(t), y: h - 10, "text-anchor": "middle", "font-size": 11 }, s).textContent = fmt(t);
    }
    items.forEach((d, k) => {
      const y = top + k * H;
      const lab = d.lab.length > 24 ? d.lab.slice(0, 23) + "…" : d.lab;
      svg("text", { x: left - 8, y: y + H / 2 + 4, "text-anchor": "end", "font-size": 11 }, s).textContent = lab;
      const x0 = sx(Math.min(0, d.v)), x1 = sx(Math.max(0, d.v));
      svg("rect", { x: x0, y: y + 3, width: Math.max(1, x1 - x0), height: H - 8, rx: 3, fill: C.s1 }, s);
      if (d.e) svg("line", { x1: sx(d.v - d.e), x2: sx(d.v + d.e), y1: y + H / 2 - 1, y2: y + H / 2 - 1, stroke: C.ink, "stroke-width": 1.2 }, s);
      const hit = svg("rect", { x: 0, y, width: W, height: H, fill: "transparent" }, s);
      const show = () => tip.show(`<b>${esc(d.lab)}</b><br>${esc(b.head[cj] || "")}: ${esc(d.raw)}`, (x1 / W) * host.clientWidth, ((y + 4) / W) * host.clientWidth);
      hit.addEventListener("pointerenter", show); hit.addEventListener("pointerdown", show); hit.addEventListener("pointerleave", () => tip.hide());
    });
  };
  el.querySelector("select").onchange = (e) => { cj = +e.target.value; render(); };
  el.querySelector(".sort").onclick = (e) => { sorted = !sorted; e.target.setAttribute("aria-pressed", sorted); render(); };
  render(); onTheme(render);
}

/* ======================= Recovered line plots (proceedings) ======================= */
// Data come from the vector drawing in the PDF (pipeline/digitize.py); names and axis titles from proceedings/interactive.json.
function plot(el, ctx) {
  const spec = ctx.paper.meta.interactive[el.dataset.fig];
  el.innerHTML = `<p class="toy">Loading…</p>`;
  fetch(el.dataset.src).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }).then((D) => drawPlot(el, spec, D))
    .catch((e) => { el.innerHTML = `<p style="color:var(--ink-3)">The interactive version could not load (${esc(e.message)}). The original is in the other tab.</p>`; });
}
function drawPlot(el, spec, D) {
  const S = D.series.map((s, i) => ({ ...s, name: spec.names?.[i] || s.name || `Series ${i + 1}`, on: true,
    pts: [...s.lines.flat(), ...s.markers].sort((a, b) => a[0] - b[0]) }));
  const all = S.flatMap((s) => s.pts.map((p) => p[0]));
  const X0 = Math.min(D.x.ticks[0], ...all), X1 = Math.max(D.x.ticks.at(-1), ...all);
  let lo = X0, hi = X1;
  const csvName = `${el.dataset.fig}.csv`;
  el.innerHTML = `<div class="legend toggles">${S.map((s, i) => `<button type="button" aria-pressed="true" data-i="${i}" class="${s.dash ? "dash" : ""}" style="--c:${s.color === "#000000" ? "var(--ink)" : s.color}">${esc(s.name)}</button>`).join("")}</div>
    <div class="plot zoomable"></div>
    <div class="controls range"><label>From <input type="range" class="r0" min="0" max="1000" value="0" aria-label="Start of the visible range"></label>
      <label>To <input type="range" class="r1" min="0" max="1000" value="1000" aria-label="End of the visible range"></label>
      <button type="button" class="btn quiet reset">Reset zoom</button>
      <button type="button" class="btn quiet csv">Download data (CSV)</button></div>
    <p class="toy">Redrawn from the vector graphics in the PDF; values are as precise as the original drawing.${spec.omitted ? ` Not included: ${esc(spec.omitted)}.` : ""} Hover or tap to read values; drag across the plot (mouse) or use the sliders to zoom.</p>`;
  const host = el.querySelector(".plot"), tip = tipFor(host);
  const r0 = el.querySelector(".r0"), r1 = el.querySelector(".r1");
  const W = host.clientWidth && host.clientWidth < 520 ? 400 : 600, H = W < 600 ? 340 : 320, m = { t: 12, r: D.y2 ? 58 : 14, b: 44, l: 58 };
  let view;
  const yr = (axis) => {
    const ps = S.filter((s) => s.on && s.axis === axis).flatMap((s) => s.pts.filter((p) => p[0] >= lo && p[0] <= hi));
    const full = lo === X0 && hi === X1, tk = (axis === "y2" ? D.y2 : D.y).ticks;
    if (!ps.length) return [tk[0], tk.at(-1)];
    let a = Math.min(...ps.map((p) => p[1])), b = Math.max(...ps.map((p) => p[1]));
    if (full) { a = Math.min(a, tk[0]); b = Math.max(b, tk.at(-1)); }
    const pad = (b - a || Math.abs(a) || 1) * 0.04; return [a - pad, b + pad];
  };
  const render = () => {
    const C = col();
    host.querySelectorAll("svg").forEach((x) => x.remove());
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Line chart: ${spec.y} against ${spec.x}` });
    host.append(s);
    const sx = (v) => m.l + ((v - lo) / (hi - lo)) * (W - m.l - m.r);
    const mk = ([a, b]) => (v) => H - m.b - ((v - a) / (b - a)) * (H - m.t - m.b);
    const ya = yr("y"), sy = mk(ya), ya2 = D.y2 ? yr("y2") : null, sy2 = ya2 ? mk(ya2) : null;
    const g = svg("g", { class: "axis" }, s);
    const full = lo === X0 && hi === X1;
    const xt = full ? D.x.ticks : niceTicks(lo, hi, 5), yt = full ? D.y.ticks : niceTicks(ya[0], ya[1], 5);
    for (const t of yt) { svg("line", { x1: m.l, x2: W - m.r, y1: sy(t), y2: sy(t), class: "gridl" }, g);
      svg("text", { x: m.l - 6, y: sy(t) + 4, "text-anchor": "end", "font-size": 11 }, g).textContent = fmt(t, 4); }
    if (D.y2) for (const t of full ? D.y2.ticks : niceTicks(ya2[0], ya2[1], 5))
      svg("text", { x: W - m.r + 6, y: sy2(t) + 4, "font-size": 11 }, g).textContent = fmt(t, 4);
    for (const t of xt) { svg("line", { x1: sx(t), x2: sx(t), y1: H - m.b, y2: H - m.b + 4 }, g);
      svg("text", { x: sx(t), y: H - m.b + 16, "text-anchor": "middle", "font-size": 11 }, g).textContent = fmt(t, 4); }
    svg("line", { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }, g);
    svg("text", { x: (m.l + W - m.r) / 2, y: H - 6, "text-anchor": "middle", "font-size": 11.5 }, g).textContent = spec.x;
    const yl = (x, txt) => svg("text", { x, y: (m.t + H - m.b) / 2, "text-anchor": "middle", "font-size": 11, transform: `rotate(-90 ${x} ${(m.t + H - m.b) / 2})` }, g).textContent = txt;
    yl(12, spec.y); if (D.y2) yl(W - 8, spec.y2);
    const id = `clip-${el.dataset.fig}-${Math.random().toString(36).slice(2, 7)}`;
    svg("rect", { x: m.l, y: m.t - 2, width: W - m.l - m.r, height: H - m.t - m.b + 2 }, svg("clipPath", { id }, svg("defs", {}, s)));
    const pl = svg("g", { "clip-path": `url(#${id})` }, s);
    S.forEach((se) => {
      if (!se.on) return;
      const Y = se.axis === "y2" ? sy2 : sy, c = se.color === "#000000" ? C.ink : se.color;
      for (const l of se.lines) svg("polyline", { points: l.map((p) => `${sx(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" "), fill: "none", stroke: c, "stroke-width": 1.6, "stroke-dasharray": se.dash ? "5 3" : null, "stroke-linejoin": "round" }, pl);
      for (const p of se.markers) svg("circle", { cx: sx(p[0]), cy: Y(p[1]), r: 3, fill: c }, pl);
    });
    const cross = svg("line", { y1: m.t, y2: H - m.b, stroke: C.ink3, "stroke-dasharray": "2 2", visibility: "hidden" }, s);
    const band = svg("rect", { y: m.t, height: H - m.t - m.b, fill: C.ink3, opacity: 0.15, visibility: "hidden" }, s);
    view = { s, sx, inv: (px) => lo + ((px - m.l) / (W - m.l - m.r)) * (hi - lo), cross, band, sy, sy2 };
  };
  const toX = (e) => { const r = view.s.getBoundingClientRect(); return ((e.clientX - r.left) / r.width) * W; };
  const near = (pts, x) => { let b = null, d = Infinity; for (const p of pts) { const k = Math.abs(p[0] - x); if (k < d) { d = k; b = p; } } return b; };
  const hover = (e) => {
    const px = toX(e); if (px < m.l || px > W - m.r) { tip.hide(); view.cross.setAttribute("visibility", "hidden"); return; }
    const x = view.inv(px);
    view.cross.setAttribute("x1", px); view.cross.setAttribute("x2", px); view.cross.setAttribute("visibility", "visible");
    const at = (s) => { // value on the drawn line at x (linear between drawn points); markers: nearest marker
      for (const l of s.lines) for (let k = 1; k < l.length; k++) {
        const [a, b] = [l[k - 1], l[k]];
        if ((a[0] - x) * (b[0] - x) <= 0) return a[0] === b[0] ? a[1] : a[1] + ((x - a[0]) / (b[0] - a[0])) * (b[1] - a[1]);
      }
      const p = near(s.markers, x); return p && Math.abs(p[0] - x) < (hi - lo) * 0.04 ? p[1] : null;
    };
    const rows = S.filter((s) => s.on).map((s) => { const v = at(s);
      return v === null ? null : `<span style="color:${s.color === "#000000" ? "inherit" : s.color}">■</span> ${esc(s.name)}: <b>${fmt(v, 4)}</b>`; }).filter(Boolean);
    const r = view.s.getBoundingClientRect();
    if (rows.length) tip.show(`${esc(spec.x)} ≈ ${fmt(x, 4)}<br>${rows.join("<br>")}`, (px / W) * r.width, 40); else tip.hide();
  };
  let drag = null;
  host.addEventListener("pointermove", (e) => {
    hover(e);
    if (drag !== null) { const a = Math.min(drag, toX(e)), b = Math.max(drag, toX(e)); view.band.setAttribute("x", a); view.band.setAttribute("width", b - a); view.band.setAttribute("visibility", "visible"); }
  });
  host.addEventListener("pointerdown", (e) => { hover(e); if (e.pointerType === "mouse") drag = toX(e); });
  host.addEventListener("pointerleave", () => { tip.hide(); view.cross.setAttribute("visibility", "hidden"); });
  window.addEventListener("pointerup", (e) => {
    if (drag === null) return;
    const a = view.inv(Math.min(drag, toX(e))), b = view.inv(Math.max(drag, toX(e))); drag = null;
    if (Math.abs(toX(e) - (view.sx(a))) > 8 || b - a > (hi - lo) * 0.02) { lo = Math.max(X0, a); hi = Math.min(X1, b); syncSliders(); }
    render();
  });
  const syncSliders = () => { r0.value = Math.round(((lo - X0) / (X1 - X0)) * 1000); r1.value = Math.round(((hi - X0) / (X1 - X0)) * 1000); };
  const fromSliders = () => { let a = +r0.value, b = +r1.value; if (b - a < 10) { if (document.activeElement === r0) a = b - 10; else b = a + 10; }
    lo = X0 + (a / 1000) * (X1 - X0); hi = X0 + (b / 1000) * (X1 - X0); render(); };
  r0.oninput = r1.oninput = fromSliders;
  el.querySelector(".reset").onclick = () => { lo = X0; hi = X1; syncSliders(); render(); };
  host.addEventListener("dblclick", () => { lo = X0; hi = X1; syncSliders(); render(); });
  el.querySelectorAll(".toggles button").forEach((b) => b.onclick = () => {
    const se = S[+b.dataset.i]; se.on = !se.on; b.setAttribute("aria-pressed", se.on); render(); });
  el.querySelector(".csv").onclick = () => {
    const q = (v) => /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
    const lines = [["series", spec.x, "value"].map(q).join(",")];
    for (const s of S) for (const p of s.pts) lines.push([q(s.name), p[0], p[1]].join(","));
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })); a.download = csvName; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  render(); onTheme(render);
}

export const WIDGETS = { plot, tablechart,  sampling2d, workflow, activations, montgomery3d, montgomerystep, composite, table5chart, table6chart, table7chart, appendixA, nnembed };

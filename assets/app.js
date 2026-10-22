// SPAICE interactive proceedings — reader app. Plain ES modules, no build step.
import { WIDGETS } from "./widgets.js";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const strip = (html) => html.replace(/<[^>]+>/g, "");
const store = {
  get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch {} },
};
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const ICON = {
  toc: '<svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h10M4 18h13"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></svg>',
  terms: '<svg viewBox="0 0 24 24"><path d="M5 4.5h10a4 4 0 0 1 4 4V20H9a4 4 0 0 1-4-4z"/><path d="M9 9h6M9 13h4"/></svg>',
  settings: '<svg viewBox="0 0 24 24"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg>',
};

/* ---------- maths: $…$ inline, $$…$$ display (KaTeX from the CDN; raw TeX if it failed to load) ---------- */
function tex(src, display = false) {
  if (!window.katex) return `<code>${esc(src)}</code>`;
  try { return katex.renderToString(src, { displayMode: display, throwOnError: false, output: "htmlAndMathml" }); }
  catch { return `<code>${esc(src)}</code>`; }
}
const math = (html) => html
  .replace(/\$\$([\s\S]+?)\$\$/g, (_, t) => tex(t, true))
  .replace(/\$([^$]+?)\$/g, (_, t) => tex(t));

/* ---------- boot ---------- */
let P, G, N, base; // paper, glossary, notes, paper folder
const params = new URLSearchParams(location.search);
const paperId = params.get("p");
applySettings();
(paperId ? openPaper(paperId) : openLibrary()).catch((e) => {
  $("#main").innerHTML = `<p class="loading">Could not load this page: ${esc(e.message)}.<br><a href="./">Back to all papers</a></p>`;
  console.error(e);
});

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} returned ${r.status}`);
  return r.json();
}

/* ---------- library ---------- */
async function openLibrary() {
  const list = await getJSON("papers/index.json");
  document.title = "SPAICE Interactive Proceedings";
  $("#app").innerHTML = `<main id="main" class="library">
    <h1>SPAICE interactive proceedings</h1>
    <p>Papers from the proceedings, rebuilt for reading on screen. Every figure you can explore, every unfamiliar term you can tap, and the original PDF page is always one tap away.</p>
    ${list.map((p) => `<a class="papercard" href="?p=${encodeURIComponent(p.id)}">
        <h2>${esc(p.title)}</h2><p>${esc(p.authors)} · ${esc(p.venue)}</p>
        <p class="feat">${esc(p.features)}</p></a>`).join("")}
  </main>`;
}

/* ---------- paper ---------- */
async function openPaper(id) {
  base = `papers/${id}/`;
  [P, G, N] = await Promise.all([getJSON(base + "paper.json"), getJSON(base + "glossary.json").catch(() => ({ terms: [] })),
                                getJSON(base + "notes.json").catch(() => ({ sections: {} }))]);
  document.title = P.meta.title;
  $("#app").innerHTML = `<div class="reader"><nav class="toc" aria-label="Contents"></nav>
    <article id="main" lang="en">${header()}${body()}${back()}</article></div>${toolbar()}`;
  buildToc();
  enrich($("article"));
  mountWidgets();
  wire();
  if (location.hash) { // deep link: land instantly, then correct once widgets near the target have mounted
    const id = decodeURIComponent(location.hash.slice(1)), go = () => document.getElementById(id)?.scrollIntoView();
    requestAnimationFrame(go); setTimeout(go, 400); setTimeout(go, 1200);
  }
}

function header() {
  const m = P.meta;
  const authors = m.authors.map((a) => `${esc(a.name)}<a class="orcid" href="https://orcid.org/${a.orcid}" title="ORCID ${a.orcid}" aria-label="ORCID of ${esc(a.name)}"></a>`).join(" and ");
  const tl = N.tldr ? `<div class="added tldr"><span class="who">Reader’s guide · added for this site</span><p>${esc(N.tldr)}</p>
      ${N.takeaways ? `<ul>${N.takeaways.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}</div>` : "";
  return `<header>
    <p class="kicker"><a href="./">All papers</a> / ${esc(m.articleType)} in ${esc(m.journal)}, ${m.year}</p>
    <h1 class="title">${esc(m.title)}</h1>
    <p class="authors">${authors}</p>
    <p class="affil">${esc(m.affiliations["1"])}</p>
    <div class="meta">
      <a href="${base}${m.pdf}" download>Download PDF</a>
      <a href="https://doi.org/${m.doi}" target="_blank" rel="noopener">DOI ${esc(m.doi)}</a>
      <a href="${esc(m.code)}" target="_blank" rel="noopener">Source code</a>
      <button type="button" data-act="cite">Cite</button>
    </div>
    <p class="dates">Received ${esc(m.received)}; accepted ${esc(m.accepted)}. © The Author(s). Licensed under <a href="${m.licenseUrl}">${esc(m.license)}</a>.</p>
    ${tl}
  </header>`;
}

function plainNote(id) {
  const t = N.sections?.[id];
  return t ? `<details class="plain"><summary>In plain words</summary><div class="added"><span class="who">Added for this site</span>${esc(t)}</div></details>` : "";
}

function body() {
  let out = "", page = 1, kw = false;
  for (const b of P.blocks) {
    if ((b.t === "p" || b.t === "h") && b.page > page) {
      page = b.page;
      out += `<div class="pagemark" role="separator"><button type="button" data-page="${page}">PDF page ${page}</button></div>`;
    }
    out += block(b);
    if (b.t === "p" && !kw) { kw = true; out += `<p class="keywords"><b>Keywords:</b> ${P.meta.keywords.map(esc).join(", ")}</p>`; }
  }
  return out;
}

function block(b) {
  switch (b.t) {
    case "h": {
      const tag = b.level === 1 ? "h2" : b.level === 2 ? (b.num === "Abstract" ? "h2" : "h3") : "h4";
      const top = b.level === 1 && b.num?.match(/^\d/) || b.num === "Abstract" || /^[AB]$/.test(b.num);
      const label = /^[AB]$/.test(b.num) ? `Appendix ${b.num}` : b.num === "Abstract" ? "" : b.num;
      const fn = b.fn ? `<sup class="fn" data-fn="${b.fn}">${b.fn}</sup>` : "";
      const t = top ? "h2" : tag;
      return `<${t} id="${b.id}" data-toc="${top ? 1 : tag === "h3" ? 2 : 3}" data-label="${esc((label ? label + " " : "") + b.title)}">${label ? `<span class="n">${label}</span>` : ""}${esc(b.title)}${fn}<a class="hlink" href="#${b.id}" aria-label="Link to this section">#</a></${t}>${plainNote(b.id)}`;
    }
    case "p": {
      const note = b.sitenote ? `<button type="button" class="sitenote" data-note="${esc(b.sitenote)}">site note</button>` : "";
      return `<p data-page="${b.page}"${b.html.startsWith("Simulation–optimization is often") ? ' class="abstract"' : ""}>${math(linkify(b.html))}${note}</p>`;
    }
    case "list": {
      const tag = b.ordered ? "ol" : "ul";
      return `<${tag} data-page="${b.page}">${b.items.map((i) => `<li>${math(i)}</li>`).join("")}</${tag}>`;
    }
    case "eq":
      return `<div class="eq" id="${b.id}"><div class="m">${tex(b.tex, true)}</div><span class="no">(${b.num})</span></div>`;
    case "figure": return figure(b);
    case "table": return table(b);
    case "algo": return algo(b);
    case "code": return code(b);
    case "explainer":
      return `<div class="added"><span class="who">${esc(b.title)} · added for this site</span><div class="w" data-widget="${b.widget}"></div></div>`;
  }
  return "";
}

const tabs = (id, list, page) => `<div class="tabs" role="tablist">${list.map(([k, label], i) =>
  `<button role="tab" type="button" aria-selected="${i === 0}" aria-controls="${id}-${k}" data-tab="${k}">${label}</button>`).join("")}
  <span class="spacer"></span><button type="button" class="pg" data-page="${page}" aria-label="Show PDF page ${page}">p. ${page}</button></div>`;

function figure(b) {
  const has = b.widget && WIDGETS[b.widget];
  const t = has ? tabs(b.id, [["live", "Interactive"], ["orig", "Original"]], b.page) : tabs(b.id, [["orig", "Original"]], b.page);
  return `<figure id="${b.id}" class="wide">${t}
    ${has ? `<div class="panel w" id="${b.id}-live" data-widget="${b.widget}" role="tabpanel"></div>` : ""}
    <div class="panel" id="${b.id}-orig" role="tabpanel" ${has ? "hidden" : ""}><img class="orig" src="${base}${b.img}" alt="${esc(b.alt)}" loading="lazy" data-zoom${b.imgSize ? ` width="${b.imgSize[0]}" height="${b.imgSize[1]}"` : ""}></div>
    <figcaption><b>Figure ${b.num}.</b> ${b.caption}</figcaption></figure>`;
}

function table(b) {
  const isNum = (v) => /^[\d.,]+( ± [\d.]+)?$/.test(v);
  const bold = new Set((b.bold || []).map(([r, c]) => `${r},${c}`));
  const rows = b.rows.map((r, i) => `<tr data-i="${i}">${r.map((v, j) =>
    `<td class="${isNum(v) ? "num" : ""}${bold.has(`${i},${j}`) ? " b" : ""}">${esc(v)}</td>`).join("")}</tr>`).join("");
  const sortable = b.rows.length > 4;
  const head = b.head.map((h, j) => sortable ? `<th scope="col" aria-sort="none"><button type="button" data-col="${j}">${esc(h)}<span class="arrow"></span></button></th>` : `<th scope="col">${esc(h)}</th>`).join("");
  const has = b.widget && WIDGETS[b.widget];
  return `<div class="float wide" id="${b.id}"><div class="cap top"><b>Table ${b.num}.</b> ${b.caption}</div>
    ${tabs(b.id, has ? [["tab", "Table"], ["live", "Chart"]] : [["tab", "Table"]], b.page)}
    <div class="panel" id="${b.id}-tab" role="tabpanel"><div class="tablewrap"><table class="data"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div></div>
    ${has ? `<div class="panel w" id="${b.id}-live" data-widget="${b.widget}" role="tabpanel" hidden></div>` : ""}
    ${b.note ? `<div class="tnote">${b.note}</div>` : ""}</div>`;
}

const LINE_NOTES = {
  alg1: ["Load the trained neural network, so its inputs and outputs can be used as variables.",
    "Limits on how much of each ingredient can be bought (for example, seasonal availability).",
    "The decision: how much of each ingredient to buy every period. The solver chooses these.",
    "Predicted spoilage, computed by the embedded network from the buying strategy.",
    "Predicted share of successful orders, also computed by the network.",
    "Each purchase amount must stay between 0 and its limit.",
    "The weighted composite objective: reward success, penalize spoilage. Changing the two weights asks for a different trade-off."],
};
function algo(b) {
  const inner = b.code
    ? `<pre class="code" data-lines="${b.id}">${b.code.split("\n").map((l, i) => `<span class="ln" data-i="${i}"><span class="num">${i + 1}</span>${hl(l)}</span>`).join("")}</pre>
       <div class="linenote" aria-live="polite"><span class="who" style="color:var(--add);font-weight:600;font-size:.75rem">Tap a line for an explanation · added for this site</span></div>`
    : `<div class="algo">${b.lines.map(([ind, l, c], i) => `<div class="row" data-i="${i}"><div style="padding-left:${ind * 1.3}rem">${math(l)}</div>${c ? `<div class="c">${math(c)}</div>` : "<div></div>"}</div>`).join("")}</div>`;
  const has = b.widget && WIDGETS[b.widget];
  return `<div class="float wide" id="${b.id}"><div class="cap top"><b>Algorithm ${b.num}.</b> ${b.caption}</div>
    ${tabs(b.id, has ? [["tab", "Algorithm"], ["live", "Step through"]] : [["tab", "Algorithm"]], b.page)}
    <div class="panel" id="${b.id}-tab" role="tabpanel" style="padding:0">${inner}</div>
    ${has ? `<div class="panel w" id="${b.id}-live" data-widget="${b.widget}" role="tabpanel" hidden></div>` : ""}</div>`;
}

function hl(line) {
  return esc(line).replace(/^(\s*)(include|float|var|constraint|solve|maximize|forall|in)\b/g, '$1<span class="kw">$2</span>')
    .replace(/\b(constraint|forall|maximize|max|var|float)\b(?![^<]*>)/g, '<span class="kw">$1</span>')
    .replace(/<span class="kw"><span class="kw">(\w+)<\/span><\/span>/g, '<span class="kw">$1</span>');
}

function code(b) {
  // Pretty-print the long neuron constraints: one weighted input per line.
  const pretty = b.lines.map((l, i) => {
    const m = l.match(/^constraint \((\S+) = (max\(\(|\()(.*?)\)(?:, 0\))?\);$/);
    let body = esc(l);
    if (m && l.length > 120) {
      const terms = m[3].split(/ \+ /);
      const relu = m[2].startsWith("max");
      body = `<span class="kw">constraint</span> (${esc(m[1])} = ${relu ? '<span class="kw">max</span>((' : "("}\n` +
        terms.map((t) => "    " + esc(t)).join(" +\n") + (relu ? "), 0));" : "));");
    } else body = hl(l);
    return `<span class="ln" data-i="${i}" id="appB-l${i + 1}"><span class="num">${i + 1}</span>${body}</span>`;
  }).join("");
  return `<div class="float wide" id="${b.id}">
    ${tabs(b.id, [["live", "Network view"], ["tab", "Code"]], b.page)}
    <div class="panel w" id="${b.id}-live" data-widget="${b.widget}" role="tabpanel"></div>
    <div class="panel" id="${b.id}-tab" role="tabpanel" hidden style="padding:0"><pre class="code">${pretty}</pre></div></div>`;
}

function back() {
  const B = P.back;
  return `<section class="back">
    <h2 id="acknowledgments" data-toc="1" data-label="Acknowledgments">Acknowledgments</h2><p>${esc(B.acknowledgments)}</p>
    <h2 id="funding" data-toc="1" data-label="Funding">Funding</h2><p>${esc(B.funding)}</p>
    <h2 id="conflicts">Declaration of Conflicting Interests</h2><p>${esc(B.conflicts)}</p>
    <h2 id="notes">Notes</h2><ol>${Object.entries(B.notes).map(([k, v]) => `<li id="note${k}">${esc(v)}</li>`).join("")}</ol>
    <h2 id="references" data-toc="1" data-label="References">References</h2>
    <ol class="refs">${P.references.map((r) => `<li id="${r.id}">${linkify(esc(r.text))}</li>`).join("")}</ol>
    <p class="license">This interactive edition re-presents the article above under its ${esc(P.meta.license)} licence, with attribution to the authors. The PDF is the version of record: use the <b>PDF page</b> buttons to compare any passage with the original. Explanations, plain-language notes and the interactive versions of figures and tables were added for this site and are marked as such; they are not part of the peer-reviewed article.</p>
  </section>`;
}
const linkify = (s) => s.replace(/(https?:\/\/[^\s<]+[^\s<.,;)])/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');

function toolbar() {
  return `<div class="toolbar" role="toolbar" aria-label="Reading tools">
    <button type="button" class="tocbtn" data-sheet="toc" aria-expanded="false">${ICON.toc}<span class="lbl">Contents</span></button>
    <button type="button" data-sheet="search" aria-expanded="false">${ICON.search}<span class="lbl">Search</span></button>
    <button type="button" data-sheet="terms" aria-expanded="false">${ICON.terms}<span class="lbl">Terms</span></button>
    <button type="button" data-sheet="settings" aria-expanded="false" aria-label="Reading settings">${ICON.settings}<span class="lbl">Display</span></button>
  </div>`;
}

/* ---------- contents + scroll spy + progress ---------- */
function tocHTML() {
  return `<a class="back" href="./">All papers</a>` + $$("article [data-toc]").map((h) =>
    `<a href="#${h.id}" class="l${h.dataset.toc}" data-for="${h.id}">${esc(h.dataset.label || h.textContent)}</a>`).join("");
}
function buildToc() {
  $("nav.toc").innerHTML = tocHTML();
  const heads = $$("article [data-toc]");
  let current;
  const spy = () => {
    const y = scrollY + 120;
    let on = heads[0];
    for (const h of heads) if (h.offsetTop <= y) on = h;
    if (on !== current) {
      current = on;
      $$(".toc a[data-for]").forEach((a) => a.classList.toggle("on", a.dataset.for === on.id));
    }
    const max = document.documentElement.scrollHeight - innerHeight;
    $("#progress").style.width = `${Math.min(100, (scrollY / max) * 100)}%`;
  };
  addEventListener("scroll", spy, { passive: true });
  spy();
}

/* ---------- inline enrichment: citations, cross-references, glossary terms ---------- */
function enrich(root) {
  const refs = P.references.filter((r) => r.year);
  const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const cites = refs.map((r) => ({ r, re: `${reEsc(r.cite)}(?:, ${r.year}| \\(${r.year}\\))` }));
  const citeRe = new RegExp(cites.map((c) => `(${c.re})`).join("|"), "g");
  const xrefRe = /\b(Figure|Table|Algorithm|Section|Appendix)\s+(\d+(?:\.\d+)*|[AB])\b/g;
  const xrefTarget = (kind, n) => ({ Figure: `fig${n}`, Table: `tab${n}`, Algorithm: `alg${n}`, Section: `s${n.replace(/\./g, "-")}`, Appendix: `app${n}` }[kind]);

  const terms = G.terms.flatMap((t, i) => t.match.map((m) => ({ m, i })));
  terms.sort((a, b) => b.m.length - a.m.length);
  const termRe = new RegExp(`(?<![\\w\\-])(${terms.map((t) => reEsc(t.m)).join("|")})(?![\\w\\-])`, "g");
  const termOf = Object.fromEntries(terms.map((t) => [t.m, t.i]));

  const SKIP = new Set(["A", "BUTTON", "CODE", "PRE", "B", "SUMMARY", "H2", "H3", "H4", "SCRIPT", "SVG", "TEXT"]);
  const skip = (el) => el.closest(".katex, .added, .w, .tabs, .meta, .kicker, .authors, .affil, .dates, .refs, header, pre, .algo .c b");
  let section = "top", seen = new Set();

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  const textNodes = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.nodeType === 1) { if (/^H[234]$/.test(n.tagName) && n.id) textNodes.push({ heading: n.id }); continue; }
    const el = n.parentElement;
    if (!n.nodeValue.trim() || SKIP.has(el.tagName) || skip(el)) continue;
    textNodes.push(n);
  }
  for (const n of textNodes) {
    if (n.heading) { section = n.heading; seen = new Set(); continue; }
    const s = n.nodeValue;
    const inPaperText = n.parentElement.closest("p, li");
    const spans = [];
    for (const m of s.matchAll(citeRe)) {
      const ref = cites[m.slice(1).findIndex(Boolean)].r;
      spans.push([m.index, m[0].length, `<a class="cite" href="#${ref.id}" data-ref="${ref.id}">${esc(m[0])}</a>`]);
    }
    for (const m of s.matchAll(xrefRe)) {
      const id = xrefTarget(m[1], m[2]);
      if (document.getElementById(id)) spans.push([m.index, m[0].length, `<a class="xref" href="#${id}" data-xref="${id}">${esc(m[0])}</a>`]);
    }
    if (inPaperText) for (const m of s.matchAll(termRe)) {
      const i = termOf[m[1]];
      if (seen.has(i)) continue;
      seen.add(i);
      spans.push([m.index, m[0].length, `<span class="term" tabindex="0" role="button" data-term="${i}">${esc(m[0])}</span>`]);
    }
    if (!spans.length) continue;
    spans.sort((a, b) => a[0] - b[0]);
    let html = "", at = 0;
    for (const [i, len, rep] of spans) { if (i < at) continue; html += esc(s.slice(at, i)) + rep; at = i + len; }
    html += esc(s.slice(at));
    const tpl = document.createElement("template");
    tpl.innerHTML = html;
    n.replaceWith(tpl.content);
  }
}

/* ---------- widgets ---------- */
function mountWidgets() {
  const ctx = { paper: P, tex, math, jump, base };
  const io = "IntersectionObserver" in window ? new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting || e.target.offsetParent === null) { /* hidden panels mount when shown */ }
    if (e.isIntersecting) { io.unobserve(e.target); mount(e.target); }
  }), { rootMargin: "400px" }) : null;
  const mount = (el) => {
    if (el.dataset.mounted) return;
    el.dataset.mounted = 1;
    try { WIDGETS[el.dataset.widget]?.(el, ctx); }
    catch (e) { el.innerHTML = `<p style="color:var(--ink-3)">This interactive view could not start (${esc(e.message)}). The original is in the other tab.</p>`; console.error(e); }
  };
  $$("[data-widget]").forEach((el) => (io && !el.hidden ? io.observe(el) : null));
  ctx.mount = mount;
  window.__mountWidget = mount;
}

/* ---------- events ---------- */
function wire() {
  const art = $("article");
  document.addEventListener("click", (e) => {
    const t = e.target;
    const tab = t.closest("[data-tab]");
    if (tab) return switchTab(tab);
    const pg = t.closest("[data-page]");
    if (pg && pg.tagName === "BUTTON") return viewer({ page: +pg.dataset.page });
    const zoom = t.closest("img[data-zoom]");
    if (zoom) return viewer({ src: zoom.src, title: zoom.closest("figure").querySelector("figcaption b").textContent });
    const term = t.closest(".term");
    if (term && !document.body.classList.contains("no-terms")) return termPop(term);
    const cite = t.closest(".cite");
    if (cite) { e.preventDefault(); return citePop(cite); }
    const fn = t.closest("sup.fn");
    if (fn) return pop(fn, `<span class="who">Note ${fn.dataset.fn} in the paper</span><p>${esc(P.back.notes[fn.dataset.fn])}</p>`);
    const sn = t.closest(".sitenote");
    if (sn) return pop(sn, `<span class="who">Site note · not part of the paper</span><p>${esc(sn.dataset.note)}</p>`);
    const x = t.closest("a.xref, .toc a[href^='#'], a.more[href^='#'], .results a, .hlink");
    if (x) { e.preventDefault(); closePop(); closeSheet(); return jump(x.getAttribute("href").slice(1)); }
    const sheetBtn = t.closest("[data-sheet]");
    if (sheetBtn) return openSheet(sheetBtn.dataset.sheet, sheetBtn);
    if (t.closest("[data-act=cite]")) return citeThis(t.closest("button"));
    const th = t.closest("th button[data-col]");
    if (th) return sortTable(th);
    const ln = t.closest("pre.code[data-lines] .ln");
    if (ln) return lineNote(ln);
    if (!t.closest(".pop")) closePop();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closePop(); closeSheet(); closeViewer(); }
    if ((e.key === "Enter" || e.key === " ") && e.target.classList?.contains("term")) { e.preventDefault(); termPop(e.target); }
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); openSheet("search"); }
  });
  // desktop hover preview for cross-references
  let hov;
  art.addEventListener("mouseover", (e) => {
    const x = e.target.closest("a.xref");
    if (!x || matchMedia("(hover: none)").matches) return;
    clearTimeout(hov);
    hov = setTimeout(() => xrefPreview(x), 350);
  });
  art.addEventListener("mouseout", (e) => { if (e.target.closest("a.xref")) clearTimeout(hov); });
}

function switchTab(btn) {
  const wrap = btn.closest(".tabs").parentElement;
  const k = btn.dataset.tab;
  $$(":scope > .tabs [data-tab]", wrap).forEach((b) => b.setAttribute("aria-selected", b === btn));
  $$(":scope > .panel", wrap).forEach((p) => { p.hidden = !p.id.endsWith("-" + k); if (!p.hidden && p.dataset.widget) window.__mountWidget(p); });
}

function sortTable(btn) {
  const th = btn.parentElement, table = th.closest("table"), col = +btn.dataset.col;
  const dir = th.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
  $$("th", table).forEach((h) => { h.setAttribute("aria-sort", "none"); const a = $(".arrow", h); if (a) a.textContent = ""; });
  th.setAttribute("aria-sort", dir);
  $(".arrow", th).textContent = dir === "ascending" ? "▲" : "▼";
  const val = (tr) => { const s = tr.children[col].textContent; const n = parseFloat(s); return isNaN(n) ? s : n; };
  const rows = $$("tbody tr", table).sort((a, b) => { const x = val(a), y = val(b); const c = x < y ? -1 : x > y ? 1 : +a.dataset.i - +b.dataset.i; return dir === "ascending" ? c : -c; });
  $("tbody", table).append(...rows);
}

function lineNote(ln) {
  const pre = ln.closest("pre"), notes = LINE_NOTES[pre.dataset.lines];
  $$(".ln", pre).forEach((l) => l.classList.toggle("on", l === ln));
  const box = pre.nextElementSibling;
  box.innerHTML = `<span class="who" style="color:var(--add);font-weight:600;font-size:.75rem">Line ${+ln.dataset.i + 1} · explanation added for this site</span><br>${esc(notes?.[ln.dataset.i] || "")}`;
}

/* ---------- navigation with a way back ---------- */
let backChip;
function jump(id, remember = true) {
  const el = document.getElementById(id);
  if (!el) return;
  const from = scrollY;
  const panel = el.closest(".panel[hidden]");
  if (panel) switchTab($(`[data-tab="${panel.id.split("-").pop()}"]`, panel.parentElement));
  el.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: el.matches("h2,h3,h4") ? "start" : "center" });
  history.replaceState(null, "", "#" + id);
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
  if (remember && Math.abs(from - el.getBoundingClientRect().top - scrollY) > innerHeight) {
    backChip?.remove();
    backChip = document.createElement("button");
    backChip.type = "button";
    backChip.className = "toolbar";
    backChip.style.cssText = "bottom:4.6rem;padding:.55rem 1rem;cursor:pointer";
    backChip.textContent = "Back to where you were";
    backChip.onclick = () => { scrollTo({ top: from, behavior: reduceMotion ? "auto" : "smooth" }); backChip.remove(); };
    document.body.append(backChip);
    setTimeout(() => backChip?.remove(), 9000);
  }
}

/* ---------- popovers ---------- */
let popEl;
function pop(anchor, html) {
  closePop();
  popEl = document.createElement("div");
  popEl.className = "pop";
  popEl.setAttribute("role", "dialog");
  popEl.innerHTML = html;
  document.body.append(popEl);
  const r = anchor.getBoundingClientRect();
  const w = popEl.offsetWidth;
  popEl.style.left = `${Math.max(12, Math.min(scrollX + r.left, scrollX + innerWidth - w - 12))}px`;
  const below = r.bottom + popEl.offsetHeight + 12 < innerHeight;
  popEl.style.top = `${scrollY + (below ? r.bottom + 8 : r.top - popEl.offsetHeight - 8)}px`;
}
function closePop() { popEl?.remove(); popEl = null; }
function termPop(el) {
  const t = G.terms[el.dataset.term];
  const see = t.see && document.getElementById(t.see) ? `<a class="more" href="#${t.see}">Where the paper covers this</a>` : "";
  pop(el, `<span class="who">Explanation added for this site</span><h3>${esc(t.term)}</h3><p>${esc(t.def)}</p>${see}`);
}
function citePop(el) {
  const r = P.references.find((x) => x.id === el.dataset.ref);
  pop(el, `<span class="who" style="color:var(--ink-3)">Reference</span><p>${linkify(esc(r.text))}</p><a class="more" href="#${r.id}">In the reference list</a>`);
  $("a.more", popEl).onclick = (e) => { e.preventDefault(); closePop(); jump(r.id); };
}
function xrefPreview(a) {
  const el = document.getElementById(a.dataset.xref);
  const cap = el.querySelector("figcaption, .cap");
  const img = el.querySelector("img.orig");
  const h = el.matches("h2,h3,h4") ? `<p><b>${esc(el.textContent.replace(/#$/, ""))}</b></p><p>${esc(strip(el.nextElementSibling?.nextElementSibling?.innerHTML || "").slice(0, 220))}…</p>` : "";
  pop(a, cap ? `${img ? `<img src="${img.src}" alt="">` : ""}<p>${cap.innerHTML.slice(0, 400)}</p>` : h);
}
function citeThis(btn) {
  const m = P.meta;
  const apa = `${m.authors.map((a) => a.name).join(", & ").replace(/Sytze P\. E\. Andringa/, "Andringa, S. P. E.").replace(/Neil Yorke-Smith/, "Yorke-Smith, N.")} (${m.year}). ${m.title}. ${m.journal}. https://doi.org/${m.doi}`;
  const bib = `@article{andringa${m.year}neuro,\n  title   = {${m.title}},\n  author  = {${m.authors.map((a) => a.name).join(" and ")}},\n  journal = {${m.journal}},\n  year    = {${m.year}},\n  doi     = {${m.doi}}\n}`;
  pop(btn, `<span class="who" style="color:var(--ink-3)">Cite this article</span><p>${esc(apa)}</p>
    <p><button type="button" class="more" data-copy="apa">Copy APA</button> &nbsp; <button type="button" class="more" data-copy="bib">Copy BibTeX</button></p>`);
  popEl.querySelectorAll("[data-copy]").forEach((b) => (b.style.cssText = "border:0;background:none;color:var(--act);cursor:pointer;padding:0",
    b.onclick = async () => { try { await navigator.clipboard.writeText(b.dataset.copy === "apa" ? apa : bib); b.textContent = "Copied"; } catch { b.textContent = "Copy not allowed here"; } }));
}

/* ---------- sheets: contents, search, terms, settings ---------- */
let sheetEl, scrimEl, sheetBtn;
function closeSheet() { sheetEl?.remove(); scrimEl?.remove(); sheetEl = scrimEl = null; sheetBtn?.setAttribute("aria-expanded", "false"); sheetBtn?.focus?.(); sheetBtn = null; }
function openSheet(kind, btn = $(`[data-sheet=${kind}]`)) {
  const again = sheetBtn === btn;
  closeSheet();
  if (again) return;
  sheetBtn = btn; btn?.setAttribute("aria-expanded", "true");
  scrimEl = document.createElement("div"); scrimEl.className = "scrim"; scrimEl.onclick = closeSheet;
  sheetEl = document.createElement("section"); sheetEl.className = "sheet"; sheetEl.setAttribute("role", "dialog"); sheetEl.setAttribute("aria-modal", "true");
  const title = { toc: "Contents", search: "Search this paper", terms: "Terms explained", settings: "Display" }[kind];
  sheetEl.setAttribute("aria-label", title);
  sheetEl.innerHTML = `<header><h2>${title}</h2><button type="button" class="x" aria-label="Close">×</button></header><div class="body"></div>`;
  $(".x", sheetEl).onclick = closeSheet;
  document.body.append(scrimEl, sheetEl);
  const bodyEl = $(".body", sheetEl);
  if (kind === "toc") bodyEl.innerHTML = `<nav class="toc">${tocHTML()}</nav>`;
  if (kind === "terms") bodyEl.innerHTML = `<p class="hint">Written for this site to help readers new to the field. Underlined terms in the text open these too.</p><dl class="gloss">${
    [...G.terms].sort((a, b) => a.term.localeCompare(b.term)).map((t) => `<dt>${esc(t.term)}</dt><dd>${esc(t.def)}${t.see && document.getElementById(t.see) ? ` <a class="more" href="#${t.see}">In the paper</a>` : ""}</dd>`).join("")}</dl>`;
  if (kind === "search") searchSheet(bodyEl);
  if (kind === "settings") settingsSheet(bodyEl);
  ($("input", sheetEl) || $(".x", sheetEl)).focus();
}

let searchIndex;
function searchSheet(el) {
  searchIndex ??= $$("article p, article li, article figcaption, article .cap, article td, article .tnote").filter((e) => !e.closest(".added, .w")).map((e) => {
    const sec = [...$$("article [data-toc]")].filter((h) => h.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING).pop();
    const c = e.cloneNode(true); // index maths by its TeX source, not by KaTeX's doubled visual+MathML text
    c.querySelectorAll(".katex").forEach((k) => k.replaceWith(k.querySelector("annotation")?.textContent || ""));
    return { e, text: c.textContent.replace(/\s+/g, " "), sec: sec ? sec.dataset.label || sec.textContent : "Front matter" };
  });
  el.innerHTML = `<input type="search" placeholder="Search words or numbers, e.g. Montgomery" aria-label="Search this paper" enterkeyhint="search"><p class="hint" aria-live="polite"></p><ul class="results"></ul>`;
  const input = $("input", el), hint = $(".hint", el), ul = $(".results", el);
  input.value = store.get("ip-q", "");
  const run = () => {
    const q = input.value.trim(); store.set("ip-q", q);
    $$("mark.hit").forEach((m) => m.replaceWith(m.textContent));
    if (q.length < 2) { ul.innerHTML = ""; hint.textContent = "Type at least two characters."; return; }
    const ql = q.toLowerCase();
    const hits = searchIndex.filter((x) => x.text.toLowerCase().includes(ql));
    hint.textContent = `${hits.length} match${hits.length === 1 ? "" : "es"}`;
    ul.innerHTML = hits.slice(0, 60).map((x, i) => {
      const at = x.text.toLowerCase().indexOf(ql), s = Math.max(0, at - 50);
      const snip = (s ? "…" : "") + esc(x.text.slice(s, at)) + `<mark class="hit">${esc(x.text.slice(at, at + q.length))}</mark>` + esc(x.text.slice(at + q.length, at + q.length + 70)) + "…";
      if (!x.e.id) x.e.id = `hit${searchIndex.indexOf(x)}`;
      return `<li><a href="#${x.e.id}"><small>${esc(x.sec)}</small>${snip}</a></li>`;
    }).join("");
    hits.forEach((x) => markIn(x.e, q));
  };
  input.addEventListener("input", run);
  run();
}
function markIn(el, q) {
  const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), ql = q.toLowerCase(), nodes = [];
  for (let n = w.nextNode(); n; n = w.nextNode()) if (!n.parentElement.closest(".katex") && n.nodeValue.toLowerCase().includes(ql)) nodes.push(n);
  for (const n of nodes) {
    const i = n.nodeValue.toLowerCase().indexOf(ql);
    const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + q.length);
    const m = document.createElement("mark"); m.className = "hit"; r.surroundContents(m);
  }
}

function applySettings() {
  const t = store.get("ip-theme", "auto");
  if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  document.documentElement.style.setProperty("--text-scale", store.get("ip-size", "1"));
  document.body.classList.toggle("no-terms", store.get("ip-terms", "on") === "off");
  document.body.classList.toggle("no-notes", store.get("ip-notes", "on") === "off");
}
function settingsSheet(el) {
  const seg = (key, opts, cur) => `<div class="w"><div class="seg" data-key="${key}">${opts.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${v === cur}">${l}</button>`).join("")}</div></div>`;
  el.innerHTML = `
    <div class="setting"><span>Theme</span>${seg("ip-theme", [["auto", "Auto"], ["light", "Light"], ["dark", "Dark"]], store.get("ip-theme", "auto"))}</div>
    <div class="setting"><span>Text size</span>${seg("ip-size", [["0.9", "A−"], ["1", "A"], ["1.12", "A+"], ["1.25", "A++"]], store.get("ip-size", "1"))}</div>
    <div class="setting"><span>Explain terms<small>Underline jargon; tap for an explanation</small></span>${seg("ip-terms", [["on", "On"], ["off", "Off"]], store.get("ip-terms", "on"))}</div>
    <div class="setting"><span>Reader’s notes<small>Plain-language summaries per section</small></span>${seg("ip-notes", [["on", "On"], ["off", "Off"]], store.get("ip-notes", "on"))}</div>
    <p class="hint">Everything this site adds to the paper is shown in green, so you can always tell it apart from the authors’ text.</p>`;
  el.addEventListener("click", (e) => {
    const b = e.target.closest(".seg button"); if (!b) return;
    const s = b.parentElement;
    $$("button", s).forEach((x) => x.setAttribute("aria-pressed", x === b));
    store.set(s.dataset.key, b.dataset.v);
    applySettings();
    document.dispatchEvent(new CustomEvent("themechange"));
  });
}

/* ---------- full-screen viewer: PDF pages and original figures ---------- */
let viewerEl;
function closeViewer() { viewerEl?.remove(); viewerEl = null; }
function viewer({ page, src, title }) {
  closeViewer();
  viewerEl = document.createElement("div");
  viewerEl.className = "viewer"; viewerEl.setAttribute("role", "dialog"); viewerEl.setAttribute("aria-modal", "true");
  const n = P.meta.pageCount;
  const render = () => {
    const s = page ? `${base}pages/p${String(page).padStart(2, "0")}.webp` : src;
    viewerEl.innerHTML = `<header><span class="t">${page ? `PDF page ${page} of ${n}` : esc(title)}</span>
      ${page ? `<button type="button" data-v="prev" ${page <= 1 ? "disabled" : ""} aria-label="Previous page">‹</button><button type="button" data-v="next" ${page >= n ? "disabled" : ""} aria-label="Next page">›</button>` : ""}
      <button type="button" data-v="zoom">Zoom</button><button type="button" data-v="close">Close</button></header>
      <div class="stage"><img src="${s}" alt="${page ? `Page ${page} of the original PDF` : esc(title)}"></div>`;
  };
  render();
  viewerEl.addEventListener("click", (e) => {
    const v = e.target.closest("[data-v]")?.dataset.v;
    if (v === "close") closeViewer();
    if (v === "zoom" || e.target.tagName === "IMG" && e.detail === 2) viewerEl.classList.toggle("zoomed");
    if (v === "prev") { page--; render(); }
    if (v === "next") { page++; render(); }
  });
  document.body.append(viewerEl);
  $("[data-v=close]", viewerEl).focus();
}

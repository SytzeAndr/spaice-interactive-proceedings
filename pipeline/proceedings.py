"""Turn the SPAICE proceedings PDF into one paper.json per paper.

Usage:
  python pipeline/proceedings.py <proceedings.pdf> [--only <id-or-number> ...] [--no-images]

Writes, under proceedings/:
  index.json                     sessions and papers (for the start page)
  pages/pNNN.webp                one image per PDF page ("PDF page N" viewer)
  front/paper.json               foreword, keynotes and committees
  <paper-id>/paper.json          structured content of each paper
  <paper-id>/img/*.webp          figure, table and equation crops

The papers share one LaTeX template (two columns, numbered sections, captions under
floats, numbered references), which this script relies on. Prose is copied verbatim
from the PDF's text layer. What the text layer cannot represent faithfully (figures,
tables, display equations) is cropped from the page as an image, and tables are
additionally extracted as data when that can be done cleanly.
"""
import argparse, json, re, unicodedata
from collections import Counter
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "proceedings"
RELEASE_PDF = "https://github.com/SytzeAndr/spaice-interactive-proceedings/releases/download/LTS/Conference_Proceedings_SPAICE_2026.pdf"
ZENODO = "https://zenodo.org/records/23495603"

COL = [(55.0, 293.0), (304.0, 541.0)]  # template column bounds (pt)
TOP, BOTTOM = 78.0, 766.0                # text area; footer lives below BOTTOM
MATH_FONTS = ("CMMI", "CMSY", "CMEX", "MSBM", "MSAM", "LMMath", "STIXMath", "rsfs", "EUFM", "CMBSY", "LMSY")
CAPTION = re.compile(r"^(Figure|Fig\.|Table|Algorithm|Listing)\s*(\d+)\s*[:.]|^(Algorithm|Listing)\s*(\d+)\s+(?=[A-Z])")
KEEP_HYPHEN = re.compile(r"(informed|based|aware|driven|guided|specific|level|scale|time|free|wise|like|related|dependent|"
                         r"independent|efficient|tuned|trained|learning|supervised|domain|end|art|orbit|board|ground|order|step|"
                         r"source|loop|grade|of-the|the-art|world|shot|layer|value|resolution|channel|class|label|task|agent)\b")
FIG_DPI, PAGE_DPI = 200, 110


# ---------------------------------------------------------------- helpers
def cap_parts(text):
    m = CAPTION.match(text)
    return (m.group(1) or m.group(3), m.group(2) or m.group(4)) if m else (None, None)


def slug(title, n=7):
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    words = [w for w in re.findall(r"[a-z0-9]+", t) if w not in {"a", "an", "the", "of", "for", "and", "in", "on", "with", "via", "to", "from", "by", "using"}]
    return "-".join(words[:n])


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clean(s):
    s = s.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("ﬀ", "ff").replace("ﬃ", "ffi").replace("ﬄ", "ffl").replace("­", "")
    return re.sub(r"[ \t]+", " ", s)


def is_math(font):
    return font.startswith(MATH_FONTS)


def col_of(x0, x1):
    """0 = left column, 1 = right column, 2 = full width."""
    if x0 < 280 and x1 > 318: return 2
    return 0 if (x0 + x1) / 2 < 298 else 1


def col_span(c):
    return (COL[0][0], COL[1][1]) if c == 2 else COL[c]


def body_size(sz):
    return 8.6 <= sz <= 10.8  # some papers shrink sections to 9 pt


class Line:
    __slots__ = ("bbox", "spans", "text", "size", "font", "bold", "body", "gaps")

    def __init__(self, l):
        self.bbox = pymupdf.Rect(l["bbox"])
        self.body = None
        self.gaps = 0
        self.spans = [s for s in l["spans"] if s["text"]]
        self.text = clean("".join(s["text"] for s in self.spans))
        big = max(self.spans, key=lambda s: len(s["text"].strip()) + (s["size"] > 9) * 2, default=None)
        self.size = big["size"] if big else 0
        self.font = big["font"] if big else ""
        self.bold = "Bold" in self.font or "Demi" in self.font or self.font.startswith(("CMBX", "SFBX"))


class Block:
    def __init__(self, b, page):
        self.page = page
        self.bbox = pymupdf.Rect(b["bbox"])
        self.lines = [Line(l) for l in b["lines"]]
        self.lines = [l for l in self.lines if l.text.strip()]
        chars = Counter()
        for l in self.lines:
            for s in l.spans: chars[(s["font"], round(s["size"], 1))] += len(s["text"].strip())
        tot = sum(chars.values()) or 1
        self.size = max(chars, key=chars.get)[1] if chars else 0
        self.font = max(chars, key=chars.get)[0] if chars else ""
        self.math = sum(v for (f, _), v in chars.items() if is_math(f)) / tot
        self.bold = sum(v for (f, _), v in chars.items() if "Bold" in f or "Demi" in f or f.startswith(("CMBX", "SFBX"))) / tot
        self.text = " ".join(l.text for l in self.lines)
        self.col = col_of(self.bbox.x0, self.bbox.x1)
        self.kind = None  # body | heading | caption | footer | float | ref | footnote

    def __repr__(self):
        return f"<{self.kind} p{self.page} {[round(v) for v in self.bbox]} {self.text[:40]!r}>"


# ---------------------------------------------------------------- inline formatting
def span_html(s, base_size):
    t = esc(clean(s["text"]))
    if not t.strip(): return t
    f, sz = s["font"], s["size"]
    if sz < base_size * 0.8 and s["flags"] & 1 or (sz < base_size * 0.78 and not t.strip().startswith("[")):
        return f"<sup>{t.strip()}</sup>"
    if is_math(f) or f.startswith(("CMMI", "CMR", "CMBX")):
        return f'<span class="m">{t}</span>'
    if "Mono" in f or f.startswith(("CMTT", "SFTT", "LMMono")):
        return f"<code>{t}</code>"
    if "Ital" in f or f.startswith(("SFTI", "CMTI")):
        return f"<em>{t}</em>"
    if "Bold" in f or "Demi" in f or f.startswith(("SFBX", "CMBX")):
        return f"<b>{t}</b>"
    return t


def lines_html(lines, base=10.0):
    """Join lines into one HTML string, undoing end-of-line hyphenation."""
    out = ""
    for ln in lines:
        h = "".join(span_html(s, base) for s in ln.spans).strip()
        if not h: continue
        m = re.search(r"(?<![\s-])-((?:</\w+>)*)$", out)
        nxt = re.sub("<[^>]+>", "", h)
        if m and re.match(r"[a-z]", nxt):
            keep = KEEP_HYPHEN.match(nxt) is not None  # "physics-" + "informed" keeps its hyphen
            out = out[:m.start()] + ("-" if keep else "") + m.group(1) + h
        else:
            out = f"{out} {h}" if out else h
    for tag in ("em", "b", "code"):
        out = re.sub(fr"</{tag}>(\s*)<{tag}>", r"\1", out)
    out = re.sub(r'</span>(\s*)<span class="m">', r"\1", out)
    return re.sub(r"\s+", " ", out).strip()


# ---------------------------------------------------------------- page analysis
def page_items(doc, pno):
    page = doc[pno]
    raw = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]
    blocks = [Block(b, pno) for b in raw if b["type"] == 0]
    blocks = merge_baselines([b for b in blocks if b.lines])
    # split blocks that pymupdf merged across a vertical gap, or where running text
    # meets a display equation / figure label (common around floats)
    out = []
    for b in blocks:
        cur, kind = [], None
        flags = [bool(line_is_body(ln)) for ln in b.lines]
        for i, ln in enumerate(b.lines):
            if not flags[i] and body_size(ln.size) and not ln.bold and ln.gaps < 2 and i > 0 and (flags[i - 1] or b.lines[i - 1].bbox.x1 >= COL[col_of(ln.bbox.x0, ln.bbox.x1) % 2][1] - 12):
                c_ = col_of(ln.bbox.x0, ln.bbox.x1) % 2
                prev = b.lines[i - 1]
                # the short last line of a paragraph sits right under a full-width line
                if ln.bbox.x0 <= COL[c_][0] + 26 and prev.bbox.x1 >= COL[c_][1] - 12 and -5 < ln.bbox.y0 - prev.bbox.y1 < 4:
                    flags[i] = True
        for i, ln in enumerate(b.lines):
            ln.body = flags[i]
            k = flags[i]
            lead = ln.spans[0]["font"] if ln.spans else ""
            if CAPTION.match(ln.text) and ("Bold" in lead or "Demi" in lead or lead.startswith(("CMBX", "SFBX")) or re.match(r"^(Figure|Fig\.|Table|Algorithm)\s*\d+:\s*[A-Z]", ln.text)):
                k = ("cap", i)  # a caption always starts its own block ...
            elif isinstance(kind, tuple) and cur and ln.bbox.y0 - cur[-1].bbox.y1 < 4 and ln.size <= cur[0].size + 0.4:
                k = kind        # ... and keeps its continuation lines
            if cur and (ln.bbox.y0 - cur[-1].bbox.y1 > 6 or k != kind):
                out.append(sub_block(b, cur)); cur = []
            cur.append(ln); kind = k
        out.append(sub_block(b, cur))
    gfx = [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
    for d in page.get_drawings():
        r = d["rect"]
        if r.y0 >= BOTTOM - 2 or (r.width > 400 and r.height > 600): continue
        gfx.append(r)
    gfx = [g for g in gfx if g.y1 > TOP - 10 and g.y0 < BOTTOM]
    if len(gfx) > 400:  # dense vector plots: snap to a coarse grid of covered cells, then merge per row
        cells = set()
        for g in gfx:
            for cx in range(int(g.x0 // 6), int(g.x1 // 6) + 1):
                for cy in range(int(g.y0 // 6), int(g.y1 // 6) + 1):
                    cells.add((cx, cy))
        rows = {}
        for cx, cy in cells: rows.setdefault(cy, []).append(cx)
        gfx = []
        for cy, xs in rows.items():
            xs.sort(); start = prev = xs[0]
            for x in xs[1:] + [None]:
                if x is not None and x == prev + 1: prev = x; continue
                gfx.append(pymupdf.Rect(start * 6, cy * 6, prev * 6 + 6, cy * 6 + 6))
                if x is not None: start = prev = x
    return page, out, gfx


def merge_baselines(blocks):
    """pymupdf sometimes cuts one printed line into pieces (wide word gaps, inline maths, "2.4.3" + title).
    Glue pieces that share a baseline and nearly touch, and merge their blocks."""
    parent = list(range(len(blocks)))
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    entries = [(l, i) for i, b in enumerate(blocks) for l in b.lines]
    entries.sort(key=lambda e: (e[0].bbox.y0 + e[0].bbox.y1) / 2)
    rows = []  # lines that sit on the same printed row
    for e in entries:
        r = e[0].bbox
        for row in reversed(rows[-20:]):
            q = row["r"]  # first line of the row
            ov = min(q.y1, r.y1) - max(q.y0, r.y0)
            if (ov >= 0.6 * min(q.height, r.height) and abs(q.height - r.height) < 6 or ov >= 0.85 * min(q.height, r.height)) and row["c"] == col_of(r.x0, r.x0 + 1):
                row["e"].append(e); break
        else:
            rows.append({"e": [e], "r": pymupdf.Rect(r), "c": col_of(r.x0, r.x0 + 1)})
    dead = set()
    for row in rows:
        row["e"].sort(key=lambda e: e[0].bbox.x0)
        keep = row["e"][0]
        for e in row["e"][1:]:
            la, lb = keep[0], e[0]
            gap = lb.bbox.x0 - la.bbox.x1
            same_col = col_of(la.bbox.x0, la.bbox.x0 + 1) == col_of(lb.bbox.x0, lb.bbox.x0 + 1)
            label = re.fullmatch(r"(Figure|Fig\.|Table|Algorithm|Listing)(\s*\d+\s*[:.])?|\d+[:.)]|•|–|\(?[a-z]\)|[ivx]+[.)]", la.text.strip())
            if same_col and -1 <= gap < (45 if label else 16):
                la.spans = la.spans + ([{**lb.spans[0], "text": " "}] if gap > 1.5 else []) + lb.spans
                la.gaps += (gap > 6) + lb.gaps
                la.text = clean("".join(sp["text"] for sp in la.spans))
                la.bbox |= lb.bbox
                dead.add(id(lb))
                parent[find(e[1])] = find(keep[1])
            else:
                keep = e
    groups = {}
    for i, b in enumerate(blocks):
        groups.setdefault(find(i), []).extend(l for l in b.lines if id(l) not in dead)
    out = []
    for root, lines in groups.items():
        lines.sort(key=lambda l: (l.bbox.y0, l.bbox.x0))
        for l in lines:  # recompute dominant size/font after gluing
            big = max(l.spans, key=lambda sp: len(sp["text"].strip()))
            l.font = big["font"]
            l.size = max((sp["size"] for sp in l.spans if sp["text"].strip()), default=big["size"])
            l.bold = "Bold" in l.font or "Demi" in l.font or l.font.startswith(("CMBX", "SFBX"))
        out.append(sub_block(blocks[root], lines))
    return out


def tabular(text):
    toks = text.split()
    return len(toks) >= 2 and sum(bool(re.fullmatch(r"[-+±−]?[\d.,%]+[%×]?,?|[–—-]|✓|✗|[A-Z]{1,3}\d+,?", t)) for t in toks) / len(toks) >= 0.45


def prose(text):
    return len(re.findall(r"\b[a-z]{3,}\b", text)) >= 2 and not tabular(text)


def line_is_body(ln):
    """A line of running text: body-size text font, starting at the column edge (or a paragraph/list indent)."""
    if not ln.spans: return False
    tot_ = sum(len(sp["text"].strip()) for sp in ln.spans) or 1
    mathshare = sum(len(sp["text"].strip()) for sp in ln.spans if is_math(sp["font"])) / tot_
    if not body_size(ln.size):
        c = col_of(ln.bbox.x0, ln.bbox.x1)
        lo, hi = COL[c] if c < 2 else (COL[0][0], COL[1][1])
        if not (is_math(ln.font) and ln.bbox.x0 <= lo + 3 and ln.bbox.x1 >= hi - 12 and 9 <= ln.size <= 11): return False
        return True
    tot = sum(len(sp["text"].strip()) for sp in ln.spans) or 1
    if sum(len(sp["text"].strip()) for sp in ln.spans if is_math(sp["font"])) / tot > 0.35: return False
    c = col_of(ln.bbox.x0, ln.bbox.x1)
    if c == 2: return ln.bbox.width > 380
    lo, hi = COL[c]
    if ln.gaps >= 2 and not re.match(r"^(Figure|Fig\.|Table)", ln.text) or ln.text.count("•") >= 3 or ln.text.count("●") >= 3:
        return False  # cells of a table row
    toks = ln.text.split()
    if len(toks) >= 3 and sum(bool(re.fullmatch(r"[-+±−]?[\d.,%]+[%×]?|[–—-]|✓|✗", t)) for t in toks) / len(toks) >= 0.45:
        return False  # a table row, not prose
    if ln.bbox.x1 >= hi - 12 and (ln.bbox.x0 <= lo + 3 or ln.bbox.x0 <= lo + 26 and mathshare < 0.6):
        return True  # justified full line (also list items), even with inline maths
    if ln.bbox.x0 > lo + 26: return False
    full = ln.bbox.x1 >= hi - 25
    words = len(ln.text.split())
    if full: return True
    listy = re.match(r"^(•|–|◦|\(?\d+[.)]|\([a-z]\)|[ivx]+\))\s", ln.text)
    if listy and (full or words >= 8) and not re.match(r"^\([a-z]\)", ln.text.strip()) or listy and full:
        return True
    if re.match(r"^\([a-z]\)\s", ln.text.strip()) and not full: return False  # sub-caption
    return ln.bbox.x0 <= lo + 16 and words >= 3 and not ln.bold and ln.gaps < 2 and len(re.findall(r"\b[a-z]{3,}\b", ln.text)) >= 2


def sub_block(b, lines):
    nb = Block.__new__(Block)
    nb.__dict__.update(b.__dict__)
    nb.lines = lines
    nb.bbox = pymupdf.Rect(lines[0].bbox)
    for l in lines[1:]: nb.bbox |= l.bbox
    nb.text = " ".join(l.text for l in lines)
    nb.col = col_of(nb.bbox.x0, nb.bbox.x1)
    chars = Counter()
    for l in lines:
        for s in l.spans: chars[(s["font"], round(s["size"], 1))] += len(s["text"].strip())
    tot = sum(chars.values()) or 1
    nb.size = max(chars, key=chars.get)[1] if chars else 0
    nb.font = max(chars, key=chars.get)[0] if chars else ""
    nb.math = sum(v for (f, _), v in chars.items() if is_math(f)) / tot
    nb.bold = sum(v for (f, _), v in chars.items() if "Bold" in f or "Demi" in f or f.startswith(("CMBX", "SFBX"))) / tot
    return nb


def classify(b, in_refs):
    x0, x1 = b.bbox.x0, b.bbox.x1
    if b.bbox.y0 >= BOTTOM: return "footer"
    first = b.lines[0]
    lead = first.spans[0]["font"] if first.spans else ""
    strong = "Bold" in lead or "Demi" in lead or lead.startswith(("CMBX", "SFBX")) or b.bold > 0.1
    if CAPTION.match(b.text) and (strong and b.size < 10.5 or re.match(r"^(Figure|Fig\.|Table|Algorithm)\s*\d+:\s*[A-Z]", b.text)):
        return "caption"
    if first.bold and first.size >= 11.5 and len(b.text) < 160:
        return "heading"
    if b.bbox.height < 16 and (b.bold > 0.8 or "Demi" in b.font) and re.match(r"^\d+(\.\d+)+\.?\s+[A-Z]", b.text) and len(b.text) < 90:
        return "heading"
    if in_refs and b.size < 9.2 and b.col < 2:
        return "ref"
    if all(getattr(l, "body", None) if getattr(l, "body", None) is not None else line_is_body(l) for l in b.lines):
        return "body"
    if b.size <= 8.3 and b.bbox.y0 > 600 and b.col < 2 and re.match(r"^(\S{1,3}\s|∗|\*|†|‡|\d)", b.text):
        return "footnote"
    return "float"


def caption_regions(page, blocks, gfx):
    """For each caption, find the rectangle holding its figure/table (above or below it).
    A float sits directly against its caption, so the side with content touching the caption wins;
    captions are resolved one by one and content claimed by one caption is not reused by another."""
    caps = [b for b in blocks if b.kind == "caption"]
    def wall(b):
        if b.kind in ("heading", "caption"): return True
        lo, hi = col_span(b.col)
        return b.kind == "body" and (b.bbox.width > 0.7 * (hi - lo) or len(b.lines) >= 2)
    walls = [b for b in blocks if wall(b)]
    raw = [b.bbox for b in blocks if b.kind == "float"] + list(gfx)
    # glue touching pieces (cells of one table row, labels of one plot) so a float moves as a whole
    par = list(range(len(raw)))
    def f(i):
        while par[i] != i: par[i] = par[par[i]]; i = par[i]
        return i
    splits = []
    for a in caps:
        for b in caps:
            if a is not b and min(a.bbox.y1, b.bbox.y1) - max(a.bbox.y0, b.bbox.y0) > 4 and a.bbox.x1 <= b.bbox.x0 + 2:
                splits.append((a.bbox.x1 + b.bbox.x0) / 2)
    order = sorted(range(len(raw)), key=lambda k: raw[k].x0)  # sweep over x so big vector plots stay fast
    for oi, i in enumerate(order):
        for j in order[oi + 1:]:
            a_, b_ = raw[i], raw[j]
            if b_.x0 > a_.x1 + 9: break
            if any(min(a_.x1, b_.x1) <= sx + 1 and max(a_.x0, b_.x0) >= sx - 1 for sx in splits): continue
            vgap = max(a_.y0, b_.y0) - min(a_.y1, b_.y1)
            hgap = max(a_.x0, b_.x0) - min(a_.x1, b_.x1)
            if vgap < 4 and hgap < 9: par[f(i)] = f(j)
    comp = {}
    for i, r in enumerate(raw): comp.setdefault(f(i), []).append(r)
    items = []
    for rs in comp.values():
        u = pymupdf.Rect(rs[0])
        for r in rs[1:]: u |= r
        items.append(u)
    taken = set()
    plans = []
    for cap in caps:
        c = 2 if cap.bbox.width > 300 else cap.col
        lo, hi = col_span(c)
        sibs = sorted([o for o in caps if o is not cap and min(o.bbox.y1, cap.bbox.y1) - max(o.bbox.y0, cap.bbox.y0) > 4
                       and o.bbox.x1 > lo and o.bbox.x0 < hi], key=lambda o: o.bbox.x0)
        for o in sibs:
            if o.bbox.x0 >= cap.bbox.x1 - 2: hi = min(hi, (cap.bbox.x1 + o.bbox.x0) / 2)
            elif o.bbox.x1 <= cap.bbox.x0 + 2: lo = max(lo, (o.bbox.x1 + cap.bbox.x0) / 2)
        def overlaps(r, lo=lo, hi=hi):
            return r.x1 > lo + 2 and r.x0 < hi - 2 and (min(r.x1, hi) - max(r.x0, lo)) > 0.7 * min(r.width, hi - lo)
        above_lim = max([w.bbox.y1 for w in walls if w is not cap and w.bbox.y1 <= cap.bbox.y0 + 1 and overlaps(w.bbox)], default=TOP - 6)
        below_lim = min([w.bbox.y0 for w in walls if w is not cap and w.bbox.y0 >= cap.bbox.y1 - 1 and overlaps(w.bbox)], default=BOTTOM)
        up = [k for k, r in enumerate(items) if overlaps(r) and r.y0 >= above_lim - 2 and r.y1 <= cap.bbox.y0 + 2]
        down = [k for k, r in enumerate(items) if overlaps(r) and r.y0 >= cap.bbox.y1 - 2 and r.y1 <= below_lim + 2]
        adj_up = any(cap.bbox.y0 - items[k].y1 < 16 for k in up)
        adj_dn = any(items[k].y0 - cap.bbox.y1 < 16 for k in down)
        plans.append({"cap": cap, "c": c, "lo": lo, "hi": hi, "up": up, "down": down, "adj": (adj_up, adj_dn), "sibs": bool(sibs),
                      "lims": (above_lim, below_lim)})
    # every content item goes to the nearest caption that can see it; then each caption keeps one side
    def options(k):
        opts = []
        for i, p in enumerate(plans):
            if k in p["up"]: opts.append((p["cap"].bbox.y0 - items[k].y1, i, "up"))
            if k in p["down"]: opts.append((items[k].y0 - p["cap"].bbox.y1, i, "down"))
        return sorted(opts)
    banned = set()  # (plan, side) combinations ruled out
    for _ in range(3):
        assigned = {i: {"up": [], "down": []} for i in range(len(plans))}
        for k in range(len(items)):
            for d, i, sd in options(k):
                if (i, sd) not in banned:
                    assigned[i][sd].append(k); break
        changed = False
        for i, p in enumerate(plans):
            up, down = assigned[i]["up"], assigned[i]["down"]
            if (i, "up") in banned or (i, "down") in banned or not (up and down): continue
            area = lambda ks: sum(items[k].width * max(items[k].height, 1) for k in ks)
            adj_up = any(p["cap"].bbox.y0 - items[k].y1 < 16 for k in up)
            adj_dn = any(items[k].y0 - p["cap"].bbox.y1 < 16 for k in down)
            if adj_up != adj_dn: keep = "up" if adj_up else "down"
            else:
                kind = cap_parts(p["cap"].text)[0]
                keep = "up" if area(up) >= area(down) * (0.5 if kind == "Table" else 1) else "down"
            banned.add((i, "down" if keep == "up" else "up")); changed = True
        if not changed: break
    out = {}
    for i, p in enumerate(plans):
        cap = p["cap"]
        side_name = "up" if assigned[i]["up"] else "down"
        side = assigned[i][side_name]
        if not side:
            out[id(cap)] = (cap, ink_region(page, cap, p), p["c"]); continue
        going_up = side_name == "up"
        side = sorted(side, key=lambda k: -items[k].y1 if going_up else items[k].y0)
        edge = cap.bbox.y0 if going_up else cap.bbox.y1
        grown = []
        for k in side:  # grow outward through touching content only
            r_ = items[k]
            gap = (edge - r_.y1) if going_up else (r_.y0 - edge)
            if gap > 18 and grown: break
            grown.append(k)
            edge = min(edge, r_.y0) if going_up else max(edge, r_.y1)
        r = pymupdf.Rect(items[grown[0]])
        for k in grown[1:]: r |= items[k]
        if p["sibs"]: lo_lim, hi_lim = p["lo"], p["hi"]
        else:  # content may run into the gutter / margin, but never into the other column
            lo_lim = 20 if p["c"] in (0, 2) else COL[0][1] + 1
            hi_lim = 575 if p["c"] in (1, 2) else COL[1][0] - 1
        r = pymupdf.Rect(max(lo_lim, r.x0 - 3), r.y0 - 3, min(hi_lim, r.x1 + 3), r.y1 + 3)
        mid = (r.y0 + r.y1) / 2
        for w in walls:
            for ln in w.lines:
                lb = ln.bbox
                if lb.y1 <= r.y0 or lb.y0 >= r.y1: continue
                if min(lb.x1, r.x1) - max(lb.x0, r.x0) < 0.5 * lb.width: continue
                if (lb.y0 + lb.y1) / 2 < mid: r.y0 = max(r.y0, lb.y1 + 0.5)
                else: r.y1 = min(r.y1, lb.y0 - 0.5)
        if r.height < 6: r = None
        out[id(cap)] = (cap, r, p["c"])
    return [out[id(c)] for c in caps]


def continue_captions(blocks):
    """A caption's last line sometimes lands in its own text block (inline maths, or a short
    final line next to a table). If a caption stops mid-sentence, take the line directly below it."""
    for cap in blocks:
        if cap.kind != "caption": continue
        while not re.search(r"[.!?:)\]]$", cap.text.rstrip()):
            nxt = [o for o in blocks if o is not cap and o.kind in ("body", "float") and len(o.lines) >= 1
                   and -3 < o.bbox.y0 - cap.bbox.y1 < 4 and abs(o.bbox.x0 - cap.bbox.x0) < 6 and abs(o.size - cap.size) < 0.8]
            if not nxt: break
            o = min(nxt, key=lambda o: o.bbox.y0)
            line = o.lines[0]
            if not (line.text[:1].islower() or line.text[:1] in "“\"(" or cap.text.rstrip().endswith("-")):
                break
            cap.lines.append(line); cap.bbox |= line.bbox
            cap.text = " ".join(l.text for l in cap.lines)
            o.lines = o.lines[1:]
            if o.lines:
                o.bbox = pymupdf.Rect(o.lines[0].bbox)
                for l in o.lines: o.bbox |= l.bbox
                o.text = " ".join(l.text for l in o.lines)
            else:
                o.kind = "used"


def claim_ruled_tables(page, blocks):
    """Tables are drawn between horizontal rules (booktabs). Everything between the rules that start
    next to a table caption belongs to the table, even cells that read like prose."""
    rules = [d["rect"] for d in page.get_drawings() if d["rect"].height < 2.2 and d["rect"].width > 40 and TOP - 10 < d["rect"].y0 < BOTTOM]
    rules += [pymupdf.Rect(i["bbox"]) for i in []]
    for cap in [b for b in blocks if b.kind == "caption" and cap_parts(b.text)[0] in ("Table", "Algorithm", "Listing")]:
        is_algo = cap_parts(cap.text)[0] != "Table"
        c = 2 if cap.bbox.width > 300 else cap.col
        lo, hi = col_span(c)
        mine = [r for r in rules if min(r.x1, hi) - max(r.x0, lo) > 0.4 * min(r.width, hi - lo) and min(r.x1, cap.bbox.x1) - max(r.x0, cap.bbox.x0) > 0]
        for direction in (1, -1):
            edge = cap.bbox.y1 if direction == 1 else cap.bbox.y0
            chain = []
            while True:
                cand = [r for r in mine if (r.y0 - edge if direction == 1 else edge - r.y1) >= -2 and r not in chain]
                cand = [r for r in cand if (r.y0 - edge if direction == 1 else edge - r.y1) < (26 if not chain else 700 if is_algo else 330)]
                if not cand: break
                nxt = min(cand, key=lambda r: abs((r.y0 if direction == 1 else r.y1) - edge))
                between = [b for b in blocks if b.kind in ("caption", "heading") and b is not cap and
                           min(b.bbox.y1, max(edge, nxt.y0)) - max(b.bbox.y0, min(edge, nxt.y1)) > 2 and b.bbox.x1 > lo and b.bbox.x0 < hi]
                if between: break
                chain.append(nxt); edge = nxt.y1 if direction == 1 else nxt.y0
            if is_algo and direction == -1: continue  # algorithm content always follows its caption
            if is_algo and len(chain) >= 1 and len(chain) < 2:  # box runs to the bottom of the page
                chain.append(pymupdf.Rect(chain[0].x0, BOTTOM - 4, chain[0].x1, BOTTOM - 3))
            if len(chain) >= 2:
                top = min(r.y0 for r in chain) - 1; bot = max(r.y1 for r in chain) + 1
                x0 = min(r.x0 for r in chain) - 2; x1 = max(r.x1 for r in chain) + 2
                for b in blocks:
                    if b.kind in ("body", "heading", "footnote", "ref") and b.bbox.y0 >= top - 1 and b.bbox.y1 <= bot + 1 and b.bbox.x0 >= x0 - 2 and b.bbox.x1 <= x1 + 2:
                        b.kind = "float"
                break


def ink_region(page, cap, p):
    """Fallback when no text/graphics objects were found: crop whatever is drawn next to the caption."""
    import numpy as np
    best = None
    for y0, y1 in ((max(p["lims"][0], cap.bbox.y0 - 380), cap.bbox.y0 - 1), (cap.bbox.y1 + 1, min(p["lims"][1], cap.bbox.y1 + 380))):
        if y1 - y0 < 20: continue
        clip = pymupdf.Rect(p["lo"], y0, p["hi"], y1)
        pix = page.get_pixmap(dpi=36, clip=clip, colorspace=pymupdf.csGRAY)
        a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width) < 235
        if a.sum() < 40: continue
        rows, cols = np.where(a.any(1))[0], np.where(a.any(0))[0]
        sc = 72 / 36
        r = pymupdf.Rect(clip.x0 + cols[0] * sc - 3, clip.y0 + rows[0] * sc - 3, clip.x0 + (cols[-1] + 1) * sc + 3, clip.y0 + (rows[-1] + 1) * sc + 3)
        if not best or a.sum() > best[0]: best = (a.sum(), r)
    return best[1] if best else None


# ---------------------------------------------------------------- tables as data
def grid_table(page, rect):
    """Rebuild a table from word positions: rows by baseline, columns by vertical whitespace."""
    words = [w for w in page.get_text("words", clip=rect) if w[4].strip()]
    if len(words) < 6: return None
    words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows = []
    for w in words:
        yc = (w[1] + w[3]) / 2
        if rows and abs(rows[-1]["y"] - yc) < 3.2: rows[-1]["w"].append(w)
        else: rows.append({"y": yc, "w": [w]})
    if len(rows) < 3: return None
    x0, x1 = rect.x0, rect.x1
    res = 0.5
    width = int((x1 - x0) / res) + 2
    def cover(rs):
        c = [0] * width
        for r in rs:
            for w in r["w"]:
                for k in range(int((w[0] - x0) / res), int((w[2] - x0) / res) + 1):
                    if 0 <= k < width: c[k] += 1
        return c
    body = rows[1:] if len(rows) > 3 else rows
    cov = cover(body)
    # gaps: runs of empty columns at least 4pt wide
    gaps, k = [], 0
    while k < width:
        if cov[k] == 0:
            j = k
            while j < width and cov[j] == 0: j += 1
            if (j - k) * res >= 4 and k > 0 and j < width: gaps.append(x0 + (k + j) / 2 * res)
            k = j
        else: k += 1
    ncol = len(gaps) + 1
    if ncol < 2 or ncol > 14: return None
    def cells(r):
        out = [[] for _ in range(ncol)]
        for w in sorted(r["w"], key=lambda w: w[0]):
            ci = sum(1 for g in gaps if (w[0] + w[2]) / 2 > g)
            out[ci].append(w[4])
        return [clean(" ".join(c)) for c in out]
    grid = [cells(r) for r in rows]
    # header rows: leading rows whose words straddle a gap or that are mostly text
    body_rows = [g for g in grid[1:]]
    empty = sum(1 for r in body_rows for c in r if not c) / max(1, len(body_rows) * ncol)
    if empty > 0.3: return None
    # headers that span several columns: rebuild the first row by word centres (allowed to straddle)
    head, rest = grid[0], grid[1:]
    numeric = lambda c: bool(re.fullmatch(r"[-+±−~≈<>]?\s*[\d.,]+.*", c))
    # multi-line headers: fold following text-only rows that leave cells empty into the header
    while rest and any(not c for c in rest[0]) and not any(numeric(c) for c in rest[0]) and len(rest) > 2:
        head = [f"{h} {c}".strip() for h, c in zip(head, rest[0])]
        rest = rest[1:]
    if sum(1 for h in head if not h) > 0.4 * ncol: return None
    return {"head": head, "rows": rest}


def table_data(page, rect):
    best = None
    for strat in ("lines", "text"):
        try:
            tabs = page.find_tables(clip=rect, strategy=strat) if strat == "lines" else page.find_tables(clip=rect, vertical_strategy="text", horizontal_strategy="lines")
        except Exception:
            continue
        for t in tabs.tables:
            rows = [[clean(c or "").replace("\n", " ").strip() for c in r] for r in t.extract()]
            rows = [r for r in rows if any(r)]
            if len(rows) < 3 or len(rows[0]) < 2: continue
            ncol = len(rows[0])
            cells = [c for r in rows for c in r]
            empty = sum(1 for c in cells if not c) / len(cells)
            if empty > 0.25 or any(len(c) > 120 for c in cells): continue
            # every word in the region must land in the table
            words = [w for w in page.get_text("words", clip=rect)]
            joined = " ".join(cells)
            missing = sum(1 for w in words if clean(w[4]) not in joined)
            if words and missing / len(words) > 0.05: continue
            score = (1 - empty) * len(cells)
            if not best or score > best[0]: best = (score, rows, ncol)
        if best: break
    if not best: return None
    rows = best[1]
    return {"head": rows[0], "rows": rows[1:]}


# ---------------------------------------------------------------- per-paper extraction
def render(page, rect, path, dpi=FIG_DPI):
    pix = page.get_pixmap(dpi=dpi, clip=rect, alpha=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    pix.pil_save(path, format="WEBP", quality=82, method=6)
    return [pix.width, pix.height]


def extract_paper(doc, entry, out_dir, images=True):
    pages = range(entry["start"] - 1, entry["end"])
    items, footnotes, refs_raw = [], [], []
    title_lines, authors_lines, affil_lines, abstract_parts = [], [], [], []
    license_line = ""
    in_refs, seen_heading = False, False
    counters = Counter()

    for pno in pages:
        page, blocks, gfx = page_items(doc, pno)
        first_page = pno == pages.start
        for b in blocks:
            b.kind = classify(b, in_refs)
            if b.kind == "heading":
                t = re.sub(r"\s+", " ", b.text).strip()
                if re.match(r"^(\d+\s+)?References$", t): in_refs = True
                elif in_refs and re.match(r"^(\d+(\.\d+)*)?\s*[A-Z]", t): in_refs = False
            if b.kind == "footer" and "licen" in b.text.lower():
                license_line = re.sub(r"^.*?(©)", r"\1", b.text.replace("\n", " "))

        # title page: title, authors, affiliations, abstract
        if first_page:
            for b in blocks:
                if b.kind == "footer": continue
                if b.size >= 15 and b.bbox.y0 < 260:
                    title_lines += [l.text for l in b.lines]; b.kind = "used"
                elif b.size >= 11 and b.bbox.y0 < 280 and b.kind != "heading":
                    authors_lines += b.lines; b.kind = "used"
            ttl_bottom = max((b.bbox.y1 for b in blocks if b.kind == "used"), default=TOP)
            for b in blocks:
                centred = abs((b.bbox.x0 + b.bbox.x1) / 2 - 298) < 40
                if b.kind in ("float", "body") and ttl_bottom - 2 < b.bbox.y0 < ttl_bottom + 70 and (b.col == 2 or centred) and b.size < 10.5 and not b.bold > 0.5:
                    affil_lines.append(b.text); b.kind = "used"
            first_head = min((b.bbox.y0 for b in blocks if b.kind == "heading" and b.col == 0), default=BOTTOM)
            for b in blocks:
                if b.kind in ("body", "float") and b.bold > 0.5 and b.col == 0 and b.bbox.y0 < first_head and b.bbox.y0 > ttl_bottom:
                    abstract_parts.append(b); b.kind = "used"

        for b in blocks:
            if b.kind != "float" or len(b.lines) > 2 or b.bold > 0.5: continue
            lo_, hi_ = col_span(b.col)
            if b.col == 2 or b.bbox.x0 > lo_ + 3 or not all(body_size(l.size) and l.gaps < 2 and not tabular(l.text) for l in b.lines): continue
            if any(o.kind == "body" and o.col == b.col and -5 < b.bbox.y0 - o.bbox.y1 < 4 and o.lines[-1].bbox.x1 >= hi_ - 12 for o in blocks):
                b.kind = "body"
        for b in blocks:
            if b.kind != "float": continue
            lo_, hi_ = col_span(b.col)
            ok = b.col < 2 and b.bbox.x0 <= lo_ + 14 and b.math < 0.35 and all(body_size(l.size) and l.gaps < 2 for l in b.lines)
            ok = ok and all(prose(l.text) or l.text.rstrip().endswith((".", ":", ",")) and not tabular(l.text) for l in b.lines) and prose(b.text)
            ok = ok and not any(o is not b and o.kind in ("float", "caption") and o.bbox.x0 > b.bbox.x1 - 2 and o.col == b.col
                                and min(o.bbox.y1, b.bbox.y1) - max(o.bbox.y0, b.bbox.y0) > 3 for o in blocks)
            ok = ok and not any(g.intersects(b.bbox) and g.get_area() > 400 for g in gfx)
            if ok: b.kind = "body"
        continue_captions(blocks)
        claim_ruled_tables(page, blocks)
        regions = caption_regions(page, blocks, gfx)
        claimed = []
        for cap, rect, c in regions:
            label, num = cap_parts(cap.text)
            kind = {"Figure": "figure", "Fig.": "figure", "Table": "table"}.get(label, "algo")
            counters[kind] += 1
            cap_html = lines_html(cap.lines, 9)
            cap_html = re.sub(r"^<b>(.*?)</b>\s*", "", cap_html)  # drop the bold "Figure 3:" label (re-added by the reader)
            cap_html = re.sub(r"^(Figure|Fig\.|Table|Algorithm|Listing)\s*\d+\s*[:.]?\s*", "", cap_html)
            blk = {"t": kind if kind != "algo" else "figure", "num": num,
                   "id": f"{'tab' if kind == 'table' else 'alg' if kind == 'algo' else 'fig'}{num}", "page": pno + 1,
                   "caption": cap_html, "y": (cap.bbox.y0 if rect is None else min(rect.y0, cap.bbox.y0)), "col": c}
            blk["label"] = label.replace("Fig.", "Figure")
            if rect is not None:
                name = f"{blk['id']}.webp"
                if images: blk["imgSize"] = render(page, rect, out_dir / "img" / name)
                blk["img"] = f"img/{name}"
                blk["rect"] = [round(v, 1) for v in rect]
                claimed.append(rect)
                if kind == "table":
                    data = grid_table(page, rect)
                    if data: blk.update(data)
            items.append(blk)

        def inside_claim(r):
            return any(pymupdf.Rect(r).intersect(cr).get_area() > 0.6 * pymupdf.Rect(r).get_area() for cr in claimed)

        # display equations and other unlabelled floats: cluster leftover float blocks per column
        loose = [b for b in blocks if b.kind == "float" and not inside_claim(b.bbox)]
        loose_g = [g for g in gfx if not inside_claim(g) and g.height < 300]
        clusters, pending = [], []
        for b in sorted(loose, key=lambda b: (b.col, b.bbox.y0)):
            r = pymupdf.Rect(b.bbox)
            for cl in clusters:
                if cl["col"] == b.col and r.y0 - cl["r"].y1 < 5 and r.y1 > cl["r"].y0 - 5:
                    cl["r"] |= r; cl["b"].append(b); break
            else:
                clusters.append({"col": b.col, "r": r, "b": [b]})
        for cl in clusters:
            for g in loose_g:
                if col_of(g.x0, g.x1) in (cl["col"], 2) and g.y1 > cl["r"].y0 - 4 and g.y0 < cl["r"].y1 + 4: cl["r"] |= g
        for cl in clusters:
            bs, r = cl["b"], cl["r"]
            text = " ".join(b.text for b in bs).strip()
            if not text or r.height < 4: continue
            if len(text.replace(" ", "")) < 8 and all(b.size < 8.6 for b in bs) and any(
                    bb.kind == "body" and any(abs(ln.bbox.y1 - r.y1) < 6 or abs(ln.bbox.y0 - r.y0) < 6 for ln in bb.lines) for bb in blocks):
                continue  # stray sub/superscript of a line of running text
            math_share = sum(b.math * len(b.text) for b in bs) / max(1, sum(len(b.text) for b in bs))
            eqno = re.search(r"\((\d+[a-z]?)\)\s*$", bs[-1].text) or any(re.fullmatch(r"\(\d+[a-z]?\)", b.text.strip()) for b in bs)
            lo, hi = col_span(cl["col"])
            y0, y1 = r.y0 - 2.5, r.y1 + 2.5
            for bb in blocks:  # never let an equation crop cover running text
                if bb.kind != "body" or not (bb.bbox.x1 > lo and bb.bbox.x0 < hi): continue
                for ln in bb.lines:
                    if ln.bbox.y1 <= y0 or ln.bbox.y0 >= y1: continue
                    if (ln.bbox.y0 + ln.bbox.y1) / 2 < (r.y0 + r.y1) / 2: y0 = max(y0, ln.bbox.y1)
                    else: y1 = min(y1, ln.bbox.y0)
            if y1 - y0 < 9 or (y1 - y0) < 0.5 * (r.height + 5): continue  # mostly covered by running text
            crop = pymupdf.Rect(lo - 2, y0, hi + 2, y1)
            has_gfx = any(g.intersects(r) and g.get_area() > 30 for g in loose_g)
            if not (math_share > 0.15 or eqno) and not has_gfx and all(body_size(l.size) and not tabular(l.text) and l.gaps < 2 for b in bs for l in b.lines):
                for b in bs: b.kind = "body"  # stray line(s) of running text: keep them as text
                continue
            pending.append({"kind": "eq" if (math_share > 0.15 or eqno) else "graphic", "r": crop, "col": cl["col"], "alt": text})
        # unclaimed pictures without caption
        for g in loose_g:
            if g.width * g.height > 4000 and not any(g.intersects(pymupdf.Rect(i["rect"])) for i in items if i.get("page") == pno + 1 and "rect" in i):
                pending.append({"kind": "graphic", "r": pymupdf.Rect(g), "col": col_of(g.x0, g.x1), "alt": ""})
        # overlapping crops (pieces of one uncaptioned figure) become one
        merged = True
        while merged:
            merged = False
            for i in range(len(pending)):
                for j in range(i + 1, len(pending)):
                    a_, b_ = pending[i]["r"], pending[j]["r"]
                    inter = pymupdf.Rect(a_).intersect(b_)
                    if not inter.is_empty and inter.get_area() > 0.2 * min(a_.get_area(), b_.get_area()):
                        pending[i] = {"kind": "graphic" if "graphic" in (pending[i]["kind"], pending[j]["kind"]) else "eq",
                                      "r": a_ | b_, "col": 2 if pending[i]["col"] != pending[j]["col"] else pending[i]["col"],
                                      "alt": (pending[i]["alt"] + " " + pending[j]["alt"]).strip()}
                        pending.pop(j); merged = True; break
                if merged: break
        for pd in pending:
            counters["eq"] += 1
            kind = pd["kind"]
            name = f"{kind}{counters['eq']}.webp"
            blk = {"t": kind, "id": f"{kind}-{counters['eq']}", "page": pno + 1, "img": f"img/{name}", "y": pd["r"].y0, "col": pd["col"],
                   "alt": pd["alt"][:300], "rect": [round(v, 1) for v in pd["r"]]}
            if images: blk["imgSize"] = render(page, pd["r"], out_dir / "img" / name, dpi=220 if kind == "eq" else FIG_DPI)
            items.append(blk)

        for b in blocks:
            if b.kind == "body" and inside_claim(b.bbox): b.kind = "float"
            if b.kind == "heading":
                items.append({"t": "h", "raw": b, "page": pno + 1, "y": b.bbox.y0, "col": b.col})
            elif b.kind == "body":
                items.append({"t": "body", "raw": b, "page": pno + 1, "y": b.bbox.y0, "col": b.col})
            elif b.kind == "ref":
                refs_raw.append(b)
            elif b.kind == "footnote":
                footnotes.append(lines_html(b.lines, 8))

    # reading order: page, then bands split by full-width items, then column, then y
    def order(it):
        pg = it["page"]
        fulls = sorted(i["y"] for i in items if i["page"] == pg and i["col"] == 2)
        band = sum(1 for f in fulls if f <= it["y"] - 0.5) * 2 + (1 if it["col"] == 2 else 0)
        if it["col"] == 2: band = sum(1 for f in fulls if f < it["y"] - 0.5) * 2 + 1
        return (pg, band, it["col"] if it["col"] < 2 else 0, it["y"])
    items.sort(key=order)

    blocks_out, para, deferred = [], None, []
    def flush():
        nonlocal para
        if para:
            html = lines_html(para["lines"])
            if html: blocks_out.append({"t": "p", "html": html, "page": para["page"]})
        para = None
        blocks_out.extend(deferred); deferred.clear()
    for it in items:
        if it["t"] == "h":
            flush()
            t = re.sub(r"\s+", " ", it["raw"].text).strip()
            m = re.match(r"^(\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\.?\s+(.*)$", t)
            num, title = (m.group(1), m.group(2)) if m and len(m.group(1)) < 7 else ("", t)
            level = num.count(".") + 1 if num else 1
            blocks_out.append({"t": "h", "level": level, "num": num, "title": title, "page": it["page"],
                               "id": "s" + num.replace(".", "-") if num else slug(title, 4) or "sec"})
            continue
        if it["t"] == "body":
            b = it["raw"]
            lo, _ = col_span(b.col)
            for ln in b.lines:
                indent = ln.bbox.x0 - lo
                starts_item = re.match(r"^(•|–|◦|\(?\d+[.)]|\([a-z]\))\s", ln.text)
                if para is None:
                    para = {"lines": [ln], "page": it["page"]}
                    continue
                prev_txt = para["lines"][-1].text.rstrip()
                new_par = (indent > 6 and indent < 40 and (ln is b.lines[0] or prev_txt.endswith((".", ":", "?", "!")))) or starts_item
                if ln is b.lines[0] and not new_par and prev_txt.endswith((".", ":", "?", "!")) and indent <= 6 and blocks_out and para["lines"][-1].bbox.y1 < ln.bbox.y0 - 14:
                    new_par = True
                if new_par:
                    flush(); para = {"lines": [ln], "page": it["page"]}
                else:
                    para["lines"].append(ln)
            continue
        blk = {k: v for k, v in it.items() if k not in ("y", "col", "rect")} | ({"rect": it["rect"]} if "rect" in it else {})
        if para and it["t"] in ("figure", "table", "graphic") and not re.search(r"[.:?!]\)?$", para["lines"][-1].text.strip()):
            deferred.append(blk)  # the sentence continues after the float: place the float after the paragraph
            continue
        flush()
        blocks_out.append(blk)
    flush()

    # make heading ids unique
    seen = Counter()
    for b in blocks_out:
        if b["t"] == "h":
            seen[b["id"]] += 1
            if seen[b["id"]] > 1: b["id"] += f"-{seen[b['id']]}"
    # unique float ids (two "Table 1" captions would collide)
    seen = Counter()
    for b in blocks_out:
        if "id" in b and b["t"] != "h":
            seen[b["id"]] += 1
            if seen[b["id"]] > 1: b["id"] += f"-{seen[b['id']]}"

    # references
    refs, cur = [], None
    for b in refs_raw:
        for ln in b.lines:
            m = re.match(r"^\[?(\d{1,3})[.\]]\s*(.*)", ln.text)
            if m and (cur is None or int(m.group(1)) == cur["n"] + 1) and ln.bbox.x0 < col_span(b.col)[0] + 12:
                cur = {"n": int(m.group(1)), "lines": [ln]}; refs.append(cur)
            elif cur: cur["lines"].append(ln)
    references = []
    for r in refs:
        html = lines_html(r["lines"], 8)
        html = re.sub(r"^\[?\d{1,3}[.\]]\s*", "", html)
        txt = re.sub("<[^>]+>", "", html)
        url = re.search(r"https?://\S+|doi:\s*\S+", txt.replace(" ", "") if "http" in txt else txt)
        references.append({"id": f"ref{r['n']}", "n": r["n"], "html": html, "text": txt,
                           "url": url.group(0).rstrip(".,") if url else None})

    # authors / affiliations
    authors_html = lines_html(authors_lines, 12) if authors_lines else ""
    names = [re.sub(r"<[^>]+>", "", re.sub(r"<sup>.*?</sup>", "", a)).strip(" ,*∗") for a in re.split(r",\s*|\s+and\s+", authors_html)]
    names = [re.sub(r"[\d,∗*†‡§¶\s]+$", "", n).strip() for n in names]
    names = [n for n in names if n and len(n) > 2]
    abstract = lines_html([l for b in abstract_parts for l in b.lines], 9)
    abstract = re.sub(r"</?b>", "", abstract)
    abstract = re.sub(r"^\s*Abstract\s*[–—:-]\s*", "", abstract)

    title = re.sub(r"\s+", " ", " ".join(title_lines)).strip() or entry["title"]
    meta = {
        "id": entry["id"], "title": entry["title"], "authors": [{"name": n} for n in names], "authorsHtml": authors_html,
        "affiliations": [re.sub(r"\s+", " ", a) for a in affil_lines], "session": entry["session"], "kind": entry["kind"],
        "pages": [entry["start"], entry["end"]], "license": "CC BY 4.0", "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
        "copyright": license_line.strip(), "venue": "Proceedings of the 3rd Conference on AI in and for Space (SPAICE 2026)",
        "year": 2026, "pdfUrl": RELEASE_PDF, "record": ZENODO, "citeStyle": "numeric", "pageImages": "../pages/",
    }
    paper = {"meta": meta, "abstract": abstract, "blocks": blocks_out, "footnotes": footnotes, "references": references,
             "stats": dict(counters, captions_seen=sum(1 for b in blocks_out if b["t"] in ("figure", "table")))}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "paper.json").write_text(json.dumps(paper, ensure_ascii=False, separators=(",", ":")))
    return paper


# ---------------------------------------------------------------- outline
def outline(doc):
    toc = doc.get_toc()
    starts = sorted({t[2] for t in toc} | {len(doc) + 1})
    session, kind, papers, sessions = None, "oral", [], []
    for lvl, title, pg in toc:
        title = re.sub(r"\s+", " ", title).strip()
        if lvl == 1:
            m = re.match(r"^([\d.]+)\s+–\s+(.*)$", title)
            num, name = (m.group(1), m.group(2)) if m else ("", title)
            if num == "3": kind = "oral"
            elif num == "4": kind = "poster"
            if "." in num:
                chair = re.search(r"Chair:\s*(.+)", doc[pg - 1].get_text())
                session = {"num": num, "name": name, "kind": kind, "chair": chair.group(1).strip() if chair else None, "papers": []}
                sessions.append(session)
            continue
        end = next(s for s in starts if s > pg) - 1
        pid = slug(title)
        papers.append({"id": pid, "title": title, "start": pg, "end": end, "session": session["name"], "sessionNum": session["num"], "kind": kind})
        session["papers"].append(pid)
    ids = Counter(p["id"] for p in papers)
    assert all(v == 1 for v in ids.values()), ids.most_common(3)
    return sessions, papers


def front_matter(doc, sessions, papers):
    """Foreword, keynotes and committees from the first pages."""
    out = {"title": "Preliminary Proceedings of SPAICE 2026", "subtitle": "The third Conference on AI in and for Space",
           "dates": "21–23 October 2026", "venue": "European Space Research and Technology Centre (ESTEC), Noordwijk"}
    # committees (page 2): bold lines are headings
    groups, cur, sub = [], None, None
    for b in doc[1].get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            t = clean("".join(s["text"] for s in l["spans"])).strip()
            bold = "Bold" in l["spans"][0]["font"]
            if not t or t.startswith("©"): continue
            if bold and l["spans"][0]["size"] >= 11.5:
                cur = {"name": t, "groups": []}; groups.append(cur); sub = None
            elif bold and t.startswith("Logo design"): out["logoCredit"] = t
            elif bold:
                sub = {"name": t, "people": []}; cur["groups"].append(sub)
            else:
                if sub is None: sub = {"name": "", "people": []}; cur["groups"].append(sub)
                sub["people"].append(t)
    out["committees"] = groups
    out["copyright"] = "© 2026 ESA Advanced Concepts Team."
    # foreword (page 7): paragraphs by line shape (a short line ends a paragraph)
    lines = []
    for b in doc[6].get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            if l["bbox"][1] > 780: continue
            lines.append((l["bbox"], clean("".join(s["text"] for s in l["spans"]))))
    lines.sort(key=lambda x: (round(x[0][1]), x[0][0]))
    paras, curp = [], ""
    for k, (bb, t) in enumerate(lines):
        t = t.strip()
        if not t: continue
        if curp.endswith("-") and t[:1].islower(): curp = curp[:-1] + ("-" if KEEP_HYPHEN.match(t) else "") + t
        elif curp == "I": curp += t  # drop capital
        else: curp = f"{curp} {t}".strip()
        if bb[2] < 500 and curp != "I": paras.append(curp); curp = ""
    if curp: paras.append(curp)
    out["foreword"] = [p for p in paras if p]
    # keynotes (pages 9-10): name (large), role, bio
    keynotes = []
    for pno in (8, 9):
        page = doc[pno]
        imgs = [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
        cur = None
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                t = clean("".join(s["text"] for s in l["spans"])).strip()
                sz = l["spans"][0]["size"]; y = l["bbox"][1]
                if not t or y > 780: continue
                if sz >= 13:
                    cur = {"name": t, "role": "", "bio": [], "y": y}; keynotes.append(cur)
                    ph = [r for r in imgs if r.y0 > y - 20 and r.y0 < y + 80]
                    if ph:
                        name = f"keynote-{len(keynotes)}.webp"
                        cur["photo"] = f"front/{name}"
                        render(page, ph[0], OUT / "front" / name, dpi=150)
                elif cur and not cur["role"]: cur["role"] = t
                elif cur and t == "Short biography": continue
                elif cur: cur["bio"].append(t)
    for k in keynotes:
        text = ""
        for t in k.pop("bio"):
            text = text[:-1] + t if text.endswith("-") and t[:1].islower() else f"{text} {t}".strip()
        k["bio"] = text; k.pop("y")
    out["keynotes"] = keynotes
    out["stats"] = {"submissions": 147, "accepted": 79, "orals": 42, "posters": 37}
    (OUT / "front").mkdir(exist_ok=True)
    (OUT / "front" / "front.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--no-pages", action="store_true")
    a = ap.parse_args()
    doc = pymupdf.open(a.pdf)
    sessions, papers = outline(doc)
    OUT.mkdir(exist_ok=True)
    if not a.no_pages and not a.only:
        (OUT / "pages").mkdir(exist_ok=True)
        for i, page in enumerate(doc, 1):
            page.get_pixmap(dpi=PAGE_DPI).pil_save(OUT / "pages" / f"p{i:03d}.webp", format="WEBP", quality=60, method=6)
    summary = []
    for i, p in enumerate(papers, 1):
        if a.only and p["id"] not in a.only and str(i) not in a.only: continue
        paper = extract_paper(doc, p, OUT / p["id"], images=not a.no_images)
        p["authors"] = ", ".join(x["name"] for x in paper["meta"]["authors"])
        p["abstract"] = re.sub("<[^>]+>", "", paper["abstract"])
        st = paper["stats"]
        summary.append(f"{i:2d} {p['id'][:46]:46s} fig {st.get('figure', 0):2d} tab {st.get('table', 0):2d} "
                       f"tabdata {sum(1 for b in paper['blocks'] if b['t'] == 'table' and 'rows' in b):2d} eq {st.get('eq', 0):2d} "
                       f"refs {len(paper['references']):3d} paras {sum(1 for b in paper['blocks'] if b['t'] == 'p'):3d}")
    if not a.only:
        front_matter(doc, sessions, papers)
        (OUT / "index.json").write_text(json.dumps({"sessions": sessions, "papers": papers, "pages": len(doc),
                                                    "pdfUrl": RELEASE_PDF, "record": ZENODO}, ensure_ascii=False, indent=1))
    print("\n".join(summary))


if __name__ == "__main__":
    main()

"""Recover the data behind vector plots in the proceedings PDF.

Usage: python pipeline/digitize.py <proceedings.pdf> <paper-id>:<figure-id> [...]

A figure drawn as vector graphics (not a bitmap) still contains every line segment, bar and
shaded area in the PDF. This script finds each panel of a figure from its numeric tick labels
(linear or logarithmic, e.g. "10^-2", "6 x 10^-3"), calibrates the axes (including a second y
axis on the right, matched by colour), and converts the drawing back into data:

  lines   polylines and plot markers
  bars    filled rectangles (bar charts, histograms)
  areas   filled shapes (confidence bands, density plots)

It writes proceedings/<paper-id>/plots/<figure-id>.json. Anything that fails a sanity check is
skipped and reported, never guessed. The site shows a recovered plot only for figures listed in
proceedings/interactive.json, after a person has compared the replot with the original.
"""
import argparse, json, math, re
from collections import defaultdict
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
NUM = re.compile(r"^[−–+-]?(\d+(?:\.\d*)?|\.\d+)(?:[eE][−+-]?\d+)?$")
INT = re.compile(r"^[−–+-]?\d+$")
MINUS = str.maketrans({"−": "-", "–": "-"})


# ---------------------------------------------------------------- tick labels
def drawn_minuses(drawings):
    """Short horizontal dashes drawn as graphics (matplotlib mathtext draws minus signs this way)."""
    out = []
    for d in drawings:
        r = d["rect"]
        if 1.2 < r.width < 7 and r.height < 1.3 and len(d["items"]) <= 5 and d.get("fill") is not None or 1.2 < r.width < 7 and r.height < 0.3 and d.get("color") is not None:
            out.append(r)
    return out


def tokens(page, rect, drawings=()):
    """Numeric labels as {v, log, x0, x1, y0, y1, cx, cy, color}. Handles superscript powers and
    minus signs drawn as graphics."""
    dashes = drawn_minuses(drawings)
    def negated(r):
        return any(0 <= r.x0 - m.x1 < 2.5 and r.y0 + 0.2 * r.height < (m.y0 + m.y1) / 2 < r.y1 - 0.1 * r.height for m in dashes)
    raw = []
    for b in page.get_text("rawdict", clip=rect)["blocks"]:
        for l in b.get("lines", []):
            run = []
            def flush():
                if run:
                    r = pymupdf.Rect(run[0][1])
                    for c in run[1:]: r |= c[1]
                    raw.append({"t": "".join(c[0] for c in run), "r": r, "size": run[0][2], "color": run[0][3]})
                run.clear()
            for s in l["spans"]:
                for c in s["chars"]:
                    ch, r = c["c"], pymupdf.Rect(c["bbox"])
                    if ch.isspace(): flush(); continue
                    # decimal points and minus signs are often separate maths glyphs with odd spacing
                    joint = ch in ".," or run and (run[-1][0] in ".," or len(run) == 1 and run[0][0] in "−–-" and r.x0 - run[0][1].x1 < 0.6 * s["size"])
                    if run and not joint and (r.x0 - run[-1][1].x1 > 0.3 * s["size"] or abs(s["size"] - run[-1][2]) > 0.3): flush()
                    run.append((ch, r, s["size"], s["color"]))
            flush()
    raw.sort(key=lambda t: (round(t["r"].y1), t["r"].x0))
    used, out = set(), []
    order = sorted(range(len(raw)), key=lambda i: raw[i]["t"] != "10")
    for i in order:
        a = raw[i]
        if i in used or a["size"] >= 11: continue
        t, r, v, log = a["t"].translate(MINUS), pymupdf.Rect(a["r"]), None, False
        def sup_after(tok):  # a smaller, raised token right after tok
            for j, b in enumerate(raw):
                if j in used or b is tok: continue
                if b["size"] < 0.9 * tok["size"] and -0.5 < b["r"].x0 - tok["r"].x1 < 5 and b["r"].y1 < tok["r"].y1 - 0.5 and b["r"].y1 > tok["r"].y0 - 2:
                    return j, b
            return None, None
        if t == "10":
            j, b = sup_after(a)
            if b and INT.match(b["t"].translate(MINUS)):
                e = int(b["t"].translate(MINUS)) * (-1 if negated(b["r"]) and e_pos(b["t"]) else 1)
                used.add(j); v, log = 10.0 ** e, True; r |= b["r"]
        if v is None and NUM.match(t):
            # mantissa × 10^k ?
            nxt = [(j, b) for j, b in enumerate(raw) if j not in used and b["t"] in ("×", "x", "·") and 0 <= b["r"].x0 - r.x1 < 4 and abs(b["r"].y1 - r.y1) < 2]
            if nxt:
                jx, bx = nxt[0]
                ten = [(j, b) for j, b in enumerate(raw) if j not in used and b["t"] == "10" and 0 <= b["r"].x0 - bx["r"].x1 < 4 and abs(b["r"].y1 - r.y1) < 2]
                if ten:
                    jt, bt = ten[0]; js, bs = sup_after(bt)
                    if bs and INT.match(bs["t"].translate(MINUS)):
                        e = int(bs["t"].translate(MINUS)) * (-1 if negated(bs["r"]) and e_pos(bs["t"]) else 1)
                        used.update([jx, jt, js]); v = float(t) * 10.0 ** e; log = True
                        r |= bs["r"]
            if v is None: v = -float(t) if negated(a["r"]) and e_pos(t) else float(t)
        if v is None: continue
        used.add(i)
        out.append({"v": v, "log": log, "x0": r.x0, "x1": r.x1, "y0": r.y0, "y1": r.y1,
                    "cx": (r.x0 + r.x1) / 2, "cy": (a["r"].y0 + a["r"].y1) / 2, "color": a["color"]})
    return out


e_pos = lambda t: not t.translate(MINUS).startswith("-")


def fit(pairs, log=False):
    """Least squares value = a*coord + b (log10 value if log); drops at most one outlier.
    Returns (a, b, max relative residual, kept pairs) or None."""
    if log:
        if any(v <= 0 for _, v in pairs): return None
        pairs = [(c, math.log10(v)) for c, v in pairs]
    def ls(ps):
        vals = {round(v, 9) for _, v in ps}
        if len(ps) < 3 or len(vals) < 3: return None
        n = len(ps); sx = sum(c for c, _ in ps); sy = sum(v for _, v in ps)
        sxx = sum(c * c for c, _ in ps); sxy = sum(c * v for c, v in ps)
        d = n * sxx - sx * sx
        if abs(d) < 1e-9: return None
        a = (n * sxy - sx * sy) / d; b = (sy - a * sx) / n
        span = max(vals) - min(vals)
        res = [abs(a * c + b - v) / span for c, v in ps]
        return a, b, max(res), res
    f = ls(pairs)
    if f and f[2] > 0.02 and len(pairs) >= 5:
        k = f[3].index(f[2]); g = ls(pairs[:k] + pairs[k + 1:])
        if g and g[2] <= 0.02: return g[0], g[1], g[2], pairs[:k] + pairs[k + 1:]
    return (f[0], f[1], f[2], pairs) if f else None


def calibrate(toks, coord):
    """Linear or log scale from a group of tick labels; None if neither fits."""
    pairs = [(t[coord], t["v"]) for t in toks]
    if any(t["log"] for t in toks):
        f = fit(pairs, log=True); return (f, True) if f and f[2] <= 0.02 else None
    f = fit(pairs)
    if f and f[2] <= 0.02: return f, False
    g = fit(pairs, log=True)
    if g and g[2] <= 0.02: return g, True
    return None


def runs(toks, along, across, align_tol):
    """Groups of >=3 labels aligned on `across` with monotonic values along `along`."""
    toks = sorted(toks, key=lambda t: t[across])
    groups, cur = [], []
    for t in toks:
        if cur and abs(t[across] - cur[-1][across]) > align_tol: groups.append(cur); cur = []
        cur.append(t)
    if cur: groups.append(cur)
    out = []
    for g in groups:
        g = sorted(g, key=lambda t: t[along])
        seq = [g[0]]
        for t in g[1:]:
            gaps = [b[along] - a[along] for a, b in zip(seq, seq[1:])]
            sign = (seq[1]["v"] - seq[0]["v"]) if len(seq) > 1 else None
            ok = t[along] - seq[-1][along] > 1 and t["v"] != seq[-1]["v"]
            if ok and sign is not None and (t["v"] - seq[-1]["v"]) * sign <= 0: ok = False
            if ok and gaps and t[along] - seq[-1][along] > 2.6 * max(gaps): ok = False
            if not ok:
                if len(seq) >= 3: out.append(seq)
                seq = [t]
            else: seq.append(t)
        if len(seq) >= 3: out.append(seq)
    return out


# ---------------------------------------------------------------- drawings
def shape(d):
    pts = []
    for it in d["items"]:
        if it[0] == "l": pts += [it[1], it[2]]
        elif it[0] == "c": pts += [it[1], it[2], it[3], it[4]]
        elif it[0] == "re": r = it[1]; pts += [r.tl, r.tr, r.br, r.bl]
        elif it[0] == "qu": q = it[1]; pts += [q.ul, q.ur, q.lr, q.ll]
    return pts


def is_rect_path(d, pts):
    if len(d["items"]) == 1 and d["items"][0][0] in ("re", "qu"): return True
    if not (4 <= len(pts) <= 10): return False
    xs = sorted({round(p.x, 1) for p in pts}); ys = sorted({round(p.y, 1) for p in pts})
    near = lambda vals: len({round(v) for v in vals}) <= 2
    return all(it[0] == "l" for it in d["items"]) and near(xs) and near(ys)


rgb = lambda c: tuple(round(v, 3) for v in c) if c else None
hexc = lambda c: "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c)
is_gray = lambda c: c is not None and max(c) - min(c) < 0.06
is_light = lambda c: c is not None and min(c) > 0.93


def segments(drawings):
    """Long horizontal and vertical straight segments (axis spines, frames)."""
    H, V = [], []
    for d in drawings:
        if d.get("color") is None and d.get("fill") is None: continue
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.y - b.y) < 0.6 and abs(a.x - b.x) > 30: H.append((min(a.x, b.x), max(a.x, b.x), (a.y + b.y) / 2))
                if abs(a.x - b.x) < 0.6 and abs(a.y - b.y) > 30: V.append((min(a.y, b.y), max(a.y, b.y), (a.x + b.x) / 2))
            elif it[0] == "re" and d.get("color") is not None:
                r = it[1]
                if r.width > 30 and r.height > 30:
                    H += [(r.x0, r.x1, r.y0), (r.x0, r.x1, r.y1)]; V += [(r.y0, r.y1, r.x0), (r.y0, r.y1, r.x1)]
    return H, V


# ---------------------------------------------------------------- panels
def find_panels(toks, drawings, rect):
    xruns = [r for r in runs(toks, "cx", "cy", 2.5)]
    xr_ids = {id(t) for r in xruns for t in r}
    rest = [t for t in toks if id(t) not in xr_ids]
    lcols = runs(rest, "cy", "x1", 3)
    rcols = runs(rest, "cy", "x0", 3)
    H, V = segments(drawings)
    panels = []
    for C in lcols:
        cy = calibrate(C, "cy")
        if not cy: continue
        top, bot, right = min(t["y0"] for t in C), max(t["y1"] for t in C), max(t["x1"] for t in C)
        # x labels: the nearest run below, starting just right of the y labels
        cands = [R for R in xruns if R[0]["x0"] > right - 6 and R[0]["x0"] < right + 70 and R[0]["cy"] > bot - 4]
        if not cands: continue
        R = min(cands, key=lambda R: R[0]["cy"] - bot)
        cx = calibrate(R, "cx")
        if not cx: continue
        # plot box: the tick range plus ~half a tick step, widened to the axis spines when they are drawn
        sx = (R[-1]["cx"] - R[0]["cx"]) / (len(R) - 1); sy = (C[-1]["cy"] - C[0]["cy"]) / (len(C) - 1)
        x0, x1 = R[0]["cx"] - 0.6 * sx, R[-1]["cx"] + 0.6 * sx
        y0, y1 = C[0]["cy"] - 0.6 * sy, C[-1]["cy"] + 0.6 * sy
        left = [v for v in V if right + 0.3 < v[2] < R[0]["cx"] + 0.6 and v[0] <= C[0]["cy"] + 1 and v[1] >= C[-1]["cy"] - 1]
        bottom = [h for h in H if C[-1]["cy"] - 1 <= h[2] < R[0]["y0"] + 1 and h[0] <= R[0]["cx"] + 1 and h[1] >= R[-1]["cx"] - 1]
        # a spine much longer than the tick range belongs to a taller (shared) frame, not this panel
        left = [v for v in left if C[0]["cy"] - v[0] < sy + 6 and v[1] - C[-1]["cy"] < sy + 6]
        if left:
            v = min(left, key=lambda v: v[2]); x0, y0, y1 = v[2], min(y0, v[0]), max(y1, v[1])
        if bottom:
            h = max(bottom, key=lambda h: h[2]); y1, x1 = max(y1, h[2]), h[1]
            if not left: x0 = h[0]
        y1 = min(y1, R[0]["y0"])
        box = pymupdf.Rect(max(x0, right + 0.3), y0, x1, y1)
        # right-hand y axis: left-aligned labels just right of the box, same vertical range
        C2 = next((K for K in rcols if R[-1]["cx"] - 4 < K[0]["x0"] < max(box.x1, R[-1]["cx"]) + 25 and K[0]["cy"] < box.y1 + 3 and K[-1]["cy"] > box.y0 - 3), None)
        cy2 = calibrate(C2, "cy") if C2 else None
        if cy2: box.x1 = min(box.x1, min(t["x0"] for t in C2) - 0.5)
        if box.width < 40 or box.height < 30: continue
        title = None
        panels.append({"box": box, "xt": R, "yt": C, "y2t": C2 if cy2 else None, "fx": cx, "fy": cy, "fy2": cy2, "title": title})
    # panels stacked in one column: split overlapping boxes between the neighbouring tick labels
    for p in panels:
        for q in panels:
            if p is q or p["box"].y0 >= q["box"].y0: continue
            if min(p["box"].x1, q["box"].x1) - max(p["box"].x0, q["box"].x0) < 20 or p["box"].y1 <= q["box"].y0: continue
            lo, hi = max(t["y1"] for t in p["yt"]), min(t["y0"] for t in q["yt"])
            if lo < hi:
                m = (lo + hi) / 2; p["box"].y1 = min(p["box"].y1, m); q["box"].y0 = max(q["box"].y0, m)
    # drop panels whose boxes overlap a larger one (duplicate detection)
    panels.sort(key=lambda p: (round(p["box"].y0 / 20), p["box"].x0))
    keep = []
    for p in panels:
        if any((p["box"] & q["box"]).get_area() > 0.5 * p["box"].get_area() for q in keep): continue
        keep.append(p)
    return keep


def conv(f):
    (a, b, *_), log = f
    return (lambda c: 10 ** (a * c + b)) if log else (lambda c: a * c + b)


def digitize(doc, paper, fig_id):
    blk = next(b for b in paper["blocks"] if b.get("id") == fig_id)
    page = doc[blk["page"] - 1]
    rect = pymupdf.Rect(blk["rect"])
    if any(pymupdf.Rect(i["bbox"]).intersects(rect) and (pymupdf.Rect(i["bbox"]) & rect).get_area() > 400 for i in page.get_image_info()):
        return None, "figure contains a bitmap"
    drawings = [d for d in page.get_drawings() if rect.intersects(d["rect"])]
    toks = tokens(page, rect, drawings)
    panels = find_panels(toks, drawings, rect)
    if not panels: return None, "no panel with numeric tick labels on both axes"
    words = page.get_text("words", clip=rect)

    def text_right_of(x1, yc):
        cand = sorted([w for w in words if -0.5 <= w[0] - x1 < 10 and abs((w[1] + w[3]) / 2 - yc) < 4], key=lambda w: w[0])
        if not cand: return None
        out, last = [], None
        for w in sorted([w for w in words if abs((w[1] + w[3]) / 2 - (cand[0][1] + cand[0][3]) / 2) < 2.5 and w[0] >= cand[0][0]], key=lambda w: w[0]):
            if last is not None and w[0] - last > 9: break
            out.append(w[4]); last = w[2]
        return " ".join(out)

    # legend entries: short line, small filled box or marker followed by text
    line_names, fill_names, mark_names = {}, {}, {}
    for d in drawings:
        r = d["rect"]; stroke, fill = rgb(d.get("color")), rgb(d.get("fill"))
        dash = bool(d.get("dashes") and d["dashes"] not in ("[] 0", "[ ] 0"))
        if stroke and not fill and r.height < 2 and 5 < r.width < 45:
            n = text_right_of(r.x1 + 0.5, (r.y0 + r.y1) / 2)
            if n: line_names.setdefault((stroke, dash), n)
        elif fill and 3 < r.width < 25 and 2 < r.height < 14:
            n = text_right_of(r.x1 + 0.5, (r.y0 + r.y1) / 2)
            if n: fill_names.setdefault(fill, n); mark_names.setdefault(fill, n)
        elif (fill or stroke) and r.width < 7.5 and r.height < 7.5:
            n = text_right_of(r.x1 + 0.5, (r.y0 + r.y1) / 2)
            if n: mark_names.setdefault(fill or stroke, n)

    out_panels, problems = [], []
    for pi, P in enumerate(panels):
        box = P["box"]
        tx, ty, ty2 = conv(P["fx"]), conv(P["fy"]), conv(P["fy2"]) if P["fy2"] else None
        inb = lambda x, y, m=2.5: box.x0 - m <= x <= box.x1 + m and box.y0 - m <= y <= box.y1 + m
        mine = []
        for d in drawings:
            pts = shape(d)
            if len(pts) < 2: continue
            k = sum(inb(p.x, p.y) for p in pts)
            if k >= max(1, 0.6 * len(pts)): mine.append((d, pts))
        frames = []
        for d, pts in mine:
            r = d["rect"]
            on_border = all(min(abs(p.x - r.x0), abs(p.x - r.x1), abs(p.y - r.y0), abs(p.y - r.y1)) < 3 for p in pts)
            if r.width > 20 and r.height > 10 and (is_rect_path(d, pts) or on_border and len(pts) <= 60) \
               and r.width * r.height < 0.4 * box.width * box.height and (d.get("color") is not None or is_light(rgb(d.get("fill")))) \
               and (box + (-3, -3, 3, 3)).intersects(r) and not (r.width > 0.8 * box.width and r.height > 0.6 * box.height):
                frames.append(r)
        in_frame = lambda x, y: any(f.x0 - 1 <= x <= f.x1 + 1 and f.y0 - 1 <= y <= f.y1 + 1 for f in frames)

        lines, marks, bars, areas = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
        for d, pts in mine:
            r = d["rect"]; stroke, fill = rgb(d.get("color")), rgb(d.get("fill"))
            cxm, cym = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
            if in_frame(cxm, cym) and not (r.width > 0.9 * box.width): continue
            if r.width >= box.width - 2 and r.height >= box.height - 2: continue               # axes background or frame
            tiny_bar = fill and is_rect_path(d, pts) and abs(r.width - r.height) > 0.3 and (bars.get((fill, round(d.get("fill_opacity") or 1, 2))) or r.height < 1.5)
            closed = d.get("closePath") or fill is not None or any(it[0] in ("c", "re", "qu") for it in d["items"])
            if r.width < 7.5 and r.height < 7.5 and len(pts) >= 3 and (fill or stroke) and closed and not tiny_bar:
                marks[(fill or stroke)].append((cxm, cym, r, round(d.get("fill_opacity") or 1, 2), is_rect_path(d, pts))); continue
            if fill and not is_light(fill) and is_rect_path(d, pts):
                if r.height >= 0.97 * box.height: continue                                     # shaded background band
                bars[(fill, round(d.get("fill_opacity") or 1, 2))].append(r); continue
            if fill and not is_light(fill) and len(pts) > 6 and r.width > 4:
                areas[(fill, round(d.get("fill_opacity") or 1, 2))].append(pts)
                if stroke is None: continue
            if stroke is None: continue
            if is_rect_path(d, pts) and len(pts) <= 5: continue                                  # bar outline
            if (r.width < 0.8 or r.height < 0.8) and len(pts) <= 4: continue                    # axis, tick, grid, swatch
            if is_gray(stroke) and stroke[0] > 0.75: continue                                   # light grid
            dash = bool(d.get("dashes") and d["dashes"] not in ("[] 0", "[ ] 0"))
            lines[(stroke, dash)].append(pts)

        def int_color(c): return (int(c[0] * 255) << 16) | (int(c[1] * 255) << 8) | int(c[2] * 255)
        lcol = {t["color"] for t in P["yt"]}; rcol = {t["color"] for t in P["y2t"]} if P["y2t"] else set()
        def axis_of(c):
            if not P["y2t"]: return "y"
            dist = lambda a, b: sum(abs(((a >> k) & 255) - ((b >> k) & 255)) for k in (0, 8, 16))
            if lcol == rcol: return None                                         # both axes labelled in the same colour
            dl = min(dist(int_color(c), x) for x in lcol); dr = min(dist(int_color(c), x) for x in rcol)
            if min(dl, dr) > 200 or abs(dl - dr) < 60: return None
            return "y" if dl < dr else "y2"
        def pt(x, y, axis): return [round(tx(x), 7), round((ty2 if axis == "y2" else ty)(y), 7)]

        series = []
        for (c, dash), polys in lines.items():
            axis = axis_of(c)
            if axis is None: problems.append("curve colour matches neither y axis"); continue
            segs = []
            for poly in polys:
                pl = []
                for p in poly:
                    if not inb(p.x, p.y, 1) or in_frame(p.x, p.y):
                        if len(pl) >= 2: segs.append(pl)
                        pl = []; continue
                    q = pt(p.x, p.y, axis)
                    if not pl or q != pl[-1]: pl.append(q)
                if len(pl) >= 2: segs.append(pl)
            joined = []
            for pl in segs:
                if joined and joined[-1][-1] == pl[0]: joined[-1].extend(pl[1:])
                else: joined.append(pl)
            if sum(len(l) for l in joined) < 4: continue
            series.append({"kind": "line", "name": line_names.get((c, dash), ""), "color": hexc(c), "dash": dash, "axis": axis,
                           "lines": joined, "markers": []})
        for c in list(marks):
            ms = marks[c]
            key = next((k for k in bars if k[0] == c), None)
            if key:
                bars[key] += [m[2] for m in ms]; del marks[c]
        for c, ms in marks.items():
            # legend markers are usually drawn larger than the data markers of the same colour
            sizes = sorted(max(m[2].width, m[2].height) for m in ms)
            med = sizes[len(sizes) // 2]
            ms = [m for m in ms if max(m[2].width, m[2].height) <= 1.6 * med + 0.2]
            # a marker with text right next to it is a legend entry, not data
            pts_ = sorted(pt(x, y, axis_of(c) or "y") for x, y, r, *_ in ms if inb(x, y) and not in_frame(x, y) and not text_right_of(r.x1 + 0.5, y))
            if len(pts_) < 3: continue
            tgt = next((s for s in series if s["color"] == hexc(c) and not s["markers"]), None)
            if tgt: tgt["markers"] = pts_
            else: series.append({"kind": "line", "name": mark_names.get(c, ""), "color": hexc(c), "dash": False,
                                 "axis": axis_of(c) or "y", "lines": [], "markers": pts_})
        base_y = box.y1
        for (c, op), rs in bars.items():
            if len(rs) < 2: continue
            axis = axis_of(c) or "y"
            bl = []
            for r in sorted(rs, key=lambda r: r.x0):
                if not inb(r.x0, r.y0) or not inb(r.x1, r.y1): continue
                lo, hi = pt(r.x0, r.y1, axis), pt(r.x1, r.y0, axis)
                bl.append([lo[0], hi[0], lo[1], hi[1]])
            if len(bl) >= 2:
                series.append({"kind": "bars", "name": fill_names.get(c, ""), "color": hexc(c), "opacity": op, "axis": axis, "bars": bl})
        for (c, op), polys in areas.items():
            axis = axis_of(c) or "y"
            ps = []
            for poly in polys:
                q = [pt(min(max(p.x, box.x0), box.x1), min(max(p.y, box.y0), box.y1), axis) for p in poly]
                if len(q) > 6: ps.append(q)
            if ps:
                series.append({"kind": "area", "name": fill_names.get(c, ""), "color": hexc(c), "opacity": op, "axis": axis, "polys": ps})
        if not series: problems.append(f"panel {pi + 1}: nothing drawn"); continue
        xs = [p[0] for s in series for l in s.get("lines", []) for p in l] + [p[0] for s in series for p in s.get("markers", [])] \
            + [v for s in series for b in s.get("bars", []) for v in b[:2]] + [p[0] for s in series for q in s.get("polys", []) for p in q]
        xv = [t["v"] for t in P["xt"]]
        span = (math.log10(max(xv)) - math.log10(min(xv))) if P["fx"][1] else (max(xv) - min(xv))
        cover = (math.log10(max(xs)) - math.log10(min(xs))) if P["fx"][1] and min(xs) > 0 else (max(xs) - min(xs))
        if cover < 0.3 * span: problems.append(f"panel {pi + 1}: data cover too little of the x axis"); continue
        # x title: words just below the x labels
        xb = max(t["y1"] for t in P["xt"])
        xt = " ".join(w[4] for w in sorted([w for w in words if xb < w[1] < xb + 14 and box.x0 - 10 < w[0] < box.x1 and not NUM.match(w[4].translate(MINUS))], key=lambda w: w[0]))[:80]
        # panel title: words just above the box
        tt = " ".join(w[4] for w in sorted([w for w in words if box.y0 - 16 < w[3] < box.y0 + 1 and box.x0 - 5 < w[0] < box.x1], key=lambda w: (round(w[1]), w[0])))[:60]
        out_panels.append({"title": tt, "box": [round(v, 1) for v in box],
                           "x": {"ticks": sorted(t["v"] for t in P["xt"]), "log": P["fx"][1], "title": xt},
                           "y": {"ticks": sorted(t["v"] for t in P["yt"]), "log": P["fy"][1]},
                           "y2": {"ticks": sorted(t["v"] for t in P["y2t"]), "log": P["fy2"][1]} if P["fy2"] else None,
                           "series": series})
    if not out_panels: return None, "; ".join(problems) or "nothing recovered"
    return {"source": {"page": blk["page"], "figure": fig_id}, "panels": out_panels, "problems": problems}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("targets", nargs="+")
    a = ap.parse_args()
    doc = pymupdf.open(a.pdf)
    for t in a.targets:
        pid, fid = t.split(":")
        paper = json.loads((ROOT / "proceedings" / pid / "paper.json").read_text())
        try:
            data, why = digitize(doc, paper, fid)
        except Exception as e:  # report and carry on with the next figure
            data, why = None, f"error: {e!r}"
        out = ROOT / "proceedings" / pid / "plots" / f"{fid}.json"
        if not data:
            out.unlink(missing_ok=True)
            print(f"SKIP {t}: {why}"); continue
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(data, separators=(",", ":")))
        desc = [f"{len(p['series'])}s[{','.join(s['kind'][0] for s in p['series'])}]{'log' if p['x']['log'] or p['y']['log'] else ''}" for p in data["panels"]]
        print(f"OK   {t}: {len(data['panels'])} panel(s) {' '.join(desc)}{'  !' + '; '.join(data['problems']) if data['problems'] else ''}")


if __name__ == "__main__":
    main()

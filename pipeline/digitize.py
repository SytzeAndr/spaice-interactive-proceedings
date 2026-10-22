"""Recover the data behind vector line plots in the proceedings PDF.

Usage: python pipeline/digitize.py <proceedings.pdf> <paper-id>:<figure-id> [...]

For a figure drawn as vector graphics (not a bitmap), the PDF still contains every line
segment of every curve. This script reads those segments, reads the numeric tick labels to
calibrate the axes (including a second y axis on the right, matched by colour), and writes
proceedings/<paper-id>/plots/<figure-id>.json with the data in the plot's own units.

Only single-panel plots with linear axes are handled. Anything that fails a sanity check is
skipped and reported, never guessed. The site shows a recovered plot only for figures listed
in proceedings/interactive.json, after a person has compared the replot with the original.
"""
import argparse, json, re
from collections import defaultdict
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
NUM = re.compile(r"^[−-]?\d+(?:[.,]\d+)?$")


def to_float(s):
    return float(s.replace("−", "-").replace(",", "."))


def fit(pairs):
    """Least-squares value = a*coord + b; returns (a, b, max relative residual) or None."""
    vals = {v for _, v in pairs}
    if len(pairs) < 3 or len(vals) < 3: return None
    n = len(pairs)
    sx = sum(c for c, _ in pairs); sy = sum(v for _, v in pairs)
    sxx = sum(c * c for c, _ in pairs); sxy = sum(c * v for c, v in pairs)
    d = n * sxx - sx * sx
    if abs(d) < 1e-9: return None
    a = (n * sxy - sx * sy) / d; b = (sy - a * sx) / n
    span = max(vals) - min(vals)
    return a, b, max(abs(a * c + b - v) for c, v in pairs) / span


def numeric_spans(page, rect):
    """Numeric tick labels with their colour (spans carry colour, words do not)."""
    out = []
    for b in page.get_text("dict", clip=rect)["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                t = s["text"].strip()
                if NUM.match(t) and s["size"] < 11:
                    x0, y0, x1, y1 = s["bbox"]
                    out.append({"v": to_float(t), "x0": x0, "x1": x1, "y0": y0, "y1": y1, "color": s["color"], "size": s["size"]})
    return out


def find_axes(spans, rect):
    # x axis: lowest row of >=3 labels sharing a baseline
    rows = defaultdict(list)
    for s in spans: rows[round((s["y0"] + s["y1"]) / 2 / 2)].append(s)
    xrow = None
    for k in sorted(rows, reverse=True):
        if len(rows[k]) >= 3: xrow = sorted(rows[k], key=lambda s: s["x0"]); break
    if not xrow: return None
    rest = [s for s in spans if s not in xrow and s["y1"] <= xrow[0]["y0"] + 2]
    # y axes: columns of right-aligned (left axis) or left-aligned (right axis) labels
    left = defaultdict(list); right = defaultdict(list)
    for s in rest:
        left[round(s["x1"] / 3)].append(s); right[round(s["x0"] / 3)].append(s)
    lcol = next((left[k] for k in sorted(left) if len(left[k]) >= 3), None)
    rcol = next((right[k] for k in sorted(right, reverse=True) if len(right[k]) >= 3 and right[k] != lcol
                 and min(s["x0"] for s in right[k]) > (max(s["x1"] for s in lcol) if lcol else 0) + 60), None)
    return xrow, lcol, rcol


def shape(d):
    pts = []
    for it in d["items"]:
        if it[0] == "l": pts += [it[1], it[2]]
        elif it[0] == "c": pts += [it[1], it[2], it[3], it[4]]
        elif it[0] == "re": r = it[1]; pts += [r.tl, r.tr, r.br, r.bl]
        elif it[0] == "qu": q = it[1]; pts += [q.ul, q.ur, q.lr, q.ll]
    return pts


def rgb(c):
    return tuple(round(v, 3) for v in c) if c else None


def is_gray(c):
    return c is not None and max(c) - min(c) < 0.06


def digitize(doc, paper, fig_id):
    blk = next(b for b in paper["blocks"] if b.get("id") == fig_id)
    page = doc[blk["page"] - 1]
    rect = pymupdf.Rect(blk["rect"])
    if any(pymupdf.Rect(i["bbox"]).intersects(rect) for i in page.get_image_info()):
        return None, "figure contains a bitmap"
    spans = numeric_spans(page, rect)
    axes = find_axes(spans, rect)
    if not axes or not axes[1]: return None, "no numeric tick labels on both axes"
    xrow, lcol, rcol = axes
    fx = fit([((s["x0"] + s["x1"]) / 2, s["v"]) for s in xrow])
    fy = fit([((s["y0"] + s["y1"]) / 2, s["v"]) for s in lcol])
    fy2 = fit([((s["y0"] + s["y1"]) / 2, s["v"]) for s in rcol]) if rcol else None
    if not fx or not fy or fx[2] > 0.02 or fy[2] > 0.02 or (rcol and (not fy2 or fy2[2] > 0.02)):
        return None, "tick labels are not linear (log axis, offsets or several panels)"
    box = pymupdf.Rect(max(s["x1"] for s in lcol), min(s["y0"] for s in lcol) - 8,
                       min(s["x0"] for s in rcol) if rcol else rect.x1, min(s["y0"] for s in xrow))
    if box.width < 60 or box.height < 40: return None, "plot area too small"

    drawings = [d for d in page.get_drawings() if rect.intersects(d["rect"])]
    frames, lines, markers = [], defaultdict(list), defaultdict(list)
    for d in drawings:
        pts = shape(d)
        if len(pts) < 2: continue
        r = d["rect"]
        stroke, fill = rgb(d.get("color")), rgb(d.get("fill"))
        small = r.width < 7.5 and r.height < 7.5
        if small and (fill or stroke) and len(pts) >= 3:          # a plot marker
            markers[fill or stroke].append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
            continue
        rectish = d.get("closePath") or any(it[0] in ("re", "qu") for it in d["items"])
        on_border = all(min(abs(p.x - r.x0), abs(p.x - r.x1), abs(p.y - r.y0), abs(p.y - r.y1)) < 3 for p in pts)
        if r.width > 25 and r.height > 12 and ((rectish and len(pts) <= 16) or (on_border and len(pts) <= 60)):
            frames.append(r); continue                             # axes box, legend box, inset
        if stroke is None: continue                                # filled areas (bands, bars)
        if r.width < 0.8 or r.height < 0.8:
            if len(pts) <= 4: continue                             # straight line: axis, tick, grid, swatch
        if is_gray(stroke) and stroke[0] > 0.8: continue           # light grid
        dash = bool(d.get("dashes") and d["dashes"] not in ("[] 0", "[ ] 0"))
        lines[(stroke, dash)].append(pts)

    plot_area = box.width * box.height
    insets = [f for f in frames if box.contains(f) and f.width * f.height < 0.6 * plot_area]
    inside_inset = lambda x, y: any(f.x0 - 1 <= x <= f.x1 + 1 and f.y0 - 1 <= y <= f.y1 + 1 for f in insets)
    in_box = lambda x, y: box.x0 - 3 <= x <= box.x1 + 3 and box.y0 - 3 <= y <= box.y1 + 3

    # legend: swatch (short line or marker) followed by text, often inside a legend frame
    words = page.get_text("words", clip=rect)
    def text_right_of(x1, yc):
        cand = sorted([w for w in words if 0 <= w[0] - x1 < 10 and abs((w[1] + w[3]) / 2 - yc) < 4], key=lambda w: w[0])
        if not cand: return None
        out, last = [], None
        for w in sorted([w for w in words if abs((w[1] + w[3]) / 2 - (cand[0][1] + cand[0][3]) / 2) < 2.5 and w[0] >= cand[0][0]], key=lambda w: w[0]):
            if last is not None and w[0] - last > 9: break
            out.append(w[4]); last = w[2]
        return " ".join(out)
    line_names, color_names, style_names = {}, {}, {}
    for d in drawings:
        r = d["rect"]; stroke = rgb(d.get("color"))
        if stroke and r.height < 1.6 and 5 < r.width < 45:
            name = text_right_of(r.x1, r.y0)
            if not name: continue
            dash = bool(d.get("dashes") and d["dashes"] not in ("[] 0", "[ ] 0"))
            line_names.setdefault((stroke, dash), name)
            if is_gray(stroke) and stroke[0] < 0.3: style_names.setdefault(dash, name)
    for c, ms in markers.items():
        for (x, y) in ms:
            name = text_right_of(x + 3, y)
            if name: color_names.setdefault(c, name)

    tx = lambda x: fx[0] * x + fx[1]
    def ty(y, axis): f = fy2 if axis == "y2" else fy; return f[0] * y + f[1]
    # which y axis does a colour belong to? match tick label colours
    def int_color(c): return (int(c[0] * 255) << 16) | (int(c[1] * 255) << 8) | int(c[2] * 255)
    lcolors = {s["color"] for s in lcol}; rcolors = {s["color"] for s in rcol} if rcol else set()
    def axis_of(c):
        if not rcol: return "y"
        ic = int_color(c)
        close = lambda a, b: all(abs(((a >> k) & 255) - ((b >> k) & 255)) < 40 for k in (0, 8, 16))
        on_r = any(close(ic, rc) for rc in rcolors) and rcolors != {0}
        on_l = any(close(ic, lc) for lc in lcolors) and lcolors != {0}
        if on_r and not on_l: return "y2"
        if on_l and not on_r: return "y"
        return None

    series = []
    for (c, dash), polys in lines.items():
        axis = axis_of(c)
        if axis is None: return None, "two y axes but a curve's axis cannot be told from its colour"
        segs = []
        for poly in polys:
            pl = []
            for p in poly:
                if not in_box(p.x, p.y) or inside_inset(p.x, p.y): continue
                q = [round(tx(p.x), 6), round(ty(p.y, axis), 6)]
                if not pl or q != pl[-1]: pl.append(q)
            if len(pl) >= 2: segs.append(pl)
        joined = []
        for pl in segs:
            if joined and joined[-1][-1] == pl[0]: joined[-1].extend(pl[1:])
            else: joined.append(pl)
        n = sum(len(l) for l in joined)
        if n < 6: continue
        name = line_names.get((c, dash)) or " ".join(x for x in (color_names.get(c), style_names.get(dash)) if x) or ""
        series.append({"name": name, "color": "#%02x%02x%02x" % tuple(int(v * 255) for v in c), "dash": dash, "axis": axis, "lines": joined, "markers": []})
    for c, ms in markers.items():
        pts = [[round(tx(x), 6), round(ty(y, axis_of(c) or "y"), 6)] for x, y in ms if in_box(x, y) and not inside_inset(x, y)]
        if len(pts) < 3: continue
        target = next((s for s in series if s["color"] == "#%02x%02x%02x" % tuple(int(v * 255) for v in c) and not s["markers"]), None)
        if target: target["markers"] = sorted(pts)
        else:
            series.append({"name": color_names.get(c, ""), "color": "#%02x%02x%02x" % tuple(int(v * 255) for v in c), "dash": False,
                           "axis": axis_of(c) or "y", "lines": [], "markers": sorted(pts)})
    if not series: return None, "no curves found"
    xs = [p[0] for s in series for l in s["lines"] for p in l] + [p[0] for s in series for p in s["markers"]]
    xr = (min(s["v"] for s in xrow), max(s["v"] for s in xrow))
    if max(xs) - min(xs) < 0.4 * (xr[1] - xr[0]): return None, "curves cover too little of the x axis"
    def title(axis_words):
        return " ".join(w[4] for w in axis_words)[:80]
    xt = title(sorted([w for w in words if w[1] > max(s["y1"] for s in xrow) + 0.5 and w[1] < max(s["y1"] for s in xrow) + 16 and not NUM.match(w[4])], key=lambda w: w[0]))
    return {"source": {"page": blk["page"], "figure": fig_id},
            "x": {"ticks": sorted(s["v"] for s in xrow), "title": xt},
            "y": {"ticks": sorted(s["v"] for s in lcol)},
            "y2": {"ticks": sorted(s["v"] for s in rcol)} if rcol else None,
            "series": series}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("targets", nargs="+")
    a = ap.parse_args()
    doc = pymupdf.open(a.pdf)
    for t in a.targets:
        pid, fid = t.split(":")
        paper = json.loads((ROOT / "proceedings" / pid / "paper.json").read_text())
        data, why = digitize(doc, paper, fid)
        out = ROOT / "proceedings" / pid / "plots" / f"{fid}.json"
        if not data:
            out.unlink(missing_ok=True)
            print(f"SKIP {t}: {why}"); continue
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(data, separators=(",", ":")))
        n = sum(len(l) for s in data["series"] for l in s["lines"]) + sum(len(s["markers"]) for s in data["series"])
        print(f"OK   {t}: {len(data['series'])} series, {n} points, names {[s['name'] for s in data['series']]}")


if __name__ == "__main__":
    main()

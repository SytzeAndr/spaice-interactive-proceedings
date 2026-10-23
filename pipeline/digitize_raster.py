"""Recover the data behind charts that are embedded in the PDF as images.

Usage: python pipeline/digitize_raster.py <proceedings.pdf> <paper-id>:<figure-id>[@<image-number>] [...]
       add --debug <dir> to save an annotated picture of what was detected

Steps, on the embedded image at its native resolution:
  1. the axes: the longest dark horizontal line in the lower part (x axis) and the longest
     dark vertical line in the left part (y axis);
  2. the tick labels: text recognition (tesseract) left of the y axis and below the x axis,
     calibrated with a straight-line fit that must agree to 2% of the axis range;
  3. the data: coloured pixels inside the axes, grouped by colour. A colour whose pixels reach
     down to the x axis in solid columns becomes bars; a pale colour becomes a shaded area
     (lowest and highest pixel per column); any other colour becomes a line (one point per
     pixel column). Text inside the axes (the legend) is masked out first.

Black and grey curves cannot be told apart from axes, grid lines and text, so they are skipped.
As with the vector digitizer, nothing is shown on the site until a person has compared the
replot with the original and listed it in proceedings/interactive.json.
"""
import argparse, io, json, re, subprocess, tempfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
NUMRE = re.compile(r"^[−–-]?\d+(?:[.,]\d+)?%?$")


def native_images(doc, page, rect):
    """Embedded images that overlap the figure, largest overlap first, as RGB arrays."""
    out = []
    for info in page.get_image_info(xrefs=True):
        r = pymupdf.Rect(info["bbox"])
        if not r.intersects(rect) or (r & rect).get_area() < 0.15 * r.get_area(): continue
        try:
            pix = pymupdf.Pixmap(doc, info["xref"])
            if pix.alpha or pix.n != 3: pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            if pix.alpha: pix = pymupdf.Pixmap(pix, 0)
            img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
        except Exception:
            continue
        out.append(((r & rect).get_area(), r, img))
    out.sort(key=lambda t: -t[0])
    return [(r, img) for _, r, img in out]


def longest_runs(mask, axis):
    """Length and start of the longest run of True along each row (axis=1) or column (axis=0)."""
    m = mask if axis == 1 else mask.T
    best = np.zeros(m.shape[0], int); start = np.zeros(m.shape[0], int)
    for i, row in enumerate(m):
        if not row.any(): continue
        d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        s, e = np.where(d == 1)[0], np.where(d == -1)[0]
        k = np.argmax(e - s); best[i] = e[k] - s[k]; start[i] = s[k]
    return best, start


def find_axes(img):
    g = img.mean(axis=2)
    H, W = g.shape
    dark = g < 140
    rl, rs = longest_runs(dark, 1)
    cl, cs = longest_runs(dark, 0)
    rows = [y for y in range(int(H * 0.3), H) if rl[y] > 0.35 * W]
    cols = [x for x in range(0, int(W * 0.6)) if cl[x] > 0.3 * H]
    if not rows or not cols: return None
    y_ax = max(rows, key=lambda y: (rl[y] > 0.9 * max(rl[r] for r in rows), y))     # lowest of the long ones
    x_ax = min(cols, key=lambda x: (not cl[x] > 0.9 * max(cl[c] for c in cols), x))  # leftmost of the long ones
    x0, x1 = x_ax, rs[y_ax] + rl[y_ax]
    y1, y0 = y_ax, cs[x_ax]
    # a frame on the top / right, if drawn
    tops = [y for y in range(y0 - 3, y1 - 20) if rl[y] > 0.8 * (x1 - x0)]
    if tops: y0 = min(tops)
    rights = [x for x in range(x0 + 20, min(W, x1 + 3)) if cl[x] > 0.8 * (y1 - y0)]
    if rights: x1 = max(rights)
    if x1 - x0 < 80 or y1 - y0 < 60: return None
    return x0, y0, x1, y1


def ocr(img, box, scale=3, psm=11, whitelist=None):
    """Words with boxes in image coordinates: [(text, conf, x0, y0, x1, y1)]."""
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0); x1, y1 = min(img.shape[1], x1), min(img.shape[0], y1)
    if x1 - x0 < 5 or y1 - y0 < 5: return []
    crop = Image.fromarray(img[y0:y1, x0:x1]).convert("L").resize(((x1 - x0) * scale, (y1 - y0) * scale), Image.LANCZOS)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "c.png"; crop.save(p)
        cmd = ["tesseract", str(p), "stdout", "--psm", str(psm)]
        if whitelist: cmd += ["-c", f"tessedit_char_whitelist={whitelist}"]
        cmd += ["tsv"]
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
    words = []
    for line in out.splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 12 or not f[11].strip(): continue
        l, t, w, h, conf = int(f[6]), int(f[7]), int(f[8]), int(f[9]), float(f[10])
        words.append((f[11].strip(), conf, x0 + l / scale, y0 + t / scale, x0 + (l + w) / scale, y0 + (t + h) / scale))
    return words


def num(t):
    t = t.replace("−", "-").replace("–", "-").replace(",", ".").rstrip("%")
    try: return float(t)
    except ValueError: return None


def fit(pairs):
    if len(pairs) < 3 or len({v for _, v in pairs}) < 3: return None
    c = np.array([p[0] for p in pairs]); v = np.array([p[1] for p in pairs])
    a, b = np.polyfit(c, v, 1)
    res = np.abs(a * c + b - v) / (v.max() - v.min())
    if res.max() > 0.02 and len(pairs) >= 4:      # one misread label is tolerated
        k = int(np.argmax(res)); keep = [p for i, p in enumerate(pairs) if i != k]
        return fit(keep)
    return (a, b, keep_pairs(pairs)) if res.max() <= 0.02 else None


def keep_pairs(p): return p


def tick_labels(img, ax):
    """Read the x and y tick labels; tries a few recognition settings until both axes calibrate."""
    x0, y0, x1, y1 = ax
    H, W = img.shape[:2]
    xbox = (x0 - 0.06 * W, y1 + 2, x1 + 0.06 * W, min(H, y1 + 0.12 * H))
    ybox = (0, y0 - 0.04 * H, x0 - 2, y1 + 0.04 * H)
    def xlabels(scale, psm):
        ws = [w for w in ocr(img, xbox, scale, psm) if num(w[0]) is not None and w[1] > 30]
        if ws:
            top = min(w[3] for w in ws)
            ws = [w for w in ws if w[3] < top + 0.6 * (w[5] - w[3]) + 2]      # the first row below the axis
        return ws, fit([((w[2] + w[4]) / 2, num(w[0])) for w in ws])
    def ylabels(scale, psm):
        ws = [w for w in ocr(img, ybox, scale, psm) if num(w[0]) is not None and w[1] > 30]
        if ws:
            right = max(w[4] for w in ws)
            ws = [w for w in ws if w[4] > right - 6]                          # right-aligned column next to the axis
        return ws, fit([((w[3] + w[5]) / 2, num(w[0])) for w in ws])
    tries = [(3, 11), (4, 11), (2, 11), (3, 6), (5, 12)]
    below, fx = next(((w, f) for w, f in (xlabels(*t) for t in tries) if f), ([], None))
    left, fy = next(((w, f) for w, f in (ylabels(*t) for t in tries) if f), ([], None))
    return fx, fy, below, left


def colour_clusters(px):
    """Main colours among saturated pixels (anti-aliased blends are absorbed by the nearest)."""
    q = (px // 24).astype(np.int32)
    key = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    keys, inv, counts = np.unique(key, return_inverse=True, return_counts=True)
    order = np.argsort(-counts)
    centres = []
    for k in order[:40]:
        if counts[k] < max(40, 0.004 * len(px)): break
        c = px[inv == k].mean(axis=0)                     # mean colour of the pixels in this bin
        if all(np.abs(c - d).sum() > 90 for d in centres): centres.append(c)
    # the same hue at a different strength (anti-aliasing against white) is one colour
    def dirn(c):
        v = 255.0 - np.asarray(c, float); return v / (np.linalg.norm(v) + 1e-9)
    merged = []
    for c in sorted(centres, key=lambda c: -(np.max(c) - np.min(c))):
        if all(float(dirn(c) @ dirn(d)) < 0.985 for d in merged): merged.append(c)
    centres = merged
    return centres


def digitize(doc, paper, fig_id, image_no=0, debug=None):
    blk = next(b for b in paper["blocks"] if b.get("id") == fig_id)
    page = doc[blk["page"] - 1]
    imgs = native_images(doc, page, pymupdf.Rect(blk["rect"]))
    if len(imgs) <= image_no: return None, "no embedded image"
    _, img = imgs[image_no]
    if img.shape[1] < 300: return None, "image too small to read"
    ax = find_axes(img)
    if debug:
        im = Image.fromarray(img); dr = ImageDraw.Draw(im)
        if ax: dr.rectangle(ax, outline=(255, 0, 255), width=3)
        im.save(Path(debug) / f"{paper['meta']['id'][:30]}-{fig_id}-{image_no}-axes.png")
    if not ax: return None, "no axes found"
    fx, fy, xl, yl = tick_labels(img, ax)
    if not fx or not fy: return None, f"tick labels not readable (x {[w[0] for w in xl]}, y {[w[0] for w in yl]})"
    x0, y0, x1, y1 = ax
    H, W = img.shape[:2]
    # mask the legend and any other text inside the axes
    mask = np.zeros((H, W), bool)
    words = [w for w in ocr(img, (x0 + 2, y0 + 2, x1 - 2, y1 - 2), psm=11) if re.search(r"[A-Za-z]{2,}", w[0]) and w[1] > 55]
    for t, c, a, b, cc, d in words:
        h = d - b
        mask[int(max(0, b - 0.4 * h)):int(d + 0.4 * h), int(max(0, a - 4 * h)):int(cc + 0.5 * h)] = True
    region = img[y0 + 2:y1 - 1, x0 + 2:x1 - 1].astype(int)
    m = mask[y0 + 2:y1 - 1, x0 + 2:x1 - 1]
    sat = region.max(axis=2) - region.min(axis=2)
    if ((sat > 80) & ~m).sum() < 50: return None, "no coloured data inside the axes"
    centres = colour_clusters(region[(sat > 80) & ~m])           # main colours from strongly saturated pixels
    tx = lambda c: fx[0] * c + fx[1]
    ty = lambda r: fy[0] * r + fy[1]
    hh, ww = region.shape[:2]
    # every pixel as a blend of one main colour with the white background: p = white - alpha * (white - main)
    white = np.array([255.0, 255.0, 255.0])
    P = (white - region).reshape(-1, 3).astype(float)
    best_k = np.full(len(P), -1); best_a = np.zeros(len(P)); best_r = np.full(len(P), 1e9)
    for k, c in enumerate(centres):
        v = white - c; vv = (v * v).sum()
        if vv < 1: continue
        al = (P @ v) / vv
        res = np.sqrt(((P - al[:, None] * v[None, :]) ** 2).sum(axis=1))
        better = (res < best_r) & (al > 0.12) & (al < 1.35)
        best_k[better], best_a[better], best_r[better] = k, al[better], res[better]
    ok = (best_r < 38) & (sat.reshape(-1) > 18) & ~m.reshape(-1)
    best_k[~ok] = -1
    best_k = best_k.reshape(hh, ww); best_a = best_a.reshape(hh, ww)
    series = []
    for k, c in enumerate(centres):
        own = best_k == k
        strong = own & (best_a > 0.55)
        pale = own & (best_a <= 0.55)
        hexc = "#%02x%02x%02x" % tuple(int(v) for v in np.clip(c, 0, 255))
        # pale pixels in thick vertical runs: a shaded band of this colour
        pcols = np.where(pale.sum(axis=0) > 6)[0]
        if len(pcols) > 0.15 * ww:
            spans = []
            for x in pcols:
                ys = np.where(pale[:, x] | strong[:, x])[0]
                spans.append((x, ys.min(), ys.max()))
            if np.median([b - a for _, a, b in spans]) > 8:
                poly = [[round(tx(x0 + 2 + x), 6), round(ty(y0 + 2 + a), 6)] for x, a, _ in spans] + \
                       [[round(tx(x0 + 2 + x), 6), round(ty(y0 + 2 + b), 6)] for x, _, b in reversed(spans)]
                step = max(1, len(poly) // 800)
                series.append({"kind": "area", "name": "", "color": hexc, "opacity": 0.35, "axis": "y", "polys": [poly[::step]]})
        sel = strong
        colsum = sel.sum(axis=0)
        cols = np.where(colsum > 0)[0]
        if sel.sum() < 40 or len(cols) < 0.05 * ww: continue
        # bars: in most occupied columns the colour runs unbroken down to the axis
        tops = np.array([np.where(sel[:, x])[0].min() if colsum[x] else hh for x in range(ww)])
        lowest = np.array([np.where(sel[:, x])[0].max() if colsum[x] else -1 for x in range(ww)])
        solid = (colsum >= 0.85 * (lowest - tops + 1)) & (lowest >= hh - 4) & (colsum > 3)
        if solid.sum() > 0.6 * len(cols):
            bars, x = [], 0
            while x < ww:
                if solid[x]:
                    s0 = x
                    while x < ww and solid[x]: x += 1
                    if x - s0 >= 2:
                        top = np.median(tops[s0:x])
                        bars.append([round(tx(x0 + 2 + s0), 6), round(tx(x0 + 2 + x - 1), 6), round(ty(y1 - 1), 6), round(ty(y0 + 2 + top), 6)])
                else: x += 1
            if len(bars) >= 2: series.append({"kind": "bars", "name": "", "color": hexc, "opacity": 0.85, "axis": "y", "bars": bars})
            continue
        # lines: follow every curve of this colour from left to right; each pixel run in a column
        # continues the nearest open track (curves of one colour, e.g. solid and dashed, stay apart)
        tracks = []                                   # each: {"pts": [(x, y)], "last": (x, y)}
        nruns = [len(np.split(np.where(sel[:, x])[0], np.where(np.diff(np.where(sel[:, x])[0]) > 1)[0] + 1)) for x in cols]
        single = np.mean(np.array(nruns) <= 1) > 0.85      # one curve of this colour: no need to separate
        for x in cols:
            ys = np.where(sel[:, x])[0]
            runs = np.split(ys, np.where(np.diff(ys) > 1)[0] + 1)
            cand = [r.mean() for r in runs if len(r) <= 0.25 * hh]
            if single:
                prev = tracks[-1]["last"][1] if tracks else None
                yv = min(cand, key=lambda v: abs(v - prev)) if (prev is not None and cand) else (cand[0] if cand else None)
                if yv is None: continue
                if tracks and x - tracks[-1]["last"][0] <= 14: tracks[-1]["pts"].append((x, yv)); tracks[-1]["last"] = (x, yv)
                else: tracks.append({"pts": [(x, yv)], "last": (x, yv)})
                continue
            free = [t for t in tracks if x - t["last"][0] <= 14]
            pairs = sorted(((abs(t["last"][1] - y) + 0.5 * (x - t["last"][0]), i, j) for i, t in enumerate(free) for j, y in enumerate(cand)))
            used_t, used_c = set(), set()
            for d, i, j in pairs:
                if i in used_t or j in used_c or d > 0.06 * hh + 4: continue
                used_t.add(i); used_c.add(j); free[i]["pts"].append((x, cand[j])); free[i]["last"] = (x, cand[j])
            for j, y in enumerate(cand):
                if j not in used_c: tracks.append({"pts": [(x, y)], "last": (x, y)})
        lines = []
        for t in tracks:
            if len(t["pts"]) < max(10, 0.04 * ww): continue
            seg, out = [], []
            for (x, y) in t["pts"]:
                if seg and x - seg[-1][0] > 4:
                    out.append(seg); seg = []
                seg.append((x, y))
            out.append(seg)
            lines.append([[[round(tx(x0 + 2 + x), 6), round(ty(y0 + 2 + y), 6)] for x, y in sg] for sg in out if len(sg) >= 2])
        for k2, ln in enumerate(sorted(lines, key=lambda l: -sum(len(s) for s in l))):
            npts = sum(len(s) for s in ln)
            if npts < 10: continue
            span = ln[-1][-1][0] - ln[0][0][0]
            dash = len(ln) > 6 and npts < 0.8 * (span / (fx[0] or 1))   # many short pieces with gaps between
            series.append({"kind": "line", "name": "", "color": hexc, "dash": bool(dash), "axis": "y", "lines": ln, "markers": []})

    if debug:
        im = Image.fromarray(img); dr = ImageDraw.Draw(im)
        dr.rectangle([x0, y0, x1, y1], outline=(255, 0, 255), width=2)
        for t, c, a, b, cc, d in xl + yl: dr.rectangle([a, b, cc, d], outline=(0, 160, 0))
        for t, c, a, b, cc, d in words: dr.rectangle([a, b, cc, d], outline=(255, 0, 0))
        im.save(Path(debug) / f"{paper['meta']['id'][:30]}-{fig_id}-{image_no}.png")
    if not series: return None, "no series found"
    xt = sorted(num(w[0]) for w in xl); yt = sorted(num(w[0]) for w in yl)
    panel = {"title": "", "box": [int(x0), int(y0), int(x1), int(y1)], "x": {"ticks": xt, "log": False, "title": ""}, "y": {"ticks": yt, "log": False}, "y2": None, "series": series, "traced": True}
    return {"source": {"page": blk["page"], "figure": fig_id, "raster": True, "image": image_no}, "panels": [panel], "problems": []}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf"); ap.add_argument("targets", nargs="+"); ap.add_argument("--debug")
    a = ap.parse_args()
    doc = pymupdf.open(a.pdf)
    for t in a.targets:
        pid, rest = t.split(":"); fid, _, k = rest.partition("@")
        paper = json.loads((ROOT / "proceedings" / pid / "paper.json").read_text())
        try: data, why = digitize(doc, paper, fid, int(k or 0), a.debug)
        except Exception as e: data, why = None, f"error: {e!r}"
        out = ROOT / "proceedings" / pid / "plots" / f"{fid}.json"
        if not data:
            print(f"SKIP {t}: {why}"); continue
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(data, separators=(",", ":")))
        p = data["panels"][0]
        print(f"OK   {t}: {len(p['series'])}s[{','.join(s['kind'][0] for s in p['series'])}] x{p['x']['ticks']} y{p['y']['ticks']}")


if __name__ == "__main__":
    main()

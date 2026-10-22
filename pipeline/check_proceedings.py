"""Check every proceedings paper's extracted text against the PDF.

Usage: python pipeline/check_proceedings.py <proceedings.pdf> [--show <paper-id-or-number>] [--min 0.9]

For each paper: the share of the PDF's words (text layer, excluding running footers)
that appear on the site inside an identical run of 4 words. Words that live inside
figures, tables and display equations are shown as images and counted separately,
so a low "missing" share means no running text was lost.
"""
import argparse, json, re, sys
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
WORD = re.compile(r"[a-z]{2,}")
N = 4


def words(t):
    t = t.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("ﬀ", "ff").replace("ﬃ", "ffi").replace("­", "")
    t = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", t)
    return WORD.findall(t.lower())


def strip(h):
    return re.sub(r"<[^>]+>", " ", h or "")


def check(doc, paper):
    a, b = paper["meta"]["pages"]
    rects = {}
    for bl in paper["blocks"]:
        if "rect" in bl: rects.setdefault(bl["page"], []).append(pymupdf.Rect(bl["rect"]))
    pdf, inside = [], []
    for pno in range(a, b + 1):
        page = doc[pno - 1]
        for w in page.get_text("words"):
            r = pymupdf.Rect(w[:4])
            if r.y0 > 766: continue
            (inside if any(r.intersects(x) for x in rects.get(pno, [])) else pdf).append(w[4])
    joined = []
    for w in pdf:  # undo end-of-line hyphenation ("sustain-" + "able")
        if joined and joined[-1].endswith("-") and w[:1].islower(): joined[-1] = joined[-1][:-1] + w
        else: joined.append(w)
    pw = words(" ".join(joined))
    site = [paper["meta"]["title"], paper.get("abstract", ""), paper["meta"].get("authorsHtml", "")]
    site += paper["meta"].get("affiliations", [])
    for bl in paper["blocks"]:
        if bl["t"] == "p": site.append(bl["html"])
        elif bl["t"] == "h": site.append(f'{bl["num"]} {bl["title"]}')
        elif bl["t"] in ("figure", "table"):
            site.append(f'{bl.get("label", "")} {bl["num"]} {bl["caption"]}')
    site += paper.get("footnotes", []) + [r["html"] for r in paper["references"]]
    sw = words(" ".join(strip(x) for x in site))
    grams = {tuple(sw[i:i + N]) for i in range(len(sw) - N + 1)}
    cov = [False] * len(pw)
    for i in range(len(pw) - N + 1):
        if tuple(pw[i:i + N]) in grams: cov[i:i + N] = [True] * N
    missing, run = [], []
    for w, c in zip(pw + [""], cov + [True]):
        if not c: run.append(w)
        elif run: missing.append(" ".join(run)); run = []
    return sum(cov) / max(1, len(pw)), len(pw), len(words(" ".join(inside))), missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--show")
    ap.add_argument("--min", type=float, default=0.9)
    a = ap.parse_args()
    doc = pymupdf.open(a.pdf)
    idx = json.loads((ROOT / "proceedings/index.json").read_text())
    worst, bad = [], 0
    for i, p in enumerate(idx["papers"], 1):
        if a.show and a.show not in (p["id"], str(i)): continue
        paper = json.loads((ROOT / "proceedings" / p["id"] / "paper.json").read_text())
        cov, n, n_img, missing = check(doc, paper)
        flag = cov < a.min
        bad += flag
        print(f"{i:2d} {cov:6.1%} of {n:5d} text words  ({n_img:4d} words in images)  {p['id'][:50]}{'  <-- LOW' if flag else ''}")
        if a.show:
            for m in missing: print("   missing:", m[:220])
    print(f"{bad} paper(s) below {a.min:.0%}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

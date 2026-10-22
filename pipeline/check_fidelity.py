"""Check that a paper's paper.json still says what its PDF says.

Usage: python pipeline/check_fidelity.py papers/<id> [--show]

Compares the words of the PDF's text layer with the words in paper.json (prose,
headings, captions, tables, notes, references), using overlapping runs of N words
so that floats moved to a different spot do not count as changes. Maths and code
are skipped on both sides, because the PDF text layer cannot represent them.

  coverage  share of the PDF's words that appear on the site within an identical N-word run
  added     site words that are not part of any N-word run found in the PDF

Exits with status 1 if coverage drops below --min-coverage or more than
--max-added words were added, so it can run in CI on every change.
"""
import argparse, json, re, sys
from pathlib import Path
import pymupdf

WORD = re.compile(r"[a-z]{2,}")


def words(text):
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("´s", "ś")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # line-break hyphenation
    return WORD.findall(text.lower())


def pdf_words(pdf):
    out = []
    for page in pymupdf.open(pdf):
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                if not 60 < l["bbox"][1] < 740: continue  # running header / footer
                fonts = {s["font"] for s in l["spans"]}
                if any("Courier" in f or "Mono" in f or "CMTT" in f for f in fonts): continue
                out.append("".join(s["text"] for s in l["spans"]))
    return words("\n".join(out))


def site_words(paper):
    strip = lambda h: re.sub(r"<[^>]+>", " ", re.sub(r"\$\$.*?\$\$|\$[^$]*\$", " ", h or "", flags=re.S))
    parts = []
    m = paper["meta"]
    parts += [m["title"], " and ".join(a["name"] for a in m["authors"]), *m["affiliations"].values(),
              "Keywords " + ", ".join(m["keywords"]), f"Received {m['received']}; accepted {m['accepted']}",
              "Acknowledgments", "Funding", "Declaration of Conflicting Interests", "Notes", "References"]
    for b in paper["blocks"]:
        t = b["t"]
        if t == "h": parts.append(b["title"])
        elif t == "p": parts.append(strip(b["html"]))
        elif t == "list": parts += [strip(i) for i in b["items"]]
        elif t in ("figure", "table", "algo"):
            parts.append(strip(b.get("caption")))
            for row in [b.get("head", [])] + b.get("rows", []): parts.append(" ".join(row))
            parts.append(strip(b.get("note")))
            parts += [strip(c) for _, _, c in b.get("lines", [])]
    back = paper["back"]
    parts += [back["acknowledgments"], back["funding"], back["conflicts"], *back["notes"].values()]
    parts += [r["text"] for r in paper["references"]]
    return [w for w in (words(p) for p in parts if p) if w]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper_dir", type=Path)
    ap.add_argument("--min-coverage", type=float, default=0.92)
    ap.add_argument("--max-added", type=int, default=30)
    ap.add_argument("-n", type=int, default=4, help="run length in words")
    ap.add_argument("--show", action="store_true", help="print every difference")
    a = ap.parse_args()
    paper = json.loads((a.paper_dir / "paper.json").read_text())
    pw, parts = pdf_words(a.paper_dir / paper["meta"]["pdf"]), site_words(paper)
    n = a.n
    pdf_grams = {tuple(pw[i:i + n]) for i in range(len(pw) - n + 1)}
    site_grams, added, short = set(), [], []
    for part in parts:
        if len(part) < n:  # short labels (headings, table cells): must appear verbatim somewhere in the PDF
            hits = [i for i in range(len(pw) - len(part) + 1) if pw[i:i + len(part)] == part]
            if hits: short.append((hits, len(part)))
            else: added.append(" ".join(part))
            continue
        ok = [False] * len(part)
        for i in range(len(part) - n + 1):
            g = tuple(part[i:i + n]); site_grams.add(g)
            if g in pdf_grams: ok[i:i + n] = [True] * n
        run = []
        for w, good in zip(part + [""], ok + [True]):
            if not good: run.append(w)
            elif run: added.append(" ".join(run)); run = []
    covered = [False] * len(pw)
    for i in range(len(pw) - n + 1):
        if tuple(pw[i:i + n]) in site_grams: covered[i:i + n] = [True] * n
    for hits, k in short:
        for i in hits: covered[i:i + k] = [True] * k
    cov = sum(covered) / len(pw)
    n_added = sum(len(x.split()) for x in added)
    print(f"PDF words: {len(pw)}  site words: {sum(map(len, parts))}  coverage: {cov:.1%}  added on site: {n_added}")
    if a.show:
        print("\n--- on the site but not in the PDF:")
        for w in added: print("  ", w)
        print("\n--- in the PDF but not on the site (maths, code, page furniture are expected here):")
        run = []
        for w, c in zip(pw + [""], covered + [True]):
            if not c: run.append(w)
            elif run: print("  ", " ".join(run)[:200]); run = []
    ok = cov >= a.min_coverage and n_added <= a.max_added
    print("OK" if ok else "FAILED: run with --show to see the differences")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

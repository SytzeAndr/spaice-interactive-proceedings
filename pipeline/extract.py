"""Extract a paper PDF into a draft block stream + page images + figure crops.

Usage: python pipeline/extract.py papers/<id>/source.pdf papers/<id>

Writes:
  <out>/draft.json      heuristic stream of headings / paragraphs / list items (for curation)
  <out>/pages/pNN.webp  one image per page ("view original" + validation)
  <out>/figures/raw/    raster figures embedded in the PDF (convert the ones you use to webp)
The draft is a starting point: paper.json is curated from it (tables, equations,
algorithms are added by hand) and checked with pipeline/check_fidelity.py.
"""
import json, re, sys
from pathlib import Path
import pymupdf

BODY_FONTS = ("NimbusRomNo9L", "STIXMath")
ABSTRACT_FONT = "GillSans"  # page-1 abstract is set in the sans font
SUPERSCRIPT = 1


def span_html(sp):
    t = sp["text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if sp["flags"] & SUPERSCRIPT and sp["size"] < 9:
        return f"<sup>{t.strip()}</sup>"
    if "Ital" in sp["font"] and t.strip():
        return f"<em>{t}</em>"
    return t


def join_lines(lines):
    out = ""
    for ln in lines:
        if out.endswith("-") and not out.endswith("--") and ln[:1].islower():
            out = out[:-1] + ln  # de-hyphenate line breaks
        else:
            out = f"{out} {ln}" if out else ln
    out = re.sub(r"</em>(\s*)<em>", r"\1", out)
    return re.sub(r"\s+", " ", out).replace("ﬁ", "fi").replace("ﬂ", "fl").strip()


def extract(pdf, out):
    doc = pymupdf.open(pdf)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pages").mkdir(exist_ok=True)
    (out / "figures" / "raw").mkdir(parents=True, exist_ok=True)

    blocks, cur = [], None
    for pno, page in enumerate(doc, 1):
        page.get_pixmap(dpi=150).pil_save(out / "pages" / f"p{pno:02d}.webp", quality=72)
        for i, img in enumerate(page.get_images(full=True)):
            rect = page.get_image_bbox(img)
            if rect.width > 150:  # skip logos / badges
                page.get_pixmap(dpi=220, clip=rect).save(out / "figures" / "raw" / f"page{pno}_img{i}.png")

        margin = min((l["bbox"][0] for b in page.get_text("dict")["blocks"] if b["type"] == 0
                      for l in b["lines"]), default=0)
        for b in page.get_text("dict")["blocks"]:
            if b["type"]: continue
            for l in b["lines"]:
                spans = [s for s in l["spans"] if s["text"].strip() or s["text"] == " "]
                if not spans: continue
                main = max(spans, key=lambda s: len(s["text"].strip()))
                x0, y0 = l["bbox"][:2]
                text = "".join(span_html(s) for s in spans).strip()
                if y0 < 60 or y0 > 740: continue  # running header / footer
                if main["font"].startswith("GillSans-Bold") and main["size"] >= 11.5 or \
                   main["font"].startswith("GillSans-Italic") and main["size"] >= 11.5:
                    if cur and cur["type"] == "heading" and cur["page"] == pno and re.fullmatch(r"[\d.]+", re.sub("<[^>]+>", "", cur["text"])):
                        cur["text"] = re.sub("<[^>]+>", "", cur["text"] + " " + text)  # "2.1" + "Constraint Programming"
                        continue
                    cur = {"type": "heading", "text": text, "page": pno}; blocks.append(cur); continue
                is_abstract = pno == 1 and main["font"] == ABSTRACT_FONT and round(main["size"]) == 10 and x0 < 100 and 215 < y0 < 355
                if not (main["font"].startswith(BODY_FONTS) or is_abstract) or main["size"] < 9.5:
                    cur = None; continue
                if re.fullmatch(r"\(\d\)|•", text):
                    cur = {"type": "li", "marker": text, "lines": [], "page": pno}; blocks.append(cur); continue
                indented = x0 > margin + 8 and x0 < margin + 16
                if cur is None or cur["type"] == "heading" or (indented and cur["type"] == "p") or \
                   (cur["type"] == "li" and x0 < margin + 14):
                    cur = {"type": "p", "lines": [], "page": pno}; blocks.append(cur)
                cur["lines"].append(text)
    for b in blocks:
        if "lines" in b: b["text"] = join_lines(b.pop("lines"))
    (out / "draft.json").write_text(json.dumps(blocks, indent=1, ensure_ascii=False))
    print(f"{len(blocks)} blocks, {len(doc)} pages -> {out}")


if __name__ == "__main__":
    extract(sys.argv[1], Path(sys.argv[2]))

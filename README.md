# SPAICE interactive proceedings

### ▶ [Open the interactive proceedings](https://sytzeandr.github.io/spaice-interactive-proceedings/)

---

The proceedings of **SPAICE 2026**, the third Conference on AI in and for Space, rebuilt as an interactive website
that reads well on any screen. Built in response to
[too-useful-not-to-build #13](https://github.com/gomezzz/too-useful-not-to-build/issues/13).

## What is included

- **All 78 papers** (talks and posters), organised by session as in the printed proceedings, plus the foreword,
  keynotes and committees. You can search them by title, author or abstract.
- **The authors' text, unchanged.** It was extracted from the published PDF and checked automatically against it.
  Every paper links to its original pages and to the full PDF, so you can compare at any time.
- **Figures and equations** as they appear in the PDF, and you can tap them to zoom.
- **Tables** you can also open as data: sort them, chart them or download them as CSV.
- **Interactive plots** for a selection of figures. You can zoom, read values, show or hide curves, and download the data.
- **Help with difficult terms.** A shared glossary of abbreviations and technical terms, plus a short
  plain-language summary of each paper.
- **Reading tools.** Contents, search, linked citations and cross-references, dark mode, text size, and
  "cite this paper".

Anything the site adds, such as explanations, summaries and interactive versions, is marked as added. It is not part of
the peer-reviewed papers.

The site also contains a **separate example paper**: *Neuro-Symbolic Enterprise Optimization* (Andringa &
Yorke-Smith). It is **not part of the SPAICE proceedings**. It is a published paper whose first author is the
owner of this repository, and it served as the proof of concept. It shows how far a fully hand-built interactive edition
can go.

## Sources

- Proceedings: [Zenodo record 23495603](https://zenodo.org/records/23495603). A copy of the PDF is attached to this
  repository's [LTS release](https://github.com/SytzeAndr/spaice-interactive-proceedings/releases/tag/LTS).
- Each paper remains under the licence printed on it, with copyright held by its authors.

## How it works

It is a static website: HTML, CSS and JavaScript only. There is no build step, no server code and no external
services, and GitHub Pages serves it directly from the `main` branch.

The content was generated once from the PDF by the scripts in `pipeline/`. They need Python and PyMuPDF. On every
change, the **Check papers** workflow under the Actions tab re-reads the PDF and confirms that each paper's text
still matches it.

```
index.html, assets/      the website
proceedings/             the 78 papers, page images, glossary and summaries
papers/                  the separate example paper
pipeline/                extraction and checking scripts
```

## Licence

Code: MIT (see `LICENSE`). Paper content: © the respective authors, under each paper's own licence. KaTeX: MIT.

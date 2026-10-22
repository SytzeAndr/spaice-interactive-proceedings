# SPAICE interactive proceedings

Papers from the SPAICE proceedings, rebuilt as interactive web pages
([too-useful-not-to-build #13](https://github.com/gomezzz/too-useful-not-to-build/issues/13)).
This is the proof of concept with one paper: *Neuro-Symbolic Enterprise Optimization* (Andringa & Yorke-Smith, 2026).

It is a plain static site: HTML, CSS and JavaScript modules, with no build step, no server code and no
external services. GitHub Pages can serve it as-is.

## What a reader gets

- **Every figure is explorable.** Each one has an *Interactive* and an *Original* tab:
  - Figure 1: Sobol, Halton and uniform sampling, live, with a point slider, playback and an "empty cells" view.
  - Figure 2: the workflow plays step by step and links each step to its section; the component diagram is tappable.
  - Figure 3: the three activation functions, with a read-out cursor and an injectivity test.
  - Figure 4: rotatable 3D Montgomery, Halton and uniform samples, with live L2* discrepancy.
- **Tables become charts** (Tables 5–7), and every larger table can be sorted.
- **Algorithms run.** Algorithm 2 steps through line by line on real Halton points; each line of Algorithm 1 has an explanation.
- **Appendix A runs live.** It is compared with Algorithm 2, which the paper leaves as future work. Appendix B shows the
  embedded network as a diagram linked to its MiniZinc code.
- **Terms are explained.** 51 terms are underlined; tap one for a plain explanation. "In plain words" notes sit under each section.
- **Citations and cross-references.** Tap a citation for the full reference, or "Figure 3" to jump there,
  with a *Back to where you were* button.
- **The original PDF is one tap away.** "PDF page N" markers show where the PDF turns a page and open that page.
- **Reading tools.** Search, contents, dark mode, text size, and "cite this article" (APA / BibTeX).

Everything the site adds is shown in **green** and labelled as added, so it can always be told apart from the authors' text.

## Publish it with GitHub Pages (works from a phone)

1. Open the repository on github.com and go to **Settings → Pages**.
   On a phone, use the browser menu's "Desktop site" option if Settings is hidden.
2. Under **Build and deployment**, set **Source** to *Deploy from a branch*.
   Then set **Branch** to `main` with the folder `/ (root)`, and tap **Save**.
3. Wait one to two minutes. Progress shows under the **Actions** tab as "pages build and deployment".
4. The site is live at `https://<your-user-name>.github.io/<repository-name>/`. The same address is shown at the top of Settings → Pages.

The **Actions** tab also runs **Check papers** on every change. That check confirms the paper's text
still matches its PDF, that the JSON files are valid, and that the JavaScript has no syntax errors.
A green tick means all is well.

To edit something from the phone, open the file on github.com, tap the pencil icon, and commit.
Pages republishes automatically. The text of the paper lives in `papers/<id>/paper.json`, explanations in
`glossary.json`, and plain-language notes in `notes.json`.

## How it is organised

```
index.html                      the app shell (library page, or a paper with ?p=<id>)
assets/app.js                   reader: rendering, terms, citations, search, PDF viewer, settings
assets/widgets.js               the interactive figures, tables and algorithms
assets/style.css                all styling (light and dark)
assets/vendor/katex/            maths typesetting, bundled so nothing loads from a CDN
papers/index.json               list of papers on the start page
papers/<id>/source.pdf          the original paper (version of record)
papers/<id>/paper.json          structured content: blocks, tables, equations, references
papers/<id>/glossary.json       term explanations (site-authored)
papers/<id>/notes.json          plain-language notes per section (site-authored)
papers/<id>/pages/              one image per PDF page, for "PDF page N"
papers/<id>/figures/            the original figures
papers/<id>/draft.json          raw text extracted from the PDF
papers/<id>/curate.py           turns draft.json into paper.json for this paper
pipeline/extract.py             PDF → draft.json, page images, figure images
pipeline/check_fidelity.py      checks paper.json against the PDF
```

## Adding the next paper (needs a computer or a Codespace)

1. Put the PDF at `papers/<new-id>/source.pdf`. To cut one paper out of the full proceedings:
   `qpdf proceedings.pdf --pages . 45-54 -- papers/<new-id>/source.pdf`
2. Extract it: `pip install -r requirements.txt && python pipeline/extract.py papers/<new-id>/source.pdf papers/<new-id>`
3. Copy `curate.py` from the example paper and adapt it. Prose is taken verbatim from `draft.json`; equations,
   tables and algorithms are transcribed by hand. The script refuses to finish if any extracted paragraph is left unused.
4. Write `glossary.json` and `notes.json`, add the paper to `papers/index.json`, and convert the figures you use to `.webp`.
5. Run `python pipeline/check_fidelity.py papers/<new-id> --show` and review every difference it lists.
6. Interactive figures are written per figure in `assets/widgets.js` and referenced by `"widget"` in `paper.json`.
   A figure without a widget simply shows the original image.

Equations and tables are not in a PDF's text layer, so they are always transcribed and must be checked against the
original page (the **p. N** button next to each figure, table and algorithm). With the LaTeX sources, this step would
become automatic.

## Checking content fidelity

`check_fidelity.py` compares every run of four consecutive words on the site with the PDF's text layer.
For this paper, 92.8% of the PDF's words appear verbatim on the site, and only 26 site words do not occur in the PDF.
The uncovered PDF words are page furniture (running headers, the DOI box), maths and code, which the text layer can't represent.
The 26 site words come from Table 7's two-row header being flattened into one row and from text around inline maths.
Run it with `--show` to list every difference.

## Licences

Code: MIT (see `LICENSE`). The paper and its figures: © the authors, used under the paper's licence (CC BY-NC 4.0 for
the example paper), as stated on its page. KaTeX: MIT.

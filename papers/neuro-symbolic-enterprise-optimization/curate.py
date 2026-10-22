"""Curate draft.json (from pipeline/extract.py) into paper.json for this paper.

Prose comes verbatim from the PDF text layer. What the text layer cannot carry
(equations, tables, algorithms, matrices) is transcribed here by hand and
should be checked against the original page via the site's "page" buttons.

Run from the repo root:  python papers/neuro-symbolic-enterprise-optimization/curate.py
"""
import json, re
from pathlib import Path

HERE = Path(__file__).parent
draft = json.loads((HERE / "draft.json").read_text())
used = set()


def clean(html):
    html = re.sub(r"<em>(\s+)", r"\1<em>", html)
    html = re.sub(r"(\s+)</em>", r"</em>\1", html)
    html = re.sub(r"<em>([.,;:])</em>", r"\1", html)
    html = html.replace("Wi´sniewski", "Wiśniewski")
    return re.sub(r"\s+", " ", html).strip()


def take(prefix):
    """Return the draft block whose text starts with `prefix` (each used once)."""
    for i, b in enumerate(draft):
        plain = re.sub("<[^>]+>", "", b["text"])
        if i not in used and plain.startswith(prefix):
            used.add(i)
            return b
    raise KeyError(prefix)


def p(prefix, then=None, html=None, runin=None, lead="", until=None, **extra):
    """Paragraph from the draft (always consumed, so nothing is silently dropped).
    then:   prefix of a continuation block (paragraph split by a page break or float)
    html:   hand-fixed replacement when the text layer mangles inline maths
    runin:  run-in heading to strip from the start (e.g. "Results.")
    lead:   text the extractor missed at the start (line shared with a run-in heading)
    until:  keep text up to and including this marker (drops display-equation debris)"""
    b = take(prefix)
    text = b["text"]
    if then: text += " " + take(then)["text"]
    if until: text = text[: text.index(until) + len(until)]
    if runin: text = text.replace(f"<em>{runin}</em>", "", 1)
    return {"t": "p", "html": html or clean(lead + text), "page": b["page"], **extra}


def items(*prefixes, ordered=True):
    bs = [take(x) for x in prefixes]
    return {"t": "list", "ordered": ordered, "items": [clean(b["text"]) for b in bs], "page": bs[0]["page"]}


def h(num, title, page, level=None):
    level = level or num.count(".") + 1
    for i, b in enumerate(draft):  # consume the matching extracted heading, if the extractor saw it
        if b["type"] == "heading" and i not in used and b["text"].replace("&amp;", "&") == f"{num} {title}":
            used.add(i)
    return {"t": "h", "level": level, "num": num, "title": title, "page": page,
            "id": "s" + num.replace(".", "-") if num[0].isdigit() else num.lower().replace(" ", "-")}


def fig(num, page, caption, img=None, widget=None, alt=""):
    return {"t": "figure", "id": f"fig{num}", "num": num, "page": page, "caption": caption,
            "img": img, "widget": widget, "alt": alt}


def table(num, page, caption, head, rows, note=None, widget=None, bold=()):
    return {"t": "table", "id": f"tab{num}", "num": num, "page": page, "caption": caption,
            "head": head, "rows": rows, "note": note, "widget": widget, "bold": [list(b) for b in bold]}


def eq(num, tex, page):
    return {"t": "eq", "id": f"eq{num}", "num": num, "tex": tex, "page": page}


# Appendix B: rebuild the code listing from the PDF text layer.
def appendix_b():
    import pymupdf
    page = pymupdf.open(HERE / "source.pdf")[15]
    lines, cur = {}, None
    for blk in page.get_text("dict")["blocks"]:
        for l in blk.get("lines", []):
            x, y = l["bbox"][:2]
            if not 80 < y < 700: continue
            t = "".join(s["text"] for s in l["spans"]).strip()
            if x < 75 and re.fullmatch(r"\d+", t): cur = int(t); lines[cur] = []; continue
            if cur is not None: lines[cur].append(t)
    out = []
    for k in sorted(lines):
        s = " ".join(lines[k])
        s = re.sub(r"(?<![\w.])(?:[A-Za-z_\d] ){2,}[A-Za-z_\d](?!\w)", lambda m: m.group(0).replace(" ", ""), s)
        s = s.replace("−", "-").replace(". . .", "...")
        s = re.sub(r"\s+", " ", s).replace("( ", "(").replace(" )", ")").replace(" ;", ";").replace("float :", "float:")
        s = s.replace("max((", "max((").replace("+ -", "+ -")
        out.append(s.strip())
    while out and not out[-1]: out.pop()
    return out


ALG1 = """include NN
float[] buying_constraints = [c1, ..., cn]
var[] buyingStrategy = [b1, ..., bn]
var spoilage
var success
constraint forall (i in 1..n) (0 <= bi <= ci)
solve maximize (success * success_weight − spoilage * spoilage_weight)"""

ALG2 = [  # (indent, latex-or-text, comment)
    (0, r"$n \leftarrow$ number of data points to sample", ""),
    (0, r"$d \leftarrow$ number of dimensions to sample", ""),
    (0, r"$H^{sub} \leftarrow H^{d-1}_{(d-1)!\cdot n}$", r"Get the first $(d-1)!\cdot n$ points of the $d-1$ dimensional Halton Sequence"),
    (0, r"$H^m \leftarrow \emptyset$", ""),
    (0, r"$i \leftarrow 0$", ""),
    (0, r"<b>while</b> $|H^m| < n$ <b>do</b>", "While not enough points are generated"),
    (1, r"$x \leftarrow H^{sub}(i)$", r"Sample a new point of dimension $d-1$"),
    (1, r"$s \leftarrow 1 - \sum_{d_i \in d-1} x_{d_i}$", r"Store 1 minus the sum of the $d-1$ points"),
    (1, r"<b>if</b> $s \geq 0$ <b>then</b>", "Discard the point if the sum exceeds 1"),
    (2, r"$x_d \leftarrow s$", r"Set $d$-th coordinate of $x$ to the sum of the $d-1$ points"),
    (2, r"$H^m \leftarrow H^m \cup x$", ""),
    (1, r"<b>end if</b>", ""),
    (1, r"$i \leftarrow i + 1$", ""),
    (0, r"<b>end while</b>", ""),
    (0, r"<b>return</b> $H^m$", ""),
]

M3 = r"""\mathbf{M}_3 = \begin{pmatrix}
-\frac{1}{\sqrt{2}} & -\frac{1}{\sqrt{6}} & \frac{1}{\sqrt{3}} \\
\frac{1}{\sqrt{2}} & -\frac{1}{\sqrt{6}} & \frac{1}{\sqrt{3}} \\
0 & \frac{2}{\sqrt{6}} & \frac{1}{\sqrt{3}}
\end{pmatrix}"""
_r = lambda k: rf"\frac{{1}}{{\sqrt{{{k}}}}}"
M6 = r"\mathbf{M}_6 = \begin{pmatrix}" + r" \\ ".join([
    rf"-{_r(2)} & -{_r(6)} & -{_r(12)} & -{_r(20)} & -{_r(30)} & {_r(6)}",
    rf"{_r(2)} & -{_r(6)} & -{_r(12)} & -{_r(20)} & -{_r(30)} & {_r(6)}",
    rf"0 & \frac{{2}}{{\sqrt{{6}}}} & -{_r(12)} & -{_r(20)} & -{_r(30)} & {_r(6)}",
    rf"0 & 0 & \frac{{3}}{{\sqrt{{12}}}} & -{_r(20)} & -{_r(30)} & {_r(6)}",
    rf"0 & 0 & 0 & \frac{{4}}{{\sqrt{{20}}}} & -{_r(30)} & {_r(6)}",
    rf"0 & 0 & 0 & 0 & \frac{{5}}{{\sqrt{{30}}}} & {_r(6)}",
]) + r"\end{pmatrix}"

# --- paragraphs whose equations / run-in headings / inline maths need hand fixes -------------
FIX = {
    "pow2": "For this reason, in this article, we study the performance of two alternative "
        "approaches to the sigmoid activation function. The first is a quadratic variant <em>power2</em>, which replaces "
        "the $e^{-x}$ term by $x^2$:",
    "taylor1": "The second is a semi-linear variant <em>taylor1</em>, based on the first term "
        "of the Taylor approximation of the sigmoid function:",
    "montgomery": "Furthermore, instead of generating the weights for individual "
        "objectives in the composite objective uniformly at random, we consider generating these by deterministic "
        "low-discrepancy sequences. The idea is that this improves the quality of the Pareto front, as the generated CSP "
        "instances are more evenly spread in the objective space. Since the sum of the sampled weights should sum to one, "
        "this article considers Montgomery sampling (see Algorithm 2), a variant on low-discrepancy sampling. Montgomery "
        "sampling takes a $d-1$ dimensional low discrepancy sequence and maps it to a $d$-dimensional low discrepancy "
        "sequence, while preserving this summation constraint. A demonstration of its performance can be found in Figure 4.",
    "highdim": "It should be noted that Sobol and Halting sampling sequences tend to become "
        "infeasible to compute for higher dimensions (around approximately $d > 10$). This can be problematic for "
        "problems with many objectives. There are several ways to overcome this issue. Suppose $p$ is the threshold from "
        "which Montgomery sampling becomes infeasible, and we would like to sample $d > p$ dimensions. One way would be to "
        "sample the first $q$ dimensions by means of Montgomery sampling and use uniform sampling to sample the remaining "
        "$d - p$ samples. Alternatively, we could also consider modifying the algorithm to sample the $d - 1$ samples in "
        "sets $q_i \\in Q$, such that $q_i \\leq p, \\forall q_i \\in Q$ and $d - 1 = \\sum_{q_i \\in Q} q_i$. The last "
        "dimension can be added similarly to Montgomery sampling, by setting it equal to 1 minus the sum of the sampled "
        "digits. Evaluating these approaches experimentally is left as future work.",
}

# ---------------------------------------------------------------------------
blocks = [
    h("Abstract", "Abstract", 1, level=2),
    p("Simulation–optimization is often used"),

    h("1", "Introduction", 1),
    p("Managerial decisions are often"),
    p("Finding these inputs by exhaustively"),
    p("This article situates"),
    p("A mapping from problem description"),
    p("A path to model problems"),
    p("This article addresses the modeling challenge"),
    p("We argue that embedding an NN"),
    items("The DM does not know all", "The DM has a large collection", "The DM is not able to do simulation"),
    p("We argue that the proposed methodology"),
    p("A preliminary report of this work"),
    items("The use of low discrepancy sampling", "The use of various output activation",
          "The direct optimization toward", "More detailed computational experiments"),
    p("The remainder of the article"),

    h("2", "Background and Related Work", 2),
    h("2.1", "Constraint Programming (CP)", 2),
    p("CP is an expressive yet practical", then="variable from its domain"),
    table(1, 3, "Mathematical Programming Versus Constraint Programming (IBM, 2021).",
          ["Mathematical Programming", "Constraint Programming"],
          [["Typically restricted to linear and quadratic problems", "Typically discrete but also continuous problems"],
           ["Proves optimality with techniques such as a lower-bound proof provided by cuts and linear relaxation",
            "Proves optimality by showing that no better solution than the current one can be found"],
           ["Algebra as theoretical basis", "Logic as theoretical basis"],
           ["Requires that the model falls in a well-defined mathematical category",
            "Does not make assumptions on the mathematical properties of the solution space"],
           ["Is specific to a class of problems whose formulation satisfies certain mathematical properties",
            "Has no limitation on the arithmetic constraints that can be set on decision variables"]]),
    p("A common optimization methodology"),
    h("2.2", "Quasi-Monte Carlo Sampling", 3),
    p("In our preliminary work, we set weights"),
    fig(1, 3, "Demonstration of two low-discrepancy sampling methods (Sobol and Halton) as opposed to uniform sampling "
              "for 1,000 data points. The plot visualizes how both low-discrepancy sequences have less gaps and clusters.",
        img="figures/fig1.webp", widget="sampling2d",
        alt="Three scatter plots of 1,000 points (Clients_N against Distr2) sampled with Sobol, Halton and uniform sampling."),
    h("2.3", "SO & Empirical Decision Model Learning", 3),
    p("As discussed in the introduction"),
    p("The literature on SO tends to favor", then="a quick evaluation of the simulation model"),
    table(2, 4, "Black Box Optimization Versus Empirical Model Learning (Lombardi et al., 2017).",
          ["Black Box Optimization", "Empirical Model Learning"],
          [["Designed for problems without a complex combinatorial structure (discrete variables and non-trivial constraints)",
            "Tends to provide the best results for problems with a complex combinatorial structure"],
           ["Relies on performing simulation during the search process", "Simulation time has no direct impact on the solver performance"],
           ["Function that describes the system is a black box",
            "No black box assumption, allowing exploitation of its structure during the search process"]]),
    p("Instead, we adopt an empirical decision model learning"),
    h("2.4", "Closely Related Approaches", 4),
    p("Combining CP with EM is recognized"),

    h("3", "Methodology", 4),
    p("Figure 2 provides an overview"),
    fig(2, 5, "Approach summarized. A simple NN is trained on simulation data. Next, business goals and trained NNs are "
              "embedded in the CP model. By utilizing soft constraints and various weight and threshold parameters, an "
              "approximation of the Pareto front for the various objectives is formed. (a) Workflow: from simulation model "
              "to Pareto front. (b) Overview of the various components of this article and how they interact. "
              "<em>Note.</em> NN = neural network; CP = constraint programming.",
        img="figures/fig2.webp", widget="workflow",
        alt="Two diagrams: (a) a nine-step workflow from simulation model to Pareto front; (b) how enterprise, simulation, NN, CP model, problem and solution relate."),
    p("In this article, the simulation model is assumed"),
    h("3.1", "The NN", 4),
    p("The first main component is a meta-model"),
    items("NNs are able to learn behavior", "NN embeddings in optimization models",
          "Compared to other machine learning techniques", ordered=False),
    h("3.1.1", "Activation Function", 5),
    p("of activation functions exist", until="activation function:",
      lead="The activation functions also play a crucial role in NN (Dubey et al., 2021). A wide variety "),
    eq(1, r"f(x) = \frac{1}{1 + e^{-x}}.", 5),
    p("Using a convex activation function"),
    p("For this reason, in this article", html=FIX["pow2"]),
    eq(2, r"f(x) = \frac{1}{1 + x^2}.", 5),
    fig(3, 6, "The shape of three activation functions.", img="figures/fig3.webp", widget="activations",
        alt="Line plot of sigmoid, power2 and taylor1 activation functions for x from -10 to 10."),
    p("The second is a semi-linear variant", html=FIX["taylor1"]),
    eq(3, r"f(x) = \frac{1}{1 + \max(0, x)}.", 6),
    p("Figure 3 visualizes the shape"),
    h("3.2", "The Constraint Program", 6),
    p("Besides the NN, the second main component"),
    items("The current situation is", "Uncertainty is also incorporated", "The preferred situation is incorporated"),
    p("It is reasonable to believe most"),
    table(3, 7, "Concepts From the Meta-Model Presented by Bock et al. (2018) and Their CP Equivalents.",
          ["Problem Conceptualization Meta-Model", "CP Equivalent"],
          [["Factual aspect", "Constraint"], ["Goal", "Objective function"], ["Value", "Variable"],
           ["Stakeholder preference", "Soft-constraint"], ["Possible action", "Decision variable"]],
          note="<em>Note.</em> A factual aspect describes something regarded as true, that is, a constraint. A goal is a "
               "metric to improve upon that is expressed by other metrics, that is, an objective function. Multiple "
               "stakeholders can be modeled by soft constraints, which provides a foundation to model individual "
               "preferences (Schiex, 1992). An action describes something that can be undertaken, hence corresponds "
               "with a variable that can be decided upon. CP = constraint programming.", widget="conceptmap"),
    p("As noted in Section 2", sitenote="The sentence “Figure 1 shows an example CP model” most likely refers to Algorithm 1, which shows the restaurant CP model."),
    {"t": "algo", "id": "alg1", "num": 1, "page": 7, "caption": "Pseudocode for the restaurant CP model. It closely matches a MiniZinc implementation.",
     "code": ALG1, "lang": "minizinc", "widget": "restaurantcp"},
    p("Our approach embeds an NN into a CP model", then="using a limited number of basic components"),
    h("3.3", "Multi-Objective Approach", 7),
    p("So far, we have a CP declarative model"),
    p("Most methods on multi-objective decision making"),
    p("We put our focus on approaches"),
    p("For the experiments in this article, we considered"),
    {"t": "explainer", "widget": "composite", "title": "Try it: weighted composite objectives",
     "after": "s3-3"},
    p("For problems that need to preserve", fn=True),
    p("Furthermore, instead of generating the weights", html=FIX["montgomery"]),
    fig(4, 8, "3D plots to show the effects of Montgomery sampling compared to uniformly sampling and a normalized Halton "
              "sampling. 32 three-dimensional data points were generated. The two normalized variants were implemented by "
              "first generating the points according to their underlying sequence, and then for each point, dividing each "
              "of its value by the sum of its values such that the summation constraint was satisfied. Montgomery sampling "
              "tends to outperform the other two in terms of L2* discrepancy (Zhou et al., 2013). Visually, this can also "
              "be observed, as the triangle-shaped solution space is more easily noticeable for Montgomery sampling than for "
              "the other two methods. (a) Normalized Halton L2* discrepancy = 0.135. (b) Normalized Uniform L2* "
              "discrepancy = 0.155. (c) Montgomery L2* discrepancy = 0.119.",
        img="figures/fig4.webp", widget="montgomery3d",
        alt="Three 3D scatter plots of 32 points on the triangle x+y+z=1: normalized Halton, normalized uniform, Montgomery."),
    {"t": "algo", "id": "alg2", "num": 2, "page": 8, "caption": "Montgomery sampling.", "lines": ALG2, "widget": "montgomerystep"},
    p("It should be noted that Sobol and Halting", html=FIX["highdim"]),

    h("4", "Experimental Validation", 9),
    table(4, 9, "Performance Indicators.", ["Metric", "Assessment", "Description"],
          [["MSE", "NN accuracy", "Mean squared difference between approximated output and real output on a test set"],
           ["Runtime", "Performance", "Average time for solving one CSP instance"],
           ["Front occupation", "Solution quality", "Amount of Pareto optimal solutions found"],
           ["Front spread", "Solution diversity", "Maximum distance between any two points in the set of solutions"]],
          note="<em>Note.</em> More details on the multi-objective metrics can be found in Audet et al. (2021). "
               "MSE = mean squared error; NN = neural network; CSP = constraint satisfaction problem.", widget="frontmetrics"),
    p("This section assesses the approach"),
    p("Two further experiments"),
    p("The Food Wars domain is more relevant"),
    h("4.1", "Restaurant—Problem Description", 9),
    p("As stated, Experiments 1 and 2"),
    p("The original problem has two objectives"),
    h("4.2", "Experiment 1: CSP Weight Sampling", 9),
    p("The purpose of this experiment is to assess"),
    p("As opposed to uniform sampling"),
    table(5, 10, "Experiment 1: Performance Indicators of Various Weight Sampling Methods.",
          ["Sampler", "Objectives", "Repetitions", "FO", "FS", "Runtime", "Repetitions"],
          [[s, o, r, fo, fs, rt, r] for s, o, r, fo, fs, rt in [
              ("Uniform", "2", "10", "4.6", "0.19", "1.2 ± 0.51"), ("Montgomery–Sobol", "2", "5", "6", "0.25", "1.1 ± 0.52"),
              ("Montgomery–Halton", "2", "5", "5", "0.25", "1.1 ± 0.54"), ("Uniform", "3", "13", "4.5", "0.75", "1.3 ± 0.81"),
              ("Montgomery–Sobol", "3", "4", "7", "0.77", "1.2 ± 0.81"), ("Montgomery–Halton", "3", "4", "6", "0.75", "1.4 ± 0.98"),
              ("Uniform", "4", "13", "5.9", "0.47", "2.5 ± 2.7"), ("Montgomery–Sobol", "4", "4", "9", "0.86", "3.3 ± 4.3"),
              ("Montgomery–Halton", "4", "4", "9.8", "0.86", "3.8 ± 4.1"), ("Uniform", "5", "12", "13", "0.56", "2.4 ± 1.4"),
              ("Montgomery–Sobol", "5", "3", "17", "1.3", "2.1 ± 1.4"), ("Montgomery–Halton", "5", "3", "17", "1.27", "2.5 ± 1.8"),
              ("Uniform", "6", "10", "6.7", "1.09", "3.2 ± 2.2"), ("Montgomery–Sobol", "6", "5", "7.8", "1.3", "2.6 ± 2.0"),
              ("Montgomery–Halton", "6", "5", "7", "1.2", "2.7 ± 2.1")]],
          note="<em>Note.</em> The best performing method is shown in bold. The experiment was repeated additionally for the "
               "uniform sampling to compensate for the random nature.FO = front occupation; FS = front spread.",
          widget="table5chart"),
    table(6, 10, "Experiment 2: Performance of Three Activation Functions.",
          ["Repetitions", "Solver", "Architecture", "Hidden Layers", "Layer Width", "Runtime", "MSE", "FO", "FS"],
          [r.split() for r in [
              "25 Gurobi Pow2 2 5 0.55 0.0033 4.2 0.12", "6 Gurobi Taylor1 3 7 1.0 0.0014 5 0.18",
              "11 Gurobi Taylor1 2 10 1.3 0.00080 5.2 0.25", "14 Gurobi Pow2 2 7 1.6 0.0016 5.8 0.26",
              "9 Gurobi Taylor1 2 12 4.5 0.00071 5.6 0.22", "13 Gurobi Pow2 2 10 6.8 0.00071 7.8 0.27",
              "12 JaCoP Sigmoid 2 5 53 0.0026 5 0.077", "8 JaCoP Pow2 2 5 99 0.0031 4.1 0.09",
              "13 JaCoP Sigmoid 2 7 116 0.0012 7.5 0.16", "8 JaCoP Pow2 2 7 183 0.002 4.8 0.17"]],
          note="<em>Note.</em> Here, we trained on 2,000 uniformly generated samples. MSE = mean squared error; "
               "FO = front occupation; FS = front spread.",
          widget="table6chart", bold=[(3, 2), (3, 5), (3, 7), (3, 8), (4, 2), (4, 5), (4, 6)]),
    h("4.3", "Experiment 2: Activation Function", 10),
    p("The purpose of this experiment is study"),
    p("Table 6 provides the results"),
    p("Second, if we consider networks"),
    p("Third, Taylor1 is significantly faster"),
    p("Lastly, Table 6 shows"),
    table(7, 11, "Six Nondominating Solutions Found for the Food Wars Experiment.",
          ["Collaboration Bonus", "Max Age", "Strength CP", "Strength SIM", "Mortality Rate CP", "Mortality Rate SIM",
           "Proactive Aggression CP", "Proactive Aggression SIM"],
          [r.split("|") for r in [
              "3.183|271|0.4009|0.4 ± 0.03|0.229|0.21 ± 0.01|0.4965|0.51 ± 0.02",
              "3.184|270|0.4010|0.4 ± 0.02|0.229|0.21 ± 0.01|0.4967|0.48 ± 0.03",
              "3.712|215|0.4030|0.4 ± 0.02|0.237|0.21 ± 0.02|0.5006|0.5 ± 0.03",
              "4.871|158|0.4072|0.44 ± 0.05|0.226|0.24 ± 0.03|0.5096|0.51 ± 0.03",
              "4.955|118|0.4396|0.43 ± 0.02|0.270|0.23 ± 0.08|0.5165|0.51 ± 0.07",
              "4.988|117|0.4401|0.42 ± 0.06|0.268|0.22 ± 0.05|0.5168|0.49 ± 0.06"]],
          note="<em>Note.</em> Initially, 30 instances were generated, each based on a different set of weights. These were "
               "solved by constraint programming (CP), of which a set of six nondominating solutions could be constructed. "
               "Next, these solutions were sent to the simulation (SIM) to get the actual values. According to the SIM "
               "values, these 13 solutions form a nondominating set. Both NNs were trained for 10 min on 5,000 samples. The "
               "NN to predict the output variables had two hidden layers of 20 nodes each. The NN to predict the average "
               "population had two hidden layers of 15 nodes each. <em>p</em> was set at 100.",
          widget="table7chart"),
    h("4.4", "Experiment 3: Food Wars", 11),
    p("The purpose of Experiment 3"),
    h("4.4.1", "Food Wars—Problem Description", 11),
    p("Food Wars—Problem Description.", runin="Food Wars—Problem Description."),
    p("One can take action in two dimensions"),
    p("The peacefulness of the population"),
    p("Additionally, it is essential"),
    p("Summarized, we are interested"),
    h("4.4.2", "Results", 11),
    p("Results.", runin="Results."),
    p("Although the outputs tend not to differ"),
    p("Furthermore, trivial examples"),
    h("4.5", "Discussion", 12),
    p("The experiments reported have offered"),
    items("Using low-discrepancy sampling", "Deeper and wider networks", "Discarding quadratic terms",
          "The approach can be applied", ordered=False),

    h("5", "Conclusion and Future Work", 12),
    p("For enterprise SO, this article"),
    p("We demonstrated the performance sensitivity"),
    p("The experiments demonstrated how Montgomery"),
    p("In a highly complex real-world scenario"),
    p("Furthermore, in this article, we showed"),
    p("Building on the approach of this article"),
]

for b in blocks:  # footnote marker -> link
    if b.pop("fn", False) is True:
        b["html"] = b["html"].replace("<sup>1</sup>", '<sup class="fn" data-fn="1">1</sup>')

# --- Appendices ------------------------------------------------------------
blocks += [
    {**h("A", "Improved Montgomery Sampling Algorithm", 14, level=1), "id": "appA", "fn": "2"},
    {"t": "list", "ordered": True, "page": 14, "items": [
        r"Generate many points from the Halton sequence, that is, $\{\mathbf{h}_j\}, j = 1 \ldots n$, in $\mathbb{R}^{d-1}$; "
        r"embed them into $\mathbb{R}^d$ by setting their last coordinate to 0.",
        r"Let $\{e_i\}$ denote the standard basis for $\mathbb{R}^n$. Construct a $d \times d$ matrix $\mathbf{M}_d$ as follows:"
        r"<ul><li>The rightmost column should be $1/\sqrt{d}$.</li><li>In all other columns:<ul class='star'>"
        r"<li>The primary subdiagonal entry in column $k$ should be $k/\sqrt{2s_k}$, where $s_k := \sum_{j=1}^{k} j$ is the $k$th triangular number.</li>"
        r"<li>All entries above the primary subdiagonal should be $-1/\sqrt{2s_i}$.</li>"
        r"<li>All entries below the primary subdiagonal should be 0.</li></ul></li></ul>"
        r"<p>Some examples:</p>$$d = 3: \quad " + M3 + r",$$$$d = 6: \quad " + M6 + r".$$"
        r"<p>We can show, for example, by induction, that the columns of $\mathbf{M}_d$ form an orthonormal basis of $\mathbb{R}^d$.</p>",
        r"Transform the Halton sequence $\{\mathbf{h}_j\}$ by $T(\mathbf{h}_j) = \sqrt{2}\mathbf{M}_d\mathbf{h}_j + \mathbf{e}_1$, where "
        r"$\mathbf{e}_1$ is the first vector in the standard basis for $\mathbb{R}^d$ (i.e., has a 1 in the first coordinate and 0 for all others)."
        r"<ul><li>The logic behind this is that the rotation matrix $\mathbf{M}_d$ maps the subspace $\mathbb{R}^{d-1} \times \{\mathbf{0}\}$ "
        r"(i.e., the subspace containing the generated Halton set) onto the space orthogonal to $\mathbf{1}$, that is, the subspace for "
        r"which the sum of the coordinates is 0. This mapping does not distort distances.</li>"
        r"<li>The $\sqrt{2}$ term is to ensure that the mapping $[0, 1]^{d-1} \times \{\mathbf{0}\} \to S$ is surjective, since "
        r"$T(\mathbf{e}_1) = (0, 1, 0, \ldots)$.</li></ul>",
        r"Many of the points transformed will not have all coordinates in $[0, 1]$ as desired; discard those that do not. Roughly "
        r"$1/d!$ of the terms in $\{\mathbf{j}_j\}$ will correctly map to $S$. So if we would like $n$ points on $S$, that would require "
        r"about $n \cdot d!$ points generated on $[0, 1]^{d-1}$."]},
    {"t": "explainer", "widget": "appendixA", "title": "Try it: the improved algorithm, running live"},
    {**h("B", "NN Embedding in MiniZinc, Supply Chain Experiment", 16, level=1), "id": "appB"},
    {"t": "code", "id": "appBcode", "page": 16, "lang": "minizinc", "lines": appendix_b(), "widget": "nnembed"},
]
for pre in ["Algorithm 1.", "Algorithm 2.", "Appendix A", "Appendix B", "Neuro-Symbolic", "Optimization",
            "Sytze", "and Neil", "Generate many points", "Let {", "The rightmost", "In all other",
            "Transform the Halton", "The logic behind", "The √", "Many of the points", "We can show", "Results.",
            "Food Wars—Problem Description."]:
    for i, d in enumerate(draft):
        if re.sub("<[^>]+>", "", d["text"]).lstrip().startswith(pre): used.add(i)

# Everything left over must be equation / algorithm / matrix debris; list it so nothing is silently lost.
left = [(i, d["text"][:60]) for i, d in enumerate(draft) if i not in used]
junk = re.compile(r"^[\s−\-–⎛⎜⎝⎞⎟⎠,.=0-9<>/a-z\"]*$|^(<em>)?[nidxHs⊳]|^end while|^return|^<em>⊳|^while|^⎞")
unexpected = [x for x in left if not junk.search(x[1])]
assert not unexpected, f"unconsumed prose blocks: {unexpected}"

# --- References (hanging indent in the PDF) ----------------------------------
def references():
    import pymupdf
    doc = pymupdf.open(HERE / "source.pdf")
    refs, cur = [], None
    for pno, margin, y0, y1 in [(12, 62.4, 240, 760), (13, 49.6, 60, 590)]:
        for blk in doc[pno].get_text("dict")["blocks"]:
            for l in blk.get("lines", []):
                x, y = l["bbox"][:2]
                if not y0 < y < y1: continue
                t = "".join(s["text"] for s in l["spans"])
                if x < margin + 3:
                    if t.strip() == "References": continue
                    cur = [t]; refs.append(cur)
                elif cur is not None:
                    cur.append(t)
    out = []
    for parts in refs:
        txt = ""
        for t in parts:
            t = t.strip()
            if txt.endswith("-") and t[:1].islower(): txt = txt[:-1] + t
            elif txt.endswith(("/", "–")): txt += t
            else: txt = f"{txt} {t}" if txt else t
        txt = re.sub(r"\s+", " ", txt).replace("ﬁ", "fi").replace("ﬂ", "fl").replace("Wi´sniewski", "Wiśniewski").replace("Lig˛eza", "Ligęza")
        m = re.match(r"(.+?) \((\d{4})\)", txt)
        doi = re.search(r"https?://\S+", txt)
        first = re.split(r",|\s&|\s\(", txt)[0].strip()
        names = re.findall(r"([A-Z][^,&()]*?), (?:[A-Z]\.[\s-]?)+", m.group(1)) if m else []
        names = [n.strip() for n in names] or [m.group(1).strip() if m else first]
        cite = names[0] if len(names) == 1 else f"{names[0]} and {names[1]}" if len(names) == 2 else f"{names[0]} et al."
        out.append({"id": f"ref{len(out) + 1}", "cite": cite, "text": txt, "first": first, "year": m.group(2) if m else "",
                    "url": doi.group(0).rstrip(".") if doi else None})
    return out


meta = {
    "id": "neuro-symbolic-enterprise-optimization",
    "title": "Neuro-Symbolic Enterprise Optimization",
    "authors": [
        {"name": "Sytze P. E. Andringa", "orcid": "0000-0003-4061-7104", "affil": 1},
        {"name": "Neil Yorke-Smith", "orcid": "0000-0002-1814-3515", "affil": 1, "corresponding": True}],
    "affiliations": {"1": "STAR Lab, Delft University of Technology, Delft, The Netherlands"},
    "journal": "The European Journal on Artificial Intelligence", "articleType": "Research Article",
    "year": 2026, "pages": "1–16", "doi": "10.1177/30504554261422145",
    "license": "CC BY-NC 4.0", "licenseUrl": "https://creativecommons.org/licenses/by-nc/4.0/",
    "received": "August 11, 2023", "accepted": "January 23, 2026",
    "keywords": ["enterprise simulation", "constraint programming", "deep learning", "simulation–optimization"],
    "code": "https://www.doi.org/doi/10.4121/26776b70-225b-4091-ace3-e57324d0eaf1",
    "pdf": "source.pdf", "pageCount": 16,
}
back = {
    "acknowledgments": "Thanks to the anonymous reviewers. The authors thank Aaron M. Montgomery for his help designing "
                       "the weight sampling method and Marco Loog for his input on activation functions.",
    "funding": "The authors disclosed receipt of the following financial support for the research, authorship, and/or "
               "publication of this article: This research was partially supported by TAILOR, a project funded by the EU "
               "Horizon 2020 research and innovation programme under grant number 952215.",
    "conflicts": "The authors declared no potential conflicts of interest with respect to the research, authorship, and/or "
                 "publication of this article.",
    "notes": {"1": "We did some minor experimenting to assess performance. We did not notice any noteworthy performance "
                   "impact when considering equal problem and NN complexity. Hence, in terms of performance, there is no "
                   "clear winner between the possibilistic and weighted composite model.",
              "2": "Algorithm design by Aaron M. Montgomery."},
}
from PIL import Image  # record image sizes so the browser can reserve space (no layout jumps)
for b in blocks:
    if b.get("img"): b["imgSize"] = list(Image.open(HERE / b["img"]).size)
paper = {"meta": meta, "blocks": blocks, "back": back, "references": references()}
(HERE / "paper.json").write_text(json.dumps(paper, indent=1, ensure_ascii=False))
print(f"paper.json: {len(blocks)} blocks, {len(paper['references'])} references; skipped debris: {len(left)}")

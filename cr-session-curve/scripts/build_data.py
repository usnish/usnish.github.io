"""Published inputs and headline numbers for "Same Curve, Two Worlds".

Step 1 (always): writes data/published.json, every published number the page and
the simulation use, with study, contrast, metric, window, DOI and location. Each
number is checked against the source text (PubMed abstracts, the Hammill full
text from PMC, the Cochrane review PDF, the CMS decision memo); the script stops
if a quoted string is missing. Downloads are cached in _viz/cache/ (not published).

Step 2 (when data/grid.json exists, i.e. after scripts/sim.py has run): writes
data/summary.json with the headline numbers the page quotes.

Order:  python3 cr-session-curve/scripts/build_data.py      (published.json)
        uv run --with numpy --with scipy python3 cr-session-curve/scripts/sim.py
        python3 cr-session-curve/scripts/build_data.py      (summary.json)
Stdlib only. Pass --offline to skip the source checks.
"""
import hashlib
import html
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = HERE.parent / "data"
CACHE = ROOT / "_viz" / "cache"   # same git-ignored cache as _viz/vizlib.py (which needs numpy, so not imported)
UA = {"User-Agent": "usnish.github.io data viz build (contact via github.com/usnish)"}


def fetch(url, name):
    """Download url into the cache once and return the local path."""
    import urllib.request
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.exists():
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
            path.write_bytes(r.read())
    return path

PUBMED = "https://pubmed.ncbi.nlm.nih.gov/"
DOI = "https://doi.org/"

# ------------------------------------------------------------------ published estimates
# metric: HR / RR / OR / risk / RD (risk difference, percentage points)
EST = [
    # Hammill 2010: the observational dose-response curve
    dict(id="hammill_adj_1", study="Hammill 2010", group="hammill", contrast="36 vs 1 session", k=1,
         est=0.53, lo=0.48, hi=0.59, metric="HR", adjusted=True,
         window="4 years from first session", design="Observational, Medicare 5% sample, attenders only",
         n=30161, doi="10.1161/CIRCULATIONAHA.109.876383", where="Abstract",
         check=["0.53; 95% CI, 0.48–0.59"],
         note="Table 2 of the author manuscript prints the CI as 0.47–0.59; the abstract's 0.48–0.59 is used."),
    dict(id="hammill_adj_12", study="Hammill 2010", group="hammill", contrast="36 vs 12 sessions", k=12,
         est=0.78, lo=0.71, hi=0.87, metric="HR", adjusted=True, window="4 years from first session",
         design="Observational", n=30161, doi="10.1161/CIRCULATIONAHA.109.876383", where="Abstract",
         check=["0.78; 95% CI, 0.71–0.87"],
         note="Table 2 of the author manuscript prints the CI as 0.71–0.86; the abstract's 0.71–0.87 is used."),
    dict(id="hammill_adj_24", study="Hammill 2010", group="hammill", contrast="36 vs 24 sessions", k=24,
         est=0.86, lo=0.77, hi=0.97, metric="HR", adjusted=True, window="4 years from first session",
         design="Observational", n=30161, doi="10.1161/CIRCULATIONAHA.109.876383", where="Abstract; Table 2",
         check=["0.86; 95% confidence interval [CI], 0.77–0.97", "0.86 (0.77–0.97)"]),
    dict(id="hammill_unadj_1", study="Hammill 2010", group="hammill", contrast="36 vs 1 session", k=1,
         est=0.42, lo=0.38, hi=0.47, metric="HR", adjusted=False, window="4 years from first session",
         design="Observational", n=30161, doi="10.1161/CIRCULATIONAHA.109.876383", where="Results, unadjusted model",
         check=["0.42; 95% CI, 0.38–0.47"]),
    dict(id="hammill_unadj_12", study="Hammill 2010", group="hammill", contrast="36 vs 12 sessions", k=12,
         est=0.71, lo=0.64, hi=0.78, metric="HR", adjusted=False, window="4 years from first session",
         design="Observational", n=30161, doi="10.1161/CIRCULATIONAHA.109.876383", where="Results, unadjusted model",
         check=["0.71; 95% CI, 0.64–0.78"]),
    dict(id="hammill_unadj_24", study="Hammill 2010", group="hammill", contrast="36 vs 24 sessions", k=24,
         est=0.82, lo=0.73, hi=0.92, metric="HR", adjusted=False, window="4 years from first session",
         design="Observational", n=30161, doi="10.1161/CIRCULATIONAHA.109.876383", where="Results, unadjusted model",
         check=["0.82; 95% CI, 0.73–0.92"]),

    # Cochrane 2021 (Dibben et al.): randomized trials, program vs no program
    *[dict(id=f"cochrane_{o}_{w}", study="Cochrane 2021", group="cochrane", outcome=lab, window=win,
           contrast="Exercise-based CR vs usual care", est=e, lo=l, hi=h, metric="RR", adjusted=False,
           design="Meta-analysis of randomized trials (intention to treat)", trials=nt,
           doi="10.1002/14651858.CD001800.pub4", url="https://eprints.gla.ac.uk/258451/1/258451.pdf",
           where="Abstract, Main results", check=[chk])
      for o, lab, w, win, e, l, h, nt, chk in [
          ("acm", "All-cause mortality", "short", "6 to 12 months", 0.87, 0.73, 1.04, 25, "RR) 0.87, 95% confidence interval (CI) 0.73 to 1.04; 25 trials"),
          ("acm", "All-cause mortality", "medium", "over 12 to 36 months", 0.90, 0.80, 1.02, 15, "RR 0.90, 95% CI 0.80 to 1.02; 15 trials"),
          ("acm", "All-cause mortality", "long", "over 36 months", 0.91, 0.75, 1.10, None, "RR 0.91, 95% CI 0.75 to 1.10"),
          ("cvm", "Cardiovascular mortality", "short", "6 to 12 months", 0.88, 0.68, 1.14, 15, "RR 0.88, 95% CI 0.68 to 1.14; 15 trials"),
          ("cvm", "Cardiovascular mortality", "medium", "over 12 to 36 months", 0.77, 0.63, 0.93, 5, "RR 0.77, 95% CI 0.63 to 0.93; 5 trials"),
          ("cvm", "Cardiovascular mortality", "long", "over 36 months", 0.58, 0.43, 0.78, 8, "RR 0.58, 95% CI 0.43 to 0.78; 8 trials"),
          ("mi", "Myocardial infarction", "short", "6 to 12 months", 0.72, 0.55, 0.93, 22, "RR 0.72, 95% CI 0.55 to 0.93; 22 trials"),
          ("mi", "Myocardial infarction", "medium", "over 12 to 36 months", 1.07, 0.91, 1.27, 12, "RR 1.07, 95% CI 0.91 to 1.27; 12 trials"),
          ("mi", "Myocardial infarction", "long", "over 36 months", 0.67, 0.50, 0.90, 10, "RR 0.67, 95% CI 0.50 to 0.90; 10 trials"),
          ("hosp", "All-cause hospitalization", "short", "6 to 12 months", 0.58, 0.43, 0.77, 14, "RR 0.58, 95% CI 0.43 to 0.77; 14 trials"),
          ("hosp", "All-cause hospitalization", "medium", "over 12 to 36 months", 0.92, 0.82, 1.03, 9, "RR 0.92, 95% CI 0.82 to 1.03; 9 trials"),
      ]],

    # Healthy-adherer evidence from drug trials (different metrics; never on one axis with the above)
    dict(id="cdp_placebo", study="Coronary Drug Project 1980", group="adherer",
         contrast="Placebo arm: good adherers (took 80% or more) vs poor adherers",
         est=round(15.1 / 28.3, 3), lo=None, hi=None, metric="risk ratio (crude, computed here)", adjusted=False,
         risk_good=15.1, risk_poor=28.3, window="5 years", design="Randomized trial, placebo arm, men after MI",
         drug="clofibrate", drug_risk=20.0, placebo_risk=20.9, drug_p=0.55,
         doi="10.1056/NEJM198010303031804", pmid=6999345, where="Abstract",
         check=["15.1 per cent mortality for good adherers and 28.3 per cent for poor adherers",
                "treated with clofibrate was 20.0 per cent, as compared with 20.9 per cent in 2789 men given placebo (P = 0.55)"],
         note="Ratio computed here from the two crude 5-year mortality figures; no CI reported in the abstract."),
    dict(id="murray_hernan_2016", study="Murray & Hernán 2016", group="adherer",
         contrast="CDP placebo arm: 5-year mortality difference, non-adherers minus adherers",
         est=2.5, lo=-2.1, hi=7.0, start=9.4, metric="RD (percentage points)", adjusted=True,
         window="5 years", design="Reanalysis of the CDP placebo arm, adjusted for pre- and post-randomization covariates",
         doi="10.1177/1740774516634335", pmid=26951361, where="Abstract",
         check=["placebo arm of 9.4 percentage points", "reduced to 2.5 (95% confidence interval: -2.1 to 7.0)"],
         quote_start="The original Coronary Drug Project analysis reported a difference in 5-year mortality between adherers and non-adherers in the placebo arm of 9.4 percentage points.",
         quote_end="Using modern approaches, we found that this difference was reduced to 2.5 (95% confidence interval: -2.1 to 7.0).",
         start_label="1980 CDP analysis, adjusted for 40 baseline characteristics",
         start_risks=dict(nonadherers=25.8, adherers=16.4, where="Murray & Hernán 2016, Table 1 (PMC4942353)"),
         check_mh_pmc=["After adjustment for 40 baseline characteristics",
                       "28.2 (25.3-31.1) 15.1 (13.5-16.7) 25.8 (22.9-28.7) 16.4 (14.8-18.0)"],
         note="9.4 is the 1980 CDP difference after adjusting for 40 baseline characteristics (25.8% vs 16.4%, Murray & Hernán Table 1); the crude difference was 13.2 points (28.3% vs 15.1%)."),
    dict(id="murray_hernan_2018", study="Murray & Hernán 2018", group="adherer",
         contrast="CDP placebo arm, inverse-probability weighted hazards models: 5-year risk difference range",
         est=None, range_lo=-0.7, range_hi=4.5, ci_examples=[[-12.2, 10.7], [-6.3, 15.3]],
         metric="RD (percentage points)", adjusted=True, window="5 years",
         design="Reanalysis", doi="10.1186/s13063-018-2519-5", pmid=29506561, where="Abstract",
         note="-0.7 to 4.5 is the range of point estimates across models, not a confidence interval; "
              "the CIs of those two estimates are -12.2 to 10.7 and -6.3 to 15.3.",
         check=["ranging from - 0.7 (95% confidence intervals (CI), - 12.2, 10.7) to 4.5 (95% CI, - 6.3, 15.3)"]),
    dict(id="simpson_placebo", study="Simpson 2006", group="adherer",
         contrast="Good vs poor adherence to placebo, mortality", est=0.56, lo=0.43, hi=0.74, metric="OR",
         adjusted=False, window="Varies by trial",
         design="Meta-analysis of observational adherence analyses; placebo subgroup from 8 studies",
         n=19633, n_note="19,633 = all participants in the 8 studies with placebo arms", studies_placebo=8,
         doi="10.1136/bmj.38875.675486.55", pmid=16790458, where="Abstract",
         check=["Good adherence to placebo was associated with lower mortality (0.56, 0.43 to 0.74)",
                "eight studies with placebo arms (19,633 participants)", "Meta-analysis of observational studies"]),
    dict(id="abell_total", study="Abell 2017", group="counter",
         contrast="Trials reporting high vs lower exercise adherence: total mortality", est=0.81, p=0.042,
         metric="ratio of risk ratios (meta-regression)", adjusted=False, window="Varies by trial",
         design="Between-trial meta-regression, 69 randomized trials", doi="10.1186/s40798-017-0086-z",
         pmid=28477308, where="Abstract", check=["total (RR 0.81, p = 0.042)"]),
    dict(id="abell_cv", study="Abell 2017", group="counter",
         contrast="Trials reporting high vs lower exercise adherence: cardiovascular mortality", est=0.72, p=0.045,
         metric="ratio of risk ratios (meta-regression)", adjusted=False, window="Varies by trial",
         design="Between-trial meta-regression", doi="10.1186/s40798-017-0086-z", pmid=28477308, where="Abstract",
         check=["cardiovascular mortality (RR 0.72, p = 0.045)"]),
    dict(id="pio_2017", study="Santiago de Araújo Pio 2017", group="counter",
         contrast="Prescribed CR dose, medium (12-35 sessions) and high (36+) vs low (<12): all-cause mortality",
         coef_medium=-0.80, se_medium=0.21, coef_high=-0.77, se_high=0.22, p="<.001",
         coef_pci_high_vs_lower=-0.73, metric="meta-regression coefficient vs low dose", adjusted=False,
         window="Varies by trial", trials=33,
         design="Systematic review and between-trial meta-regression of 33 trials of CR vs usual care, by prescribed dose",
         doi="10.1016/j.mayocp.2017.07.019", pmid=29101934, where="Abstract",
         note="No dose-response association for cardiovascular mortality, all-cause hospitalization, CABG or MI; "
              "36+ sessions was associated with fewer PCIs than lower doses.",
         check=["high: -0.77; SE, 0.22; P<.001; medium: -0.80; SE, 0.21",
                "33 trials were included comparing CR to usual care",
                "No dose-response association was found for cardiovascular mortality, all-cause hospitalization, coronary artery bypass graft surgery, or myocardial infarction",
                "high vs medium/low: -0.73; SE, 0.20; P<.001"]),

    # Named in text only: replications that share the same design
    dict(id="doll_2015", study="Doll 2015", group="replication", contrast="Per 5 more sessions, death",
         est=0.87, lo=0.83, hi=0.92, metric="HR", adjusted=True, window="1 year",
         design="Observational, ACTION Registry-GWTG linked to Medicare, 11,862 patients after MI",
         doi="10.1016/j.ahj.2015.08.001", pmid=26542492, where="Abstract",
         check=["adjusted hazard ratio [HR] 0.87, 95% CI 0.83-0.92"]),
    dict(id="medina_2021", study="Medina-Inojosa 2021", group="replication", contrast="Per additional session, MACE",
         est=0.98, lo=0.97, hi=0.99, metric="HR", adjusted=True, window="Mean 6 years",
         design="Observational, single center, 2,345 patients", doi="10.1161/JAHA.120.021356", pmid=34612055,
         where="Abstract", check=["fully adjusted hazard ratio, 0.98 [95% CI, 0.97-0.99]"]),
    dict(id="husaini_2023", study="Husaini 2023", group="replication", contrast="Intensive CR vs traditional CR, all-cause mortality",
         est=0.88, lo=0.78, hi=0.99, metric="HR", adjusted=True, window="Median 2.4 years",
         design="Observational, Medicare FFS, propensity matched; reports a dose-response by days attended",
         doi="10.1161/CIRCOUTCOMES.123.010131", pmid=38037867, where="Abstract",
         check=["0.88 [95% CI, 0.78-0.99]"]),
]

QUOTES = [
    dict(id="cms_2006", source="CMS decision memo for cardiac rehabilitation programs (CAG-00089R), March 22, 2006",
         url="https://www.cms.gov/medicare-coverage-database/view/ncacal-decision-memo.aspx?NCAId=164&proposed=N",
         text="These limits are well-established by the literature and represent how the majority of clinical trials were conducted.",
         context="Said of 36 sessions within 18 weeks, extendable to 72 within 36 weeks.",
         sessions=36, weeks=18, max_sessions=72, max_weeks=36, year=2006),
    dict(id="cms_2006_b", source="CMS decision memo (CAG-00089R), 2006",
         url="https://www.cms.gov/medicare-coverage-database/view/ncacal-decision-memo.aspx?NCAId=164&proposed=N",
         text="Although the evidence is inconsistent, the majority of evidence reviewed in the technology assessments included studies allowing 36 cardiac rehabilitation sessions."),
    dict(id="cochrane_dose", source="Cochrane 2021 (Dibben et al.), abstract",
         url="https://eprints.gla.ac.uk/258451/1/258451.pdf",
         text="Meta-regression showed benefits in outcomes were independent of CHD case mix, type of CR, exercise dose, follow-up length, publication year, CR setting, study location, sample size or risk of bias.",
         context="Exercise dose in the meta-regression = weeks of training x sessions per week x minutes per session, as prescribed by each trial."),
    dict(id="hammill_proxy", source="Hammill 2010, Discussion",
         url="https://pmc.ncbi.nlm.nih.gov/articles/PMC2829871/",
         text="Adherence to early cardiac rehabilitation may be a proxy for other factors, such as a patient’s general activity level, long-term exercise adherence, medication adherence, socioeconomic characteristics, and smoking status,"),
]

# Cochrane 2021 trial populations (abstract)
COCHRANE_POP = dict(trials=85, participants=23430, mean_age_range="47 to 77", women_share="under 15%",
                    median_followup_months=12,
                    check=["This review included 85 trials which randomised 23,430 people with CHD",
                           "mean age ranging from 47 to 77 years", "small percentage of participants recruited overall ( < 15%)",
                           "The median longest follow-up time was 12 months"])

# Hammill 2010 cohort facts used to calibrate the simulation
HAMMILL = dict(
    doi="10.1161/CIRCULATIONAHA.109.876383", pmcid="PMC2829871",
    n=30161, mean_age=74, years="2000-2005",
    sessions=dict(median=25, q1=13, q3=34, pct_36=0.18, pct_under6=0.13, pct_30plus="more than 40%",
                  capped_over36=1225, where="Results; Figure 1"),
    hospitalized_36wk=8560, resumed_after_hosp=2676, resumed_pct=0.31,
    mortality_36wk=0.020, deaths_36wk=605,
    r2_sessions=0.05, hosp_hr_death=2.68,
    spline_knots=[10, 16, 22, 28], followup_years=4,
    check=["The median number of sessions was 25 (interquartile range, 13–34)",
           "More than 40% of the patients attended at least 30 sessions, and 13% attended fewer than 6",
           "Nearly one third of the patients (n = 8560)", "2676 (31%) resumed",
           "Overall mortality during the first 36 weeks was 2.0% (n = 605)",
           "R 2 = 0.05", "knots at 10, 16, 22, and 28 sessions", "only 18% attended the full 36 sessions",
           "1225 patients (4%)"],
)

# Hammill Figure 2 (Kaplan-Meier cumulative incidence of death), digitized from the
# PMC figure image nihms166816f2.jpg (800 x 753 px): y = 0 at the curve origin
# (pixel row 480.5), 18.46 px per percentage point from the tick labels; each curve's
# last 16-42 visible pixels fitted with a line and read at x = 4 years.
# Reading error is about +/-0.3 points.
FIG2 = dict(
    source="Hammill 2010 Figure 2, digitized", image="https://pmc.ncbi.nlm.nih.gov/articles/instance/2829871/bin/nihms166816f2.jpg",
    groups=["1 to 11", "12 to 23", "24 to 35", "36"],
    at_risk_36wk=[5937, 6933, 10978, 5465],
    cum_inc_4y=[18.3, 14.2, 12.6, 11.3],
    cum_inc_36wk=2.0,
    reading_error_pts=0.3,
)


def fig2_derived():
    y36 = FIG2["cum_inc_36wk"] / 100
    cond = [(v / 100 - y36) / (1 - y36) for v in FIG2["cum_inc_4y"]]   # 36 weeks -> 4 years, given alive at 36 weeks
    w = FIG2["at_risk_36wk"]
    cond_all = sum(c * n for c, n in zip(cond, w)) / sum(w)
    overall = y36 + (1 - y36) * cond_all
    pattern = math.log(cond[0] / cond[1]) / math.log(cond[1] / cond[3])
    return dict(cond_4y=[round(c, 4) for c in cond], overall_4y=round(overall, 4),
                pattern_1v2_over_2v4=round(pattern, 3))


def e_value(rr):
    rr = 1 / rr if rr < 1 else rr
    return rr + math.sqrt(rr * (rr - 1))


def hr_to_rr_common(hr):
    """VanderWeele's conversion for a common outcome (over 15%)."""
    return (1 - 0.5 ** math.sqrt(hr)) / (1 - 0.5 ** math.sqrt(1 / hr))


# ------------------------------------------------------------------ source checks

def norm(s):
    s = html.unescape(s)
    s = s.replace(" ", " ").replace(" ", " ")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s)


def verify():
    texts = {}
    pmids = sorted({e["pmid"] for e in EST if e.get("pmid")})
    tag = hashlib.md5(",".join(map(str, pmids)).encode()).hexdigest()[:8]   # new cache file when the PMID list changes
    p = fetch("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&rettype=abstract&retmode=text&id="
              + ",".join(map(str, pmids)), name=f"crcurve_pubmed_abstracts_{tag}.txt")
    texts["pubmed"] = norm(p.read_text(encoding="utf-8", errors="ignore"))
    p = fetch("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=2829871&rettype=xml",
              name="crcurve_hammill_pmc.xml")
    texts["hammill"] = norm(p.read_text(encoding="utf-8", errors="ignore"))
    p = fetch("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=4942353&rettype=xml",
              name="crcurve_murray_hernan_2016_pmc.xml")
    texts["mh_pmc"] = norm(p.read_text(encoding="utf-8", errors="ignore"))
    p = fetch(QUOTES[0]["url"], name="crcurve_cms_memo.html")
    texts["cms"] = norm(p.read_text(encoding="utf-8", errors="ignore"))
    pdf = fetch("https://eprints.gla.ac.uk/258451/1/258451.pdf", name="crcurve_cochrane.pdf")
    if shutil.which("pdftotext"):
        txt = pdf.with_suffix(".txt")
        if not txt.exists():
            subprocess.run(["pdftotext", "-l", "6", str(pdf), str(txt)], check=True)
        texts["cochrane"] = norm(txt.read_text(errors="ignore")).replace("- ", "-")
    else:
        print("  pdftotext not found: Cochrane numbers not checked against the PDF")

    def need(where, s, label):
        if where not in texts:
            return None
        hay = texts[where]
        ok = norm(s) in hay or norm(s).replace("–", "-") in hay.replace("–", "-")
        if not ok:
            raise SystemExit(f"SOURCE CHECK FAILED [{label}]: {s!r} not found in {where}")
        return True

    n = 0
    for e in EST:
        src = "hammill" if e["study"].startswith("Hammill") else "cochrane" if e["group"] == "cochrane" else "pubmed"
        for c in e.get("check", []):
            n += bool(need(src, c, e["id"]))
        for c in e.get("check_mh_pmc", []):
            n += bool(need("mh_pmc", c, e["id"]))
    for c in HAMMILL["check"]:
        n += bool(need("hammill", c, "hammill cohort"))
    for c in COCHRANE_POP["check"]:
        n += bool(need("cochrane", c, "cochrane population"))
    n += bool(need("cms", QUOTES[0]["text"], "cms quote"))
    n += bool(need("cms", "the initial 36 sessions may take place within a maximum time of 18 weeks", "cms 18 weeks"))
    n += bool(need("cms", "maximum (including the initial program) to 72 sessions within 36 weeks", "cms 72"))
    n += bool(need("cms", QUOTES[1]["text"], "cms quote 2"))
    n += bool(need("cochrane", QUOTES[2]["text"], "cochrane quote"))
    n += bool(need("hammill", QUOTES[3]["text"].rstrip(","), "hammill quote"))
    print(f"  {n} quoted strings found in their sources")
    return n


# ------------------------------------------------------------------ summary from the grid

def summarize(grid, pub):
    cells = grid["cells"]
    meta = grid["meta"]
    m4 = meta["m4y_default"]
    get = lambda w, b, s, dec=0, m=m4: next(c for c in cells if c["w"] == w and c["b"] == b and c["s"] == s
                                            and c["dec"] == dec and c["m4"] == m)
    hr = lambda c, k, kind="adj", q=1: c[kind][q][k - 1] / 1000
    ham = {e["k"]: e for e in pub["estimates"] if e["group"] == "hammill" and e["adjusted"]}

    def matches(c):
        return sum(ham[k]["lo"] <= hr(c, k) <= ham[k]["hi"] for k in (1, 12, 24))

    d = meta["default"]
    out = dict(default=d)
    full = [c for c in cells if "adj" in c]
    for w in ("A", "B"):
        fits = [c for c in full if matches(c) == 3]
        fits_w = [c for c in fits if c["w"] == w]
        out[f"cells_{w}"] = sum(c["w"] == w for c in full)
        out[f"fit3_{w}"] = len(fits_w)
        out[f"fit3_{w}_b"] = sorted({c["b"] for c in fits_w})
        # split by the pre-death decline toggle: most zero-effect matches need it switched on
        for dec, tag in ((0, "nodec"), (1, "dec")):
            fd = [c for c in fits_w if c["dec"] == dec]
            out[f"fit3_{w}_{tag}"] = len(fd)
            out[f"fit3_{w}_{tag}_b"] = sorted({c["b"] for c in fd})
        best = min((c for c in full if c["w"] == w),
                   key=lambda c: sum((math.log(hr(c, k)) - math.log(ham[k]["est"])) ** 2 for k in (1, 12, 24)))
        out[f"best_{w}"] = dict(b=best["b"], s=best["s"], dec=best["dec"],
                                hr=[hr(best, k) for k in (1, 12, 24)])
    cB = get("B", d["b"], d["s"], d["dec"])
    cA = get("A", d["b"], d["s"], d["dec"])
    out["default_B"] = dict(hr=[hr(cB, k) for k in (1, 12, 24)], lo=[hr(cB, k, q=0) for k in (1, 12, 24)],
                            hi=[hr(cB, k, q=2) for k in (1, 12, 24)], or_good=cB["or_good"])
    out["default_A"] = dict(hr=[hr(cA, k) for k in (1, 12, 24)])
    out["default_inside"] = dict(B=matches(cB), A=matches(cA))
    # 36 vs 24 when late stops are all program-driven vs all health-driven, World B, at the default decline setting
    key = lambda v: f"{v:g}"  # matches JavaScript's String(number)
    dd = d["dec"]
    out["v24_dec"] = dd
    out["v24_by_s"] = {key(b): {key(s): hr(get("B", b, s, dd), 24) for s in meta["s_levels"]} for b in meta["b_levels"]}
    out["v24_cat_by_s"] = {key(b): {key(s): get("B", b, s, dd)["cat"][1][4] / 1000 for s in meta["s_levels"]}
                           for b in meta["b_levels"]}
    flat = get("B", 1.0, d["s"], 0)
    out["null_flat"] = [hr(flat, k) for k in (1, 12, 24)]
    dec_only = get("B", 1.0, d["s"], 1)
    out["decline_only"] = [hr(dec_only, k) for k in (1, 12, 24)]
    # b settings where a zero-effect world gives a crude good-vs-poor attender OR inside Simpson's placebo CI
    simp = next(e for e in pub["estimates"] if e["id"] == "simpson_placebo")
    out["placebo_band_b"] = sorted({c["b"] for c in full if c["w"] == "B" and c["dec"] == d["dec"] and c["s"] == d["s"]
                                    and simp["lo"] <= c["or_good"] <= simp["hi"]})
    # 4-year mortality sensitivity
    sens = []
    for c in cells:
        if "adj_k" in c:
            base = get(c["w"], c["b"], c["s"], 0)
            sens.append(dict(w=c["w"], b=c["b"], m4=c["m4"], hr=[v / 1000 for v in c["adj_k"][1]],
                             base=[hr(base, k) for k in (1, 12, 24)]))
    sens_s = sorted({c["s"] for c in cells if "adj_k" in c})
    sens_dec = sorted({c["dec"] for c in cells if "adj_k" in c})
    out["sens_scope"] = dict(s=sens_s, dec=sens_dec, b="all", worlds=["A", "B"])
    out["sens_max_abs_diff"] = round(max(abs(a - b) for r in sens for a, b in zip(r["hr"], r["base"])), 3)
    out["sensitivity"] = sens
    # E-value for Hammill's 0.53
    h = ham[1]
    out["evalue"] = dict(hr=h["est"], ci_limit=h["hi"], rare=round(e_value(h["est"]), 2),
                         rare_ci=round(e_value(h["hi"]), 2),
                         common=round(e_value(hr_to_rr_common(h["est"])), 2),
                         common_ci=round(e_value(hr_to_rr_common(h["hi"])), 2),
                         overall_4y=pub["fig2"]["derived"]["overall_4y"],
                         used="rare" if pub["fig2"]["derived"]["overall_4y"] < 0.15 else "common")
    cal = json.loads((DATA / "calibration.json").read_text())
    out["calibration"] = [dict(s=c["s"], **{k: round(c["achieved"][k], 3) for k in
                                            ("med", "q1", "q3", "p36", "lt6", "ge30", "r2", "share", "hosp",
                                             "resume", "pattern")}) for c in cal["by_s"]]
    out["sim"] = dict(n=meta["n"], seeds=meta["seeds"], cells=len(cells))
    return out


def main():
    DATA.mkdir(exist_ok=True)
    offline = "--offline" in sys.argv
    if not offline:
        print("checking published numbers against their sources...")
        try:
            verify()
        except SystemExit:
            raise
        except Exception as ex:  # network trouble: say so, keep going
            print(f"  could not check sources ({ex}); rerun online to verify")
    fig2 = dict(FIG2, derived=fig2_derived())
    pub = dict(
        note="Published summary numbers only. The simulated cohort is synthetic.",
        checked="2026-11-11",
        estimates=[{k: v for k, v in e.items() if not k.startswith("check")} for e in EST],
        quotes=QUOTES,
        hammill={k: v for k, v in HAMMILL.items() if k != "check"},
        cochrane_population={k: v for k, v in COCHRANE_POP.items() if k != "check"},
        fig2=fig2,
    )
    (DATA / "published.json").write_text(json.dumps(pub, indent=1, ensure_ascii=False))
    print(f"wrote published.json: {len(EST)} estimates; Fig 2 derived {fig2['derived']}")

    g = DATA / "grid.json"
    if g.exists() and (DATA / "calibration.json").exists():
        s = summarize(json.loads(g.read_text()), pub)
        (DATA / "summary.json").write_text(json.dumps(s, indent=1))
        print("wrote summary.json")
        for k in ("default_B", "default_A", "default_inside", "best_B", "best_A", "fit3_B", "fit3_A", "fit3_B_b", "fit3_A_b",
                  "fit3_B_dec", "fit3_B_dec_b", "fit3_B_nodec", "fit3_B_nodec_b",
                  "null_flat", "decline_only", "placebo_band_b", "sens_max_abs_diff", "evalue"):
            print(f"  {k}: {s[k]}")
        print("  36 vs 24 (spline) by admin share, World B:", s["v24_by_s"])
        print("  36 vs 24-29 (categories) by admin share, World B:", s["v24_cat_by_s"])
    else:
        print("no grid.json yet: run scripts/sim.py, then rerun this script for summary.json")


if __name__ == "__main__":
    main()

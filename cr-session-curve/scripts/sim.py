"""Same Curve, Two Worlds: synthetic Medicare cardiac rehab cohorts.

Simulates cohorts the size of Hammill et al. (Circulation 2010) in two worlds:
  World B: sessions have no effect on survival.
  World A: one assumption consistent with Cochrane (benefit plateaus at 12 sessions).
In both, a hidden health trait Z drives stopping rehab early and dying. The
analysis then mirrors Hammill's: cumulative sessions as a time-dependent
restricted cubic spline (knots 10/16/22/28) in a survival model adjusted for a
measured part of Z and a time-dependent hospitalization flag. The survival model
is a piecewise-exponential Poisson GLM fit by IRLS, which is equivalent to a Cox
model with time bands.

Everything is synthetic. Inputs are published summary numbers only.

Run:  uv run --with numpy --with scipy python3 cr-session-curve/scripts/sim.py
Writes cr-session-curve/data/grid.json and data/calibration.json.
Takes about 5 to 10 minutes on 8 cores. Fixed seeds, so reruns give the same output.
"""
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "data"

MASTER_SEED = 20261111
N = 30000            # synthetic patients per cohort (Hammill: 30,161)
SEEDS = 20           # cohorts per grid cell; the same 20 cohorts are reused in every cell
CAL_N = 60000        # cohort size used for calibration
WEEKS = 208          # 4 years of follow-up, weekly steps
ATTEND_WEEKS = 36    # sessions counted in the first 36 weeks (Hammill)
SCHED = 3            # sessions offered per week ("2 to 3 sessions per week", CMS NCD)
RATE = 0.8           # chance each offered session is attended -> 2.4 a week on average
PAUSE = 3            # weeks without sessions after a hospitalization
C_HOSP = 0.7         # log hazard ratio per SD of Z for hospitalization (assumption)
HOSP_EARLY = 2.0     # hospitalization hazard is front-loaded: x(1 + 2*exp(-(week-1)/8)), readmissions cluster early
DECLINE = 8          # pre-death decline: attendance stops this many weeks before death
EFFECT_A = -0.15     # World A: log hazard ratio once 12 or more sessions are attended
EFFECT_FROM = 12
RHO_FROM = 12        # stopping from this session on has a weaker link to the hidden trait (factor rho, calibrated)
ADMIN_W = np.arange(1, 13) / np.arange(1, 13).sum()   # program end points 24..35, weighted toward later sessions
KNOTS = (10, 16, 22, 28)
BAND_EDGES = np.array([1, 13, 25, 37, 53, 105, 157, 209])  # time bands (weeks) for the baseline hazard
NB = len(BAND_EDGES) - 1

# Calibration targets from data/published.json (written by build_data.py): Hammill 2010
PUB = json.loads((OUT / "published.json").read_text())
_H, _F = PUB["hammill"], PUB["fig2"]["derived"]
T = dict(lt6=_H["sessions"]["pct_under6"], q1=_H["sessions"]["q1"], med=_H["sessions"]["median"],
         q3=_H["sessions"]["q3"], p36=_H["sessions"]["pct_36"],
         ge30=0.41,                                  # "more than 40%" attended 30 or more
         r2=_H["r2_sessions"], hosp=_H["hospitalized_36wk"] / _H["n"], resume=_H["resumed_pct"],
         m36=_H["mortality_36wk"],
         m4y=_F["overall_4y"],                       # digitized from Fig 2
         pattern=_F["pattern_1v2_over_2v4"],         # spacing of Fig 2's group death rates (see below)
         cond4y=sum(c * n for c, n in zip(_F["cond_4y"], PUB["fig2"]["at_risk_36wk"])) / sum(PUB["fig2"]["at_risk_36wk"]))
B_REF = 2.0  # death HR per SD used only to turn the Fig 2 spacing into a calibration target

B_LEVELS = [1.0, 1.2, 1.35, 1.5, 1.65, 2.0, 2.7]   # death hazard ratio per SD of Z
S_LEVELS = [0.0, 0.25, 0.5, 0.75, 1.0]            # share of late (24-35) non-hospital stops that are administrative
M4Y_SENS = [round(T["m4y"] - 0.05, 4), round(T["m4y"] + 0.05, 4)]   # +/- 5 points on 4-year mortality
DEFAULT = dict(b=1.65, s=0.5, dec=1)  # both worlds put all three of Hammill's adjusted HRs inside their CIs; zero-effect crude OR inside Simpson's placebo band


def band_of_week():
    w = np.arange(1, WEEKS + 1)
    return np.searchsorted(BAND_EDGES, w, side="right") - 1


BAND = band_of_week()


def simulate(p, n, seed, world="B", b=1.5, d1=None, d2=None, decline=False,
             weeks=WEEKS, collect=False):
    """One synthetic cohort. p holds the attendance and hospitalization parameters."""
    rng = np.random.default_rng([MASTER_SEED, seed])
    Z = rng.standard_normal(n)
    Zm = 0.5 * Z + math.sqrt(0.75) * rng.standard_normal(n)   # measured part (claims comorbidities)
    U = rng.exponential(1.0, n)                                 # death threshold on cumulative hazard
    admin = rng.random(n) < p["q"]
    L = np.where(admin, 24 + rng.choice(12, n, p=ADMIN_W), 36)   # program end session (24..35) or 36
    u_res = rng.random(n)
    cuts = np.quantile(Zm, np.linspace(0.1, 0.9, 9))
    dec = np.searchsorted(cuts, Zm)
    zm_dec_mean = np.bincount(dec, weights=Zm, minlength=10) / np.bincount(dec, minlength=10)

    lb = math.log(b)
    eZb = np.exp(lb * Z)
    eZa_e = np.exp(p["a"] * Z)                       # frailty link for stops before session 12
    eZa_l = np.exp(p["a"] * p.get("rho", 1.0) * Z)   # weaker or equal link for stops from session 12 on
    hz_h = p["base_h"] * np.exp(C_HOSP * Z)
    if d1 is None:
        d1 = 0.0006
    if d2 is None:
        d2 = 0.0007

    alive = np.ones(n, bool)
    active = np.ones(n, bool)
    hosp = np.zeros(n, bool)
    cum = np.ones(n, np.int64)          # first session is the index date
    cum_at_h = np.zeros(n, np.int64)
    pause = np.zeros(n, np.int64)
    reason = np.zeros(n, np.int8)       # 1 frailty stop, 2 hospital stop, 3 program end, 4 pre-death decline
    H = np.zeros(n)
    dweek = np.full(n, 10_000)
    if collect:
        size = NB * 36 * 2 * 10
        pt = np.zeros(size)
        dd = np.zeros(size)

    for t in range(1, weeks + 1):
        bd = d1 if t <= ATTEND_WEEKS else d2
        if world == "A":
            eff = np.where(cum >= EFFECT_FROM, math.exp(EFFECT_A), 1.0)
            rate = eZb * eff
        else:
            rate = eZb
        if decline and t <= ATTEND_WEEKS:
            n1 = max(0, min(ATTEND_WEEKS, t + DECLINE - 1) - t + 1)
            fut = (n1 * d1 + (DECLINE - n1) * d2) * rate
            stopnow = alive & active & (H + fut >= U)
            reason[stopnow] = 4
            active &= ~stopnow
        h = bd * rate
        dies = alive & (H + h >= U)
        if collect:
            frac = np.where(dies, (U - H) / h, 1.0)
            idx = ((BAND[t - 1] * 36 + (cum - 1)) * 2 + hosp) * 10 + dec
            pt += np.bincount(idx[alive], weights=frac[alive], minlength=size)
            dd += np.bincount(idx[dies], minlength=size)
        H += h
        alive &= ~dies
        dweek[dies] = t

        if t <= ATTEND_WEEKS:
            pause = np.maximum(pause - 1, 0)
            r_h = rng.random(n)
            newh = alive & ~hosp & (r_h < 1 - np.exp(-hz_h * (1 + HOSP_EARLY * math.exp(-(t - 1) / 8))))
            hosp |= newh
            cum_at_h = np.where(newh, cum, cum_at_h)
            hit = newh & active
            quit_ = hit & (u_res >= p["resume_p"])
            reason[quit_] = 2
            active &= ~quit_
            pause = np.where(hit & ~quit_, PAUSE, pause)
            g = np.select([cum < 6, cum < 13, cum < 24, cum < 30], [p["e_mult"], 1.0, p["m_mid"], p["m_late"]],
                          p["m_late2"])
            r_s = rng.random(n)
            k = rng.binomial(SCHED if t > 1 else SCHED - 1, RATE, n)
            can = alive & active & (pause == 0)
            eZa = np.where(cum < RHO_FROM, eZa_e, eZa_l)
            stop = can & (r_s < 1 - np.exp(-p["base_s"] * eZa * g))
            reason[stop] = 1
            active &= ~stop
            att = can & ~stop
            cum = np.where(att, np.minimum(cum + k, L), cum)
            done = att & (cum >= L)
            reason[done & (L < 36)] = 3
            active &= ~done
            if t == ATTEND_WEEKS:
                final = cum.copy()
                alive36 = alive.copy()
                hosp36 = hosp.copy()

    out = dict(final=final, alive36=alive36, hosp36=hosp36, reason=reason, Zm=Zm, Z=Z,
               dweek=dweek, cum_at_h=cum_at_h)
    if collect:
        out["pt"] = pt.reshape(NB, 36, 2, 10)
        out["d"] = dd.reshape(NB, 36, 2, 10)
        out["zm_dec_mean"] = zm_dec_mean
    return out


def attendance_stats(o):
    f = o["final"]
    F = lambda k: np.mean(f <= k)
    a36 = o["alive36"]
    # R^2 of sessions on measured covariates among 36-week survivors (Hammill Table 4: 0.05)
    X = np.column_stack([np.ones(a36.sum()), o["Zm"][a36], o["hosp36"][a36]])
    y = f[a36].astype(float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    r2 = 1 - np.var(y - X @ beta) / np.var(y)
    late = a36 & (f >= 24) & (f <= 35)
    r = o["reason"]
    nonh = late & (r != 2)
    share = np.mean(r[nonh] == 3) if nonh.any() else 0.0
    share_all = np.mean(r[late] == 3) if late.any() else 0.0
    hosp = o["hosp36"]
    resumed = hosp & (f > o["cum_at_h"])
    # Spacing of 4-year death risk across Hammill's Fig 2 attendance groups, as World B would show it
    # at death HR B_REF per SD: log(g1/g2) / log(g2/g4), groups 1-11, 12-23, 24-35, 36 sessions.
    z = o["Z"][a36]
    ez = np.exp(math.log(B_REF) * z)
    lam = -math.log(1 - T["cond4y"]) / ez.mean()
    risk = 1 - np.exp(-lam * ez)
    fa = f[a36]
    g = [risk[(fa >= lo) & (fa <= hi)].mean() for lo, hi in ((1, 11), (12, 23), (24, 35), (36, 36))]
    pattern = math.log(g[0] / g[1]) / math.log(g[1] / g[3])
    return dict(
        F5=F(5), F125=(F(12) + F(13)) / 2, F245=(F(24) + F(25)) / 2, F335=(F(33) + F(34)) / 2,
        lt6=F(5), p36=np.mean(f == 36), ge30=np.mean(f >= 30),
        q1=float(np.percentile(f, 25, method="inverted_cdf")),
        med=float(np.percentile(f, 50, method="inverted_cdf")),
        q3=float(np.percentile(f, 75, method="inverted_cdf")),
        r2=r2, share=share, share_all=share_all, late_frac=np.mean((f >= 24) & (f <= 35)),
        hosp=np.mean(hosp), resume=resumed.sum() / max(1, hosp.sum()),
        m36=np.mean(o["dweek"] <= ATTEND_WEEKS), m4y=np.mean(o["dweek"] <= WEEKS), pattern=pattern,
    )


# ---------------------------------------------------------------- calibration

def calibrate_hosp():
    """base_h so that 28.4% are hospitalized within 36 weeks."""
    p = dict(q=0.0, a=0.5, base_s=0.02, e_mult=3, m_mid=1, m_late=3, m_late2=3, resume_p=0.5, base_h=0.01)
    lo, hi = 1e-4, 0.05
    for _ in range(30):
        mid = math.sqrt(lo * hi)
        p["base_h"] = mid
        o = simulate(p, CAL_N, 999, weeks=ATTEND_WEEKS, d1=0.00055)
        if np.mean(o["hosp36"]) < T["hosp"]:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi)


def calibrate_attendance(s, base_h):
    """Fit stopping parameters to Hammill's session distribution for a given administrative share s."""
    fix_q0 = s == 0.0
    fix_m0 = s == 1.0

    def unpack(x):
        p = dict(base_h=base_h)
        p["base_s"] = math.exp(x[0])
        p["e_mult"] = math.exp(x[1])
        p["a"] = math.exp(x[2])
        p["resume_p"] = 1 / (1 + math.exp(-x[3]))
        p["m_mid"] = math.exp(x[4])
        p["m_late"] = 0.0 if fix_m0 else math.exp(x[5])
        p["m_late2"] = 0.0 if fix_m0 else math.exp(x[6])
        p["q"] = 0.0 if fix_q0 else 1 / (1 + math.exp(-x[7]))
        p["rho"] = 1 / (1 + math.exp(-x[8]))
        return p

    def loss(x):
        p = unpack(x)
        st = attendance_stats(simulate(p, CAL_N, 999, weeks=ATTEND_WEEKS, d1=0.00055))
        r = [(st["F5"] - T["lt6"]) / 0.005, (st["F125"] - 0.25) / 0.005, (st["F245"] - 0.5) / 0.005,
             (st["F335"] - 0.75) / 0.005, (st["p36"] - T["p36"]) / 0.005, (st["ge30"] - T["ge30"]) / 0.01,
             (st["r2"] - T["r2"]) / 0.005, (st["resume"] - T["resume"]) / 0.01,
             (st["pattern"] - T["pattern"]) / 0.05]
        if not (fix_q0 or fix_m0):
            r.append((st["share"] - s) / 0.02)
        return float(np.sum(np.square(r)))

    best = None
    logit = lambda v: math.log(v / (1 - v))
    starts = [[math.log(0.04), math.log(1.0), math.log(1.0), 1.2, math.log(2.0), math.log(1.0), math.log(4), logit(0.02 + 0.6 * s), logit(0.3)],
              [math.log(0.03), math.log(1.2), math.log(1.2), 1.0, math.log(2.5), math.log(1.5), math.log(6), logit(0.02 + 0.66 * s), logit(0.2)],
              [math.log(0.05), math.log(0.8), math.log(0.8), 1.4, math.log(1.5), math.log(0.8), math.log(3), logit(0.02 + 0.55 * s), logit(0.45)]]
    for x0 in starts:
        res = minimize(loss, x0, method="Nelder-Mead",
                       options=dict(maxiter=4000, xatol=1e-3, fatol=1e-3, adaptive=True))
        if best is None or res.fun < best.fun:
            best = res
    p = unpack(best.x)
    st = attendance_stats(simulate(p, CAL_N, 999, weeks=ATTEND_WEEKS, d1=0.00055))
    return p, st, best.fun


def calibrate_death(p, world, b, decline, m4y):
    """Weekly death hazards so 2.0% die by 36 weeks and m4y by 4 years."""
    lb = math.log(b)
    ez = math.exp(lb * lb / 2)  # E[exp(lb*Z)]
    d1 = -math.log(1 - T["m36"]) / ATTEND_WEEKS / ez
    d2 = -math.log((1 - m4y) / (1 - T["m36"])) / (WEEKS - ATTEND_WEEKS) / ez
    for _ in range(8):
        o = simulate(p, CAL_N, 998, world, b, d1, d2, decline)
        m36 = np.mean(o["dweek"] <= ATTEND_WEEKS)
        m4 = np.mean(o["dweek"] <= WEEKS)
        d1 *= math.log(1 - T["m36"]) / math.log(1 - m36)
        d2 *= math.log((1 - m4y) / (1 - T["m36"])) / math.log((1 - m4) / (1 - m36))
        if abs(m36 - T["m36"]) < 2e-4 and abs(m4 - m4y) < 5e-4:
            break
    return d1, d2


# ---------------------------------------------------------------- estimator

def rcs(x):
    """Restricted cubic spline basis (Harrell), knots KNOTS: linear term + 2 nonlinear terms."""
    x = np.asarray(x, float)
    t = KNOTS
    pos = lambda v: np.maximum(v, 0) ** 3
    norm = (t[3] - t[0]) ** 2
    cols = [x]
    for j in range(2):
        cols.append((pos(x - t[j]) - pos(x - t[2]) * (t[3] - t[j]) / (t[3] - t[2])
                     + pos(x - t[3]) * (t[2] - t[j]) / (t[3] - t[2])) / norm)
    return np.column_stack(cols)


SPL = rcs(np.arange(1, 37))


def poisson_irls(X, y, off, iters=50):
    beta = np.zeros(X.shape[1])
    beta[:NB] = math.log(max(y.sum(), 1) / np.exp(off).sum())
    for _ in range(iters):
        eta = X @ beta + off
        mu = np.exp(eta)
        z = eta - off + (y - mu) / mu
        XW = X * mu[:, None]
        new = np.linalg.solve(X.T @ XW, XW.T @ z)
        if np.max(np.abs(new - beta)) < 1e-9:
            beta = new
            break
        beta = new
    return beta


def fit(o):
    """Hazard ratios 36 sessions vs k (k = 1..36), adjusted and unadjusted."""
    pt, d = o["pt"], o["d"]
    band, cum, hosp, dec = np.indices(pt.shape)
    m = pt > 0
    y, off = d[m], np.log(pt[m])
    bd = np.eye(NB)[band[m]]
    spl = SPL[cum[m]]
    Xu = np.column_stack([bd, spl])
    Xa = np.column_stack([bd, spl, o["zm_dec_mean"][dec[m]], hosp[m]])
    out = {}
    for name, X in (("unadj", Xu), ("adj", Xa)):
        beta = poisson_irls(X, y, off)
        bs = beta[NB:NB + 3]
        out[name] = np.exp((SPL[35] - SPL) @ bs)   # HR 36 vs k
        if name == "adj":
            out["hr_zm"] = math.exp(beta[NB + 3])
            out["hr_hosp"] = math.exp(beta[NB + 4])
    return out


CAT_EDGES = [(1, 5), (6, 11), (12, 17), (18, 23), (24, 29), (30, 35)]


def fit_categories(o):
    """Same adjusted model with 6 attendance categories (reference: 36) instead of the spline."""
    pt, d = o["pt"], o["d"]
    band, cum, hosp, dec = np.indices(pt.shape)
    m = pt > 0
    k = cum[m] + 1
    C = np.column_stack([(k >= lo) & (k <= hi) for lo, hi in CAT_EDGES]).astype(float)
    X = np.column_stack([np.eye(NB)[band[m]], C, o["zm_dec_mean"][dec[m]], hosp[m]])
    beta = poisson_irls(X, d[m], np.log(pt[m]))
    return np.exp(-beta[NB:NB + 6])   # HR 36 vs each category


def crude(o):
    """Crude contrasts a reader might compute from this cohort."""
    f, dw, a36 = o["final"], o["dweek"], o["alive36"]
    died = dw <= WEEKS
    good = f >= 29                              # attended at least 80% of 36 (the CDP adherence cut)
    a, b_ = np.sum(good & died), np.sum(good & ~died)
    c, d = np.sum(~good & died), np.sum(~good & ~died)
    or_ = (a / b_) / (c / d)
    groups = [(1, 11), (12, 23), (24, 35), (36, 36)]
    km = []
    for lo, hi in groups:  # Hammill Fig 2 groups, conditional on survival to 36 weeks
        g = a36 & (f >= lo) & (f <= hi)
        km.append(float(np.mean(dw[g] <= WEEKS)))
    return or_, km


# ---------------------------------------------------------------- grid

def run_cell(args):
    cell, p = args
    d1, d2 = calibrate_death(p, cell["w"], cell["b"], cell["dec"], cell["m4"])
    adj, unadj, cat, ors, kms, sts, hz, hh = [], [], [], [], [], [], [], []
    for sd in range(SEEDS):
        o = simulate(p, N, sd, cell["w"], cell["b"], d1, d2, cell["dec"], collect=True)
        fr = fit(o)
        adj.append(fr["adj"])
        unadj.append(fr["unadj"])
        cat.append(fit_categories(o))
        hz.append(fr["hr_zm"])
        hh.append(fr["hr_hosp"])
        or_, km = crude(o)
        ors.append(or_)
        kms.append(km)
        sts.append(attendance_stats(o))
    adj, unadj = np.array(adj), np.array(unadj)
    q = lambda a: np.percentile(a, [10, 50, 90], axis=0)
    st = {k: float(np.median([s[k] for s in sts])) for k in sts[0]}
    return dict(cell=cell, d1=d1, d2=d2, adj=q(adj), unadj=q(unadj), cat=q(np.array(cat)),
                crude_or=float(np.median(ors)), km=np.median(np.array(kms), axis=0).tolist(),
                hr_zm=float(np.median(hz)), hr_hosp=float(np.median(hh)), st=st)


def pm(a):
    return [int(round(1000 * v)) for v in a]


def main():
    t0 = time.time()
    OUT.mkdir(exist_ok=True)
    print("calibrating hospitalization...", flush=True)
    base_h = calibrate_hosp()
    print(f"  base_h = {base_h:.5f}", flush=True)

    print("calibrating attendance for each administrative share...", flush=True)
    with ProcessPoolExecutor(max_workers=min(len(S_LEVELS), os.cpu_count() or 4)) as ex:
        cal = list(ex.map(calibrate_attendance, S_LEVELS, [base_h] * len(S_LEVELS)))
    params = {}
    calib_out = []
    for s, (p, st, loss) in zip(S_LEVELS, cal):
        params[s] = p
        print(f"  s_admin={s:.2f}: median {st['med']:.0f} IQR {st['q1']:.0f}-{st['q3']:.0f}, "
              f"36 = {st['p36']:.3f}, <6 = {st['lt6']:.3f}, >=30 = {st['ge30']:.3f}, R2 = {st['r2']:.3f}, "
              f"admin share of late non-hospital stops = {st['share']:.2f} (of all late stops {st['share_all']:.2f}), "
              f"hosp = {st['hosp']:.3f}, resumed = {st['resume']:.3f}, Fig 2 spacing {st['pattern']:.2f} "
              f"(target {T['pattern']:.2f})   loss {loss:.2f}", flush=True)
        print("     params " + ", ".join(f"{k}={v:.4f}" for k, v in p.items()), flush=True)
        calib_out.append(dict(s=s, params=p, achieved=st, loss=loss))

    cells = []
    for w in ("B", "A"):
        for dec in (0, 1):
            for s in S_LEVELS:
                for b in B_LEVELS:
                    cells.append(dict(w=w, b=b, s=s, dec=dec, m4=T["m4y"], full=True))
    for w in ("B", "A"):
        for m4 in M4Y_SENS:
            for b in B_LEVELS:
                cells.append(dict(w=w, b=b, s=DEFAULT["s"], dec=0, m4=m4, full=False))
    print(f"running {len(cells)} cells x {SEEDS} cohorts of {N:,}...", flush=True)
    with ProcessPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
        res = list(ex.map(run_cell, [(c, params[c["s"]]) for c in cells], chunksize=1))

    grid = []
    for r in res:
        c = r["cell"]
        row = dict(w=c["w"], b=c["b"], s=c["s"], dec=c["dec"], m4=c["m4"],
                   or_good=round(r["crude_or"], 3), km=[round(v, 4) for v in r["km"]],
                   hr_zm=round(r["hr_zm"], 3), hr_hosp=round(r["hr_hosp"], 3),
                   st={k: round(v, 4) for k, v in r["st"].items()
                       if k in ("med", "q1", "q3", "p36", "lt6", "ge30", "r2", "share", "share_all",
                                "hosp", "resume", "m36", "m4y", "pattern")})
        if c["full"]:
            row["adj"] = [pm(r["adj"][i]) for i in range(3)]       # [p10, median, p90], k = 1..36
            row["unadj"] = [pm(r["unadj"][i]) for i in range(3)]
            row["cat"] = [pm(r["cat"][i]) for i in range(3)]            # 36 vs 1-5, 6-11, 12-17, 18-23, 24-29, 30-35
        else:
            ks = [0, 11, 23]  # k = 1, 12, 24
            row["adj_k"] = [[int(round(1000 * r["adj"][i][k])) for k in ks] for i in range(3)]
            row["unadj_k"] = [[int(round(1000 * r["unadj"][i][k])) for k in ks] for i in range(3)]
        grid.append(row)

    meta = dict(
        generated_by="scripts/sim.py", master_seed=MASTER_SEED, n=N, seeds=SEEDS, weeks=WEEKS,
        attend_weeks=ATTEND_WEEKS, sessions_offered_per_week=SCHED, attend_prob=RATE, pause_weeks=PAUSE,
        hosp_log_hr_per_sd=C_HOSP, decline_weeks=DECLINE, effect_A=dict(log_hr=EFFECT_A, from_sessions=EFFECT_FROM),
        cat_groups=CAT_EDGES, stop_segments=[6, 13, 24, 30], rho_from=RHO_FROM, b_ref_pattern=B_REF, admin_weights=ADMIN_W.round(4).tolist(), hosp_early=HOSP_EARLY,
        knots=KNOTS, band_edges_weeks=BAND_EDGES.tolist(), b_levels=B_LEVELS, s_levels=S_LEVELS,
        m4y_default=T["m4y"], m4y_sens=M4Y_SENS, default=DEFAULT, targets=T, measured_loading=0.5,
        curves="hazard ratio x1000, 36 sessions vs k for k = 1..36; rows are 10th, 50th, 90th percentile over cohorts",
    )
    (OUT / "grid.json").write_text(json.dumps(dict(meta=meta, cells=grid), separators=(",", ":")))
    (OUT / "calibration.json").write_text(json.dumps(dict(base_h=base_h, by_s=calib_out), indent=1, default=float))

    # ---------------- sanity checks
    def get(w, b, s, dec=0, m4=T["m4y"]):
        for r in grid:
            if r["w"] == w and r["b"] == b and r["s"] == s and r["dec"] == dec and r["m4"] == m4:
                return r

    def hr(r, k, kind="adj"):
        return r[kind][1][k - 1] / 1000

    print("\nSanity: World B with no link between the trait and death (b = 1.0) should be flat:")
    for s in S_LEVELS:
        r = get("B", 1.0, s)
        print(f"  s={s:.2f}: 36v1 {hr(r,1):.3f}  36v12 {hr(r,12):.3f}  36v24 {hr(r,24):.3f}")
    print("World B, s=0.5, decline off: adjusted (unadjusted) HR 36 vs 1 / 12 / 24")
    for b in B_LEVELS:
        r = get("B", b, 0.5)
        print(f"  b={b:.2f}: {hr(r,1):.2f} ({hr(r,1,'unadj'):.2f}) / {hr(r,12):.2f} ({hr(r,12,'unadj'):.2f}) / "
              f"{hr(r,24):.2f} ({hr(r,24,'unadj'):.2f})   crude good-vs-poor OR {r['or_good']:.2f}   "
              f"HR hosp {r['hr_hosp']:.2f}  m4y {r['st']['m4y']:.3f}")
    print("World B 36v24 by administrative share (b = 1.5, 2.0):")
    for b in (1.5, 2.0):
        print("  b=%.2f: " % b + "  ".join(f"s={s:.2f}: {hr(get('B', b, s), 24):.2f}" for s in S_LEVELS))
    print("World A, s=0.5, decline off:")
    for b in B_LEVELS:
        r = get("A", b, 0.5)
        print(f"  b={b:.2f}: {hr(r,1):.2f} / {hr(r,12):.2f} / {hr(r,24):.2f}")
    print("Pre-death decline on, World B, s=0.5:")
    for b in B_LEVELS:
        r = get("B", b, 0.5, dec=1)
        print(f"  b={b:.2f}: {hr(r,1):.2f} / {hr(r,12):.2f} / {hr(r,24):.2f}")
    print(f"\ndone in {time.time() - t0:.0f} s; grid.json {(OUT / 'grid.json').stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()

"""The population what-if: a cohort-component projection by single year of age and sex.

Starts from one year's population in five-year age groups (the UN WPP pyramid)
and steps forward a year at a time:

  * mortality: a one-parameter Brass logit life table per sex and year, its
    level solved so the table's life expectancy at birth matches the path
    (WPP medium, plus any change asked for);
  * fertility: births from women aged 15 to 49, the total fertility rate spread
    across ages around the mean age at childbearing; boys and girls split by
    the sex ratio at birth;
  * migration: net migrants split evenly by sex and spread across ages with a
    standard (Rogers-Castro) age profile, young adults most.

The model is simple on purpose and so is not the UN's own. Where the UN's
births and deaths for a year are known, the default run is tuned to them (a
factor on fertility and one on the risk of dying, each year, both then kept in
every scenario), which takes out most of the difference in age patterns. Run
with the UN's inputs it lands close to the UN projection (how close is reported
as `raw_error`), and `whatif` corrects the rest: the scenario is shown as the UN figures plus
the difference the levers make, so at default settings it is the UN projection
exactly. Pure Python, so the API and the pipeline's checks can both use it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

TOP = 100                       # single ages 0..99, then 100+ as one open group
GROUPS = [f"{a}-{a + 4}" for a in range(0, 100, 5)] + ["100+"]
MAX_AGE = 130                   # life tables run to here
FERTILE = range(15, 50)

DEFAULTS = {"mac": 28.0, "srb": 105.0}
INPUTS = ("tfr", "mac", "srb", "e0_male", "e0_female", "net_migration")
TARGETS = ("births", "deaths")  # optional: the UN's own counts, to tune the default run to

# Standard mortality: a Siler hazard (falling child mortality, a constant, and an
# exponential rise with age), close to a mid-level modern life table.
SILER = {"a1": 0.03, "b1": 1.5, "a2": 0.001, "a3": 0.00005, "b3": 0.09}


# ----------------------------------------------------------------------------- mortality
def _standard_logits() -> list[float]:
    s = SILER
    out = [-math.inf]
    for x in range(1, MAX_AGE + 1):
        h = s["a1"] / s["b1"] * (1 - math.exp(-s["b1"] * x)) + s["a2"] * x + s["a3"] / s["b3"] * (math.exp(s["b3"] * x) - 1)
        lx = math.exp(-h)
        out.append(0.5 * math.log((1 - lx) / lx))
    return out


_YS = _standard_logits()


@dataclass(frozen=True)
class LifeTable:
    l: list[float]   # survivors to exact age x, l[0] = 1
    L: list[float]   # person-years lived between x and x+1
    T: list[float]   # person-years lived above x
    e0: float


def life_table(alpha: float) -> LifeTable:
    l = [1.0] + [1 / (1 + math.exp(min(700.0, 2 * (alpha + y)))) for y in _YS[1:]] + [0.0]
    q0 = 1 - l[1]
    a0 = min(0.35, 0.07 + 1.7 * q0) if q0 < 0.1 else 0.34  # Coale-Demeny, both sexes
    L = [l[1] + a0 * (1 - l[1])] + [(l[x] + l[x + 1]) / 2 for x in range(1, MAX_AGE + 1)]
    T = [0.0] * (MAX_AGE + 2)
    for x in range(MAX_AGE, -1, -1):
        T[x] = T[x + 1] + L[x]
    return LifeTable(l, L, T, T[0])


# e0 against the Brass level, once: life tables for a given e0 come from it by interpolation.
_ALPHAS = [-3 + 0.01 * i for i in range(601)]
_E0S: list[float] = []


def _alpha_for(e0: float) -> float:
    if not _E0S:
        _E0S.extend(life_table(a).e0 for a in _ALPHAS)  # falls as alpha rises
    if e0 >= _E0S[0]:
        return _ALPHAS[0]
    if e0 <= _E0S[-1]:
        return _ALPHAS[-1]
    lo, hi = 0, len(_E0S) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _E0S[mid] > e0:
            lo = mid
        else:
            hi = mid
    f = (_E0S[lo] - e0) / (_E0S[lo] - _E0S[hi])
    return _ALPHAS[lo] + f * (_ALPHAS[hi] - _ALPHAS[lo])


_tables: dict[float, LifeTable] = {}


def table_for(e0: float) -> LifeTable:
    """The Brass life table with this life expectancy at birth (to 0.01 years)."""
    key = round(e0, 2)
    if key not in _tables:
        if len(_tables) > 20_000:
            _tables.clear()
        _tables[key] = life_table(_alpha_for(key))
    return _tables[key]


# ----------------------------------------------------------------------------- fertility and migration
_shapes: dict[float, list[float]] = {}


def fertility_shape(mac: float) -> list[float]:
    """Share of a woman's births at each age 15..49 (sums to 1), peaking near the mean age."""
    key = round(mac, 1)
    if key not in _shapes:
        sd = 5.5
        w = [math.exp(-0.5 * ((x + 0.5 - key) / sd) ** 2) for x in FERTILE]
        total = sum(w)
        _shapes[key] = [v / total for v in w]
    return _shapes[key]


def _migration_profile() -> list[float]:
    m = [0.02 * math.exp(-0.1 * x) + 0.06 * math.exp(-0.1 * (x - 20) - math.exp(-0.4 * (x - 20))) + 0.003
         for x in range(TOP + 1)]
    total = sum(m)
    return [v / total for v in m]


MIGRATION_PROFILE = _migration_profile()


# ----------------------------------------------------------------------------- helpers
def split_groups(groups: list[float]) -> list[float]:
    """Five-year groups (0-4 .. 95-99, 100+) spread evenly over single ages."""
    out = []
    for g in groups[:20]:
        out.extend([g / 5] * 5)
    out.append(groups[20] if len(groups) > 20 else 0.0)
    return out


def to_groups(ages: list[float]) -> list[float]:
    return [sum(ages[a:a + 5]) for a in range(0, 100, 5)] + [ages[TOP]]


@dataclass
class Levers:
    """Changes to the UN medium path. tfr and e0 are added in full after `phase`
    years (growing evenly until then); migration changes apply at once."""
    tfr: float = 0.0              # children per woman, e.g. -0.5
    e0: float = 0.0               # years of life expectancy, both sexes
    migration: float = 1.0        # multiplier on net migration, 0..3
    extra_migrants: float = 0.0   # added to net migration each year (persons)
    phase: int = 10               # years until the changes are in full

    def is_default(self) -> bool:
        return self.tfr == 0 and self.e0 == 0 and self.migration == 1 and self.extra_migrants == 0

    def ramp(self, years_on: float) -> float:
        return 1.0 if self.phase <= 0 else min(1.0, max(0.0, years_on / self.phase))


@dataclass
class Paths:
    """The yearly inputs (calendar years), with what was missing and held level."""
    years: list[int]
    values: dict[str, dict[int, float]]
    held: dict[str, int] = field(default_factory=dict)  # input -> last year that had data


def fill_paths(raw: dict[str, dict[int, float]], start: int, end: int) -> Paths:
    """Every input for every year from start to end: gaps take the nearest earlier
    value (or the first one), and inputs with no data at all take the defaults."""
    years = list(range(start, end + 1))
    values: dict[str, dict[int, float]] = {}
    held: dict[str, int] = {}
    for name in INPUTS:
        have = {y: v for y, v in (raw.get(name) or {}).items() if v is not None and math.isfinite(v)}
        if not have:
            if name in DEFAULTS:
                values[name] = {y: DEFAULTS[name] for y in years}
            elif name == "net_migration":
                values[name] = {y: 0.0 for y in years}
                held[name] = start
            else:
                raise ValueError(f"no {name} data to project with")
            continue
        known = sorted(have)
        out, last = {}, have[known[0]]
        for y in years:
            if y in have:
                last = have[y]
            out[y] = last
        values[name] = out
        if known[-1] < end:
            held[name] = known[-1]
    for name in TARGETS:  # only the years given; no filling
        values[name] = {y: v for y, v in (raw.get(name) or {}).items() if v and math.isfinite(v) and start <= y <= end}
    return Paths(years, values, held)


# ----------------------------------------------------------------------------- projection
@dataclass
class Year:
    year: int
    male: list[float]     # single ages 0..99, 100+
    female: list[float]
    births: float = 0.0
    deaths: float = 0.0
    migrants: float = 0.0

    @property
    def total(self) -> float:
        return sum(self.male) + sum(self.female)


def project(base_year: int, male5: list[float], female5: list[float], paths: Paths, end: int,
            levers: Levers | None = None, tune: dict[int, tuple[float, float]] | None = None) -> list[Year]:
    """Population on 1 July of each year from base_year to end.

    tune: per step (keyed by its start year) a factor on fertility and one on the
    risk of dying. Pass an empty dict to have them fitted here to the UN's births
    and deaths where given (holding the last factors after that); they are written
    into it, to pass to a scenario run so it stands on the same footing. None: no tuning.
    """
    lv = levers or Levers()
    v = paths.values
    fitting = tune is not None and not tune
    out = [Year(base_year, split_groups(male5), split_groups(female5))]
    kf, km = 1.0, 1.0
    for t in range(base_year, end):
        cur = out[-1]
        # The step runs from 1 July t to 1 July t+1: half of each calendar year's rates.
        mid = lambda name: (v[name][t] + v[name][t + 1]) / 2  # noqa: E731
        r = lv.ramp(t + 0.5 - base_year)
        tfr = max(0.0, mid("tfr") + lv.tfr * r)
        srb = mid("srb")
        mig = mid("net_migration") * lv.migration + lv.extra_migrants
        tables = {sex: table_for(max(15.0, min(95.0, mid(f"e0_{sex}") + lv.e0 * r))) for sex in ("male", "female")}
        if tune is not None and not fitting:
            kf, km = tune.get(t, (kf, km))
        new, died = _survive(cur, tables, km)
        shape = fertility_shape(mid("mac"))
        exposure = sum(s * (cur.female[x] + new["female"][x]) / 2 for s, x in zip(shape, FERTILE))
        if fitting:
            target = {k: (v[k][t] + v[k][t + 1]) / 2 for k in TARGETS if t in v[k] and t + 1 in v[k]}
            if "births" in target and tfr * exposure > 0:
                kf = target["births"] / (tfr * exposure)
            if "deaths" in target and died > 0:
                # The UN count includes babies born in the year; aim the rest at it.
                babies = tfr * kf * exposure * sum(1 - tables[s].L[0] for s in tables) / 2
                km *= max(0.2, target["deaths"] - babies) / died
                new, died = _survive(cur, tables, km)
                exposure = sum(s * (cur.female[x] + new["female"][x]) / 2 for s, x in zip(shape, FERTILE))
            tune[t] = (kf, km)
        births = tfr * kf * exposure
        nxt = Year(t + 1, new["male"], new["female"])
        boys = births * srb / (100 + srb)
        deaths = died
        for sex, b in (("male", boys), ("female", births - boys)):
            l0 = 1 - min(1.0, km * (1 - tables[sex].L[0]))
            getattr(nxt, sex)[0] = b * l0
            deaths += b * (1 - l0)
        # Net migrants, half each sex, spread over ages; never below zero people.
        moved = 0.0
        for sex in ("male", "female"):
            pop = getattr(nxt, sex)
            for x, share in enumerate(MIGRATION_PROFILE):
                add = max(-pop[x], mig / 2 * share)
                pop[x] += add
                moved += add
        nxt.births, nxt.deaths, nxt.migrants = births, deaths, moved
        out.append(nxt)
    return out


def _survive(cur: Year, tables: dict[str, LifeTable], k: float) -> tuple[dict[str, list[float]], float]:
    """Everyone a year older, with the risk of dying at each age times k."""
    new_pops, died = {}, 0.0
    for sex, pop in (("male", cur.male), ("female", cur.female)):
        L, T = tables[sex].L, tables[sex].T
        p = [1 - min(1.0, k * (1 - L[x + 1] / L[x])) for x in range(TOP - 1)]
        p.append(1 - min(1.0, k * (1 - T[TOP] / T[TOP - 1])))
        p.append(1 - min(1.0, k * (1 - T[TOP + 1] / T[TOP])))
        new = [0.0] * (TOP + 1)
        for x in range(TOP - 1):
            new[x + 1] = pop[x] * p[x]
        new[TOP] = pop[TOP - 1] * p[TOP - 1] + pop[TOP] * p[TOP]
        died += sum(pop) - sum(new[1:])
        new_pops[sex] = new
    return new_pops, died


# ----------------------------------------------------------------------------- the what-if
@dataclass
class Pyramid:
    male: list[float]    # five-year groups, GROUPS order
    female: list[float]

    @property
    def total(self) -> float:
        return sum(self.male) + sum(self.female)


def whatif(base_year: int, base: Pyramid, raw: dict[str, dict[int, float]], end: int, levers: Levers,
           un: dict[int, Pyramid] | None = None, un_totals: dict[int, float] | None = None) -> dict:
    """The scenario next to the UN's own projection.

    un: the UN pyramids by year (five-year groups), where held; un_totals: UN
    total population by year, used where pyramids are not held. The scenario is
    the UN figure plus (scenario run - default run), group by group, so the model's
    own error cancels; raw_error is that error, the default run against the UN.
    """
    un, un_totals = un or {}, un_totals or {}
    paths = fill_paths(raw, base_year, end)
    tune: dict[int, tuple[float, float]] = {}
    default = project(base_year, base.male, base.female, paths, end, tune=tune)
    scen = default if levers.is_default() else project(base_year, base.male, base.female, paths, end, levers, tune)
    years, baseline, scenario, pyramids, model = [], [], [], {}, []
    for d, s in zip(default, scen):
        y = d.year
        dm, df, sm, sf = to_groups(d.male), to_groups(d.female), to_groups(s.male), to_groups(s.female)
        if y in un:
            u = un[y]
            bm, bf = u.male, u.female
            am = [max(0.0, b + x - z) for b, x, z in zip(u.male, sm, dm)]
            af = [max(0.0, b + x - z) for b, x, z in zip(u.female, sf, df)]
        else:
            k = un_totals[y] / d.total if y in un_totals and d.total else 1.0
            bm, bf = [z * k for z in dm], [z * k for z in df]
            am, af = [z * k for z in sm], [z * k for z in sf]
        years.append(y)
        baseline.append(sum(bm) + sum(bf))
        scenario.append(sum(am) + sum(af))
        model.append(d.total)
        pyramids[y] = {"baseline": {"male": bm, "female": bf}, "scenario": {"male": am, "female": af}}
    return {
        "base_year": base_year, "years": years, "groups": GROUPS,
        "baseline": baseline, "scenario": scenario, "model_default": model,
        "births": {"baseline": [d.births for d in default], "scenario": [s.births for s in scen]},
        "deaths": {"baseline": [d.deaths for d in default], "scenario": [s.deaths for s in scen]},
        "pyramids": pyramids,
        "inputs": _input_paths(paths, years, base_year, levers),
        "held": paths.held,
        "raw_error": raw_error(default, un, un_totals),
    }


def _input_paths(paths: Paths, years: list[int], base_year: int, lv: Levers) -> dict:
    """The yearly inputs as the UN has them and with the levers applied, for charts."""
    v = paths.values
    e0 = {y: (v["e0_male"][y] + v["e0_female"][y]) / 2 for y in years}
    mig = {y: v["net_migration"][y] for y in years}
    ramp = {y: lv.ramp(y - base_year) for y in years}
    return {
        "tfr": {"baseline": [v["tfr"][y] for y in years],
                "scenario": [max(0.0, v["tfr"][y] + lv.tfr * ramp[y]) for y in years]},
        "e0": {"baseline": [e0[y] for y in years], "scenario": [e0[y] + lv.e0 * ramp[y] for y in years]},
        "net_migration": {"baseline": [mig[y] for y in years],
                          "scenario": [mig[y] * lv.migration + lv.extra_migrants for y in years]},
    }


def raw_error(run: list[Year], un: dict[int, Pyramid], un_totals: dict[int, float]) -> dict:
    """How far the model's default run is from the UN's: total population by year
    (percent), and the largest gap in any five-year group as a share of the total."""
    by_year = {}
    for d in run:
        ref = un[d.year].total if d.year in un else un_totals.get(d.year)
        if not ref or d.year == run[0].year:
            continue
        rec = {"total_pct": round(100 * (d.total - ref) / ref, 3)}
        if d.year in un:
            u = un[d.year]
            gaps = [abs(a - b) for a, b in zip(to_groups(d.male) + to_groups(d.female), u.male + u.female)]
            rec["worst_group_pct"] = round(100 * max(gaps) / ref, 3)
        by_year[d.year] = rec
    worst = max((abs(r["total_pct"]) for r in by_year.values()), default=None)
    return {"by_year": by_year, "worst_total_pct": worst}


def summary(pyr: Pyramid) -> dict:
    """Key shares of a pyramid: under 15, 15 to 64, 65 and over, old-age dependency, median age."""
    tot = [m + f for m, f in zip(pyr.male, pyr.female)]
    total = sum(tot) or 1.0
    young, old = sum(tot[:3]), sum(tot[13:])
    work = total - young - old
    half, run, median = total / 2, 0.0, None
    for i, n in enumerate(tot):
        if run + n >= half:
            width = 5 if i < 20 else 10
            median = 5 * i + width * (half - run) / n if n else 5 * i
            break
        run += n
    return {"total": total, "share_0_14": 100 * young / total, "share_65_plus": 100 * old / total,
            "old_age_dependency": 100 * old / work if work else None, "median_age": median}


# ----------------------------------------------------------------------------- reading the warehouse
# Indicator ids the what-if reads, and the input each one feeds.
SERIES = {"tfr": "tfr", "mean_age_childbearing": "mac", "sex_ratio_at_birth": "srb",
          "life_expectancy_male": "e0_male", "life_expectancy_female": "e0_female",
          "net_migration": "net_migration", "births": "births", "deaths": "deaths"}


def inputs_sql() -> str:
    """Everything the what-if needs for one country (parameter: entity_id), UN medium
    variant: the pyramids, the input paths, and total population to check against."""
    ids = ", ".join(f"'{i}'" for i in [*SERIES, "net_migration_rate", "pop_total", "pop_by_age_sex"])
    return f"""
        SELECT indicator_id, year(period_start) AS year, breakdown, value, status
        FROM series
        WHERE entity_id = ? AND source_id = 'un_wpp' AND freq = 'A' AND variant = 'central' AND indicator_id IN ({ids})
            AND (breakdown = '' OR breakdown LIKE '%|sex=male' OR breakdown LIKE '%|sex=female')"""


@dataclass
class Inputs:
    base_year: int
    base: Pyramid
    raw: dict[str, dict[int, float]]
    un: dict[int, Pyramid]
    un_totals: dict[int, float]
    last_year: int


def prepare(rows: list[tuple], base_year: int | None = None) -> Inputs | None:
    """Rows from inputs_sql in, the what-if's inputs out. The base year is the last
    year of the UN's estimates (the projection starts there) unless given; None when
    there is no pyramid to start from."""
    index = {g: i for i, g in enumerate(GROUPS)}
    pyr: dict[int, Pyramid] = {}
    raw: dict[str, dict[int, float]] = {k: {} for k in INPUTS + TARGETS}
    rate: dict[int, float] = {}
    totals: dict[int, float] = {}
    estimated: set[int] = set()
    for ind, year, breakdown, value, status in rows:
        if value is None:
            continue
        if ind == "pop_by_age_sex":
            parts = dict(p.split("=", 1) for p in breakdown.split("|") if "=" in p)
            i = index.get(parts.get("age", ""))
            if i is None:
                continue
            p = pyr.setdefault(year, Pyramid([0.0] * len(GROUPS), [0.0] * len(GROUPS)))
            getattr(p, parts["sex"])[i] = value
            if status == "E":
                estimated.add(year)
        elif ind == "pop_total":
            totals[year] = value
        elif ind == "net_migration_rate":
            rate[year] = value
        else:
            raw[SERIES[ind]][year] = value
    if not raw["net_migration"] and rate:  # per 1,000 people
        raw["net_migration"] = {y: r * totals[y] / 1000 for y, r in rate.items() if y in totals}
    if base_year is None:
        base_year = max(estimated, default=None) or max(pyr, default=None)
    if base_year is None or base_year not in pyr or not raw["tfr"] or not raw["e0_male"] or not raw["e0_female"]:
        return None
    last = max([y for y in totals if y > base_year] + [y for y in raw["tfr"] if y > base_year], default=base_year)
    return Inputs(base_year, pyr[base_year], raw, {y: p for y, p in pyr.items() if y > base_year}, totals, last)

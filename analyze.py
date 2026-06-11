#!/usr/bin/env python3
"""Veganblatt GSC analysis -> data.json. Stdlib only, read-only on source CSVs."""
import csv, json, re, os

SRC = os.path.expanduser("~/Data/veganblatt-gsc")
OUT = os.path.join(os.path.dirname(__file__), "data.json")


def read_csv(name):
    with open(os.path.join(SRC, name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


meta = json.load(open(os.path.join(SRC, "fetch_metadata.json")))
brand_terms = [t.lower() for t in meta["brand_terms"]]

# ---- daily series + 7-day rolling avg ----
daily = read_csv("gsc_daily.csv")
daily.sort(key=lambda r: r["date"])
dates = [r["date"] for r in daily]
clicks = [int(r["clicks"]) for r in daily]
impr = [int(r["impressions"]) for r in daily]


def rolling(xs, w=7):
    out = []
    for i in range(len(xs)):
        s = xs[max(0, i - w + 1): i + 1]
        out.append(round(sum(s) / len(s), 1))
    return out


# ---- monthly aggregates + growth ----
months = {}
for r in daily:
    m = r["date"][:7]
    months.setdefault(m, {"clicks": 0, "impr": 0, "days": 0})
    months[m]["clicks"] += int(r["clicks"])
    months[m]["impr"] += int(r["impressions"])
    months[m]["days"] += 1
month_list = sorted(months)
monthly = [{"month": m, **months[m]} for m in month_list]

# ---- top queries ----
queries = read_csv("gsc_top_queries.csv")
for q in queries:
    q["clicks"] = int(q["clicks"])
    q["impressions"] = int(q["impressions"])
    q["ctr"] = float(q["ctr"])
    q["position"] = float(q["position"])

total_clicks = sum(q["clicks"] for q in queries)
total_impr = sum(q["impressions"] for q in queries)
# overall weighted metrics
overall_ctr = total_clicks / total_impr if total_impr else 0
avg_position = sum(q["position"] * q["impressions"] for q in queries) / total_impr

# summary file (authoritative totals for the property)
summary = read_csv("gsc_summary.csv")[0]
site_clicks = int(summary["clicks"])
site_impr = int(summary["impressions"])

# ---- recompute brand vs non-brand ----
brand_re = re.compile("|".join(re.escape(t.replace("-", "")) for t in brand_terms))


def is_brand(q):
    s = q.lower().replace("-", "").replace(" ", "")
    return any(t.replace(" ", "").replace("-", "") in s for t in brand_terms)


brand_clicks = sum(q["clicks"] for q in queries if is_brand(q["query"]))
brand_impr = sum(q["impressions"] for q in queries if is_brand(q["query"]))

# ---- top 25 by clicks ----
top = sorted(queries, key=lambda q: q["clicks"], reverse=True)[:25]

# ---- opportunities: high impressions, weak CTR-for-position ----
# Expected CTR by position (rough industry curve) -> clicks left on table.
exp_ctr = {1: .27, 2: .15, 3: .10, 4: .07, 5: .05, 6: .04,
           7: .03, 8: .025, 9: .02, 10: .018}


def expected(pos):
    p = int(round(pos))
    if p < 1:
        p = 1
    if p > 10:
        return 0.012
    return exp_ctr.get(p, 0.012)


opps = []
for q in queries:
    if q["impressions"] >= 1500 and 2.5 <= q["position"] <= 20:
        potential = q["impressions"] * expected(q["position"])
        gap = potential - q["clicks"]
        if gap > 15:
            opps.append({**q, "potential_clicks": round(potential),
                         "clicks_gap": round(gap)})
opps.sort(key=lambda q: q["clicks_gap"], reverse=True)
opps = opps[:15]

# ---- theme clustering (simple keyword buckets) ----
themes = {
    "Brand (veganblatt)": brand_terms,
    "E-numbers / additives": ["e9", "e6", "e4", "e1", "zusatz", "inosinat", "dinatrium"],
    "Recipes / cooking": ["rezept", "kuchen", "muffin", "salat", "suppe", "laibchen",
                           "palatschinken", "gugelhupf", "creme", "teig", "brot"],
    "Drinks": ["red bull", "cola", "juice", "saft", "drink", "bull"],
    "\"Is X vegan?\" checks": ["vegan", "ist ", "sind "],
}
theme_counts = {k: {"clicks": 0, "queries": 0} for k in themes}
for q in queries:
    ql = q["query"].lower()
    for name, kws in themes.items():
        if any(kw in ql for kw in kws):
            theme_counts[name]["clicks"] += q["clicks"]
            theme_counts[name]["queries"] += 1
            break

first7 = round(sum(clicks[:7]) / 7, 1)
last7 = round(sum(clicks[-7:]) / 7, 1)

# ============================================================
# SEASONAL / HOLIDAY OVERLAY  (Austria + Germany, 2026 window)
# ============================================================
import datetime

# Public holidays in the window. c = countries affected.
HOLIDAYS = {
    "2026-04-03": ("Good Friday / Karfreitag", "DE"),       # public DE (not general AT)
    "2026-04-05": ("Easter Sunday / Ostersonntag", "AT+DE"),
    "2026-04-06": ("Easter Monday / Ostermontag", "AT+DE"),
    "2026-05-01": ("Labour Day / 1. Mai", "AT+DE"),
    "2026-05-14": ("Ascension / Christi Himmelfahrt (DE: Vatertag)", "AT+DE"),
    "2026-05-24": ("Pentecost Sunday / Pfingstsonntag", "AT+DE"),
    "2026-05-25": ("Whit Monday / Pfingstmontag", "AT+DE"),
    "2026-06-04": ("Corpus Christi / Fronleichnam", "AT+DE(cath.)"),
}
# School-vacation bands (approximate, varies by Bundesland) — for context shading.
SCHOOL_BANDS = [
    {"start": "2026-03-28", "end": "2026-04-07", "label": "Easter school holidays (AT/DE)"},
    {"start": "2026-05-26", "end": "2026-06-05", "label": "Pentecost week (BY/BW)"},
]

# centered 7-day baseline -> detrended ratio per day (isolates holiday/weekend effect from the 4.5x trend)
ratios, baselines = [], []
for i in range(len(clicks)):
    lo, hi = max(0, i - 3), min(len(clicks), i + 4)
    base = sum(clicks[lo:hi]) / (hi - lo)
    baselines.append(round(base, 1))
    ratios.append(round(clicks[i] / base, 3) if base else 1.0)

WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
dow = {w: [] for w in WD}
for i, d in enumerate(dates):
    dow[WD[datetime.date.fromisoformat(d).weekday()]].append(ratios[i])
dow_avg = [{"day": w, "ratio": round(sum(v) / len(v), 3)} for w, v in dow.items()]

# holiday impact: each holiday's detrended ratio (>1 = above local trend, <1 = suppressed)
hol_rows = []
for d, (name, c) in HOLIDAYS.items():
    if d in dates:
        i = dates.index(d)
        hol_rows.append({"date": d, "name": name, "country": c,
                         "clicks": clicks[i], "baseline": baselines[i],
                         "ratio": ratios[i], "delta_pct": round((ratios[i] - 1) * 100)})
hol_ratio_avg = round(sum(h["ratio"] for h in hol_rows) / len(hol_rows), 3)
nonhol_ratios = [ratios[i] for i, d in enumerate(dates) if d not in HOLIDAYS]
nonhol_avg = round(sum(nonhol_ratios) / len(nonhol_ratios), 3)

# seasonal query themes (spring food calendar) — clicks are 90-day totals
SEASON_Q = {
    "Easter (Oster*)": ["oster"],
    "Asparagus (Spargel)": ["spargel"],
    "Rhubarb / Strawberry": ["rhabarb", "erdbeer"],
    "Wild garlic (Bärlauch)": ["bärlauch", "baerlauch"],
    "Grilling / BBQ": ["grill"],
}
season_rows = []
for label, kws in SEASON_Q.items():
    c = i_ = n = 0
    for q in queries:
        ql = q["query"].lower()
        if any(k in ql for k in kws):
            c += q["clicks"]; i_ += q["impressions"]; n += 1
    season_rows.append({"theme": label, "clicks": c, "impressions": i_, "queries": n})
season_rows.sort(key=lambda r: r["clicks"], reverse=True)

seasonal = {
    "ratios": ratios, "baselines": baselines,
    "holidays": hol_rows, "school_bands": SCHOOL_BANDS,
    "holiday_ratio_avg": hol_ratio_avg, "nonholiday_ratio_avg": nonhol_avg,
    "dow": dow_avg, "season_queries": season_rows,
}

data = {
    "meta": meta,
    "site": {"clicks": site_clicks, "impressions": site_impr,
             "ctr": round(site_clicks / site_impr, 4)},
    "daily": {"dates": dates, "clicks": clicks, "impr": impr,
              "clicks_roll": rolling(clicks), "impr_roll": rolling(impr)},
    "monthly": monthly,
    "growth": {"first7": first7, "last7": last7,
               "factor": round(last7 / first7, 1)},
    "overall": {"ctr": round(overall_ctr, 4), "avg_position": round(avg_position, 1),
                "unique_queries": len(queries),
                "queries_clicks": total_clicks, "queries_impr": total_impr},
    "brand": {"brand_clicks": brand_clicks, "brand_impr": brand_impr,
              "nonbrand_clicks": total_clicks - brand_clicks,
              "nonbrand_impr": total_impr - brand_impr},
    "top": [{"query": q["query"], "clicks": q["clicks"],
             "impressions": q["impressions"], "ctr": q["ctr"],
             "position": q["position"]} for q in top],
    "opportunities": [{"query": q["query"], "clicks": q["clicks"],
                       "impressions": q["impressions"], "ctr": q["ctr"],
                       "position": q["position"],
                       "potential_clicks": q["potential_clicks"],
                       "clicks_gap": q["clicks_gap"]} for q in opps],
    "themes": theme_counts,
    "seasonal": seasonal,
}

json.dump(data, open(OUT, "w"), ensure_ascii=False, indent=2)
print("Wrote", OUT)
print(f"site clicks={site_clicks} impr={site_impr} ctr={data['site']['ctr']}")
print(f"growth {first7} -> {last7}/day = {data['growth']['factor']}x")
print("months:", [(m['month'], m['clicks']) for m in monthly])
print(f"brand clicks={brand_clicks} nonbrand={total_clicks-brand_clicks}")
print("top opp:", opps[0]['query'], "gap", opps[0]['clicks_gap'])

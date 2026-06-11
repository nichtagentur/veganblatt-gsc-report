#!/usr/bin/env python3
"""Scrape live Google SERPs (DataForSEO) for AI Overviews on 10 high-AIO-probability
veganblatt queries, detect sources + whether veganblatt is cited, model traffic impact."""
import os, csv, json, base64, urllib.request

LOGIN = os.environ["DATAFORSEO_LOGIN"]; PW = os.environ["DATAFORSEO_PASSWORD"]
SRC = os.path.expanduser("~/Data/veganblatt-gsc/gsc_top_queries.csv")
HERE = os.path.dirname(__file__)

# 10 queries with high AI-Overview probability — all informational/question intent,
# all from veganblatt's own high-impression query set (so impact ties to real data).
QUERIES = ["ist honig vegan", "ist senf vegan", "ist cola vegan", "ist kakaobutter vegan",
           "ist red bull vegan", "ist milchsäure vegan", "ist blätterteig vegan",
           "e920", "agavendicksaft gesund", "juice cleanse"]

# pull our own impressions/clicks for these queries
own = {}
for r in csv.DictReader(open(SRC, encoding="utf-8")):
    if r["query"] in QUERIES:
        own[r["query"]] = {"clicks": int(r["clicks"]), "impr": int(r["impressions"]),
                           "position": float(r["position"])}

AUTH = "Basic " + base64.b64encode(f"{LOGIN}:{PW}".encode()).decode()


def fetch(keyword):  # live endpoint accepts only ONE task per request
    body = json.dumps([{"keyword": keyword, "location_code": 2276,
                        "language_code": "de", "device": "desktop"}]).encode()
    req = urllib.request.Request(
        "https://api.dataforseo.com/v3/serp/google/organic/live/advanced", data=body,
        headers={"Authorization": AUTH, "Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req))
    return (r["tasks"][0].get("result") or [None])[0], r.get("cost", 0)


total_cost = 0
rows = []
for kw in QUERIES:
    res, cost = fetch(kw)
    total_cost += cost
    if not res:
        print("  (no result for", kw, ")"); continue
    items = res.get("items") or []
    aio = next((it for it in items if it["type"] == "ai_overview"), None)
    cited = False; sources = []
    if aio:
        refs = aio.get("references") or []
        # references can also live on nested item components
        for sub in (aio.get("items") or []):
            refs += (sub.get("references") or [])
        seen = set()
        for ref in refs:
            dom = (ref.get("domain") or "").lower()
            if dom and dom not in seen:
                seen.add(dom); sources.append(dom)
            if "veganblatt" in dom:
                cited = True
    # our organic position from live SERP (where we actually rank now)
    serp_pos = None
    for it in items:
        if it["type"] == "organic" and "veganblatt" in (it.get("domain") or ""):
            serp_pos = it.get("rank_absolute"); break
    o = own.get(kw, {"clicks": 0, "impr": 0, "position": None})
    rows.append({"query": kw, "aio": bool(aio), "cited": cited,
                 "sources": sources[:6], "n_sources": len(sources),
                 "serp_pos": serp_pos, "gsc_clicks": o["clicks"],
                 "gsc_impr": o["impr"], "gsc_pos": o["position"]})

# ---- traffic impact model ----
# These queries are mostly high-impression / near-zero-click — the classic signature of
# an AI Overview already absorbing the answer. So we model POTENTIAL clicks (what the
# ranking *should* earn) and how much an AIO puts at risk.
EXP_CTR = {1: .27, 2: .15, 3: .10, 4: .07, 5: .05, 6: .04, 7: .03, 8: .025, 9: .02, 10: .018}


def exp_ctr(pos):
    if not pos:
        return .012
    p = int(round(pos))
    return EXP_CTR.get(p, .012 if p > 10 else .27)


# Risk = share of POTENTIAL clicks an AIO removes (links demoted + answer given inline).
#   AIO present, veganblatt NOT cited -> 0.55 at risk    AIO present + cited -> 0.25    no AIO -> 0
RISK_NOT = 0.55; RISK_CITED = 0.25
for r in rows:
    pot = round(r["gsc_impr"] * exp_ctr(r["gsc_pos"]))
    r["potential_clicks"] = pot
    rf = (RISK_CITED if r["cited"] else RISK_NOT) if r["aio"] else 0.0
    r["risk_factor"] = rf
    r["clicks_at_risk"] = round(pot * rf)

aio_n = sum(1 for r in rows if r["aio"])
cited_n = sum(1 for r in rows if r["cited"])
risk_clicks = sum(r["clicks_at_risk"] for r in rows)
sample_potential = sum(r["potential_clicks"] for r in rows)
sample_impr = sum(r["gsc_impr"] for r in rows)

out = {"location": "Germany (de)", "queries_tested": len(rows),
       "aio_present": aio_n, "veganblatt_cited": cited_n, "api_cost_usd": round(total_cost, 4),
       "sample_potential_clicks": sample_potential, "sample_gsc_impr": sample_impr,
       "clicks_at_risk_per_90d": risk_clicks,
       "risk_factor_not_cited": RISK_NOT, "risk_factor_cited": RISK_CITED, "rows": rows}
json.dump(out, open(os.path.join(HERE, "aio.json"), "w"), ensure_ascii=False, indent=2)

print(f"\nAPI cost $ {total_cost:.4f}")
print(f"AI Overview present on {aio_n}/{len(rows)} queries; veganblatt cited in {cited_n}.")
for r in rows:
    tag = "AIO" if r["aio"] else "no "
    c = "CITED" if r["cited"] else ("---" if r["aio"] else "")
    print(f"  [{tag}] {r['query']:24} cited={c:5} serp#{str(r['serp_pos']):4} "
          f"impr={r['gsc_impr']:5} pot={r['potential_clicks']:3} at_risk={r['clicks_at_risk']:3}  "
          f"src:{','.join(r['sources'][:3])}")
print(f"\nPotential clicks at risk to AI Overviews (sample of {len(rows)}): "
      f"{risk_clicks} of {sample_potential}/90d "
      f"({round(risk_clicks/sample_potential*100) if sample_potential else 0}%)")

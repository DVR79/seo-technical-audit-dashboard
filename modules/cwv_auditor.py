"""
cwv_auditor.py
Fetch and parse Core Web Vitals data via Google PageSpeed Insights API v5.
No API key required for basic usage (400 req / 100 s per IP).
"""

import requests

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# ── Thresholds (Google's official Good / Needs Improvement / Poor) ────────────

THRESHOLDS = {
    "lcp":  {"good": 2500,  "needs": 4000,  "unit": "ms",  "label": "LCP"},
    "cls":  {"good": 0.1,   "needs": 0.25,  "unit": "",    "label": "CLS"},
    "inp":  {"good": 200,   "needs": 500,   "unit": "ms",  "label": "INP"},
    "fid":  {"good": 100,   "needs": 300,   "unit": "ms",  "label": "FID"},
    "fcp":  {"good": 1800,  "needs": 3000,  "unit": "ms",  "label": "FCP"},
    "ttfb": {"good": 800,   "needs": 1800,  "unit": "ms",  "label": "TTFB"},
    "tbt":  {"good": 200,   "needs": 600,   "unit": "ms",  "label": "TBT"},
    "si":   {"good": 3400,  "needs": 5800,  "unit": "ms",  "label": "Speed Index"},
}


def _rating(key, numeric_value):
    """Return 'good' | 'needs-improvement' | 'poor'."""
    if numeric_value is None:
        return "unknown"
    t = THRESHOLDS.get(key, {})
    if not t:
        return "unknown"
    if numeric_value <= t["good"]:
        return "good"
    if numeric_value <= t["needs"]:
        return "needs-improvement"
    return "poor"


def _color(rating):
    return {"good": "#10B981", "needs-improvement": "#F59E0B", "poor": "#EF4444"}.get(rating, "#94A3B8")


def fetch_psi(url, strategy="mobile", api_key=None):
    """
    Call PageSpeed Insights API.  Returns raw JSON dict or None on failure.
    strategy: "mobile" | "desktop"
    """
    params = {"url": url, "strategy": strategy, "locale": "en"}
    if api_key:
        params["key"] = api_key
    try:
        resp = requests.get(PSI_ENDPOINT, params=params, timeout=40)
        if resp.status_code != 200:
            return None, f"API returned HTTP {resp.status_code}"
        return resp.json(), None
    except requests.exceptions.Timeout:
        return None, "Request timed out (40 s). Try again."
    except Exception as exc:
        return None, str(exc)


def parse_psi(data):
    """
    Parse raw PSI JSON into a clean structured dict ready for display.
    """
    if not data:
        return {}

    lhr    = data.get("lighthouseResult", {})
    audits = lhr.get("audits", {})
    cats   = lhr.get("categories", {})

    # ── Performance score ────────────────────────────────────────────────────
    raw_score = cats.get("performance", {}).get("score")
    perf_score = int(round((raw_score or 0) * 100))

    # ── Lab metrics (Lighthouse) ─────────────────────────────────────────────
    def lab(audit_key, cwv_key):
        a = audits.get(audit_key, {})
        val = a.get("numericValue")
        return {
            "value":   val,
            "display": a.get("displayValue", "—"),
            "score":   a.get("score"),
            "rating":  _rating(cwv_key, val),
            "color":   _color(_rating(cwv_key, val)),
        }

    lab_metrics = {
        "lcp":  lab("largest-contentful-paint",  "lcp"),
        "cls":  lab("cumulative-layout-shift",   "cls"),
        "tbt":  lab("total-blocking-time",       "tbt"),
        "fcp":  lab("first-contentful-paint",    "fcp"),
        "si":   lab("speed-index",               "si"),
        "ttfb": lab("server-response-time",      "ttfb"),
    }

    # ── Field data (CrUX real-user data) ────────────────────────────────────
    le = data.get("loadingExperience", {})
    field_raw = le.get("metrics", {})

    def field(crux_key, cwv_key, divisor=1):
        m = field_raw.get(crux_key, {})
        p = m.get("percentile")
        val = (p / divisor) if p is not None else None
        cat = m.get("category", "")          # FAST / AVERAGE / SLOW
        rating_map = {"FAST": "good", "AVERAGE": "needs-improvement", "SLOW": "poor"}
        rating = rating_map.get(cat, "unknown")
        # Format display
        if val is None:
            disp = "No data"
        elif cwv_key == "cls":
            disp = f"{val:.3f}"
        else:
            disp = f"{val / 1000:.1f}s" if val >= 1000 else f"{int(val)} ms"
        return {
            "value":   val,
            "display": disp,
            "category": cat,
            "rating":  rating,
            "color":   _color(rating),
        }

    field_metrics = {
        "lcp":  field("LARGEST_CONTENTFUL_PAINT_MS",    "lcp"),
        "cls":  field("CUMULATIVE_LAYOUT_SHIFT_SCORE",  "cls", divisor=100),
        "inp":  field("INTERACTION_TO_NEXT_PAINT",      "inp"),
        "fcp":  field("FIRST_CONTENTFUL_PAINT_MS",      "fcp"),
    }

    # ── Opportunities (quick wins) ───────────────────────────────────────────
    opportunities = []
    for key, audit in audits.items():
        details = audit.get("details", {})
        score   = audit.get("score")
        if score is None or score >= 0.9:
            continue
        d_type = details.get("type", "")
        if d_type not in ("opportunity", "table", "list"):
            continue
        savings = details.get("overallSavingsMs") or details.get("overallSavingsBytes", 0) or 0
        opportunities.append({
            "id":          key,
            "title":       audit.get("title", key),
            "description": audit.get("description", ""),
            "savings_ms":  savings if d_type == "opportunity" else 0,
            "score":       score or 0,
        })
    opportunities.sort(key=lambda x: x["savings_ms"], reverse=True)

    # ── Diagnostics ──────────────────────────────────────────────────────────
    diagnostics = []
    for key, audit in audits.items():
        details = audit.get("details", {})
        score   = audit.get("score")
        if score is None or score >= 0.9:
            continue
        if details.get("type") == "diagnostic":
            diagnostics.append({
                "title":       audit.get("title", key),
                "description": audit.get("description", ""),
                "score":       score,
            })

    has_field = bool(field_raw)
    overall_category = le.get("overall_category", "")  # FAST / AVERAGE / SLOW

    return {
        "performance_score": perf_score,
        "lab":               lab_metrics,
        "field":             field_metrics,
        "has_field_data":    has_field,
        "overall_category":  overall_category,
        "opportunities":     opportunities[:10],
        "diagnostics":       diagnostics[:8],
        "strategy":          lhr.get("configSettings", {}).get("emulatedFormFactor", ""),
        "fetch_time":        lhr.get("fetchTime", ""),
    }

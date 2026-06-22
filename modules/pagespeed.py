"""
pagespeed.py
Google PageSpeed Insights API v5 client.
Returns real Lighthouse scores and CWV values.
No API key required for anonymous usage (100 req/day per IP).
Provide an API key for higher quotas (25 000 req/day).
"""

import requests

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PSI_TIMEOUT  = 60  # PSI itself fetches the page, so allow a generous timeout


def _score_to_status(score):
    """Convert a 0–1 Lighthouse score to pass/warning/fail/info."""
    if score is None:
        return "info"
    if score >= 0.9:
        return "pass"
    if score >= 0.5:
        return "warning"
    return "fail"


def _extract_metric(audits, key):
    a = audits.get(key, {})
    return {
        "value":        a.get("displayValue", "—"),
        "numericValue": a.get("numericValue"),
        "score":        a.get("score"),
        "status":       _score_to_status(a.get("score")),
    }


def fetch_pagespeed(url, strategy="mobile", api_key=None):
    """
    Call PageSpeed Insights API and return structured results.

    Parameters
    ----------
    url : str
        The page URL to analyze.
    strategy : str
        "mobile" or "desktop".
    api_key : str, optional
        Google API key. If None, auto-fetched from APIKeyManager (falls back to anonymous).

    Returns
    -------
    dict
        Keys: success, performance_score, accessibility_score, seo_score,
              best_practices_score, strategy, fcp, lcp, tbt, cls, si, ttfb, inp,
              opportunities, source.
        On failure: success=False, error=str.
    """
    if api_key is None:
        try:
            from modules.api_key_manager import APIKeyManager
            api_key = APIKeyManager.get("psi") or None
        except Exception:
            api_key = None

    params = {"url": url, "strategy": strategy, "category": ["performance", "accessibility", "seo", "best-practices"]}
    if api_key:
        params["key"] = api_key

    try:
        resp = requests.get(PSI_ENDPOINT, params=params, timeout=PSI_TIMEOUT)
        if resp.status_code == 429:
            return {
                "success": False,
                "error_code": 429,
                "error": (
                    "Rate limit reached for anonymous PSI requests. "
                    "Add a free Google API key to get 25,000 requests/day."
                ),
            }
        if resp.status_code == 400:
            return {"success": False, "error_code": 400,
                    "error": "Invalid URL or request rejected by PageSpeed Insights."}
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        return {"success": False, "error_code": 0,
                "error": "PageSpeed Insights request timed out (60s). Try again."}
    except Exception as e:
        return {"success": False, "error_code": 0, "error": str(e)}

    lhr    = data.get("lighthouseResult", {})
    cats   = lhr.get("categories", {})
    audits = lhr.get("audits", {})

    def _cat_score(key):
        raw = (cats.get(key, {}) or {}).get("score")
        return round(raw * 100) if raw is not None else None

    # Core metrics
    fcp  = _extract_metric(audits, "first-contentful-paint")
    lcp  = _extract_metric(audits, "largest-contentful-paint")
    tbt  = _extract_metric(audits, "total-blocking-time")
    cls  = _extract_metric(audits, "cumulative-layout-shift")
    si   = _extract_metric(audits, "speed-index")
    ttfb = _extract_metric(audits, "server-response-time")
    inp  = _extract_metric(audits, "interaction-to-next-paint")
    if not inp.get("value") or inp["value"] == "—":
        inp = _extract_metric(audits, "experimental-interaction-to-next-paint")
    if not inp.get("value") or inp["value"] == "—":
        inp = {"value": "Not available", "numericValue": None, "score": None, "status": "info"}

    # Opportunities (audits that could save time/bytes)
    opps = []
    for aid, a in audits.items():
        if (
            isinstance(a, dict)
            and a.get("details", {}).get("type") == "opportunity"
            and a.get("score") is not None
            and a.get("score") < 0.9
        ):
            opps.append({
                "id":           aid,
                "title":        a.get("title", ""),
                "description":  a.get("description", ""),
                "displayValue": a.get("displayValue", ""),
                "score":        a.get("score"),
            })
    opps.sort(key=lambda x: x["score"] or 0)

    # Image sizes — pulled from Lighthouse audits so they work even on CDNs
    # that block server-side requests (Cloudflare, Webflow, etc.)
    image_sizes = {}
    for _audit_key in ("network-requests",):
        for _item in (audits.get(_audit_key, {}).get("details", {}).get("items", []) or []):
            _url  = _item.get("url") or ""
            _size = _item.get("resourceSize") or _item.get("transferSize") or 0
            _type = (_item.get("resourceType") or "").lower()
            if _url and _size and _type == "image":
                image_sizes[_url] = int(_size)
    for _audit_key in ("uses-optimized-images", "uses-responsive-images",
                       "modern-image-formats", "efficiently-encode-images"):
        for _item in (audits.get(_audit_key, {}).get("details", {}).get("items", []) or []):
            _url  = _item.get("url") or ""
            _size = _item.get("totalBytes") or 0
            if _url and _size and _url not in image_sizes:
                image_sizes[_url] = int(_size)

    return {
        "success":             True,
        "source":              "PageSpeed Insights (Lighthouse)",
        "strategy":            strategy,
        "performance_score":   _cat_score("performance"),
        "accessibility_score": _cat_score("accessibility"),
        "seo_score":           _cat_score("seo"),
        "best_practices_score":_cat_score("best-practices"),
        "fcp":  fcp,
        "lcp":  lcp,
        "tbt":  tbt,
        "cls":  cls,
        "si":   si,
        "ttfb": ttfb,
        "inp":  inp,
        "opportunities":  opps[:10],
        "image_sizes":    image_sizes,
    }

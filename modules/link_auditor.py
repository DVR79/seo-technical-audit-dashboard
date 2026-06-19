"""Internal and external link discovery, classification, and validation."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

# Browser-like headers — avoids 403/999 bot blocks on LinkedIn, McKinsey, etc.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
TIMEOUT = 8

# Sites that always block HEAD/GET with non-standard codes — don't count as "broken"
KNOWN_BLOCKER_DOMAINS = {
    "linkedin.com", "www.linkedin.com",
    "twitter.com", "x.com", "www.twitter.com",
    "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com",
    "tiktok.com", "www.tiktok.com",
}

WEAK_ANCHORS = {
    "click here", "here", "read more", "learn more", "link",
    "this", "more", "see more", "see here", "visit", "go here",
    "continue", "source", "website", "url", "page", "article",
    "post", "check out", "check this", "find out", "more info",
    "click", "view", "details", "info", "example", "download",
}

# Domain type categories for external link classification
DOMAIN_CATEGORIES = {
    "social":    {"facebook.com","twitter.com","x.com","linkedin.com","instagram.com",
                  "youtube.com","tiktok.com","pinterest.com","reddit.com","snapchat.com"},
    "news":      {"bbc.com","cnn.com","nytimes.com","theguardian.com","reuters.com",
                  "apnews.com","bloomberg.com","forbes.com","wsj.com","techcrunch.com",
                  "businessinsider.com","entrepreneur.com"},
    "academic":  {"scholar.google.com","researchgate.net","academia.edu","jstor.org",
                  "pubmed.ncbi.nlm.nih.gov","springer.com","ieee.org","ssrn.com"},
    "government":{"gov","mil","europa.eu"},
    "reference": {"wikipedia.org","wikimedia.org","britannica.com","investopedia.com",
                  "merriam-webster.com"},
    "tech":      {"github.com","stackoverflow.com","developer.mozilla.org","docs.python.org",
                  "aws.amazon.com","cloud.google.com","docs.microsoft.com","npmjs.com"},
}


def get_base_domain(url):
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def get_full_domain(url):
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def categorize_domain(domain):
    """Return a category label for an external domain."""
    d = domain.lower().lstrip("www.")
    for cat, domains in DOMAIN_CATEGORIES.items():
        if d in domains:
            return cat.title()
        # TLD-based check for gov/mil
        if cat == "government":
            for tld in domains:
                if d.endswith("." + tld) or d == tld:
                    return "Government"
    return "Other"


def status_label(code):
    """Human-readable HTTP status label (Ahrefs-style)."""
    if code is None:
        return "Not Checked"
    if code == 0:
        return "Error"
    if code == 200:
        return "OK"
    if code in (301, 302, 303, 307, 308):
        return f"{code} Redirect"
    if code == 403:
        return "403 Forbidden"
    if code == 404:
        return "404 Not Found"
    if code == 410:
        return "410 Gone"
    if code == 429:
        return "429 Rate Limited"
    if code == 500:
        return "500 Server Error"
    if code == 503:
        return "503 Unavailable"
    if code == 999:
        return "999 Blocked"
    if 200 <= code < 300:
        return f"{code} OK"
    if 300 <= code < 400:
        return f"{code} Redirect"
    if 400 <= code < 500:
        return f"{code} Client Error"
    if 500 <= code < 600:
        return f"{code} Server Error"
    return str(code)


def link_health(code, domain=""):
    """
    Classify link health:
      ok       — 2xx
      redirect — 3xx
      blocked  — 999, 403 on known social/professional sites
      broken   — 4xx (not blocked), 5xx, 0 (connection error)
      unknown  — None (not validated)
    """
    if code is None:
        return "unknown"
    if code == 0:
        return "broken"
    base = get_base_domain(domain or "")
    if code == 999 or (code == 403 and base in KNOWN_BLOCKER_DOMAINS):
        return "blocked"
    if 200 <= code < 300:
        return "ok"
    if 300 <= code < 400:
        return "redirect"
    if code >= 400:
        return "broken"
    return "unknown"


def classify_link(href, base_url):
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    if href.startswith("//"):
        href = "https:" + href
    if not href.startswith("http"):
        return "internal"
    base_domain = get_base_domain(base_url)
    link_domain = get_base_domain(href)
    if link_domain == base_domain or link_domain.endswith("." + base_domain):
        return "internal"
    return "external"


def parse_link_tag(tag, base_url):
    href = tag.get("href", "").strip()
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None

    if href.startswith("//"):
        full_url = "https:" + href
    elif href.startswith("http"):
        full_url = href
    else:
        full_url = urljoin(base_url, href)

    rel_attr = tag.get("rel", [])
    if isinstance(rel_attr, str):
        rel_attr = rel_attr.split()
    rel = [r.lower() for r in rel_attr]

    target     = tag.get("target", "").lower()
    title_attr = tag.get("title", "").strip()
    anchor_raw = tag.get_text(strip=True)
    has_img    = bool(tag.find("img"))
    if not anchor_raw and has_img:
        img = tag.find("img")
        anchor_raw = img.get("alt", "").strip() if img else ""
        anchor_type = "image" if anchor_raw else "image-no-alt"
    else:
        anchor_type = "text" if anchor_raw else "empty"

    anchor = anchor_raw or ("[Image]" if has_img else "[No Text]")

    is_nofollow  = "nofollow"  in rel
    is_sponsored = "sponsored" in rel
    is_ugc       = "ugc"       in rel
    is_dofollow  = not (is_nofollow or is_sponsored)

    return {
        "url":              full_url,
        "href":             href,
        "anchor_text":      anchor[:150],
        "anchor_type":      anchor_type,      # text / image / image-no-alt / empty
        "title_attr":       title_attr,
        "rel":              " ".join(rel) if rel else "dofollow",
        "rel_list":         rel,
        "target":           target,
        "is_nofollow":      is_nofollow,
        "is_sponsored":     is_sponsored,
        "is_ugc":           is_ugc,
        "is_dofollow":      is_dofollow,
        "opens_new_tab":    target == "_blank",
        "has_noopener":     "noopener"   in rel,
        "has_noreferrer":   "noreferrer" in rel,
        "is_weak_anchor":   anchor.lower().strip() in WEAK_ANCHORS,
        "status_code":      None,
        "status_label":     "Not Checked",
        "health":           "unknown",
        "is_broken":        None,
        "is_redirect":      None,
        "final_url":        None,
    }


def validate_url(url):
    """HTTP-check a URL. Returns status, health, label."""
    domain = get_full_domain(url)
    base   = get_base_domain(url)

    if base in KNOWN_BLOCKER_DOMAINS:
        return {
            "url": url,
            "status_code": 999,
            "status_label": "999 Blocked",
            "health": "blocked",
            "is_broken": False,
            "is_redirect": False,
            "final_url": url,
            "redirect_count": 0,
            "note": "Skipped — site blocks automated requests",
        }

    try:
        resp = requests.head(
            url, headers=HEADERS, timeout=TIMEOUT,
            allow_redirects=True, verify=False
        )
        code = resp.status_code

        if code in (405, 501):
            resp = requests.get(
                url, headers=HEADERS, timeout=TIMEOUT,
                allow_redirects=True, verify=False,
                stream=True
            )
            resp.close()
            code = resp.status_code

        h     = link_health(code, url)
        label = status_label(code)

        return {
            "url":            url,
            "status_code":    code,
            "status_label":   label,
            "health":         h,
            "is_broken":      h == "broken",
            "is_redirect":    h == "redirect",
            "final_url":      resp.url,
            "redirect_count": len(resp.history),
        }

    except requests.exceptions.Timeout:
        return {"url": url, "status_code": 0, "status_label": "Timeout",
                "health": "broken", "is_broken": True, "is_redirect": False}
    except requests.exceptions.SSLError:
        return {"url": url, "status_code": 0, "status_label": "SSL Error",
                "health": "broken", "is_broken": True, "is_redirect": False}
    except requests.exceptions.ConnectionError:
        return {"url": url, "status_code": 0, "status_label": "Connection Error",
                "health": "broken", "is_broken": True, "is_redirect": False}
    except Exception as e:
        return {"url": url, "status_code": 0, "status_label": f"Error: {str(e)[:40]}",
                "health": "broken", "is_broken": True, "is_redirect": False}


def validate_urls_bulk(urls, max_workers=12):
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(validate_url, url): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception:
                results[url] = {"url": url, "status_code": 0, "status_label": "Error",
                                "health": "broken", "is_broken": True}
    return results


def audit_links(soup, base_url, validate=False):
    internal, external = [], []

    for tag in soup.find_all("a", href=True):
        link_data = parse_link_tag(tag, base_url)
        if not link_data:
            continue
        kind = classify_link(link_data["href"], base_url)
        if kind == "internal":
            internal.append(link_data)
        elif kind == "external":
            external.append(link_data)

    if validate:
        all_urls = list({l["url"] for l in internal + external})
        validation = validate_urls_bulk(all_urls)
        for link in internal + external:
            v = validation.get(link["url"], {})
            link["status_code"]  = v.get("status_code")
            link["status_label"] = v.get("status_label", "Not Checked")
            link["health"]       = v.get("health", "unknown")
            link["is_broken"]    = v.get("is_broken")
            link["is_redirect"]  = v.get("is_redirect")
            link["final_url"]    = v.get("final_url")

    return {
        "internal": _summarize_internal(internal),
        "external": _summarize_external(external),
    }


# ── Anchor text analysis ──────────────────────────────────────────────────

def analyze_anchor_text(links):
    """
    Returns a detailed anchor text report across a list of link dicts.
    Works for both internal and external link sets.
    """
    total = len(links)
    if total == 0:
        return {"total": 0, "distribution": [], "issues": [], "opportunities": []}

    anchors = [l.get("anchor_text","").strip() for l in links]
    counter = Counter(a.lower() for a in anchors if a)

    distribution = [
        {
            "anchor": text,
            "count": cnt,
            "pct": round(cnt / total * 100, 1),
            "is_weak": text in WEAK_ANCHORS,
        }
        for text, cnt in counter.most_common(50)
    ]

    exact_match_threshold = 0.30  # >30% same anchor = over-optimised
    issues       = []
    opportunities= []

    top_anchor, top_cnt = (counter.most_common(1)[0] if counter else ("", 0))
    if top_cnt / total > exact_match_threshold:
        issues.append({
            "type": "over_optimized",
            "anchor": top_anchor,
            "pct": round(top_cnt / total * 100, 1),
            "message": f'"{top_anchor}" used on {round(top_cnt/total*100,1)}% of links — may look spammy to Google.',
            "recommendation": "Vary your anchor text with natural phrases, branded terms, and partial-match keywords.",
        })

    weak_links  = [l for l in links if l.get("is_weak_anchor")]
    img_no_alt  = [l for l in links if l.get("anchor_type") == "image-no-alt"]
    empty_links = [l for l in links if l.get("anchor_type") == "empty"]

    if weak_links:
        opportunities.append({
            "type": "weak_anchor",
            "count": len(weak_links),
            "message": f"{len(weak_links)} link(s) use generic anchor text ('click here', 'read more', etc.).",
            "recommendation": "Replace with descriptive, keyword-rich anchor text that signals the target page topic.",
            "links": [l.get("url","") for l in weak_links[:10]],
        })
    if img_no_alt:
        opportunities.append({
            "type": "image_no_alt",
            "count": len(img_no_alt),
            "message": f"{len(img_no_alt)} image link(s) have no alt text — search engines cannot read the anchor.",
            "recommendation": "Add descriptive alt attributes to all linked images.",
            "links": [l.get("url","") for l in img_no_alt[:10]],
        })
    if empty_links:
        opportunities.append({
            "type": "empty_anchor",
            "count": len(empty_links),
            "message": f"{len(empty_links)} link(s) have completely empty anchor text.",
            "recommendation": "Add meaningful anchor text or remove the empty link tag.",
            "links": [l.get("url","") for l in empty_links[:10]],
        })

    unique_anchors = len(counter)
    if unique_anchors > 0:
        diversity = round(unique_anchors / total * 100, 1)
        opportunities.append({
            "type": "diversity",
            "count": unique_anchors,
            "message": f"Anchor text diversity: {unique_anchors} unique phrases across {total} links ({diversity}% unique).",
            "recommendation": (
                "Good diversity — keep varying anchor text."
                if diversity > 60 else
                "Low diversity — try using more unique, contextually relevant phrases per link."
            ),
            "links": [],
        })

    return {
        "total":        total,
        "unique":       unique_anchors,
        "weak_count":   len(weak_links),
        "image_no_alt": len(img_no_alt),
        "empty_count":  len(empty_links),
        "distribution": distribution,
        "issues":       issues,
        "opportunities":opportunities,
    }


# ── Internal link opportunity detection ───────────────────────────────────

def get_internal_link_opportunities(results_list):
    """
    Analyse audit results to find internal linking gaps and suggestions.
    Returns a list of opportunity dicts.
    """
    opportunities = []

    # Pages with few or no internal links pointing TO them
    page_urls = {r.get("url","") for r in results_list}

    # Count inbound internal links per page
    inbound = {url: 0 for url in page_urls}
    for r in results_list:
        for lk in r.get("internal_links", {}).get("links", []):
            target = lk.get("url","")
            if target in inbound:
                inbound[target] += 1

    orphan_pages = [url for url, cnt in inbound.items() if cnt == 0]
    low_link_pages = [url for url, cnt in inbound.items() if 0 < cnt < 3]

    if orphan_pages:
        opportunities.append({
            "type": "orphan_pages",
            "severity": "High",
            "count": len(orphan_pages),
            "title": "Orphan Pages — No Internal Links Pointing To Them",
            "message": f"{len(orphan_pages)} page(s) have zero internal inbound links from other audited pages.",
            "recommendation": "Link to these pages from relevant content to help search engines discover and crawl them.",
            "pages": orphan_pages[:10],
        })

    if low_link_pages:
        opportunities.append({
            "type": "low_inbound",
            "severity": "Medium",
            "count": len(low_link_pages),
            "title": "Under-Linked Pages — Fewer Than 3 Internal Inbound Links",
            "message": f"{len(low_link_pages)} page(s) have fewer than 3 internal links pointing to them.",
            "recommendation": "Increase internal links to these pages to distribute link equity and improve crawl priority.",
            "pages": low_link_pages[:10],
        })

    # Pages with very few outbound internal links
    for r in results_list:
        il = r.get("internal_links", {})
        total_out = il.get("total_links", 0)
        word_count = r.get("content", {}).get("word_count", 0)
        if word_count > 500 and total_out < 3:
            opportunities.append({
                "type": "low_outbound",
                "severity": "Medium",
                "count": 1,
                "title": "Content-Rich Page With Few Outgoing Internal Links",
                "message": f"{r.get('url','')} has {word_count:,} words but only {total_out} internal link(s).",
                "recommendation": "Add relevant internal links to distribute link equity and guide readers to related content.",
                "pages": [r.get("url","")],
            })

    # Broken internal links by target page
    broken_targets = {}
    for r in results_list:
        for lk in r.get("internal_links", {}).get("links", []):
            if lk.get("is_broken"):
                t = lk.get("url","")
                if t not in broken_targets:
                    broken_targets[t] = []
                broken_targets[t].append(r.get("url",""))

    if broken_targets:
        for target, sources in list(broken_targets.items())[:10]:
            opportunities.append({
                "type": "broken_target",
                "severity": "Critical",
                "count": len(sources),
                "title": "Broken Internal Link Target",
                "message": f"'{target}' is broken — linked from {len(sources)} page(s).",
                "recommendation": "Fix or redirect the broken target URL, or update all links pointing to it.",
                "pages": sources[:5],
            })

    # Weak anchor text opportunities per page
    for r in results_list:
        weak = r.get("internal_links", {}).get("weak_anchor_count", 0)
        if weak > 0:
            opportunities.append({
                "type": "weak_anchors_page",
                "severity": "Low",
                "count": weak,
                "title": f"Weak Internal Anchor Text ({weak} links)",
                "message": f"{r.get('url','')} has {weak} internal link(s) with generic anchor text.",
                "recommendation": "Use descriptive, keyword-rich anchor text on internal links to signal relevance to search engines.",
                "pages": [r.get("url","")],
            })

    return opportunities


# ── Summarise helpers ─────────────────────────────────────────────────────

def _summarize_internal(links):
    issues = []
    unique    = list({l["url"] for l in links})
    dofollow  = sum(1 for l in links if l["is_dofollow"])
    nofollow  = sum(1 for l in links if l["is_nofollow"])
    broken    = sum(1 for l in links if l.get("is_broken") is True)
    redirect  = sum(1 for l in links if l.get("is_redirect") is True)
    new_tab   = sum(1 for l in links if l["opens_new_tab"])
    same_tab  = len(links) - new_tab
    miss_no   = sum(1 for l in links if l["opens_new_tab"] and not l["has_noopener"])
    weak_a    = sum(1 for l in links if l.get("is_weak_anchor"))
    img_links = sum(1 for l in links if "image" in l.get("anchor_type",""))
    empty_a   = sum(1 for l in links if l.get("anchor_type") == "empty")

    if len(links) == 0:
        issues.append({
            "issue": "No Internal Links Found", "category": "Internal Links",
            "severity": "Warning", "impact_score": 7, "effort": "Medium",
            "recommendation": "Add internal links to improve crawlability and distribute link equity.",
        })
    elif len(links) < 3:
        issues.append({
            "issue": f"Very Few Internal Links ({len(links)})", "category": "Internal Links",
            "severity": "Warning", "impact_score": 5, "effort": "Medium",
            "recommendation": "Add more internal links to connect related content and improve navigation.",
        })
    if broken > 0:
        issues.append({
            "issue": f"Broken Internal Links ({broken})", "category": "Internal Links",
            "severity": "Critical", "impact_score": 9, "effort": "Low",
            "recommendation": "Fix or remove all broken internal links immediately — they harm user experience and crawlability.",
        })
    if redirect > 0:
        issues.append({
            "issue": f"Redirecting Internal Links ({redirect})", "category": "Internal Links",
            "severity": "Warning", "impact_score": 5, "effort": "Low",
            "recommendation": "Update internal links to point directly to final destination URLs.",
        })
    if miss_no > 0:
        issues.append({
            "issue": f"Internal Links Opening in New Tab Without rel='noopener' ({miss_no})", "category": "Internal Links",
            "severity": "Medium", "impact_score": 4, "effort": "Low",
            "recommendation": "Add rel='noopener noreferrer' to all internal links that open in new tabs.",
        })
    if weak_a > 0:
        issues.append({
            "issue": f"Weak Anchor Text on {weak_a} Internal Link(s)", "category": "Internal Links",
            "severity": "Low", "impact_score": 4, "effort": "Low",
            "recommendation": "Replace generic anchor text ('click here', 'read more') with descriptive keyword-rich phrases.",
        })

    return {
        "total_links":            len(links),
        "unique_links":           len(unique),
        "dofollow_count":         dofollow,
        "nofollow_count":         nofollow,
        "broken_count":           broken,
        "redirect_count":         redirect,
        "new_tab_count":          new_tab,
        "same_tab_count":         same_tab,
        "missing_noopener_count": miss_no,
        "weak_anchor_count":      weak_a,
        "image_link_count":       img_links,
        "empty_anchor_count":     empty_a,
        "links":                  links[:200],
        "issues":                 issues,
    }


def _summarize_external(links):
    issues = []
    unique_domains  = list({get_base_domain(l["url"]) for l in links})
    dofollow        = sum(1 for l in links if l["is_dofollow"])
    nofollow        = sum(1 for l in links if l["is_nofollow"])
    sponsored       = sum(1 for l in links if l["is_sponsored"])
    ugc             = sum(1 for l in links if l["is_ugc"])
    broken          = sum(1 for l in links if l.get("is_broken") is True)
    blocked         = sum(1 for l in links if l.get("health") == "blocked")
    redirect        = sum(1 for l in links if l.get("is_redirect") is True)
    new_tab         = sum(1 for l in links if l["opens_new_tab"])
    same_tab        = len(links) - new_tab
    miss_noop       = sum(1 for l in links if l["opens_new_tab"] and not l["has_noopener"])
    miss_noref      = sum(1 for l in links if l["opens_new_tab"] and not l["has_noreferrer"])
    weak_a          = sum(1 for l in links if l.get("is_weak_anchor"))
    img_links       = sum(1 for l in links if "image" in l.get("anchor_type",""))
    no_security     = sum(1 for l in links if l["opens_new_tab"] and not (l["has_noopener"] and l["has_noreferrer"]))

    if broken > 0:
        issues.append({
            "issue": f"Broken External Links ({broken})", "category": "External Links",
            "severity": "High", "impact_score": 8, "effort": "Low",
            "recommendation": "Replace or remove all broken external links — they harm user experience and trust signals.",
        })
    if miss_noop > 0:
        issues.append({
            "issue": f"External Links Missing rel='noopener' ({miss_noop})", "category": "External Links",
            "severity": "Medium", "impact_score": 5, "effort": "Low",
            "recommendation": "Add rel='noopener noreferrer' to all external links that open in new tabs (security best practice).",
        })
    if same_tab > 0:
        issues.append({
            "issue": f"{same_tab} External Link(s) Open in Same Tab", "category": "External Links",
            "severity": "Low", "impact_score": 3, "effort": "Low",
            "recommendation": "Consider opening external links in a new tab (target='_blank' + noopener) to retain visitors.",
        })
    if dofollow > 20:
        issues.append({
            "issue": f"High Dofollow External Link Count ({dofollow})", "category": "External Links",
            "severity": "Warning", "impact_score": 4, "effort": "Medium",
            "recommendation": "Review excessive external dofollow links — add rel='nofollow' for commercial or low-authority destinations.",
        })
    if weak_a > 0:
        issues.append({
            "issue": f"Weak Anchor Text on {weak_a} External Link(s)", "category": "External Links",
            "severity": "Low", "impact_score": 3, "effort": "Low",
            "recommendation": "Use descriptive anchor text for external links rather than generic phrases.",
        })

    return {
        "total_links":              len(links),
        "unique_domains":           len(unique_domains),
        "domains":                  unique_domains[:30],
        "dofollow_count":           dofollow,
        "nofollow_count":           nofollow,
        "sponsored_count":          sponsored,
        "ugc_count":                ugc,
        "broken_count":             broken,
        "blocked_count":            blocked,
        "redirect_count":           redirect,
        "new_tab_count":            new_tab,
        "same_tab_count":           same_tab,
        "missing_noopener_count":   miss_noop,
        "missing_noreferrer_count": miss_noref,
        "no_security_count":        no_security,
        "weak_anchor_count":        weak_a,
        "image_link_count":         img_links,
        "links":                    links[:200],
        "issues":                   issues,
    }

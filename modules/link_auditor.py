"""Internal and external link discovery, classification, and validation."""

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
    "continue", "source", "website", "url",
}


def get_base_domain(url):
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        # Strip www. prefix for domain comparison
        return netloc.lstrip("www.") if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def get_full_domain(url):
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


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


def status_badge_color(health):
    return {
        "ok":       "#10B981",
        "redirect": "#F59E0B",
        "blocked":  "#8B5CF6",
        "broken":   "#EF4444",
        "unknown":  "#94A3B8",
    }.get(health, "#94A3B8")


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
    anchor_raw = tag.get_text(strip=True)
    anchor     = anchor_raw or "[Image Link]" if tag.find("img") else anchor_raw or "[No Anchor]"

    is_nofollow  = "nofollow"  in rel
    is_sponsored = "sponsored" in rel
    is_ugc       = "ugc"       in rel
    is_dofollow  = not (is_nofollow or is_sponsored)

    return {
        "url":           full_url,
        "href":          href,
        "anchor_text":   anchor[:120],
        "rel":           " ".join(rel) if rel else "dofollow",
        "rel_list":      rel,
        "target":        target,
        "is_nofollow":   is_nofollow,
        "is_sponsored":  is_sponsored,
        "is_ugc":        is_ugc,
        "is_dofollow":   is_dofollow,
        "opens_new_tab": target == "_blank",
        "has_noopener":  "noopener"  in rel,
        "has_noreferrer":"noreferrer" in rel,
        "is_weak_anchor": anchor.lower().strip() in WEAK_ANCHORS,
        "status_code":   None,
        "status_label":  "Not Checked",
        "health":        "unknown",
        "is_broken":     None,
        "is_redirect":   None,
        "final_url":     None,
    }


def validate_url(url):
    """HTTP-check a URL. Returns status, health, label."""
    domain = get_full_domain(url)
    base   = get_base_domain(url)

    # If domain is known to block bots, skip check and mark as blocked
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
        # Try HEAD first (fast)
        resp = requests.head(
            url, headers=HEADERS, timeout=TIMEOUT,
            allow_redirects=True, verify=False
        )
        code = resp.status_code

        # Some servers return 405 for HEAD — retry with GET
        if code in (405, 501):
            resp = requests.get(
                url, headers=HEADERS, timeout=TIMEOUT,
                allow_redirects=True, verify=False,
                stream=True  # don't download body
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
        return {
            "url": url, "status_code": 0,
            "status_label": "Timeout",
            "health": "broken", "is_broken": True, "is_redirect": False,
        }
    except requests.exceptions.SSLError:
        return {
            "url": url, "status_code": 0,
            "status_label": "SSL Error",
            "health": "broken", "is_broken": True, "is_redirect": False,
        }
    except requests.exceptions.ConnectionError:
        return {
            "url": url, "status_code": 0,
            "status_label": "Connection Error",
            "health": "broken", "is_broken": True, "is_redirect": False,
        }
    except Exception as e:
        return {
            "url": url, "status_code": 0,
            "status_label": f"Error: {str(e)[:40]}",
            "health": "broken", "is_broken": True, "is_redirect": False,
        }


def validate_urls_bulk(urls, max_workers=12):
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(validate_url, url): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception as e:
                results[url] = {
                    "url": url, "status_code": 0,
                    "status_label": "Error",
                    "health": "broken", "is_broken": True,
                }
    return results


def audit_links(soup, base_url, validate=False):
    internal, external = [], []
    seen_urls = set()

    for tag in soup.find_all("a", href=True):
        link_data = parse_link_tag(tag, base_url)
        if not link_data:
            continue
        kind = classify_link(link_data["href"], base_url)
        url  = link_data["url"]

        if kind == "internal":
            internal.append(link_data)
        elif kind == "external":
            external.append(link_data)
            seen_urls.add(url)

    if validate:
        # Validate all unique external URLs + internal
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


def _summarize_internal(links):
    issues = []
    unique  = list({l["url"] for l in links})
    dofollow= sum(1 for l in links if l["is_dofollow"])
    nofollow= sum(1 for l in links if l["is_nofollow"])
    broken  = sum(1 for l in links if l.get("is_broken") is True)
    redirect= sum(1 for l in links if l.get("is_redirect") is True)
    new_tab = sum(1 for l in links if l["opens_new_tab"])
    miss_no = sum(1 for l in links if l["opens_new_tab"] and not l["has_noopener"])
    weak_a  = sum(1 for l in links if l.get("is_weak_anchor"))

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
            "recommendation": "Update internal links to point directly to final destination URLs, avoiding unnecessary redirects.",
        })
    if miss_no > 0:
        issues.append({
            "issue": f"Internal Links Opening in New Tab Without rel='noopener' ({miss_no})", "category": "Internal Links",
            "severity": "Medium", "impact_score": 4, "effort": "Low",
            "recommendation": "Add rel='noopener noreferrer' to all internal links that open in new tabs (security best practice).",
        })
    if weak_a > 0:
        issues.append({
            "issue": f"Weak Anchor Text on {weak_a} Internal Link(s)", "category": "Internal Links",
            "severity": "Low", "impact_score": 4, "effort": "Low",
            "recommendation": "Replace generic anchor text ('click here', 'read more') with descriptive keyword-rich phrases.",
        })

    return {
        "total_links":           len(links),
        "unique_links":          len(unique),
        "dofollow_count":        dofollow,
        "nofollow_count":        nofollow,
        "broken_count":          broken,
        "redirect_count":        redirect,
        "new_tab_count":         new_tab,
        "same_tab_count":        len(links) - new_tab,
        "missing_noopener_count":miss_no,
        "weak_anchor_count":     weak_a,
        "links":                 links[:200],
        "issues":                issues,
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
    same_tab        = sum(1 for l in links if not l["opens_new_tab"])
    miss_noop       = sum(1 for l in links if l["opens_new_tab"] and not l["has_noopener"])
    miss_noref      = sum(1 for l in links if l["opens_new_tab"] and not l["has_noreferrer"])
    weak_a          = sum(1 for l in links if l.get("is_weak_anchor"))

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
        "total_links":             len(links),
        "unique_domains":          len(unique_domains),
        "domains":                 unique_domains[:30],
        "dofollow_count":          dofollow,
        "nofollow_count":          nofollow,
        "sponsored_count":         sponsored,
        "ugc_count":               ugc,
        "broken_count":            broken,
        "blocked_count":           blocked,
        "redirect_count":          redirect,
        "new_tab_count":           len(links) - same_tab,
        "same_tab_count":          same_tab,
        "missing_noopener_count":  miss_noop,
        "missing_noreferrer_count":miss_noref,
        "weak_anchor_count":       weak_a,
        "links":                   links[:200],
        "issues":                  issues,
    }

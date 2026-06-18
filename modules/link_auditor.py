"""Internal and external link discovery, classification, and validation."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SEOLinkBot/1.0)"}
TIMEOUT = 10


def get_base_domain(url):
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


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

    full_url = href if href.startswith("http") else urljoin(base_url, href)
    if href.startswith("//"):
        full_url = "https:" + href

    rel_attr = tag.get("rel", [])
    if isinstance(rel_attr, str):
        rel_attr = rel_attr.split()
    rel = [r.lower() for r in rel_attr]

    target = tag.get("target", "").lower()
    anchor = tag.get_text(strip=True)

    return {
        "url": full_url,
        "href": href,
        "anchor_text": anchor or "[No anchor text]",
        "rel": rel,
        "target": target,
        "is_nofollow": "nofollow" in rel,
        "is_sponsored": "sponsored" in rel,
        "is_ugc": "ugc" in rel,
        "is_dofollow": "nofollow" not in rel and "sponsored" not in rel,
        "opens_new_tab": target == "_blank",
        "has_noopener": "noopener" in rel,
        "has_noreferrer": "noreferrer" in rel,
        "status_code": None,
        "is_broken": None,
        "is_redirect": None,
    }


def validate_url(url):
    try:
        resp = requests.head(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, verify=False)
        if resp.status_code == 405:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, verify=False)
        return {
            "url": url,
            "status_code": resp.status_code,
            "is_broken": resp.status_code >= 400,
            "is_redirect": 300 <= resp.status_code < 400,
            "final_url": resp.url,
            "redirect_count": len(resp.history),
        }
    except Exception as e:
        return {
            "url": url,
            "status_code": 0,
            "is_broken": True,
            "is_redirect": False,
            "error": str(e),
        }


def validate_urls_bulk(urls, max_workers=15):
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(validate_url, url): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception as e:
                results[url] = {"url": url, "status_code": 0, "is_broken": True, "error": str(e)}
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
            link["status_code"] = v.get("status_code")
            link["is_broken"] = v.get("is_broken")
            link["is_redirect"] = v.get("is_redirect")

    return {
        "internal": _summarize_internal(internal),
        "external": _summarize_external(external),
    }


def _summarize_internal(links):
    issues = []
    unique = list({l["url"] for l in links})
    dofollow = sum(1 for l in links if l["is_dofollow"])
    nofollow = sum(1 for l in links if l["is_nofollow"])
    broken = sum(1 for l in links if l.get("is_broken"))
    redirecting = sum(1 for l in links if l.get("is_redirect"))
    new_tab = sum(1 for l in links if l["opens_new_tab"])
    missing_noopener = sum(1 for l in links if l["opens_new_tab"] and not l["has_noopener"])

    if len(links) == 0:
        issues.append({
            "issue": "No Internal Links Found",
            "category": "Internal Links",
            "severity": "Warning",
            "recommendation": "Add internal links to improve crawlability and distribute link equity.",
        })
    elif len(links) < 3:
        issues.append({
            "issue": f"Very Few Internal Links ({len(links)})",
            "category": "Internal Links",
            "severity": "Warning",
            "recommendation": "Add more internal links to connect related content and improve navigation.",
        })

    if broken > 0:
        issues.append({
            "issue": f"Broken Internal Links ({broken})",
            "category": "Internal Links",
            "severity": "Critical",
            "recommendation": "Fix or remove all broken internal links immediately.",
        })
    if redirecting > 0:
        issues.append({
            "issue": f"Redirecting Internal Links ({redirecting})",
            "category": "Internal Links",
            "severity": "Warning",
            "recommendation": "Update internal links to point directly to final destination URLs.",
        })
    if missing_noopener > 0:
        issues.append({
            "issue": f"Internal Links Missing rel='noopener' ({missing_noopener})",
            "category": "Internal Links",
            "severity": "Medium",
            "recommendation": "Add rel='noopener noreferrer' to all internal links that open in new tabs.",
        })

    weak_anchor = sum(1 for l in links if l["anchor_text"].lower() in
                      ["click here", "here", "read more", "learn more", "link", "this"])
    if weak_anchor > 0:
        issues.append({
            "issue": f"Weak Anchor Text on {weak_anchor} Internal Link(s)",
            "category": "Internal Links",
            "severity": "Low",
            "recommendation": "Replace generic anchor text ('click here', 'read more') with descriptive keywords.",
        })

    return {
        "total_links": len(links),
        "unique_links": len(unique),
        "dofollow_count": dofollow,
        "nofollow_count": nofollow,
        "broken_count": broken,
        "redirect_count": redirecting,
        "new_tab_count": new_tab,
        "same_tab_count": len(links) - new_tab,
        "missing_noopener_count": missing_noopener,
        "weak_anchor_count": weak_anchor,
        "links": links[:60],
        "issues": issues,
    }


def _summarize_external(links):
    issues = []
    unique_domains = list({get_base_domain(l["url"]) for l in links})
    dofollow = sum(1 for l in links if l["is_dofollow"])
    nofollow = sum(1 for l in links if l["is_nofollow"])
    sponsored = sum(1 for l in links if l["is_sponsored"])
    ugc = sum(1 for l in links if l["is_ugc"])
    broken = sum(1 for l in links if l.get("is_broken"))
    same_tab = sum(1 for l in links if not l["opens_new_tab"])
    missing_noopener = sum(1 for l in links if l["opens_new_tab"] and not l["has_noopener"])
    missing_noreferrer = sum(1 for l in links if l["opens_new_tab"] and not l["has_noreferrer"])

    if broken > 0:
        issues.append({
            "issue": f"Broken External Links ({broken})",
            "category": "External Links",
            "severity": "High",
            "recommendation": "Replace or remove all broken external links.",
        })
    if missing_noopener > 0:
        issues.append({
            "issue": f"External Links Missing rel='noopener' ({missing_noopener})",
            "category": "External Links",
            "severity": "Medium",
            "recommendation": "Add rel='noopener noreferrer' to all external links opening in new tabs.",
        })
    if same_tab > 0:
        issues.append({
            "issue": f"External Links Opening in Same Tab ({same_tab})",
            "category": "External Links",
            "severity": "Low",
            "recommendation": "Open external links in a new tab (target='_blank') to retain users.",
        })
    if dofollow > 20:
        issues.append({
            "issue": f"High Dofollow External Link Count ({dofollow})",
            "category": "External Links",
            "severity": "Warning",
            "recommendation": "Review excessive external dofollow links; consider nofollow for commercial or low-authority links.",
        })

    return {
        "total_links": len(links),
        "unique_domains": len(unique_domains),
        "domains": unique_domains[:20],
        "dofollow_count": dofollow,
        "nofollow_count": nofollow,
        "sponsored_count": sponsored,
        "ugc_count": ugc,
        "broken_count": broken,
        "new_tab_count": len(links) - same_tab,
        "same_tab_count": same_tab,
        "missing_noopener_count": missing_noopener,
        "missing_noreferrer_count": missing_noreferrer,
        "links": links[:60],
        "issues": issues,
    }

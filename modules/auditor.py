"""Core URL audit engine — fetches pages and runs all SEO checks."""

import re
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

TIMEOUT = 20
MAX_TITLE_LEN   = 60
MIN_TITLE_LEN   = 30
MAX_DESC_LEN    = 160
MIN_DESC_LEN    = 120
THIN_THRESHOLD  = 300
SLOW_THRESHOLD  = 3.0   # seconds


def _issue(issue, category, severity, recommendation, impact_score=5, effort="Medium"):
    return {
        "issue": issue,
        "category": category,
        "severity": severity,
        "recommendation": recommendation,
        "impact_score": impact_score,
        "effort": effort,
    }


def fetch_page(url):
    """Fetch URL with proper encoding detection and error handling."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                            allow_redirects=True, verify=True)
        # Use detected encoding, fall back to apparent then utf-8
        if resp.encoding and resp.encoding.lower() not in ("utf-8", "utf8"):
            try:
                text = resp.content.decode(resp.encoding, errors="replace")
            except (LookupError, UnicodeDecodeError):
                text = resp.content.decode("utf-8", errors="replace")
        else:
            text = resp.content.decode("utf-8", errors="replace")

        soup = BeautifulSoup(text, "lxml")
        return {
            "success": True,
            "status_code": resp.status_code,
            "final_url": resp.url,
            "redirect_count": len(resp.history),
            "redirect_history": [r.url for r in resp.history],
            "content_type": resp.headers.get("Content-Type", ""),
            "soup": soup,
            "response_time": resp.elapsed.total_seconds(),
            "http_headers": dict(resp.headers),
            "page_size_bytes": len(resp.content),
        }
    except requests.exceptions.SSLError:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                                allow_redirects=True, verify=False)
            text = resp.content.decode("utf-8", errors="replace")
            soup = BeautifulSoup(text, "lxml")
            return {
                "success": True,
                "status_code": resp.status_code,
                "final_url": resp.url,
                "redirect_count": len(resp.history),
                "redirect_history": [r.url for r in resp.history],
                "content_type": resp.headers.get("Content-Type", ""),
                "soup": soup,
                "response_time": resp.elapsed.total_seconds(),
                "ssl_warning": True,
                "http_headers": dict(resp.headers),
                "page_size_bytes": len(resp.content),
            }
        except Exception as e:
            return {"success": False, "error": f"SSL Error: {e}", "status_code": 0}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request Timeout (20s)", "status_code": 0}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "error": f"Connection Error: {e}", "status_code": 0}
    except Exception as e:
        return {"success": False, "error": str(e), "status_code": 0}


def analyze_metadata(soup, url):
    issues = []

    # Title
    title_tag = soup.find("title")
    title = title_tag.get_text().strip() if title_tag else ""
    title_len = len(title)

    if not title:
        issues.append(_issue("Missing Meta Title", "Metadata", "Critical",
            "Add a unique, descriptive meta title (30–60 chars) containing your primary keyword.",
            impact_score=10, effort="Low"))
    elif title_len < MIN_TITLE_LEN:
        issues.append(_issue(f"Meta Title Too Short ({title_len} chars)", "Metadata", "Warning",
            f"Expand the meta title to at least {MIN_TITLE_LEN} characters for better SERP visibility.",
            impact_score=6, effort="Low"))
    elif title_len > MAX_TITLE_LEN:
        issues.append(_issue(f"Meta Title Too Long ({title_len} chars)", "Metadata", "Warning",
            f"Shorten meta title to under {MAX_TITLE_LEN} characters to avoid SERP truncation.",
            impact_score=6, effort="Low"))

    # Description
    desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    description = desc_tag.get("content", "").strip() if desc_tag else ""
    desc_len = len(description)

    if not description:
        issues.append(_issue("Missing Meta Description", "Metadata", "Critical",
            "Add a compelling meta description (120–160 chars) with a clear call to action.",
            impact_score=9, effort="Low"))
    elif desc_len < MIN_DESC_LEN:
        issues.append(_issue(f"Meta Description Too Short ({desc_len} chars)", "Metadata", "Warning",
            f"Expand description to at least {MIN_DESC_LEN} characters.",
            impact_score=5, effort="Low"))
    elif desc_len > MAX_DESC_LEN:
        issues.append(_issue(f"Meta Description Too Long ({desc_len} chars)", "Metadata", "Warning",
            f"Shorten description to under {MAX_DESC_LEN} characters.",
            impact_score=5, effort="Low"))

    # OG tags
    og_title = soup.find("meta", property="og:title")
    og_desc  = soup.find("meta", property="og:description")
    og_image = soup.find("meta", property="og:image")

    missing_og = []
    if not og_title:  missing_og.append("og:title")
    if not og_desc:   missing_og.append("og:description")
    if not og_image:  missing_og.append("og:image")
    if missing_og:
        issues.append(_issue(f"Missing Open Graph Tags: {', '.join(missing_og)}", "Metadata", "Medium",
            "Add all og: meta tags to control how this page appears when shared on social media.",
            impact_score=4, effort="Low"))

    return {
        "title": title, "title_length": title_len, "has_title": bool(title),
        "description": description, "description_length": desc_len,
        "has_description": bool(description),
        "has_og_tags": bool(og_title and og_desc),
        "has_og_image": bool(og_image),
        "issues": issues,
    }


def analyze_headings(soup):
    issues = []
    h1_tags = soup.find_all("h1")
    h2_tags = soup.find_all("h2")
    h3_tags = soup.find_all("h3")
    h4_tags = soup.find_all("h4")
    h1_count = len(h1_tags)
    h1_texts = [h.get_text().strip() for h in h1_tags]

    if h1_count == 0:
        issues.append(_issue("Missing H1 Tag", "Headings", "Critical",
            "Add exactly one H1 tag containing the primary keyword.",
            impact_score=9, effort="Low"))
    elif h1_count > 1:
        issues.append(_issue(f"Multiple H1 Tags ({h1_count})", "Headings", "High",
            "Keep only one H1 per page. Move additional headings to H2 or H3.",
            impact_score=7, effort="Low"))

    if len(h2_tags) == 0 and h1_count > 0:
        issues.append(_issue("No H2 Tags Found", "Headings", "Warning",
            "Add H2 tags to structure your content and improve readability.",
            impact_score=4, effort="Low"))

    # Heading hierarchy check — detect skipped levels
    all_headings = []
    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        level = int(tag.name[1])
        all_headings.append(level)

    skipped = False
    for i in range(1, len(all_headings)):
        if all_headings[i] > all_headings[i - 1] + 1:
            skipped = True
            break
    if skipped:
        issues.append(_issue("Skipped Heading Levels (e.g. H1→H3)", "Headings", "Low",
            "Use sequential heading levels (H1→H2→H3) without skipping levels for proper document structure.",
            impact_score=3, effort="Low"))

    return {
        "h1_count": h1_count, "h2_count": len(h2_tags),
        "h3_count": len(h3_tags), "h4_count": len(h4_tags),
        "h1_texts": h1_texts, "issues": issues,
    }


def analyze_canonical(soup, url):
    issues = []
    canonical_tags = soup.find_all("link", rel="canonical")
    canonical_url  = ""
    is_self_ref    = False

    if len(canonical_tags) == 0:
        issues.append(_issue("Missing Canonical Tag", "Canonical", "Warning",
            "Add a canonical tag to prevent duplicate content issues.",
            impact_score=5, effort="Low"))
    elif len(canonical_tags) > 1:
        issues.append(_issue(f"Multiple Canonical Tags ({len(canonical_tags)})", "Canonical", "Critical",
            "Remove duplicate canonical tags — only one should exist per page.",
            impact_score=8, effort="Low"))
    else:
        href = canonical_tags[0].get("href", "").strip()
        # Resolve relative canonical to absolute
        if href and not href.startswith("http"):
            href = urljoin(url, href)
        canonical_url = href

        if canonical_url:
            p_url = urlparse(url)
            p_can = urlparse(canonical_url)
            url_norm = f"{p_url.netloc}{p_url.path}".rstrip("/").lower()
            can_norm = f"{p_can.netloc}{p_can.path}".rstrip("/").lower()
            is_self_ref = url_norm == can_norm

            if not is_self_ref:
                issues.append(_issue("Canonical Points to Different URL", "Canonical", "Warning",
                    f"Verify this is intentional. Points to: {canonical_url[:80]}",
                    impact_score=6, effort="Low"))

    return {
        "canonical_url": canonical_url,
        "canonical_count": len(canonical_tags),
        "is_self_referencing": is_self_ref,
        "issues": issues,
    }


def analyze_indexability(soup):
    issues = []
    robots_meta = soup.find("meta", attrs={"name": re.compile(r"robots", re.I)})
    robots_content = ""
    is_indexable = True

    if robots_meta:
        robots_content = robots_meta.get("content", "").lower()
        tokens = [t.strip() for t in robots_content.replace(",", " ").split()]
        if "noindex" in tokens:
            is_indexable = False
            issues.append(_issue("Page Set to Noindex", "Indexability", "Critical",
                "Remove 'noindex' from meta robots if this page should appear in search results.",
                impact_score=10, effort="Low"))
        if "nofollow" in tokens:
            issues.append(_issue("Meta Robots: Nofollow Active", "Indexability", "Warning",
                "Review whether nofollow on meta robots is intentional — it prevents link equity flow.",
                impact_score=5, effort="Low"))

    return {"robots_meta": robots_content, "is_indexable": is_indexable, "issues": issues}


def analyze_url_structure(url, response_time=0.0):
    issues = []
    parsed = urlparse(url)
    path   = parsed.path
    slug   = path.rstrip("/").split("/")[-1] if path else ""
    url_len = len(url)

    if url_len > 115:
        issues.append(_issue(f"URL Too Long ({url_len} chars)", "URL Structure", "Warning",
            "Keep URLs under 115 characters for better crawlability and usability.",
            impact_score=4, effort="Medium"))

    if re.search(r"[A-Z]", path):
        issues.append(_issue("URL Contains Uppercase Letters", "URL Structure", "Low",
            "Use lowercase-only URLs to avoid duplicate content issues.",
            impact_score=3, effort="Low"))

    if re.search(r"[?&=#+%]", path):
        issues.append(_issue("URL Contains Special Characters", "URL Structure", "Warning",
            "Use clean, readable URLs without special characters.",
            impact_score=4, effort="Medium"))

    if parsed.scheme != "https":
        issues.append(_issue("Not Using HTTPS", "URL Structure", "Critical",
            "Migrate to HTTPS. Google uses HTTPS as a ranking signal and it's required for trust.",
            impact_score=9, effort="High"))

    if response_time > SLOW_THRESHOLD:
        issues.append(_issue(f"Slow Server Response ({response_time:.2f}s)", "Performance", "High",
            "Aim for under 200ms TTFB. Optimise server, enable caching, and use a CDN.",
            impact_score=7, effort="High"))

    return {
        "length": url_len, "slug": slug, "path": path,
        "is_https": parsed.scheme == "https", "issues": issues,
    }


def analyze_content(soup):
    """Analyse content quality. Makes a deep copy so the original soup is not mutated."""
    issues = []
    soup_copy = BeautifulSoup(str(soup), "lxml")
    for tag in soup_copy(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = soup_copy.get_text(separator=" ")
    # Only count alphabetic words (exclude numbers, punctuation)
    words = re.findall(r"[a-zA-Z]{2,}", text)
    word_count   = len(words)
    reading_time = round(word_count / 200, 1)

    html_len   = len(str(soup))
    text_len   = len(text.strip())
    content_ratio = round((text_len / html_len * 100) if html_len > 0 else 0, 1)

    if word_count < THIN_THRESHOLD:
        issues.append(_issue(f"Thin Content ({word_count} words)", "Content", "High",
            f"Expand content to at least {THIN_THRESHOLD} words. Thin content rarely ranks well.",
            impact_score=8, effort="High"))
    elif word_count < 600:
        issues.append(_issue(f"Below Recommended Word Count ({word_count} words)", "Content", "Warning",
            "Aim for 600+ words to cover the topic comprehensively and outrank competitors.",
            impact_score=5, effort="High"))

    if content_ratio < 10:
        issues.append(_issue(f"Low Content-to-HTML Ratio ({content_ratio}%)", "Content", "Warning",
            "Reduce bloated HTML markup and increase meaningful text content.",
            impact_score=3, effort="Medium"))

    # Extract beginning and ending paragraphs for content preview
    paras = [
        p.get_text(separator=" ", strip=True)
        for p in soup_copy.find_all("p")
        if len(p.get_text(strip=True)) > 60   # skip very short/nav paragraphs
    ]
    intro_paras     = paras[:3]   # first 3 meaningful paragraphs
    conclusion_paras = paras[-3:] if len(paras) > 3 else []

    return {
        "word_count": word_count, "reading_time": reading_time,
        "content_ratio": content_ratio, "is_thin": word_count < THIN_THRESHOLD,
        "intro_paragraphs": intro_paras,
        "conclusion_paragraphs": conclusion_paras,
        "total_paragraphs": len(paras),
        "issues": issues,
    }


def analyze_images(soup):
    issues = []
    images = soup.find_all("img")
    total  = len(images)
    missing_alt, empty_alt, poor_alt = [], [], []

    GENERIC_ALT = re.compile(r"^(image|img|photo|pic|picture|banner|logo)\d*\.?(jpg|png|gif|webp|svg)?$", re.I)

    for img in images:
        src = img.get("src", "")
        alt = img.get("alt")
        if alt is None:
            missing_alt.append(src)
        elif alt.strip() == "":
            empty_alt.append(src)
        elif GENERIC_ALT.match(alt.strip()):
            poor_alt.append((src, alt.strip()))

    if missing_alt:
        issues.append(_issue(f"{len(missing_alt)} Image(s) Missing Alt Attribute", "Images", "High",
            "Add descriptive alt text to every image for accessibility and image SEO.",
            impact_score=7, effort="Low"))
    if empty_alt:
        issues.append(_issue(f"{len(empty_alt)} Image(s) with Empty Alt Text", "Images", "Medium",
            "Replace empty alt='' with meaningful descriptions unless they are purely decorative.",
            impact_score=5, effort="Low"))
    if poor_alt:
        issues.append(_issue(f"{len(poor_alt)} Image(s) with Generic Alt Text", "Images", "Low",
            "Replace generic alt text like 'image.jpg' with descriptive phrases that include keywords.",
            impact_score=3, effort="Low"))

    return {
        "total_images": total,
        "missing_alt_count": len(missing_alt),
        "empty_alt_count":   len(empty_alt),
        "poor_alt_count":    len(poor_alt),
        "missing_alt_urls":  missing_alt[:10],
        "issues": issues,
    }


def analyze_redirect_chain(redirect_history):
    """Analyse redirect chain for multiple hops."""
    issues = []
    if len(redirect_history) > 1:
        issues.append(_issue(
            f"Redirect Chain Detected ({len(redirect_history)} hops)",
            "Redirects", "Warning",
            "Fix redirect chains — each hop wastes crawl budget and dilutes link equity. Link directly to the final URL.",
            impact_score=6, effort="Medium"))
    return {
        "chain_length": len(redirect_history),
        "chain": redirect_history,
        "issues": issues,
    }


def detect_page_type(url, soup):
    url_lower = url.lower()
    if any(x in url_lower for x in ["/course", "/courses", "/training", "/program", "/workshop", "/bootcamp"]):
        return "course"
    if any(x in url_lower for x in ["/blog", "/blogs", "/article", "/post", "/news", "/insight"]):
        return "blog"
    if soup:
        text = soup.get_text().lower()
        course_signals = ["curriculum", "syllabus", "enroll", "instructor", "certification", "learning objectives"]
        blog_signals   = ["published", "author:", "read time", "tags:", "share this article"]
        if sum(1 for s in course_signals if s in text) > sum(1 for s in blog_signals if s in text):
            return "course"
        if sum(1 for s in blog_signals if s in text) >= 2:
            return "blog"
    return "general"


def audit_url(url, audit_type="auto", check_links=True, validate_links=False,
              fetch_pagespeed=False, psi_api_key=None):
    result = {
        "url": url,
        "audit_timestamp": datetime.now().isoformat(),
        "status_code": 0,
        "audit_type": audit_type,
        "fetch_error": None,
        "response_time": 0.0,
        "redirect_count": 0,
        "redirect_chain": [],
        "final_url": url,
        "metadata": {},
        "headings": {},
        "canonical": {},
        "indexability": {},
        "url_structure": {},
        "content": {},
        "images": {},
        "advanced": {},
        "redirect_analysis": {},
        "internal_links": {},
        "external_links": {},
        "course_audit": {},
        "blog_audit": {},
        "http_headers": {},
        "technical_seo": {},
        "seo_score": 0,
        "score_breakdown": {},
        "all_issues": [],
    }

    result["url_structure"] = analyze_url_structure(url)

    fetch = fetch_page(url)
    if not fetch["success"]:
        result["fetch_error"] = fetch.get("error", "Unknown error")
        result["status_code"] = fetch.get("status_code", 0)
        result["all_issues"] = [_issue(
            f"Page Fetch Failed: {result['fetch_error']}",
            "Accessibility", "Critical",
            "Ensure the URL is publicly accessible and returns a valid HTTP response.",
            impact_score=10, effort="High")]
        from modules.scoring import calculate_seo_score
        sr = calculate_seo_score(result)
        result["seo_score"] = sr["score"]
        result["score_breakdown"] = sr["breakdown"]
        return result

    result["status_code"]    = fetch["status_code"]
    result["response_time"]  = fetch.get("response_time", 0.0)
    result["redirect_count"] = fetch.get("redirect_count", 0)
    result["redirect_chain"] = fetch.get("redirect_history", [])
    result["final_url"]      = fetch.get("final_url", url)

    soup = fetch["soup"]

    result["metadata"]     = analyze_metadata(soup, url)
    result["headings"]     = analyze_headings(soup)   # kept for scoring compatibility
    result["canonical"]    = analyze_canonical(soup, url)
    result["indexability"] = analyze_indexability(soup)
    result["url_structure"] = analyze_url_structure(url, result["response_time"])
    result["content"]      = analyze_content(soup)
    result["images"]       = analyze_images(soup)     # kept for scoring compatibility
    result["redirect_analysis"] = analyze_redirect_chain(result["redirect_chain"])

    # ── Deep-analysis modules (new dedicated pages) ───────────────────────
    from modules.heading_auditor import analyze_heading_structure
    result["heading_detail"] = analyze_heading_structure(
        soup, title=result["metadata"].get("title", "")
    )

    from modules.image_auditor import analyze_images_advanced
    result["image_detail"] = analyze_images_advanced(soup, base_url=url)

    # Capture HTTP headers and page size from the fetch result
    http_headers = fetch.get("http_headers", {})
    page_size_bytes = fetch.get("page_size_bytes", 0)
    result["http_headers"] = http_headers

    # Advanced checks (mobile, schema, social, hreflang, Twitter, headers, technical)
    from modules.advanced_checks import analyze_advanced
    result["advanced"] = analyze_advanced(
        soup, url,
        http_headers=http_headers,
        page_size_bytes=page_size_bytes,
        response_time=result["response_time"],
    )

    # Expose technical_seo sub-dict at top level for easy access
    result["technical_seo"] = result["advanced"].get("technical_seo", {})

    # ── Optional PageSpeed Insights API call ─────────────────────────────
    pagespeed_data = None
    if fetch_pagespeed:
        from modules.pagespeed import fetch_pagespeed as _fetch_psi
        pagespeed_data = _fetch_psi(url, strategy="mobile", api_key=psi_api_key)
    result["pagespeed"] = pagespeed_data or {}

    from modules.mobile_auditor import analyze_mobile
    result["mobile_audit"] = analyze_mobile(
        soup,
        base_url=url,
        technical_seo=result["technical_seo"],
        advanced_data=result["advanced"],
        pagespeed=pagespeed_data,
    )

    if audit_type == "auto":
        result["audit_type"] = detect_page_type(url, soup)

    if check_links:
        from modules.link_auditor import audit_links
        link_res = audit_links(soup, url, validate=validate_links)
        result["internal_links"] = link_res["internal"]
        result["external_links"] = link_res["external"]

    if result["audit_type"] == "course":
        from modules.course_auditor import audit_course_page
        result["course_audit"] = audit_course_page(soup, url)
    elif result["audit_type"] == "blog":
        from modules.blog_auditor import audit_blog_page
        result["blog_audit"] = audit_blog_page(soup, url)

    all_issues = []
    for key in ["metadata", "headings", "canonical", "indexability", "url_structure",
                "content", "images", "advanced", "redirect_analysis",
                "internal_links", "external_links", "course_audit", "blog_audit"]:
        all_issues.extend(result.get(key, {}).get("issues", []))
    result["all_issues"] = all_issues

    from modules.scoring import calculate_seo_score
    sr = calculate_seo_score(result)
    result["seo_score"] = sr["score"]
    result["score_breakdown"] = sr["breakdown"]

    return result


def audit_urls_bulk(urls, audit_type="auto", check_links=True, validate_links=False,
                    max_workers=8, progress_callback=None,
                    fetch_pagespeed=False, psi_api_key=None):
    import threading
    results = []
    completed = 0
    lock = threading.Lock()
    total = len(urls)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                audit_url, url, audit_type, check_links, validate_links,
                fetch_pagespeed, psi_api_key
            ): url
            for url in urls
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                results.append({
                    "url": url, "fetch_error": str(e), "status_code": 0,
                    "audit_type": "general", "seo_score": 0, "advanced": {},
                    "http_headers": {}, "technical_seo": {},
                    "all_issues": [_issue(str(e), "Error", "Critical",
                        "Check URL validity and network accessibility.",
                        impact_score=10, effort="High")],
                })
            with lock:
                completed += 1
                done = completed
            if progress_callback:
                progress_callback(done, total)

    return results

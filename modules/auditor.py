"""Core URL audit engine — fetches pages and runs all SEO checks."""

import re
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore", category=requests.packages.urllib3.exceptions.InsecureRequestWarning)

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
MAX_TITLE_LEN = 60
MIN_TITLE_LEN = 30
MAX_DESC_LEN = 160
MIN_DESC_LEN = 120
THIN_THRESHOLD = 300


def fetch_page(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, verify=True)
        soup = BeautifulSoup(resp.text, "lxml")
        return {
            "success": True,
            "status_code": resp.status_code,
            "final_url": resp.url,
            "redirect_count": len(resp.history),
            "content_type": resp.headers.get("Content-Type", ""),
            "soup": soup,
            "response_time": resp.elapsed.total_seconds(),
        }
    except requests.exceptions.SSLError:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, verify=False)
            soup = BeautifulSoup(resp.text, "lxml")
            return {
                "success": True,
                "status_code": resp.status_code,
                "final_url": resp.url,
                "redirect_count": len(resp.history),
                "content_type": resp.headers.get("Content-Type", ""),
                "soup": soup,
                "response_time": resp.elapsed.total_seconds(),
                "ssl_warning": True,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "status_code": 0}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request Timeout (20s)", "status_code": 0}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Connection Error", "status_code": 0}
    except Exception as e:
        return {"success": False, "error": str(e), "status_code": 0}


def analyze_metadata(soup, url):
    issues = []
    title_tag = soup.find("title")
    title = title_tag.get_text().strip() if title_tag else ""
    title_len = len(title)

    if not title:
        issues.append({
            "issue": "Missing Meta Title",
            "category": "Metadata",
            "severity": "Critical",
            "recommendation": "Add a unique descriptive meta title between 30–60 characters.",
        })
    elif title_len < MIN_TITLE_LEN:
        issues.append({
            "issue": f"Meta Title Too Short ({title_len} chars)",
            "category": "Metadata",
            "severity": "Warning",
            "recommendation": f"Expand the meta title to at least {MIN_TITLE_LEN} characters.",
        })
    elif title_len > MAX_TITLE_LEN:
        issues.append({
            "issue": f"Meta Title Too Long ({title_len} chars)",
            "category": "Metadata",
            "severity": "Warning",
            "recommendation": f"Shorten meta title to under {MAX_TITLE_LEN} characters to avoid SERP truncation.",
        })

    desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    description = desc_tag.get("content", "").strip() if desc_tag else ""
    desc_len = len(description)

    if not description:
        issues.append({
            "issue": "Missing Meta Description",
            "category": "Metadata",
            "severity": "Critical",
            "recommendation": "Add a compelling meta description between 120–160 characters.",
        })
    elif desc_len < MIN_DESC_LEN:
        issues.append({
            "issue": f"Meta Description Too Short ({desc_len} chars)",
            "category": "Metadata",
            "severity": "Warning",
            "recommendation": f"Expand description to at least {MIN_DESC_LEN} characters.",
        })
    elif desc_len > MAX_DESC_LEN:
        issues.append({
            "issue": f"Meta Description Too Long ({desc_len} chars)",
            "category": "Metadata",
            "severity": "Warning",
            "recommendation": f"Shorten description to under {MAX_DESC_LEN} characters.",
        })

    # Open Graph
    og_title = soup.find("meta", property="og:title")
    og_desc = soup.find("meta", property="og:description")
    og_image = soup.find("meta", property="og:image")

    if not og_title:
        issues.append({
            "issue": "Missing og:title",
            "category": "Metadata",
            "severity": "Low",
            "recommendation": "Add og:title meta tag for better social sharing appearance.",
        })
    if not og_image:
        issues.append({
            "issue": "Missing og:image",
            "category": "Metadata",
            "severity": "Low",
            "recommendation": "Add og:image for rich social media previews.",
        })

    return {
        "title": title,
        "title_length": title_len,
        "has_title": bool(title),
        "description": description,
        "description_length": desc_len,
        "has_description": bool(description),
        "has_og_tags": bool(og_title),
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
        issues.append({
            "issue": "Missing H1 Tag",
            "category": "Headings",
            "severity": "Critical",
            "recommendation": "Add exactly one H1 tag containing the primary keyword for this page.",
        })
    elif h1_count > 1:
        issues.append({
            "issue": f"Multiple H1 Tags ({h1_count} found)",
            "category": "Headings",
            "severity": "High",
            "recommendation": "Keep only one H1 tag per page. Move additional headings to H2 or H3.",
        })

    if len(h2_tags) == 0 and h1_count > 0:
        issues.append({
            "issue": "No H2 Tags Found",
            "category": "Headings",
            "severity": "Warning",
            "recommendation": "Add H2 tags to organise content and improve readability.",
        })

    return {
        "h1_count": h1_count,
        "h2_count": len(h2_tags),
        "h3_count": len(h3_tags),
        "h4_count": len(h4_tags),
        "h1_texts": h1_texts,
        "issues": issues,
    }


def analyze_canonical(soup, url):
    issues = []
    canonical_tags = soup.find_all("link", rel="canonical")
    canonical_url = ""
    is_self_ref = False

    if len(canonical_tags) == 0:
        issues.append({
            "issue": "Missing Canonical Tag",
            "category": "Canonical",
            "severity": "Warning",
            "recommendation": "Add a canonical tag to prevent duplicate content issues.",
        })
    elif len(canonical_tags) > 1:
        issues.append({
            "issue": f"Multiple Canonical Tags ({len(canonical_tags)})",
            "category": "Canonical",
            "severity": "Critical",
            "recommendation": "Keep only one canonical tag per page.",
        })
    else:
        canonical_url = canonical_tags[0].get("href", "").strip()
        p_url = urlparse(url)
        p_can = urlparse(canonical_url)
        url_norm = f"{p_url.netloc}{p_url.path}".rstrip("/")
        can_norm = f"{p_can.netloc}{p_can.path}".rstrip("/")
        is_self_ref = url_norm == can_norm

        if canonical_url and not is_self_ref:
            issues.append({
                "issue": "Canonical Points to Different URL",
                "category": "Canonical",
                "severity": "Warning",
                "recommendation": f"Verify this is intentional. Canonical: {canonical_url[:80]}",
            })

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
        if "noindex" in robots_content:
            is_indexable = False
            issues.append({
                "issue": "Page Set to Noindex",
                "category": "Indexability",
                "severity": "Critical",
                "recommendation": "Remove noindex from meta robots if this page should appear in search results.",
            })
        if "nofollow" in robots_content:
            issues.append({
                "issue": "Meta Robots: Nofollow Active",
                "category": "Indexability",
                "severity": "Warning",
                "recommendation": "Review whether nofollow on the meta robots tag is intentional.",
            })

    return {
        "robots_meta": robots_content,
        "is_indexable": is_indexable,
        "issues": issues,
    }


def analyze_url_structure(url):
    issues = []
    parsed = urlparse(url)
    path = parsed.path
    slug = path.rstrip("/").split("/")[-1] if path else ""
    url_len = len(url)

    if url_len > 115:
        issues.append({
            "issue": f"URL Too Long ({url_len} chars)",
            "category": "URL Structure",
            "severity": "Warning",
            "recommendation": "Keep URLs under 115 characters for better crawlability.",
        })

    if re.search(r"[A-Z]", path):
        issues.append({
            "issue": "URL Contains Uppercase Letters",
            "category": "URL Structure",
            "severity": "Low",
            "recommendation": "Use lowercase URLs only to avoid duplicate content issues.",
        })

    if re.search(r"[?&=#+%]", path):
        issues.append({
            "issue": "URL Contains Special Characters",
            "category": "URL Structure",
            "severity": "Warning",
            "recommendation": "Use clean, readable URLs without special characters.",
        })

    if not parsed.scheme == "https":
        issues.append({
            "issue": "Not Using HTTPS",
            "category": "URL Structure",
            "severity": "Critical",
            "recommendation": "Migrate to HTTPS for security and SEO benefit.",
        })

    return {
        "length": url_len,
        "slug": slug,
        "path": path,
        "is_https": parsed.scheme == "https",
        "issues": issues,
    }


def analyze_content(soup):
    issues = []
    soup_copy = BeautifulSoup(str(soup), "lxml")
    for tag in soup_copy(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = soup_copy.get_text(separator=" ")
    words = [w for w in text.split() if len(w) > 1]
    word_count = len(words)
    reading_time = round(word_count / 200, 1)
    html_len = len(str(soup))
    text_len = len(text)
    content_ratio = round((text_len / html_len * 100) if html_len > 0 else 0, 1)

    if word_count < THIN_THRESHOLD:
        issues.append({
            "issue": f"Thin Content ({word_count} words)",
            "category": "Content",
            "severity": "High",
            "recommendation": f"Expand content to at least {THIN_THRESHOLD} words for better search rankings.",
        })
    elif word_count < 600:
        issues.append({
            "issue": f"Below Recommended Word Count ({word_count} words)",
            "category": "Content",
            "severity": "Warning",
            "recommendation": "Aim for 600+ words to cover the topic comprehensively.",
        })

    if content_ratio < 10:
        issues.append({
            "issue": f"Low Content-to-HTML Ratio ({content_ratio}%)",
            "category": "Content",
            "severity": "Warning",
            "recommendation": "Reduce bloated HTML and increase meaningful text content.",
        })

    return {
        "word_count": word_count,
        "reading_time": reading_time,
        "content_ratio": content_ratio,
        "is_thin": word_count < THIN_THRESHOLD,
        "issues": issues,
    }


def analyze_images(soup):
    issues = []
    images = soup.find_all("img")
    total = len(images)
    missing_alt = []
    empty_alt = []

    for img in images:
        src = img.get("src", "")
        alt = img.get("alt")
        if alt is None:
            missing_alt.append(src)
        elif alt.strip() == "":
            empty_alt.append(src)

    if len(missing_alt) > 0:
        issues.append({
            "issue": f"{len(missing_alt)} Image(s) Missing Alt Attribute",
            "category": "Images",
            "severity": "High",
            "recommendation": "Add descriptive alt text to every image for accessibility and SEO.",
        })
    if len(empty_alt) > 0:
        issues.append({
            "issue": f"{len(empty_alt)} Image(s) with Empty Alt Text",
            "category": "Images",
            "severity": "Medium",
            "recommendation": "Replace empty alt attributes with meaningful descriptions.",
        })

    return {
        "total_images": total,
        "missing_alt_count": len(missing_alt),
        "empty_alt_count": len(empty_alt),
        "missing_alt_urls": missing_alt[:10],
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
        blog_signals = ["published", "author:", "read time", "tags:", "share this article"]
        if sum(1 for s in course_signals if s in text) > sum(1 for s in blog_signals if s in text):
            return "course"
        if sum(1 for s in blog_signals if s in text) >= 2:
            return "blog"
    return "general"


def audit_url(url, audit_type="auto", check_links=True, validate_links=False):
    result = {
        "url": url,
        "audit_timestamp": datetime.now().isoformat(),
        "status_code": 0,
        "audit_type": audit_type,
        "fetch_error": None,
        "response_time": 0,
        "redirect_count": 0,
        "final_url": url,
        "metadata": {},
        "headings": {},
        "canonical": {},
        "indexability": {},
        "url_structure": {},
        "content": {},
        "images": {},
        "internal_links": {},
        "external_links": {},
        "course_audit": {},
        "blog_audit": {},
        "seo_score": 0,
        "score_breakdown": {},
        "all_issues": [],
    }

    result["url_structure"] = analyze_url_structure(url)
    fetch = fetch_page(url)

    if not fetch["success"]:
        result["fetch_error"] = fetch.get("error", "Unknown error")
        result["status_code"] = fetch.get("status_code", 0)
        result["all_issues"] = [{
            "issue": f"Page Fetch Failed: {result['fetch_error']}",
            "category": "Accessibility",
            "severity": "Critical",
            "recommendation": "Ensure the URL is publicly accessible and returns a valid HTTP response.",
        }]
        from modules.scoring import calculate_seo_score
        sr = calculate_seo_score(result)
        result["seo_score"] = sr["score"]
        result["score_breakdown"] = sr["breakdown"]
        return result

    result["status_code"] = fetch["status_code"]
    result["response_time"] = fetch.get("response_time", 0)
    result["redirect_count"] = fetch.get("redirect_count", 0)
    result["final_url"] = fetch.get("final_url", url)

    soup = fetch["soup"]

    result["metadata"] = analyze_metadata(soup, url)
    result["headings"] = analyze_headings(soup)
    result["canonical"] = analyze_canonical(soup, url)
    result["indexability"] = analyze_indexability(soup)
    result["content"] = analyze_content(soup)
    result["images"] = analyze_images(soup)

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
                "content", "images", "internal_links", "external_links", "course_audit", "blog_audit"]:
        all_issues.extend(result.get(key, {}).get("issues", []))
    result["all_issues"] = all_issues

    from modules.scoring import calculate_seo_score
    sr = calculate_seo_score(result)
    result["seo_score"] = sr["score"]
    result["score_breakdown"] = sr["breakdown"]

    return result


def audit_urls_bulk(urls, audit_type="auto", check_links=True, validate_links=False,
                    max_workers=8, progress_callback=None):
    results = []
    completed = 0
    total = len(urls)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(audit_url, url, audit_type, check_links, validate_links): url
                   for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                results.append({
                    "url": url,
                    "fetch_error": str(e),
                    "status_code": 0,
                    "audit_type": "general",
                    "seo_score": 0,
                    "all_issues": [{"issue": str(e), "category": "Error",
                                    "severity": "Critical", "recommendation": "Check URL validity."}],
                })
            completed += 1
            if progress_callback:
                progress_callback(completed, total)

    return results

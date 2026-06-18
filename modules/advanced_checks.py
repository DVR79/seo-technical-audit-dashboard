"""Advanced SEO checks: mobile, schema, social, hreflang, SERP/social preview data."""

import json
import re
from urllib.parse import urlparse


def analyze_advanced(soup, url):
    """
    Run advanced SEO checks not covered by the core auditor.
    Returns data for: mobile, charset, lang, hreflang, Twitter cards,
    schema markup, favicon, SERP preview, and social preview.
    """
    issues = []
    parsed = urlparse(url)

    # ── 1. Viewport / Mobile-friendliness ────────────────────────────────
    viewport_tag = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
    has_viewport = bool(viewport_tag)
    viewport_content = viewport_tag.get("content", "") if viewport_tag else ""

    if not has_viewport:
        issues.append({
            "issue": "Missing Viewport Meta Tag",
            "category": "Mobile",
            "severity": "Critical",
            "recommendation": 'Add <meta name="viewport" content="width=device-width, initial-scale=1"> to make the page mobile-friendly.',
            "impact_score": 9,
            "effort": "Low",
        })
    elif "width=device-width" not in viewport_content.lower():
        issues.append({
            "issue": "Viewport Not Set to Device Width",
            "category": "Mobile",
            "severity": "High",
            "recommendation": 'Update viewport to content="width=device-width, initial-scale=1" for proper mobile rendering.',
            "impact_score": 7,
            "effort": "Low",
        })

    # ── 2. Charset ────────────────────────────────────────────────────────
    charset_tag = soup.find("meta", charset=True)
    if not charset_tag:
        charset_tag = soup.find("meta", attrs={"http-equiv": re.compile(r"content-type", re.I)})
    has_charset = bool(charset_tag)
    charset_value = (charset_tag.get("charset") or "").upper() if charset_tag else ""

    if not has_charset:
        issues.append({
            "issue": "Missing Charset Declaration",
            "category": "Technical",
            "severity": "Medium",
            "recommendation": 'Add <meta charset="UTF-8"> as the first element inside <head>.',
            "impact_score": 5,
            "effort": "Low",
        })

    # ── 3. HTML lang attribute ────────────────────────────────────────────
    html_tag = soup.find("html")
    lang_attr = html_tag.get("lang", "").strip() if html_tag else ""

    if not lang_attr:
        issues.append({
            "issue": 'Missing lang Attribute on <html> Tag',
            "category": "Accessibility",
            "severity": "Warning",
            "recommendation": 'Add lang="en" (or the correct language code) to the <html> element.',
            "impact_score": 4,
            "effort": "Low",
        })

    # ── 4. Hreflang ───────────────────────────────────────────────────────
    hreflang_tags = soup.find_all("link", rel="alternate", hreflang=True)
    hreflang_list = [
        {"lang": t.get("hreflang", ""), "url": t.get("href", "")}
        for t in hreflang_tags
    ]
    has_xdefault = any(h["lang"] == "x-default" for h in hreflang_list)

    if hreflang_list and not has_xdefault:
        issues.append({
            "issue": "Hreflang Missing x-default Tag",
            "category": "International SEO",
            "severity": "Warning",
            "recommendation": 'Add <link rel="alternate" hreflang="x-default" href="..."> as a fallback for unmatched languages.',
            "impact_score": 5,
            "effort": "Low",
        })

    # ── 5. Twitter Card tags ──────────────────────────────────────────────
    def get_meta_content(name):
        tag = soup.find("meta", attrs={"name": re.compile(rf"^{name}$", re.I)})
        return tag.get("content", "").strip() if tag else ""

    twitter_card   = get_meta_content("twitter:card")
    twitter_title  = get_meta_content("twitter:title")
    twitter_desc   = get_meta_content("twitter:description")
    twitter_image  = get_meta_content("twitter:image")
    twitter_site   = get_meta_content("twitter:site")

    missing_twitter = []
    if not twitter_card:  missing_twitter.append("twitter:card")
    if not twitter_title: missing_twitter.append("twitter:title")
    if not twitter_desc:  missing_twitter.append("twitter:description")
    if not twitter_image: missing_twitter.append("twitter:image")

    if missing_twitter:
        issues.append({
            "issue": f"Missing Twitter Card Tags ({len(missing_twitter)} missing)",
            "category": "Social SEO",
            "severity": "Medium",
            "recommendation": f"Add missing tags: {', '.join(missing_twitter)}. Twitter card tags control appearance when shared on X/Twitter.",
            "impact_score": 4,
            "effort": "Low",
        })

    # ── 6. Schema / Structured data ───────────────────────────────────────
    schema_tags = soup.find_all("script", type="application/ld+json")
    schema_types_found = []
    schema_raw = []
    schema_errors = []

    for tag in schema_tags:
        raw_text = tag.get_text(strip=True)
        try:
            data = json.loads(raw_text)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                stype = item.get("@type", "")
                if isinstance(stype, list):
                    schema_types_found.extend(stype)
                elif stype:
                    schema_types_found.append(str(stype))
                schema_raw.append(item)
        except json.JSONDecodeError as e:
            schema_errors.append(str(e))

    if schema_errors:
        issues.append({
            "issue": f"Invalid JSON-LD Schema ({len(schema_errors)} parse error(s))",
            "category": "Structured Data",
            "severity": "High",
            "recommendation": "Fix JSON syntax errors in your structured data. Use Google's Rich Results Test to validate.",
            "impact_score": 7,
            "effort": "Medium",
        })

    if not schema_types_found:
        issues.append({
            "issue": "No Structured Data Found",
            "category": "Structured Data",
            "severity": "Medium",
            "recommendation": "Add relevant JSON-LD schema markup (Article, Course, FAQPage, BreadcrumbList) for rich results.",
            "impact_score": 6,
            "effort": "Medium",
        })
    else:
        # Check for FAQPage — high rich snippet value
        has_faq_schema = "FAQPage" in schema_types_found
        # Check for BreadcrumbList
        has_breadcrumb = "BreadcrumbList" in schema_types_found
        if not has_breadcrumb:
            issues.append({
                "issue": "Missing BreadcrumbList Schema",
                "category": "Structured Data",
                "severity": "Low",
                "recommendation": "Add BreadcrumbList schema to display breadcrumb rich results in Google.",
                "impact_score": 3,
                "effort": "Medium",
            })

    # ── 7. Favicon ────────────────────────────────────────────────────────
    favicon = soup.find("link", rel=lambda r: r and (
        "icon" in (r if isinstance(r, str) else " ".join(r)).lower()
    ))
    has_favicon = bool(favicon)

    if not has_favicon:
        issues.append({
            "issue": "Missing Favicon",
            "category": "Technical",
            "severity": "Low",
            "recommendation": "Add a favicon (32×32 PNG minimum) for brand recognition in browser tabs and search results.",
            "impact_score": 2,
            "effort": "Low",
        })

    # ── 8. SERP Preview data ──────────────────────────────────────────────
    title_tag = soup.find("title")
    page_title = title_tag.get_text().strip() if title_tag else ""
    desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    page_desc = desc_tag.get("content", "").strip() if desc_tag else ""

    # Breadcrumb trail for SERP
    path_parts = [p for p in parsed.path.split("/") if p]
    breadcrumb_parts = [parsed.netloc] + path_parts
    breadcrumb_str = " › ".join(breadcrumb_parts)[:80]

    serp_title_display = page_title[:57] + "..." if len(page_title) > 57 else page_title
    serp_desc_display  = page_desc[:157]  + "..." if len(page_desc)  > 157 else page_desc

    # ── 9. Social / OG preview data ───────────────────────────────────────
    def get_og(prop):
        tag = soup.find("meta", property=f"og:{prop}")
        return tag.get("content", "").strip() if tag else ""

    og_title     = get_og("title") or page_title
    og_desc      = get_og("description") or page_desc
    og_image_url = get_og("image")
    og_type      = get_og("type") or "website"
    og_site_name = get_og("site_name") or parsed.netloc

    return {
        # Mobile
        "has_viewport": has_viewport,
        "viewport_content": viewport_content,
        # Charset
        "has_charset": has_charset,
        "charset_value": charset_value,
        # Language
        "lang_attr": lang_attr,
        # Hreflang
        "hreflang_tags": hreflang_list,
        "has_hreflang": len(hreflang_list) > 0,
        # Twitter
        "twitter_card": twitter_card,
        "twitter_title": twitter_title,
        "twitter_description": twitter_desc,
        "twitter_image": twitter_image,
        "twitter_site": twitter_site,
        "twitter_complete": len(missing_twitter) == 0,
        # Schema
        "schema_types": schema_types_found,
        "schema_raw": schema_raw[:5],
        "has_schema": len(schema_types_found) > 0,
        "schema_errors": schema_errors,
        # Favicon
        "has_favicon": has_favicon,
        # SERP Preview
        "serp_preview": {
            "title": serp_title_display,
            "description": serp_desc_display,
            "breadcrumb": breadcrumb_str,
            "url": url,
            "title_too_long": len(page_title) > 60,
            "desc_too_short": len(page_desc) < 120,
            "desc_too_long": len(page_desc) > 160,
        },
        # Social Preview
        "social_preview": {
            "og_title": og_title[:80],
            "og_description": og_desc[:200],
            "og_image": og_image_url,
            "og_type": og_type,
            "og_site_name": og_site_name,
            "twitter_card_type": twitter_card or "summary",
            "twitter_image": twitter_image,
        },
        "issues": issues,
    }


def detect_duplicate_metas(results):
    """
    Scan bulk audit results for duplicate meta titles, descriptions, and H1s.
    Returns a dict of duplicates found.
    """
    title_map = {}
    desc_map  = {}
    h1_map    = {}

    for r in results:
        url   = r.get("url", "")
        meta  = r.get("metadata", {})
        heads = r.get("headings", {})

        title = (meta.get("title") or "").strip().lower()
        desc  = (meta.get("description") or "").strip().lower()
        h1s   = heads.get("h1_texts", [])

        if title:
            title_map.setdefault(title, []).append(url)
        if desc:
            desc_map.setdefault(desc, []).append(url)
        for h1 in h1s:
            h = (h1 or "").strip().lower()
            if h:
                h1_map.setdefault(h, []).append(url)

    dup_titles = {t: urls for t, urls in title_map.items() if len(urls) > 1}
    dup_descs  = {d: urls for d, urls in desc_map.items()  if len(urls) > 1}
    dup_h1s    = {h: urls for h, urls in h1_map.items()    if len(urls) > 1}

    return {
        "duplicate_titles": dup_titles,
        "duplicate_descriptions": dup_descs,
        "duplicate_h1s": dup_h1s,
        "total_dup_titles": len(dup_titles),
        "total_dup_descs": len(dup_descs),
        "total_dup_h1s": len(dup_h1s),
    }

"""Advanced SEO checks: mobile, schema, social, hreflang, SERP/social preview data,
HTTP headers analysis, and deep technical SEO signals."""

import json
import re
from urllib.parse import urlparse


# ════════════════════════════════════════════════════════════════════════════
# HTTP Headers Analysis
# ════════════════════════════════════════════════════════════════════════════

def analyze_http_headers(http_headers: dict, url: str) -> dict:
    """
    Analyze HTTP response headers for SEO-relevant insights.
    Returns a dict of parsed header signals and issues.
    """
    issues = []
    h = {k.lower(): v for k, v in (http_headers or {}).items()}

    # X-Robots-Tag
    x_robots_tag = h.get("x-robots-tag", "")
    x_robots_noindex = "noindex" in x_robots_tag.lower() if x_robots_tag else False

    if x_robots_noindex:
        issues.append({
            "issue": "X-Robots-Tag Header Contains noindex",
            "category": "Indexability",
            "severity": "Critical",
            "recommendation": "Remove 'noindex' from the X-Robots-Tag HTTP header if this page should be indexed by search engines.",
            "impact_score": 10,
            "effort": "Low",
        })

    # Cache-Control
    cache_control = h.get("cache-control", "")
    has_cache_control = bool(cache_control)

    if not has_cache_control:
        issues.append({
            "issue": "Missing Cache-Control Header",
            "category": "Performance",
            "severity": "Warning",
            "recommendation": "Add a Cache-Control header (e.g. 'public, max-age=31536000') to improve repeat-visit performance and reduce server load.",
            "impact_score": 5,
            "effort": "Medium",
        })

    # Content-Encoding / Compression
    content_encoding = h.get("content-encoding", "identity")
    has_compression = content_encoding.lower() in ("gzip", "br", "deflate", "zstd")

    if not has_compression:
        issues.append({
            "issue": "Response Not Compressed (No gzip/Brotli)",
            "category": "Performance",
            "severity": "Warning",
            "recommendation": "Enable gzip or Brotli compression on your server/CDN to reduce page transfer size and improve load times.",
            "impact_score": 6,
            "effort": "Low",
        })

    # Server
    server = h.get("server", "")

    # HSTS
    hsts_value = h.get("strict-transport-security", "")
    has_hsts = bool(hsts_value)

    if not has_hsts:
        issues.append({
            "issue": "Missing HSTS Header (Strict-Transport-Security)",
            "category": "Security",
            "severity": "Medium",
            "recommendation": "Add 'Strict-Transport-Security: max-age=31536000; includeSubDomains' to enforce HTTPS connections. This is a security best practice and minor trust signal — not a direct Google ranking factor.",
            "impact_score": 4,
            "effort": "Low",
        })

    # CSP
    has_csp = bool(h.get("content-security-policy", ""))

    # X-Frame-Options
    x_frame_options = h.get("x-frame-options", "")
    has_x_frame_options = bool(x_frame_options)

    if not has_x_frame_options:
        issues.append({
            "issue": "Missing X-Frame-Options Header",
            "category": "Security",
            "severity": "Medium",
            "recommendation": "Add 'X-Frame-Options: SAMEORIGIN' to prevent clickjacking attacks and protect user trust.",
            "impact_score": 4,
            "effort": "Low",
        })

    # X-Content-Type-Options
    has_x_content_type_options = bool(h.get("x-content-type-options", ""))

    if not has_x_content_type_options:
        issues.append({
            "issue": "Missing X-Content-Type-Options Header",
            "category": "Security",
            "severity": "Low",
            "recommendation": "Add 'X-Content-Type-Options: nosniff' to prevent MIME-type sniffing vulnerabilities.",
            "impact_score": 3,
            "effort": "Low",
        })

    # Referrer-Policy
    referrer_policy = h.get("referrer-policy", "")
    has_referrer_policy = bool(referrer_policy)

    # Permissions-Policy
    has_permissions_policy = bool(
        h.get("permissions-policy", "") or h.get("feature-policy", "")
    )

    # ETag and Last-Modified
    etag = h.get("etag", "")
    last_modified = h.get("last-modified", "")

    # Cloudflare cache status
    cf_cache_status = h.get("cf-cache-status", "")

    return {
        "x_robots_tag": x_robots_tag,
        "x_robots_noindex": x_robots_noindex,
        "cache_control": cache_control,
        "has_cache_control": has_cache_control,
        "content_encoding": content_encoding,
        "has_compression": has_compression,
        "server": server,
        "has_hsts": has_hsts,
        "hsts_value": hsts_value,
        "has_csp": has_csp,
        "has_x_frame_options": has_x_frame_options,
        "x_frame_options": x_frame_options,
        "has_x_content_type_options": has_x_content_type_options,
        "has_referrer_policy": has_referrer_policy,
        "referrer_policy": referrer_policy,
        "has_permissions_policy": has_permissions_policy,
        "etag": etag,
        "last_modified": last_modified,
        "cf_cache_status": cf_cache_status,
        "issues": issues,
    }


# ════════════════════════════════════════════════════════════════════════════
# Technical SEO Analysis
# ════════════════════════════════════════════════════════════════════════════

def analyze_technical_seo(soup, url: str, page_size_bytes: int, response_time: float) -> dict:
    """
    Deep technical SEO analysis from HTML.
    Returns resource counts, CWV estimates, mixed content, AMP, pagination, etc.
    """
    issues = []
    parsed = urlparse(url or "")
    is_https = parsed.scheme == "https"

    # ── Page size ─────────────────────────────────────────────────────────
    page_size_kb = round((page_size_bytes or 0) / 1024, 1)
    if page_size_kb < 100:
        page_size_label = "Small (<100KB)"
    elif page_size_kb < 500:
        page_size_label = "Medium (100-500KB)"
    else:
        page_size_label = "Large (>500KB)"

    if page_size_kb > 500:
        issues.append({
            "issue": f"Large Page Size ({page_size_kb} KB)",
            "category": "Performance",
            "severity": "Warning",
            "recommendation": "Reduce page size below 500 KB by compressing images, minifying HTML/CSS/JS, and removing unnecessary code.",
            "impact_score": 6,
            "effort": "Medium",
        })

    # ── AMP ───────────────────────────────────────────────────────────────
    amp_link = soup.find("link", rel="amphtml") if soup else None
    amp_url = (amp_link.get("href", "") or "") if amp_link else ""
    html_tag = soup.find("html") if soup else None
    html_attrs = html_tag.attrs if html_tag else {}
    has_amp_attr = "amp" in html_attrs or "⚡" in html_attrs
    has_amp = bool(amp_url) or has_amp_attr

    # ── Pagination ────────────────────────────────────────────────────────
    prev_link = soup.find("link", rel="prev") if soup else None
    next_link = soup.find("link", rel="next") if soup else None
    has_pagination_prev = bool(prev_link)
    has_pagination_next = bool(next_link)
    pagination_prev_url = (prev_link.get("href", "") or "") if prev_link else ""
    pagination_next_url = (next_link.get("href", "") or "") if next_link else ""

    # ── RSS Feed ─────────────────────────────────────────────────────────
    rss_link = soup.find("link", rel="alternate", type="application/rss+xml") if soup else None
    if not rss_link and soup:
        rss_link = soup.find("link", attrs={"type": "application/atom+xml"})
    has_rss_feed = bool(rss_link)
    rss_url = (rss_link.get("href", "") or "") if rss_link else ""

    # ── Scripts ──────────────────────────────────────────────────────────
    all_scripts = soup.find_all("script") if soup else []
    script_count = len(all_scripts)
    external_script_count = sum(
        1 for s in all_scripts
        if (s.get("src") or "").startswith("http")
    )

    # ── Stylesheets ──────────────────────────────────────────────────────
    all_links = soup.find_all("link") if soup else []
    stylesheets = [l for l in all_links if "stylesheet" in (
        " ".join(l.get("rel", [])) if isinstance(l.get("rel"), list) else str(l.get("rel", ""))
    ).lower()]
    stylesheet_count = len(stylesheets)
    external_stylesheet_count = sum(
        1 for s in stylesheets
        if (s.get("href") or "").startswith("http")
    )

    # ── Iframes ──────────────────────────────────────────────────────────
    iframes = soup.find_all("iframe") if soup else []
    iframe_count = len(iframes)
    has_iframes = iframe_count > 0

    if has_iframes:
        issues.append({
            "issue": f"Page Contains {iframe_count} iframe(s)",
            "category": "Technical",
            "severity": "Low",
            "recommendation": "Avoid iframes where possible — they can slow page load, cause CLS, and may not be crawled by search engines.",
            "impact_score": 3,
            "effort": "Medium",
        })

    # ── DOM size ─────────────────────────────────────────────────────────
    dom_elements = len(soup.find_all()) if soup else 0
    if dom_elements < 500:
        dom_size_label = "Small (<500)"
    elif dom_elements < 1500:
        dom_size_label = "Medium (500-1500)"
    else:
        dom_size_label = "Large (>1500)"

    if dom_elements > 1500:
        issues.append({
            "issue": f"Large DOM Size ({dom_elements} elements)",
            "category": "Performance",
            "severity": "Warning",
            "recommendation": "Reduce DOM size below 1500 elements. A bloated DOM slows rendering, increases memory usage, and harms Core Web Vitals.",
            "impact_score": 5,
            "effort": "High",
        })

    # ── Mixed content ─────────────────────────────────────────────────────
    mixed_content_count = 0
    if is_https and soup:
        for tag in soup.find_all(["img", "script", "link", "audio", "video", "source", "iframe"]):
            for attr in ["src", "href", "data-src"]:
                val = tag.get(attr, "") or ""
                if val.startswith("http://"):
                    mixed_content_count += 1
                    break

    has_mixed_content = mixed_content_count > 0
    if has_mixed_content:
        issues.append({
            "issue": f"Mixed Content Detected ({mixed_content_count} HTTP resource(s) on HTTPS page)",
            "category": "Security",
            "severity": "Critical",
            "recommendation": "Replace all http:// resource URLs with https:// equivalents. Mixed content breaks secure connections and triggers browser warnings.",
            "impact_score": 10,
            "effort": "Medium",
        })

    # ── Resource hints ────────────────────────────────────────────────────
    preconnect_tags = [
        l for l in all_links
        if "preconnect" in (
            " ".join(l.get("rel", [])) if isinstance(l.get("rel"), list) else str(l.get("rel", ""))
        ).lower()
    ]
    has_preconnect = len(preconnect_tags) > 0
    preconnect_domains = [l.get("href", "") or "" for l in preconnect_tags]

    dns_prefetch_tags = [
        l for l in all_links
        if "dns-prefetch" in (
            " ".join(l.get("rel", [])) if isinstance(l.get("rel"), list) else str(l.get("rel", ""))
        ).lower()
    ]
    has_dns_prefetch = len(dns_prefetch_tags) > 0

    preload_tags = [
        l for l in all_links
        if "preload" in (
            " ".join(l.get("rel", [])) if isinstance(l.get("rel"), list) else str(l.get("rel", ""))
        ).lower()
    ]
    has_preload = len(preload_tags) > 0

    if external_script_count > 3 and not has_preconnect and not has_dns_prefetch:
        issues.append({
            "issue": f"No Resource Hints for {external_script_count} External Scripts",
            "category": "Performance",
            "severity": "Low",
            "recommendation": "Add <link rel='preconnect'> or <link rel='dns-prefetch'> for your most critical external script domains (e.g. analytics, fonts). Focus on domains you control or that block rendering.",
            "impact_score": 3,
            "effort": "Low",
        })

    # ── Print stylesheet ──────────────────────────────────────────────────
    has_print_stylesheet = any(
        "print" in (l.get("media", "") or "").lower()
        for l in stylesheets
    )

    # ── Core Web Vitals estimates ─────────────────────────────────────────
    ttfb_ms = round((response_time or 0.0) * 1000)
    if ttfb_ms < 200:
        cwv_ttfb_estimate = "Good (<200ms)"
    elif ttfb_ms < 500:
        cwv_ttfb_estimate = "Needs Improvement (200-500ms)"
    else:
        cwv_ttfb_estimate = "Poor (>500ms)"

    if ttfb_ms > 500:
        issues.append({
            "issue": f"Poor TTFB — Server Response Time {ttfb_ms}ms",
            "category": "Performance",
            "severity": "High",
            "recommendation": "Reduce Time to First Byte below 200ms. Investigate server-side rendering time, database queries, and implement server-side caching or a CDN.",
            "impact_score": 8,
            "effort": "High",
        })
    elif ttfb_ms > 200:
        issues.append({
            "issue": f"TTFB Needs Improvement ({ttfb_ms}ms)",
            "category": "Performance",
            "severity": "Warning",
            "recommendation": "Aim for TTFB under 200ms. Consider server-side caching, CDN, or optimizing backend processing.",
            "impact_score": 5,
            "effort": "Medium",
        })

    # LCP heuristic based on page size + image count
    image_tags = soup.find_all("img") if soup else []
    image_count = len(image_tags)
    if page_size_kb < 200 and image_count < 10:
        cwv_lcp_estimate = "Good"
    elif page_size_kb < 500 and image_count < 25:
        cwv_lcp_estimate = "Needs Improvement"
    else:
        cwv_lcp_estimate = "Poor"

    # CLS risk: iframes + images without width/height
    images_without_dims = sum(
        1 for img in image_tags
        if not (img.get("width") and img.get("height"))
    )
    if iframe_count == 0 and images_without_dims < 5:
        cwv_cls_risk = "Low"
    elif iframe_count <= 2 and images_without_dims < 15:
        cwv_cls_risk = "Medium"
    else:
        cwv_cls_risk = "High"

    # Simple performance score 0-100
    perf_score = 100
    if page_size_kb > 500:
        perf_score -= 20
    elif page_size_kb > 200:
        perf_score -= 10
    if ttfb_ms > 500:
        perf_score -= 25
    elif ttfb_ms > 200:
        perf_score -= 10
    if dom_elements > 1500:
        perf_score -= 15
    elif dom_elements > 800:
        perf_score -= 5
    if has_mixed_content:
        perf_score -= 20
    if external_script_count > 10:
        perf_score -= 10
    elif external_script_count > 5:
        perf_score -= 5
    performance_score = max(0, min(100, perf_score))

    return {
        "page_size_kb": page_size_kb,
        "page_size_label": page_size_label,
        "has_amp": has_amp,
        "amp_url": amp_url,
        "has_pagination_prev": has_pagination_prev,
        "has_pagination_next": has_pagination_next,
        "pagination_prev_url": pagination_prev_url,
        "pagination_next_url": pagination_next_url,
        "has_rss_feed": has_rss_feed,
        "rss_url": rss_url,
        "script_count": script_count,
        "external_script_count": external_script_count,
        "stylesheet_count": stylesheet_count,
        "external_stylesheet_count": external_stylesheet_count,
        "iframe_count": iframe_count,
        "has_iframes": has_iframes,
        "dom_elements": dom_elements,
        "dom_size_label": dom_size_label,
        "has_mixed_content": has_mixed_content,
        "mixed_content_count": mixed_content_count,
        "has_print_stylesheet": has_print_stylesheet,
        "has_preconnect": has_preconnect,
        "has_dns_prefetch": has_dns_prefetch,
        "preconnect_domains": preconnect_domains,
        "has_preload": has_preload,
        "cwv_ttfb_estimate": cwv_ttfb_estimate,
        "cwv_ttfb_ms": ttfb_ms,
        "cwv_lcp_estimate": cwv_lcp_estimate,
        "cwv_cls_risk": cwv_cls_risk,
        "performance_score": performance_score,
        "image_count": image_count,
        "images_without_dims": images_without_dims,
        "issues": issues,
    }


# ════════════════════════════════════════════════════════════════════════════
# Main advanced analysis entry point
# ════════════════════════════════════════════════════════════════════════════

def analyze_advanced(soup, url, http_headers=None, page_size_bytes=0, response_time=0.0):
    """
    Run advanced SEO checks not covered by the core auditor.
    Returns data for: mobile, charset, lang, hreflang, Twitter cards,
    schema markup, favicon, SERP preview, social preview, HTTP headers,
    and deep technical SEO signals.
    """
    issues = []
    parsed = urlparse(url or "")

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

    # ── 10. HTTP Headers analysis ─────────────────────────────────────────
    http_headers_data = analyze_http_headers(http_headers or {}, url or "")
    issues.extend(http_headers_data.get("issues", []))

    # ── 11. Technical SEO analysis ────────────────────────────────────────
    technical_seo = analyze_technical_seo(soup, url or "", page_size_bytes or 0, response_time or 0.0)
    issues.extend(technical_seo.get("issues", []))

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
        # HTTP Headers data (full sub-dict)
        "http_headers_data": http_headers_data,
        # Technical SEO data (full sub-dict)
        "technical_seo": technical_seo,
        # Top-level convenience flags
        "has_hsts": http_headers_data.get("has_hsts", False),
        "has_compression": http_headers_data.get("has_compression", False),
        "has_mixed_content": technical_seo.get("has_mixed_content", False),
        "page_size_kb": technical_seo.get("page_size_kb", 0.0),
        "has_amp": technical_seo.get("has_amp", False),
        "has_pagination": (
            technical_seo.get("has_pagination_next", False)
            or technical_seo.get("has_pagination_prev", False)
        ),
        "issues": issues,
    }


# ════════════════════════════════════════════════════════════════════════════
# Duplicate meta detection (unchanged)
# ════════════════════════════════════════════════════════════════════════════

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

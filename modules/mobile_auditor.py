"""
mobile_auditor.py
Mobile SEO and responsiveness analysis for SEO Technical Audit Dashboard.
"""

import re


# ---------------------------------------------------------------------------
# Pattern constants
# ---------------------------------------------------------------------------

HAMBURGER_PATTERN = re.compile(
    r"hamburger|toggle|nav-toggle|menu-toggle|sidebar-toggle|mobile-menu|offcanvas",
    re.IGNORECASE,
)

POPUP_PATTERN = re.compile(
    r"popup|modal|overlay|interstitial|exit-popup|exit_popup|lightbox",
    re.IGNORECASE,
)

CTA_PATTERN = re.compile(
    r"cta|call-to-action|enroll|register|buy-now|buy_now|get-started|get_started",
    re.IGNORECASE,
)

RESPONSIVE_FRAMEWORKS = re.compile(
    r"\b(col-|container|row|grid-|d-flex|flex-|tw-|sm:|md:|lg:|xl:|foundation|uk-)",
    re.IGNORECASE,
)

FONT_SIZE_PX_RE = re.compile(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", re.IGNORECASE)
INLINE_WIDTH_RE = re.compile(r"width\s*:\s*(\d+(?:\.\d+)?)px", re.IGNORECASE)
INLINE_HEIGHT_RE = re.compile(r"height\s*:\s*(\d+(?:\.\d+)?)px", re.IGNORECASE)
MEDIA_QUERY_RE = re.compile(r"@media\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Individual check helpers
# ---------------------------------------------------------------------------

def _check_viewport(soup):
    """Check presence and correctness of viewport meta tag."""
    viewport = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
    if not viewport:
        return {
            "id": "viewport_tag",
            "name": "Viewport Meta Tag",
            "category": "Mobile Basics",
            "status": "fail",
            "value": "Missing",
            "detail": "No viewport meta tag found. Mobile browsers will use desktop layout.",
        }
    content = viewport.get("content", "")
    if "width=device-width" in content:
        return {
            "id": "viewport_tag",
            "name": "Viewport Meta Tag",
            "category": "Mobile Basics",
            "status": "pass",
            "value": content,
            "detail": "Viewport correctly set to device-width.",
        }
    return {
        "id": "viewport_tag",
        "name": "Viewport Meta Tag",
        "category": "Mobile Basics",
        "status": "warning",
        "value": content,
        "detail": "Viewport meta tag present but does not include 'width=device-width'.",
    }


def _check_prevents_zoom(soup):
    """Warn if viewport prevents user zoom."""
    viewport = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
    if not viewport:
        return {
            "id": "prevents_zoom",
            "name": "Zoom Prevention",
            "category": "Accessibility",
            "status": "info",
            "value": "N/A",
            "detail": "No viewport tag found (see viewport_tag check).",
        }
    content = viewport.get("content", "")
    blocks_zoom = (
        "user-scalable=no" in content
        or re.search(r"maximum-scale\s*=\s*1\b", content)
    )
    if blocks_zoom:
        return {
            "id": "prevents_zoom",
            "name": "Zoom Prevention",
            "category": "Accessibility",
            "status": "warning",
            "value": content,
            "detail": "Viewport prevents user zoom — this harms accessibility and is penalised by Google.",
        }
    return {
        "id": "prevents_zoom",
        "name": "Zoom Prevention",
        "category": "Accessibility",
        "status": "pass",
        "value": content,
        "detail": "User zoom is not restricted.",
    }


def _check_responsive_framework(soup):
    """Detect common responsive CSS frameworks via class patterns."""
    html_str = str(soup)
    found = bool(RESPONSIVE_FRAMEWORKS.search(html_str))
    return {
        "id": "responsive_framework",
        "name": "Responsive Framework Detected",
        "category": "Responsiveness",
        "status": "pass" if found else "info",
        "value": "Detected" if found else "Not detected",
        "detail": (
            "A responsive CSS framework or utility classes were detected."
            if found
            else "No common responsive framework classes found. Verify CSS manually."
        ),
    }


def _check_media_queries(soup):
    """Check for @media rules in inline <style> tags."""
    has_mq = False
    for style_tag in soup.find_all("style"):
        if MEDIA_QUERY_RE.search(style_tag.get_text()):
            has_mq = True
            break
    return {
        "id": "media_queries",
        "name": "CSS Media Queries",
        "category": "Responsiveness",
        "status": "pass" if has_mq else "info",
        "value": "Found" if has_mq else "Not found in inline styles",
        "detail": (
            "Media queries found in inline styles."
            if has_mq
            else "No @media rules in inline <style> tags. They may be in external stylesheets."
        ),
    }


def _check_touch_targets(soup):
    """Warn if interactive elements have inline style dimensions < 44px."""
    small = 0
    for tag in soup.find_all(["button", "a", "input"]):
        style = tag.get("style", "")
        for match in INLINE_WIDTH_RE.finditer(style):
            if float(match.group(1)) < 44:
                small += 1
                break
        else:
            for match in INLINE_HEIGHT_RE.finditer(style):
                if float(match.group(1)) < 44:
                    small += 1
                    break
    return {
        "id": "touch_targets",
        "name": "Touch Target Sizes",
        "category": "Usability",
        "status": "pass" if small == 0 else "warning",
        "value": f"{small} small target(s) found",
        "detail": (
            "All interactive elements appear to meet the 44px minimum touch target size."
            if small == 0
            else f"{small} interactive element(s) have inline width or height below 44px."
        ),
    }


def _check_font_size(soup):
    """Warn if inline styles set font-size below 12px."""
    small = 0
    for tag in soup.find_all(True):
        style = tag.get("style", "")
        for match in FONT_SIZE_PX_RE.finditer(style):
            if float(match.group(1)) < 12:
                small += 1
    return {
        "id": "font_size",
        "name": "Font Size",
        "category": "Readability",
        "status": "pass" if small == 0 else "warning",
        "value": f"{small} small font(s) found",
        "detail": (
            "No inline font sizes below 12px detected."
            if small == 0
            else f"{small} element(s) have inline font-size below 12px — too small for mobile."
        ),
    }


def _check_mobile_nav(soup):
    """Check for <nav> element and hamburger/toggle patterns."""
    has_nav = soup.find("nav") is not None
    has_hamburger = False
    for tag in soup.find_all(True):
        class_str = " ".join(tag.get("class", []))
        id_str = tag.get("id", "")
        if HAMBURGER_PATTERN.search(class_str) or HAMBURGER_PATTERN.search(id_str):
            has_hamburger = True
            break

    if has_nav and has_hamburger:
        status, detail = "pass", "Navigation element and mobile toggle/hamburger detected."
    elif has_nav:
        status, detail = "warning", "Navigation found but no hamburger/toggle pattern detected for mobile."
    else:
        status, detail = "fail", "No <nav> element or mobile navigation pattern detected."

    return {
        "id": "mobile_nav",
        "name": "Mobile Navigation",
        "category": "Navigation",
        "status": status,
        "value": f"nav={'yes' if has_nav else 'no'}, toggle={'yes' if has_hamburger else 'no'}",
        "detail": detail,
    }


def _check_form_usability(soup):
    """Count inputs missing labels and missing type attribute."""
    inputs = soup.find_all("input")
    missing_label = 0
    missing_type = 0

    for inp in inputs:
        # Skip hidden inputs
        if inp.get("type", "").lower() in ("hidden", "submit", "button", "reset", "image"):
            continue
        if not inp.get("type"):
            missing_type += 1

        has_label = False
        inp_id = inp.get("id")
        if inp_id and soup.find("label", attrs={"for": inp_id}):
            has_label = True
        if inp.get("aria-label") or inp.get("aria-labelledby"):
            has_label = True
        if inp.get("placeholder"):
            has_label = True  # placeholder counts per spec
        if not has_label:
            missing_label += 1

    issues_count = missing_label + missing_type
    return {
        "id": "form_usability",
        "name": "Form Usability",
        "category": "Usability",
        "status": "pass" if issues_count == 0 else "warning",
        "value": f"{missing_label} unlabelled, {missing_type} missing type",
        "detail": (
            "All form inputs appear to have labels and type attributes."
            if issues_count == 0
            else f"{missing_label} input(s) missing accessible labels; {missing_type} input(s) missing type attribute."
        ),
        "_missing_label": missing_label,
        "_missing_type": missing_type,
    }


def _check_intrusive_popups(soup):
    """Search for popup/modal/overlay patterns in class and id attributes."""
    popup_count = 0
    for tag in soup.find_all(True):
        class_str = " ".join(tag.get("class", []))
        id_str = tag.get("id", "")
        if POPUP_PATTERN.search(class_str) or POPUP_PATTERN.search(id_str):
            popup_count += 1

    return {
        "id": "intrusive_popups",
        "name": "Intrusive Popups / Interstitials",
        "category": "User Experience",
        "status": "warning" if popup_count > 0 else "pass",
        "value": f"{popup_count} popup-like element(s) detected",
        "detail": (
            "No popup, modal, or interstitial patterns detected."
            if popup_count == 0
            else (
                f"{popup_count} element(s) with popup/modal/overlay class or id patterns found. "
                "Intrusive interstitials can harm mobile rankings."
            )
        ),
        "_popup_count": popup_count,
    }


def _check_cta_visibility(soup):
    """Search for CTA patterns in class/id/href attributes."""
    cta_count = 0
    for tag in soup.find_all(True):
        class_str = " ".join(tag.get("class", []))
        id_str = tag.get("id", "")
        href = tag.get("href", "")
        if (
            CTA_PATTERN.search(class_str)
            or CTA_PATTERN.search(id_str)
            or CTA_PATTERN.search(href)
        ):
            cta_count += 1

    return {
        "id": "cta_visibility",
        "name": "CTA Visibility",
        "category": "Conversion",
        "status": "info",
        "value": f"{cta_count} CTA element(s) detected",
        "detail": f"{cta_count} call-to-action element(s) detected on the page.",
        "_cta_count": cta_count,
    }


def _check_responsive_images(soup):
    """Count imgs with srcset vs total imgs."""
    imgs = soup.find_all("img")
    total = len(imgs)
    with_srcset = sum(1 for img in imgs if img.get("srcset"))

    if total == 0 or with_srcset == total:
        status = "pass"
        detail = "All images use srcset or no images found." if total > 0 else "No images found."
    elif with_srcset > 0:
        status = "info"
        detail = f"{with_srcset} of {total} images use srcset for responsive loading."
    else:
        status = "warning"
        detail = f"None of the {total} images use srcset. Add srcset for responsive image delivery."

    return {
        "id": "responsive_images",
        "name": "Responsive Images (srcset)",
        "category": "Performance",
        "status": status,
        "value": f"{with_srcset}/{total} have srcset",
        "detail": detail,
    }


def _check_image_dimensions(soup):
    """Count imgs missing explicit width and height attributes."""
    imgs = soup.find_all("img")
    missing = sum(
        1 for img in imgs
        if not img.get("width") or not img.get("height")
    )
    return {
        "id": "image_dimensions",
        "name": "Image Dimensions Specified",
        "category": "Performance",
        "status": "pass" if missing <= 3 else "warning",
        "value": f"{missing} image(s) missing dimensions",
        "detail": (
            "All images have explicit width and height attributes."
            if missing == 0
            else f"{missing} image(s) are missing explicit width/height attributes, risking layout shift (CLS)."
        ),
    }


def _check_content_wider_screen(soup):
    """Search for inline width styles > 1000px on block elements."""
    BLOCK_TAGS = {"div", "section", "article", "main", "aside", "header", "footer", "table"}
    wide_count = 0
    for tag in soup.find_all(BLOCK_TAGS):
        style = tag.get("style", "")
        for match in INLINE_WIDTH_RE.finditer(style):
            if float(match.group(1)) > 1000:
                wide_count += 1
                break
    return {
        "id": "content_wider_screen",
        "name": "Content Wider Than Screen",
        "category": "Layout",
        "status": "warning" if wide_count > 0 else "pass",
        "value": f"{wide_count} element(s) wider than 1000px",
        "detail": (
            "No elements with inline width > 1000px detected."
            if wide_count == 0
            else f"{wide_count} block element(s) have inline width > 1000px — may overflow on mobile screens."
        ),
    }


# ---------------------------------------------------------------------------
# Core Web Vitals helpers
# ---------------------------------------------------------------------------

def _parse_cwv(technical_seo):
    """Extract CWV estimates from technical_seo dict."""
    ts = technical_seo or {}

    ttfb = ts.get("cwv_ttfb_estimate", "Unknown")
    lcp = ts.get("cwv_lcp_estimate", "Unknown")
    cls = ts.get("cwv_cls_risk", "Unknown")
    perf_score = ts.get("performance_score", 0)
    ttfb_ms = ts.get("cwv_ttfb_ms", 0)

    def _rating(value, good_label="Good", warn_label="Needs Improvement"):
        if value in ("Good", good_label):
            return "pass"
        if value in ("Needs Improvement", warn_label):
            return "warning"
        if value in ("Poor", "High"):
            return "fail"
        return "info"

    # FCP estimated from TTFB
    try:
        ttfb_ms_val = float(ttfb_ms)
    except (TypeError, ValueError):
        ttfb_ms_val = 0

    if ttfb_ms_val < 200:
        fcp_label = "Good"
        fcp_status = "pass"
    elif ttfb_ms_val < 500:
        fcp_label = "Needs Improvement"
        fcp_status = "warning"
    else:
        fcp_label = "Poor"
        fcp_status = "fail"

    return {
        "ttfb": {"value": ttfb, "status": _rating(ttfb)},
        "lcp": {"value": lcp, "status": _rating(lcp)},
        "cls": {"value": cls, "status": _rating(cls, good_label="Low", warn_label="Medium")},
        "fcp": {"value": fcp_label, "status": fcp_status},
        "inp": {"value": "Requires Browser Measurement", "status": "info"},
        "perf_score": perf_score,
    }


# ---------------------------------------------------------------------------
# Issues builder
# ---------------------------------------------------------------------------

def _build_issues(checks, summary):
    """Generate SEO issue dicts from failed/warning checks and summary data."""
    issues = []

    check_map = {c["id"]: c for c in checks}

    vp = check_map.get("viewport_tag", {})
    if vp.get("status") == "fail":
        issues.append({
            "issue": "Missing viewport meta tag",
            "category": "Mobile SEO",
            "severity": "Critical",
            "recommendation": "Add <meta name='viewport' content='width=device-width, initial-scale=1'> to the <head>.",
            "impact_score": 9,
            "effort": "Low",
        })
    elif vp.get("status") == "warning":
        issues.append({
            "issue": "Incorrect viewport configuration",
            "category": "Mobile SEO",
            "severity": "High",
            "recommendation": "Set viewport content to 'width=device-width, initial-scale=1'.",
            "impact_score": 7,
            "effort": "Low",
        })

    if check_map.get("prevents_zoom", {}).get("status") == "warning":
        issues.append({
            "issue": "Viewport prevents user zoom",
            "category": "Accessibility",
            "severity": "Warning",
            "recommendation": "Remove user-scalable=no and maximum-scale=1 to allow user zoom.",
            "impact_score": 5,
            "effort": "Low",
        })

    if check_map.get("touch_targets", {}).get("status") == "warning":
        issues.append({
            "issue": "Small touch targets detected",
            "category": "Usability",
            "severity": "Warning",
            "recommendation": "Ensure all interactive elements are at least 44×44px.",
            "impact_score": 5,
            "effort": "Medium",
        })

    if check_map.get("font_size", {}).get("status") == "warning":
        issues.append({
            "issue": "Font sizes below 12px detected",
            "category": "Readability",
            "severity": "Warning",
            "recommendation": "Use a minimum font size of 12px for mobile readability.",
            "impact_score": 5,
            "effort": "Low",
        })

    if check_map.get("mobile_nav", {}).get("status") in ("warning", "fail"):
        issues.append({
            "issue": "No mobile navigation detected",
            "category": "Navigation",
            "severity": "Warning",
            "recommendation": "Implement a responsive navigation with a hamburger or toggle menu for mobile.",
            "impact_score": 4,
            "effort": "High",
        })

    form_check = check_map.get("form_usability", {})
    if form_check.get("status") == "warning":
        issues.append({
            "issue": (
                f"Form inputs missing labels or type attributes "
                f"({form_check.get('_missing_label', 0)} unlabelled, "
                f"{form_check.get('_missing_type', 0)} missing type)"
            ),
            "category": "Usability",
            "severity": "Medium",
            "recommendation": "Associate each input with a <label> or aria-label for accessibility.",
            "impact_score": 5,
            "effort": "Medium",
        })

    if check_map.get("intrusive_popups", {}).get("status") == "warning":
        count = check_map["intrusive_popups"].get("_popup_count", 0)
        issues.append({
            "issue": f"Intrusive popup/modal patterns detected ({count} element(s))",
            "category": "User Experience",
            "severity": "Warning",
            "recommendation": "Avoid intrusive interstitials that block content on mobile — they can incur a Google penalty.",
            "impact_score": 6,
            "effort": "Medium",
        })

    if check_map.get("responsive_images", {}).get("status") == "warning":
        issues.append({
            "issue": "No responsive images (srcset) detected",
            "category": "Performance",
            "severity": "Low",
            "recommendation": "Add srcset attributes to images for responsive image delivery across device sizes.",
            "impact_score": 4,
            "effort": "Medium",
        })

    if check_map.get("image_dimensions", {}).get("status") == "warning":
        issues.append({
            "issue": "Images missing explicit width/height dimensions",
            "category": "Performance",
            "severity": "Medium",
            "recommendation": "Add width and height attributes to all images to reduce Cumulative Layout Shift (CLS).",
            "impact_score": 6,
            "effort": "Low",
        })

    if check_map.get("content_wider_screen", {}).get("status") == "warning":
        issues.append({
            "issue": "Content wider than screen detected",
            "category": "Layout",
            "severity": "Warning",
            "recommendation": "Remove or replace fixed pixel widths > 1000px with responsive CSS units.",
            "impact_score": 6,
            "effort": "Medium",
        })

    return issues


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_mobile(soup, base_url="", technical_seo=None, advanced_data=None):
    """
    Mobile SEO and responsiveness analysis.

    Parameters
    ----------
    soup : BeautifulSoup
        Parsed HTML document.
    base_url : str
        Base URL of the audited page.
    technical_seo : dict, optional
        Existing audit data for CWV estimates.
    advanced_data : dict, optional
        Additional audit data (reserved for future use).

    Returns
    -------
    dict
        Comprehensive mobile analysis results.
    """
    technical_seo = technical_seo or {}
    advanced_data = advanced_data or {}

    # Run all checks
    raw_checks = [
        _check_viewport(soup),
        _check_prevents_zoom(soup),
        _check_responsive_framework(soup),
        _check_media_queries(soup),
        _check_touch_targets(soup),
        _check_font_size(soup),
        _check_mobile_nav(soup),
        _check_form_usability(soup),
        _check_intrusive_popups(soup),
        _check_cta_visibility(soup),
        _check_responsive_images(soup),
        _check_image_dimensions(soup),
        _check_content_wider_screen(soup),
    ]

    # Compute score: pass + info count / total
    passed_checks = sum(1 for c in raw_checks if c["status"] in ("pass", "info"))
    total_checks = len(raw_checks)
    mobile_score = round((passed_checks / total_checks) * 100) if total_checks > 0 else 0

    # Determine mobile friendly: no Critical or High issues
    issues = _build_issues(raw_checks, {})
    high_or_critical = any(i["severity"] in ("Critical", "High") for i in issues)
    is_mobile_friendly = not high_or_critical

    # CWV section
    cwv = _parse_cwv(technical_seo)

    # Summary counts
    check_map = {c["id"]: c for c in raw_checks}
    summary = {
        "viewport_ok": check_map.get("viewport_tag", {}).get("status") == "pass",
        "prevents_zoom": check_map.get("prevents_zoom", {}).get("status") == "warning",
        "has_nav": "yes" in check_map.get("mobile_nav", {}).get("value", ""),
        "form_issues": (
            check_map.get("form_usability", {}).get("_missing_label", 0)
            + check_map.get("form_usability", {}).get("_missing_type", 0)
        ),
        "popup_count": check_map.get("intrusive_popups", {}).get("_popup_count", 0),
        "cta_count": int(
            re.search(r"\d+", check_map.get("cta_visibility", {}).get("value", "0") or "0").group()
        ),
    }

    # Strip private keys from checks before returning
    cleaned_checks = []
    for c in raw_checks:
        cleaned = {k: v for k, v in c.items() if not k.startswith("_")}
        cleaned_checks.append(cleaned)

    return {
        "is_mobile_friendly": is_mobile_friendly,
        "mobile_score": mobile_score,
        "checks": cleaned_checks,
        "cwv": cwv,
        "issues": issues,
        "summary": summary,
        "passed_checks": passed_checks,
        "total_checks": total_checks,
    }

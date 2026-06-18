"""
image_auditor.py
Advanced image SEO analysis for SEO Technical Audit Dashboard.
"""

import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GENERIC_ALT_PATTERNS = {
    "image", "img", "photo", "pic", "picture", "banner", "logo", "icon",
    "thumbnail", "placeholder", "image1", "img1", "photo1", "screenshot",
    "untitled",
}

BAD_NAMING_RE = re.compile(
    r"^(img|image|dsc|screenshot|untitled|photo)\d*|image-final|IMG_\d+",
    re.IGNORECASE,
)

EXTENSION_TO_FORMAT = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WebP",
    "svg": "SVG",
    "gif": "GIF",
    "avif": "AVIF",
}

SIZE_LABELS = [
    (100 * 1024, "< 100KB"),
    (300 * 1024, "100–300KB"),
    (500 * 1024, "300–500KB"),
]


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _get_extension(url_or_path):
    """Return lowercased file extension without leading dot, or 'unknown'."""
    path = urlparse(url_or_path).path
    if "." in path:
        ext = path.rsplit(".", 1)[-1].lower().split("?")[0]
        return ext if ext else "unknown"
    return "unknown"


def _file_size_label(size_bytes):
    if size_bytes is None:
        return "Unknown"
    for threshold, label in SIZE_LABELS:
        if size_bytes < threshold:
            return label
    return "> 500KB"


def _is_keyword_stuffed(alt_text):
    """Flag if alt text > 100 chars or if more than 6 words are all the same."""
    if len(alt_text) > 100:
        return True
    words = alt_text.lower().split()
    if len(words) > 6:
        unique = set(words)
        if len(unique) == 1:
            return True
    return False


def _alt_status(alt_attr):
    """
    Classify alt attribute.
    Returns: "missing" | "empty" | "generic" | "keyword_stuffed" | "ok"
    """
    if alt_attr is None:
        return "missing"
    stripped = alt_attr.strip()
    if stripped == "":
        return "empty"
    if _is_keyword_stuffed(stripped):
        return "keyword_stuffed"
    if stripped.lower() in GENERIC_ALT_PATTERNS:
        return "generic"
    return "ok"


def _naming_quality(filename):
    """Return "bad" if filename matches bad naming patterns, else "good"."""
    if not filename:
        return "bad"
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return "bad" if BAD_NAMING_RE.search(stem) else "good"


def _resolve_url(src, base_url):
    """Resolve src to absolute URL using base_url."""
    if not src:
        return ""
    return urljoin(base_url, src) if base_url else src


def _fetch_size(url):
    """HEAD request to get Content-Length. Returns (url, size_bytes or None)."""
    if not REQUESTS_AVAILABLE:
        return url, None
    try:
        resp = requests.head(
            url,
            timeout=5,
            allow_redirects=True,
            verify=False,
            headers={"User-Agent": "SEO-Audit-Bot/1.0"},
        )
        cl = resp.headers.get("Content-Length")
        return url, int(cl) if cl and cl.isdigit() else None
    except Exception:
        return url, None


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def _extract_image_data(soup, base_url):
    """
    Extract metadata for every <img> and <source> tag in the document.
    Returns list of image dicts.
    """
    images = []

    for tag in soup.find_all(["img", "source"]):
        # Determine source URL
        src = tag.get("src") or tag.get("data-src") or tag.get("data-lazy-src") or ""
        if tag.name == "source":
            src = tag.get("srcset", "").split(",")[0].split()[0] if tag.get("srcset") else src

        url = _resolve_url(src, base_url)
        path = urlparse(url).path
        name = path.rsplit("/", 1)[-1] if "/" in path else path

        ext = _get_extension(url)
        format_label = EXTENSION_TO_FORMAT.get(ext, "Unknown")

        alt_attr = tag.get("alt")  # None if missing, "" if empty
        a_status = _alt_status(alt_attr)

        has_lazy = tag.get("loading", "").lower() == "lazy"

        raw_width = tag.get("width")
        raw_height = tag.get("height")
        try:
            width = int(raw_width) if raw_width else None
        except (ValueError, TypeError):
            width = None
        try:
            height = int(raw_height) if raw_height else None
        except (ValueError, TypeError):
            height = None
        has_dimensions = width is not None and height is not None

        has_srcset = bool(tag.get("srcset"))

        # Check if inside <picture>
        is_in_picture = tag.find_parent("picture") is not None

        nq = _naming_quality(name)

        per_image_issues = []
        if a_status == "missing":
            per_image_issues.append("Missing alt text")
        elif a_status == "empty":
            per_image_issues.append("Empty alt text")
        elif a_status == "generic":
            per_image_issues.append("Generic alt text")
        elif a_status == "keyword_stuffed":
            per_image_issues.append("Keyword-stuffed alt text")
        if not has_lazy:
            per_image_issues.append("Missing lazy loading")
        if not has_dimensions:
            per_image_issues.append("Missing width/height dimensions")
        if nq == "bad":
            per_image_issues.append("Poor filename convention")
        if ext in ("jpg", "jpeg", "png"):
            per_image_issues.append("Could be converted to WebP/AVIF")

        images.append({
            "url": url,
            "name": name,
            "extension": ext,
            "format_label": format_label,
            "alt_text": alt_attr,
            "alt_status": a_status,
            "has_lazy": has_lazy,
            "width": width,
            "height": height,
            "has_dimensions": has_dimensions,
            "has_srcset": has_srcset,
            "is_in_picture": is_in_picture,
            "naming_quality": nq,
            "file_size_bytes": None,
            "file_size_label": "Unknown",
            "issues": per_image_issues,
        })

    return images


def _populate_sizes(images, max_size_checks):
    """
    Make HEAD requests for up to max_size_checks unique image URLs
    and populate file_size_bytes / file_size_label.
    """
    if not REQUESTS_AVAILABLE:
        return

    seen = {}
    to_check = []
    for img in images:
        url = img["url"]
        if url and url not in seen and len(to_check) < max_size_checks:
            to_check.append(url)
            seen[url] = None

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(_fetch_size, to_check))

    size_map = {url: size for url, size in results}

    for img in images:
        url = img["url"]
        if url in size_map:
            size_bytes = size_map[url]
            img["file_size_bytes"] = size_bytes
            img["file_size_label"] = _file_size_label(size_bytes)
            # Update large image issue flag
            if size_bytes is not None and size_bytes > 300 * 1024:
                if "Large file size (> 300KB)" not in img["issues"]:
                    img["issues"].append("Large file size (> 300KB)")


def _compute_summary(images, check_sizes):
    """Compute aggregate summary counts."""
    total = len(images)
    missing_alt = sum(1 for i in images if i["alt_status"] == "missing")
    empty_alt = sum(1 for i in images if i["alt_status"] == "empty")
    generic_alt = sum(1 for i in images if i["alt_status"] == "generic")
    keyword_stuffed_alt = sum(1 for i in images if i["alt_status"] == "keyword_stuffed")
    no_lazy = sum(1 for i in images if not i["has_lazy"])
    no_dimensions = sum(1 for i in images if not i["has_dimensions"])
    non_webp = sum(1 for i in images if i["extension"] in ("jpg", "jpeg", "png"))
    bad_naming = sum(1 for i in images if i["naming_quality"] == "bad")

    # Duplicate alt detection (same non-empty alt on 2+ images)
    alt_counter = defaultdict(int)
    for img in images:
        if img["alt_text"] and img["alt_text"].strip():
            alt_counter[img["alt_text"].strip().lower()] += 1
    duplicate_alt = sum(1 for count in alt_counter.values() if count > 1)

    large_images = 0
    if check_sizes:
        large_images = sum(
            1 for i in images
            if i["file_size_bytes"] is not None and i["file_size_bytes"] > 300 * 1024
        )

    format_breakdown = defaultdict(int)
    for img in images:
        format_breakdown[img["format_label"]] += 1

    return {
        "total": total,
        "missing_alt": missing_alt,
        "empty_alt": empty_alt,
        "generic_alt": generic_alt,
        "keyword_stuffed_alt": keyword_stuffed_alt,
        "duplicate_alt": duplicate_alt,
        "no_lazy": no_lazy,
        "no_dimensions": no_dimensions,
        "non_webp_jpg_png": non_webp,
        "bad_naming": bad_naming,
        "large_images": large_images,
        "format_breakdown": dict(format_breakdown),
    }


def _build_issues(summary, check_sizes):
    """Build list of SEO issue dicts from summary counts."""
    issues = []
    n = summary

    if n["missing_alt"] > 0:
        issues.append({
            "issue": f"Missing alt text on {n['missing_alt']} image(s)",
            "category": "Image SEO",
            "severity": "High",
            "recommendation": "Add descriptive alt text to all images for accessibility and SEO.",
            "impact_score": 7,
            "effort": "Medium",
        })

    if n["empty_alt"] > 0:
        issues.append({
            "issue": f"Empty alt text on {n['empty_alt']} image(s)",
            "category": "Image SEO",
            "severity": "Medium",
            "recommendation": "Provide meaningful alt text; use alt='' only for purely decorative images.",
            "impact_score": 5,
            "effort": "Low",
        })

    if n["generic_alt"] > 0:
        issues.append({
            "issue": f"Generic alt text on {n['generic_alt']} image(s)",
            "category": "Image SEO",
            "severity": "Low",
            "recommendation": "Replace generic alt text with descriptive, keyword-relevant descriptions.",
            "impact_score": 3,
            "effort": "Medium",
        })

    if n["keyword_stuffed_alt"] > 0:
        issues.append({
            "issue": f"Keyword-stuffed alt text on {n['keyword_stuffed_alt']} image(s)",
            "category": "Image SEO",
            "severity": "Warning",
            "recommendation": "Keep alt text concise and natural; avoid over-optimisation.",
            "impact_score": 5,
            "effort": "Low",
        })

    if n["duplicate_alt"] > 0:
        issues.append({
            "issue": f"Duplicate alt text on {n['duplicate_alt']} image(s)",
            "category": "Image SEO",
            "severity": "Warning",
            "recommendation": "Use unique alt text for each image to provide distinct context.",
            "impact_score": 4,
            "effort": "Medium",
        })

    if n["no_lazy"] > 0:
        issues.append({
            "issue": f"{n['no_lazy']} image(s) missing lazy loading",
            "category": "Performance",
            "severity": "Low",
            "recommendation": "Add loading='lazy' to below-the-fold images to improve page load speed.",
            "impact_score": 4,
            "effort": "Low",
        })

    if n["no_dimensions"] > 0:
        issues.append({
            "issue": f"{n['no_dimensions']} image(s) missing width/height dimensions",
            "category": "Performance",
            "severity": "Medium",
            "recommendation": "Specify width and height attributes to prevent layout shifts (CLS).",
            "impact_score": 6,
            "effort": "Low",
        })

    if n["non_webp_jpg_png"] > 0:
        issues.append({
            "issue": f"{n['non_webp_jpg_png']} image(s) could be converted to WebP",
            "category": "Performance",
            "severity": "Low",
            "recommendation": "Convert JPEG/PNG images to WebP or AVIF for better compression.",
            "impact_score": 4,
            "effort": "Medium",
        })

    if n["bad_naming"] > 0:
        issues.append({
            "issue": f"{n['bad_naming']} image(s) have poor filename conventions",
            "category": "Image SEO",
            "severity": "Low",
            "recommendation": "Use descriptive, hyphen-separated filenames instead of generic names like img001.jpg.",
            "impact_score": 3,
            "effort": "Medium",
        })

    if check_sizes and n["large_images"] > 0:
        issues.append({
            "issue": f"{n['large_images']} image(s) are larger than 300KB",
            "category": "Performance",
            "severity": "High",
            "recommendation": "Compress images or switch to a more efficient format to reduce file size.",
            "impact_score": 8,
            "effort": "Medium",
        })

    return issues


def _format_opportunity(images):
    """Return list of images where extension is jpg/png (WebP/AVIF upgrade candidates)."""
    return [
        img for img in images if img["extension"] in ("jpg", "jpeg", "png")
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_images_advanced(soup, base_url="", check_sizes=False, max_size_checks=30):
    """
    Advanced image SEO analysis.

    Parameters
    ----------
    soup : BeautifulSoup
        Parsed HTML document.
    base_url : str
        Base URL for resolving relative image paths.
    check_sizes : bool
        If True, perform HEAD requests to fetch file sizes.
    max_size_checks : int
        Maximum number of unique URLs to check for file size.

    Returns
    -------
    dict
        Comprehensive image analysis results.
    """
    images = _extract_image_data(soup, base_url)

    if check_sizes and images:
        _populate_sizes(images, max_size_checks)

    summary = _compute_summary(images, check_sizes)
    issues = _build_issues(summary, check_sizes)
    format_opportunity = _format_opportunity(images)

    return {
        "images": images,
        "summary": summary,
        "format_breakdown": summary["format_breakdown"],
        "format_opportunity": format_opportunity,
        "issues": issues,
        # Flat access for page_image_seo() KPI strip and overview table
        "total": summary["total"],
        "missing_alt": summary["missing_alt"],
        "empty_alt": summary["empty_alt"],
        "generic_alt": summary["generic_alt"],
        "keyword_stuffed_alt": summary["keyword_stuffed_alt"],
        "duplicate_alt": summary["duplicate_alt"],
        "no_lazy": summary["no_lazy"],
        "no_dimensions": summary["no_dimensions"],
        "non_webp_jpg_png": summary["non_webp_jpg_png"],
        "bad_naming": summary["bad_naming"],
        "large_images": summary["large_images"],
    }

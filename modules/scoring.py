"""SEO Health Score calculation (0–100)."""

WEIGHTS = {
    "metadata":       0.20,
    "headings":       0.10,
    "canonical":      0.05,
    "indexability":   0.05,
    "url_structure":  0.05,
    "content":        0.20,
    "images":         0.10,
    "internal_links": 0.15,
    "external_links": 0.05,
    "page_specific":  0.05,
}

PENALTY = {
    "Critical": 25,
    "High":     15,
    "Warning":  8,
    "Medium":   5,
    "Low":      2,
}


def _category_score(issues):
    if not issues:
        return 100.0
    penalty = sum(PENALTY.get(i.get("severity", "Low"), 2) for i in issues)
    return max(0.0, 100.0 - penalty)


def calculate_seo_score(result):
    breakdown = {
        "metadata":       _category_score(result.get("metadata", {}).get("issues", [])),
        "headings":       _category_score(result.get("headings", {}).get("issues", [])),
        "canonical":      _category_score(result.get("canonical", {}).get("issues", [])),
        "indexability":   _category_score(result.get("indexability", {}).get("issues", [])),
        "url_structure":  _category_score(result.get("url_structure", {}).get("issues", [])),
        "content":        _category_score(result.get("content", {}).get("issues", [])),
        "images":         _category_score(result.get("images", {}).get("issues", [])),
        "internal_links": _category_score(result.get("internal_links", {}).get("issues", [])),
        "external_links": _category_score(result.get("external_links", {}).get("issues", [])),
        "page_specific":  _category_score(
            result.get("course_audit", {}).get("issues", []) +
            result.get("blog_audit", {}).get("issues", [])
        ),
    }

    total = sum(breakdown[cat] * weight for cat, weight in WEIGHTS.items())

    # Status-code adjustments
    status = result.get("status_code", 200)
    if result.get("fetch_error") or status == 0:
        total = 0.0
    elif status >= 400:
        total = max(0.0, total - 50)
    elif 300 <= status < 400:
        total = max(0.0, total - 10)

    return {"score": round(total, 1), "breakdown": breakdown}


def get_score_label(score):
    if score >= 90:
        return "Excellent"
    elif score >= 75:
        return "Good"
    elif score >= 50:
        return "Needs Attention"
    return "Critical"


def get_score_color(score):
    if score >= 90:
        return "#10B981"
    elif score >= 75:
        return "#3B82F6"
    elif score >= 50:
        return "#F59E0B"
    return "#EF4444"


def get_severity_color(severity):
    colors = {
        "Critical": "#EF4444",
        "High":     "#F97316",
        "Warning":  "#F59E0B",
        "Medium":   "#EAB308",
        "Low":      "#3B82F6",
    }
    return colors.get(severity, "#6B7280")

"""SEO Health Score calculation (0–100) with thematic category grouping."""

WEIGHTS = {
    "metadata":        0.18,
    "headings":        0.09,
    "canonical":       0.05,
    "indexability":    0.06,
    "url_structure":   0.05,
    "content":         0.17,
    "images":          0.08,
    "internal_links":  0.13,
    "external_links":  0.05,
    "advanced":        0.09,   # mobile, schema, social, hreflang
    "page_specific":   0.05,   # course / blog
}

PENALTY = {
    "Critical": 25,
    "High":     15,
    "Medium":   8,
    "Warning":  6,   # Warning < Medium — it is a caution, not a confirmed problem
    "Low":      2,
}

# SEMrush-style thematic groupings
THEMES = {
    "Crawlability": ["Accessibility", "Redirects", "Indexability", "URL Structure"],
    "Metadata":     ["Metadata"],
    "Content":      ["Content", "Headings", "Readability"],
    "Links":        ["Internal Links", "External Links"],
    "Technical":    ["Canonical", "Technical", "Mobile", "Performance"],
    "Social & Schema": ["Structured Data", "Social SEO", "International SEO"],
    "Images":       ["Images"],
    "Page-Specific": ["Course Content", "Blog Content", "Conversion"],
}


def _category_score(issues):
    if not issues:
        return 100.0
    penalty = sum(PENALTY.get(i.get("severity", "Low"), 2) for i in issues)
    return max(0.0, 100.0 - penalty)


def calculate_seo_score(result):
    breakdown = {
        "metadata":       _category_score(result.get("metadata",    {}).get("issues", [])),
        "headings":       _category_score(result.get("headings",    {}).get("issues", [])),
        "canonical":      _category_score(result.get("canonical",   {}).get("issues", [])),
        "indexability":   _category_score(result.get("indexability",{}).get("issues", [])),
        "url_structure":  _category_score(result.get("url_structure",{}).get("issues", [])),
        "content":        _category_score(result.get("content",     {}).get("issues", [])),
        "images":         _category_score(result.get("images",      {}).get("issues", [])),
        "internal_links": _category_score(result.get("internal_links",{}).get("issues", [])),
        "external_links": _category_score(result.get("external_links",{}).get("issues", [])),
        "advanced":       _category_score(
                              result.get("advanced", {}).get("issues", []) +
                              result.get("redirect_analysis", {}).get("issues", [])
                          ),
        "page_specific":  _category_score(
                              result.get("course_audit", {}).get("issues", []) +
                              result.get("blog_audit",   {}).get("issues", [])
                          ),
    }

    total = sum(breakdown[cat] * weight for cat, weight in WEIGHTS.items())

    status = result.get("status_code", 200)
    if result.get("fetch_error") or status == 0:
        total = 0.0
    elif status >= 400:
        total = max(0.0, total - 50)
    elif 300 <= status < 400:
        total = max(0.0, total - 10)

    return {"score": round(total, 1), "breakdown": breakdown}


def get_thematic_issues(all_issues):
    """Group issues into SEMrush-style thematic categories."""
    grouped = {theme: [] for theme in THEMES}
    other = []
    for issue in all_issues:
        cat = issue.get("category", "")
        placed = False
        for theme, categories in THEMES.items():
            if any(c.lower() in cat.lower() for c in categories):
                grouped[theme].append(issue)
                placed = True
                break
        if not placed:
            other.append(issue)
    if other:
        grouped["Other"] = other
    return {k: v for k, v in grouped.items() if v}


def get_top_issues_by_impact(all_issues, top_n=10):
    """Return top N issues sorted by impact_score descending."""
    sorted_issues = sorted(all_issues, key=lambda x: x.get("impact_score", 0), reverse=True)
    return sorted_issues[:top_n]



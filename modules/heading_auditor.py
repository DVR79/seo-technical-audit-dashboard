"""
heading_auditor.py
Deep heading structure analysis for SEO Technical Audit Dashboard.
"""

import html as _html
import re
from collections import defaultdict


# Color map for heading levels in tree visualization
HEADING_COLORS = {
    1: "#1E40AF",
    2: "#047857",
    3: "#92400E",
    4: "#6B21A8",
    5: "#9D174D",
    6: "#374151",
}


def _extract_headings(soup):
    """Extract all h1-h6 tags in document order with metadata."""
    headings = []
    position = 0
    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        level = int(tag.name[1])
        text = tag.get_text(separator=" ", strip=True)
        id_attr = tag.get("id", None)
        is_empty = len(text) == 0
        headings.append({
            "level": level,
            "text": text,
            "position": position,
            "is_empty": is_empty,
            "length": len(text),
            "id_attr": id_attr,
        })
        position += 1
    return headings


def _count_headings(headings):
    """Return dict with counts per level h1..h6."""
    counts = {f"h{i}": 0 for i in range(1, 7)}
    for h in headings:
        counts[f"h{h['level']}"] += 1
    return counts


def _detect_sequence_violations(headings):
    """
    Flag heading level skips: current_level > prev_level + 1.
    Returns list of violation dicts.
    """
    violations = []
    prev_level = 0
    for h in headings:
        current_level = h["level"]
        if prev_level > 0 and current_level > prev_level + 1:
            violations.append({
                "position": h["position"],
                "from_level": prev_level,
                "to_level": current_level,
                "heading_text": h["text"],
            })
        prev_level = current_level
    return violations


def _detect_empty_headings(headings):
    """Return list of headings that are empty."""
    return [h for h in headings if h["is_empty"]]


def _detect_duplicate_headings(headings):
    """
    Return dict: level (str) → list of duplicate texts (case-insensitive).
    Only lists texts that appear more than once.
    """
    level_texts = defaultdict(list)
    for h in headings:
        level_texts[f"h{h['level']}"].append(h["text"].lower())

    duplicates = {}
    for level, texts in level_texts.items():
        seen = defaultdict(int)
        for t in texts:
            seen[t] += 1
        dupes = [t for t, count in seen.items() if count > 1]
        if dupes:
            duplicates[level] = dupes
    return duplicates


def _check_keyword_coverage(headings, title):
    """
    For each word in title with length > 4 chars, check if it appears
    in any h1 or h2 text (case-insensitive).
    Returns dict: keyword → bool (found or not).
    """
    if not title:
        return {}

    keywords = [w.lower() for w in re.findall(r"\w+", title) if len(w) > 4]
    if not keywords:
        return {}

    h1_h2_text = " ".join(
        h["text"].lower() for h in headings if h["level"] in (1, 2)
    )

    coverage = {}
    for kw in keywords:
        coverage[kw] = kw in h1_h2_text
    return coverage


def _build_tree_html(headings):
    """
    Build a nested <ul>/<li> HTML tree visualization of the heading structure.
    Color-coded per level. Skipped levels marked with ⚠️.
    """
    if not headings:
        return "<p style='color:#9CA3AF;font-style:italic;'>No headings found.</p>"

    lines = []
    stack = []  # stack of levels currently open

    def close_until(target_level):
        while stack and stack[-1] > target_level:
            lines.append("</ul>")
            stack.pop()

    def open_level(level):
        indent = (level - 1) * 20
        lines.append(f"<ul style='list-style:none;padding-left:{indent}px;margin:2px 0;'>")
        stack.append(level)

    prev_level = 0
    for h in headings:
        level = h["level"]
        color = HEADING_COLORS.get(level, "#374151")
        text = _html.escape(h["text"]) if not h["is_empty"] else "<em>(empty)</em>"
        label = f"H{level}"

        skip_marker = ""
        if prev_level > 0 and level > prev_level + 1:
            skip_marker = " ⚠️"

        if level > prev_level:
            # Going deeper
            for lv in range(prev_level + 1, level + 1):
                if lv == level:
                    open_level(lv)
                else:
                    # Phantom open for skipped level
                    indent = (lv - 1) * 20
                    lines.append(f"<ul style='list-style:none;padding-left:{indent}px;margin:2px 0;'>")
                    stack.append(lv)
        elif level < prev_level:
            close_until(level)
            if not stack or stack[-1] != level:
                open_level(level)
        else:
            # Same level — ensure list is open
            if not stack or stack[-1] != level:
                open_level(level)

        empty_style = "font-style:italic;opacity:0.55;" if h["is_empty"] else ""
        lines.append(
            f"<li style='margin:3px 0;{empty_style}'>"
            f"<span style='background:{color};color:#fff;border-radius:4px;"
            f"padding:1px 7px;font-size:.72rem;font-weight:700;margin-right:8px;"
            f"display:inline-block;min-width:28px;text-align:center'>{label}</span>"
            f"<span style='font-size:.84rem;'>{text}{skip_marker}</span>"
            f"</li>"
        )
        prev_level = level

    # Close all open lists
    while stack:
        lines.append("</ul>")
        stack.pop()

    return "\n".join(lines)


def _build_issues(headings, counts, violations, empty_headings, duplicate_headings, h1_list):
    """Generate SEO issue dicts based on analysis results."""
    issues = []

    # Missing H1
    if counts["h1"] == 0:
        issues.append({
            "issue": "Missing H1 heading",
            "category": "Heading Structure",
            "severity": "Critical",
            "recommendation": "Add a single, descriptive H1 heading that includes your primary keyword.",
            "impact_score": 9,
            "effort": "Low",
        })

    # Multiple H1
    if counts["h1"] > 1:
        issues.append({
            "issue": f"Multiple H1 headings found ({counts['h1']})",
            "category": "Heading Structure",
            "severity": "High",
            "recommendation": "Use only one H1 per page to clearly signal the primary topic to search engines.",
            "impact_score": 7,
            "effort": "Low",
        })

    # H1 too long / too short
    for h in h1_list:
        if h["length"] > 70:
            issues.append({
                "issue": f"H1 heading is too long ({h['length']} chars)",
                "category": "Heading Structure",
                "severity": "Warning",
                "recommendation": "Keep the H1 under 70 characters for optimal display and relevance.",
                "impact_score": 5,
                "effort": "Low",
            })
        if 0 < h["length"] < 10:
            issues.append({
                "issue": f"H1 heading is too short ({h['length']} chars)",
                "category": "Heading Structure",
                "severity": "Low",
                "recommendation": "Make the H1 more descriptive (at least 10 characters).",
                "impact_score": 4,
                "effort": "Low",
            })

    # Skipped heading levels — one issue per violation
    for v in violations:
        issues.append({
            "issue": (
                f"Skipped heading level: H{v['from_level']} → H{v['to_level']} "
                f"(position {v['position']})"
            ),
            "category": "Heading Structure",
            "severity": "Warning",
            "recommendation": (
                f"Do not skip from H{v['from_level']} to H{v['to_level']}. "
                f"Use sequential heading levels to maintain document outline."
            ),
            "impact_score": 5,
            "effort": "Low",
        })

    # Empty headings
    if empty_headings:
        issues.append({
            "issue": f"Empty heading detected ({len(empty_headings)} found)",
            "category": "Heading Structure",
            "severity": "Medium",
            "recommendation": "Remove or fill empty heading tags — they confuse screen readers and crawlers.",
            "impact_score": 6,
            "effort": "Low",
        })

    # Duplicate headings (H1, H2, H3)
    for level in ("h1", "h2", "h3"):
        if level in duplicate_headings:
            dupes = duplicate_headings[level]
            issues.append({
                "issue": f"Duplicate {level.upper()} headings found: {', '.join(dupes[:3])}",
                "category": "Heading Structure",
                "severity": "Warning",
                "recommendation": f"Ensure each {level.upper()} has unique text to avoid confusion for users and crawlers.",
                "impact_score": 5,
                "effort": "Medium",
            })

    # No H2 when H1 exists
    if counts["h1"] >= 1 and counts["h2"] == 0:
        issues.append({
            "issue": "No H2 headings found despite H1 being present",
            "category": "Heading Structure",
            "severity": "Warning",
            "recommendation": "Add H2 subheadings to break content into logical sections and improve scannability.",
            "impact_score": 4,
            "effort": "Medium",
        })

    return issues


def analyze_heading_structure(soup, title=""):
    """
    Deep heading structure analysis.

    Parameters
    ----------
    soup : BeautifulSoup
        Parsed HTML document.
    title : str, optional
        Page title used for keyword coverage check.

    Returns
    -------
    dict
        Comprehensive heading analysis results.
    """
    headings = _extract_headings(soup)
    counts = _count_headings(headings)

    h1_list = [h for h in headings if h["level"] == 1]
    h1_text = (h1_list[0]["text"] if h1_list and not h1_list[0]["is_empty"] else "")

    sequence_violations = _detect_sequence_violations(headings)
    empty_headings = _detect_empty_headings(headings)
    duplicate_headings = _detect_duplicate_headings(headings)
    keyword_coverage = _check_keyword_coverage(headings, title)
    tree_html = _build_tree_html(headings)
    issues = _build_issues(
        headings, counts, sequence_violations, empty_headings, duplicate_headings, h1_list
    )

    return {
        "headings": headings,
        "counts": counts,
        "h1_text": h1_text,
        "sequence_violations": sequence_violations,
        "empty_headings": empty_headings,
        "duplicate_headings": duplicate_headings,
        "keyword_coverage": keyword_coverage,
        "tree_html": tree_html,
        "issues": issues,
        "total_headings": len(headings),
    }

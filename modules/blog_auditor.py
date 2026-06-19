"""Blog-page-specific SEO content checks."""

import re


BLOG_ELEMENTS = [
    ("Author Information",  ["author", "written by", "by ", "posted by"]),
    ("Published Date",      None),   # checked via tags + meta
    ("Updated Date",        ["updated", "last updated", "modified", "last modified"]),
    ("Introduction",        ["introduction", "in this article", "in this blog", "in this post",
                              "in this guide", "overview"]),
    ("Conclusion Section",  ["conclusion", "summary", "in conclusion", "to summarise", "final thoughts",
                              "wrapping up", "key takeaways"]),
    ("FAQ Section",         ["faq", "frequently asked questions", "questions and answers"]),
    ("Table of Contents",   ["table of contents", "jump to", "skip to", "in this article:"]),
]

MIN_BLOG_WORDS = 800
GOOD_BLOG_WORDS = 1500


def audit_blog_page(soup, url):
    issues = []
    raw_text  = soup.get_text(separator=" ")
    page_text = raw_text.lower()

    # Blog elements
    elements_found = {}
    for element_name, keywords in BLOG_ELEMENTS:
        if element_name == "Published Date":
            date_tags = soup.find_all(
                ["time", "span", "div", "p"],
                class_=re.compile(r"date|time|publish|posted", re.I),
            )
            meta_date = soup.find("meta", property="article:published_time")
            found = bool(date_tags or meta_date)
        else:
            found = any(kw in page_text for kw in (keywords or []))
        elements_found[element_name] = found

        if not found:
            severity_map = {
                "Author Information": "High",
                "Published Date": "High",
                "Introduction": "Medium",
                "Conclusion Section": "Medium",
                "FAQ Section": "Medium",
                "Updated Date": "Low",
                "Table of Contents": "Low",
            }
            issues.append({
                "issue": f"Missing {element_name}",
                "category": "Blog Content",
                "severity": severity_map.get(element_name, "Low"),
                "recommendation": f"Add '{element_name}' to improve content quality and E-E-A-T signals.",
            })

    # Word count — reuse raw_text from above
    words = [w for w in raw_text.split() if len(w) > 1]
    word_count = len(words)
    reading_time = round(word_count / 200, 1)

    if word_count < MIN_BLOG_WORDS:
        issues.append({
            "issue": f"Blog Too Short ({word_count} words)",
            "category": "Blog Content",
            "severity": "High",
            "recommendation": f"Expand content to at least {MIN_BLOG_WORDS} words for competitive blog rankings.",
        })
    elif word_count < GOOD_BLOG_WORDS:
        issues.append({
            "issue": f"Below Recommended Blog Length ({word_count} words)",
            "category": "Blog Content",
            "severity": "Warning",
            "recommendation": f"Aim for {GOOD_BLOG_WORDS}+ words to outperform competitors in search.",
        })

    # Schema
    schema_tags = soup.find_all("script", type="application/ld+json")
    has_article_schema = any(
        any(x in tag.get_text() for x in ["Article", "BlogPosting", "NewsArticle"])
        for tag in schema_tags
    )
    if not has_article_schema:
        issues.append({
            "issue": "Missing Article Schema Markup",
            "category": "Structured Data",
            "severity": "Medium",
            "recommendation": "Add BlogPosting schema (JSON-LD) to enhance rich snippets.",
        })

    # Open Graph
    og_title = soup.find("meta", property="og:title")
    og_desc = soup.find("meta", property="og:description")
    og_image = soup.find("meta", property="og:image")
    missing_og = [x for x, tag in [("og:title", og_title), ("og:description", og_desc), ("og:image", og_image)] if not tag]
    if missing_og:
        issues.append({
            "issue": f"Missing Open Graph Tags: {', '.join(missing_og)}",
            "category": "Social SEO",
            "severity": "Medium",
            "recommendation": "Add all og: meta tags for better social media sharing previews.",
        })

    # Readability
    sentences = re.split(r"[.!?]+", raw_text)
    sentence_count = max(len([s for s in sentences if len(s.strip()) > 10]), 1)
    avg_sentence_len = round(word_count / sentence_count, 1)
    readability = "Good"
    if avg_sentence_len > 25:
        readability = "Complex"
        issues.append({
            "issue": f"Long Average Sentence Length ({avg_sentence_len} words)",
            "category": "Readability",
            "severity": "Low",
            "recommendation": "Break long sentences into shorter ones (aim for under 20 words per sentence).",
        })

    elements_score = round(sum(1 for v in elements_found.values() if v) / len(elements_found) * 100, 1)

    return {
        "elements_found": elements_found,
        "has_article_schema": has_article_schema,
        "has_og_tags": not bool(missing_og),
        "word_count": word_count,
        "reading_time": reading_time,
        "readability_score": readability,
        "avg_sentence_length": avg_sentence_len,
        "elements_score": elements_score,
        "issues": issues,
    }

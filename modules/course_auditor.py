"""Course-page-specific SEO and conversion checks."""

COURSE_SECTIONS = [
    ("Course Overview",       ["overview", "about this course", "course summary", "about the course"]),
    ("Learning Objectives",   ["learning objectives", "what you'll learn", "what you will learn",
                                "learning outcomes", "key takeaways"]),
    ("Key Features",          ["key features", "course features", "highlights", "course highlights",
                                "what makes"]),
    ("Benefits Section",      ["benefits", "why take", "what you get", "course benefits", "advantages"]),
    ("Curriculum Section",    ["curriculum", "course content", "syllabus", "modules", "lessons",
                                "chapter", "topics covered"]),
    ("Trainer / Instructor",  ["trainer", "instructor", "about the trainer", "about the instructor",
                                "meet the trainer", "faculty", "expert"]),
    ("FAQ Section",           ["faq", "frequently asked questions", "common questions"]),
    ("CTA / Enrol Section",   ["enroll now", "enrol now", "register now", "get started", "sign up",
                                "book now", "request a callback", "apply now"]),
]

CONVERSION_CHECKS = [
    ("CTA Button",      ["enroll", "enrol", "register", "book", "get started", "apply now", "sign up"]),
    ("Lead / Inquiry Form", None),          # checked via soup
    ("Contact Section", ["contact us", "reach us", "get in touch"]),
    ("Price / Fee Section", ["fee", "price", "cost", "pricing", "investment"]),
]


def audit_course_page(soup, url):
    issues = []
    page_text = soup.get_text().lower()

    # Section completeness
    sections_found = {}
    for section_name, keywords in COURSE_SECTIONS:
        found = any(kw in page_text for kw in keywords)
        sections_found[section_name] = found
        if not found:
            severity = "High" if section_name in (
                "Curriculum Section", "CTA / Enrol Section", "Learning Objectives"
            ) else "Medium"
            issues.append({
                "issue": f"Missing {section_name}",
                "category": "Course Content",
                "severity": severity,
                "recommendation": (
                    f"Add a '{section_name}' section to improve page completeness and user confidence."
                ),
                "impact_score": 8 if severity == "High" else 5,
                "effort": "Medium",
            })

    # Conversion elements
    conversion_found = {}
    for element_name, keywords in CONVERSION_CHECKS:
        if element_name == "Lead / Inquiry Form":
            found = bool(soup.find("form"))
        else:
            found = any(kw in page_text for kw in (keywords or []))
        conversion_found[element_name] = found
        if not found and element_name in ("CTA Button", "Lead / Inquiry Form"):
            issues.append({
                "issue": f"Missing {element_name}",
                "category": "Conversion",
                "severity": "High",
                "recommendation": f"Add a {element_name} to improve lead generation.",
                "impact_score": 8,
                "effort": "Medium",
            })

    # Schema
    schema_tags = soup.find_all("script", type="application/ld+json")
    has_course_schema = any("Course" in tag.get_text() for tag in schema_tags)
    if not has_course_schema:
        issues.append({
            "issue": "Missing Course Schema Markup",
            "category": "Structured Data",
            "severity": "Medium",
            "recommendation": "Add Course schema (JSON-LD) to enhance rich results in search.",
            "impact_score": 6,
            "effort": "Medium",
        })

    sections_score = round(sum(1 for v in sections_found.values() if v) / len(sections_found) * 100, 1)

    return {
        "sections_found": sections_found,
        "conversion_elements": conversion_found,
        "has_course_schema": has_course_schema,
        "sections_score": sections_score,
        "issues": issues,
    }

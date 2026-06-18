# 🔍 SEO Technical Audit Dashboard

A modern, enterprise-grade Streamlit application for comprehensive SEO auditing — inspired by SEMrush, Ahrefs, Ubersuggest, and SEO Meta in 1 Click.

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://seo-technical-audit-dashboard-ub4xctw2yktn9smirs88ft.streamlit.app/)

**Live App:** [https://seo-technical-audit-dashboard-ub4xctw2yktn9smirs88ft.streamlit.app/](https://seo-technical-audit-dashboard-ub4xctw2yktn9smirs88ft.streamlit.app/)

---

## Features

### Core Audit Checks
| Feature | Details |
|---|---|
| **Metadata Audit** | Title, description length, OG tags, OG image validation |
| **Heading Hierarchy** | H1–H6 count, missing H1, hierarchy violations |
| **Canonical** | Self-referencing, relative URL resolution, missing canonical |
| **Indexability** | Noindex, X-Robots-Tag, robots.txt signals |
| **URL Structure** | Length, HTTPS, underscores vs hyphens, slug quality |
| **Content Quality** | Word count, thin content, reading time, content-to-HTML ratio |
| **Image SEO** | Missing/empty/generic alt text, total image count |
| **Redirect Chain** | Redirect count, chain depth, redirect loop detection |

### Link Auditing
| Feature | Details |
|---|---|
| **Internal Links** | Total, unique, dofollow/nofollow, broken, redirect, weak anchor text |
| **External Links** | Domain count, dofollow/nofollow, sponsored, UGC, missing noopener |
| **Broken Link Detection** | HTTP status validation for every link |
| **Security Attributes** | noopener, noreferrer on external links |

### Advanced Technical Checks (Inspired by SEMrush / Ahrefs)
| Feature | Details |
|---|---|
| **SERP Preview** | Live Google snippet mock with title/desc length warnings |
| **Social Card Preview** | Facebook/LinkedIn + Twitter/X card visual preview |
| **Schema / Structured Data** | JSON-LD type detection, parse error detection, raw JSON view |
| **Mobile-Friendliness** | Viewport meta tag check |
| **Charset** | Charset declaration validation |
| **Hreflang** | Tag detection, x-default check |
| **Twitter Cards** | All 4 required tags validated |
| **Favicon** | Presence check |
| **Duplicate Meta Detection** | Cross-URL duplicate titles, descriptions, H1s |

### Page-Type Specific
| Feature | Details |
|---|---|
| **Course Page Audit** | 8 required sections, conversion elements, Course schema |
| **Blog Page Audit** | Author, date, category, readability, Article schema, OG tags |
| **Auto-Detection** | Automatically classifies course / blog / general pages |

### Scoring & Recommendations (Inspired by Ubersuggest / Ahrefs)
| Feature | Details |
|---|---|
| **SEO Health Score** | Weighted 0–100 score across 11 categories |
| **Impact Score** | Each issue rated 1–10 (ranking importance) |
| **Effort Level** | Low / Medium / High effort label per issue |
| **Top Issues by Impact** | Priority-ranked recommendations, fix high-impact first |
| **Thematic Grouping** | SEMrush-style: Crawlability / Metadata / Content / Links / Technical / Social & Schema |
| **Radar Chart** | Visual per-category score breakdown |

### Export
| Format | Contents |
|---|---|
| **CSV** | Flat summary of all audited URLs |
| **Excel** | 3 sheets: Audit Summary + All Issues + Link Audit, colour-coded |
| **PDF** | Executive summary with colour-coded score table |

---

## Quick Start

### Local

```bash
git clone https://github.com/DVR79/seo-technical-audit-dashboard.git
cd seo-technical-audit-dashboard
pip install -r requirements.txt
streamlit run app.py
```

### Streamlit Cloud

1. Fork this repository
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Click **New app** → select this repo → set `app.py` as the main file
4. Click **Deploy**

---

## Project Structure

```
├── app.py                      # Main Streamlit application
├── requirements.txt            # Python dependencies
├── assets/
│   └── style.css               # Custom enterprise UI styles
└── modules/
    ├── __init__.py
    ├── auditor.py              # Core URL audit engine
    ├── advanced_checks.py      # SERP preview, schema, mobile, hreflang, social
    ├── link_auditor.py         # Internal & external link analysis
    ├── course_auditor.py       # Course-page checks
    ├── blog_auditor.py         # Blog-page checks
    ├── scoring.py              # SEO Health Score + thematic grouping
    └── report_generator.py     # CSV / Excel / PDF export
```

---

## SEO Score Breakdown

| Category | Weight | What it checks |
|---|---|---|
| Metadata | 18% | Title, description, OG tags |
| Content | 17% | Word count, thin content, ratio |
| Internal Links | 13% | Count, broken, anchor quality |
| Advanced | 9% | Schema, mobile, social, hreflang |
| Headings | 9% | H1 presence, hierarchy |
| Images | 8% | Alt text coverage |
| Indexability | 6% | Noindex, robots |
| Canonical | 5% | Self-referencing canonical |
| External Links | 5% | Security, dofollow quality |
| URL Structure | 5% | HTTPS, length, slug |
| Page-Specific | 5% | Course / Blog completeness |

**Score labels:** Excellent (90–100) · Good (75–89) · Needs Attention (50–74) · Critical (<50)

---

## Tech Stack

| Library | Purpose |
|---|---|
| [Streamlit](https://streamlit.io) | UI framework |
| [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) | HTML parsing |
| [lxml](https://lxml.de) | Fast XML/HTML parser |
| [Requests](https://requests.readthedocs.io) | HTTP crawling |
| [Pandas](https://pandas.pydata.org) | Data processing |
| [Plotly](https://plotly.com/python/) | Interactive charts |
| [fpdf2](https://pyfpdf.github.io/fpdf2/) | PDF generation |
| [XlsxWriter](https://xlsxwriter.readthedocs.io) | Excel export |

---

## License

MIT

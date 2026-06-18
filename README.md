# 🔍 SEO Technical Audit Dashboard

A modern, enterprise-grade Streamlit application for comprehensive SEO auditing of Course pages and Blog pages.

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://share.streamlit.io/user/dvr79)

---

## Features

- **Single URL Audit** — Instant audit of any URL
- **Bulk Audit** — Upload CSV/XLSX with hundreds of URLs
- **Sitemap Audit** — Extract and audit all URLs from an XML sitemap
- **Technical SEO Checks** — Metadata, headings, canonical, indexability, URL structure
- **Content Quality Analysis** — Word count, thin content, content-to-HTML ratio
- **Image SEO** — Missing/empty alt text detection
- **Internal Link Audit** — Count, dofollow/nofollow, broken links, redirect chains, anchor text
- **External Link Audit** — Domain analysis, noopener/noreferrer, broken links, sponsored links
- **Course Page Audit** — Section completeness, conversion elements, Course schema
- **Blog Page Audit** — Author, dates, readability, Article schema, OG tags
- **SEO Health Score** — Weighted 0–100 score with radar chart breakdown
- **AI Recommendations** — Prioritised, actionable fixes for every issue
- **Export Reports** — CSV, colour-coded Excel, PDF

---

## Quick Start

### Local

```bash
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
├── app.py                  # Main Streamlit application
├── requirements.txt        # Python dependencies
├── assets/
│   └── style.css           # Custom enterprise UI styles
└── modules/
    ├── auditor.py          # Core URL audit engine
    ├── link_auditor.py     # Internal & external link analysis
    ├── course_auditor.py   # Course-page checks
    ├── blog_auditor.py     # Blog-page checks
    ├── scoring.py          # SEO Health Score (0–100)
    └── report_generator.py # CSV / Excel / PDF export
```

---

## SEO Score Breakdown

| Category | Weight |
|---|---|
| Metadata | 20% |
| Content Quality | 20% |
| Internal Links | 15% |
| Headings | 10% |
| Images | 10% |
| External Links | 5% |
| Canonical | 5% |
| Indexability | 5% |
| URL Structure | 5% |
| Page-specific (Course/Blog) | 5% |

Score labels: **Excellent** (90–100) · **Good** (75–89) · **Needs Attention** (50–74) · **Critical** (<50)

---

## Tech Stack

- [Streamlit](https://streamlit.io) — UI framework
- [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) — HTML parsing
- [Requests](https://requests.readthedocs.io) — HTTP crawling
- [Pandas](https://pandas.pydata.org) — Data processing
- [Plotly](https://plotly.com/python/) — Interactive charts
- [fpdf2](https://pyfpdf.github.io/fpdf2/) — PDF generation
- [XlsxWriter](https://xlsxwriter.readthedocs.io) — Excel export

---

## License

MIT

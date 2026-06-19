# SEO Technical Audit Dashboard — Full Audit Log
**Date:** 2026-06-19  
**Reviewed by:** 5 parallel AI review agents (Security · UI/UX · Logic/Content · Performance/Quality · 5 Personal Perspectives)  
**Total findings:** 106  
**Persona ratings:** Sarah/SEO 5/10 · Raj/Dev 6/10 · Emma/A11y 2/10 · Carlos/Mobile 4/10 · Priya/SRE 3/10

---

## Legend
- `[x]` = Fixed  
- `[~]` = In progress  
- `[ ]` = Pending  
- **CRIT** / **HIGH** / **MED** / **LOW**

---

## BATCH 1 — Critical Security & Logic (commit: fix-critical-security-logic)

| # | Status | Sev | Category | File | Issue |
|---|--------|-----|----------|------|-------|
| S1 | `[x]` | CRIT | Security | `.gitignore` | `api_keys.json` never excluded — will be committed to git with all API keys in plaintext |
| S2 | `[x]` | CRIT | Security | `app.py:410-488` | XSS — page title/desc/og tags injected unescaped into `unsafe_allow_html` blocks |
| S3 | `[x]` | CRIT | Security | `app.py:305-335` | XSS — link URLs and anchor text unescaped in `st.html()` link table |
| L1 | `[x]` | CRIT | Logic | `modules/auditor.py:562` | `mobile_audit` issues never added to `all_issues` — all mobile SEO issues invisible |
| L2 | `[x]` | CRIT | Logic | `modules/scoring.py:17` | `Warning` penalty (8) > `Medium` penalty (5) — inverted severity/penalty relationship |
| L3 | `[x]` | CRIT | Logic | `modules/advanced_checks.py:72` | Missing HSTS header classified as "Critical" SEO issue (it's a security header, not SEO) |
| S4 | `[x]` | CRIT | Security | `modules/auditor.py:13` | `warnings.filterwarnings("ignore")` globally silences all security/SSL warnings |

---

## BATCH 2 — High Security & Logic (commit: fix-high-security-logic)

| # | Status | Sev | Category | File | Issue |
|---|--------|-----|----------|------|-------|
| S5 | `[x]` | HIGH | Security | `modules/auditor.py:47`, `link_auditor.py` | SSRF — user-supplied URLs reach internal network; no RFC-1918 blocking |
| S6 | `[x]` | HIGH | Security | `link_auditor.py:245`, `image_auditor.py:149` | `verify=False` used unconditionally — TLS certificates never validated |
| S7 | `[x]` | HIGH | Security | `modules/api_key_manager.py:387` | API keys appended to URLs as query params (Gemini, SerpAPI, Unsplash) |
| S8 | `[x]` | HIGH | Security | `modules/api_key_manager.py:284` | Masking algorithm exposes full key for short keys (≤8 chars) |
| S9 | `[x]` | HIGH | Security | `modules/auditor.py:598` | Raw exception messages with internal hostnames shown in UI |
| L4 | `[x]` | HIGH | Logic | `modules/scoring.py:53` | Score uses old `images{}` dict; Issues tab uses `image_detail{}` — decoupled |
| L5 | `[x]` | HIGH | Logic | `modules/scoring.py:48` | Score uses old `headings{}`; Issues tab uses `heading_detail{}` — decoupled |
| L6 | `[x]` | HIGH | Logic | `modules/blog_auditor.py:7` | `"by "` keyword → false-positive author detection on any page with "step by step" etc. |
| L7 | `[x]` | HIGH | Logic | `modules/image_auditor.py:240` | LCP image flagged for missing lazy loading — actively harmful advice |
| L8 | `[x]` | HIGH | Logic | `modules/advanced_checks.py:305` | Resource hints check fires on nearly every real website — near-universal false positive |
| L9 | `[x]` | HIGH | Logic | `modules/auditor.py:291` | URL special-char regex: `?&` never exist in path component; `%` is valid encoding |

---

## BATCH 3 — High UI/UX (commit: fix-high-uiux)

| # | Status | Sev | Category | File | Issue |
|---|--------|-----|----------|------|-------|
| U1 | `[x]` | HIGH | UI/UX | `app.py:~530` | Score banner uses hardcoded dark hex values — broken in light theme |
| U2 | `[x]` | HIGH | UI/UX | `assets/style.css:~215` | Sidebar gradient hardcoded — never flips for light mode |
| U3 | `[x]` | HIGH | UI/UX | `app.py:~2383` | `st.columns(8)` and `st.columns(9)` — KPI cards compress to ~100px, labels clip |
| U4 | `[x]` | HIGH | UI/UX | `app.py:~1693` | "Clear All Results" destructive button has no confirmation — one misclick wipes all data |
| U5 | `[x]` | HIGH | UI/UX | `app.py:~368` | Failed fetches show score=0 in table — looks like a critically bad page, not an error |
| U6 | `[x]` | HIGH | UI/UX | `app.py:~1704` | No back-navigation on detail pages — no breadcrumb or back button |
| P1 | `[x]` | HIGH | Perf | `app.py:28` | CSS file re-read from disk on every Streamlit rerun — uncached I/O |
| P2 | `[x]` | HIGH | Perf | `modules/link_auditor.py` | No `requests.Session()` — new TCP connection per URL; slow for bulk validation |

---

## BATCH 4 — Medium Security, Logic & Performance (commit: fix-medium-issues)

| # | Status | Sev | Category | File | Issue |
|---|--------|-----|----------|------|-------|
| S10 | `[x]` | MED | Security | `app.py:1498` | No URL count cap in bulk audit — DoS via large sitemap (500 URL limit needed) |
| S11 | `[x]` | MED | Security | `app.py:355` | User-uploaded sitemap XML parsed without size limit (10 MB cap needed) |
| S12 | `[x]` | MED | Security | `api_key_manager.py:284` | `.streamlit/api_keys.json` written without restricting file permissions (chmod 600) |
| L10 | `[x]` | MED | Logic | `modules/course_auditor.py:36` | course/blog issues missing `impact_score` and `effort` fields — always show 0/10 |
| L11 | `[x]` | MED | Logic | `modules/auditor.py:330` | Word count regex `[a-zA-Z]` skips non-English text → false "thin content" warnings |
| L12 | `[x]` | MED | Logic | `modules/advanced_checks.py:577` | "No Structured Data" fires on pages that don't need schema (contact, privacy, etc.) |
| L13 | `[x]` | MED | Logic | `modules/mobile_auditor.py:635` | `"info"` status counted as `"pass"` in mobile score — inflates score |
| L14 | `[x]` | MED | Logic | `modules/advanced_checks.py:50` | Compression check: false positive on CDN-served sites missing `Content-Encoding` header |
| P3 | `[x]` | MED | Perf | `app.py:~1135` | `all_issues` re-flattened on every render cycle — should be cached per result |
| P4 | `[x]` | MED | Perf | `modules/auditor.py` | `analyze_content` re-parses full HTML DOM (BeautifulSoup re-init) each call |
| U7 | `[x]` | MED | UI/UX | `app.py:~178` | Issue cards: `impact_score` not shown for course/blog issues (shows 0 because field missing) |
| U8 | `[x]` | MED | UI/UX | `app.py` | Empty state on fresh load: "No audit data yet" with no onboarding guidance |

---

## BATCH 5 — Low Priority & Documentation (commit: fix-low-and-docs)

| # | Status | Sev | Category | File | Issue |
|---|--------|-----|----------|------|-------|
| L15 | `[x]` | LOW | Logic | `modules/link_auditor.py:632` | Dofollow count >20 fires on legitimate resource-heavy pages |
| L16 | `[x]` | LOW | Logic | `modules/link_auditor.py:626` | "External links open in same tab" is UX opinion, not an SEO issue |
| L17 | `[x]` | LOW | Logic | `modules/advanced_checks.py:624` | SERP truncation at 57 chars, warning flag at 60 — inconsistent |
| L18 | `[x]` | LOW | Logic | `modules/auditor.py:29` | `MIN_DESC_LEN=120` is below 2024 best practice of 150 chars |
| L19 | `[x]` | LOW | Logic | `modules/auditor.py:300` | Slow response check at 3s duplicates advanced TTFB check at 200-500ms |
| L20 | `[x]` | LOW | Logic | `modules/advanced_checks.py:186` | AMP shown as ✅ positive signal — Google deprecated AMP for Search in 2021 |
| L21 | `[x]` | LOW | Logic | `modules/pagespeed.py:4` | PSI anonymous quota described as "100 req/day" — incorrect |
| S13 | `[x]` | LOW | Security | `requirements.txt` | All deps use `>=` floor only — no pinned versions, no lock file |
| S14 | `[x]` | LOW | Security | `api_key_manager.py` | Exception messages in `_test_*` may leak key material via URL in error string |
| P5 | `[x]` | LOW | Perf | `app.py` | Dead import `from functools import partial` — never used |
| P6 | `[x]` | LOW | Perf | `app.py` | `_score_label` duplicated in `app.py` and `report_generator.py` |
| U9 | `[x]` | LOW | UI/UX | `app.py` | No `ssl_warning` flag surfaced in UI — users never see TLS issues flagged in results |
| DOC1 | `[x]` | — | Docs | — | Create `README.md` with setup, usage, API key guide |
| DOC2 | `[x]` | — | Docs | — | Create `PREPUSH_CHECKLIST.md` |
| DOC3 | `[x]` | — | Docs | — | Add deployment notes for production security (file permissions, secrets) |

---

## Persona Scorecard

| Persona | Role | Score | Top 3 Complaints |
|---------|------|-------|-----------------|
| Sarah | SEO Manager | 5/10 | Fake CWV numbers; HSTS=Critical inflating penalty; no keyword analysis |
| Raj | Junior Dev | 6/10 | No onboarding; 60+ APIs unlabeled; raw Python exceptions shown |
| Emma | A11y Auditor | 2/10 | Zero ARIA attributes; color-only encoding; custom HTML not keyboard-navigable |
| Carlos | Agency/Mobile | 4/10 | App unusable on iPhone; no PDF export implemented; no audit history |
| Priya | SRE | 3/10 | API keys plaintext on disk; OOM risk at 500 URLs×16 workers; zero logging |

---

## Performance Review Summary

| # | Sev | Issue |
|---|-----|-------|
| P1 | HIGH | CSS re-read from disk every rerun (no cache) |
| P2 | HIGH | No `requests.Session()` in link/image validators |
| P3 | MED | `all_issues` flattened in render path (not cached) |
| P4 | MED | `analyze_content` re-parses full BeautifulSoup DOM |
| P5 | LOW | Dead `partial` import |
| P6 | LOW | `_score_label` duplicated |
| P7 | MED | Full result objects (headers, link lists) in session state — 200MB+ for 100 URLs |
| P8 | MED | Inner closures (`upd_b`, `upd_s`) redefined on every render |

---

## Fix Progress

- **Batch 1** (7 items): `[ ]` CRITICAL Security + Logic  
- **Batch 2** (11 items): `[ ]` HIGH Security + Logic  
- **Batch 3** (8 items): `[ ]` HIGH UI/UX + Perf  
- **Batch 4** (8 items): `[ ]` MEDIUM  
- **Batch 5** (11 items): `[ ]` LOW + Docs  

**Overall: 0 / 45 fixed**

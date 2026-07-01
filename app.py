"""SEO Technical Audit Dashboard — Enterprise Streamlit Application."""

import io
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from modules.image_auditor import _fetch_size
from modules.api_key_manager import APIKeyManager, CATEGORIES, _API_FLAT, test_api_key
from modules.report_generator import _score_label as _score_label
from modules.auditor import audit_url as _raw_audit_url, audit_urls_bulk

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SEO Technical Audit Dashboard",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────
@st.cache_resource
def _load_css():
    # Use absolute path relative to this file so CWD doesn't matter
    p = Path(__file__).parent / "assets" / "style.css"
    return p.read_text(encoding="utf-8") if p.exists() else ""

_css = _load_css()
if _css:
    st.markdown(f"<style>{_css}</style>", unsafe_allow_html=True)

# ── Block Streamlit's 'C' keyboard shortcut (triggers Clear Caches dialog) ─
# Streamlit registers 'C' as a hotkey. When users press Ctrl+C to copy text
# the C keypress leaks through and opens the dialog. We intercept it early.
st.markdown("""
<script>
(function() {
    function blockClearCacheShortcut(e) {
        // Block bare 'C' / 'c' key when not typing in an input/textarea
        if ((e.key === 'c' || e.key === 'C') && !e.ctrlKey && !e.metaKey && !e.altKey) {
            var tag = (document.activeElement || {}).tagName || '';
            var editable = (document.activeElement || {}).isContentEditable;
            if (tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT' && !editable) {
                e.stopImmediatePropagation();
            }
        }
    }
    // Use capture phase so we run before Streamlit's listener
    document.addEventListener('keydown', blockClearCacheShortcut, true);
})();
</script>
""", unsafe_allow_html=True)

# ── st.html compatibility shim (requires Streamlit ≥1.31) ─────────────────
if not hasattr(st, "html"):
    st.html = lambda s, **kw: st.markdown(s, unsafe_allow_html=True)

# ── Module-level cached audit wrapper (cache keyed by args, not function obj) ─
@st.cache_data(ttl=3600, show_spinner=False)
def _cached_audit_url(url, atype, check_links, validate_links, fetch_pagespeed=False, psi_api_key=None):
    return _raw_audit_url(url, atype, check_links, validate_links,
                          fetch_pagespeed=fetch_pagespeed, psi_api_key=psi_api_key)

# ── Session state ──────────────────────────────────────────────────────────
_PAGES = [
    "📊 Dashboard Overview",
    "🚀 New Audit",
    "📋 Audit Results",
    "🔎 URL Detail",
    "🔗 Link Analysis",
    "⚡ Performance Audit",
    "📝 Heading Analysis",
    "📤 Export Reports",
    "⚙️ Settings",
]

for key, default in [
    ("audit_results", []),
    ("last_audit_date", None),
    ("selected_url_idx", 0),
    ("single_result", None),
    ("dup_report", None),
    ("nav_page", None),
    ("nav_filter", None),
    ("active_page", _PAGES[0]),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Load all API keys from secrets/file into session state ─────────────────
APIKeyManager._init()
# Back-compat: keep psi_api_key_global in sync with centralized store
if not st.session_state.get("psi_api_key_global") and APIKeyManager.has("psi"):
    st.session_state["psi_api_key_global"] = APIKeyManager.get("psi")


# ════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ════════════════════════════════════════════════════════════════════════════

def _score_color(s):
    if s >= 90: return "#10B981"
    if s >= 75: return "#3B82F6"
    if s >= 50: return "#F59E0B"
    return "#EF4444"


def _score_class(s):
    if s >= 90: return "score-excellent"
    if s >= 75: return "score-good"
    if s >= 50: return "score-needs"
    return "score-critical"

def _sev_color(sev):
    return {"Critical":"#EF4444","High":"#F97316","Warning":"#F59E0B",
            "Medium":"#EAB308","Low":"#3B82F6"}.get(sev,"#6B7280")

def _sev_bg(sev):
    # Semi-transparent — works on both light and dark Streamlit themes
    return {
        "Critical": "var(--sev-critical-bg,rgba(239,68,68,.10))",
        "High":     "var(--sev-high-bg,rgba(249,115,22,.10))",
        "Warning":  "var(--sev-warning-bg,rgba(245,158,11,.10))",
        "Medium":   "var(--sev-medium-bg,rgba(234,179,8,.10))",
        "Low":      "var(--sev-low-bg,rgba(59,130,246,.10))",
    }.get(sev, "var(--sev-other-bg,rgba(107,114,128,.08))")

def metric_card(label, value, color="#3B82F6", nav_target=None, nav_filter=None):
    st.markdown(f"""
        <div class="metric-card" style="{'cursor:pointer;' if nav_target else ''}">
            <div class="metric-value" style="color:{color}">{value}</div>
            <div class="metric-label">{label}</div>
        </div>""", unsafe_allow_html=True)
    if nav_target:
        _key = f"nav_{label.replace(' ','_').lower()}_{nav_target[:6]}"
        if st.button("View →", key=_key, use_container_width=True, help=f"Go to {nav_target}"):
            st.session_state["nav_page"]   = nav_target
            st.session_state["nav_filter"] = nav_filter
            st.rerun()


# ── Ahrefs-style link table ────────────────────────────────────────────────

def _health_badge(health, label):
    colors = {
        "ok":       ("var(--seo-success-bg,rgba(5,150,105,.10))",  "var(--seo-success,#059669)"),
        "redirect": ("var(--seo-warning-bg,rgba(217,119,6,.10))",  "var(--seo-warning,#D97706)"),
        "blocked":  ("var(--seo-accent-light,rgba(79,70,229,.10))","var(--seo-accent,#4F46E5)"),
        "broken":   ("var(--seo-error-bg,rgba(220,38,38,.10))",    "var(--seo-error,#DC2626)"),
        "unknown":  ("var(--seo-card-bg-alt,#F1F5F9)",             "var(--seo-muted,#475569)"),
    }
    bg, fg = colors.get(health, ("var(--seo-card-bg-alt,#F1F5F9)", "var(--seo-muted,#475569)"))
    return (f"<span style='background:{bg};color:{fg};padding:2px 7px;"
            f"border-radius:4px;font-size:.72rem;font-weight:700;white-space:nowrap'>{label}</span>")


def _rel_badge(is_dofollow, is_nofollow, is_sponsored, is_ugc):
    if is_sponsored:
        return "<span style='background:var(--seo-warning-bg,rgba(217,119,6,.10));color:var(--seo-warning,#D97706);padding:2px 7px;border-radius:4px;font-size:.72rem;font-weight:700'>Sponsored</span>"
    if is_ugc:
        return "<span style='background:var(--seo-accent-light,rgba(79,70,229,.10));color:var(--seo-accent,#4F46E5);padding:2px 7px;border-radius:4px;font-size:.72rem;font-weight:700'>UGC</span>"
    if is_nofollow:
        return "<span style='background:var(--seo-error-bg,rgba(220,38,38,.10));color:var(--seo-error,#DC2626);padding:2px 7px;border-radius:4px;font-size:.72rem;font-weight:700'>Nofollow</span>"
    return "<span style='background:var(--seo-success-bg,rgba(5,150,105,.10));color:var(--seo-success,#059669);padding:2px 7px;border-radius:4px;font-size:.72rem;font-weight:700'>Dofollow</span>"


def _cwv_color(label):
    l = label or ""
    if "Good" in l or l == "Low":
        return ("var(--seo-success-bg,rgba(5,150,105,.13))", "var(--seo-success,#059669)")
    if "Needs" in l or l == "Medium":
        return ("var(--seo-warning-bg,rgba(217,119,6,.13))", "var(--seo-warning,#D97706)")
    return ("var(--seo-error-bg,rgba(220,38,38,.13))", "var(--seo-error,#DC2626)")


_SEV_COLORS = {
    "Critical": "#EF4444", "High": "#F97316",
    "Warning": "#F59E0B", "Medium": "#EAB308", "Low": "#3B82F6",
}

def _render_issue_card(iss):
    """Shared issue card renderer used across all audit pages."""
    sev   = iss.get("severity", "Low")
    sev_c = _SEV_COLORS.get(sev, "#6B7280")
    st.markdown(f"""
    <div style='background:var(--seo-card-bg,#fff);border-left:5px solid {sev_c};
         border-radius:0 10px 10px 0;padding:12px 16px;margin-bottom:8px;
         border:1px solid var(--seo-border,rgba(148,163,184,.22))'>
        <div style='display:flex;align-items:center;gap:8px;margin-bottom:4px'>
            <span style='background:{sev_c};color:#fff;padding:2px 10px;border-radius:999px;
                  font-size:.7rem;font-weight:700'>{sev}</span>
            <span style='font-weight:700;font-size:.85rem;color:var(--seo-heading,#0F172A)'>
                {iss.get("issue","")}</span>
            <span style='margin-left:auto;font-size:.75rem;font-weight:700;color:{sev_c}'>
                Impact {iss.get("impact_score",0)}/10</span>
        </div>
        <div style='font-size:.78rem;color:var(--seo-info-text,#1D4ED8);margin-top:4px'>
            ✅ {iss.get("recommendation","")}</div>
        <div style='font-size:.72rem;color:var(--seo-muted,#64748B);margin-top:3px'>
            Effort: {iss.get("effort","—")}
            &nbsp;·&nbsp; Category: {iss.get("category","—")}
        </div>
    </div>""", unsafe_allow_html=True)


def render_link_table(links, show_source=False, source_label="Source", max_rows=100, key_prefix="lnk"):
    """Render an Ahrefs-style link table with status badges."""
    if not links:
        st.info("No links found.")
        return

    # Filter controls — keys must be stable across reruns (no id(obj) which changes every run)
    fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 2])
    with fc1:
        filter_rel = st.selectbox(
            "Filter by Rel",
            ["All", "Dofollow", "Nofollow", "Sponsored", "UGC"],
            key=f"{key_prefix}_rel_f"
        )
    with fc2:
        filter_health = st.selectbox(
            "Filter by Status",
            ["All", "OK (2xx)", "Redirect (3xx)", "Broken (4xx/5xx)", "Blocked (999)", "Not Checked"],
            key=f"{key_prefix}_hlt_f"
        )
    with fc3:
        filter_anchor = st.selectbox(
            "Anchor Text",
            ["All", "Has Anchor", "No Anchor"],
            key=f"{key_prefix}_anc_f"
        )
    with fc4:
        search_q = st.text_input("Search URL / Keyword", placeholder="Type URL or anchor keyword…", key=f"{key_prefix}_srch_f")

    filtered = links
    if filter_rel == "Dofollow":
        filtered = [l for l in filtered if l.get("is_dofollow")]
    elif filter_rel == "Nofollow":
        filtered = [l for l in filtered if l.get("is_nofollow")]
    elif filter_rel == "Sponsored":
        filtered = [l for l in filtered if l.get("is_sponsored")]
    elif filter_rel == "UGC":
        filtered = [l for l in filtered if l.get("is_ugc")]

    if filter_health == "OK (2xx)":
        filtered = [l for l in filtered if l.get("health") == "ok"]
    elif filter_health == "Redirect (3xx)":
        filtered = [l for l in filtered if l.get("health") == "redirect"]
    elif filter_health == "Broken (4xx/5xx)":
        filtered = [l for l in filtered if l.get("health") == "broken"]
    elif filter_health == "Blocked (999)":
        filtered = [l for l in filtered if l.get("health") == "blocked"]
    elif filter_health == "Not Checked":
        filtered = [l for l in filtered if l.get("health") == "unknown"]

    if filter_anchor == "Has Anchor":
        filtered = [l for l in filtered if (l.get("anchor_text") or "").strip()]
    elif filter_anchor == "No Anchor":
        filtered = [l for l in filtered if not (l.get("anchor_text") or "").strip()]

    if search_q:
        sq = search_q.lower()
        filtered = [l for l in filtered
                    if sq in l.get("url","").lower() or sq in (l.get("anchor_text","") or "").lower()]

    st.caption(
        f"Showing **{min(len(filtered), max_rows)}** of {len(filtered)} links &nbsp;|&nbsp; "
        f"Anchor: "
        f"<span style='background:var(--seo-accent-light,rgba(79,70,229,.12));color:var(--seo-accent,#4F46E5);border-radius:3px;padding:1px 6px;font-size:.7rem;font-weight:700'>Descriptive (3+ words)</span> &nbsp;"
        f"<span style='background:var(--seo-warning-bg,rgba(217,119,6,.10));color:var(--seo-warning,#D97706);border-radius:3px;padding:1px 6px;font-size:.7rem;font-weight:700'>Short / Generic</span> &nbsp;"
        f"<span style='background:var(--seo-card-bg-alt,#F1F5F9);color:var(--seo-muted,#475569);border-radius:3px;padding:1px 6px;font-size:.7rem;font-weight:700'>No Anchor</span>",
        unsafe_allow_html=True
    )

    rows_html = ""
    import html as _h
    for lk in filtered[:max_rows]:
        url    = lk.get("url","")
        anchor = lk.get("anchor_text","") or ""
        anchor_display = anchor.strip() if anchor.strip() else "[No Anchor]"
        is_no_anchor   = not anchor.strip()
        health = lk.get("health","unknown")
        sl     = lk.get("status_label") or ("Not Checked" if lk.get("status_code") is None else str(lk.get("status_code","")))
        hbadge = _health_badge(health, sl)
        rbadge = _rel_badge(
            lk.get("is_dofollow", True),
            lk.get("is_nofollow", False),
            lk.get("is_sponsored", False),
            lk.get("is_ugc", False),
        )
        new_tab = "🔗" if lk.get("opens_new_tab") else ""
        noop    = "" if lk.get("has_noopener") else ("⚠️" if lk.get("opens_new_tab") else "")
        # Escape all scraped-page content before injecting into HTML
        url_safe  = _h.escape(url)
        short_url = _h.escape(url[:65] + ("…" if len(url) > 65 else ""))
        short_anc = _h.escape(anchor_display[:50] + ("…" if len(anchor_display) > 50 else ""))
        src_text  = _h.escape(lk.get('source','')[:60])
        source_col = (f"<td style='padding:7px 10px;font-size:.72rem;color:var(--seo-muted,#64748B);max-width:130px;word-break:break-all'>"
                      f"{src_text}</td>") if show_source else ""

        # Anchor keyword chip — color-coded like other badges
        # Blue  = good descriptive anchor (≥3 words)
        # Yellow = short/generic anchor (1–2 words)
        # Gray  = no anchor text at all
        if is_no_anchor:
            anc_bg = "var(--seo-card-bg-alt,#F1F5F9)"
            anc_fg = "var(--seo-muted,#475569)"
            anc_label = "[No Anchor]"
            anc_title = "No anchor text — add descriptive keyword text to this link"
        elif len(anchor_display.split()) >= 3:
            anc_bg = "var(--seo-accent-light,rgba(79,70,229,.12))"
            anc_fg = "var(--seo-accent,#4F46E5)"   # indigo — descriptive keyword phrase
            anc_label = short_anc
            anc_title = short_anc  # already escaped
        else:
            anc_bg = "var(--seo-warning-bg,rgba(217,119,6,.10))"
            anc_fg = "var(--seo-warning,#D97706)"   # amber — short/generic anchor
            anc_label = short_anc
            anc_title = short_anc  # already escaped
        anchor_chip = (
            f"<span style='display:inline-block;background:{anc_bg};color:{anc_fg};"
            f"border-radius:4px;padding:2px 8px;font-size:.72rem;font-weight:700;"
            f"max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
            f"vertical-align:middle' title='{anc_title}'>{anc_label}</span>"
        )

        rows_html += f"""
        <tr style='border-bottom:1px solid var(--table-row-border,rgba(148,163,184,.15));'>
            {source_col}
            <td style='padding:7px 10px;max-width:220px;word-break:break-all'>
                <a href='{url_safe}' target='_blank' style='font-size:.78rem;color:var(--seo-info-text,#1D4ED8);text-decoration:none'
                   title='{url_safe}'>{short_url}</a>
            </td>
            <td style='padding:7px 10px;max-width:220px'>{anchor_chip}</td>
            <td style='padding:7px 10px;text-align:center'>{rbadge}</td>
            <td style='padding:7px 10px;text-align:center'>{hbadge}</td>
            <td style='padding:7px 10px;text-align:center;font-size:.75rem;color:var(--seo-muted,#64748B)'>{new_tab} {noop}</td>
        </tr>"""

    source_th = f"<th style='padding:8px 10px;text-align:left;color:var(--seo-text,#374151);font-size:.78rem'>{source_label}</th>" if show_source else ""
    table_html = f"""
    <div style='overflow-x:auto;border-radius:10px;border:1px solid var(--seo-border,rgba(148,163,184,.22));margin-top:8px'>
    <table style='width:100%;border-collapse:collapse;background:var(--seo-card-bg,#FFFFFF)'>
        <thead style='background:var(--seo-card-bg,#F8FAFC)'>
            <tr>
                {source_th}
                <th style='padding:8px 10px;text-align:left;color:var(--seo-text,#374151);font-size:.78rem'>Target URL</th>
                <th style='padding:8px 10px;text-align:left;color:var(--seo-text,#374151);font-size:.78rem'>Anchor Text (Keyword)</th>
                <th style='padding:8px 10px;text-align:center;color:var(--seo-text,#374151);font-size:.78rem'>Link Type</th>
                <th style='padding:8px 10px;text-align:center;color:var(--seo-text,#374151);font-size:.78rem'>Status</th>
                <th style='padding:8px 10px;text-align:center;color:var(--seo-text,#374151);font-size:.78rem'>Tab / Security</th>
            </tr>
        </thead>
        <tbody>{rows_html}</tbody>
    </table>
    </div>"""
    st.html(table_html)


def extract_urls_from_csv_xlsx(uploaded_file):
    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
        url_cols = [c for c in df.columns
                    if any(kw in c.lower() for kw in ["url","link","href","address","page"])]
        col  = url_cols[0] if url_cols else df.columns[0]
        urls = df[col].dropna().astype(str).tolist()
        urls = [u.strip() for u in urls if u.strip().startswith("http")]
        return urls, col
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return [], ""


_SITEMAP_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def extract_urls_from_sitemap(uploaded_file):
    try:
        content = uploaded_file.read()
        if len(content) > _SITEMAP_MAX_BYTES:
            st.error(f"Sitemap file is too large ({len(content) // (1024*1024)} MB). Maximum allowed size is 10 MB.")
            return []
        root = ET.fromstring(content)
        ns   = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [loc.text.strip() for loc in root.findall(".//sm:loc", ns) if loc.text]
        if not urls:
            urls = [loc.text.strip() for loc in root.findall(".//{*}loc") if loc.text]
        return urls
    except Exception as e:
        st.error(f"Error parsing sitemap: {e}")
        return []


def build_results_df(results):
    rows = []
    for r in results:
        issues = r.get("all_issues", [])
        rows.append({
            "URL":         r.get("url",""),
            "Type":        r.get("audit_type","general").title(),
            "Status":      r.get("status_code", 0),
            "SEO Score":   r.get("seo_score", 0),
            "Score Label": _score_label(r.get("seo_score", 0)),
            "Total Issues":len(issues),
            "Critical":    sum(1 for i in issues if i.get("severity")=="Critical"),
            "High":        sum(1 for i in issues if i.get("severity")=="High"),
            "Word Count":  r.get("content",{}).get("word_count", 0),
            "Int. Links":  r.get("internal_links",{}).get("total_links", 0),
            "Ext. Links":  r.get("external_links",{}).get("total_links", 0),
            "Broken Int.": r.get("internal_links",{}).get("broken_count", 0),
            "Broken Ext.": r.get("external_links",{}).get("broken_count", 0),
            "Indexable":   r.get("indexability",{}).get("is_indexable", True),
            "Viewport":    r.get("advanced",{}).get("has_viewport", False),
            "Schema":      r.get("advanced",{}).get("has_schema", False),
            "Fetch Error": r.get("fetch_error") or "",
        })
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════════════════
# SERP & Social Preview renderers
# ════════════════════════════════════════════════════════════════════════════

def render_serp_preview(serp_data):
    import html as _h
    title = _h.escape(serp_data.get("title","—") or "—")
    desc  = _h.escape(serp_data.get("description","") or "No meta description found.")
    bc    = _h.escape(serp_data.get("breadcrumb","") or serp_data.get("url",""))
    t_long = serp_data.get("title_too_long", False)
    d_short= serp_data.get("desc_too_short", False)
    d_long = serp_data.get("desc_too_long", False)

    t_color = "#d93025" if t_long else "#1a0dab"
    d_color = "#d93025" if (d_short or d_long) else "#4d5156"

    st.markdown(f"""
    <div style="font-family:Arial,sans-serif;background:var(--seo-card-bg,#fff);border-radius:10px;
         padding:20px 24px;border:1px solid var(--seo-border,rgba(148,163,184,.22));max-width:620px;box-shadow:0 2px 8px rgba(0,0,0,.08)">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
            <div style="width:28px;height:28px;background:#e8f0fe;border-radius:50%;
                 display:flex;align-items:center;justify-content:center;font-size:.7rem;color:#1967d2">G</div>
            <div>
                <div style="font-size:13px;color:var(--seo-text,#202124);font-weight:500">Google Search Preview</div>
                <div style="font-size:11px;color:var(--seo-muted,#5f6368)">{bc}</div>
            </div>
        </div>
        <div style="height:1px;background:var(--seo-border,#e0e0e0);margin-bottom:10px"></div>
        <div style="font-size:11px;color:var(--seo-muted,#5f6368);margin-bottom:3px">{bc}</div>
        <div style="font-size:19px;color:{t_color};line-height:1.3;margin-bottom:4px;
             font-family:arial,sans-serif;cursor:pointer;text-decoration:none">
            {title}
        </div>
        <div style="font-size:13px;color:{d_color};line-height:1.55;font-family:arial,sans-serif">
            {desc}
        </div>
    </div>
    """, unsafe_allow_html=True)

    flags = []
    if t_long:  flags.append("⚠️ Title may be truncated in search results (>60 chars)")
    if d_short: flags.append("⚠️ Description too short — Google may auto-generate one (<120 chars)")
    if d_long:  flags.append("⚠️ Description may be cut off in search results (>160 chars)")
    for f in flags:
        st.warning(f)


def render_social_preview(social_data, url):
    import html as _h
    og_title  = _h.escape(social_data.get("og_title","") or "No title")
    og_desc   = _h.escape(social_data.get("og_description","") or "No description")
    og_img    = social_data.get("og_image","")   # URL used in src= attribute only — not injected as text
    site_name = _h.escape(social_data.get("og_site_name","") or url)

    img_html = (
        f'<img src="{og_img}" style="width:100%;height:200px;object-fit:cover">'
        if og_img else
        '<div style="width:100%;height:200px;background:linear-gradient(135deg,#667eea,#764ba2);'
        'display:flex;align-items:center;justify-content:center;color:white;font-size:.85rem">'
        '📷 No og:image found</div>'
    )

    st.markdown("**Facebook / LinkedIn Card**")
    st.markdown(f"""
    <div style="max-width:420px;border-radius:10px;overflow:hidden;border:1px solid var(--seo-border,rgba(148,163,184,.22));
         font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.1)">
        {img_html}
        <div style="background:var(--seo-card-bg,#f7f8fa);padding:10px 14px;border-top:1px solid var(--seo-border,rgba(148,163,184,.22))">
            <div style="font-size:11px;color:var(--seo-muted,#606770);text-transform:uppercase;letter-spacing:.04em">{site_name}</div>
            <div style="font-size:15px;font-weight:700;color:var(--seo-heading,#1c1e21);margin:4px 0;line-height:1.3">{og_title[:80]}</div>
            <div style="font-size:13px;color:var(--seo-muted,#606770);line-height:1.45">{og_desc[:120]}{"…" if len(og_desc)>120 else ""}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>**Twitter / X Card**", unsafe_allow_html=True)
    tw_img  = social_data.get("twitter_image","") or og_img
    tw_card = social_data.get("twitter_card_type","summary")
    img_html2 = (
        f'<img src="{tw_img}" style="width:100%;height:{"200" if tw_card=="summary_large_image" else "100"}px;object-fit:cover">'
        if tw_img else
        '<div style="width:100%;height:120px;background:linear-gradient(135deg,#1da1f2,#0d8ecf);'
        'display:flex;align-items:center;justify-content:center;color:white;font-size:.85rem">'
        '📷 No twitter:image found</div>'
    )
    st.markdown(f"""
    <div style="max-width:420px;border-radius:14px;overflow:hidden;border:1px solid var(--seo-border,rgba(148,163,184,.22));
         font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.08)">
        {img_html2}
        <div style="background:var(--seo-card-bg,#fff);padding:10px 14px">
            <div style="font-size:14px;font-weight:700;color:var(--seo-heading,#0f1419)">{og_title[:70]}</div>
            <div style="font-size:13px;color:var(--seo-muted,#536471);margin-top:2px">{og_desc[:100]}{"…" if len(og_desc)>100 else ""}</div>
            <div style="font-size:12px;color:var(--seo-muted,#536471);margin-top:4px">🔗 {site_name}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_schema_display(schema_types, schema_raw):
    if not schema_types:
        st.warning("No structured data (JSON-LD) found on this page.")
        return

    st.success(f"Found {len(schema_types)} schema type(s): **{', '.join(schema_types)}**")
    for i, item in enumerate(schema_raw[:3], 1):
        stype = item.get("@type","Unknown")
        with st.expander(f"Schema #{i}: {stype}", expanded=i == 1):
            st.json(item)


# ════════════════════════════════════════════════════════════════════════════
# Inline result renderer (New Audit page — Single URL)
# ════════════════════════════════════════════════════════════════════════════

def render_inline_result(r):
    score    = r.get("seo_score", 0)
    issues   = r.get("all_issues", [])
    meta     = r.get("metadata", {})
    head     = r.get("headings", {})
    cont     = r.get("content", {})
    imgs     = r.get("images", {})
    can_     = r.get("canonical", {})
    idx_d    = r.get("indexability", {})
    il       = r.get("internal_links", {})
    el_      = r.get("external_links", {})
    adv      = r.get("advanced", {})
    atype    = r.get("audit_type", "general")

    color    = _score_color(score)
    label    = _score_label(score)
    crit_n   = sum(1 for i in issues if i.get("severity") == "Critical")
    high_n   = sum(1 for i in issues if i.get("severity") == "High")

    st.markdown("---")

    # ── Score hero ────────────────────────────────────────────────────────
    import html as _html_mod
    _url_safe   = _html_mod.escape(r.get("url", "")[:90])
    _title_safe = _html_mod.escape((meta.get("title") or {}).get("content", "") or _url_safe)[:70]

    _arc_deg   = (score / 100) * 360
    _arc_color = "#34D399" if score >= 70 else "#FCD34D" if score >= 50 else "#F87171"
    _grade     = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D"

    def _cat_cls(s):  return "g" if s >= 70 else "w" if s >= 50 else "r"
    def _bar_clr(s):  return "#34D399" if s >= 70 else "#FCD34D" if s >= 50 else "#F87171"

    _meta_s  = (meta.get("score") or 0)
    _cont_s  = (cont.get("score") or 0)
    _link_s  = (il.get("score") or el_.get("score") or 0)
    _sch_s   = (adv.get("schema_score") or r.get("schema", {}).get("score") or 0)
    _tech_s  = (idx_d.get("score") or r.get("technical", {}).get("score") or 0)
    _img_s   = (imgs.get("score") or 0)

    st.html(f"""
    <div class='score-hero'>
      <div class='score-arc-bg' style='background:conic-gradient(from -90deg,{_arc_color} {_arc_deg:.1f}deg,rgba(255,255,255,0.07) 0deg);'>
        <div class='score-arc-inner'>
          <div class='score-arc-num'>{score}</div>
          <div class='score-arc-lbl'>/ 100</div>
        </div>
      </div>
      <div class='score-hero-mid'>
        <div class='score-hero-url'>{_url_safe}</div>
        <div class='score-hero-title'>{_title_safe}</div>
        <div class='score-cats'>
          <div class='score-cat'><span class='score-cat-lbl'>Metadata</span><div class='score-cat-bar'><div class='score-cat-fill' style='width:{_meta_s}%;background:{_bar_clr(_meta_s)};'></div></div><span class='score-cat-n {_cat_cls(_meta_s)}'>{_meta_s}</span></div>
          <div class='score-cat'><span class='score-cat-lbl'>Content</span><div class='score-cat-bar'><div class='score-cat-fill' style='width:{_cont_s}%;background:{_bar_clr(_cont_s)};'></div></div><span class='score-cat-n {_cat_cls(_cont_s)}'>{_cont_s}</span></div>
          <div class='score-cat'><span class='score-cat-lbl'>Links</span><div class='score-cat-bar'><div class='score-cat-fill' style='width:{_link_s}%;background:{_bar_clr(_link_s)};'></div></div><span class='score-cat-n {_cat_cls(_link_s)}'>{_link_s}</span></div>
          <div class='score-cat'><span class='score-cat-lbl'>Schema</span><div class='score-cat-bar'><div class='score-cat-fill' style='width:{_sch_s}%;background:{_bar_clr(_sch_s)};'></div></div><span class='score-cat-n {_cat_cls(_sch_s)}'>{_sch_s}</span></div>
          <div class='score-cat'><span class='score-cat-lbl'>Technical</span><div class='score-cat-bar'><div class='score-cat-fill' style='width:{_tech_s}%;background:{_bar_clr(_tech_s)};'></div></div><span class='score-cat-n {_cat_cls(_tech_s)}'>{_tech_s}</span></div>
          <div class='score-cat'><span class='score-cat-lbl'>Images</span><div class='score-cat-bar'><div class='score-cat-fill' style='width:{_img_s}%;background:{_bar_clr(_img_s)};'></div></div><span class='score-cat-n {_cat_cls(_img_s)}'>{_img_s}</span></div>
        </div>
      </div>
      <div class='score-hero-stats'>
        <div class='hero-stat'><div class='hero-stat-n gold'>{_grade}</div><div class='hero-stat-l'>Grade</div></div>
        <div class='hero-stat'><div class='hero-stat-n red'>{crit_n}</div><div class='hero-stat-l'>Critical</div></div>
        <div class='hero-stat'><div class='hero-stat-n amber'>{high_n}</div><div class='hero-stat-l'>High</div></div>
      </div>
    </div>""")

    if r.get("ssl_warning"):
        st.warning("⚠️ TLS/SSL certificate could not be verified for this URL. The audit continued with certificate validation disabled — treat results with caution.")

    # ── Tabs ──────────────────────────────────────────────────────────────
    tabs = st.tabs([
        "📊 Summary", "🔗 Outgoing Links", "🌐 SERP & Social",
        "🔬 Schema", "🔧 Technical", "🔑 Keywords", "⚠️ Issues", "💡 Top Recommendations"
    ])

    # Tab 0 — Summary
    with tabs[0]:
        k1,k2,k3,k4 = st.columns(4)
        k1.metric("H1",          head.get("h1_count",0))
        k2.metric("H2",          head.get("h2_count",0))
        k3.metric("Images",      imgs.get("total_images",0))
        k4.metric("Missing Alt", imgs.get("missing_alt_count",0))
        k5,k6,k7,k8 = st.columns(4)
        k5.metric("Int. Links",  il.get("total_links",0))
        k6.metric("Ext. Links",  el_.get("total_links",0))
        k7.metric("Broken",      (il.get("broken_count",0) or 0) + (el_.get("broken_count",0) or 0))
        k8.metric("Schema Types",len(adv.get("schema_types",[])))

        # Heading structure tree
        hd = r.get("heading_detail", {})
        if hd.get("tree_html"):
            st.markdown('<div class="section-header">🏗️ Heading Structure</div>', unsafe_allow_html=True)
            hcol1, hcol2 = st.columns([2, 1])
            with hcol1:
                st.markdown(
                    f"<div style='background:var(--seo-card-bg,#F8FAFC);border:1px solid var(--seo-border,rgba(148,163,184,.22));"
                    f"border-radius:10px;padding:14px 18px;max-height:260px;overflow-y:auto'>"
                    f"{hd['tree_html']}</div>",
                    unsafe_allow_html=True)
            with hcol2:
                cnts = hd.get("counts", {})
                for lv in range(1, 7):
                    c = cnts.get(f"h{lv}", 0)
                    if c:
                        bar_w = min(c * 12, 100)
                        st.markdown(
                            f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:5px'>"
                            f"<span style='font-size:.72rem;font-weight:700;min-width:24px;color:var(--seo-text,#374151)'>H{lv}</span>"
                            f"<div style='flex:1;background:var(--seo-border,rgba(148,163,184,.22));border-radius:4px;height:8px'>"
                            f"<div style='width:{bar_w}%;background:var(--seo-accent,#4F46E5);height:100%;border-radius:4px'></div></div>"
                            f"<span style='font-size:.72rem;color:var(--seo-muted,#64748B);min-width:16px;text-align:right'>{c}</span>"
                            f"</div>",
                            unsafe_allow_html=True)
                if hd.get("sequence_violations"):
                    st.warning(f"⚠️ {len(hd['sequence_violations'])} heading level skip(s) detected")
                if hd.get("empty_headings"):
                    st.warning(f"⚠️ {len(hd['empty_headings'])} empty heading(s) found")

        st.markdown("<br>", unsafe_allow_html=True)
        left, right = st.columns([3, 2])

        with left:
            # Metadata
            st.markdown('<div class="section-header">📋 Metadata</div>', unsafe_allow_html=True)
            m1, m2 = st.columns(2)
            with m1:
                tl = meta.get("title_length",0)
                ok = "✅" if 30 <= tl <= 60 else "⚠️"
                st.markdown(f"**{ok} Meta Title** `{tl} chars`")
                st.code(meta.get("title","—") or "—", language=None)
            with m2:
                dl = meta.get("description_length",0)
                ok = "✅" if 120 <= dl <= 160 else "⚠️"
                st.markdown(f"**{ok} Meta Description** `{dl} chars`")
                desc = meta.get("description","") or "—"
                st.code(desc[:120]+("…" if len(desc)>120 else ""), language=None)

            def chk(v): return "✅" if v else "❌"
            st.caption(
                f"OG Tags: {chk(meta.get('has_og_tags'))}  |  "
                f"OG Image: {chk(meta.get('has_og_image'))}  |  "
                f"Viewport: {chk(adv.get('has_viewport'))}  |  "
                f"Charset: {chk(adv.get('has_charset'))}  |  "
                f"Lang: {adv.get('lang_attr','—') or '❌ Missing'}  |  "
                f"Hreflang: {chk(adv.get('has_hreflang'))}  |  "
                f"Twitter Cards: {chk(adv.get('twitter_complete'))}  |  "
                f"Favicon: {chk(adv.get('has_favicon'))}  |  "
                f"Indexable: {chk(idx_d.get('is_indexable',True))}  |  "
                f"Canonical: {chk(can_.get('is_self_referencing'))}"
            )

            # Content
            st.markdown('<div class="section-header">📝 Content</div>', unsafe_allow_html=True)
            wc = cont.get("word_count",0)
            wc_color = "#EF4444" if cont.get("is_thin") else ("#F59E0B" if wc < 600 else "#10B981")
            st.markdown(f"""
            <div style='display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px'>
                <div style='background:var(--seo-card-bg,#F8FAFC);border-radius:8px;padding:10px 14px;text-align:center'>
                    <div style='font-size:1.3rem;font-weight:700;color:{wc_color}'>{wc:,}</div>
                    <div style='font-size:.7rem;color:var(--seo-muted,#64748B)'>Words</div></div>
                <div style='background:var(--seo-card-bg,#F8FAFC);border-radius:8px;padding:10px 14px;text-align:center'>
                    <div style='font-size:1.3rem;font-weight:700;color:#3B82F6'>{cont.get("reading_time",0)}</div>
                    <div style='font-size:.7rem;color:var(--seo-muted,#64748B)'>Min Read</div></div>
                <div style='background:var(--seo-card-bg,#F8FAFC);border-radius:8px;padding:10px 14px;text-align:center'>
                    <div style='font-size:1.3rem;font-weight:700;color:#6366F1'>{cont.get("content_ratio",0)}%</div>
                    <div style='font-size:.7rem;color:var(--seo-muted,#64748B)'>Content Ratio</div></div>
            </div>""", unsafe_allow_html=True)

            # Links
            st.markdown('<div class="section-header">🔗 Links</div>', unsafe_allow_html=True)
            lc1, lc2 = st.columns(2)
            with lc1:
                bi      = il.get("broken_count",0) or 0
                il_tot  = il.get("total_links",0)
                il_df   = il.get("dofollow_count",0)
                il_nf   = il.get("nofollow_count",0)
                il_blk  = il.get("redirect_count",0) or 0
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#F8FAFC);border-radius:8px;padding:10px 14px;border:1px solid var(--seo-border,rgba(148,163,184,.22))'>
                    <div style='font-weight:700;font-size:.82rem;color:var(--seo-heading,#0F172A);margin-bottom:6px'>🔵 Internal Links</div>
                    <div style='display:flex;gap:10px;flex-wrap:wrap'>
                        <span style='font-size:.75rem;color:var(--seo-text,#374151)'>Total: <b>{il_tot}</b></span>
                        <span style='font-size:.75rem;color:#10B981'>Dofollow: <b>{il_df}</b></span>
                        <span style='font-size:.75rem;color:#EF4444'>Nofollow: <b>{il_nf}</b></span>
                        <span style='font-size:.75rem;color:#F59E0B'>Redirects: <b>{il_blk}</b></span>
                    </div>
                    <div style='margin-top:6px'>
                        {"<span style='background:var(--seo-error-bg,rgba(220,38,38,.12));color:var(--seo-error,#DC2626);padding:3px 8px;border-radius:5px;font-size:.78rem;font-weight:700'>🔴 " + str(bi) + " Broken</span>" if bi else "<span style='background:var(--seo-success-bg,rgba(5,150,105,.12));color:var(--seo-success,#059669);padding:3px 8px;border-radius:5px;font-size:.78rem;font-weight:700'>✅ No Broken Links</span>"}
                    </div>
                </div>""", unsafe_allow_html=True)
            with lc2:
                be      = el_.get("broken_count",0) or 0
                blk_cnt = el_.get("blocked_count",0) or 0
                el_tot  = el_.get("total_links",0)
                el_df   = el_.get("dofollow_count",0)
                el_nf   = el_.get("nofollow_count",0)
                el_dom  = el_.get("unique_domains",0)
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#F8FAFC);border-radius:8px;padding:10px 14px;border:1px solid var(--seo-border,rgba(148,163,184,.22))'>
                    <div style='font-weight:700;font-size:.82rem;color:var(--seo-heading,#0F172A);margin-bottom:6px'>🟣 External Links</div>
                    <div style='display:flex;gap:10px;flex-wrap:wrap'>
                        <span style='font-size:.75rem;color:var(--seo-text,#374151)'>Total: <b>{el_tot}</b></span>
                        <span style='font-size:.75rem;color:#10B981'>Dofollow: <b>{el_df}</b></span>
                        <span style='font-size:.75rem;color:#EF4444'>Nofollow: <b>{el_nf}</b></span>
                        <span style='font-size:.75rem;color:var(--seo-text,#374151)'>Domains: <b>{el_dom}</b></span>
                    </div>
                    <div style='margin-top:6px;display:flex;gap:6px;flex-wrap:wrap'>
                        {"<span style='background:var(--seo-error-bg,rgba(220,38,38,.12));color:var(--seo-error,#DC2626);padding:3px 8px;border-radius:5px;font-size:.78rem;font-weight:700'>🔴 " + str(be) + " Broken</span>" if be else "<span style='background:var(--seo-success-bg,rgba(5,150,105,.12));color:var(--seo-success,#059669);padding:3px 8px;border-radius:5px;font-size:.78rem;font-weight:700'>✅ No Broken</span>"}
                        {"<span style='background:var(--seo-accent-light,rgba(79,70,229,.12));color:var(--seo-accent,#4F46E5);padding:3px 8px;border-radius:5px;font-size:.78rem;font-weight:700'>🚫 " + str(blk_cnt) + " Blocked</span>" if blk_cnt else ""}
                    </div>
                </div>""", unsafe_allow_html=True)

            # Course / Blog
            if atype == "course":
                ca = r.get("course_audit",{})
                st.markdown('<div class="section-header">🎓 Course Completeness</div>', unsafe_allow_html=True)
                ss = ca.get("sections_score", 0)
                st.progress(int(ss)/100, text=f"Section Score: {ss:.0f}%")
                cols = st.columns(2)
                for i, (name, found) in enumerate(ca.get("sections_found",{}).items()):
                    cols[i%2].markdown(f"{'✅' if found else '❌'} {name}")
            elif atype == "blog":
                ba = r.get("blog_audit",{})
                st.markdown('<div class="section-header">📝 Blog Completeness</div>', unsafe_allow_html=True)
                es = ba.get("elements_score", 0)
                st.progress(int(es)/100, text=f"Elements Score: {es:.0f}%")
                cols = st.columns(2)
                for i, (name, found) in enumerate(ba.get("elements_found",{}).items()):
                    cols[i%2].markdown(f"{'✅' if found else '❌'} {name}")
                st.caption(f"Readability: {ba.get('readability_score','—')} | "
                           f"Schema: {'✅' if ba.get('has_article_schema') else '❌'} | "
                           f"OG Tags: {'✅' if ba.get('has_og_tags') else '❌'}")

        with right:
            st.markdown('<div class="section-header">📊 Score Breakdown</div>', unsafe_allow_html=True)
            bd = r.get("score_breakdown", {})
            if bd:
                labels = [k.replace("_"," ").title() for k in bd]
                values = list(bd.values())
                fig = go.Figure()
                fig.add_trace(go.Scatterpolar(
                    r=values, theta=labels, fill="toself",
                    line_color="#3B82F6", fillcolor="rgba(59,130,246,0.15)"))
                fig.update_layout(
                    polar=dict(radialaxis=dict(visible=True, range=[0,100])),
                    showlegend=False, height=280,
                    margin=dict(t=10,b=10,l=10,r=10))
                st.plotly_chart(fig, use_container_width=True)
                for k, v in bd.items():
                    st.markdown(
                        f"""<div style='display:flex;justify-content:space-between;
                        padding:4px 0;border-bottom:1px solid var(--table-row-border,rgba(148,163,184,.15))'>
                        <span style='font-size:.78rem;color:var(--seo-text,#374151)'>{k.replace("_"," ").title()}</span>
                        <span style='font-weight:700;color:{_score_color(v)}'>{v:.0f}</span></div>""",
                        unsafe_allow_html=True)

    # Tab 0 continued — Technical Signals grid (below score breakdown)
    with tabs[0]:
        tech_seo = adv.get("technical_seo", {})
        hdr_data = adv.get("http_headers_data", {})
        st.markdown("---")
        st.markdown("**🔧 Technical Signals**")
        def _chk(v): return "✅" if v else "❌"
        signal_rows = [
            [
                ("HTTPS",        r.get("url_structure", {}).get("is_https", False)),
                ("Viewport",     adv.get("has_viewport", False)),
                ("Charset",      adv.get("has_charset", False)),
                ("Lang",         bool(adv.get("lang_attr", ""))),
                ("Canonical",    can_.get("is_self_referencing", False)),
                ("Indexable",    idx_d.get("is_indexable", True)),
            ],
            [
                ("HSTS",         hdr_data.get("has_hsts", False)),
                ("Compression",  hdr_data.get("has_compression", False)),
                ("Schema",       adv.get("has_schema", False)),
                ("Twitter Cards",adv.get("twitter_complete", False)),
                ("Favicon",      adv.get("has_favicon", False)),
            ],
            [
                ("OG Tags",      meta.get("has_og_tags", False)),
                ("OG Image",     meta.get("has_og_image", False)),
                ("Hreflang",     adv.get("has_hreflang", False)),
                ("Pagination",   adv.get("has_pagination", False)),
                ("RSS Feed",     tech_seo.get("has_rss_feed", False)),
                ("Mixed Content",not tech_seo.get("has_mixed_content", False)),
            ],
        ]
        row_labels = ["Core", "Security & Speed", "Social & Discovery"]
        for row_label, row in zip(row_labels, signal_rows):
            st.caption(row_label)
            cols = st.columns(6)
            for col, (label, val) in zip(cols, row):
                icon = "✅" if val else "❌"
                col.markdown(
                    f"<div style='text-align:center;padding:6px 2px;"
                    f"background:var(--seo-card-bg,#F8FAFC);border-radius:8px;border:1px solid var(--seo-border,rgba(148,163,184,.22))'>"
                    f"<div style='font-size:1.2rem'>{icon}</div>"
                    f"<div style='font-size:.65rem;color:var(--seo-muted,#475569);margin-top:2px'>{label}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    # Tab 1 — Outgoing Links (Ahrefs-style)
    with tabs[1]:
        st.markdown('<div class="section-header">🔵 Internal Links</div>', unsafe_allow_html=True)
        il_links = il.get("links", [])
        lm1, lm2, lm3, lm4, lm5 = st.columns(5)
        lm1.metric("Total", il.get("total_links",0))
        lm2.metric("Dofollow", il.get("dofollow_count",0))
        lm3.metric("Nofollow", il.get("nofollow_count",0))
        lm4.metric("Broken", il.get("broken_count",0))
        lm5.metric("Redirects", il.get("redirect_count",0))
        if il_links:
            render_link_table(il_links, max_rows=100, key_prefix="url_il")
        else:
            st.info("No internal links found — enable 'Audit Links' to collect link data.")

        st.markdown("---")
        st.markdown('<div class="section-header">🟣 External Links</div>', unsafe_allow_html=True)
        el_links = el_.get("links", [])
        em1, em2, em3, em4, em5, em6 = st.columns(6)
        em1.metric("Total", el_.get("total_links",0))
        em2.metric("Domains", el_.get("unique_domains",0))
        em3.metric("Dofollow", el_.get("dofollow_count",0))
        em4.metric("Nofollow", el_.get("nofollow_count",0))
        em5.metric("Broken", el_.get("broken_count",0))
        em6.metric("Blocked", el_.get("blocked_count",0) or 0)

        if not el_links:
            st.info("No external links found — enable 'Audit Links' to collect link data.")
        elif el_.get("broken_count",0) or el_.get("blocked_count",0):
            bc = el_.get("broken_count",0) or 0
            blk = el_.get("blocked_count",0) or 0
            if bc:
                st.error(f"⚠️ {bc} broken external link(s) detected — these return 4xx/5xx HTTP errors.")
            if blk:
                st.warning(f"🚫 {blk} link(s) blocked (e.g. LinkedIn/Twitter return 999) — not necessarily broken, site blocks automated checks.")
            render_link_table(el_links, max_rows=100, key_prefix="url_el")
        else:
            render_link_table(el_links, max_rows=100, key_prefix="url_el")

        if not il_links and not el_links:
            st.markdown("""
            > **Tip:** Turn on **"Audit Links"** in the sidebar settings before running the audit
            > to see all internal and external links with their HTTP status codes.
            """)

    # Tab 2 — SERP & Social
    with tabs[2]:
        serp = adv.get("serp_preview", {})
        social = adv.get("social_preview", {})
        s1, s2 = st.columns(2)
        with s1:
            st.markdown('<div class="section-header">🔍 Google SERP Preview</div>', unsafe_allow_html=True)
            if serp:
                render_serp_preview(serp)
            else:
                st.info("SERP data unavailable.")
        with s2:
            st.markdown('<div class="section-header">📱 Social Card Preview</div>', unsafe_allow_html=True)
            if social:
                render_social_preview(social, r.get("url",""))
            else:
                st.info("Social preview data unavailable.")

    # Tab 3 — Schema
    with tabs[3]:
        st.markdown('<div class="section-header">🔬 Structured Data</div>', unsafe_allow_html=True)
        schema_types = adv.get("schema_types", [])
        schema_raw   = adv.get("schema_raw", [])
        schema_errors= adv.get("schema_errors", [])
        if schema_errors:
            st.error(f"JSON-LD Parse Errors: {'; '.join(schema_errors)}")
        render_schema_display(schema_types, schema_raw)

    # Tab 4 — Technical (new)
    with tabs[4]:
        _tech = adv.get("technical_seo", {})
        _hdr  = adv.get("http_headers_data", {})
        _raw_headers = r.get("http_headers", {})

        # ── Performance & Page Size ───────────────────────────────────────
        st.markdown('<div class="section-header">⚡ Performance & Page Size</div>', unsafe_allow_html=True)
        tp1, tp2, tp3, tp4 = st.columns(4)
        tp1.metric("Page Size", f"{_tech.get('page_size_kb', 0)} KB",
                   help=_tech.get("page_size_label", ""))
        tp2.metric("TTFB", f"{_tech.get('cwv_ttfb_ms', 0)} ms",
                   help=_tech.get("cwv_ttfb_estimate", ""))
        tp3.metric("DOM Elements", _tech.get("dom_elements", 0),
                   help=_tech.get("dom_size_label", ""))
        tp4.metric("Scripts", f"{_tech.get('external_script_count',0)} ext / {_tech.get('script_count',0)} total")

        # ── Core Web Vitals Estimates ─────────────────────────────────────
        st.markdown('<div class="section-header">📊 Core Web Vitals Estimates</div>', unsafe_allow_html=True)
        st.caption("These are heuristic estimates based on response time and page size — not real field data.")


        cwv1, cwv2, cwv3 = st.columns(3)
        ttfb_est = _tech.get("cwv_ttfb_estimate", "—")
        lcp_est  = _tech.get("cwv_lcp_estimate", "—")
        cls_est  = _tech.get("cwv_cls_risk", "—")

        for col, metric_name, metric_val in [
            (cwv1, "TTFB (Time to First Byte)", ttfb_est),
            (cwv2, "LCP (Largest Contentful Paint)", lcp_est),
            (cwv3, "CLS Risk (Layout Shift)", cls_est),
        ]:
            bg, fg = _cwv_color(metric_val)
            col.markdown(
                f"<div style='background:{bg};color:{fg};border-radius:10px;padding:14px 16px;text-align:center'>"
                f"<div style='font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em'>{metric_name}</div>"
                f"<div style='font-size:1.05rem;font-weight:800;margin-top:4px'>{metric_val}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # ── HTTP Headers ──────────────────────────────────────────────────
        st.markdown('<div class="section-header">📡 HTTP Response Headers</div>', unsafe_allow_html=True)
        if _raw_headers:
            # SEO-critical headers first
            critical_hdr_keys = [
                "content-type", "content-encoding", "cache-control",
                "strict-transport-security", "content-security-policy",
                "x-robots-tag", "x-frame-options", "x-content-type-options",
                "referrer-policy", "permissions-policy", "server",
                "etag", "last-modified", "cf-cache-status",
            ]
            shown_keys = set()
            crit_rows = ""
            for key in critical_hdr_keys:
                for raw_key, val in _raw_headers.items():
                    if raw_key.lower() == key:
                        crit_rows += (
                            f"<tr><td style='padding:5px 10px;font-weight:600;color:var(--seo-info-text,#1E40AF);"
                            f"font-size:.78rem;white-space:nowrap'>{raw_key}</td>"
                            f"<td style='padding:5px 10px;font-size:.76rem;color:var(--seo-text,#374151);"
                            f"word-break:break-all'>{val}</td></tr>"
                        )
                        shown_keys.add(raw_key.lower())
                        break

            other_rows = ""
            for raw_key, val in _raw_headers.items():
                if raw_key.lower() not in shown_keys:
                    other_rows += (
                        f"<tr><td style='padding:4px 10px;font-size:.74rem;color:var(--seo-muted,#64748B);"
                        f"white-space:nowrap'>{raw_key}</td>"
                        f"<td style='padding:4px 10px;font-size:.73rem;color:var(--seo-text,#475569);"
                        f"word-break:break-all'>{val}</td></tr>"
                    )

            st.html(
                f"<div style='overflow-x:auto;border-radius:8px;border:1px solid var(--seo-border,rgba(148,163,184,.22))'>"
                f"<table style='width:100%;border-collapse:collapse;background:var(--seo-card-bg,#fff)'>"
                f"<thead style='background:var(--table-header-bg,rgba(241,245,249,.9))'><tr>"
                f"<th style='padding:7px 10px;text-align:left;font-size:.78rem;color:var(--seo-info-text,#1E40AF)'>Header</th>"
                f"<th style='padding:7px 10px;text-align:left;font-size:.78rem;color:var(--seo-info-text,#1E40AF)'>Value</th>"
                f"</tr></thead><tbody>"
                f"{crit_rows}"
                f"<tr><td colspan='2' style='padding:4px 10px;font-size:.7rem;color:var(--seo-muted,#94A3B8);"
                f"background:var(--seo-card-bg,#F8FAFC)'>— Other headers —</td></tr>"
                f"{other_rows}"
                f"</tbody></table></div>"
            )
        else:
            st.info("No HTTP headers captured. Re-run the audit to collect headers.")

        # ── Security Headers ──────────────────────────────────────────────
        st.markdown('<div class="section-header">🔒 Security Headers</div>', unsafe_allow_html=True)
        sec_items = [
            ("HSTS (Strict-Transport-Security)", _hdr.get("has_hsts", False),
             _hdr.get("hsts_value", "") or "Missing — add max-age=31536000; includeSubDomains"),
            ("Content-Security-Policy", _hdr.get("has_csp", False),
             "Present" if _hdr.get("has_csp") else "Missing — helps prevent XSS attacks"),
            ("X-Frame-Options", _hdr.get("has_x_frame_options", False),
             _hdr.get("x_frame_options", "") or "Missing — add SAMEORIGIN to prevent clickjacking"),
            ("X-Content-Type-Options", _hdr.get("has_x_content_type_options", False),
             "nosniff" if _hdr.get("has_x_content_type_options") else "Missing — add nosniff"),
            ("Referrer-Policy", _hdr.get("has_referrer_policy", False),
             _hdr.get("referrer_policy", "") or "Missing — recommended: strict-origin-when-cross-origin"),
            ("Compression (gzip/br)", _hdr.get("has_compression", False),
             _hdr.get("content_encoding", "identity") or "No compression detected"),
        ]
        for name, present, detail in sec_items:
            icon = "✅" if present else "❌"
            color = "var(--seo-success,#059669)" if present else "var(--seo-error,#DC2626)"
            bg = "var(--seo-success-bg,rgba(5,150,105,.09))" if present else "var(--seo-error-bg,rgba(220,38,38,.09))"
            border = "var(--seo-success-border,rgba(5,150,105,.25))" if present else "var(--seo-error-border,rgba(220,38,38,.25))"
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;padding:7px 12px;"
                f"background:{bg};border-radius:7px;margin-bottom:5px;"
                f"border:1px solid {border}'>"
                f"<span style='font-size:1rem'>{icon}</span>"
                f"<span style='font-weight:600;font-size:.82rem;color:{color};min-width:220px'>{name}</span>"
                f"<span style='font-size:.76rem;color:var(--seo-text,#374151)'>{detail}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # ── Resource Analysis ─────────────────────────────────────────────
        st.markdown('<div class="section-header">📦 Resource Analysis</div>', unsafe_allow_html=True)
        ra1, ra2, ra3, ra4 = st.columns(4)
        ra1.metric("Scripts (total)", _tech.get("script_count", 0))
        ra2.metric("Scripts (external)", _tech.get("external_script_count", 0))
        ra3.metric("Stylesheets (total)", _tech.get("stylesheet_count", 0))
        ra4.metric("Stylesheets (external)", _tech.get("external_stylesheet_count", 0))
        rb1, rb2, rb3, rb4 = st.columns(4)
        rb1.metric("Iframes", _tech.get("iframe_count", 0))
        rb2.metric("DOM Elements", _tech.get("dom_elements", 0))
        rb3.metric("Preconnect hints", len(_tech.get("preconnect_domains", [])))
        rb4.metric("DNS-Prefetch", "Yes" if _tech.get("has_dns_prefetch") else "No")

        if _tech.get("preconnect_domains"):
            st.caption("Preconnect domains: " + ", ".join(_tech["preconnect_domains"][:8]))

        mixed_cnt = _tech.get("mixed_content_count", 0)
        if mixed_cnt:
            st.error(f"🔴 Mixed Content: {mixed_cnt} HTTP resource(s) loaded on an HTTPS page. Fix immediately.")
        else:
            st.success("✅ No mixed content detected.")

        # ── AMP & Pagination ──────────────────────────────────────────────
        st.markdown('<div class="section-header">📄 AMP & Pagination</div>', unsafe_allow_html=True)
        amp_col, pag_col = st.columns(2)
        with amp_col:
            st.markdown("**AMP**")
            if _tech.get("has_amp"):
                st.info(f"AMP version detected (Google deprecated AMP as a ranking factor in 2021)")
                if _tech.get("amp_url"):
                    st.caption(f"AMP URL: {_tech['amp_url']}")
            else:
                st.info("No AMP version detected.")
        with pag_col:
            st.markdown("**Pagination**")
            if _tech.get("has_pagination_prev") or _tech.get("has_pagination_next"):
                st.success("✅ Pagination signals present")
                if _tech.get("pagination_prev_url"):
                    st.caption(f"rel=prev: {_tech['pagination_prev_url']}")
                if _tech.get("pagination_next_url"):
                    st.caption(f"rel=next: {_tech['pagination_next_url']}")
            else:
                st.info("No pagination (rel=prev/next) detected.")

        if _tech.get("has_rss_feed"):
            st.success(f"✅ RSS/Atom feed detected: {_tech.get('rss_url', '')}")

    # Tab 5 — Keyword Density
    with tabs[5]:
        st.markdown('<div class="section-header">🔑 Keyword Density Analysis</div>', unsafe_allow_html=True)
        st.caption("Top words appearing in visible page content. Helps identify primary and secondary topics.")
        import re as _re
        from collections import Counter
        _html_content = r.get("content", {})
        _word_count   = _html_content.get("word_count", 0)
        # Pull raw text via soup if available, else skip
        _raw_text = ""
        try:
            _soup_ref = r.get("_soup_text", "")
            if _soup_ref:
                _raw_text = _soup_ref
            else:
                # Build from title + description + headings as fallback
                _title = r.get("metadata", {}).get("title", "") or ""
                _desc  = r.get("metadata", {}).get("description", "") or ""
                _h1s   = " ".join(r.get("headings", {}).get("h1_texts", []) or [])
                _raw_text = f"{_title} {_desc} {_h1s}"
        except Exception:
            _raw_text = ""

        _STOPWORDS = {
            "the","a","an","and","or","but","in","on","at","to","for","of","with",
            "is","are","was","were","be","been","being","have","has","had","do","does",
            "did","will","would","could","should","may","might","shall","can","this",
            "that","these","those","it","its","their","they","we","our","you","your",
            "he","she","his","her","from","by","as","into","through","about","up","out",
            "if","then","than","so","not","no","only","also","more","what","how","all",
            "i","me","my","us","who","which","when","where","there","here","any","some",
        }

        if _raw_text:
            _words = _re.findall(r'\b[a-z]{3,}\b', _raw_text.lower())
            _filtered = [w for w in _words if w not in _STOPWORDS]
            _freq = Counter(_filtered)
            _total_words = max(len(_filtered), 1)
            _top_kw = _freq.most_common(20)
        else:
            _top_kw = []

        if not _top_kw:
            st.info("Keyword data unavailable for this audit. The content text could not be extracted.")
        else:
            kw_col1, kw_col2 = st.columns([3, 2])
            with kw_col1:
                st.markdown("**Top 20 Keywords by Frequency**")
                kw_html = "<div style='display:flex;flex-wrap:wrap;gap:8px;padding:12px 0'>"
                for word, count in _top_kw:
                    density = round(count / _total_words * 100, 1)
                    # Size varies with frequency
                    fs = 0.75 + (count / max(_top_kw[0][1], 1)) * 0.55
                    kw_html += (
                        f"<span style='background:var(--seo-accent-light,rgba(79,70,229,.10));"
                        f"border:1px solid var(--seo-accent-border,rgba(79,70,229,.2));"
                        f"color:var(--seo-accent,#4F46E5);border-radius:8px;"
                        f"padding:4px 12px;font-size:{fs:.2f}rem;font-weight:600;"
                        f"cursor:default' title='{count}× ({density}%)'>"
                        f"{word} <span style='background:var(--seo-accent,#4F46E5);color:#fff;"
                        f"border-radius:4px;padding:1px 5px;font-size:.65rem;margin-left:3px'>{count}</span>"
                        f"</span>"
                    )
                kw_html += "</div>"
                st.markdown(kw_html, unsafe_allow_html=True)
            with kw_col2:
                st.markdown("**Density Table**")
                kw_rows = ""
                for rank, (word, count) in enumerate(_top_kw[:15], 1):
                    density = round(count / _total_words * 100, 2)
                    bar_w = round(count / max(_top_kw[0][1], 1) * 100)
                    kw_rows += (
                        f"<tr>"
                        f"<td style='padding:5px 8px;font-size:.75rem;color:var(--seo-muted,#64748B);width:24px'>{rank}</td>"
                        f"<td style='padding:5px 8px;font-size:.82rem;font-weight:600;color:var(--seo-heading,#0F172A)'>{word}</td>"
                        f"<td style='padding:5px 8px'><div style='background:var(--seo-border,rgba(148,163,184,.2));border-radius:4px;height:8px;width:100%'>"
                        f"<div style='width:{bar_w}%;background:var(--seo-accent,#4F46E5);height:100%;border-radius:4px'></div></div></td>"
                        f"<td style='padding:5px 8px;font-size:.78rem;color:var(--seo-muted,#64748B);white-space:nowrap'>{count}× &nbsp; {density}%</td>"
                        f"</tr>"
                    )
                st.html(
                    f"<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse'>"
                    f"<thead><tr>"
                    f"<th style='padding:5px 8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:left'>#</th>"
                    f"<th style='padding:5px 8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:left'>Keyword</th>"
                    f"<th style='padding:5px 8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:left;min-width:80px'>Freq</th>"
                    f"<th style='padding:5px 8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:left'>Count / Density</th>"
                    f"</tr></thead><tbody>{kw_rows}</tbody></table></div>"
                )

    # Tab 6 — Issues (severity-grouped)
    with tabs[6]:
        import html as _h_esc
        _crit_issues = [i for i in issues if i.get("severity","").lower() in ("critical",)]
        _high_issues = [i for i in issues if i.get("severity","").lower() in ("high",)]
        _med_issues  = [i for i in issues if i.get("severity","").lower() in ("medium","moderate","low","")]

        if not issues:
            st.success("No issues found — this page looks clean.")
        else:
            def _issue_rows(rows, dot_cls, tag_cls, tag_lbl):
                out = ""
                for iss in rows:
                    t = _h_esc.escape(str(iss.get("issue", iss.get("message", ""))))
                    d = _h_esc.escape(str(iss.get("recommendation", iss.get("description", ""))))
                    imp = iss.get("impact_score", 0)
                    out += f"""
                    <div class='issue-row'>
                      <div class='issue-dot {dot_cls}'></div>
                      <div class='issue-body'>
                        <div class='issue-title'>{t}</div>
                        {'<div class="issue-desc">' + d + '</div>' if d else ''}
                        {'<div class="issue-desc" style="color:var(--seo-text-3);">Impact: ' + str(imp) + '/10</div>' if imp else ''}
                      </div>
                      <span class='issue-tag {tag_cls}'>{tag_lbl}</span>
                    </div>"""
                return out

            parts = []
            if _crit_issues:
                parts.append(f"<div class='issue-section-head'>Critical <span class='issue-cnt r'>{len(_crit_issues)}</span></div>")
                parts.append(_issue_rows(_crit_issues, "r", "r", "Critical"))
            if _high_issues:
                parts.append(f"<div class='issue-section-head'>High <span class='issue-cnt w'>{len(_high_issues)}</span></div>")
                parts.append(_issue_rows(_high_issues, "w", "w", "High"))
            if _med_issues:
                parts.append(f"<div class='issue-section-head'>Other <span class='issue-cnt b'>{len(_med_issues)}</span></div>")
                parts.append(_issue_rows(_med_issues, "b", "b", "Info"))

            st.html(f"<div class='seo-card'>{''.join(parts)}</div>")

    # Tab 7 — Top Recommendations by Impact
    with tabs[7]:
        from modules.scoring import get_top_issues_by_impact
        st.markdown('<div class="section-header">💡 Top Issues by Impact Score</div>', unsafe_allow_html=True)
        st.caption("Sorted by impact score (10 = highest ranking factor). Fix these first.")
        top = get_top_issues_by_impact(issues, 15)
        if not top:
            st.success("🎉 No recommendations — this page is well optimised!")
        else:
            for i, iss in enumerate(top, 1):
                sev = iss.get("severity","Low")
                imp = iss.get("impact_score",0)
                eff = iss.get("effort","—")
                bar_pct = imp * 10
                st.markdown(f"""
                <div style='padding:12px 16px;background:{_sev_bg(sev)};border-radius:10px;
                margin-bottom:10px;border-left:4px solid {_sev_color(sev)}'>
                    <div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px'>
                        <span style='font-weight:700;font-size:.9rem;color:var(--seo-heading,#0F172A)'>
                            {i}. {iss.get("issue","")}</span>
                        <div style='display:flex;gap:6px;align-items:center'>
                            <div style='background:rgba(148,163,184,.25);border-radius:4px;overflow:hidden;width:80px;height:10px'>
                                <div style='background:{_sev_color(sev)};width:{bar_pct}%;height:100%'></div>
                            </div>
                            <span style='font-size:.78rem;font-weight:700;color:{_sev_color(sev)}'>{imp}/10</span>
                            <span style='font-size:.75rem;color:var(--seo-muted,#64748B)'>• Effort: {eff}</span>
                        </div>
                    </div>
                    <div style='font-size:.76rem;color:var(--seo-muted,#64748B);margin:3px 0'>📂 {iss.get("category","")} • {sev}</div>
                    <div style='font-size:.84rem;color:var(--seo-info-text,#1D4ED8);margin-top:6px'>✅ {iss.get("recommendation","")}</div>
                </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# Dashboard
# ════════════════════════════════════════════════════════════════════════════

def page_dashboard():
    import html as _hesc
    results  = st.session_state.audit_results
    last_date= st.session_state.last_audit_date

    # ── Compute stats (safe even with no data) ────────────────────────────
    total      = len(results)
    scores     = [r.get("seo_score", 0) for r in results]
    avg_sc     = round(sum(scores) / total, 1) if total else 0
    all_issues = [i for r in results for i in r.get("all_issues", [])]
    warn_iss   = sum(1 for i in all_issues if i.get("severity","").lower() in ("warning","medium","high"))
    crit_iss   = sum(1 for i in all_issues if i.get("severity","").lower() == "critical")
    s90        = sum(1 for s in scores if s >= 90)
    s70        = sum(1 for s in scores if 70 <= s < 90)
    s50        = sum(1 for s in scores if 50 <= s < 70)
    slo        = sum(1 for s in scores if s < 50)
    dist_max   = max(s90, s70, s50, slo, 1)

    last_str = last_date or "—"

    # ── Top bar ───────────────────────────────────────────────────────────
    st.html("""
    <div style='background:#fff;border-bottom:0.5px solid #E2E8F0;padding:10px 0 10px;
    display:flex;align-items:center;gap:10px;margin-bottom:20px;border-radius:10px;padding:10px 16px;'>
      <span style='font-size:13px;color:#94A3B8;'>🏠</span>
      <span style='font-size:12px;color:#94A3B8;'>›</span>
      <span style='font-size:13px;font-weight:500;color:#0F172A;'>Overview</span>
      <div style='flex:1'></div>
      <div style='background:#F8FAFC;border:0.5px solid #E2E8F0;border-radius:7px;
      padding:6px 12px;font-size:12px;color:#94A3B8;display:flex;align-items:center;gap:6px;'>
        🔍 Search audits…
      </div>
    </div>
    """)

    # ── 4 Stat cards ──────────────────────────────────────────────────────
    avg_color = "green" if (total and avg_sc >= 75) else "amber" if (total and avg_sc >= 50) else ("red" if (total and avg_sc < 50) else "")
    avg_disp  = str(avg_sc) if total else "—"
    st.html(f"""
    <div style='display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;'>
      <div class='stat-card blue'>
        <div class='stat-label'>Total audits</div>
        <div class='stat-value'>{total}</div>
        <div class='stat-footer'>{'Last: ' + last_str if last_str != '—' else 'No audits yet'}</div>
      </div>
      <div class='stat-card green'>
        <div class='stat-label'>Avg SEO score</div>
        <div class='stat-value {avg_color}'>{avg_disp}</div>
        <div class='stat-footer'>across all sessions</div>
      </div>
      <div class='stat-card amber'>
        <div class='stat-label'>Warnings</div>
        <div class='stat-value amber'>{warn_iss}</div>
        <div class='stat-footer'>across {total} URL{'s' if total != 1 else ''}</div>
      </div>
      <div class='stat-card red'>
        <div class='stat-label'>Critical issues</div>
        <div class='stat-value red'>{crit_iss}</div>
        <div class='stat-footer'>need attention</div>
      </div>
    </div>
    """)

    # ── Two-column layout ─────────────────────────────────────────────────
    col_left, col_right = st.columns([3, 2])

    with col_left:
        # Recent audits card
        if not results:
            st.html("""
            <div class='seo-card'>
              <div class='seo-card-head'><h3>Recent audits</h3></div>
              <div style='padding:40px 24px;text-align:center;'>
                <div style='font-size:2.5rem;margin-bottom:12px'>🚀</div>
                <div style='font-size:14px;font-weight:500;color:#0F172A;margin-bottom:6px'>Run your first SEO audit</div>
                <div style='font-size:12px;color:#64748B;max-width:360px;margin:0 auto 16px;line-height:1.6;'>
                  Paste a URL in <b>New Audit</b> to get a full technical report — metadata, headings, images, links, PageSpeed, and more.</div>
                <div style='display:flex;gap:12px;justify-content:center;font-size:11px;color:#94A3B8;flex-wrap:wrap;'>
                  <span>📋 Single URL audit</span>
                  <span>📂 Bulk CSV / XLSX</span>
                  <span>🗺️ Sitemap XML import</span>
                </div>
              </div>
            </div>
            """)
        else:
            def _circle_cls(s):
                return "a" if s >= 75 else "b" if s >= 50 else "c"
            def _tag(s):
                if s >= 75: return "<span class='seo-tag g'>✓ Pass</span>"
                if s >= 50: return "<span class='seo-tag w'>Fair</span>"
                return "<span class='seo-tag r'>Poor</span>"

            rows_html = ""
            for r in results[-8:][::-1]:
                sc   = r.get("seo_score", 0)
                url  = _hesc.escape(r.get("url", ""))
                disp = url.replace("https://","").replace("http://","")[:55]
                atype = r.get("audit_type","general").title()
                nissues = len(r.get("all_issues", []))
                rows_html += f"""
                <div class='audit-row'>
                  <div class='score-circle {_circle_cls(sc)}'>{sc}</div>
                  <div style='flex:1;min-width:0;'>
                    <div class='audit-row-url'>{disp}</div>
                    <div class='audit-row-meta'>{atype} · {nissues} issue{'s' if nissues != 1 else ''}</div>
                  </div>
                  {_tag(sc)}
                </div>"""

            st.html(f"""
            <div class='seo-card'>
              <div class='seo-card-head'>
                <h3>Recent audits</h3>
                <span>{total} total</span>
              </div>
              {rows_html}
            </div>
            """)

    with col_right:
        # Score distribution
        def _bar(pct, color):
            return f"<div style='flex:1;height:6px;background:#F1F5F9;border-radius:3px;overflow:hidden;'><div style='width:{pct}%;height:100%;background:{color};border-radius:3px;'></div></div>"

        p90 = round(s90 / dist_max * 100)
        p70 = round(s70 / dist_max * 100)
        p50 = round(s50 / dist_max * 100)
        plo = round(slo / dist_max * 100)

        st.html(f"""
        <div class='seo-card' style='margin-bottom:12px;'>
          <div class='seo-card-head'><h3>Score distribution</h3></div>
          <div class='seo-card-body'>
            <div class='dist-bar-row'><span class='dist-bar-lbl' style='color:#059669;'>90–100</span>{_bar(p90,'#059669')}<span class='dist-bar-num'>{s90}</span></div>
            <div class='dist-bar-row'><span class='dist-bar-lbl' style='color:#2563EB;'>70–89</span>{_bar(p70,'#2563EB')}<span class='dist-bar-num'>{s70}</span></div>
            <div class='dist-bar-row'><span class='dist-bar-lbl' style='color:#D97706;'>50–69</span>{_bar(p50,'#D97706')}<span class='dist-bar-num'>{s50}</span></div>
            <div class='dist-bar-row'><span class='dist-bar-lbl' style='color:#DC2626;'>Below 50</span>{_bar(plo,'#DC2626')}<span class='dist-bar-num'>{slo}</span></div>
          </div>
        </div>
        """)

        # Issue summary
        high_iss = sum(1 for i in all_issues if i.get("severity","").lower() == "high")
        st.html(f"""
        <div class='seo-card'>
          <div class='seo-card-head'><h3>Issue summary</h3></div>
          <div class='seo-card-body'>
            <div class='dist-bar-row'>
              <span class='dist-bar-lbl' style='color:#DC2626;'>Critical</span>
              <div style='flex:1;height:6px;background:#FEF2F2;border-radius:3px;overflow:hidden;'>
                <div style='width:{min(crit_iss*8,100)}%;height:100%;background:#DC2626;border-radius:3px;'></div>
              </div>
              <span class='dist-bar-num'>{crit_iss}</span>
            </div>
            <div class='dist-bar-row'>
              <span class='dist-bar-lbl' style='color:#D97706;'>High</span>
              <div style='flex:1;height:6px;background:#FFFBEB;border-radius:3px;overflow:hidden;'>
                <div style='width:{min(high_iss*6,100)}%;height:100%;background:#D97706;border-radius:3px;'></div>
              </div>
              <span class='dist-bar-num'>{high_iss}</span>
            </div>
            <div class='dist-bar-row'>
              <span class='dist-bar-lbl' style='color:#2563EB;'>Warnings</span>
              <div style='flex:1;height:6px;background:#EFF6FF;border-radius:3px;overflow:hidden;'>
                <div style='width:{min(warn_iss*3,100)}%;height:100%;background:#2563EB;border-radius:3px;'></div>
              </div>
              <span class='dist-bar-num'>{warn_iss}</span>
            </div>
          </div>
        </div>
        """)

        if results:
            if st.button("View all results →", key="dash_view_results", use_container_width=True):
                st.session_state["nav_page"] = "📋 Audit Results"
                st.rerun()

        # Quick audit card — right column, below Issue summary
        st.html("""
        <div class='seo-card' style='margin-top:0;'>
          <div class='seo-card-head'><h3>Run a quick audit</h3></div>
          <div style='padding:14px 16px;'>
            <div style='background:#F8FAFC;border:0.5px solid #E2E8F0;border-radius:7px;
            padding:9px 12px;font-size:12px;color:#94A3B8;display:flex;align-items:center;gap:8px;'>
              🌐 Paste a URL to audit…
            </div>
          </div>
        </div>
        """)
        if st.button("🔍 Open audit form", key="dash_open_audit", use_container_width=True):
            st.session_state["nav_page"] = "🚀 New Audit"
            st.rerun()

    if not results:
        return

# ════════════════════════════════════════════════════════════════════════════
# New Audit
# ════════════════════════════════════════════════════════════════════════════

def page_new_audit():
    st.html("<div class='page-header'><h2>New audit</h2><p>Single URL · Bulk CSV/XLSX · Sitemap XML — full technical SEO analysis</p></div>")

    tab1, tab2, tab3 = st.tabs(["Single URL", "Bulk Upload (CSV/XLSX)", "Sitemap XML"])

    with st.sidebar:
        st.markdown("---")
        st.markdown("**⚙️ Audit Settings**")
        audit_type = st.selectbox("Page Type",
            ["Auto-Detect","Course","Blog","General"],
            help="Auto-Detect analyses the URL to determine type.")
        check_links    = st.toggle("Audit Links", value=True,
            help="Discover all internal and external links on the page.")
        validate_links = st.toggle("Validate Link Status Codes", value=True,
            help="HTTP-check every link and show status codes (like Ahrefs). Adds ~10-30s per page.")
        fetch_psi      = st.toggle("🚀 Fetch Real PageSpeed Insights", value=False,
            help="Call Google PageSpeed Insights API for accurate Lighthouse scores (Performance, CWV). Adds ~15s per URL.")
        psi_api_key    = APIKeyManager.get("psi") or ""
        if fetch_psi:
            if psi_api_key:
                _masked = APIKeyManager.mask(psi_api_key)
                st.markdown(
                    f"<div style='background:rgba(5,150,105,.10);border:1px solid rgba(5,150,105,.3);"
                    f"border-radius:7px;padding:8px 12px;font-size:.78rem;color:var(--seo-success,#059669)'>"
                    f"✅ Using stored PSI key &nbsp;<span style='font-family:monospace;opacity:.7'>{_masked}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<div style='background:rgba(245,158,11,.10);border:1px solid rgba(245,158,11,.3);"
                    "border-radius:7px;padding:8px 12px;font-size:.78rem;color:var(--seo-warning,#D97706)'>"
                    "⚠️ No PSI key saved. Add one in <b>Settings → API Keys</b> for higher rate limits."
                    "</div>",
                    unsafe_allow_html=True,
                )
            st.caption("📡 Real Lighthouse scores will appear in the **Mobile Audit → Core Web Vitals** tab.")
        max_workers    = st.slider("Concurrent Workers", 2, 16, 6)
        if validate_links:
            st.caption("🔍 Status validation ON — links will show 200/301/403/404/999 etc.")
        st.markdown("---")

    atype_map = {"Auto-Detect":"auto","Course":"course","Blog":"blog","General":"general"}
    atype = atype_map[audit_type]

    # audit_url uses module-level _cached_audit_url for stable caching across reruns
    audit_url = _cached_audit_url

    # ── Single URL ────────────────────────────────────────────────────────
    with tab1:
        st.markdown("#### Enter a URL to audit")
        single_url = st.text_input("URL",
            placeholder="https://example.com/courses/python-for-beginners",
            label_visibility="collapsed")
        run_single = st.button("🔍 Run Audit", type="primary", key="btn_single")

        if run_single:
            if not single_url.strip():
                st.warning("Please enter a URL.")
            elif not single_url.strip().startswith("http"):
                st.warning("URL must start with http:// or https://")
            else:
                spinner_msg = f"Auditing {single_url} …" + (" + PageSpeed Insights (30–90s)" if fetch_psi else "")
                with st.spinner(spinner_msg):
                    result = audit_url(single_url.strip(), atype, check_links, validate_links,
                                       fetch_pagespeed=fetch_psi, psi_api_key=psi_api_key or None)
                existing = [r["url"] for r in st.session_state.audit_results]
                if single_url.strip() in existing:
                    st.session_state.audit_results[existing.index(single_url.strip())] = result
                else:
                    st.session_state.audit_results.insert(0, result)
                st.session_state.last_audit_date  = datetime.now().strftime("%Y-%m-%d %H:%M")
                st.session_state.selected_url_idx = 0
                st.session_state.single_result    = result

        if st.session_state.single_result:
            render_inline_result(st.session_state.single_result)

    # ── Bulk Upload ───────────────────────────────────────────────────────
    with tab2:
        st.markdown("#### Upload a CSV or Excel file containing URLs")
        st.caption("Auto-detects URL column. Supports .csv and .xlsx")
        bulk_file = st.file_uploader("Upload file", type=["csv","xlsx"],
                                     label_visibility="collapsed")
        if bulk_file:
            urls, detected_col = extract_urls_from_csv_xlsx(bulk_file)
            if urls:
                _BULK_URL_LIMIT = 500
                if len(urls) > _BULK_URL_LIMIT:
                    st.warning(f"File contains {len(urls)} URLs — only the first {_BULK_URL_LIMIT} will be audited.")
                    urls = urls[:_BULK_URL_LIMIT]
                st.success(f"Found **{len(urls)}** valid URLs in column '**{detected_col}**'")
                with st.expander("Preview URLs"):
                    st.dataframe(pd.DataFrame({"URL": urls[:20]}), use_container_width=True)
                if st.button("🚀 Start Bulk Audit", type="primary", key="btn_bulk"):
                    bar  = st.progress(0.0)
                    stat = st.empty()
                    def upd_b(done, tot):
                        bar.progress(done/tot)
                        stat.text(f"Auditing URL {done}/{tot} …")
                    new_res = audit_urls_bulk(urls, atype, check_links, validate_links,
                                             max_workers=max_workers, progress_callback=upd_b,
                                             fetch_pagespeed=fetch_psi, psi_api_key=psi_api_key or None)
                    bar.progress(1.0); stat.text("Done!")
                    st.session_state.audit_results   = new_res + st.session_state.audit_results
                    st.session_state.last_audit_date = datetime.now().strftime("%Y-%m-%d %H:%M")
                    st.success(f"✅ Audited {len(new_res)} URLs.")

    # ── Sitemap ───────────────────────────────────────────────────────────
    with tab3:
        st.markdown("#### Upload an XML Sitemap")
        sm_file = st.file_uploader("Upload sitemap", type=["xml"],
                                   label_visibility="collapsed")
        if sm_file:
            _SITEMAP_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
            if sm_file.size > _SITEMAP_MAX_BYTES:
                st.error(f"Sitemap file is too large ({sm_file.size // (1024*1024)} MB). Maximum allowed size is 10 MB.")
                sm_urls = []
            else:
                sm_urls = extract_urls_from_sitemap(sm_file)
            if sm_urls:
                _SITEMAP_URL_LIMIT = 500
                if len(sm_urls) > _SITEMAP_URL_LIMIT:
                    st.warning(f"Sitemap contains {len(sm_urls)} URLs — only the first {_SITEMAP_URL_LIMIT} will be available.")
                    sm_urls = sm_urls[:_SITEMAP_URL_LIMIT]
                st.success(f"Extracted **{len(sm_urls)}** URLs.")
                select_all = st.checkbox("Select All URLs", value=True)
                chosen = sm_urls if select_all else st.multiselect(
                    "Choose URLs to audit", sm_urls, default=sm_urls[:10])
                st.info(f"**{len(chosen)}** URL(s) selected.")
                if st.button("🚀 Audit Sitemap URLs", type="primary", key="btn_sitemap"):
                    if not chosen:
                        st.warning("Select at least one URL.")
                    else:
                        bar  = st.progress(0.0)
                        stat = st.empty()
                        def upd_s(done, tot):
                            bar.progress(done/tot)
                            stat.text(f"Auditing URL {done}/{tot} …")
                        new_res = audit_urls_bulk(chosen, atype, check_links, validate_links,
                                                 max_workers=max_workers, progress_callback=upd_s,
                                                 fetch_pagespeed=fetch_psi, psi_api_key=psi_api_key or None)
                        bar.progress(1.0); stat.text("Done!")
                        st.session_state.audit_results   = new_res + st.session_state.audit_results
                        st.session_state.last_audit_date = datetime.now().strftime("%Y-%m-%d %H:%M")
                        st.success(f"✅ Audited {len(new_res)} URLs.")


# ════════════════════════════════════════════════════════════════════════════
# Audit Results
# ════════════════════════════════════════════════════════════════════════════

def page_results():
    st.html("<div class='page-header'><h2>Audit results</h2><p>All audited URLs — scores, issues, and filters</p></div>")
    results = st.session_state.audit_results
    if not results:
        st.info("No audit results yet. Run a **New Audit** first.")
        return

    df = build_results_df(results)

    # ── Apply nav_filter pre-set from dashboard cards ──────────────────────
    _nf = st.session_state.get("nav_filter")
    _score_default  = 0
    _sev_default    = "Any"
    _broken_default = False
    if _nf == "healthy_urls":    _score_default = 75
    elif _nf == "critical_urls": _score_default = 0;   _sev_default = "Any"   # handled below
    elif _nf in ("critical_issues",): _sev_default = "Critical"
    elif _nf == "high_issues":   _sev_default = "High"
    elif _nf in ("warnings","notices"): _sev_default = "Medium" if _nf == "warnings" else "Any"
    elif _nf == "broken_links":  _broken_default = True
    if _nf:
        _label_map = {
            "healthy_urls":    "✅ Showing Healthy URLs (score ≥ 75)",
            "critical_urls":   "🔴 Showing Critical URLs (score < 50)",
            "critical_issues": "🔴 Showing URLs with Critical Issues",
            "high_issues":     "🟠 Showing URLs with High Priority Issues",
            "warnings":        "🟡 Showing URLs with Warnings",
            "notices":         "🔵 Showing URLs with Notices",
            "broken_links":    "🔗 Showing URLs with Broken Links",
            "no_viewport":     "📱 Showing URLs Missing Viewport",
            "no_schema":       "🔬 Showing URLs Without Schema",
            "noindex":         "🚫 Showing Noindex URLs",
            "has_redirect":    "↪️ Showing URLs with Redirects",
        }
        st.info(_label_map.get(_nf, f"Filter: {_nf}"))
        col_clr, _ = st.columns([1, 5])
        if col_clr.button("✕ Clear Filter", key="clr_nav_filter"):
            st.session_state["nav_filter"] = None
            st.rerun()
        st.session_state["nav_filter"] = None   # consume once

    with st.expander("🔽 Filters", expanded=bool(_nf)):
        fc1,fc2,fc3,fc4 = st.columns(4)
        with fc1: type_filter = st.multiselect("Page Type", df["Type"].unique().tolist(),
                                                default=df["Type"].unique().tolist())
        with fc2: score_min = st.slider("Min SEO Score", 0, 100, _score_default)
        with fc3: sev_filter = st.selectbox("Has Severity", ["Any","Critical","High","Medium"],
                                             index=["Any","Critical","High","Medium"].index(_sev_default)
                                             if _sev_default in ["Any","Critical","High","Medium"] else 0)
        with fc4: broken_only = st.checkbox("Has Broken Links", value=_broken_default)

    mask = df["Type"].isin(type_filter) & (df["SEO Score"] >= score_min)
    if _nf == "critical_urls":
        mask &= df["SEO Score"] < 50
    elif _nf == "no_viewport":
        mask &= df["Viewport"] == False
    elif _nf == "no_schema":
        mask &= df["Schema"] == False
    elif _nf == "noindex":
        mask &= df["Indexable"] == False
    if sev_filter != "Any" and sev_filter in df.columns:
        mask &= df[sev_filter] > 0
    if broken_only:
        mask &= (df["Broken Int."] + df["Broken Ext."]) > 0

    df_f = df[mask].reset_index(drop=True)
    st.caption(f"Showing **{len(df_f)}** of {len(df)} URLs")

    def color_score(val):
        if val == 0:
            # 0 may mean a fetch error — use neutral gray instead of alarming red
            return "background-color:#F1F5F9;color:#64748B;font-weight:600"
        if val >= 90: return "background-color:#D1FAE5;color:#065F46;font-weight:600"
        if val >= 75: return "background-color:#DBEAFE;color:#1E40AF;font-weight:600"
        if val >= 50: return "background-color:#FEF3C7;color:#92400E;font-weight:600"
        return "background-color:#FEE2E2;color:#991B1B;font-weight:600"

    def color_red(val):
        return "color:#EF4444;font-weight:700" if (val and val > 0) else ""

    styled = (df_f.style
              .map(color_score, subset=["SEO Score"])
              .map(color_red, subset=["Critical","Broken Int.","Broken Ext."])
              .format({"SEO Score": "{:.1f}"}))
    st.dataframe(styled, use_container_width=True, height=450)

    st.markdown("---")
    selected_url = st.selectbox("🔎 Open URL Detail",
        [r.get("url","") for r in results],
        index=st.session_state.selected_url_idx)
    if st.button("Open Detail View →", type="primary"):
        idx = next((i for i,r in enumerate(results) if r.get("url")==selected_url), 0)
        st.session_state.selected_url_idx = idx
        st.session_state["nav_page"] = "🔎 URL Detail"
        st.rerun()

    if st.session_state.get("_confirm_clear"):
        st.warning("⚠️ This will delete all audit results from this session. Are you sure?")
        cc1, cc2 = st.columns(2)
        with cc1:
            if st.button("✔ Yes, Clear All", type="primary", use_container_width=True):
                st.session_state.audit_results   = []
                st.session_state.last_audit_date = None
                st.session_state.single_result   = None
                st.session_state["_confirm_clear"] = False
                st.rerun()
        with cc2:
            if st.button("✖ Cancel", use_container_width=True):
                st.session_state["_confirm_clear"] = False
                st.rerun()
    else:
        if st.button("🗑️ Clear All Results", type="secondary"):
            st.session_state["_confirm_clear"] = True
            st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# URL Detail
# ════════════════════════════════════════════════════════════════════════════

def page_url_detail():
    st.html("<div class='page-header'><h2>URL detail</h2><p>Deep-dive inspection — metadata · links · SERP · schema · technical · keywords</p></div>")
    results = st.session_state.audit_results
    if not results:
        st.info("No audit results yet. Run an audit first.")
        return

    idx = st.session_state.selected_url_idx
    if idx >= len(results): idx = 0
    r = results[idx]

    url_list = [res.get("url","") for res in results]
    chosen   = st.selectbox("Select URL", url_list, index=idx)
    if chosen != r.get("url"):
        idx = url_list.index(chosen)
        st.session_state.selected_url_idx = idx
        r = results[idx]

    score  = r.get("seo_score", 0)
    issues = r.get("all_issues", [])
    meta   = r.get("metadata", {})
    head   = r.get("headings", {})
    cont   = r.get("content", {})
    imgs   = r.get("images", {})
    can_   = r.get("canonical", {})
    idx_d  = r.get("indexability", {})
    il     = r.get("internal_links", {})
    el_    = r.get("external_links", {})
    adv    = r.get("advanced", {})
    atype  = r.get("audit_type","general")

    # ── Header ────────────────────────────────────────────────────────────
    hc1,hc2,hc3,hc4 = st.columns([3,1,1,1])
    with hc1:
        st.markdown(f"**URL:** [{r.get('url','')[:80]}]({r.get('url','')})")
        st.caption(f"Type: {atype.title()} | HTTP {r.get('status_code',0)} | "
                   f"Response: {r.get('response_time',0):.2f}s | "
                   f"Redirects: {r.get('redirect_count',0)}")
    with hc2:
        color = _score_color(score)
        st.markdown(f"""<div style='text-align:center'>
            <div style='font-size:2.4rem;font-weight:800;color:{color}'>{score}</div>
            <div style='font-size:.75rem;color:var(--seo-muted,#64748B)'>/ 100</div>
            <span class='{_score_class(score)} score-badge'>{_score_label(score)}</span>
            </div>""", unsafe_allow_html=True)
    with hc3: metric_card("Total Issues", len(issues), "#6366F1")
    with hc4: metric_card("Critical", sum(1 for i in issues if i.get("severity")=="Critical"), "#EF4444")
    st.markdown("---")

    tabs = st.tabs([
        "📊 Score Breakdown","🌐 SERP & Social","🔬 Schema & Technical",
        "📡 Technical","⚠️ Issues","🔗 Links","📄 Content & Images","🎓 Course/Blog","💡 Recommendations"
    ])

    # Tab 0 — Score Breakdown
    with tabs[0]:
        bd = r.get("score_breakdown",{})
        left_s, right_s = st.columns([1,1])
        with left_s:
            if bd:
                fig = go.Figure()
                fig.add_trace(go.Scatterpolar(
                    r=list(bd.values()),
                    theta=[k.replace("_"," ").title() for k in bd],
                    fill="toself", line_color="#3B82F6",
                    fillcolor="rgba(59,130,246,0.15)"))
                fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0,100])),
                                  showlegend=False, height=360,
                                  margin=dict(t=10,b=10,l=10,r=10))
                st.plotly_chart(fig, use_container_width=True)
        with right_s:
            st.markdown("**Category Scores**")
            for k, v in bd.items():
                st.markdown(
                    f"""<div style='display:flex;justify-content:space-between;
                    padding:6px 0;border-bottom:1px solid var(--table-row-border,rgba(148,163,184,.15))'>
                    <span style='font-size:.85rem;color:var(--seo-text,#374151)'>{k.replace("_"," ").title()}</span>
                    <span style='font-weight:700;color:{_score_color(v)}'>{v:.0f}</span></div>""",
                    unsafe_allow_html=True)

        # Advanced signals summary
        st.markdown('<div class="section-header">🔎 Technical Signals</div>', unsafe_allow_html=True)
        def chk(v): return "✅" if v else "❌"
        sig_items = [
            ("Viewport",        adv.get("has_viewport",False)),
            ("Charset",         adv.get("has_charset",False)),
            ("Lang Attr",       bool(adv.get("lang_attr",""))),
            ("Hreflang",        adv.get("has_hreflang",False)),
            ("Schema Markup",   adv.get("has_schema",False)),
            ("Twitter Cards",   adv.get("twitter_complete",False)),
            ("Favicon",         adv.get("has_favicon",False)),
            ("HTTPS",           r.get("url_structure",{}).get("is_https",False)),
            ("Indexable",       idx_d.get("is_indexable",True)),
            ("Self-Canonical",  can_.get("is_self_referencing",False)),
            ("OG Tags",         meta.get("has_og_tags",False)),
            ("OG Image",        meta.get("has_og_image",False)),
        ]
        sc1,sc2,sc3,sc4 = st.columns(4)
        for i,(name,val) in enumerate(sig_items):
            [sc1,sc2,sc3,sc4][i%4].markdown(f"{chk(val)} {name}")

        st.markdown('<div class="section-header">📋 Metadata Preview</div>', unsafe_allow_html=True)
        mp1, mp2 = st.columns(2)
        with mp1:
            tl = meta.get("title_length",0)
            st.markdown(f"**Meta Title** `{tl} chars`")
            st.code(meta.get("title","—") or "—", language=None)
        with mp2:
            dl = meta.get("description_length",0)
            st.markdown(f"**Meta Description** `{dl} chars`")
            d = meta.get("description","") or "—"
            st.code(d[:160]+("…" if len(d)>160 else ""), language=None)
        h1t, h2t, h3t, h4t = st.columns(4)
        h1t.metric("H1", head.get("h1_count",0))
        h2t.metric("H2", head.get("h2_count",0))
        h3t.metric("H3", head.get("h3_count",0))
        h4t.metric("H4", head.get("h4_count",0))
        if head.get("h1_texts"):
            st.caption(f"H1: {' | '.join(head['h1_texts'][:3])}")

        # Heading structure tree
        hd = r.get("heading_detail", {})
        if hd.get("tree_html"):
            st.markdown('<div class="section-header">🏗️ Heading Structure</div>', unsafe_allow_html=True)
            ht_l, ht_r = st.columns([2, 1])
            with ht_l:
                st.markdown(
                    f"<div style='background:var(--seo-card-bg,#F8FAFC);border:1px solid var(--seo-border,rgba(148,163,184,.22));"
                    f"border-radius:10px;padding:14px 18px;max-height:300px;overflow-y:auto'>"
                    f"{hd['tree_html']}</div>",
                    unsafe_allow_html=True)
            with ht_r:
                cnts = hd.get("counts", {})
                for lv in range(1, 7):
                    c = cnts.get(f"h{lv}", 0)
                    if c:
                        bar_w = min(c * 12, 100)
                        st.markdown(
                            f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:5px'>"
                            f"<span style='font-size:.72rem;font-weight:700;min-width:24px;color:var(--seo-text,#374151)'>H{lv}</span>"
                            f"<div style='flex:1;background:var(--seo-border,rgba(148,163,184,.22));border-radius:4px;height:8px'>"
                            f"<div style='width:{bar_w}%;background:var(--seo-accent,#4F46E5);height:100%;border-radius:4px'></div></div>"
                            f"<span style='font-size:.72rem;color:var(--seo-muted,#64748B);min-width:16px;text-align:right'>{c}</span>"
                            f"</div>",
                            unsafe_allow_html=True)
                kw_cov = hd.get("keyword_coverage", {})
                if kw_cov:
                    found = sum(1 for v in kw_cov.values() if v)
                    total_kw = len(kw_cov)
                    kw_color = "var(--seo-success,#059669)" if found == total_kw else "var(--seo-warning,#D97706)"
                    st.markdown(
                        f"<div style='margin-top:10px;font-size:.75rem;color:var(--seo-muted,#64748B)'>Keyword Coverage: "
                        f"<span style='color:{kw_color};font-weight:700'>{found}/{total_kw}</span> title keywords in H1/H2</div>",
                        unsafe_allow_html=True)
                if hd.get("sequence_violations"):
                    st.warning(f"⚠️ {len(hd['sequence_violations'])} heading level skip(s)")
                if hd.get("empty_headings"):
                    st.warning(f"⚠️ {len(hd['empty_headings'])} empty heading(s)")

    # Tab 1 — SERP & Social
    with tabs[1]:
        serp   = adv.get("serp_preview",{})
        social = adv.get("social_preview",{})
        s1, s2 = st.columns(2)
        with s1:
            st.markdown('<div class="section-header">🔍 Google SERP Preview</div>', unsafe_allow_html=True)
            render_serp_preview(serp) if serp else st.info("Unavailable.")
        with s2:
            st.markdown('<div class="section-header">📱 Social Card Preview</div>', unsafe_allow_html=True)
            render_social_preview(social, r.get("url","")) if social else st.info("Unavailable.")

    # Tab 2 — Schema & Technical
    with tabs[2]:
        st.markdown('<div class="section-header">🔬 Structured Data</div>', unsafe_allow_html=True)
        render_schema_display(adv.get("schema_types",[]), adv.get("schema_raw",[]))
        if adv.get("schema_errors"):
            st.error(f"JSON-LD parse errors: {'; '.join(adv['schema_errors'])}")

        st.markdown('<div class="section-header">🌍 Hreflang</div>', unsafe_allow_html=True)
        hreflang = adv.get("hreflang_tags",[])
        if hreflang:
            st.dataframe(pd.DataFrame(hreflang), use_container_width=True)
        else:
            st.info("No hreflang tags found. Add them if this is a multi-language site.")

        st.markdown('<div class="section-header">🐦 Twitter / X Card Tags</div>',
                    unsafe_allow_html=True)
        tc1,tc2,tc3,tc4 = st.columns(4)
        tc1.markdown(f"**twitter:card**\n`{adv.get('twitter_card','❌ missing') or '❌ missing'}`")
        tc2.markdown(f"**twitter:title**\n`{adv.get('twitter_title','❌ missing') or '❌ missing'}`")
        tc3.markdown(f"**twitter:description**\n`{(adv.get('twitter_description','') or '')[:40] or '❌ missing'}`")
        tc4.markdown(f"**twitter:image**\n`{'✅ set' if adv.get('twitter_image') else '❌ missing'}`")

        # Redirect chain
        chain = r.get("redirect_chain",[])
        if chain:
            st.markdown('<div class="section-header">🔄 Redirect Chain</div>', unsafe_allow_html=True)
            for i, u in enumerate(chain):
                arrow = "→ " if i < len(chain)-1 else "✅ "
                st.caption(f"{arrow} {u}")

    # Tab 3 — Technical (new)
    with tabs[3]:
        _t = adv.get("technical_seo", {})
        _h = adv.get("http_headers_data", {})
        _raw_h = r.get("http_headers", {})

        # Performance & Page Size
        st.markdown('<div class="section-header">⚡ Performance & Page Size</div>', unsafe_allow_html=True)
        pd1, pd2, pd3, pd4 = st.columns(4)
        pd1.metric("Page Size", f"{_t.get('page_size_kb', 0)} KB", help=_t.get("page_size_label", ""))
        pd2.metric("TTFB", f"{_t.get('cwv_ttfb_ms', 0)} ms", help=_t.get("cwv_ttfb_estimate", ""))
        pd3.metric("DOM Elements", _t.get("dom_elements", 0), help=_t.get("dom_size_label", ""))
        pd4.metric("Scripts", f"{_t.get('external_script_count',0)} ext / {_t.get('script_count',0)} total")

        # Core Web Vitals Estimates
        st.markdown('<div class="section-header">📊 Core Web Vitals Estimates</div>', unsafe_allow_html=True)
        st.caption("Heuristic estimates based on response time and page size — not real field data.")


        wv1, wv2, wv3 = st.columns(3)
        for wcol, mname, mval in [
            (wv1, "TTFB (Time to First Byte)", _t.get("cwv_ttfb_estimate", "—")),
            (wv2, "LCP (Largest Contentful Paint)", _t.get("cwv_lcp_estimate", "—")),
            (wv3, "CLS Risk (Layout Shift)", _t.get("cwv_cls_risk", "—")),
        ]:
            bg, fg = _cwv_color(mval)
            wcol.markdown(
                f"<div style='background:{bg};color:{fg};border-radius:10px;padding:14px 16px;text-align:center'>"
                f"<div style='font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em'>{mname}</div>"
                f"<div style='font-size:1.05rem;font-weight:800;margin-top:4px'>{mval}</div>"
                f"</div>", unsafe_allow_html=True)

        # HTTP Headers table
        st.markdown('<div class="section-header">📡 HTTP Response Headers</div>', unsafe_allow_html=True)
        if _raw_h:
            crit_keys = [
                "content-type","content-encoding","cache-control",
                "strict-transport-security","content-security-policy",
                "x-robots-tag","x-frame-options","x-content-type-options",
                "referrer-policy","permissions-policy","server",
                "etag","last-modified","cf-cache-status",
            ]
            shown = set()
            crit_html = ""
            for ck in crit_keys:
                for rk, rv in _raw_h.items():
                    if rk.lower() == ck:
                        crit_html += (
                            f"<tr><td style='padding:5px 10px;font-weight:600;color:var(--seo-info-text,#1E40AF);"
                            f"font-size:.78rem;white-space:nowrap'>{rk}</td>"
                            f"<td style='padding:5px 10px;font-size:.76rem;color:var(--seo-text,#374151);"
                            f"word-break:break-all'>{rv}</td></tr>"
                        )
                        shown.add(rk.lower())
                        break
            other_html = "".join(
                f"<tr><td style='padding:4px 10px;font-size:.74rem;color:var(--seo-muted,#64748B);"
                f"white-space:nowrap'>{rk}</td>"
                f"<td style='padding:4px 10px;font-size:.73rem;color:var(--seo-text,#475569);"
                f"word-break:break-all'>{rv}</td></tr>"
                for rk, rv in _raw_h.items() if rk.lower() not in shown
            )
            st.html(
                f"<div style='overflow-x:auto;border-radius:8px;border:1px solid var(--seo-border,rgba(148,163,184,.22))'>"
                f"<table style='width:100%;border-collapse:collapse;background:var(--seo-card-bg,#fff)'>"
                f"<thead style='background:var(--table-header-bg,rgba(241,245,249,.9))'><tr>"
                f"<th style='padding:7px 10px;text-align:left;font-size:.78rem;color:var(--seo-info-text,#1E40AF)'>Header</th>"
                f"<th style='padding:7px 10px;text-align:left;font-size:.78rem;color:var(--seo-info-text,#1E40AF)'>Value</th>"
                f"</tr></thead><tbody>{crit_html}"
                f"<tr><td colspan='2' style='padding:4px 10px;font-size:.7rem;color:var(--seo-muted,#94A3B8);"
                f"background:var(--seo-card-bg,#F8FAFC)'>— Other headers —</td></tr>"
                f"{other_html}</tbody></table></div>"
            )
        else:
            st.info("No HTTP headers captured. Re-run the audit to collect headers.")

        # Security Headers checklist
        st.markdown('<div class="section-header">🔒 Security Headers</div>', unsafe_allow_html=True)
        sec_chk = [
            ("HSTS (Strict-Transport-Security)", _h.get("has_hsts", False),
             _h.get("hsts_value", "") or "Missing — add max-age=31536000; includeSubDomains"),
            ("Content-Security-Policy", _h.get("has_csp", False),
             "Present" if _h.get("has_csp") else "Missing — helps prevent XSS attacks"),
            ("X-Frame-Options", _h.get("has_x_frame_options", False),
             _h.get("x_frame_options", "") or "Missing — add SAMEORIGIN"),
            ("X-Content-Type-Options", _h.get("has_x_content_type_options", False),
             "nosniff" if _h.get("has_x_content_type_options") else "Missing — add nosniff"),
            ("Referrer-Policy", _h.get("has_referrer_policy", False),
             _h.get("referrer_policy", "") or "Missing — recommended: strict-origin-when-cross-origin"),
            ("Compression (gzip/br)", _h.get("has_compression", False),
             _h.get("content_encoding", "identity") or "No compression detected"),
        ]
        for sname, spresent, sdetail in sec_chk:
            sbg = "var(--seo-success-bg,rgba(5,150,105,.09))" if spresent else "var(--seo-error-bg,rgba(220,38,38,.09))"
            sfg = "var(--seo-success,#059669)" if spresent else "var(--seo-error,#DC2626)"
            sborder = "var(--seo-success-border,rgba(5,150,105,.25))" if spresent else "var(--seo-error-border,rgba(220,38,38,.25))"
            sicon = "✅" if spresent else "❌"
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;padding:7px 12px;"
                f"background:{sbg};border-radius:7px;margin-bottom:5px;"
                f"border:1px solid {sborder}'>"
                f"<span style='font-size:1rem'>{sicon}</span>"
                f"<span style='font-weight:600;font-size:.82rem;color:{sfg};min-width:220px'>{sname}</span>"
                f"<span style='font-size:.76rem;color:var(--seo-text,#374151)'>{sdetail}</span>"
                f"</div>", unsafe_allow_html=True)

        # Resource Analysis
        st.markdown('<div class="section-header">📦 Resource Analysis</div>', unsafe_allow_html=True)
        rr1, rr2, rr3, rr4 = st.columns(4)
        rr1.metric("Scripts (total)", _t.get("script_count", 0))
        rr2.metric("Scripts (external)", _t.get("external_script_count", 0))
        rr3.metric("Stylesheets (total)", _t.get("stylesheet_count", 0))
        rr4.metric("Stylesheets (external)", _t.get("external_stylesheet_count", 0))
        rr5, rr6, rr7, rr8 = st.columns(4)
        rr5.metric("Iframes", _t.get("iframe_count", 0))
        rr6.metric("DOM Elements", _t.get("dom_elements", 0))
        rr7.metric("Preconnect hints", len(_t.get("preconnect_domains", [])))
        rr8.metric("DNS-Prefetch", "Yes" if _t.get("has_dns_prefetch") else "No")
        if _t.get("preconnect_domains"):
            st.caption("Preconnect domains: " + ", ".join(_t["preconnect_domains"][:8]))
        if _t.get("has_mixed_content"):
            st.error(f"🔴 Mixed Content: {_t.get('mixed_content_count',0)} HTTP resource(s) on HTTPS page.")
        else:
            st.success("✅ No mixed content detected.")

        # AMP & Pagination
        st.markdown('<div class="section-header">📄 AMP & Pagination</div>', unsafe_allow_html=True)
        ac, pc = st.columns(2)
        with ac:
            st.markdown("**AMP**")
            if _t.get("has_amp"):
                st.info("AMP version detected (Google deprecated AMP as a ranking factor in 2021)")
                if _t.get("amp_url"):
                    st.caption(f"AMP URL: {_t['amp_url']}")
            else:
                st.info("No AMP version detected.")
        with pc:
            st.markdown("**Pagination**")
            if _t.get("has_pagination_prev") or _t.get("has_pagination_next"):
                st.success("✅ Pagination signals present")
                if _t.get("pagination_prev_url"):
                    st.caption(f"rel=prev: {_t['pagination_prev_url']}")
                if _t.get("pagination_next_url"):
                    st.caption(f"rel=next: {_t['pagination_next_url']}")
            else:
                st.info("No pagination (rel=prev/next) detected.")
        if _t.get("has_rss_feed"):
            st.success(f"✅ RSS/Atom feed: {_t.get('rss_url', '')}")

    # Tab 4 — Issues (thematic)
    with tabs[4]:
        from modules.scoring import get_thematic_issues
        themed = get_thematic_issues(issues)
        if not themed:
            st.success("🎉 No issues found!")
        else:
            for theme, t_issues in themed.items():
                with st.expander(f"**{theme}** — {len(t_issues)} issue(s)",
                                 expanded=any(i.get("severity") in ["Critical","High"]
                                              for i in t_issues)):
                    for iss in sorted(t_issues, key=lambda x: x.get("impact_score",0), reverse=True):
                        sev = iss.get("severity","Low")
                        imp = iss.get("impact_score",0)
                        eff = iss.get("effort","—")
                        st.markdown(f"""
                        <div style='padding:10px 14px;background:{_sev_bg(sev)};border-radius:8px;
                        margin-bottom:8px;border-left:4px solid {_sev_color(sev)}'>
                            <div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px'>
                                <span style='font-weight:700;font-size:.88rem;color:var(--seo-heading,#0F172A)'>{iss.get("issue","")}</span>
                                <div style='display:flex;gap:6px'>
                                    <span style='background:{_sev_color(sev)};color:white;padding:2px 8px;border-radius:4px;font-size:.72rem;font-weight:700'>{sev}</span>
                                    <span style='background:var(--seo-accent-light,rgba(79,70,229,.12));color:var(--seo-accent,#4F46E5);padding:2px 8px;border-radius:4px;font-size:.72rem'>Impact: {imp}/10</span>
                                    <span style='background:var(--seo-card-bg-alt,#F1F5F9);color:var(--seo-text-light,#475569);padding:2px 8px;border-radius:4px;font-size:.72rem'>Effort: {eff}</span>
                                </div>
                            </div>
                            <div style='font-size:.75rem;color:var(--seo-muted,#64748B);margin-top:3px'>📂 {iss.get("category","")}</div>
                            <div style='font-size:.83rem;color:var(--seo-info-text,#1D4ED8);margin-top:6px'>✅ {iss.get("recommendation","")}</div>
                        </div>""", unsafe_allow_html=True)

    # Tab 5 — Links (Ahrefs-style)
    with tabs[5]:
        st.markdown('<div class="section-header">🔵 Internal Links</div>', unsafe_allow_html=True)
        i1,i2,i3,i4,i5,i6 = st.columns(6)
        i1.metric("Total",       il.get("total_links",0))
        i2.metric("Unique",      il.get("unique_links",0))
        i3.metric("Dofollow",    il.get("dofollow_count",0))
        i4.metric("Nofollow",    il.get("nofollow_count",0))
        i5.metric("Broken",      il.get("broken_count",0))
        i6.metric("Weak Anchors",il.get("weak_anchor_count",0))
        if il.get("links"):
            render_link_table(il["links"], max_rows=150, key_prefix="det_il")
        else:
            st.info("Enable 'Audit Links' in sidebar settings to see internal link details.")

        st.markdown("---")
        st.markdown('<div class="section-header">🟣 External / Outgoing Links</div>', unsafe_allow_html=True)
        e1,e2,e3,e4,e5,e6,e7 = st.columns(7)
        e1.metric("Total",    el_.get("total_links",0))
        e2.metric("Domains",  el_.get("unique_domains",0))
        e3.metric("Dofollow", el_.get("dofollow_count",0))
        e4.metric("Nofollow", el_.get("nofollow_count",0))
        e5.metric("Broken",   el_.get("broken_count",0))
        e6.metric("Blocked",  el_.get("blocked_count",0) or 0)
        e7.metric("Sponsored",el_.get("sponsored_count",0))

        be_d = el_.get("broken_count",0) or 0
        blk_d= el_.get("blocked_count",0) or 0
        if be_d:
            st.error(f"⚠️ {be_d} external link(s) return 4xx/5xx — these are broken and should be fixed.")
        if blk_d:
            st.warning(f"🚫 {blk_d} link(s) blocked (LinkedIn, Twitter etc. return 999 for bots) — not broken, just restricted access.")

        if el_.get("links"):
            render_link_table(el_["links"], max_rows=150, key_prefix="det_el")
        else:
            st.info("Enable 'Audit Links' in sidebar settings to see external link details.")

    # Tab 6 — Content & Images
    with tabs[6]:
        ctt1, ctt2 = st.columns(2)
        with ctt1:
            st.markdown('<div class="section-header">Content Quality</div>', unsafe_allow_html=True)
            ca1,ca2,ca3 = st.columns(3)
            ca1.metric("Word Count", cont.get("word_count",0))
            ca2.metric("Reading Time", f"{cont.get('reading_time',0)} min")
            ca3.metric("Content Ratio", f"{cont.get('content_ratio',0)}%")
            st.markdown(f"Thin Content: {'⚠️ Yes' if cont.get('is_thin') else '✅ No'}")
        with ctt2:
            st.markdown('<div class="section-header">Images</div>', unsafe_allow_html=True)
            ia1,ia2,ia3 = st.columns(3)
            ia1.metric("Total", imgs.get("total_images",0))
            ia2.metric("Missing Alt", imgs.get("missing_alt_count",0))
            ia3.metric("Empty Alt", imgs.get("empty_alt_count",0))
            if imgs.get("poor_alt_count",0):
                st.warning(f"⚠️ {imgs['poor_alt_count']} images with generic alt text")

        ctt3, ctt4 = st.columns(2)
        with ctt3:
            st.markdown('<div class="section-header">Canonical & Indexability</div>', unsafe_allow_html=True)
            st.markdown(f"**Canonical:** `{can_.get('canonical_url','—') or '—'}`")
            st.markdown(f"**Self-Referencing:** {'✅' if can_.get('is_self_referencing') else '❌'}")
            st.markdown(f"**Indexable:** {'✅' if idx_d.get('is_indexable',True) else '🔴 Noindex'}")
            st.markdown(f"**Meta Robots:** `{idx_d.get('robots_meta','Not set') or 'Not set'}`")
        with ctt4:
            st.markdown('<div class="section-header">URL Structure</div>', unsafe_allow_html=True)
            url_d = r.get("url_structure",{})
            st.markdown(f"**Length:** {url_d.get('length',0)} chars")
            st.markdown(f"**HTTPS:** {'✅' if url_d.get('is_https') else '🔴 No'}")
            st.markdown(f"**Slug:** `{url_d.get('slug','—')}`")
            rt = r.get("response_time",0)
            perf_color = "#EF4444" if rt > 3 else ("#F59E0B" if rt > 1 else "#10B981")
            st.markdown(f"**Response Time:** <span style='color:{perf_color};font-weight:700'>{rt:.2f}s</span>",
                        unsafe_allow_html=True)

    # Tab 7 — Course/Blog
    with tabs[7]:
        if atype == "course":
            ca = r.get("course_audit",{})
            st.markdown('<div class="section-header">🎓 Course Page Audit</div>', unsafe_allow_html=True)
            cv1,cv2,cv3 = st.columns(3)
            cv1.metric("Section Score", f"{ca.get('sections_score',0):.0f}%")
            cv2.metric("Schema", "✅" if ca.get("has_course_schema") else "❌")
            cv3.metric("Lead Form", "✅" if ca.get("conversion_elements",{}).get("Lead / Inquiry Form") else "❌")
            s1,s2 = st.columns(2)
            with s1:
                st.markdown("**Required Sections**")
                for n,f in ca.get("sections_found",{}).items():
                    st.markdown(f"{'✅' if f else '❌'} {n}")
            with s2:
                st.markdown("**Conversion Elements**")
                for n,f in ca.get("conversion_elements",{}).items():
                    st.markdown(f"{'✅' if f else '❌'} {n}")
        elif atype == "blog":
            ba = r.get("blog_audit",{})
            st.markdown('<div class="section-header">📝 Blog Page Audit</div>', unsafe_allow_html=True)
            bv1,bv2,bv3,bv4 = st.columns(4)
            bv1.metric("Elements Score", f"{ba.get('elements_score',0):.0f}%")
            bv2.metric("Word Count", ba.get("word_count",0))
            bv3.metric("Readability", ba.get("readability_score","—"))
            bv4.metric("Avg Sentence", f"{ba.get('avg_sentence_length',0)} wds")
            sv1,sv2 = st.columns(2)
            with sv1:
                st.markdown("**Blog Elements**")
                for n,f in ba.get("elements_found",{}).items():
                    st.markdown(f"{'✅' if f else '❌'} {n}")
            with sv2:
                st.markdown("**Technical**")
                st.markdown(f"{'✅' if ba.get('has_article_schema') else '❌'} Article Schema")
                st.markdown(f"{'✅' if ba.get('has_og_tags') else '❌'} Open Graph Tags")

            # ── Content Body Preview ─────────────────────────────────────
            st.markdown("---")
            intro_paras = cont.get("intro_paragraphs", [])
            conc_paras  = cont.get("conclusion_paragraphs", [])
            total_paras = cont.get("total_paragraphs", 0)

            if intro_paras or conc_paras:
                cp1, cp2 = st.columns(2)

                with cp1:
                    st.markdown(
                        "<div style='display:flex;align-items:center;gap:8px;margin-bottom:8px'>"
                        "<span style='background:var(--seo-accent,#4F46E5);color:#fff;padding:2px 10px;"
                        "border-radius:20px;font-size:.75rem;font-weight:700'>INTRO</span>"
                        "<span style='font-size:.8rem;color:var(--seo-muted,#64748B)'>Beginning of blog content</span>"
                        "</div>",
                        unsafe_allow_html=True
                    )
                    if intro_paras:
                        for i, para in enumerate(intro_paras):
                            border = "3px solid var(--seo-accent,#3B82F6)" if i == 0 else "2px solid var(--seo-accent-border,#93C5FD)"
                            opacity = "1" if i == 0 else "0.75"
                            st.markdown(
                                f"<div style='border-left:{border};background:var(--seo-info-bg,rgba(37,99,235,.07));"
                                f"padding:10px 14px;border-radius:0 6px 6px 0;margin-bottom:8px;"
                                f"opacity:{opacity}'>"
                                f"<span style='font-size:.78rem;color:var(--seo-text,#334155);line-height:1.6'>{para[:400]}{'…' if len(para)>400 else ''}</span>"
                                f"</div>",
                                unsafe_allow_html=True
                            )
                    else:
                        st.info("No intro paragraphs detected.")

                with cp2:
                    st.markdown(
                        "<div style='display:flex;align-items:center;gap:8px;margin-bottom:8px'>"
                        "<span style='background:var(--seo-success,#059669);color:#fff;padding:2px 10px;"
                        "border-radius:20px;font-size:.75rem;font-weight:700'>CONCLUSION</span>"
                        "<span style='font-size:.8rem;color:var(--seo-muted,#64748B)'>Ending of blog content</span>"
                        "</div>",
                        unsafe_allow_html=True
                    )
                    if conc_paras:
                        for i, para in enumerate(conc_paras):
                            border = "3px solid var(--seo-success,#10B981)" if i == len(conc_paras)-1 else "2px solid var(--seo-success-border,rgba(5,150,105,.4))"
                            opacity = "1" if i == len(conc_paras)-1 else "0.75"
                            st.markdown(
                                f"<div style='border-left:{border};background:var(--seo-success-bg,rgba(5,150,105,.07));"
                                f"padding:10px 14px;border-radius:0 6px 6px 0;margin-bottom:8px;"
                                f"opacity:{opacity}'>"
                                f"<span style='font-size:.78rem;color:var(--seo-text,#334155);line-height:1.6'>{para[:400]}{'…' if len(para)>400 else ''}</span>"
                                f"</div>",
                                unsafe_allow_html=True
                            )
                    else:
                        st.info("No conclusion paragraphs detected.")

                st.caption(f"Showing first 3 and last 3 paragraphs from {total_paras} total content paragraphs detected.")
            else:
                st.info("Content preview not available — re-run the audit to extract paragraph data.")
        else:
            st.info("General page — no course/blog specific checks available.")

    # Tab 8 — Recommendations
    with tabs[8]:
        from modules.scoring import get_top_issues_by_impact
        top = get_top_issues_by_impact(issues, 20)
        st.markdown('<div class="section-header">💡 Prioritised Recommendations</div>',
                    unsafe_allow_html=True)
        st.caption("Sorted by impact score (10 = critical ranking factor). Fix high-impact, low-effort items first.")
        if not top:
            st.success("🎉 No recommendations — this page is well optimised!")
        else:
            for i, iss in enumerate(top, 1):
                sev = iss.get("severity","Low")
                imp = iss.get("impact_score",0)
                eff = iss.get("effort","—")
                st.markdown(f"""
                <div style='padding:12px 16px;background:{_sev_bg(sev)};border-radius:10px;
                margin-bottom:10px;border-left:4px solid {_sev_color(sev)}'>
                    <div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px'>
                        <span style='font-weight:700;font-size:.9rem;color:var(--seo-heading,#0F172A)'>{i}. {iss.get("issue","")}</span>
                        <div style='display:flex;gap:6px;align-items:center'>
                            <div style='background:rgba(148,163,184,.25);border-radius:4px;overflow:hidden;width:70px;height:8px'>
                                <div style='background:{_sev_color(sev)};width:{imp*10}%;height:100%'></div>
                            </div>
                            <span style='font-size:.78rem;font-weight:700;color:{_sev_color(sev)}'>{imp}/10</span>
                            <span style='font-size:.75rem;color:var(--seo-muted,#64748B)'>Effort: {eff}</span>
                        </div>
                    </div>
                    <div style='font-size:.76rem;color:var(--seo-muted,#64748B);margin:3px 0'>📂 {iss.get("category","")} • {sev}</div>
                    <div style='font-size:.84rem;color:var(--seo-info-text,#1D4ED8);margin-top:6px'>✅ {iss.get("recommendation","")}</div>
                </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# Link Analysis
# ════════════════════════════════════════════════════════════════════════════

def page_link_analysis():
    st.html("<div class='page-header'><h2>Link analysis</h2><p>Internal · external · broken · nofollow · anchor text across all audited URLs</p></div>")
    results = st.session_state.audit_results
    if not results:
        st.info("No audit results yet. Run an audit first.")
        return

    from modules.link_auditor import (
        get_base_domain, categorize_domain,
        analyze_anchor_text, get_internal_link_opportunities,
    )

    # ── Build flat link lists with source URL attached ────────────────────
    all_int_links, all_ext_links = [], []
    for r_item in results:
        src = r_item.get("url", "")
        for lk in r_item.get("internal_links", {}).get("links", []):
            d = dict(lk); d["source"] = src
            all_int_links.append(d)
        for lk in r_item.get("external_links", {}).get("links", []):
            d = dict(lk); d["source"] = src
            all_ext_links.append(d)

    # ── Pre-compute totals ────────────────────────────────────────────────
    def _sum(key_path, link_type="internal_links"):
        k1, k2 = link_type, key_path
        return sum(r.get(k1, {}).get(k2, 0) or 0 for r in results)

    i_total   = _sum("total_links",   "internal_links")
    i_unique  = len({l["url"] for l in all_int_links})
    i_broken  = _sum("broken_count",  "internal_links")
    i_redir   = _sum("redirect_count","internal_links")
    i_df      = _sum("dofollow_count","internal_links")
    i_nf      = _sum("nofollow_count","internal_links")
    i_new_tab = _sum("new_tab_count", "internal_links")
    i_miss_no = _sum("missing_noopener_count","internal_links")
    i_weak    = _sum("weak_anchor_count","internal_links")

    e_total   = _sum("total_links",   "external_links")
    e_unique  = len({get_base_domain(l["url"]) for l in all_ext_links})
    e_broken  = _sum("broken_count",  "external_links")
    e_blocked = _sum("blocked_count", "external_links")
    e_redir   = _sum("redirect_count","external_links")
    e_df      = _sum("dofollow_count","external_links")
    e_nf      = _sum("nofollow_count","external_links")
    e_new_tab = _sum("new_tab_count", "external_links")
    e_miss_no = _sum("missing_noopener_count","external_links")
    e_no_sec  = _sum("no_security_count","external_links")
    e_weak    = _sum("weak_anchor_count","external_links")

    # ── 5-tab layout ──────────────────────────────────────────────────────
    tab_ov, tab_i, tab_e, tab_at, tab_op = st.tabs([
        "📊 Overview",
        "🔵 Internal Links",
        "🟣 External Links",
        "🔤 Anchor Text",
        "💡 Opportunities",
    ])

    # ════════════════════════ TAB 1: OVERVIEW ═══════════════════════════ #

    # Filter state for clickable KPI cards
    if "la_ov_filter" not in st.session_state:
        st.session_state["la_ov_filter"] = None   # (kind, filter_key)

    def _kpi_card_btn(col, label, val, clr, fkind, fkey):
        """Render a clickable KPI card. Sets session_state filter on click."""
        active = st.session_state.get("la_ov_filter") == (fkind, fkey)
        border = f"2px solid {clr}" if active else "1px solid var(--seo-border,rgba(148,163,184,.22))"
        shadow = f"0 0 0 2px {clr}44" if active else "none"
        with col:
            st.markdown(f"""
            <div style='background:var(--seo-card-bg,#fff);border:{border};box-shadow:{shadow};
                 border-radius:10px;padding:10px;text-align:center;cursor:pointer'>
                <div style='font-size:1.4rem;font-weight:800;color:{clr}'>{val}</div>
                <div style='font-size:.68rem;color:var(--seo-muted,#64748B);margin-top:2px'>{label}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"↓ {label}", key=f"la_btn_{fkind}_{fkey}", use_container_width=True,
                         help=f"Click to filter links by: {label}"):
                if st.session_state.get("la_ov_filter") == (fkind, fkey):
                    st.session_state["la_ov_filter"] = None   # toggle off
                else:
                    st.session_state["la_ov_filter"] = (fkind, fkey)
                st.rerun()

    with tab_ov:
        st.markdown('<div class="section-header">🔵 Internal Links Summary</div>', unsafe_allow_html=True)
        ic1 = st.columns(4)
        ic2 = st.columns(4)
        _kv = [
            ("Total",      i_total,   "#3B82F6", "int", "all"),
            ("Unique URLs",i_unique,  "#6366F1", "int", "unique"),
            ("Dofollow",   i_df,      "#10B981", "int", "dofollow"),
            ("Nofollow",   i_nf,      "#F59E0B", "int", "nofollow"),
            ("Broken",     i_broken,  "#EF4444", "int", "broken"),
            ("Redirecting",i_redir,   "#F97316", "int", "redirect"),
            ("New Tab",    i_new_tab, "#8B5CF6", "int", "new_tab"),
            ("Weak Anchor",i_weak,    "#F59E0B", "int", "weak"),
        ]
        for col, (label, val, clr, fkind, fkey) in zip(ic1 + ic2, _kv):
            _kpi_card_btn(col, label, val, clr, fkind, fkey)

        st.markdown('<div class="section-header" style="margin-top:20px">🟣 External Links Summary</div>',
                    unsafe_allow_html=True)
        ec1 = st.columns(4)
        ec2 = st.columns(4)
        _kv_e = [
            ("Total",      e_total,   "#7C3AED", "ext", "all"),
            ("Domains",    e_unique,  "#6366F1", "ext", "unique"),
            ("Dofollow",   e_df,      "#10B981", "ext", "dofollow"),
            ("Nofollow",   e_nf,      "#F59E0B", "ext", "nofollow"),
            ("Broken",     e_broken,  "#EF4444", "ext", "broken"),
            ("Blocked",    e_blocked, "#8B5CF6", "ext", "blocked"),
            ("No Security",e_no_sec,  "#F97316", "ext", "no_security"),
            ("Weak Anchor",e_weak,    "#F59E0B", "ext", "weak"),
        ]
        for col, (label, val, clr, fkind, fkey) in zip(ec1 + ec2, _kv_e):
            _kpi_card_btn(col, label, val, clr, fkind, fkey)

        # ── Filtered link table driven by card clicks ─────────────────────
        ov_filter = st.session_state.get("la_ov_filter")
        # Only react to overview-level filters (fkind "int"/"ext"); ignore tab-specific fkinds
        if ov_filter and ov_filter[0] in ("int", "ext"):
            fkind, fkey = ov_filter
            src_links = all_int_links if fkind == "int" else all_ext_links
            label_map = {
                "all":        ("All Links",             src_links),
                "unique":     ("Unique URLs",            list({l["url"]: l for l in src_links}.values())),
                "dofollow":   ("Dofollow Links",         [l for l in src_links if l.get("is_dofollow")]),
                "nofollow":   ("Nofollow Links",         [l for l in src_links if l.get("is_nofollow")]),
                "broken":     ("Broken Links",           [l for l in src_links if l.get("health") == "broken"]),
                "redirect":   ("Redirecting Links",      [l for l in src_links if l.get("health") == "redirect"]),
                "blocked":    ("Blocked Links",          [l for l in src_links if l.get("health") == "blocked"]),
                "new_tab":    ("New Tab Links",          [l for l in src_links if l.get("opens_new_tab")]),
                "no_security":("Missing Noopener Links", [l for l in src_links if l.get("opens_new_tab") and not l.get("has_noopener")]),
                "weak":       ("Weak Anchor Links",      [l for l in src_links if l.get("is_weak_anchor")]),
            }
            section_label, filtered_links = label_map.get(fkey, ("Links", src_links))
            kind_label = "Internal" if fkind == "int" else "External"
            kind_icon  = "🔵" if fkind == "int" else "🟣"
            st.markdown("---")
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:8px'>"
                f"<span style='font-size:1rem;font-weight:700;color:var(--seo-heading,#0F172A)'>"
                f"{kind_icon} {kind_label}: {section_label}</span>"
                f"<span style='background:var(--seo-card-bg-alt,#F1F5F9);color:var(--seo-muted,#475569);padding:2px 8px;border-radius:12px;"
                f"font-size:.75rem;font-weight:600'>{len(filtered_links)} links</span>"
                f"</div>",
                unsafe_allow_html=True
            )
            if filtered_links:
                render_link_table(filtered_links, show_source=True, source_label="Source Page",
                                  max_rows=300, key_prefix=f"la_ov_{fkind}_{fkey}")
            else:
                st.info(f"No {section_label.lower()} found.")

        st.markdown("<br>", unsafe_allow_html=True)

        # Link health donut charts side-by-side
        ov1, ov2, ov3 = st.columns(3)
        with ov1:
            i_ok      = sum(1 for l in all_int_links if l.get("health") == "ok")
            i_unknown = sum(1 for l in all_int_links if l.get("health") == "unknown")
            fig_i = go.Figure(go.Pie(
                labels=["OK", "Broken", "Redirecting", "Not Checked"],
                values=[i_ok, i_broken, i_redir, i_unknown],
                hole=0.55,
                marker_colors=["#10B981","#EF4444","#F59E0B","#94A3B8"],
            ))
            fig_i.update_traces(textinfo="value+percent", textfont_size=11)
            fig_i.update_layout(
                title="Internal Link Health",
                showlegend=True, height=300,
                margin=dict(t=40,b=5,l=5,r=5),
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_i, use_container_width=True)

        with ov2:
            fig_e = go.Figure(go.Pie(
                labels=["OK", "Broken", "Redirect", "Blocked"],
                values=[max(e_total - e_broken - e_redir - e_blocked, 0),
                        e_broken, e_redir, e_blocked],
                hole=0.55,
                marker_colors=["#10B981","#EF4444","#F59E0B","#8B5CF6"],
            ))
            fig_e.update_traces(textinfo="value+percent", textfont_size=11)
            fig_e.update_layout(
                title="External Link Health",
                showlegend=True, height=300,
                margin=dict(t=40,b=5,l=5,r=5),
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_e, use_container_width=True)

        with ov3:
            fig_rel = go.Figure(go.Pie(
                labels=["Dofollow", "Nofollow", "Sponsored", "UGC"],
                values=[
                    i_df + e_df,
                    i_nf + e_nf,
                    _sum("sponsored_count","external_links"),
                    _sum("ugc_count","external_links"),
                ],
                hole=0.55,
                marker_colors=["#3B82F6","#F97316","#8B5CF6","#06B6D4"],
            ))
            fig_rel.update_traces(textinfo="value+percent", textfont_size=11)
            fig_rel.update_layout(
                title="All Links by Rel Type",
                showlegend=True, height=300,
                margin=dict(t=40,b=5,l=5,r=5),
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_rel, use_container_width=True)

        # Consolidated issues
        all_link_issues = []
        for r in results:
            all_link_issues += r.get("internal_links",{}).get("issues",[])
            all_link_issues += r.get("external_links",{}).get("issues",[])
        if all_link_issues:
            st.markdown('<div class="section-header">⚠️ Link Issues Found</div>', unsafe_allow_html=True)
            for iss in sorted(all_link_issues, key=lambda x: x.get("impact_score",0), reverse=True)[:12]:
                _render_issue_card(iss)

    # ════════════════════════ TAB 2: INTERNAL LINKS ══════════════════════ #
    with tab_i:
        if i_broken:
            st.error(f"⚠️ {i_broken} broken internal link(s) detected — fix these immediately.")
        if i_redir:
            st.warning(f"↪️ {i_redir} internal link(s) redirect — update to final URLs.")
        if i_miss_no:
            st.warning(f"🔒 {i_miss_no} internal link(s) open in new tab without rel='noopener'.")

        # Tab behavior breakdown — clickable cards
        st.markdown('<div class="section-header">🖱️ Tab Behavior & Security</div>', unsafe_allow_html=True)
        sec_clr    = "#10B981" if i_miss_no == 0 else "#EF4444"
        i_same_tab = sum(1 for l in all_int_links if not l.get("opens_new_tab"))
        i_secure   = sum(1 for l in all_int_links if l.get("opens_new_tab") and l.get("has_noopener"))
        _int_tab_cards = [
            ("Same Tab",         i_same_tab, "#3B82F6", "int_tab", "same_tab",      [l for l in all_int_links if not l.get("opens_new_tab")]),
            ("New Tab",          i_new_tab,  "#8B5CF6", "int_tab", "new_tab",        [l for l in all_int_links if l.get("opens_new_tab")]),
            ("Missing noopener", i_miss_no,  sec_clr,   "int_tab", "miss_noopener",  [l for l in all_int_links if l.get("opens_new_tab") and not l.get("has_noopener")]),
            ("Secure New Tab",   i_secure,   "#10B981", "int_tab", "secure_tab",     [l for l in all_int_links if l.get("opens_new_tab") and l.get("has_noopener")]),
        ]
        tb1, tb2, tb3, tb4 = st.columns(4)
        for col, (label, val, clr, fkind, fkey, _) in zip([tb1,tb2,tb3,tb4], _int_tab_cards):
            _kpi_card_btn(col, label, val, clr, fkind, fkey)

        # Show filtered table if a card was clicked
        ov_f = st.session_state.get("la_ov_filter")
        if ov_f and ov_f[0] == "int_tab":
            _, fkey = ov_f
            matched = next((links for lbl, val, clr, fk0, fk1, links in _int_tab_cards if fk1 == fkey), [])
            lbl_name = next((lbl for lbl, val, clr, fk0, fk1, links in _int_tab_cards if fk1 == fkey), fkey)
            st.markdown("---")
            st.markdown(f"**🔵 Internal — {lbl_name}** &nbsp; <span style='background:var(--seo-card-bg-alt,#F1F5F9);color:var(--seo-muted,#475569);padding:2px 8px;border-radius:12px;font-size:.75rem;font-weight:600'>{len(matched)} links</span>", unsafe_allow_html=True)
            if matched:
                render_link_table(matched, show_source=True, source_label="Source Page", max_rows=300, key_prefix=f"la_{fkey}")
            else:
                st.info("No links match this filter.")
        st.markdown("<br>", unsafe_allow_html=True)

        # Per-page internal link summary
        if len(results) > 1:
            with st.expander("📄 Per-Page Internal Link Breakdown", expanded=False):
                page_rows = []
                for r in results:
                    il = r.get("internal_links", {})
                    page_rows.append({
                        "Page URL": r.get("url","")[-65:],
                        "Total": il.get("total_links",0),
                        "Unique": il.get("unique_links",0),
                        "Dofollow": il.get("dofollow_count",0),
                        "Nofollow": il.get("nofollow_count",0),
                        "Broken": il.get("broken_count",0),
                        "Redirecting": il.get("redirect_count",0),
                        "New Tab": il.get("new_tab_count",0),
                        "Weak Anchor": il.get("weak_anchor_count",0),
                    })
                st.dataframe(pd.DataFrame(page_rows), use_container_width=True, hide_index=True)

        st.markdown('<div class="section-header">📋 All Internal Links</div>', unsafe_allow_html=True)
        if all_int_links:
            render_link_table(all_int_links, show_source=True, source_label="Source Page", max_rows=300, key_prefix="la_il")
        else:
            st.info("No internal link data. Enable 'Audit Links' and re-run the audit.")

    # ════════════════════════ TAB 3: EXTERNAL LINKS ══════════════════════ #
    with tab_e:
        if e_broken:
            st.error(f"⚠️ {e_broken} broken external link(s) (4xx/5xx) — update or remove these.")
        if e_blocked:
            st.warning(f"🚫 {e_blocked} link(s) blocked by site (LinkedIn, Twitter etc.) — not broken, just bot-restricted.")
        if e_no_sec:
            st.warning(f"🔒 {e_no_sec} external new-tab link(s) missing rel='noopener noreferrer' — security risk.")

        # Security attributes breakdown — clickable cards
        st.markdown('<div class="section-header">🔒 Security Attributes Analysis</div>', unsafe_allow_html=True)
        e_same_tab  = e_total - e_new_tab
        # Fully secure = opens_new_tab AND has both noopener + noreferrer
        e_full_sec  = sum(1 for l in all_ext_links if l.get("opens_new_tab") and l.get("has_noopener") and l.get("has_noreferrer"))
        _ext_sec_cards = [
            ("Same Tab",           e_same_tab, "#3B82F6", "ext_tab", "e_same_tab",      [l for l in all_ext_links if not l.get("opens_new_tab")]),
            ("New Tab",            e_new_tab,  "#8B5CF6", "ext_tab", "e_new_tab",        [l for l in all_ext_links if l.get("opens_new_tab")]),
            ("Fully Secure",       e_full_sec, "#10B981", "ext_tab", "e_has_noopener",   [l for l in all_ext_links if l.get("opens_new_tab") and l.get("has_noopener") and l.get("has_noreferrer")]),
            ("Missing noopener",   e_miss_no,  "#F97316", "ext_tab", "e_miss_no",        [l for l in all_ext_links if l.get("opens_new_tab") and not l.get("has_noopener")]),
            ("Missing both",       e_no_sec,   "#EF4444", "ext_tab", "e_no_sec",         [l for l in all_ext_links if l.get("opens_new_tab") and not l.get("has_noopener") and not l.get("has_noreferrer")]),
        ]
        sa1, sa2, sa3, sa4, sa5 = st.columns(5)
        for col, (label, val, clr, fkind, fkey, _) in zip([sa1,sa2,sa3,sa4,sa5], _ext_sec_cards):
            _kpi_card_btn(col, label, val, clr, fkind, fkey)

        # Show filtered table when a card is clicked
        ov_f = st.session_state.get("la_ov_filter")
        if ov_f and ov_f[0] == "ext_tab":
            _, fkey = ov_f
            matched = next((links for lbl, val, clr, fk0, fk1, links in _ext_sec_cards if fk1 == fkey), [])
            lbl_name = next((lbl for lbl, val, clr, fk0, fk1, links in _ext_sec_cards if fk1 == fkey), fkey)
            st.markdown("---")
            st.markdown(f"**🟣 External — {lbl_name}** &nbsp; <span style='background:var(--seo-card-bg-alt,#F1F5F9);color:var(--seo-muted,#475569);padding:2px 8px;border-radius:12px;font-size:.75rem;font-weight:600'>{len(matched)} links</span>", unsafe_allow_html=True)
            if matched:
                render_link_table(matched, show_source=True, source_label="Source Page", max_rows=300, key_prefix=f"la_e_{fkey}")
            else:
                st.info("No links match this filter.")

        st.markdown("<br>", unsafe_allow_html=True)

        # Domain category breakdown + top domains chart
        ec1, ec2 = st.columns([1, 1])
        with ec1:
            st.markdown('<div class="section-header">🌐 External Domain Categories</div>',
                        unsafe_allow_html=True)
            domain_cats = {}
            domain_counts = {}
            for lk in all_ext_links:
                d = get_base_domain(lk.get("url",""))
                cat = categorize_domain(d)
                domain_cats[cat] = domain_cats.get(cat, 0) + 1
                domain_counts[d]  = domain_counts.get(d, 0) + 1
            if domain_cats:
                cat_colors = {
                    "Social":"#3B82F6","News":"#10B981","Academic":"#8B5CF6",
                    "Government":"#F59E0B","Reference":"#06B6D4","Tech":"#6366F1","Other":"#94A3B8",
                }
                fig_cat = go.Figure(go.Pie(
                    labels=list(domain_cats.keys()),
                    values=list(domain_cats.values()),
                    hole=0.5,
                    marker_colors=[cat_colors.get(k,"#94A3B8") for k in domain_cats],
                ))
                fig_cat.update_traces(textinfo="label+percent", textfont_size=11)
                fig_cat.update_layout(showlegend=False, height=280,
                                      margin=dict(t=10,b=5,l=5,r=5),
                                      paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_cat, use_container_width=True)

        with ec2:
            st.markdown('<div class="section-header">🏆 Top External Domains</div>',
                        unsafe_allow_html=True)
            if domain_counts:
                top_d = dict(sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:12])
                fig_d = px.bar(
                    x=list(top_d.values()), y=list(top_d.keys()), orientation="h",
                    labels={"x": "Links", "y": "Domain"},
                    color=list(top_d.values()), color_continuous_scale="Blues",
                )
                fig_d.update_layout(showlegend=False, height=300,
                                    coloraxis_showscale=False,
                                    margin=dict(t=10,b=10,l=10,r=10),
                                    paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_d, use_container_width=True)

        # Dofollow vs nofollow per domain (top 10)
        st.markdown('<div class="section-header">📊 Link Equity — Dofollow vs Nofollow by Domain</div>',
                    unsafe_allow_html=True)
        dom_df_nf = {}
        for lk in all_ext_links:
            d = get_base_domain(lk.get("url",""))
            if d not in dom_df_nf:
                dom_df_nf[d] = {"dofollow": 0, "nofollow": 0}
            if lk.get("is_dofollow"):
                dom_df_nf[d]["dofollow"] += 1
            else:
                dom_df_nf[d]["nofollow"] += 1
        top_doms = sorted(dom_df_nf.items(), key=lambda x: x[1]["dofollow"]+x[1]["nofollow"], reverse=True)[:10]
        if top_doms:
            df_eq = pd.DataFrame([
                {"Domain": d, "Dofollow": v["dofollow"], "Nofollow": v["nofollow"]}
                for d, v in top_doms
            ])
            fig_eq = go.Figure()
            fig_eq.add_trace(go.Bar(name="Dofollow", y=df_eq["Domain"], x=df_eq["Dofollow"],
                                    orientation="h", marker_color="#3B82F6"))
            fig_eq.add_trace(go.Bar(name="Nofollow", y=df_eq["Domain"], x=df_eq["Nofollow"],
                                    orientation="h", marker_color="#F97316"))
            fig_eq.update_layout(barmode="stack", height=320, showlegend=True,
                                  margin=dict(t=10,b=10,l=10,r=10),
                                  paper_bgcolor="rgba(0,0,0,0)",
                                  legend=dict(orientation="h", y=1.1))
            st.plotly_chart(fig_eq, use_container_width=True)

        st.markdown('<div class="section-header">📋 All External Links</div>', unsafe_allow_html=True)
        if all_ext_links:
            render_link_table(all_ext_links, show_source=True, source_label="Source Page", max_rows=300, key_prefix="la_el")
        else:
            st.info("No external link data. Enable 'Audit Links' and re-run the audit.")

    # ════════════════════════ TAB 4: ANCHOR TEXT ═════════════════════════ #
    with tab_at:
        st.markdown('<div class="section-header">🔤 Anchor Text Analysis</div>', unsafe_allow_html=True)
        at1, at2 = st.tabs(["🔵 Internal", "🟣 External"])

        def _render_anchor_analysis(links, link_type_label):
            if not links:
                st.info(f"No {link_type_label} link data available.")
                return
            report = analyze_anchor_text(links)

            # KPI row
            k1, k2, k3, k4, k5 = st.columns(5)
            _at_kpis = [
                (k1, "Total Links",   report["total"],       "#3B82F6"),
                (k2, "Unique Anchors",report["unique"],      "#6366F1"),
                (k3, "Weak Anchors",  report["weak_count"],  "#F97316"),
                (k4, "Image No-Alt",  report["image_no_alt"],"#EF4444"),
                (k5, "Empty Anchor",  report["empty_count"], "#EF4444"),
            ]
            for col, lbl, val, clr in _at_kpis:
                with col:
                    st.markdown(f"""
                    <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                         border-radius:10px;padding:12px;text-align:center'>
                        <div style='font-size:1.4rem;font-weight:800;color:{clr}'>{val}</div>
                        <div style='font-size:.72rem;color:var(--seo-muted,#64748B);margin-top:2px'>{lbl}</div>
                    </div>""", unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # Issues & opportunities
            if report["issues"] or report["opportunities"]:
                oi1, oi2 = st.columns(2)
                with oi1:
                    if report["issues"]:
                        st.markdown('<div class="section-header">🚨 Issues Detected</div>', unsafe_allow_html=True)
                        for iss in report["issues"]:
                            st.markdown(f"""
                            <div style='background:var(--sev-high-bg,rgba(249,115,22,.10));border-left:4px solid #F97316;
                                 border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:6px'>
                                <div style='font-weight:700;font-size:.84rem;color:var(--seo-heading,#0F172A)'>
                                    {iss["message"]}</div>
                                <div style='font-size:.75rem;color:var(--seo-info-text,#1D4ED8);margin-top:4px'>
                                    ✅ {iss["recommendation"]}</div>
                            </div>""", unsafe_allow_html=True)
                with oi2:
                    if report["opportunities"]:
                        st.markdown('<div class="section-header">💡 Optimisation Opportunities</div>',
                                    unsafe_allow_html=True)
                        for op in report["opportunities"]:
                            clr = "#EF4444" if op["type"] in ("weak_anchor","image_no_alt","empty_anchor") else "#3B82F6"
                            st.markdown(f"""
                            <div style='background:var(--seo-card-bg,#fff);border-left:4px solid {clr};
                                 border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:6px;
                                 border:1px solid var(--seo-border,rgba(148,163,184,.22))'>
                                <div style='font-weight:700;font-size:.84rem;color:var(--seo-heading,#0F172A)'>
                                    {op["message"]}</div>
                                <div style='font-size:.75rem;color:var(--seo-info-text,#1D4ED8);margin-top:4px'>
                                    ✅ {op["recommendation"]}</div>
                            </div>""", unsafe_allow_html=True)

            # Anchor text distribution table
            st.markdown('<div class="section-header">📊 Anchor Text Distribution (Top 50)</div>',
                        unsafe_allow_html=True)
            if report["distribution"]:
                dist_df = pd.DataFrame(report["distribution"])
                dist_df.columns = ["Anchor Text", "Count", "% of Links", "Is Weak"]
                dist_df["Flag"] = dist_df["Is Weak"].map(lambda x: "⚠️ Weak" if x else "✅ OK")
                dist_df = dist_df.drop(columns=["Is Weak"])

                # Bar chart of top 20
                top20 = report["distribution"][:20]
                bar_colors = ["#EF4444" if d["is_weak"] else "#3B82F6" for d in top20]
                fig_at = go.Figure(go.Bar(
                    x=[d["anchor"][:40] for d in top20],
                    y=[d["count"] for d in top20],
                    marker_color=bar_colors,
                    text=[f"{d['pct']}%" for d in top20],
                    textposition="outside",
                ))
                fig_at.update_layout(
                    title="Top 20 Anchor Texts (red = weak/generic)",
                    height=320, margin=dict(t=40,b=80,l=10,r=10),
                    xaxis_tickangle=-35,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_at, use_container_width=True)

                # Full table
                with st.expander("View Full Anchor Text Table"):
                    st.dataframe(dist_df, use_container_width=True, hide_index=True)

            # Anchor type breakdown
            anchor_types = {}
            for lk in links:
                at = lk.get("anchor_type", "text")
                anchor_types[at] = anchor_types.get(at, 0) + 1
            if anchor_types:
                st.markdown('<div class="section-header">🏷️ Anchor Type Breakdown</div>',
                            unsafe_allow_html=True)
                atype_cols = st.columns(len(anchor_types))
                _at_labels = {"text":"Text Anchors","image":"Image w/ Alt",
                              "image-no-alt":"Image No Alt","empty":"Empty"}
                _at_colors = {"text":"#3B82F6","image":"#10B981",
                              "image-no-alt":"#EF4444","empty":"#F97316"}
                for col, (atype, cnt) in zip(atype_cols, sorted(anchor_types.items(), key=lambda x: -x[1])):
                    with col:
                        clr = _at_colors.get(atype, "#94A3B8")
                        lbl = _at_labels.get(atype, atype)
                        st.markdown(f"""
                        <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                             border-radius:10px;padding:12px;text-align:center'>
                            <div style='font-size:1.4rem;font-weight:800;color:{clr}'>{cnt}</div>
                            <div style='font-size:.72rem;color:var(--seo-muted,#64748B);margin-top:2px'>{lbl}</div>
                        </div>""", unsafe_allow_html=True)

        with at1:
            _render_anchor_analysis(all_int_links, "internal")
        with at2:
            _render_anchor_analysis(all_ext_links, "external")

    # ════════════════════════ TAB 5: OPPORTUNITIES ═══════════════════════ #
    with tab_op:
        st.markdown('<div class="section-header">💡 Internal Linking Opportunities</div>',
                    unsafe_allow_html=True)
        st.caption("Detected gaps and improvement opportunities across all audited pages.")

        opps = get_internal_link_opportunities(results)
        if not opps:
            st.success("✅ No major internal linking gaps detected across your audited pages.")
        else:
            sev_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
            opps_sorted = sorted(opps, key=lambda x: sev_order.get(x.get("severity","Low"), 4))
            for opp in opps_sorted:
                sev   = opp.get("severity","Low")
                sev_c = _SEV_COLORS.get(sev,"#6B7280")
                pages = opp.get("pages",[])
                pages_html = "".join(
                    f"<div style='font-size:.72rem;color:var(--seo-info-text,#1D4ED8);margin-top:2px'>→ {p[:90]}</div>"
                    for p in pages[:5]
                )
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#fff);border-left:5px solid {sev_c};
                     border-radius:0 10px 10px 0;padding:14px 18px;margin-bottom:10px;
                     border:1px solid var(--seo-border,rgba(148,163,184,.22))'>
                    <div style='display:flex;align-items:center;gap:10px;margin-bottom:6px'>
                        <span style='background:{sev_c};color:white;padding:2px 10px;border-radius:999px;
                              font-size:.72rem;font-weight:700'>{sev}</span>
                        <span style='font-weight:700;font-size:.88rem;color:var(--seo-heading,#0F172A)'>
                            {opp.get("title","")}</span>
                        <span style='margin-left:auto;font-size:.78rem;font-weight:700;color:{sev_c}'>
                            {opp.get("count",0)} affected</span>
                    </div>
                    <div style='font-size:.82rem;color:var(--seo-text,#374151)'>{opp.get("message","")}</div>
                    <div style='font-size:.78rem;color:var(--seo-info-text,#1D4ED8);margin-top:6px'>
                        ✅ {opp.get("recommendation","")}</div>
                    {pages_html}
                </div>""", unsafe_allow_html=True)

        # Pages that have the most inbound internal links (strong hubs)
        st.markdown('<div class="section-header">🌟 Internal Link Hubs (Most Inbound Links)</div>',
                    unsafe_allow_html=True)
        inbound_map = {}
        for r_item in results:
            for lk in r_item.get("internal_links", {}).get("links", []):
                t = lk.get("url","")
                inbound_map[t] = inbound_map.get(t, 0) + 1
        if inbound_map:
            top_hubs = sorted(inbound_map.items(), key=lambda x: x[1], reverse=True)[:10]
            hub_df = pd.DataFrame([{"Target URL": u[-70:], "Inbound Internal Links": cnt}
                                    for u, cnt in top_hubs])
            fig_hub = px.bar(hub_df, x="Inbound Internal Links", y="Target URL",
                             orientation="h", color="Inbound Internal Links",
                             color_continuous_scale="Blues",
                             title="Pages Receiving the Most Internal Links")
            fig_hub.update_layout(showlegend=False, height=350, coloraxis_showscale=False,
                                  margin=dict(t=40,b=10,l=10,r=10),
                                  paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_hub, use_container_width=True)
        else:
            st.info("Run the audit with 'Audit Links' enabled to see inbound link data.")


# ════════════════════════════════════════════════════════════════════════════
# Helpers shared across new audit pages
# ════════════════════════════════════════════════════════════════════════════

def _no_data_info():
    st.info("No audit data yet. Go to **New Audit** to get started.")

def _pick_url(results):
    """Sidebar-style URL selector returning (index, result_dict)."""
    if not results:
        return None, None
    urls = [r.get("url","") for r in results]
    idx  = st.selectbox("Select URL to inspect", range(len(urls)),
                        format_func=lambda i: urls[i][-80:], key="sel_url_detail_shared")
    return idx, results[idx]


# ════════════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════════════
# Performance Audit  (Mobile · Image SEO · Core Web Vitals — unified)
# ════════════════════════════════════════════════════════════════════════════

def page_performance():
    st.html("<div class='page-header'><h2>Performance</h2><p>Core Web Vitals · PageSpeed · mobile · page size · security headers</p></div>")
    st.markdown(  # keep original blank line for indentation integrity
        "",
        unsafe_allow_html=True,
    )
    tab_mobile, tab_image = st.tabs([
        "📱 Mobile Audit",
        "🖼️ Image SEO",
    ])
    with tab_mobile:
        _page_mobile_audit_body()
    with tab_image:
        _page_image_seo_body()


# ════════════════════════════════════════════════════════════════════════════
# Mobile Audit Page
# ════════════════════════════════════════════════════════════════════════════

def _page_mobile_audit_body():
    results = st.session_state.audit_results
    if not results:
        _no_data_info(); return

    # ── Overview table across all URLs ───────────────────────────────────
    st.markdown('<div class="section-header">📊 Mobile Audit Overview — All URLs</div>',
                unsafe_allow_html=True)
    rows = []
    for r in results:
        ma  = r.get("mobile_audit", {})
        cwv = ma.get("cwv", {})
        ps  = cwv.get("perf_score", 0) or 0
        psi_available = "PageSpeed" in cwv.get("source", "")
        rows.append({
            "URL":                r.get("url","")[-70:],
            "Mobile Friendly":    "✅ Yes" if ma.get("is_mobile_friendly") else "❌ No",
            "Viewport":           "✅" if ma.get("summary",{}).get("viewport_ok") else "❌",
            "Lighthouse Score":   f"{ps}%" if psi_available else "—",
            "UX Check Score":     f"{ma.get('mobile_score',0)}% ({ma.get('passed_checks',0)}/{ma.get('total_checks',0)} checks)",
            "UX Issues":          len(ma.get("issues",[])),
            "Source":             "PSI" if psi_available else "Heuristic",
        })
    mob_df = pd.DataFrame(rows)
    st.dataframe(mob_df, use_container_width=True, hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Per-URL deep dive ─────────────────────────────────────────────────
    st.markdown('<div class="section-header">🔍 URL Deep Dive</div>', unsafe_allow_html=True)
    urls = [r.get("url","") for r in results]
    sel  = st.selectbox("Select URL", range(len(urls)), format_func=lambda i: urls[i][-90:],
                        key="mob_url_sel")
    r    = results[sel]
    ma   = r.get("mobile_audit", {})

    if not ma:
        st.warning("Mobile audit data not available for this URL. Please re-run the audit.")
        return

    # KPI strip — reads cwv after potential live PSI patch
    _psi_cache_key_kpi = f"psi_live_{r.get('url','')}"
    _live_psi_kpi = st.session_state.get(_psi_cache_key_kpi)
    if _live_psi_kpi and _live_psi_kpi.get("success"):
        from modules.mobile_auditor import _parse_cwv as _pcwv_kpi
        ma["cwv"] = _pcwv_kpi(r.get("technical_seo", {}), pagespeed=_live_psi_kpi)
    cwv_now      = ma.get("cwv", {})
    ps_now       = cwv_now.get("perf_score", 0) or 0
    psi_now      = "PageSpeed" in cwv_now.get("source", "")
    ux_score     = ma.get("mobile_score", 0)
    score_lbl    = "Lighthouse Score" if psi_now else "UX Check Score"
    score_val    = f"{ps_now}%" if psi_now else f"{ux_score}%"
    score_sub    = "(PageSpeed Insights)" if psi_now else f"({ma.get('passed_checks',0)}/{ma.get('total_checks',0)} checks passed)"
    score_clr    = "#10B981" if ps_now >= 90 else "#F59E0B" if ps_now >= 50 else "#EF4444"

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(f"""
        <div style='background:var(--seo-card-bg,#fff);border:1px solid {"#10B981" if psi_now else "var(--seo-border,rgba(148,163,184,.22))"};
             border-radius:10px;padding:14px;text-align:center'>
            <div style='font-size:1.6rem;font-weight:800;color:{score_clr}'>{score_val}</div>
            <div style='font-size:.75rem;font-weight:700;color:var(--seo-heading,#0F172A);margin-top:3px'>{score_lbl}</div>
            <div style='font-size:.65rem;color:var(--seo-muted,#64748B);margin-top:2px'>{score_sub}</div>
        </div>""", unsafe_allow_html=True)

    _mob_kpis_rest = [
        (k2, "Checks Passed",   f"{ma.get('passed_checks',0)}/{ma.get('total_checks',0)}", "#3B82F6"),
        (k3, "Issues Found",    len(ma.get("issues",[])),   "#F97316"),
        (k4, "UX Check Score",  f"{ux_score}%",             "#8B5CF6" if psi_now else "#6366F1"),
        (k5, "Mobile Friendly", "✅ Yes" if ma.get("is_mobile_friendly") else "❌ No",
             "#10B981" if ma.get("is_mobile_friendly") else "#EF4444"),
    ]
    for col, lbl, val, clr in _mob_kpis_rest:
        with col:
            st.markdown(f"""
            <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                 border-radius:10px;padding:14px;text-align:center'>
                <div style='font-size:1.5rem;font-weight:800;color:{clr}'>{val}</div>
                <div style='font-size:.72rem;color:var(--seo-muted,#64748B);margin-top:3px'>{lbl}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    tab_checks, tab_cwv, tab_issues = st.tabs(["✅ Checks", "⚡ Core Web Vitals", "⚠️ Issues"])

    # ── Tab: Checks ───────────────────────────────────────────────────────
    with tab_checks:
        st.markdown('<div class="section-header">📋 Mobile Checks Detail</div>', unsafe_allow_html=True)
        checks = ma.get("checks", [])
        if not checks:
            st.info("No check data available.")
        else:
            status_color = {"pass":"#10B981","fail":"#EF4444","warning":"#F59E0B","info":"#3B82F6"}
            status_icon  = {"pass":"✅","fail":"❌","warning":"⚠️","info":"ℹ️"}
            for chk in checks:
                s    = chk.get("status","info")
                clr  = status_color.get(s,"#94A3B8")
                icon = status_icon.get(s,"ℹ️")
                cat  = chk.get("category","")
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                     border-left:5px solid {clr};border-radius:0 10px 10px 0;
                     padding:10px 16px;margin-bottom:6px;display:flex;align-items:flex-start;gap:12px'>
                    <div style='font-size:1.1rem;flex-shrink:0;margin-top:2px'>{icon}</div>
                    <div style='flex:1'>
                        <div style='font-weight:700;font-size:.85rem;color:var(--seo-heading,#0F172A)'>
                            {chk.get("name","")}</div>
                        <div style='font-size:.78rem;color:var(--seo-muted,#64748B);margin-top:2px'>
                            <b>Value:</b> {chk.get("value","—")} &nbsp;·&nbsp; <b>Category:</b> {cat}</div>
                        <div style='font-size:.78rem;color:var(--seo-text,#374151);margin-top:3px'>
                            {chk.get("detail","")}</div>
                    </div>
                    <div style='font-size:.72rem;font-weight:700;color:{clr};text-transform:uppercase;
                         flex-shrink:0'>{s.upper()}</div>
                </div>""", unsafe_allow_html=True)

    # ── Tab: Core Web Vitals ──────────────────────────────────────────────
    with tab_cwv:
        st.markdown('<div class="section-header">⚡ Core Web Vitals</div>', unsafe_allow_html=True)

        # Live PSI fetch — allows getting real scores without re-running the full audit
        current_url = r.get("url", "")
        psi_cache_key = f"psi_live_{current_url}"

        # If we already have real PSI data from the audit, use it
        _stored_psi = r.get("pagespeed", {})
        if _stored_psi and _stored_psi.get("success"):
            if psi_cache_key not in st.session_state:
                st.session_state[psi_cache_key] = _stored_psi

        _live_psi = st.session_state.get(psi_cache_key)
        _has_real = bool(_live_psi and _live_psi.get("success"))

        if not _has_real:
            st.markdown("""
            <div style='background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.4);
                 border-radius:8px;padding:10px 16px;margin-bottom:12px'>
                <span style='font-size:.85rem;color:#F59E0B;font-weight:600'>⚠️ Showing heuristic estimates</span>
                <span style='font-size:.78rem;color:var(--seo-muted,#94A3B8);margin-left:8px'>
                — values are approximations based on server response time, not real Lighthouse measurements.</span>
            </div>""", unsafe_allow_html=True)
            # Persist the API key in session_state so button click doesn't clear it
            _psi_key_ss = "psi_api_key_global"
            _saved_key  = st.session_state.get(_psi_key_ss, "")
            psi_key_col, psi_btn_col = st.columns([3, 1])
            with psi_key_col:
                if _saved_key:
                    _masked = _saved_key[:6] + "•" * max(0, len(_saved_key) - 10) + _saved_key[-4:]
                    st.markdown(f"""
                    <div style='background:rgba(16,185,129,.10);border:1px solid rgba(16,185,129,.3);
                         border-radius:8px;padding:8px 14px;font-size:.8rem;color:#10B981'>
                        ✅ API key from Settings: <span style='font-family:monospace'>{_masked}</span>
                        &nbsp;·&nbsp;
                        <a href='#' style='color:#10B981' onclick=''>change in ⚙️ Settings</a>
                    </div>""", unsafe_allow_html=True)
                else:
                    _typed_key = st.text_input(
                        "Google API Key",
                        value="",
                        type="password",
                        placeholder="Paste API key here — or save it once in ⚙️ Settings",
                        key="psi_key_input_field",
                    )
                    if _typed_key:
                        st.session_state[_psi_key_ss] = _typed_key.strip()
            with psi_btn_col:
                st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
                _do_fetch = st.button("🚀 Fetch Real Scores", key=f"psi_btn_{current_url}",
                                      type="primary", use_container_width=True)

            _final_key = st.session_state.get(_psi_key_ss, "").strip() or None
            if not _final_key:
                st.caption("⚠️ No API key — go to ⚙️ Settings to save your key permanently.")

            if _do_fetch:
                if not _final_key:
                    st.error("Paste your Google API key before fetching. Anonymous requests are blocked on Streamlit Cloud.")
                else:
                    with st.spinner("Calling PageSpeed Insights API — Google renders the full page remotely, takes 30–90s …"):
                        from modules.pagespeed import fetch_pagespeed as _fetch_psi_live
                        _result = _fetch_psi_live(current_url, strategy="mobile", api_key=_final_key)
                    if _result.get("success"):
                        st.session_state[psi_cache_key] = _result
                        from modules.mobile_auditor import _parse_cwv as _pcwv
                        r["mobile_audit"]["cwv"] = _pcwv(r.get("technical_seo", {}), pagespeed=_result)
                        st.success("✅ Real Lighthouse data loaded!")
                        st.rerun()
                    elif _result.get("error_code") == 429:
                        st.markdown("""
                        <div style='background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.4);
                             border-radius:8px;padding:14px 18px;margin-top:8px'>
                            <div style='font-weight:700;color:#EF4444;font-size:.88rem;margin-bottom:8px'>
                                🚫 Still rate-limited — key may not be active yet</div>
                            <div style='font-size:.82rem;color:var(--seo-text,#CBD5E1);line-height:1.8'>
                                • Newly created API keys take <b>1–5 minutes</b> to activate — wait and try again<br>
                                • Make sure <b>PageSpeed Insights API</b> is enabled in your Google Cloud project<br>
                                • Verify the key has no IP/referrer restrictions that block Streamlit Cloud<br>
                                • Your key should start with <b>AIza</b>
                            </div>
                        </div>""", unsafe_allow_html=True)
                    else:
                        st.error(f"PSI error: {_result.get('error','Unknown error')}")
        else:
            _ref_col, _btn_col = st.columns([4, 2])
            with _ref_col:
                st.markdown("""
                <div style='background:rgba(16,185,129,.10);border:1px solid rgba(16,185,129,.35);
                     border-radius:8px;padding:8px 16px;display:inline-block'>
                    <span style='font-size:.82rem;color:#10B981;font-weight:600'>
                        ✅ Real Lighthouse data — PageSpeed Insights API</span>
                </div>""", unsafe_allow_html=True)
            with _btn_col:
                if st.button("🔄 Re-fetch", key=f"psi_refetch_{current_url}", use_container_width=True):
                    if psi_cache_key in st.session_state:
                        del st.session_state[psi_cache_key]
                    st.rerun()

            # 4 PSI category score tiles
            _ps4 = [
                ("⚡ Performance",    _live_psi.get("performance_score")),
                ("♿ Accessibility",  _live_psi.get("accessibility_score")),
                ("🔍 SEO",            _live_psi.get("seo_score")),
                ("✅ Best Practices", _live_psi.get("best_practices_score")),
            ]
            st.markdown("<br>", unsafe_allow_html=True)
            _s4cols = st.columns(4)
            for _sc4, (_lbl4, _sv4) in zip(_s4cols, _ps4):
                _clr4 = "#10B981" if (_sv4 or 0) >= 90 else "#F59E0B" if (_sv4 or 0) >= 50 else "#EF4444"
                _rat4 = "Good" if (_sv4 or 0) >= 90 else "Needs Improvement" if (_sv4 or 0) >= 50 else "Poor"
                with _sc4:
                    st.markdown(f"""
                    <div style='background:var(--seo-card-bg,#fff);
                         border:1px solid var(--seo-border,rgba(148,163,184,.22));
                         border-top:4px solid {_clr4};border-radius:10px;
                         padding:14px;text-align:center;margin-bottom:12px'>
                        <div style='font-size:2rem;font-weight:900;color:{_clr4}'>{_sv4 if _sv4 is not None else "—"}</div>
                        <div style='font-size:.75rem;font-weight:700;
                             color:var(--seo-heading,#0F172A);margin-top:4px'>{_lbl4}</div>
                        <div style='font-size:.68rem;color:{_clr4};margin-top:3px;font-weight:600'>{_rat4}</div>
                    </div>""", unsafe_allow_html=True)
            st.markdown("---")

        # Use live PSI data if available, otherwise keep heuristic cwv
        if _has_real:
            from modules.mobile_auditor import _parse_cwv as _pcwv_live
            cwv = _pcwv_live(r.get("technical_seo", {}), pagespeed=_live_psi)
            # Patch into ma so the KPI strip and gauge show correct numbers
            ma["cwv"] = cwv
        else:
            cwv = ma.get("cwv", {})
        # cwv values are nested dicts: {"value": "Good (<200ms)", "status": "pass"}
        _cwv_status_color = {"pass":"#10B981","warning":"#F59E0B","fail":"#EF4444","info":"#94A3B8"}
        _cwv_status_label = {"pass":"Good","warning":"Needs Improvement","fail":"Poor","info":"—"}
        cwv_metrics = [
            ("TTFB", "Time to First Byte",
             cwv.get("ttfb", {}).get("value", "—"),
             cwv.get("ttfb", {}).get("status", "info"),
             "< 200ms Good · 200–500ms Needs Improvement · > 500ms Poor"),
            ("FCP", "First Contentful Paint",
             cwv.get("fcp", {}).get("value", "—"),
             cwv.get("fcp", {}).get("status", "info"),
             "< 1.8s Good · 1.8–3s Needs Improvement · > 3s Poor"),
            ("LCP", "Largest Contentful Paint",
             cwv.get("lcp", {}).get("value", "—"),
             cwv.get("lcp", {}).get("status", "info"),
             "< 2.5s Good · 2.5–4s Needs Improvement · > 4s Poor"),
            ("CLS", "Cumulative Layout Shift",
             cwv.get("cls", {}).get("value", "—"),
             cwv.get("cls", {}).get("status", "info"),
             "Low risk Good · Medium risk Warning · High risk Poor"),
            ("INP", "Interaction to Next Paint",
             cwv.get("inp", {}).get("value", "Requires Browser Measurement"),
             "info",
             "Cannot be measured from static HTML — use Chrome UX Report or PageSpeed Insights"),
        ]
        cw1, cw2, cw3, cw4, cw5 = st.columns(5)
        for col, (metric, full_name, val, status, desc) in zip([cw1,cw2,cw3,cw4,cw5], cwv_metrics):
            clr = _cwv_status_color.get(status, "#94A3B8")
            rating_label = _cwv_status_label.get(status, status.title())
            with col:
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                     border-radius:10px;padding:14px;text-align:center'>
                    <div style='font-size:.7rem;font-weight:700;color:var(--seo-muted,#64748B);
                         text-transform:uppercase;letter-spacing:.06em'>{metric}</div>
                    <div style='font-size:1.1rem;font-weight:800;color:{clr};margin:6px 0'>{val}</div>
                    <div style='font-size:.68rem;font-weight:700;color:{clr}'>{rating_label}</div>
                    <div style='font-size:.65rem;color:var(--seo-muted,#64748B);margin-top:4px'>{full_name}</div>
                </div>""", unsafe_allow_html=True)
                st.caption(desc)

        # Source badge
        cwv_source = cwv.get("source", "Heuristic Estimate")
        is_real = "PageSpeed" in cwv_source
        src_clr = "#10B981" if is_real else "#F59E0B"
        src_icon = "✅" if is_real else "⚠️"
        st.markdown(f"""
        <div style='background:var(--seo-card-bg,#fff);border:1px solid {src_clr};
             border-radius:8px;padding:8px 14px;margin:12px 0;display:inline-flex;
             align-items:center;gap:8px'>
            <span style='font-size:.85rem'>{src_icon}</span>
            <span style='font-size:.78rem;font-weight:600;color:{src_clr}'>{cwv_source}</span>
            {"" if is_real else "<span style='font-size:.72rem;color:var(--seo-muted,#64748B)'>&nbsp;— Enable 🚀 PageSpeed Insights in New Audit for real Lighthouse data</span>"}
        </div>""", unsafe_allow_html=True)

        # Extra PSI-only metrics (TBT, Speed Index)
        if is_real:
            tbt_d = cwv.get("tbt", {})
            si_d  = cwv.get("si",  {})
            if tbt_d.get("value","—") != "—" or si_d.get("value","—") != "—":
                ex1, ex2 = st.columns(2)
                for col, (lbl, metric_d, desc) in zip(
                    [ex1, ex2],
                    [
                        ("TBT — Total Blocking Time", tbt_d, "< 200ms Good · 200–600ms Needs Improvement · > 600ms Poor"),
                        ("SI — Speed Index",          si_d,  "< 3.4s Good · 3.4–5.8s Needs Improvement · > 5.8s Poor"),
                    ]
                ):
                    clr = _cwv_status_color.get(metric_d.get("status","info"), "#94A3B8")
                    with col:
                        st.markdown(f"""
                        <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                             border-radius:10px;padding:12px;text-align:center;margin-top:4px'>
                            <div style='font-size:.7rem;font-weight:700;color:var(--seo-muted,#64748B)'>{lbl}</div>
                            <div style='font-size:1.2rem;font-weight:800;color:{clr};margin:6px 0'>{metric_d.get("value","—")}</div>
                            <div style='font-size:.65rem;color:var(--seo-muted,#64748B)'>{desc}</div>
                        </div>""", unsafe_allow_html=True)

            # Opportunities from PSI
            opps = cwv.get("opportunities", [])
            if opps:
                st.markdown('<div class="section-header" style="margin-top:16px">💡 Lighthouse Opportunities</div>',
                            unsafe_allow_html=True)
                for opp in opps:
                    score = opp.get("score", 1) or 1
                    opp_clr = "#EF4444" if score < 0.5 else "#F59E0B"
                    st.markdown(f"""
                    <div style='background:var(--seo-card-bg,#fff);border-left:4px solid {opp_clr};
                         border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:6px;
                         border:1px solid var(--seo-border,rgba(148,163,184,.22))'>
                        <div style='font-weight:700;font-size:.83rem;color:var(--seo-heading,#0F172A)'>
                            {opp.get("title","")}</div>
                        {"<div style='font-size:.75rem;color:var(--seo-info-text,#1D4ED8);margin-top:3px'>" + opp.get("displayValue","") + "</div>" if opp.get("displayValue") else ""}
                    </div>""", unsafe_allow_html=True)

        # Performance score gauge
        ps = cwv.get("perf_score", 0) or 0
        ps_clr = "#10B981" if ps >= 90 else "#F59E0B" if ps >= 50 else "#EF4444"
        gauge_title = "Lighthouse Performance Score" if is_real else "Heuristic Performance Score"
        fig_ps = go.Figure(go.Indicator(
            mode="gauge+number",
            value=ps,
            number={"suffix":"%","font":{"size":28,"color":ps_clr}},
            gauge={
                "axis": {"range":[0,100],"tickwidth":1},
                "bar": {"color":ps_clr,"thickness":0.28},
                "steps":[
                    {"range":[0,50], "color":"rgba(239,68,68,.12)"},
                    {"range":[50,89],"color":"rgba(245,158,11,.12)"},
                    {"range":[89,100],"color":"rgba(16,185,129,.12)"},
                ],
                "threshold": {"line":{"color":"#10B981","width":3},"thickness":0.75,"value":90},
            },
        ))
        fig_ps.update_layout(height=220, margin=dict(t=30,b=5,l=20,r=20),
                             paper_bgcolor="rgba(0,0,0,0)", font_color="gray",
                             title={"text": gauge_title, "font":{"size":13}})
        st.plotly_chart(fig_ps, use_container_width=True)

    # ── Tab: Issues ───────────────────────────────────────────────────────
    with tab_issues:
        issues = ma.get("issues", [])
        if not issues:
            st.success("✅ No mobile SEO issues found for this URL.")
        else:
            st.markdown(f'<div class="info-box">Found <b>{len(issues)}</b> mobile issue(s) — fix highest severity first.</div>',
                        unsafe_allow_html=True)
            sev_order = {"Critical":0,"High":1,"Warning":2,"Medium":3,"Low":4}
            for iss in sorted(issues, key=lambda x: sev_order.get(x.get("severity","Low"),5)):
                _render_issue_card(iss)


# ════════════════════════════════════════════════════════════════════════════
# Image SEO Page
# ════════════════════════════════════════════════════════════════════════════

def _page_image_seo_body():
    results = st.session_state.audit_results
    if not results:
        _no_data_info(); return

    # ── Overview table across all URLs ────────────────────────────────────
    with st.expander("📊 All URLs — Image SEO Overview", expanded=len(results) > 1):
        ov_rows = []
        for r in results:
            im = r.get("image_detail", {})
            total = im.get("total", 0)
            ok_alt = total - im.get("missing_alt",0) - im.get("empty_alt",0) - im.get("generic_alt",0)
            ov_rows.append({
                "Page URL":      r.get("url","")[-80:],
                "Total":         total,
                "✅ OK Alt":     max(ok_alt, 0),
                "❌ Missing Alt": im.get("missing_alt",0),
                "⚠️ Empty Alt":  im.get("empty_alt",0),
                "🔵 Generic Alt": im.get("generic_alt",0),
                "No Lazy":       im.get("no_lazy",0),
                "No Dimensions": im.get("no_dimensions",0),
                "Non-WebP":      im.get("non_webp_jpg_png",0),
            })
        st.dataframe(pd.DataFrame(ov_rows), use_container_width=True, hide_index=True)

    # ── URL selector ──────────────────────────────────────────────────────
    urls = [r.get("url","") for r in results]
    sel  = st.selectbox("Select URL for detailed image analysis", range(len(urls)),
                        format_func=lambda i: urls[i][-90:], key="img_url_sel")
    r   = results[sel]
    im  = r.get("image_detail", {})

    if not im:
        st.warning("Image audit data not available. Please re-run the audit.")
        return

    images = im.get("images", [])

    # ── LCP candidate — SVGs excluded (browser never picks SVG as LCP) ──
    _lcp_url = None
    _raster = [img for img in images if img.get("format_label") not in ("SVG",)
               and img.get("url","").startswith("http")]
    _with_dims = [(img, (img.get("width") or 0) * (img.get("height") or 0))
                  for img in _raster if img.get("has_dimensions")]
    if _with_dims:
        _best_img, _best_area = max(_with_dims, key=lambda x: x[1])
        if _best_area > 0:
            _lcp_url = _best_img["url"]
    if not _lcp_url and _raster:
        _lcp_url = _raster[0]["url"]

    # ── Sizes cache ───────────────────────────────────────────────────────────
    _sz_cache_key   = f"img_sizes_{sel}"
    _sz_auto_key    = f"img_sizes_auto_{sel}"   # flag: auto-fetch already attempted
    _sz_cache       = st.session_state.get(_sz_cache_key, {})

    # 1. Pull from audit data (populated when check_sizes=True on new audits)
    if not _sz_cache:
        _audit_sizes = {
            img["url"]: img["file_size_bytes"]
            for img in images
            if img.get("url") and img.get("file_size_bytes") is not None
        }
        if _audit_sizes:
            st.session_state[_sz_cache_key] = _audit_sizes
            _sz_cache = _audit_sizes

    # 2. Merge PSI image sizes (real Chrome bypasses CDN bot-protection)
    _psi_for_url   = st.session_state.get(f"psi_live_{urls[sel]}", {})
    _psi_img_sizes = _psi_for_url.get("image_sizes", {}) if _psi_for_url.get("success") else {}
    if _psi_img_sizes:
        _merged = {**_sz_cache, **{k: v for k, v in _psi_img_sizes.items() if v}}
        if _merged != _sz_cache:
            st.session_state[_sz_cache_key] = _merged
            _sz_cache = _merged

    # 3. Auto-fetch on first visit if cache still empty (old audit data)
    if not _sz_cache and not st.session_state.get(_sz_auto_key):
        st.session_state[_sz_auto_key] = True
        _http_urls = list({img["url"] for img in images
                           if img.get("url", "").startswith("http")})[:60]
        if _http_urls:
            _ph = st.empty()
            _ph.info(f"Fetching file sizes for {len(_http_urls)} images…")
            _fetch_fn = partial(_fetch_size, referer=urls[sel])
            with ThreadPoolExecutor(max_workers=10) as _exe:
                _raw = list(_exe.map(_fetch_fn, _http_urls))
            _auto_sizes = {u: sz for u, sz in _raw if sz}
            if _auto_sizes:
                st.session_state[_sz_cache_key] = _auto_sizes
                _sz_cache = _auto_sizes
            _ph.empty()

    _sizes_fetched = bool(_sz_cache)
    _large_count   = sum(1 for v in _sz_cache.values() if v is not None and v > 200 * 1024)

    # ── KPI cards — clickable to filter table ─────────────────────────────
    if "img_filter" not in st.session_state:
        st.session_state["img_filter"] = None

    def _img_kpi_btn(col, label, val, clr, fkey):
        active = st.session_state.get("img_filter") == fkey
        border = f"2px solid {clr}" if active else "1px solid var(--seo-border,rgba(148,163,184,.22))"
        shadow = f"0 0 0 2px {clr}44" if active else "none"
        with col:
            st.markdown(f"""
            <div style='background:var(--seo-card-bg,#fff);border:{border};box-shadow:{shadow};
                 border-radius:10px;padding:10px 6px;text-align:center'>
                <div style='font-size:1.3rem;font-weight:800;color:{clr}'>{val}</div>
                <div style='font-size:.63rem;color:var(--seo-muted,#64748B);margin-top:2px;line-height:1.3'>{label}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"↓ {label}", key=f"imgbtn_{fkey}", use_container_width=True,
                         help=f"Filter images: {label}"):
                st.session_state["img_filter"] = None if st.session_state.get("img_filter") == fkey else fkey
                st.rerun()

    kc1 = st.columns(5)
    kc2 = st.columns(4)
    _large_val = _large_count if _sizes_fetched else "—"
    _img_kpis = [
        (kc1[0], "Total",         im.get("total",0),               "#3B82F6", "all"),
        (kc1[1], "Missing Alt",   im.get("missing_alt",0),          "#EF4444", "missing"),
        (kc1[2], "Empty Alt",     im.get("empty_alt",0),            "#F97316", "empty"),
        (kc1[3], "Generic Alt",   im.get("generic_alt",0),          "#F59E0B", "generic"),
        (kc1[4], "No Lazy Load",  im.get("no_lazy",0),              "#8B5CF6", "no_lazy"),
        (kc2[0], "No Dimensions", im.get("no_dimensions",0),        "#F97316", "no_dims"),
        (kc2[1], "Non-WebP",      im.get("non_webp_jpg_png",0),     "#06B6D4", "non_webp"),
        (kc2[2], "Bad Naming",    im.get("bad_naming",0),           "#94A3B8", "bad_name"),
        (kc2[3], ">200KB",        _large_val,                       "#EF4444", "large_size"),
    ]
    for col, lbl, val, clr, fkey in _img_kpis:
        _img_kpi_btn(col, lbl, val, clr, fkey)

    st.markdown("<br>", unsafe_allow_html=True)

    tab_table, tab_fmt, tab_issues = st.tabs(["📋 Image Table", "📊 Format Analysis", "⚠️ Issues"])

    # ── Tab: Image Table ─────────────────────────────────────────────────
    with tab_table:
        st.markdown('<div class="section-header">📋 All Images Found</div>', unsafe_allow_html=True)
        if not images:
            st.info("No images found on this page.")
        else:
            # ── Fetch real file sizes ─────────────────────────────────────────
            _btn_col, _stat_col = st.columns([2, 5])
            with _btn_col:
                if st.button("🔍 Check Real File Sizes", key=f"img_fetch_sz_{sel}",
                             help="Make HEAD requests to measure actual image file sizes"):
                    _page_url = urls[sel]
                    _img_urls = list({img["url"] for img in images
                                      if img.get("url", "").startswith("http")})[:60]
                    _spinner = st.empty()
                    _spinner.info(f"Checking {len(_img_urls)} image URLs… please wait")
                    _fetch_with_ref = partial(_fetch_size, referer=_page_url)
                    with ThreadPoolExecutor(max_workers=10) as _exe:
                        _raw = list(_exe.map(_fetch_with_ref, _img_urls))
                    _new_sizes = {u: sz for u, sz in _raw}
                    # Merge with existing PSI sizes (PSI wins for CDN-blocked images)
                    _merged = {**_new_sizes, **{k: v for k, v in _sz_cache.items() if v is not None}}
                    st.session_state[_sz_cache_key] = _merged
                    _spinner.empty()
                    st.rerun()
            with _stat_col:
                if _sizes_fetched:
                    _known = sum(1 for v in _sz_cache.values() if v is not None)
                    _psi_src = bool(st.session_state.get(f"psi_live_{urls[sel]}", {}).get("image_sizes"))
                    _src_txt = " via PSI" if _psi_src else ""
                    st.markdown(
                        f"<div style='padding:6px 0;font-size:.78rem;color:var(--seo-muted,#64748B)'>"
                        f"✅ Sizes loaded{_src_txt} for <b>{_known}</b> images &nbsp;|&nbsp; "
                        f"<span style='color:#EF4444;font-weight:700'>{_large_count} &gt; 200KB</span></div>",
                        unsafe_allow_html=True)
                else:
                    st.markdown(
                        "<div style='padding:6px 0;font-size:.75rem;color:var(--seo-muted,#64748B)'>"
                        "Run <b>Mobile Audit → Fetch Real Scores</b> first for automatic sizes, "
                        "or click here to check via HEAD requests.</div>",
                        unsafe_allow_html=True)

            # Filter controls
            fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 3])
            with fc1:
                f_alt = st.selectbox("Alt Status",
                    ["All","missing","empty","generic","keyword_stuffed","ok"], key="img_f_alt")
            with fc2:
                f_lazy = st.selectbox("Lazy Load",
                    ["All","Has lazy","Missing lazy"], key="img_f_lazy")
            with fc3:
                f_fmt = st.selectbox("Format",
                    ["All","JPEG","PNG","WebP","SVG","GIF","AVIF","Unknown"], key="img_f_fmt")
            with fc4:
                f_search = st.text_input("Search filename or alt text", placeholder="Type to search…", key="img_f_search")

            # Apply active KPI card filter first
            active_card = st.session_state.get("img_filter")
            card_filter_map = {
                "all":        lambda i: True,
                "missing":    lambda i: i.get("alt_status") == "missing",
                "empty":      lambda i: i.get("alt_status") == "empty",
                "generic":    lambda i: i.get("alt_status") == "generic",
                "no_lazy":    lambda i: not i.get("has_lazy"),
                "no_dims":    lambda i: not i.get("has_dimensions"),
                "non_webp":   lambda i: i.get("extension","") in ("jpg","jpeg","png"),
                "bad_name":   lambda i: i.get("naming_quality") == "bad",
                "large_size": lambda i: (i.get("file_size_bytes") or 0) > 200 * 1024,
            }
            filtered = [i for i in images if card_filter_map.get(active_card, lambda x: True)(i)] if active_card else images

            # Dropdown filters
            if f_alt != "All":
                filtered = [i for i in filtered if i.get("alt_status") == f_alt]
            if f_lazy == "Has lazy":
                filtered = [i for i in filtered if i.get("has_lazy")]
            elif f_lazy == "Missing lazy":
                filtered = [i for i in filtered if not i.get("has_lazy")]
            if f_fmt != "All":
                filtered = [i for i in filtered if i.get("format_label") == f_fmt]
            if f_search:
                sq = f_search.lower()
                filtered = [i for i in filtered if sq in (i.get("name","") or "").lower()
                            or sq in (i.get("alt_text","") or "").lower()
                            or sq in (i.get("url","") or "").lower()]

            # Legend + count
            st.markdown(
                f"Showing **{len(filtered)}** of {len(images)} images &nbsp;|&nbsp; "
                f"Alt: "
                f"<span style='background:var(--seo-success-bg,rgba(5,150,105,.10));color:var(--seo-success,#059669);border-radius:3px;padding:1px 6px;font-size:.7rem;font-weight:700'>OK</span> &nbsp;"
                f"<span style='background:var(--seo-error-bg,rgba(220,38,38,.10));color:var(--seo-error,#DC2626);border-radius:3px;padding:1px 6px;font-size:.7rem;font-weight:700'>Missing</span> &nbsp;"
                f"<span style='background:var(--sev-high-bg,rgba(249,115,22,.10));color:var(--sev-high,#EA580C);border-radius:3px;padding:1px 6px;font-size:.7rem;font-weight:700'>Empty</span> &nbsp;"
                f"<span style='background:var(--seo-warning-bg,rgba(217,119,6,.10));color:var(--seo-warning,#D97706);border-radius:3px;padding:1px 6px;font-size:.7rem;font-weight:700'>Generic</span> &nbsp;"
                f"<span style='background:var(--seo-accent-light,rgba(79,70,229,.10));color:var(--seo-accent,#4F46E5);border-radius:3px;padding:1px 6px;font-size:.7rem;font-weight:700'>Stuffed</span>",
                unsafe_allow_html=True
            )

            alt_status_badge = {
                "missing":        "<span style='background:var(--seo-error-bg,rgba(220,38,38,.10));color:var(--seo-error,#DC2626);padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:700'>Missing</span>",
                "empty":          "<span style='background:var(--sev-high-bg,rgba(249,115,22,.10));color:var(--sev-high,#EA580C);padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:700'>Empty</span>",
                "generic":        "<span style='background:var(--seo-warning-bg,rgba(217,119,6,.10));color:var(--seo-warning,#D97706);padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:700'>Generic</span>",
                "keyword_stuffed":"<span style='background:var(--seo-accent-light,rgba(79,70,229,.10));color:var(--seo-accent,#4F46E5);padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:700'>Stuffed</span>",
                "ok":             "<span style='background:var(--seo-success-bg,rgba(5,150,105,.10));color:var(--seo-success,#059669);padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:700'>OK</span>",
            }
            fmt_badge = {
                "JPEG":    ("<span style='background:var(--seo-info-bg,rgba(37,99,235,.07));color:var(--seo-info,#2563EB);padding:2px 7px;border-radius:4px;font-size:.7rem;font-weight:700'>JPEG</span>"),
                "PNG":     ("<span style='background:var(--seo-accent-light,rgba(79,70,229,.10));color:var(--seo-accent,#4F46E5);padding:2px 7px;border-radius:4px;font-size:.7rem;font-weight:700'>PNG</span>"),
                "WebP":    ("<span style='background:var(--seo-success-bg,rgba(5,150,105,.10));color:var(--seo-success,#059669);padding:2px 7px;border-radius:4px;font-size:.7rem;font-weight:700'>WebP</span>"),
                "SVG":     ("<span style='background:var(--seo-warning-bg,rgba(217,119,6,.10));color:var(--seo-warning,#D97706);padding:2px 7px;border-radius:4px;font-size:.7rem;font-weight:700'>SVG</span>"),
                "GIF":     ("<span style='background:var(--seo-error-bg,rgba(220,38,38,.10));color:var(--seo-error,#DC2626);padding:2px 7px;border-radius:4px;font-size:.7rem;font-weight:700'>GIF</span>"),
                "AVIF":    ("<span style='background:var(--seo-success-bg,rgba(5,150,105,.10));color:var(--cwv-good-text,#065F46);padding:2px 7px;border-radius:4px;font-size:.7rem;font-weight:700'>AVIF</span>"),
                "Unknown": ("<span style='background:var(--seo-card-bg-alt,#F1F5F9);color:var(--seo-muted,#475569);padding:2px 7px;border-radius:4px;font-size:.7rem;font-weight:700'>?</span>"),
            }

            from modules.image_auditor import _file_size_label as _fsl
            rows_html = ""
            for img in filtered[:200]:
                raw_url  = img.get("url","") or ""
                name     = img.get("name","") or "—"
                # Show clean filename; if name is a CDN hash, fall back to last path segment
                disp_name = name[:45] + ("…" if len(name) > 45 else "")
                # Readable URL: show last 2 path segments so user sees context
                from urllib.parse import urlparse as _uparse
                _parts = [p for p in _uparse(raw_url).path.split("/") if p]
                url_label = ("/".join(_parts[-2:]) if len(_parts) >= 2 else _parts[-1] if _parts else raw_url)[:60]

                fmt      = img.get("format_label","Unknown")
                fmt_b    = fmt_badge.get(fmt, fmt_badge["Unknown"])
                alt_st   = img.get("alt_status","missing")
                alt_b    = alt_status_badge.get(alt_st,"")
                alt_txt  = (img.get("alt_text") or "")
                alt_disp = alt_txt[:60] + ("…" if len(alt_txt) > 60 else "") if alt_txt else "<span style='color:var(--seo-placeholder,#94A3B8);font-style:italic'>—</span>"
                lazy_b   = "<span style='background:var(--seo-success-bg,rgba(5,150,105,.10));color:var(--seo-success,#059669);padding:1px 7px;border-radius:4px;font-size:.7rem;font-weight:700'>✓</span>" if img.get("has_lazy") else "<span style='background:var(--seo-error-bg,rgba(220,38,38,.10));color:var(--seo-error,#DC2626);padding:1px 7px;border-radius:4px;font-size:.7rem;font-weight:700'>✗</span>"
                dims_val = f'{img.get("width")}×{img.get("height")}' if img.get("has_dimensions") else "<span style='color:var(--seo-placeholder,#94A3B8)'>—</span>"
                srcset_b = "<span style='color:var(--seo-success,#10B981);font-size:.8rem'>✓</span>" if img.get("has_srcset") else "<span style='color:var(--seo-placeholder,#94A3B8);font-size:.8rem'>—</span>"
                name_q   = "" if img.get("naming_quality") == "good" else " <span style='color:#F59E0B;font-size:.7rem' title='Poor filename'>⚠</span>"

                # File size — cache first, then audit data fallback
                _sz_bytes = _sz_cache.get(raw_url) or img.get("file_size_bytes")
                if _sz_bytes is not None and _sz_bytes > 200 * 1024:
                    size_lbl = f"<b style=\"color:#EF4444\">{_fsl(_sz_bytes)} ⚠</b>"
                elif _sz_bytes is not None:
                    size_lbl = f"<b style=\"color:#10B981\">{_fsl(_sz_bytes)}</b>"
                else:
                    size_lbl = "—"

                # LCP candidate badge
                _is_lcp = (raw_url and raw_url == _lcp_url)
                lcp_badge = ("<span style='background:#7C3AED;color:#fff;padding:2px 7px;border-radius:4px;"
                             "font-size:.65rem;font-weight:700;margin-left:4px' title='Likely LCP element'>⚡ LCP</span>"
                             if _is_lcp else "")

                # Thumbnail: only render for non-SVG/non-CDN-hashed URLs
                if raw_url and fmt not in ("SVG",) and raw_url.startswith("http"):
                    thumb = f"<img src='{raw_url}' style='width:36px;height:36px;object-fit:cover;border-radius:4px;border:1px solid rgba(148,163,184,.2)' onerror=\"this.style.display='none'\" loading='lazy'>"
                else:
                    thumb = f"<span style='display:inline-block;width:36px;height:36px;background:var(--seo-card-bg-alt,#F1F5F9);border-radius:4px;text-align:center;line-height:36px;font-size:.65rem;color:var(--seo-placeholder,#94A3B8)'>{fmt[:3]}</span>"

                _row_bg = "background:rgba(124,58,237,.06);" if _is_lcp else ""
                rows_html += f"""
                <tr style='border-bottom:1px solid var(--table-row-border,rgba(148,163,184,.12));{_row_bg}'>
                    <td style='padding:6px 8px;text-align:center;width:44px'>{thumb}</td>
                    <td style='padding:6px 8px;max-width:220px'>
                        <a href='{raw_url}' target='_blank' style='font-size:.73rem;color:var(--seo-info-text,#1D4ED8);text-decoration:none;word-break:break-all' title='{raw_url}'>{url_label}</a>{lcp_badge}
                        <span style='display:block;font-size:.67rem;color:var(--seo-muted,#64748B);margin-top:1px'>{disp_name}{name_q}</span>
                    </td>
                    <td style='padding:6px 8px;text-align:center'>{fmt_b}</td>
                    <td style='padding:6px 8px;font-size:.72rem;text-align:center'>{size_lbl}</td>
                    <td style='padding:6px 8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:center'>{dims_val}</td>
                    <td style='padding:6px 8px;max-width:200px'>
                        {alt_b}
                        <span style='display:block;font-size:.68rem;color:var(--seo-muted,#64748B);margin-top:2px'>{alt_disp}</span>
                    </td>
                    <td style='padding:6px 8px;text-align:center'>{lazy_b}</td>
                    <td style='padding:6px 8px;text-align:center'>{srcset_b}</td>
                </tr>"""

            st.html(f"""
            <div style='overflow-x:auto;border-radius:10px;border:1px solid var(--seo-border,rgba(148,163,184,.22));margin-top:8px'>
            <table style='width:100%;border-collapse:collapse;background:var(--seo-card-bg,#fff)'>
                <thead style='background:var(--table-header-bg,rgba(241,245,249,.9))'>
                <tr>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B);width:44px'></th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:left'>Image URL / Filename</th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:center'>Format</th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:center'>File Size</th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:center'>Dimensions</th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B)'>Alt Text (Keyword)</th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:center'>Lazy</th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:center'>srcset</th>
                </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table></div>""")

            # ── LCP recommendation card ───────────────────────────────────
            if _lcp_url:
                _lcp_name = _lcp_url.split("/")[-1][:80] or _lcp_url[-80:]
                st.markdown("""
                <div style='margin-top:16px;border-left:5px solid #7C3AED;
                     border-radius:0 10px 10px 0;padding:12px 16px 4px 16px;
                     background:var(--seo-card-bg,#fff);
                     border:1px solid var(--seo-border,rgba(148,163,184,.22))'>
                    <div style='display:flex;align-items:center;gap:8px;margin-bottom:6px'>
                        <span style='background:#7C3AED;color:#fff;padding:3px 10px;
                              border-radius:999px;font-size:.72rem;font-weight:700'>
                            ⚡ LCP Candidate</span>
                        <b style='font-size:.88rem;color:var(--seo-heading,#0F172A)'>
                            Largest Contentful Paint Optimisation</b>
                    </div>
                    <p style='font-size:.8rem;color:var(--seo-text,#374151);margin:0 0 6px 0'>
                        This image is likely the LCP element on the page. Paste the snippet below
                        into your page <code>&lt;head&gt;</code> to preload it early and improve
                        your LCP score. Also add <code>fetchpriority="high"</code> on the
                        <code>&lt;img&gt;</code> tag itself.
                    </p>
                </div>""", unsafe_allow_html=True)
                st.code(
                    f'<link rel="preload" as="image" href="{_lcp_url}" fetchpriority="high">',
                    language="html",
                )

    # ── Tab: Format Analysis ─────────────────────────────────────────────
    with tab_fmt:
        fmts = im.get("format_breakdown", {})
        if fmts:
            fc1, fc2 = st.columns([1,1])
            with fc1:
                st.markdown('<div class="section-header">📊 Format Distribution</div>', unsafe_allow_html=True)
                fmt_clrs = {"JPEG":"#3B82F6","PNG":"#8B5CF6","WebP":"#10B981","SVG":"#F59E0B",
                             "GIF":"#EF4444","AVIF":"#06B6D4","Unknown":"#94A3B8"}
                fig_fmt = go.Figure(go.Pie(
                    labels=list(fmts.keys()), values=list(fmts.values()), hole=0.5,
                    marker_colors=[fmt_clrs.get(k,"#94A3B8") for k in fmts],
                ))
                fig_fmt.update_traces(textinfo="label+value+percent", textfont_size=11)
                fig_fmt.update_layout(showlegend=True, height=300,
                                      margin=dict(t=10,b=5,l=5,r=5),
                                      paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_fmt, use_container_width=True)

                # Alt text quality pie below format
                st.markdown('<div class="section-header">🏷️ Alt Text Quality</div>', unsafe_allow_html=True)
                alt_counts = {
                    "OK":      sum(1 for i in images if i.get("alt_status") == "ok"),
                    "Missing": im.get("missing_alt",0),
                    "Empty":   im.get("empty_alt",0),
                    "Generic": im.get("generic_alt",0),
                    "Stuffed": im.get("keyword_stuffed_alt",0),
                }
                fig_alt = go.Figure(go.Pie(
                    labels=list(alt_counts.keys()), values=list(alt_counts.values()), hole=0.5,
                    marker_colors=["#10B981","#EF4444","#F97316","#F59E0B","#8B5CF6"],
                ))
                fig_alt.update_traces(textinfo="label+value+percent", textfont_size=11)
                fig_alt.update_layout(showlegend=True, height=260,
                                      margin=dict(t=5,b=5,l=5,r=5),
                                      paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_alt, use_container_width=True)

            with fc2:
                st.markdown('<div class="section-header">💡 Format Upgrade Opportunities</div>', unsafe_allow_html=True)
                webp_opps = im.get("non_webp_jpg_png", 0)
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                     border-radius:10px;padding:16px;margin-bottom:14px'>
                    <div style='font-size:.85rem;color:var(--seo-text,#374151);margin-bottom:10px'>
                        <b>{webp_opps}</b> image(s) in legacy format (PNG/JPEG) — convert to WebP or AVIF.
                    </div>
                    <div style='font-size:.78rem;color:var(--seo-muted,#64748B);line-height:1.6'>
                        <b>WebP</b> → 25–35% smaller than JPEG, 26% smaller than PNG<br>
                        <b>AVIF</b> → up to 50% smaller than JPEG, supported in all modern browsers
                    </div>
                    <div style='margin-top:12px;display:flex;gap:8px;flex-wrap:wrap'>
                        <span style='background:#D1FAE5;color:#065F46;padding:3px 10px;border-radius:999px;font-size:.75rem;font-weight:600'>✅ WebP: {fmts.get("WebP",0)}</span>
                        <span style='background:#CFFAFE;color:#0E7490;padding:3px 10px;border-radius:999px;font-size:.75rem;font-weight:600'>✅ AVIF: {fmts.get("AVIF",0)}</span>
                        <span style='background:#FEF3C7;color:#92400E;padding:3px 10px;border-radius:999px;font-size:.75rem;font-weight:600'>⚠️ Needs conversion: {webp_opps}</span>
                    </div>
                </div>""", unsafe_allow_html=True)

                # Lazy load breakdown
                st.markdown('<div class="section-header">⚡ Lazy Load Status</div>', unsafe_allow_html=True)
                lazy_yes = sum(1 for i in images if i.get("has_lazy"))
                lazy_no  = len(images) - lazy_yes
                fig_lazy = go.Figure(go.Pie(
                    labels=["Has Lazy Load", "Missing Lazy Load"],
                    values=[lazy_yes, lazy_no], hole=0.5,
                    marker_colors=["#10B981","#EF4444"],
                ))
                fig_lazy.update_traces(textinfo="label+value+percent", textfont_size=11)
                fig_lazy.update_layout(showlegend=False, height=220,
                                       margin=dict(t=5,b=5,l=5,r=5),
                                       paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_lazy, use_container_width=True)

                # Dimensions breakdown
                st.markdown('<div class="section-header">📐 Dimensions Specified</div>', unsafe_allow_html=True)
                dims_yes = sum(1 for i in images if i.get("has_dimensions"))
                dims_no  = len(images) - dims_yes
                fig_dims = go.Figure(go.Pie(
                    labels=["Has Dimensions", "Missing Dimensions"],
                    values=[dims_yes, dims_no], hole=0.5,
                    marker_colors=["#3B82F6","#F97316"],
                ))
                fig_dims.update_traces(textinfo="label+value+percent", textfont_size=11)
                fig_dims.update_layout(showlegend=False, height=220,
                                       margin=dict(t=5,b=5,l=5,r=5),
                                       paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_dims, use_container_width=True)

    # ── Tab: Issues ───────────────────────────────────────────────────────
    with tab_issues:
        img_issues = im.get("issues", [])
        if not img_issues:
            st.success("✅ No significant image SEO issues found.")
        else:
            sev_order = {"Critical":0,"High":1,"Warning":2,"Medium":3,"Low":4}
            for iss in sorted(img_issues, key=lambda x: sev_order.get(x.get("severity","Low"),5)):
                _render_issue_card(iss)


# ════════════════════════════════════════════════════════════════════════════
# Heading Analysis Page
# ════════════════════════════════════════════════════════════════════════════

def page_heading_analysis():
    import html as _esc
    st.html("<div class='page-header'><h2>Heading structure</h2><p>H1–H6 hierarchy · violations · empty headings · duplicates</p></div>")
    st.markdown(
        "",
        unsafe_allow_html=True,
    )
    results = st.session_state.audit_results
    if not results:
        _no_data_info(); return

    urls = [r.get("url","") for r in results]

    # ── Overview table ────────────────────────────────────────────────────
    st.markdown('<div class="section-header">📊 Heading Audit Overview — All URLs</div>',
                unsafe_allow_html=True)
    ov_rows = []
    for r in results:
        hd = r.get("heading_detail", {})
        c  = hd.get("counts", {})
        ov_rows.append({
            "URL":             r.get("url","")[-70:],
            "H1 Text":         (hd.get("h1_text","") or "❌ Missing")[:80],
            "H1": c.get("h1",0), "H2": c.get("h2",0), "H3": c.get("h3",0),
            "Total":           hd.get("total_headings",0),
            "Seq. Errors":     len(hd.get("sequence_violations",[])),
            "Empty":           len(hd.get("empty_headings",[])),
            "Issues":          len(hd.get("issues",[])),
        })
    st.dataframe(pd.DataFrame(ov_rows), use_container_width=True, hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Per-URL selector ──────────────────────────────────────────────────
    sel  = st.selectbox("Select URL for detailed analysis", range(len(urls)),
                        format_func=lambda i: urls[i][-90:], key="hdg_url_sel")
    r    = results[sel]
    hd   = r.get("heading_detail", {})

    if not hd:
        st.warning("Heading audit data not available. Please re-run the audit.")
        return

    counts   = hd.get("counts", {})
    headings = hd.get("headings", [])

    # ── KPI strip (B3 fixed: is_ok only drives color, H2/H3 green only when >0) ──
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    _hd_kpis = [
        (k1, "H1",             counts.get("h1",0), "#1E40AF", counts.get("h1",0) == 1),
        (k2, "H2",             counts.get("h2",0), "#EF4444", counts.get("h2",0) > 0),
        (k3, "H3",             counts.get("h3",0), "#92400E", counts.get("h3",0) > 0),
        (k4, "Seq. Errors",    len(hd.get("sequence_violations",[])), "#EF4444", len(hd.get("sequence_violations",[]))==0),
        (k5, "Empty Headings", len(hd.get("empty_headings",[])),      "#F97316", len(hd.get("empty_headings",[]))==0),
        (k6, "Issues",         len(hd.get("issues",[])),              "#8B5CF6", len(hd.get("issues",[]))==0),
    ]
    for col, lbl, val, clr, is_ok in _hd_kpis:
        display_clr = "#10B981" if is_ok else clr
        with col:
            st.markdown(f"""
            <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                 border-top:3px solid {display_clr};border-radius:10px;padding:14px;text-align:center'>
                <div style='font-size:1.5rem;font-weight:800;color:{display_clr}'>{val}</div>
                <div style='font-size:.72rem;color:var(--seo-muted,#64748B);margin-top:3px'>{lbl}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    tab_tree, tab_table, tab_h1s, tab_issues = st.tabs([
        "🌳 Hierarchy Tree", "📋 Heading List", "🔑 H1 Across Site", "⚠️ Issues"
    ])

    # ── Tab: Hierarchy Tree ───────────────────────────────────────────────
    with tab_tree:
        h1_text = hd.get("h1_text","")
        if h1_text:
            _len_clr = "#EF4444" if len(h1_text) > 70 else "#10B981"
            st.markdown(f"""
            <div style='background:var(--seo-info-bg,rgba(37,99,235,.07));border:2px solid var(--seo-accent,#1E40AF);border-radius:10px;
                 padding:14px 18px;margin-bottom:12px'>
                <div style='display:flex;justify-content:space-between;align-items:center'>
                    <span style='font-size:.72rem;font-weight:700;color:var(--seo-accent,#1E40AF);
                          text-transform:uppercase;letter-spacing:.06em'>H1 — Primary Heading</span>
                    <span style='font-size:.72rem;font-weight:700;color:{_len_clr}'>
                        {len(h1_text)} chars {"⚠ Over 70" if len(h1_text) > 70 else "✓"}</span>
                </div>
                <div style='font-size:1.05rem;font-weight:700;color:var(--seo-heading,#0F172A);margin-top:6px'>
                    {_esc.escape(h1_text)}</div>
            </div>""", unsafe_allow_html=True)
        else:
            st.error("❌ No H1 tag found on this page — add one with your primary keyword.")

        tree_html = hd.get("tree_html","")
        if tree_html:
            st.markdown(f"""
            <div style='border:1px solid var(--seo-border,rgba(148,163,184,.22));
                 border-radius:10px;padding:16px 20px;line-height:2;overflow-x:auto'>
                {tree_html}
            </div>""",
                unsafe_allow_html=True)

        # Sequence violations
        violations = hd.get("sequence_violations", [])
        if violations:
            st.markdown('<div class="section-header" style="margin-top:16px">⚠️ Sequence Violations</div>',
                        unsafe_allow_html=True)
            for v in violations:
                st.markdown(f"""
                <div style='background:rgba(245,158,11,.10);border-left:4px solid #F59E0B;
                     border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:6px'>
                    <b>Position {v.get("position","?")}:</b>
                    H{v.get("from_level","?")} → H{v.get("to_level","?")} skips a level &nbsp;
                    <span style='color:var(--seo-muted,#64748B);font-size:.8rem'>
                        "{_esc.escape((v.get("heading_text") or "")[:70])}"</span><br>
                    <span style='font-size:.75rem;color:var(--seo-info-text,#1D4ED8)'>
                        ✅ Add H{v.get("from_level",1)+1} before this H{v.get("to_level","?")}
                        to keep the outline sequential.</span>
                </div>""", unsafe_allow_html=True)
        else:
            st.success("✅ No heading sequence violations — hierarchy is correct.")

        # Keyword coverage (B1 fixed: derive lists from {kw: bool} dict)
        kw = hd.get("keyword_coverage", {})
        if kw:
            found_in   = [k for k, v in kw.items() if v]
            missing_kw = [k for k, v in kw.items() if not v]
            st.markdown('<div class="section-header" style="margin-top:16px">🔍 Title Keyword Coverage in H1/H2</div>',
                        unsafe_allow_html=True)
            kc1, kc2 = st.columns(2)
            with kc1:
                if found_in:
                    st.success(f"✅ Found in headings: **{', '.join(found_in)}**")
                else:
                    st.warning("⚠️ No title keywords found in H1/H2 headings.")
            with kc2:
                if missing_kw:
                    st.info(f"💡 Missing from headings: **{', '.join(missing_kw[:5])}**")

        # Duplicates
        dupes = hd.get("duplicate_headings", {})
        if any(dupes.values()):
            st.markdown('<div class="section-header" style="margin-top:16px">🔁 Duplicate Headings</div>',
                        unsafe_allow_html=True)
            for level, dup_list in dupes.items():
                for dup in (dup_list or []):
                    st.warning(f"**{level.upper()}** duplicate: \"{_esc.escape(str(dup)[:80])}\"")

    # ── Tab: Full Heading List ─────────────────────────────────────────────
    with tab_table:
        if not headings:
            st.info("No headings found on this page.")
        else:
            # CSV export
            import io as _io
            _csv_lines = ["Level,Text,Length,Position"]
            for h in headings:
                _csv_lines.append(
                    f'H{h["level"]},"{h["text"].replace(chr(34), chr(39))}",{h["length"]},{h["position"]}'
                )
            st.download_button(
                "⬇️ Download Headings CSV",
                data="\n".join(_csv_lines),
                file_name=f"headings_{urls[sel].split('/')[-1] or 'page'}.csv",
                mime="text/csv",
                key=f"hdg_csv_{sel}",
            )

            level_color = {1:"#1E40AF",2:"#047857",3:"#92400E",4:"#6B21A8",5:"#9D174D",6:"#374151"}
            rows_html = ""
            for h in headings:
                lv  = h.get("level",1)
                clr = level_color.get(lv,"#374151")
                lg  = h.get("length",0)
                # Length badge: red if >70 chars, amber if 1-9 chars, green otherwise
                if lg > 70:
                    len_clr, len_tip = "#EF4444", "Too long (>70 chars)"
                elif 0 < lg < 10:
                    len_clr, len_tip = "#F59E0B", "Too short (<10 chars)"
                elif lg == 0:
                    len_clr, len_tip = "#EF4444", "Empty"
                else:
                    len_clr, len_tip = "#10B981", "Good length"
                txt  = _esc.escape(h.get("text","")[:120]) if not h.get("is_empty") else \
                       "<em style='color:#EF4444;font-size:.8rem'>[Empty]</em>"
                rows_html += f"""
                <tr style='border-bottom:1px solid var(--table-row-border,rgba(148,163,184,.12))'>
                    <td style='padding:8px 10px;text-align:center;width:56px'>
                        <span style='background:{clr};color:#fff;padding:3px 10px;
                              border-radius:6px;font-size:.75rem;font-weight:700'>H{lv}</span></td>
                    <td style='padding:8px 12px;font-size:.83rem;color:var(--seo-text,#374151)'>{txt}</td>
                    <td style='padding:8px 10px;text-align:center;font-size:.73rem;
                         font-weight:700;color:{len_clr}' title='{len_tip}'>{lg}ch</td>
                    <td style='padding:8px 10px;text-align:center;font-size:.72rem;
                         color:var(--seo-muted,#64748B)'>#{h.get("position",0)+1}</td>
                </tr>"""
            st.html(f"""
            <div style='overflow-x:auto;border-radius:10px;
                 border:1px solid var(--seo-border,rgba(148,163,184,.22));margin-top:8px'>
            <table style='width:100%;border-collapse:collapse;background:var(--seo-card-bg,#fff)'>
                <thead style='background:var(--table-header-bg,rgba(241,245,249,.9))'>
                <tr>
                    <th style='padding:8px 10px;font-size:.73rem;color:var(--seo-muted,#64748B);
                         text-align:center'>Level</th>
                    <th style='padding:8px 10px;font-size:.73rem;color:var(--seo-muted,#64748B);
                         text-align:left'>Heading Text</th>
                    <th style='padding:8px 10px;font-size:.73rem;color:var(--seo-muted,#64748B);
                         text-align:center'>Length</th>
                    <th style='padding:8px 10px;font-size:.73rem;color:var(--seo-muted,#64748B);
                         text-align:center'>Order</th>
                </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table></div>""")
            st.caption("Length: 🟢 Good  🟡 <10 chars  🔴 >70 chars or Empty")

    # ── Tab: H1 Across All Audited URLs ───────────────────────────────────
    with tab_h1s:
        st.markdown('<div class="section-header">🔑 H1 Comparison Across All URLs</div>',
                    unsafe_allow_html=True)
        h1_rows = []
        for _r in results:
            _hd  = _r.get("heading_detail", {})
            _h1  = _hd.get("h1_text","")
            _cnt = _hd.get("counts",{}).get("h1",0)
            if _cnt == 0:     _status, _status_clr = "❌ Missing",  "#EF4444"
            elif _cnt > 1:    _status, _status_clr = f"⚠ {_cnt} H1s","#F59E0B"
            elif len(_h1)>70: _status, _status_clr = "⚠ Too long",  "#F59E0B"
            elif len(_h1)<10 and _h1: _status, _status_clr = "⚠ Too short","#F59E0B"
            else:             _status, _status_clr = "✅ Good",      "#10B981"
            h1_rows.append({
                "URL":    _r.get("url","")[-80:],
                "H1 Text": _h1 or "—",
                "Length":  len(_h1) if _h1 else 0,
                "Status":  _status,
            })

        # Summary counts
        _missing = sum(1 for row in h1_rows if "Missing" in row["Status"])
        _multi   = sum(1 for row in h1_rows if "H1s" in row["Status"])
        _issues  = sum(1 for row in h1_rows if "⚠" in row["Status"] or "❌" in row["Status"])
        sm1, sm2, sm3 = st.columns(3)
        for _col, _lbl, _val, _clr in [
            (sm1, "Missing H1",     _missing, "#EF4444" if _missing else "#10B981"),
            (sm2, "Multiple H1s",   _multi,   "#F59E0B" if _multi   else "#10B981"),
            (sm3, "H1 Issues Total",_issues,  "#EF4444" if _issues  else "#10B981"),
        ]:
            with _col:
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#fff);
                     border:1px solid var(--seo-border,rgba(148,163,184,.22));
                     border-top:3px solid {_clr};border-radius:10px;
                     padding:12px;text-align:center;margin-bottom:12px'>
                    <div style='font-size:1.6rem;font-weight:900;color:{_clr}'>{_val}</div>
                    <div style='font-size:.72rem;color:var(--seo-muted,#64748B)'>{_lbl}</div>
                </div>""", unsafe_allow_html=True)

        st.dataframe(pd.DataFrame(h1_rows), use_container_width=True, hide_index=True)

        # Export
        _h1_csv = "URL,H1 Text,Length,Status\n" + "\n".join(
            f'"{row["URL"]}","{row["H1 Text"].replace(chr(34),chr(39))}",{row["Length"]},"{row["Status"]}"'
            for row in h1_rows
        )
        st.download_button("⬇️ Download H1 Report CSV", data=_h1_csv,
                           file_name="h1_report.csv", mime="text/csv", key="h1_csv_export")

    # ── Tab: Issues ───────────────────────────────────────────────────────
    with tab_issues:
        hdg_issues = hd.get("issues", [])
        if not hdg_issues:
            st.success("✅ No heading structure issues found for this page.")
        else:
            sev_order = {"Critical":0,"High":1,"Warning":2,"Medium":3,"Low":4}
            sev_icon  = {"Critical":"🔴","High":"🟠","Warning":"🟡","Medium":"🟡","Low":"🔵"}
            sorted_issues = sorted(hdg_issues, key=lambda x: sev_order.get(x.get("severity","Low"),5))

            # Summary counts row
            _sev_counts = {}
            for _i in sorted_issues:
                _s = _i.get("severity","Low")
                _sev_counts[_s] = _sev_counts.get(_s, 0) + 1
            _sc_cols = st.columns(len(_sev_counts) or 1)
            for _ci, (_sv, _cnt) in enumerate(sorted(_sev_counts.items(), key=lambda x: sev_order.get(x[0],5))):
                with _sc_cols[_ci]:
                    _cc = _SEV_COLORS.get(_sv,"#6B7280")
                    st.markdown(f"""
                    <div style='background:var(--seo-card-bg,#fff);
                         border:1px solid var(--seo-border,rgba(148,163,184,.22));
                         border-top:3px solid {_cc};border-radius:8px;
                         padding:10px;text-align:center;margin-bottom:12px'>
                        <div style='font-size:1.4rem;font-weight:900;color:{_cc}'>{_cnt}</div>
                        <div style='font-size:.7rem;color:var(--seo-muted,#64748B)'>{_sv}</div>
                    </div>""", unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # Accordion — one expander per issue
            for iss in sorted_issues:
                sev   = iss.get("severity","Low")
                sev_c = _SEV_COLORS.get(sev,"#6B7280")
                icon  = sev_icon.get(sev,"⚪")
                label = f"{icon} **{sev}** — {_esc.escape(iss.get('issue',''))}"
                with st.expander(label, expanded=False):
                    st.markdown(f"""
                    <div style='border-left:4px solid {sev_c};padding:8px 14px;border-radius:0 6px 6px 0;
                         background:var(--seo-card-bg,#fff)'>
                        <div style='font-size:.82rem;color:var(--seo-info-text,#1D4ED8);margin-bottom:6px'>
                            ✅ <b>Fix:</b> {_esc.escape(iss.get("recommendation",""))}
                        </div>
                        <div style='font-size:.75rem;color:var(--seo-muted,#64748B)'>
                            📈 Impact: <b>{iss.get("impact_score",0)}/10</b>
                            &nbsp;·&nbsp;
                            🔧 Effort: <b>{iss.get("effort","—")}</b>
                            &nbsp;·&nbsp;
                            📂 Category: <b>{iss.get("category","—")}</b>
                        </div>
                    </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# Settings
# ════════════════════════════════════════════════════════════════════════════

def page_settings():
    # ── Init edit-mode state ───────────────────────────────────────────────
    if "_api_edit" not in st.session_state:
        st.session_state["_api_edit"] = None
    if "_api_test_running" not in st.session_state:
        st.session_state["_api_test_running"] = None

    st.html("<div class='page-header'><h2>Settings &amp; API keys</h2><p>Configure Google PageSpeed, Ahrefs, SEMrush, and 60+ integrations</p></div>")

    # ── Summary bar ────────────────────────────────────────────────────────
    total_apis = sum(len(c["apis"]) for c in CATEGORIES)
    configured = APIKeyManager.configured_count()
    pct = int(configured / total_apis * 100) if total_apis else 0
    st.markdown(
        f"<div style='background:var(--seo-card-bg,#F8FAFC);border:1px solid var(--seo-border,rgba(148,163,184,.22));"
        f"border-radius:12px;padding:16px 22px;margin-bottom:18px;display:flex;align-items:center;gap:20px'>"
        f"<div style='font-size:2rem;font-weight:800;color:var(--seo-accent,#4F46E5)'>{configured}</div>"
        f"<div>"
        f"<div style='font-size:.9rem;font-weight:600;color:var(--seo-heading,#0F172A)'>"
        f"API Keys Configured</div>"
        f"<div style='font-size:.78rem;color:var(--seo-muted,#64748B)'>"
        f"{configured} of {total_apis} APIs configured ({pct}%)</div>"
        f"<div style='width:200px;height:6px;background:var(--seo-border,rgba(148,163,184,.3));"
        f"border-radius:3px;margin-top:6px'>"
        f"<div style='width:{pct}%;height:100%;background:var(--seo-accent,#4F46E5);"
        f"border-radius:3px'></div></div>"
        f"</div>"
        f"<div style='margin-left:auto;display:flex;gap:10px'>",
        unsafe_allow_html=True,
    )

    # Export to Secrets format button (outside the markdown div — Streamlit widgets can't be inside HTML)
    st.markdown("</div></div>", unsafe_allow_html=True)

    col_exp, col_info = st.columns([1, 3])
    with col_exp:
        if st.button("📋 Export to Secrets Format", use_container_width=True,
                     help="Copy this TOML into Streamlit Cloud → App settings → Secrets"):
            st.session_state["_show_secrets_export"] = True
    with col_info:
        st.markdown(
            "<div style='font-size:.78rem;color:var(--seo-muted,#64748B);padding-top:6px'>"
            "Keys are stored in <code>.streamlit/api_keys.json</code> and survive page reloads. "
            "Use <b>Export to Secrets Format</b> to copy them to Streamlit Cloud for permanent deployment."
            "</div>",
            unsafe_allow_html=True,
        )

    if st.session_state.get("_show_secrets_export"):
        toml_text = APIKeyManager.export_secrets_format()
        st.code(toml_text, language="toml")
        if st.button("✖ Close Export", key="_close_export"):
            st.session_state["_show_secrets_export"] = False
            st.rerun()

    # ── Search bar ─────────────────────────────────────────────────────────
    search_q = st.text_input(
        "🔍 Search APIs",
        placeholder="Search by name or category…",
        label_visibility="collapsed",
        key="_api_search",
    ).lower().strip()

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    # ── Category sections ──────────────────────────────────────────────────
    for cat in CATEGORIES:
        cat_apis = cat["apis"]
        # Apply search filter
        if search_q:
            cat_apis = [
                a for a in cat_apis
                if search_q in a[1].lower() or search_q in cat["label"].lower()
            ]
            if not cat_apis:
                continue

        cat_configured = sum(1 for a in cat_apis if APIKeyManager.has(a[0]))
        cat_total = len(cat_apis)

        # Category header chip
        chip_bg   = "rgba(5,150,105,.12)"  if cat_configured > 0 else "rgba(148,163,184,.15)"
        chip_text = "var(--seo-success,#059669)" if cat_configured > 0 else "var(--seo-muted,#64748B)"
        chip_label = f"{cat_configured}/{cat_total}"

        expander_label = (
            f"{cat['icon']} {cat['label']}  ·  "
            f"{cat_configured} configured"
        )
        with st.expander(expander_label, expanded=(cat_configured > 0 and search_q == "")):
            for api_entry in cat_apis:
                api_id, api_name, placeholder, docs_url, testable = api_entry
                has_key  = APIKeyManager.has(api_id)
                cur_key  = APIKeyManager.get(api_id)
                masked   = APIKeyManager.mask(cur_key) if cur_key else ""
                test_res = APIKeyManager.get_test_status(api_id)
                is_editing = st.session_state["_api_edit"] == api_id

                # Row container
                row_bg = (
                    "rgba(5,150,105,.06)" if has_key
                    else "rgba(148,163,184,.07)"
                )
                st.markdown(
                    f"<div style='background:{row_bg};border:1px solid var(--seo-border,rgba(148,163,184,.22));"
                    f"border-radius:9px;padding:10px 14px;margin-bottom:8px'>",
                    unsafe_allow_html=True,
                )

                c_name, c_status, c_actions = st.columns([3, 2, 2])

                with c_name:
                    status_dot = "🟢" if has_key else "⚪"
                    docs_link  = (
                        f" <a href='{docs_url}' target='_blank' "
                        f"style='font-size:.7rem;color:var(--seo-info-text,#1D4ED8);"
                        f"text-decoration:none;opacity:.7'>docs ↗</a>"
                        if docs_url else ""
                    )
                    st.markdown(
                        f"<div style='font-size:.84rem;font-weight:600;"
                        f"color:var(--seo-heading,#0F172A)'>"
                        f"{status_dot} {api_name}{docs_link}</div>",
                        unsafe_allow_html=True,
                    )

                with c_status:
                    if has_key:
                        st.markdown(
                            f"<div style='font-size:.75rem;font-family:monospace;"
                            f"color:var(--seo-muted,#64748B);padding-top:2px'>{masked}</div>",
                            unsafe_allow_html=True,
                        )
                        if test_res is not None:
                            tc = "var(--seo-success,#059669)" if test_res["ok"] else "var(--seo-error,#DC2626)"
                            ti = "✅" if test_res["ok"] else "❌"
                            st.markdown(
                                f"<div style='font-size:.72rem;color:{tc}'>{ti} {test_res['msg']}</div>",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.markdown(
                            "<div style='font-size:.75rem;color:var(--seo-muted,#94A3B8);"
                            "padding-top:2px;font-style:italic'>Not configured</div>",
                            unsafe_allow_html=True,
                        )

                with c_actions:
                    btn_col1, btn_col2, btn_col3 = st.columns(3)
                    with btn_col1:
                        edit_label = "✏️ Edit" if has_key else "➕ Add"
                        if st.button(edit_label, key=f"_edit_{api_id}", use_container_width=True):
                            if st.session_state["_api_edit"] == api_id:
                                st.session_state["_api_edit"] = None
                            else:
                                st.session_state["_api_edit"] = api_id
                            st.rerun()
                    with btn_col2:
                        test_disabled = not has_key or not testable
                        test_help = (
                            "No test available for this API" if not testable
                            else ("Add a key first" if not has_key else "Test connection")
                        )
                        if st.button(
                            "🔌 Test", key=f"_test_{api_id}",
                            use_container_width=True,
                            disabled=test_disabled,
                            help=test_help,
                        ):
                            with st.spinner(f"Testing {api_name}…"):
                                ok, msg = test_api_key(api_id)
                            st.rerun()
                    with btn_col3:
                        del_disabled = not has_key
                        if st.button(
                            "🗑️", key=f"_del_{api_id}",
                            use_container_width=True,
                            disabled=del_disabled,
                            help="Remove key",
                        ):
                            APIKeyManager.delete(api_id)
                            if api_id == "psi":
                                st.session_state.pop("psi_api_key_global", None)
                            st.rerun()

                # Inline edit form
                if is_editing:
                    with st.form(key=f"_form_{api_id}", clear_on_submit=True):
                        new_key = st.text_input(
                            f"API Key for {api_name}",
                            type="password",
                            placeholder=placeholder,
                            help=f"Paste your {api_name} API key here.",
                        )
                        save_col, cancel_col = st.columns(2)
                        with save_col:
                            submitted = st.form_submit_button("💾 Save Key", type="primary", use_container_width=True)
                        with cancel_col:
                            cancelled = st.form_submit_button("✖ Cancel", use_container_width=True)

                        if submitted:
                            if new_key.strip():
                                APIKeyManager.set(api_id, new_key.strip())
                                if api_id == "psi":
                                    st.session_state["psi_api_key_global"] = new_key.strip()
                                st.session_state["_api_edit"] = None
                                st.success(f"✅ {api_name} key saved.")
                                st.rerun()
                            else:
                                st.warning("Key cannot be empty. Use 🗑️ to remove an existing key.")
                        if cancelled:
                            st.session_state["_api_edit"] = None
                            st.rerun()

                st.markdown("</div>", unsafe_allow_html=True)

    # ── Permanent storage instructions ─────────────────────────────────────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    with st.expander("🔐 Permanent Storage — Streamlit Cloud Secrets"):
        st.markdown("""
Keys stored in `.streamlit/api_keys.json` survive page reloads during local development but are lost on Streamlit Cloud redeploy.

**To make them permanent on Streamlit Cloud:**
1. Click **Export to Secrets Format** above to get a TOML snippet
2. Go to your app on [share.streamlit.io](https://share.streamlit.io)
3. Click **⋮ Menu → Settings → Secrets**
4. Paste the TOML and click **Save**

The app loads Streamlit Secrets automatically on every startup — no re-entry needed.
        """)

    # ── Session info ───────────────────────────────────────────────────────
    st.markdown('<div class="section-header">ℹ️ Session Info</div>', unsafe_allow_html=True)
    n_audited = len(st.session_state.get("audit_results", []))
    st.markdown(
        f"<div style='background:var(--seo-card-bg,#fff);"
        f"border:1px solid var(--seo-border,rgba(148,163,184,.22));"
        f"border-radius:10px;padding:14px 18px;font-size:.82rem;"
        f"color:var(--seo-text,#374151)'>"
        f"<b>Audited URLs in session:</b> {n_audited}<br>"
        f"<b>API Keys configured:</b> {APIKeyManager.configured_count()} of {total_apis}<br>"
        f"<b>PSI Key status:</b> {'✅ Ready' if APIKeyManager.has('psi') else '❌ Not set — audits run without PSI data'}"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    if st.button("🗑️ Clear all audit data from session", type="secondary"):
        st.session_state["audit_results"] = []
        st.session_state["last_audit_date"] = None
        st.success("Session audit data cleared.")


# Export
# ════════════════════════════════════════════════════════════════════════════

def page_export():
    st.html("<div class='page-header'><h2>Export reports</h2><p>Download audit data as CSV · Excel · PDF executive summary</p></div>")
    results = st.session_state.audit_results
    if not results:
        st.info("No audit results to export. Run an audit first.")
        return

    st.markdown(f'<div class="info-box">Ready to export <b>{len(results)}</b> audited URLs.</div>',
                unsafe_allow_html=True)

    from modules.report_generator import generate_csv, generate_excel, generate_pdf

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("#### 📄 CSV Report")
        st.caption("Flat table with all audit metrics. Best for quick data analysis.")
        csv_data = generate_csv(results)
        st.download_button("⬇️ Download CSV", data=csv_data,
            file_name=f"seo_audit_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv", type="primary")
    with col2:
        st.markdown("#### 📊 Excel Report")
        st.caption("Multi-sheet: Summary + Issues + Links, colour-coded.")
        excel_data = generate_excel(results)
        st.download_button("⬇️ Download Excel", data=excel_data,
            file_name=f"seo_audit_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary")
    with col3:
        st.markdown("#### 📑 PDF Report")
        st.caption("Executive summary with URL table and colour-coded scores.")
        pdf_data = generate_pdf(results)
        st.download_button("⬇️ Download PDF", data=pdf_data,
            file_name=f"seo_audit_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf", type="primary")

    st.markdown("---")
    st.markdown("#### Preview")
    st.dataframe(build_results_df(results), use_container_width=True, height=350)


# ════════════════════════════════════════════════════════════════════════════
# Sidebar Navigation
# ════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.html("""
    <div class='sb-logo'>
      <div class='sb-logo-mark'>🔍</div>
      <div>
        <div class='sb-logo-name'>SEO Audit</div>
        <div class='sb-logo-sub'>Technical dashboard</div>
      </div>
    </div>
    """)

    # Programmatic navigation — resolve BEFORE rendering the radio
    if st.session_state.get("nav_page"):
        target = st.session_state.pop("nav_page")
        if target in _PAGES:
            st.session_state["active_page"] = target
    # Legacy routing from old "page" key
    if st.session_state.get("page") == "URL Detail":
        st.session_state["active_page"] = "🔎 URL Detail"
        del st.session_state["page"]

    _cur_idx = _PAGES.index(st.session_state["active_page"]) if st.session_state["active_page"] in _PAGES else 0

    page = st.radio(
        "Navigation",
        _PAGES,
        index=_cur_idx,
        label_visibility="collapsed",
    )
    # Keep session state in sync so programmatic nav works visually
    st.session_state["active_page"] = page

    results = st.session_state.audit_results
    if results:
        st.markdown("---")
        st.markdown("**📌 Audit Status**")
        avg = sum(r.get("seo_score",0) for r in results) / len(results)
        crit_u = sum(1 for r in results if r.get("seo_score",0) < 50)
        broken = (sum(r.get("internal_links",{}).get("broken_count",0) or 0 for r in results) +
                  sum(r.get("external_links",{}).get("broken_count",0) or 0 for r in results))
        st.caption(f"URLs: {len(results)}")
        if st.session_state.last_audit_date:
            st.caption(f"Last run: {st.session_state.last_audit_date}")
        color = _score_color(avg)
        st.markdown(f"<div style='color:{color};font-weight:700;font-size:.9rem'>"
                    f"Avg Score: {avg:.1f}/100</div>", unsafe_allow_html=True)
        if crit_u:
            st.markdown(f"<div style='color:#EF4444;font-size:.8rem'>⚠️ {crit_u} critical URL(s)</div>",
                        unsafe_allow_html=True)
        if broken:
            st.markdown(f"<div style='color:#F97316;font-size:.8rem'>🔴 {broken} broken link(s)</div>",
                        unsafe_allow_html=True)

    st.html("""
    <div class='sb-profile'>
      <div class='sb-avatar'>VR</div>
      <div>
        <div class='sb-user-name'>Venkat Ramana</div>
        <div class='sb-user-email'>venkat.r@edstellar.com</div>
      </div>
    </div>
    """)


# ════════════════════════════════════════════════════════════════════════════
# Router
# ════════════════════════════════════════════════════════════════════════════

if   page == "📊 Dashboard Overview": page_dashboard()
elif page == "🚀 New Audit":          page_new_audit()
elif page == "📋 Audit Results":      page_results()
elif page == "🔎 URL Detail":         page_url_detail()
elif page == "🔗 Link Analysis":      page_link_analysis()
elif page == "⚡ Performance Audit":  page_performance()
elif page == "📝 Heading Analysis":   page_heading_analysis()
elif page == "📤 Export Reports":     page_export()
elif page == "⚙️ Settings":           page_settings()

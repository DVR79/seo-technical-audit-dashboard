"""SEO Technical Audit Dashboard — Enterprise Streamlit Application."""

import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SEO Technical Audit Dashboard",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────
css_path = Path("assets/style.css")
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────────────────────
for key, default in [
    ("audit_results", []),
    ("last_audit_date", None),
    ("selected_url_idx", 0),
    ("single_result", None),
    ("dup_report", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ════════════════════════════════════════════════════════════════════════════

def _score_color(s):
    if s >= 90: return "#10B981"
    if s >= 75: return "#3B82F6"
    if s >= 50: return "#F59E0B"
    return "#EF4444"

def _score_label(s):
    if s >= 90: return "Excellent"
    if s >= 75: return "Good"
    if s >= 50: return "Needs Attention"
    return "Critical"

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

def metric_card(label, value, color="#3B82F6"):
    st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value" style="color:{color}">{value}</div>
            <div class="metric-label">{label}</div>
        </div>""", unsafe_allow_html=True)


# ── Ahrefs-style link table ────────────────────────────────────────────────

def _health_badge(health, label):
    colors = {
        "ok":       ("#D1FAE5", "#065F46"),
        "redirect": ("#FEF3C7", "#92400E"),
        "blocked":  ("#EDE9FE", "#5B21B6"),
        "broken":   ("#FEE2E2", "#991B1B"),
        "unknown":  ("#F1F5F9", "#475569"),
    }
    bg, fg = colors.get(health, ("#F1F5F9", "#475569"))
    return (f"<span style='background:{bg};color:{fg};padding:2px 7px;"
            f"border-radius:4px;font-size:.72rem;font-weight:700;white-space:nowrap'>{label}</span>")


def _rel_badge(is_dofollow, is_nofollow, is_sponsored, is_ugc):
    if is_sponsored:
        return "<span style='background:#FEF3C7;color:#92400E;padding:2px 7px;border-radius:4px;font-size:.72rem;font-weight:700'>Sponsored</span>"
    if is_ugc:
        return "<span style='background:#EDE9FE;color:#5B21B6;padding:2px 7px;border-radius:4px;font-size:.72rem;font-weight:700'>UGC</span>"
    if is_nofollow:
        return "<span style='background:#FEE2E2;color:#991B1B;padding:2px 7px;border-radius:4px;font-size:.72rem;font-weight:700'>Nofollow</span>"
    return "<span style='background:#D1FAE5;color:#065F46;padding:2px 7px;border-radius:4px;font-size:.72rem;font-weight:700'>Dofollow</span>"


def render_link_table(links, show_source=False, source_label="Source", max_rows=100):
    """Render an Ahrefs-style link table with status badges."""
    if not links:
        st.info("No links found.")
        return

    # Filter controls
    fc1, fc2, fc3 = st.columns([2, 2, 2])
    with fc1:
        filter_rel = st.selectbox(
            "Filter by Rel",
            ["All", "Dofollow", "Nofollow", "Sponsored", "UGC"],
            key=f"rel_f_{id(links)}"
        )
    with fc2:
        filter_health = st.selectbox(
            "Filter by Status",
            ["All", "OK (2xx)", "Redirect (3xx)", "Broken (4xx/5xx)", "Blocked (999)", "Not Checked"],
            key=f"hlt_f_{id(links)}"
        )
    with fc3:
        search_q = st.text_input("Search URL / Anchor", key=f"srch_f_{id(links)}")

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

    if search_q:
        sq = search_q.lower()
        filtered = [l for l in filtered
                    if sq in l.get("url","").lower() or sq in l.get("anchor_text","").lower()]

    st.caption(f"Showing **{min(len(filtered), max_rows)}** of {len(filtered)} links")

    rows_html = ""
    for lk in filtered[:max_rows]:
        url    = lk.get("url","")
        anchor = lk.get("anchor_text","[No Anchor]") or "[No Anchor]"
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
        short_url = url[:70] + ("…" if len(url) > 70 else "")
        short_anc = anchor[:55] + ("…" if len(anchor) > 55 else "")
        source_col = (f"<td style='font-size:.72rem;color:var(--seo-muted,#64748B);max-width:130px;word-break:break-all'>"
                      f"{lk.get('source','')[:60]}</td>") if show_source else ""

        rows_html += f"""
        <tr style='border-bottom:1px solid var(--table-row-border,rgba(148,163,184,.15));'>
            {source_col}
            <td style='padding:7px 10px;max-width:260px;word-break:break-all'>
                <a href='{url}' target='_blank' style='font-size:.78rem;color:var(--seo-info-text,#1D4ED8);text-decoration:none'
                   title='{url}'>{short_url}</a>
                <div style='font-size:.7rem;color:#94A3B8;margin-top:2px'>{short_anc}</div>
            </td>
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
                <th style='padding:8px 10px;text-align:left;color:var(--seo-text,#374151);font-size:.78rem'>Target URL / Anchor Text</th>
                <th style='padding:8px 10px;text-align:center;color:var(--seo-text,#374151);font-size:.78rem'>Link Type</th>
                <th style='padding:8px 10px;text-align:center;color:var(--seo-text,#374151);font-size:.78rem'>Status</th>
                <th style='padding:8px 10px;text-align:center;color:var(--seo-text,#374151);font-size:.78rem'>Tab / Security</th>
            </tr>
        </thead>
        <tbody>{rows_html}</tbody>
    </table>
    </div>"""
    st.markdown(table_html, unsafe_allow_html=True)


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


def extract_urls_from_sitemap(uploaded_file):
    try:
        content = uploaded_file.read()
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
    title = serp_data.get("title","—") or "—"
    desc  = serp_data.get("description","") or "No meta description found."
    bc    = serp_data.get("breadcrumb","") or serp_data.get("url","")
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
    og_title = social_data.get("og_title","") or "No title"
    og_desc  = social_data.get("og_description","") or "No description"
    og_img   = social_data.get("og_image","")
    site_name= social_data.get("og_site_name","") or url

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

    # ── Score banner ──────────────────────────────────────────────────────
    st.markdown(f"""
    <div style='background:linear-gradient(135deg,#0F172A,#1E293B);border-radius:14px;
    padding:20px 28px;margin-bottom:18px;display:flex;align-items:center;gap:32px;flex-wrap:wrap'>
        <div style='text-align:center;min-width:90px'>
            <div style='font-size:3rem;font-weight:800;color:{color};line-height:1'>{score}</div>
            <div style='font-size:.78rem;color:#94A3B8;margin-top:2px'>SEO Score / 100</div>
            <div style='margin-top:6px'><span class='{_score_class(score)} score-badge'>{label}</span></div>
        </div>
        <div style='flex:1;min-width:200px'>
            <div style='font-size:.95rem;font-weight:700;color:#F1F5F9;margin-bottom:6px;word-break:break-all'>
                {r.get("url","")[:100]}
            </div>
            <div style='font-size:.8rem;color:#94A3B8'>
                Type: <b style='color:#CBD5E1'>{atype.title()}</b> &nbsp;|&nbsp;
                HTTP: <b style='color:#CBD5E1'>{r.get("status_code",0)}</b> &nbsp;|&nbsp;
                Response: <b style='color:#CBD5E1'>{r.get("response_time",0):.2f}s</b> &nbsp;|&nbsp;
                Redirects: <b style='color:#CBD5E1'>{r.get("redirect_count",0)}</b>
            </div>
            <div style='margin-top:10px;display:flex;gap:10px;flex-wrap:wrap'>
                <span style='background:#1E3A5F;color:#93C5FD;padding:4px 10px;border-radius:8px;font-size:.78rem'>
                    Issues: <b>{len(issues)}</b></span>
                <span style='background:#450A0A;color:#FCA5A5;padding:4px 10px;border-radius:8px;font-size:.78rem'>
                    Critical: <b>{crit_n}</b></span>
                <span style='background:#431407;color:#FDBA74;padding:4px 10px;border-radius:8px;font-size:.78rem'>
                    High: <b>{high_n}</b></span>
                <span style='background:#052E16;color:#86EFAC;padding:4px 10px;border-radius:8px;font-size:.78rem'>
                    Words: <b>{cont.get("word_count",0):,}</b></span>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

    # ── Tabs ──────────────────────────────────────────────────────────────
    tabs = st.tabs([
        "📊 Summary", "🔗 Outgoing Links", "🌐 SERP & Social",
        "🔬 Schema", "🔧 Technical", "⚠️ Issues", "💡 Top Recommendations"
    ])

    # Tab 0 — Summary
    with tabs[0]:
        k1,k2,k3,k4,k5,k6,k7,k8 = st.columns(8)
        k1.metric("H1",          head.get("h1_count",0))
        k2.metric("H2",          head.get("h2_count",0))
        k3.metric("Images",      imgs.get("total_images",0))
        k4.metric("Missing Alt", imgs.get("missing_alt_count",0))
        k5.metric("Int. Links",  il.get("total_links",0))
        k6.metric("Ext. Links",  el_.get("total_links",0))
        k7.metric("Broken",      (il.get("broken_count",0) or 0) + (el_.get("broken_count",0) or 0))
        k8.metric("Schema Types",len(adv.get("schema_types",[])))

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
                        {"<span style='background:#FEE2E2;color:#991B1B;padding:3px 8px;border-radius:5px;font-size:.78rem;font-weight:700'>🔴 " + str(bi) + " Broken</span>" if bi else "<span style='background:#D1FAE5;color:#065F46;padding:3px 8px;border-radius:5px;font-size:.78rem;font-weight:700'>✅ No Broken Links</span>"}
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
                        {"<span style='background:#FEE2E2;color:#991B1B;padding:3px 8px;border-radius:5px;font-size:.78rem;font-weight:700'>🔴 " + str(be) + " Broken</span>" if be else "<span style='background:#D1FAE5;color:#065F46;padding:3px 8px;border-radius:5px;font-size:.78rem;font-weight:700'>✅ No Broken</span>"}
                        {"<span style='background:#EDE9FE;color:#5B21B6;padding:3px 8px;border-radius:5px;font-size:.78rem;font-weight:700'>🚫 " + str(blk_cnt) + " Blocked</span>" if blk_cnt else ""}
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
                ("AMP",          adv.get("has_amp", False)),
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
            render_link_table(il_links, max_rows=100)
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
            render_link_table(el_links, max_rows=100)
        else:
            render_link_table(el_links, max_rows=100)

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

        def _cwv_color(label):
            if "Good" in label: return ("#D1FAE5", "#065F46")
            if "Needs" in label: return ("#FEF3C7", "#92400E")
            return ("#FEE2E2", "#991B1B")

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
                            f"<tr><td style='padding:5px 10px;font-weight:600;color:var(--seo-heading,#1E40AF);"
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

            st.markdown(
                f"<div style='overflow-x:auto;border-radius:8px;border:1px solid var(--seo-border,rgba(148,163,184,.22))'>"
                f"<table style='width:100%;border-collapse:collapse;background:var(--seo-card-bg,#fff)'>"
                f"<thead style='background:var(--table-header-bg,rgba(241,245,249,.9))'><tr>"
                f"<th style='padding:7px 10px;text-align:left;font-size:.78rem;color:var(--seo-muted,#1E40AF)'>Header</th>"
                f"<th style='padding:7px 10px;text-align:left;font-size:.78rem;color:var(--seo-muted,#1E40AF)'>Value</th>"
                f"</tr></thead><tbody>"
                f"{crit_rows}"
                f"<tr><td colspan='2' style='padding:4px 10px;font-size:.7rem;color:#94A3B8;"
                f"background:var(--seo-card-bg,#F8FAFC)'>— Other headers —</td></tr>"
                f"{other_rows}"
                f"</tbody></table></div>",
                unsafe_allow_html=True,
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
            color = "#065F46" if present else "#991B1B"
            bg = "#D1FAE5" if present else "#FEE2E2"
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;padding:7px 12px;"
                f"background:{bg};border-radius:7px;margin-bottom:5px'>"
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
                st.success(f"✅ AMP version detected")
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

    # Tab 5 — Issues (thematic)
    with tabs[5]:
        from modules.scoring import get_thematic_issues
        themed = get_thematic_issues(issues)
        if not themed:
            st.success("🎉 No issues found!")
        else:
            for theme, theme_issues in themed.items():
                with st.expander(f"**{theme}** — {len(theme_issues)} issue(s)",
                                 expanded=any(i.get("severity") in ["Critical","High"]
                                              for i in theme_issues)):
                    for iss in sorted(theme_issues,
                                      key=lambda x: x.get("impact_score",0), reverse=True):
                        sev = iss.get("severity","Low")
                        imp = iss.get("impact_score",0)
                        eff = iss.get("effort","—")
                        st.markdown(f"""
                        <div style='padding:10px 14px;background:{_sev_bg(sev)};border-radius:8px;
                        margin-bottom:8px;border-left:4px solid {_sev_color(sev)}'>
                            <div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px'>
                                <span style='font-weight:700;font-size:.88rem;color:var(--seo-heading,#0F172A)'>
                                    {iss.get("issue","")}</span>
                                <div style='display:flex;gap:6px'>
                                    <span style='background:{_sev_color(sev)};color:white;
                                    padding:2px 8px;border-radius:4px;font-size:.72rem;font-weight:700'>{sev}</span>
                                    <span style='background:#1E3A5F;color:#93C5FD;
                                    padding:2px 8px;border-radius:4px;font-size:.72rem'>Impact: {imp}/10</span>
                                    <span style='background:#1E293B;color:#CBD5E1;
                                    padding:2px 8px;border-radius:4px;font-size:.72rem'>Effort: {eff}</span>
                                </div>
                            </div>
                            <div style='font-size:.75rem;color:var(--seo-muted,#64748B);margin-top:3px'>📂 {iss.get("category","")}</div>
                            <div style='font-size:.83rem;color:var(--seo-info-text,#1D4ED8);margin-top:6px'>✅ {iss.get("recommendation","")}</div>
                        </div>""", unsafe_allow_html=True)

    # Tab 6 — Top Recommendations by Impact
    with tabs[6]:
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
                    <div style='font-size:.84rem;color:#1D4ED8;margin-top:6px'>✅ {iss.get("recommendation","")}</div>
                </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# Dashboard
# ════════════════════════════════════════════════════════════════════════════

def page_dashboard():
    results  = st.session_state.audit_results
    last_date= st.session_state.last_audit_date

    st.markdown("""
    <h1 style='font-size:1.8rem;font-weight:800;color:var(--seo-heading,#0F172A);margin-bottom:2px'>
    🔍 SEO Technical Audit Dashboard</h1>
    <p style='color:var(--seo-muted,#64748B);margin-bottom:20px'>Comprehensive SEO Audit for Courses and Blogs</p>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1: st.caption(f"**Last Audit:** {last_date}" if last_date else "No audit run yet")
    with c2: st.caption(f"**Total URLs Audited:** {len(results)}")

    if not results:
        st.markdown('<div class="info-box">👆 No audit data yet. Go to <b>New Audit</b> to get started.</div>',
                    unsafe_allow_html=True)
        return

    total  = len(results)
    scores = [r.get("seo_score",0) for r in results]
    avg_sc = round(sum(scores)/total, 1)
    healthy= sum(1 for s in scores if s >= 75)
    crit_u = sum(1 for s in scores if s < 50)
    warn_u = sum(1 for s in scores if 50 <= s < 75)
    all_issues = [i for r in results for i in r.get("all_issues",[])]
    crit_iss   = sum(1 for i in all_issues if i.get("severity")=="Critical")
    broken_lnk = (sum(r.get("internal_links",{}).get("broken_count",0) or 0 for r in results) +
                  sum(r.get("external_links",{}).get("broken_count",0) or 0 for r in results))
    miss_meta  = sum(1 for r in results
                     if not r.get("metadata",{}).get("has_title") or
                        not r.get("metadata",{}).get("has_description"))
    no_viewport= sum(1 for r in results if not r.get("advanced",{}).get("has_viewport",True))
    no_schema  = sum(1 for r in results if not r.get("advanced",{}).get("has_schema",True))
    avg_wc     = round(sum(r.get("content",{}).get("word_count",0) for r in results)/total)

    # ── KPI Cards ─────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">📊 Overview</div>', unsafe_allow_html=True)
    r1 = st.columns(4)
    r2 = st.columns(4)
    with r1[0]: metric_card("Total URLs",       total,              "#3B82F6")
    with r1[1]: metric_card("Healthy URLs",     healthy,            "#10B981")
    with r1[2]: metric_card("Critical URLs",    crit_u,             "#EF4444")
    with r1[3]: metric_card("Avg SEO Score",    f"{avg_sc}/100",    _score_color(avg_sc))
    with r2[0]: metric_card("Critical Issues",  crit_iss,           "#EF4444")
    with r2[1]: metric_card("Broken Links",     broken_lnk,         "#F97316")
    with r2[2]: metric_card("No Viewport",      no_viewport,        "#8B5CF6")
    with r2[3]: metric_card("No Schema",        no_schema,          "#06B6D4")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── SEMrush-style Issues Summary + Site Health Gauge ─────────────────
    warn_iss  = sum(1 for i in all_issues if i.get("severity") in ("Warning","Medium"))
    notice_iss= sum(1 for i in all_issues if i.get("severity") == "Low")
    high_iss  = sum(1 for i in all_issues if i.get("severity") == "High")
    errors_total = crit_iss + high_iss
    health_pct   = max(0, min(100, round(100 - (errors_total * 4 + warn_iss * 2 + notice_iss * 0.5) / max(total,1))))

    hp1, hp2 = st.columns([2, 1])
    with hp1:
        st.markdown('<div class="section-header">🏥 Site Health Overview</div>', unsafe_allow_html=True)
        e1, e2, e3, e4 = st.columns(4)
        with e1:
            st.markdown(f"""
            <div style='background:var(--sev-critical-bg,rgba(239,68,68,.10));border-radius:10px;
                 padding:14px 16px;text-align:center;border:1px solid rgba(239,68,68,.2)'>
                <div style='font-size:2rem;font-weight:800;color:#EF4444'>{crit_iss}</div>
                <div style='font-size:.75rem;font-weight:700;color:#EF4444;margin-top:2px'>ERRORS</div>
                <div style='font-size:.68rem;color:var(--seo-muted,#64748B);margin-top:2px'>Critical issues</div>
            </div>""", unsafe_allow_html=True)
        with e2:
            st.markdown(f"""
            <div style='background:var(--sev-high-bg,rgba(249,115,22,.10));border-radius:10px;
                 padding:14px 16px;text-align:center;border:1px solid rgba(249,115,22,.2)'>
                <div style='font-size:2rem;font-weight:800;color:#F97316'>{high_iss}</div>
                <div style='font-size:.75rem;font-weight:700;color:#F97316;margin-top:2px'>HIGH</div>
                <div style='font-size:.68rem;color:var(--seo-muted,#64748B);margin-top:2px'>High priority</div>
            </div>""", unsafe_allow_html=True)
        with e3:
            st.markdown(f"""
            <div style='background:var(--sev-warning-bg,rgba(245,158,11,.10));border-radius:10px;
                 padding:14px 16px;text-align:center;border:1px solid rgba(245,158,11,.2)'>
                <div style='font-size:2rem;font-weight:800;color:#F59E0B'>{warn_iss}</div>
                <div style='font-size:.75rem;font-weight:700;color:#F59E0B;margin-top:2px'>WARNINGS</div>
                <div style='font-size:.68rem;color:var(--seo-muted,#64748B);margin-top:2px'>Medium priority</div>
            </div>""", unsafe_allow_html=True)
        with e4:
            st.markdown(f"""
            <div style='background:var(--sev-low-bg,rgba(59,130,246,.10));border-radius:10px;
                 padding:14px 16px;text-align:center;border:1px solid rgba(59,130,246,.2)'>
                <div style='font-size:2rem;font-weight:800;color:#3B82F6'>{notice_iss}</div>
                <div style='font-size:.75rem;font-weight:700;color:#3B82F6;margin-top:2px'>NOTICES</div>
                <div style='font-size:.68rem;color:var(--seo-muted,#64748B);margin-top:2px'>Low priority</div>
            </div>""", unsafe_allow_html=True)

    with hp2:
        st.markdown('<div class="section-header">📊 Health Score</div>', unsafe_allow_html=True)
        h_color = "#10B981" if health_pct >= 80 else "#F59E0B" if health_pct >= 60 else "#EF4444"
        h_label = "Excellent" if health_pct >= 80 else "Needs Work" if health_pct >= 60 else "Critical"
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=health_pct,
            number={"suffix": "%", "font": {"size": 32, "color": h_color}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "gray"},
                "bar": {"color": h_color, "thickness": 0.28},
                "steps": [
                    {"range": [0, 50],  "color": "rgba(239,68,68,.12)"},
                    {"range": [50, 75], "color": "rgba(245,158,11,.12)"},
                    {"range": [75, 100],"color": "rgba(16,185,129,.12)"},
                ],
                "threshold": {"line": {"color": h_color, "width": 3}, "value": health_pct},
            },
        ))
        fig_gauge.update_layout(
            height=200, margin=dict(t=20, b=10, l=20, r=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="gray",
            annotations=[{"text": h_label, "x": 0.5, "y": 0.15, "showarrow": False,
                           "font": {"size": 13, "color": h_color}}],
        )
        st.plotly_chart(fig_gauge, use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Crawlability Status ───────────────────────────────────────────────
    idx_count  = sum(1 for r in results if not r.get("indexability",{}).get("is_noindex",False))
    noindex_c  = total - idx_count
    redirect_c = sum(1 for r in results if r.get("redirect_count",0) > 0)
    amp_c      = sum(1 for r in results if r.get("technical_seo",{}).get("has_amp",False))
    paginated  = sum(1 for r in results if r.get("technical_seo",{}).get("has_pagination",False))
    schema_c   = sum(1 for r in results if r.get("advanced",{}).get("has_schema",False))

    st.markdown('<div class="section-header">🕷️ Crawlability & Indexability</div>', unsafe_allow_html=True)
    cr1, cr2, cr3, cr4, cr5 = st.columns(5)
    _cw_items = [
        (cr1, "✅ Indexable",    idx_count,  "#10B981"),
        (cr2, "🚫 Noindex",      noindex_c,  "#EF4444"),
        (cr3, "↪️ Has Redirect",  redirect_c, "#F97316"),
        (cr4, "📋 Has Schema",   schema_c,   "#3B82F6"),
        (cr5, "📄 AMP Pages",    amp_c,      "#8B5CF6"),
    ]
    for col, lbl, cnt, clr in _cw_items:
        with col:
            st.markdown(f"""
            <div style='background:var(--seo-card-bg,#F8FAFC);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                 border-radius:10px;padding:12px 10px;text-align:center'>
                <div style='font-size:1.5rem;font-weight:800;color:{clr}'>{cnt}</div>
                <div style='font-size:.72rem;color:var(--seo-muted,#64748B);margin-top:2px'>{lbl}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Quick Wins (high impact + low effort) ─────────────────────────────
    quick_wins = sorted(
        [i for i in all_issues if i.get("effort","") == "Low" and i.get("impact_score",0) >= 7],
        key=lambda x: x.get("impact_score", 0), reverse=True
    )[:6]
    if quick_wins:
        st.markdown('<div class="section-header">⚡ Quick Wins — High Impact, Low Effort</div>',
                    unsafe_allow_html=True)
        st.caption("Fix these first — maximum SEO gain for minimum time investment.")
        qw_cols = st.columns(2)
        for idx_qw, qw in enumerate(quick_wins):
            sev   = qw.get("severity","Low")
            imp   = qw.get("impact_score",0)
            sev_c = {"Critical":"#EF4444","High":"#F97316","Warning":"#F59E0B","Medium":"#EAB308","Low":"#3B82F6"}.get(sev,"#6B7280")
            with qw_cols[idx_qw % 2]:
                st.markdown(f"""
                <div class='qw-card'>
                    <div class='qw-number'>{idx_qw+1}</div>
                    <div class='qw-text'>
                        <div class='qw-title'>{qw.get("issue","")}</div>
                        <div class='qw-sub'>
                            <span style='color:{sev_c};font-weight:700'>{sev}</span>
                            &nbsp;·&nbsp; Impact: <b>{imp}/10</b>
                            &nbsp;·&nbsp; <span style='color:#10B981;font-weight:600'>Low Effort</span>
                        </div>
                        <div style='font-size:.75rem;color:var(--seo-info-text,#1D4ED8);margin-top:4px'>
                            ✅ {qw.get("recommendation","")}
                        </div>
                    </div>
                </div>""", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    # ── Duplicate Meta Detection ──────────────────────────────────────────
    if len(results) > 1:
        from modules.advanced_checks import detect_duplicate_metas
        dup = detect_duplicate_metas(results)
        st.session_state.dup_report = dup
        dt = dup.get("total_dup_titles",0)
        dd = dup.get("total_dup_descs",0)
        dh = dup.get("total_dup_h1s",0)
        if dt + dd + dh > 0:
            st.markdown('<div class="section-header">⚠️ Duplicate Content Alerts</div>',
                        unsafe_allow_html=True)
            da1, da2, da3 = st.columns(3)
            with da1:
                if dt:
                    st.error(f"🔴 **{dt}** duplicate meta title(s)")
            with da2:
                if dd:
                    st.warning(f"⚠️ **{dd}** duplicate meta description(s)")
            with da3:
                if dh:
                    st.warning(f"⚠️ **{dh}** duplicate H1(s)")

            with st.expander("View Duplicate Details"):
                if dup.get("duplicate_titles"):
                    st.markdown("**Duplicate Meta Titles:**")
                    for t, urls in list(dup["duplicate_titles"].items())[:5]:
                        st.markdown(f"- `{t[:80]}` → {len(urls)} pages")
                        for u in urls[:3]:
                            st.caption(f"  • {u}")
                if dup.get("duplicate_descriptions"):
                    st.markdown("**Duplicate Meta Descriptions:**")
                    for d, urls in list(dup["duplicate_descriptions"].items())[:5]:
                        st.markdown(f"- `{d[:80]}` → {len(urls)} pages")
            st.markdown("<br>", unsafe_allow_html=True)

    # ── Charts ────────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">📈 Analytics</div>', unsafe_allow_html=True)
    ch1, ch2 = st.columns(2)

    with ch1:
        dist = {
            "Excellent (90-100)":    sum(1 for s in scores if s >= 90),
            "Good (75-89)":          sum(1 for s in scores if 75 <= s < 90),
            "Needs Attention (50-74)": sum(1 for s in scores if 50 <= s < 75),
            "Critical (<50)":        sum(1 for s in scores if s < 50),
        }
        fig = px.pie(names=list(dist.keys()), values=list(dist.values()),
                     color_discrete_sequence=["#10B981","#3B82F6","#F59E0B","#EF4444"],
                     title="SEO Health Distribution")
        fig.update_layout(margin=dict(t=40,b=10,l=10,r=10), height=320)
        st.plotly_chart(fig, use_container_width=True)

    with ch2:
        sev_counts = {}
        for i in all_issues:
            s = i.get("severity","Other")
            sev_counts[s] = sev_counts.get(s,0) + 1
        fig2 = px.bar(x=list(sev_counts.keys()), y=list(sev_counts.values()),
                      color=list(sev_counts.keys()),
                      color_discrete_map={"Critical":"#EF4444","High":"#F97316",
                                          "Medium":"#EAB308","Warning":"#F59E0B","Low":"#3B82F6"},
                      title="Issue Severity Breakdown",
                      labels={"x":"Severity","y":"Count"})
        fig2.update_layout(showlegend=False, margin=dict(t=40,b=10,l=10,r=10), height=320)
        st.plotly_chart(fig2, use_container_width=True)

    ch3, ch4 = st.columns(2)
    with ch3:
        # Top Issues by Impact across all results
        from modules.scoring import get_top_issues_by_impact
        top_global = get_top_issues_by_impact(all_issues, 10)
        if top_global:
            top_df = pd.DataFrame([{
                "Issue": i.get("issue","")[:55],
                "Impact": i.get("impact_score",0),
                "Severity": i.get("severity","Low"),
            } for i in top_global])
            fig3 = px.bar(top_df, x="Impact", y="Issue", orientation="h",
                          color="Severity",
                          color_discrete_map={"Critical":"#EF4444","High":"#F97316",
                                              "Medium":"#EAB308","Warning":"#F59E0B","Low":"#3B82F6"},
                          title="Top 10 Issues by Impact Score")
            fig3.update_layout(showlegend=True, height=360, margin=dict(t=40,b=10,l=10,r=10))
            st.plotly_chart(fig3, use_container_width=True)

    with ch4:
        # Thematic grouping
        from modules.scoring import THEMES
        theme_counts = {}
        for iss in all_issues:
            cat = iss.get("category","")
            placed = False
            for theme, cats in THEMES.items():
                if any(c.lower() in cat.lower() for c in cats):
                    theme_counts[theme] = theme_counts.get(theme,0) + 1
                    placed = True
                    break
            if not placed:
                theme_counts["Other"] = theme_counts.get("Other",0) + 1
        if theme_counts:
            fig4 = px.bar(x=list(theme_counts.values()), y=list(theme_counts.keys()),
                          orientation="h", title="Issues by SEO Theme (SEMrush-style)",
                          color=list(theme_counts.values()),
                          color_continuous_scale="OrRd")
            fig4.update_layout(showlegend=False, height=360,
                               margin=dict(t=40,b=10,l=10,r=10), coloraxis_showscale=False)
            st.plotly_chart(fig4, use_container_width=True)

    ch5, ch6 = st.columns(2)
    with ch5:
        int_t = sum(r.get("internal_links",{}).get("total_links",0) for r in results)
        ext_t = sum(r.get("external_links",{}).get("total_links",0) for r in results)
        fig5 = go.Figure()
        fig5.add_trace(go.Bar(name="Internal Links", x=["Link Distribution"], y=[int_t], marker_color="#3B82F6"))
        fig5.add_trace(go.Bar(name="External Links", x=["Link Distribution"], y=[ext_t], marker_color="#8B5CF6"))
        fig5.update_layout(title="Internal vs External Links",
                           margin=dict(t=40,b=10,l=10,r=10), height=300, barmode="group")
        st.plotly_chart(fig5, use_container_width=True)

    with ch6:
        if total > 1:
            df_plot = pd.DataFrame([{
                "URL": r.get("url","")[-50:],
                "SEO Score": r.get("seo_score",0),
                "Word Count": r.get("content",{}).get("word_count",0),
                "Type": r.get("audit_type","general").title(),
                "Issues": len(r.get("all_issues",[])),
            } for r in results])
            fig6 = px.scatter(df_plot, x="Word Count", y="SEO Score", color="Type",
                              size="Issues", hover_data=["URL","Issues"],
                              title="SEO Score vs Word Count",
                              color_discrete_sequence=px.colors.qualitative.Set2)
            fig6.add_hline(y=75, line_dash="dot", line_color="#3B82F6",
                           annotation_text="Good (75)")
            fig6.add_hline(y=50, line_dash="dot", line_color="#EF4444",
                           annotation_text="Critical (50)")
            fig6.update_layout(height=300, margin=dict(t=40,b=10,l=10,r=10))
            st.plotly_chart(fig6, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
# New Audit
# ════════════════════════════════════════════════════════════════════════════

def page_new_audit():
    st.markdown("<h2 style='font-size:1.5rem;font-weight:700;color:var(--seo-heading,#0F172A)'>🚀 New Audit</h2>",
                unsafe_allow_html=True)

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
        psi_api_key    = ""
        if fetch_psi:
            psi_api_key = st.text_input(
                "PSI API Key (optional — leave blank for anonymous)",
                type="password",
                help="Get a free key at console.cloud.google.com → PageSpeed Insights API. Anonymous limit: ~100 req/day.",
            )
            st.caption("📡 Real Lighthouse scores will appear in the **Mobile Audit → Core Web Vitals** tab.")
        max_workers    = st.slider("Concurrent Workers", 2, 16, 6)
        if validate_links:
            st.caption("🔍 Status validation ON — links will show 200/301/403/404/999 etc.")
        st.markdown("---")

    atype_map = {"Auto-Detect":"auto","Course":"course","Blog":"blog","General":"general"}
    atype = atype_map[audit_type]

    from modules.auditor import audit_url, audit_urls_bulk

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
                spinner_msg = f"Auditing {single_url} …" + (" + PageSpeed Insights (15s)" if fetch_psi else "")
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
            sm_urls = extract_urls_from_sitemap(sm_file)
            if sm_urls:
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
    st.markdown("<h2 style='font-size:1.5rem;font-weight:700;color:var(--seo-heading,#0F172A)'>📋 Audit Results</h2>",
                unsafe_allow_html=True)
    results = st.session_state.audit_results
    if not results:
        st.info("No audit results yet. Run a **New Audit** first.")
        return

    df = build_results_df(results)

    with st.expander("🔽 Filters", expanded=False):
        fc1,fc2,fc3,fc4 = st.columns(4)
        with fc1: type_filter = st.multiselect("Page Type", df["Type"].unique().tolist(),
                                                default=df["Type"].unique().tolist())
        with fc2: score_min = st.slider("Min SEO Score", 0, 100, 0)
        with fc3: sev_filter = st.selectbox("Has Severity", ["Any","Critical","High","Medium"])
        with fc4: broken_only = st.checkbox("Has Broken Links")

    mask = df["Type"].isin(type_filter) & (df["SEO Score"] >= score_min)
    if sev_filter != "Any" and sev_filter in df.columns:
        mask &= df[sev_filter] > 0
    if broken_only:
        mask &= (df["Broken Int."] + df["Broken Ext."]) > 0

    df_f = df[mask].reset_index(drop=True)
    st.caption(f"Showing **{len(df_f)}** of {len(df)} URLs")

    def color_score(val):
        if val >= 90: return "background-color:#D1FAE5;color:#065F46;font-weight:600"
        if val >= 75: return "background-color:#DBEAFE;color:#1E40AF;font-weight:600"
        if val >= 50: return "background-color:#FEF3C7;color:#92400E;font-weight:600"
        return "background-color:#FEE2E2;color:#991B1B;font-weight:600"

    def color_red(val):
        return "color:#EF4444;font-weight:700" if (val and val > 0) else ""

    styled = (df_f.style
              .map(color_score, subset=["SEO Score"])
              .map(color_red, subset=["Critical","Broken Int.","Broken Ext."]))
    st.dataframe(styled, use_container_width=True, height=450)

    st.markdown("---")
    selected_url = st.selectbox("🔎 Open URL Detail",
        [r.get("url","") for r in results],
        index=st.session_state.selected_url_idx)
    if st.button("Open Detail View →", type="primary"):
        idx = next((i for i,r in enumerate(results) if r.get("url")==selected_url), 0)
        st.session_state.selected_url_idx = idx
        st.session_state.page = "URL Detail"
        st.rerun()

    if st.button("🗑️ Clear All Results", type="secondary"):
        st.session_state.audit_results  = []
        st.session_state.last_audit_date= None
        st.session_state.single_result  = None
        st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# URL Detail
# ════════════════════════════════════════════════════════════════════════════

def page_url_detail():
    results = st.session_state.audit_results
    if not results:
        st.info("No audit results yet.")
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

        def _cwv_col(label):
            if "Good" in (label or ""): return ("#D1FAE5", "#065F46")
            if "Needs" in (label or "") or "Low" in (label or ""): return ("#FEF3C7", "#92400E")
            return ("#FEE2E2", "#991B1B")

        wv1, wv2, wv3 = st.columns(3)
        for wcol, mname, mval in [
            (wv1, "TTFB (Time to First Byte)", _t.get("cwv_ttfb_estimate", "—")),
            (wv2, "LCP (Largest Contentful Paint)", _t.get("cwv_lcp_estimate", "—")),
            (wv3, "CLS Risk (Layout Shift)", _t.get("cwv_cls_risk", "—")),
        ]:
            bg, fg = _cwv_col(mval)
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
                            f"<tr><td style='padding:5px 10px;font-weight:600;color:#1E40AF;"
                            f"font-size:.78rem;white-space:nowrap'>{rk}</td>"
                            f"<td style='padding:5px 10px;font-size:.76rem;color:var(--seo-text,#374151);"
                            f"word-break:break-all'>{rv}</td></tr>"
                        )
                        shown.add(rk.lower())
                        break
            other_html = "".join(
                f"<tr><td style='padding:4px 10px;font-size:.74rem;color:var(--seo-muted,#64748B);"
                f"white-space:nowrap'>{rk}</td>"
                f"<td style='padding:4px 10px;font-size:.73rem;color:#475569;"
                f"word-break:break-all'>{rv}</td></tr>"
                for rk, rv in _raw_h.items() if rk.lower() not in shown
            )
            st.markdown(
                f"<div style='overflow-x:auto;border-radius:8px;border:1px solid var(--seo-border,rgba(148,163,184,.22))'>"
                f"<table style='width:100%;border-collapse:collapse;background:var(--seo-card-bg,#fff)'>"
                f"<thead style='background:var(--table-header-bg,rgba(241,245,249,.9))'><tr>"
                f"<th style='padding:7px 10px;text-align:left;font-size:.78rem;color:var(--seo-muted,#1E40AF)'>Header</th>"
                f"<th style='padding:7px 10px;text-align:left;font-size:.78rem;color:var(--seo-muted,#1E40AF)'>Value</th>"
                f"</tr></thead><tbody>{crit_html}"
                f"<tr><td colspan='2' style='padding:4px 10px;font-size:.7rem;color:#94A3B8;"
                f"background:var(--seo-card-bg,#F8FAFC)'>— Other headers —</td></tr>"
                f"{other_html}</tbody></table></div>",
                unsafe_allow_html=True,
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
            sbg = "#D1FAE5" if spresent else "#FEE2E2"
            sfg = "#065F46" if spresent else "#991B1B"
            sicon = "✅" if spresent else "❌"
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;padding:7px 12px;"
                f"background:{sbg};border-radius:7px;margin-bottom:5px'>"
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
                st.success("✅ AMP version detected")
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
                                    <span style='background:#1E3A5F;color:#93C5FD;padding:2px 8px;border-radius:4px;font-size:.72rem'>Impact: {imp}/10</span>
                                    <span style='background:#1E293B;color:#CBD5E1;padding:2px 8px;border-radius:4px;font-size:.72rem'>Effort: {eff}</span>
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
            render_link_table(il["links"], max_rows=150)
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
            render_link_table(el_["links"], max_rows=150)
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
                    <div style='font-size:.84rem;color:#1D4ED8;margin-top:6px'>✅ {iss.get("recommendation","")}</div>
                </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# Link Analysis
# ════════════════════════════════════════════════════════════════════════════

def page_link_analysis():
    st.markdown(
        "<h2 style='font-size:1.5rem;font-weight:700;color:var(--seo-heading,#0F172A)'>🔗 Link Analysis</h2>",
        unsafe_allow_html=True,
    )
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
    with tab_ov:
        st.markdown('<div class="section-header">🔵 Internal Links Summary</div>', unsafe_allow_html=True)
        ic = st.columns(8)
        _kv = [
            ("Total",      i_total,   "#3B82F6"),
            ("Unique URLs",i_unique,  "#6366F1"),
            ("Dofollow",   i_df,      "#10B981"),
            ("Nofollow",   i_nf,      "#F59E0B"),
            ("Broken",     i_broken,  "#EF4444"),
            ("Redirecting",i_redir,   "#F97316"),
            ("New Tab",    i_new_tab, "#8B5CF6"),
            ("Weak Anchor",i_weak,    "#F59E0B"),
        ]
        for col, (label, val, clr) in zip(ic, _kv):
            with col:
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                     border-radius:10px;padding:10px;text-align:center'>
                    <div style='font-size:1.4rem;font-weight:800;color:{clr}'>{val}</div>
                    <div style='font-size:.68rem;color:var(--seo-muted,#64748B);margin-top:2px'>{label}</div>
                </div>""", unsafe_allow_html=True)

        st.markdown('<div class="section-header" style="margin-top:20px">🟣 External Links Summary</div>',
                    unsafe_allow_html=True)
        ec = st.columns(8)
        _kv_e = [
            ("Total",      e_total,   "#7C3AED"),
            ("Domains",    e_unique,  "#6366F1"),
            ("Dofollow",   e_df,      "#10B981"),
            ("Nofollow",   e_nf,      "#F59E0B"),
            ("Broken",     e_broken,  "#EF4444"),
            ("Blocked",    e_blocked, "#8B5CF6"),
            ("No Security",e_no_sec,  "#F97316"),
            ("Weak Anchor",e_weak,    "#F59E0B"),
        ]
        for col, (label, val, clr) in zip(ec, _kv_e):
            with col:
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                     border-radius:10px;padding:10px;text-align:center'>
                    <div style='font-size:1.4rem;font-weight:800;color:{clr}'>{val}</div>
                    <div style='font-size:.68rem;color:var(--seo-muted,#64748B);margin-top:2px'>{label}</div>
                </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Link health donut charts side-by-side
        ov1, ov2, ov3 = st.columns(3)
        with ov1:
            i_ok  = i_total - i_broken - i_redir
            fig_i = go.Figure(go.Pie(
                labels=["OK", "Broken", "Redirecting", "Unknown"],
                values=[max(i_ok,0), i_broken, i_redir,
                        max(i_total - i_broken - i_redir, 0) if i_total and not (i_broken + i_redir) else 0],
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
                sev   = iss.get("severity","Low")
                sev_c = {"Critical":"#EF4444","High":"#F97316","Warning":"#F59E0B",
                          "Medium":"#EAB308","Low":"#3B82F6"}.get(sev,"#6B7280")
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#fff);border-left:4px solid {sev_c};
                     border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:6px;
                     border:1px solid var(--seo-border,rgba(148,163,184,.22))'>
                    <div style='font-weight:700;font-size:.85rem;color:var(--seo-heading,#0F172A)'>
                        {iss.get("issue","")}</div>
                    <div style='font-size:.75rem;color:var(--seo-info-text,#1D4ED8);margin-top:4px'>
                        ✅ {iss.get("recommendation","")}</div>
                    <div style='font-size:.72rem;color:var(--seo-muted,#64748B);margin-top:2px'>
                        <span style='color:{sev_c};font-weight:700'>{sev}</span>
                        &nbsp;·&nbsp; Impact: {iss.get("impact_score",0)}/10
                        &nbsp;·&nbsp; Effort: {iss.get("effort","—")}</div>
                </div>""", unsafe_allow_html=True)

    # ════════════════════════ TAB 2: INTERNAL LINKS ══════════════════════ #
    with tab_i:
        if i_broken:
            st.error(f"⚠️ {i_broken} broken internal link(s) detected — fix these immediately.")
        if i_redir:
            st.warning(f"↪️ {i_redir} internal link(s) redirect — update to final URLs.")
        if i_miss_no:
            st.warning(f"🔒 {i_miss_no} internal link(s) open in new tab without rel='noopener'.")

        # Tab behavior breakdown
        st.markdown('<div class="section-header">🖱️ Tab Behavior & Security</div>', unsafe_allow_html=True)
        tb1, tb2, tb3, tb4 = st.columns(4)
        with tb1:
            st.markdown(f"""
            <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                 border-radius:10px;padding:14px;text-align:center'>
                <div style='font-size:1.5rem;font-weight:800;color:#3B82F6'>{i_total - i_new_tab}</div>
                <div style='font-size:.75rem;color:var(--seo-muted,#64748B);margin-top:3px'>Same Tab</div>
                <div style='font-size:.68rem;color:var(--seo-muted,#64748B)'>target not _blank</div>
            </div>""", unsafe_allow_html=True)
        with tb2:
            st.markdown(f"""
            <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                 border-radius:10px;padding:14px;text-align:center'>
                <div style='font-size:1.5rem;font-weight:800;color:#8B5CF6'>{i_new_tab}</div>
                <div style='font-size:.75rem;color:var(--seo-muted,#64748B);margin-top:3px'>New Tab</div>
                <div style='font-size:.68rem;color:var(--seo-muted,#64748B)'>target="_blank"</div>
            </div>""", unsafe_allow_html=True)
        with tb3:
            sec_ok_i = i_new_tab - i_miss_no
            sec_clr  = "#10B981" if i_miss_no == 0 else "#EF4444"
            st.markdown(f"""
            <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                 border-radius:10px;padding:14px;text-align:center'>
                <div style='font-size:1.5rem;font-weight:800;color:{sec_clr}'>{i_miss_no}</div>
                <div style='font-size:.75rem;color:var(--seo-muted,#64748B);margin-top:3px'>Missing noopener</div>
                <div style='font-size:.68rem;color:var(--seo-muted,#64748B)'>security risk</div>
            </div>""", unsafe_allow_html=True)
        with tb4:
            st.markdown(f"""
            <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                 border-radius:10px;padding:14px;text-align:center'>
                <div style='font-size:1.5rem;font-weight:800;color:#10B981'>{i_new_tab - i_miss_no}</div>
                <div style='font-size:.75rem;color:var(--seo-muted,#64748B);margin-top:3px'>Secure New Tab</div>
                <div style='font-size:.68rem;color:var(--seo-muted,#64748B)'>has noopener</div>
            </div>""", unsafe_allow_html=True)

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
            render_link_table(all_int_links, show_source=True, source_label="Source Page", max_rows=300)
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

        # Security attributes breakdown
        st.markdown('<div class="section-header">🔒 Security Attributes Analysis</div>', unsafe_allow_html=True)
        sa1, sa2, sa3, sa4, sa5 = st.columns(5)
        e_same_tab = e_total - e_new_tab
        e_full_sec = e_new_tab - e_no_sec
        _sec_items = [
            (sa1, "Same Tab",       e_same_tab,  "#3B82F6", "no target=_blank"),
            (sa2, "New Tab",        e_new_tab,   "#8B5CF6", "target=_blank"),
            (sa3, "Has noopener",   e_full_sec,  "#10B981", "safe new tabs"),
            (sa4, "Missing noopener",e_miss_no,  "#F97316", "⚠️ fix these"),
            (sa5, "Missing both",   e_no_sec,    "#EF4444", "noopener+noreferrer"),
        ]
        for col, label, val, clr, sub in _sec_items:
            with col:
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                     border-radius:10px;padding:12px;text-align:center'>
                    <div style='font-size:1.4rem;font-weight:800;color:{clr}'>{val}</div>
                    <div style='font-size:.73rem;color:var(--seo-muted,#64748B);margin-top:2px'>{label}</div>
                    <div style='font-size:.65rem;color:var(--seo-muted,#64748B)'>{sub}</div>
                </div>""", unsafe_allow_html=True)

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
            render_link_table(all_ext_links, show_source=True, source_label="Source Page", max_rows=300)
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
                sev_c = {"Critical":"#EF4444","High":"#F97316","Medium":"#F59E0B","Low":"#3B82F6"}.get(sev,"#6B7280")
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
# Mobile Audit Page
# ════════════════════════════════════════════════════════════════════════════

def page_mobile_audit():
    st.markdown(
        "<h2 style='font-size:1.5rem;font-weight:700;color:var(--seo-heading,#0F172A)'>📱 Mobile SEO Audit</h2>",
        unsafe_allow_html=True,
    )
    results = st.session_state.audit_results
    if not results:
        _no_data_info(); return

    # ── Overview table across all URLs ───────────────────────────────────
    st.markdown('<div class="section-header">📊 Mobile Audit Overview — All URLs</div>',
                unsafe_allow_html=True)
    rows = []
    for r in results:
        ma = r.get("mobile_audit", {})
        rows.append({
            "URL":              r.get("url","")[-70:],
            "Mobile Friendly":  "✅ Yes" if ma.get("is_mobile_friendly") else "❌ No",
            "Viewport":         "✅" if ma.get("summary",{}).get("viewport_ok") else "❌",
            "Perf Score":       ma.get("cwv",{}).get("perf_score", "—"),
            "UX Issues":        len(ma.get("issues",[])),
            "Passed Checks":    f"{ma.get('passed_checks',0)}/{ma.get('total_checks',0)}",
            "Mobile Score":     f"{ma.get('mobile_score',0)}%",
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

    # KPI strip
    k1, k2, k3, k4, k5 = st.columns(5)
    _mob_kpis = [
        (k1, "Mobile Score",    f"{ma.get('mobile_score',0)}%",
             "#10B981" if ma.get("mobile_score",0) >= 80 else "#F59E0B" if ma.get("mobile_score",0) >= 60 else "#EF4444"),
        (k2, "Checks Passed",   f"{ma.get('passed_checks',0)}/{ma.get('total_checks',0)}", "#3B82F6"),
        (k3, "Issues Found",    len(ma.get("issues",[])),   "#F97316"),
        (k4, "Perf Score",      ma.get("cwv",{}).get("perf_score","—"), "#6366F1"),
        (k5, "Mobile Friendly", "✅ Yes" if ma.get("is_mobile_friendly") else "❌ No",
             "#10B981" if ma.get("is_mobile_friendly") else "#EF4444"),
    ]
    for col, lbl, val, clr in _mob_kpis:
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
        st.markdown('<div class="section-header">⚡ Core Web Vitals Estimates</div>', unsafe_allow_html=True)
        st.caption("These are heuristic estimates from HTML/response analysis — not Lighthouse measurements. Use Google PageSpeed Insights for definitive scores.")
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
                sev   = iss.get("severity","Low")
                sev_c = {"Critical":"#EF4444","High":"#F97316","Warning":"#F59E0B",
                          "Medium":"#EAB308","Low":"#3B82F6"}.get(sev,"#6B7280")
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#fff);border-left:5px solid {sev_c};
                     border-radius:0 10px 10px 0;padding:12px 16px;margin-bottom:8px;
                     border:1px solid var(--seo-border,rgba(148,163,184,.22))'>
                    <div style='display:flex;align-items:center;gap:8px;margin-bottom:4px'>
                        <span style='background:{sev_c};color:white;padding:2px 10px;
                              border-radius:999px;font-size:.7rem;font-weight:700'>{sev}</span>
                        <span style='font-weight:700;font-size:.85rem;color:var(--seo-heading,#0F172A)'>
                            {iss.get("issue","")}</span>
                    </div>
                    <div style='font-size:.78rem;color:var(--seo-info-text,#1D4ED8);margin-top:4px'>
                        ✅ {iss.get("recommendation","")}</div>
                    <div style='font-size:.72rem;color:var(--seo-muted,#64748B);margin-top:3px'>
                        Impact: {iss.get("impact_score",0)}/10 &nbsp;·&nbsp; Effort: {iss.get("effort","—")}
                    </div>
                </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# Image SEO Page
# ════════════════════════════════════════════════════════════════════════════

def page_image_seo():
    st.markdown(
        "<h2 style='font-size:1.5rem;font-weight:700;color:var(--seo-heading,#0F172A)'>🖼️ Image SEO Audit</h2>",
        unsafe_allow_html=True,
    )
    results = st.session_state.audit_results
    if not results:
        _no_data_info(); return

    # ── Overview across all URLs ──────────────────────────────────────────
    st.markdown('<div class="section-header">📊 Image SEO Overview — All URLs</div>',
                unsafe_allow_html=True)
    ov_rows = []
    for r in results:
        im = r.get("image_detail", {})
        ov_rows.append({
            "URL":           r.get("url","")[-70:],
            "Total Images":  im.get("total",0),
            "Missing Alt":   im.get("missing_alt",0),
            "Empty Alt":     im.get("empty_alt",0),
            "No Lazy Load":  im.get("no_lazy",0),
            "No Dimensions": im.get("no_dimensions",0),
            "Non-WebP":      im.get("non_webp_jpg_png",0),
            "Bad Naming":    im.get("bad_naming",0),
        })
    st.dataframe(pd.DataFrame(ov_rows), use_container_width=True, hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── URL selector ──────────────────────────────────────────────────────
    urls = [r.get("url","") for r in results]
    sel  = st.selectbox("Select URL for detailed analysis", range(len(urls)),
                        format_func=lambda i: urls[i][-90:], key="img_url_sel")
    r    = results[sel]
    im   = r.get("image_detail", {})

    if not im:
        st.warning("Image audit data not available. Please re-run the audit.")
        return

    images = im.get("images", [])

    # KPI strip
    kc = st.columns(7)
    _img_kpis = [
        (kc[0], "Total Images",    im.get("total",0),          "#3B82F6"),
        (kc[1], "Missing Alt",     im.get("missing_alt",0),    "#EF4444"),
        (kc[2], "Empty Alt",       im.get("empty_alt",0),      "#F97316"),
        (kc[3], "Generic Alt",     im.get("generic_alt",0),    "#F59E0B"),
        (kc[4], "No Lazy Load",    im.get("no_lazy",0),        "#8B5CF6"),
        (kc[5], "No Dimensions",   im.get("no_dimensions",0),  "#F97316"),
        (kc[6], "Non-WebP (PNG/JPG)", im.get("non_webp_jpg_png",0), "#06B6D4"),
    ]
    for col, lbl, val, clr in _img_kpis:
        with col:
            st.markdown(f"""
            <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                 border-radius:10px;padding:12px;text-align:center'>
                <div style='font-size:1.3rem;font-weight:800;color:{clr}'>{val}</div>
                <div style='font-size:.65rem;color:var(--seo-muted,#64748B);margin-top:2px'>{lbl}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    tab_table, tab_fmt, tab_issues = st.tabs(["📋 Image Table", "📊 Format Analysis", "⚠️ Issues"])

    # ── Tab: Image Table ─────────────────────────────────────────────────
    with tab_table:
        st.markdown('<div class="section-header">📋 All Images Found</div>', unsafe_allow_html=True)
        if not images:
            st.info("No images found on this page.")
        else:
            # Filter controls
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                f_alt = st.selectbox("Filter by Alt Status",
                    ["All","missing","empty","generic","keyword_stuffed","ok"], key="img_f_alt")
            with fc2:
                f_lazy = st.selectbox("Filter by Lazy Load",
                    ["All","Has lazy","Missing lazy"], key="img_f_lazy")
            with fc3:
                f_fmt = st.selectbox("Filter by Format",
                    ["All","JPEG","PNG","WebP","SVG","GIF","AVIF","Unknown"], key="img_f_fmt")

            filtered = images
            if f_alt != "All":
                filtered = [i for i in filtered if i.get("alt_status") == f_alt]
            if f_lazy == "Has lazy":
                filtered = [i for i in filtered if i.get("has_lazy")]
            elif f_lazy == "Missing lazy":
                filtered = [i for i in filtered if not i.get("has_lazy")]
            if f_fmt != "All":
                filtered = [i for i in filtered if i.get("format_label") == f_fmt]

            st.caption(f"Showing **{len(filtered)}** of {len(images)} images")

            alt_status_badge = {
                "missing":        "<span style='background:#FEE2E2;color:#991B1B;padding:1px 7px;border-radius:4px;font-size:.7rem'>Missing</span>",
                "empty":          "<span style='background:#FED7AA;color:#9A3412;padding:1px 7px;border-radius:4px;font-size:.7rem'>Empty</span>",
                "generic":        "<span style='background:#FEF3C7;color:#92400E;padding:1px 7px;border-radius:4px;font-size:.7rem'>Generic</span>",
                "keyword_stuffed":"<span style='background:#EDE9FE;color:#5B21B6;padding:1px 7px;border-radius:4px;font-size:.7rem'>Stuffed</span>",
                "ok":             "<span style='background:#D1FAE5;color:#065F46;padding:1px 7px;border-radius:4px;font-size:.7rem'>OK</span>",
            }
            fmt_color = {"JPEG":"#3B82F6","PNG":"#8B5CF6","WebP":"#10B981","SVG":"#F59E0B",
                          "GIF":"#EF4444","AVIF":"#06B6D4","Unknown":"#94A3B8"}

            rows_html = ""
            for img in filtered[:200]:
                url_short = img.get("url","")[-60:] or "—"
                name      = img.get("name","—")[:30]
                fmt       = img.get("format_label","Unknown")
                fmt_c     = fmt_color.get(fmt,"#94A3B8")
                alt_st    = img.get("alt_status","missing")
                alt_badge = alt_status_badge.get(alt_st,"")
                alt_txt   = (img.get("alt_text") or "")[:50]
                lazy_ic   = "✅" if img.get("has_lazy") else "❌"
                dims      = f'{img.get("width","?")}×{img.get("height","?")}' if img.get("has_dimensions") else "—"
                srcset_ic = "✅" if img.get("has_srcset") else "—"
                size_lbl  = img.get("file_size_label","Unknown")
                name_q    = "✅" if img.get("naming_quality") == "good" else "⚠️"

                rows_html += f"""
                <tr style='border-bottom:1px solid var(--table-row-border,rgba(148,163,184,.12))'>
                    <td style='padding:7px 8px;font-size:.73rem;color:var(--seo-info-text,#1D4ED8);
                         max-width:200px;word-break:break-all'>{url_short}</td>
                    <td style='padding:7px 8px;font-size:.73rem;color:var(--seo-muted,#64748B)'>{name} {name_q}</td>
                    <td style='padding:7px 8px;text-align:center'>
                        <span style='color:{fmt_c};font-weight:700;font-size:.75rem'>{fmt}</span></td>
                    <td style='padding:7px 8px;font-size:.72rem;color:var(--seo-muted,#64748B)'>{size_lbl}</td>
                    <td style='padding:7px 8px;font-size:.72rem;color:var(--seo-muted,#64748B)'>{dims}</td>
                    <td style='padding:7px 8px'>{alt_badge}
                        <div style='font-size:.68rem;color:var(--seo-muted,#64748B);margin-top:2px'>{alt_txt}</div></td>
                    <td style='padding:7px 8px;text-align:center;font-size:.8rem'>{lazy_ic}</td>
                    <td style='padding:7px 8px;text-align:center;font-size:.8rem'>{srcset_ic}</td>
                </tr>"""

            st.markdown(f"""
            <div style='overflow-x:auto;border-radius:10px;border:1px solid var(--seo-border,rgba(148,163,184,.22))'>
            <table style='width:100%;border-collapse:collapse;background:var(--seo-card-bg,#fff)'>
                <thead style='background:var(--table-header-bg,rgba(241,245,249,.9))'>
                <tr>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:left'>Image URL</th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:left'>Name</th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:center'>Format</th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B)'>File Size</th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B)'>Dimensions</th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B)'>Alt Text</th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:center'>Lazy</th>
                    <th style='padding:8px;font-size:.72rem;color:var(--seo-muted,#64748B);text-align:center'>srcset</th>
                </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table></div>""", unsafe_allow_html=True)

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
                fig_fmt.update_layout(showlegend=False, height=280,
                                      margin=dict(t=10,b=5,l=5,r=5),
                                      paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_fmt, use_container_width=True)
            with fc2:
                st.markdown('<div class="section-header">💡 Format Upgrade Opportunities</div>',
                            unsafe_allow_html=True)
                webp_opps = im.get("non_webp_jpg_png", 0)
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                     border-radius:10px;padding:16px'>
                    <div style='font-size:.85rem;color:var(--seo-text,#374151);margin-bottom:10px'>
                        <b>{webp_opps}</b> image(s) in legacy format (PNG/JPEG) could be converted to WebP.
                    </div>
                    <div style='font-size:.78rem;color:var(--seo-muted,#64748B)'>
                        <b>WebP</b> offers 25–35% smaller file sizes than JPEG and 26% smaller than PNG at equivalent quality.<br><br>
                        <b>AVIF</b> offers even better compression (up to 50% smaller than JPEG) and is supported in all modern browsers.
                    </div>
                    <div style='margin-top:10px'>
                        <span style='background:#D1FAE5;color:#065F46;padding:3px 10px;border-radius:999px;font-size:.75rem;font-weight:600'>
                            ✅ Already WebP: {fmts.get("WebP",0)}</span>
                        &nbsp;
                        <span style='background:#FEF3C7;color:#92400E;padding:3px 10px;border-radius:999px;font-size:.75rem;font-weight:600'>
                            ⚠️ Needs conversion: {webp_opps}</span>
                    </div>
                </div>""", unsafe_allow_html=True)

                # Alt text quality pie
                st.markdown('<div class="section-header" style="margin-top:14px">🏷️ Alt Text Quality</div>',
                            unsafe_allow_html=True)
                alt_counts = {
                    "OK":       sum(1 for i in images if i.get("alt_status")=="ok"),
                    "Missing":  im.get("missing_alt",0),
                    "Empty":    im.get("empty_alt",0),
                    "Generic":  im.get("generic_alt",0),
                    "Stuffed":  im.get("keyword_stuffed_alt",0),
                }
                fig_alt = go.Figure(go.Pie(
                    labels=list(alt_counts.keys()), values=list(alt_counts.values()), hole=0.5,
                    marker_colors=["#10B981","#EF4444","#F97316","#F59E0B","#8B5CF6"],
                ))
                fig_alt.update_traces(textinfo="label+value", textfont_size=11)
                fig_alt.update_layout(showlegend=False, height=220,
                                      margin=dict(t=5,b=5,l=5,r=5),
                                      paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_alt, use_container_width=True)

    # ── Tab: Issues ───────────────────────────────────────────────────────
    with tab_issues:
        img_issues = im.get("issues", [])
        if not img_issues:
            st.success("✅ No significant image SEO issues found.")
        else:
            sev_order = {"Critical":0,"High":1,"Warning":2,"Medium":3,"Low":4}
            for iss in sorted(img_issues, key=lambda x: sev_order.get(x.get("severity","Low"),5)):
                sev   = iss.get("severity","Low")
                sev_c = {"Critical":"#EF4444","High":"#F97316","Warning":"#F59E0B",
                          "Medium":"#EAB308","Low":"#3B82F6"}.get(sev,"#6B7280")
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#fff);border-left:5px solid {sev_c};
                     border-radius:0 10px 10px 0;padding:12px 16px;margin-bottom:8px;
                     border:1px solid var(--seo-border,rgba(148,163,184,.22))'>
                    <div style='display:flex;align-items:center;gap:8px;margin-bottom:4px'>
                        <span style='background:{sev_c};color:white;padding:2px 10px;border-radius:999px;
                              font-size:.7rem;font-weight:700'>{sev}</span>
                        <span style='font-weight:700;font-size:.85rem;color:var(--seo-heading,#0F172A)'>
                            {iss.get("issue","")}</span>
                    </div>
                    <div style='font-size:.78rem;color:var(--seo-info-text,#1D4ED8);margin-top:4px'>
                        ✅ {iss.get("recommendation","")}</div>
                    <div style='font-size:.72rem;color:var(--seo-muted,#64748B);margin-top:3px'>
                        Impact: {iss.get("impact_score",0)}/10 &nbsp;·&nbsp; Effort: {iss.get("effort","—")}
                    </div>
                </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# Heading Analysis Page
# ════════════════════════════════════════════════════════════════════════════

def page_heading_analysis():
    st.markdown(
        "<h2 style='font-size:1.5rem;font-weight:700;color:var(--seo-heading,#0F172A)'>📝 Heading Structure Audit</h2>",
        unsafe_allow_html=True,
    )
    results = st.session_state.audit_results
    if not results:
        _no_data_info(); return

    # ── Overview table across all URLs ───────────────────────────────────
    st.markdown('<div class="section-header">📊 Heading Audit Overview — All URLs</div>',
                unsafe_allow_html=True)
    ov_rows = []
    for r in results:
        hd = r.get("heading_detail", {})
        c  = hd.get("counts", {})
        ov_rows.append({
            "URL":            r.get("url","")[-70:],
            "H1": c.get("h1",0), "H2": c.get("h2",0), "H3": c.get("h3",0),
            "H4": c.get("h4",0), "H5": c.get("h5",0), "H6": c.get("h6",0),
            "Total":          hd.get("total_headings",0),
            "Sequence Errors":len(hd.get("sequence_violations",[])),
            "Empty":          len(hd.get("empty_headings",[])),
            "Issues":         len(hd.get("issues",[])),
        })
    st.dataframe(pd.DataFrame(ov_rows), use_container_width=True, hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Per-URL deep dive ─────────────────────────────────────────────────
    urls = [r.get("url","") for r in results]
    sel  = st.selectbox("Select URL for detailed analysis", range(len(urls)),
                        format_func=lambda i: urls[i][-90:], key="hdg_url_sel")
    r    = results[sel]
    hd   = r.get("heading_detail", {})

    if not hd:
        st.warning("Heading audit data not available. Please re-run the audit.")
        return

    counts = hd.get("counts", {})
    headings = hd.get("headings", [])

    # KPI strip
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    _hd_kpis = [
        (k1,"H1",counts.get("h1",0), "#1E40AF", counts.get("h1",0)==1),
        (k2,"H2",counts.get("h2",0), "#047857", True),
        (k3,"H3",counts.get("h3",0), "#92400E", True),
        (k4,"Sequence Errors",len(hd.get("sequence_violations",[])), "#EF4444", len(hd.get("sequence_violations",[]))==0),
        (k5,"Empty Headings",len(hd.get("empty_headings",[])), "#F97316", len(hd.get("empty_headings",[]))==0),
        (k6,"Issues",len(hd.get("issues",[])), "#8B5CF6", len(hd.get("issues",[]))==0),
    ]
    for col, lbl, val, clr, is_ok in _hd_kpis:
        display_clr = "#10B981" if (is_ok and val >= 0) else clr
        with col:
            st.markdown(f"""
            <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                 border-radius:10px;padding:14px;text-align:center'>
                <div style='font-size:1.5rem;font-weight:800;color:{display_clr}'>{val}</div>
                <div style='font-size:.72rem;color:var(--seo-muted,#64748B);margin-top:3px'>{lbl}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    tab_tree, tab_table, tab_issues = st.tabs(["🌳 Hierarchy Tree", "📋 Full Heading List", "⚠️ Issues"])

    # ── Tab: Tree ─────────────────────────────────────────────────────────
    with tab_tree:
        st.markdown('<div class="section-header">🌳 Heading Hierarchy Visualization</div>',
                    unsafe_allow_html=True)

        # H1 highlighted at top
        h1_text = hd.get("h1_text","")
        if h1_text:
            st.markdown(f"""
            <div style='background:rgba(30,64,175,.08);border:2px solid #1E40AF;border-radius:10px;
                 padding:14px 18px;margin-bottom:12px'>
                <span style='font-size:.72rem;font-weight:700;color:#1E40AF;text-transform:uppercase;
                      letter-spacing:.06em'>H1 — Primary Heading</span>
                <div style='font-size:1.05rem;font-weight:700;color:var(--seo-heading,#0F172A);margin-top:4px'>
                    {h1_text[:120]}</div>
            </div>""", unsafe_allow_html=True)
        else:
            st.error("❌ No H1 tag found on this page.")

        # Visual tree
        tree_html = hd.get("tree_html","")
        if tree_html:
            st.markdown(f"""
            <div style='background:var(--seo-card-bg,#fff);border:1px solid var(--seo-border,rgba(148,163,184,.22));
                 border-radius:10px;padding:16px 20px;font-family:monospace;font-size:.82rem;
                 line-height:1.8;overflow-x:auto'>{tree_html}</div>""",
                unsafe_allow_html=True)

        # Sequence violations
        violations = hd.get("sequence_violations", [])
        if violations:
            st.markdown('<div class="section-header" style="margin-top:16px">⚠️ Sequence Violations</div>',
                        unsafe_allow_html=True)
            for v in violations:
                st.markdown(f"""
                <div style='background:var(--sev-warning-bg,rgba(245,158,11,.10));border-left:4px solid #F59E0B;
                     border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:6px'>
                    <b>Position {v.get("position","?")}:</b>
                    H{v.get("from_level","?")} → H{v.get("to_level","?")} skips a level &nbsp;
                    <span style='color:var(--seo-muted,#64748B);font-size:.8rem'>
                        "{(v.get("heading_text") or "")[:70]}"</span><br>
                    <span style='font-size:.75rem;color:var(--seo-info-text,#1D4ED8)'>
                        ✅ Add an H{v.get("from_level",1)+1} heading before this H{v.get("to_level","?")}
                        to maintain correct document structure.</span>
                </div>""", unsafe_allow_html=True)
        else:
            st.success("✅ No heading sequence violations found — heading hierarchy is correct.")

        # Keyword coverage
        kw = hd.get("keyword_coverage", {})
        if kw:
            st.markdown('<div class="section-header" style="margin-top:16px">🔍 Keyword Coverage</div>',
                        unsafe_allow_html=True)
            kc1, kc2 = st.columns(2)
            with kc1:
                found_in = kw.get("found_in", [])
                if found_in:
                    st.success(f"✅ Title keywords found in headings: **{', '.join(found_in)}**")
                else:
                    st.warning("⚠️ No title keywords detected in H1/H2 headings.")
            with kc2:
                missing_kw = kw.get("missing_from_headings", [])
                if missing_kw:
                    st.info(f"💡 Consider working these keywords into your H2s: **{', '.join(missing_kw[:5])}**")

        # Duplicates
        dupes = hd.get("duplicate_headings", {})
        has_dupes = any(dupes.values())
        if has_dupes:
            st.markdown('<div class="section-header" style="margin-top:16px">🔁 Duplicate Headings</div>',
                        unsafe_allow_html=True)
            for level, dup_list in dupes.items():
                if dup_list:
                    for dup in dup_list:
                        st.warning(f"**{level.upper()}** duplicated heading: \"{str(dup)[:80]}\"")

    # ── Tab: Full heading list ─────────────────────────────────────────────
    with tab_table:
        st.markdown('<div class="section-header">📋 All Headings</div>', unsafe_allow_html=True)
        if not headings:
            st.info("No headings found.")
        else:
            level_color = {1:"#1E40AF",2:"#047857",3:"#92400E",4:"#6B21A8",5:"#9D174D",6:"#374151"}
            rows_html = ""
            for h in headings:
                lv    = h.get("level",1)
                clr   = level_color.get(lv,"#374151")
                txt   = h.get("text","")[:100] or "<em style='color:var(--seo-muted,#64748B)'>[Empty]</em>"
                pos   = h.get("position","")
                empty = "⚠️ Empty" if h.get("is_empty") else ""
                lg    = h.get("length",0)
                rows_html += f"""
                <tr style='border-bottom:1px solid var(--table-row-border,rgba(148,163,184,.12))'>
                    <td style='padding:8px 10px;text-align:center'>
                        <span style='background:{clr};color:white;padding:3px 10px;border-radius:6px;
                              font-size:.75rem;font-weight:700'>H{lv}</span></td>
                    <td style='padding:8px 10px;font-size:.83rem;color:var(--seo-text,#374151)'>{txt} {empty}</td>
                    <td style='padding:8px 10px;text-align:center;font-size:.75rem;color:var(--seo-muted,#64748B)'>{pos}</td>
                    <td style='padding:8px 10px;text-align:center;font-size:.75rem;color:var(--seo-muted,#64748B)'>{lg} chars</td>
                </tr>"""
            st.markdown(f"""
            <div style='overflow-x:auto;border-radius:10px;border:1px solid var(--seo-border,rgba(148,163,184,.22))'>
            <table style='width:100%;border-collapse:collapse;background:var(--seo-card-bg,#fff)'>
                <thead style='background:var(--table-header-bg,rgba(241,245,249,.9))'>
                <tr>
                    <th style='padding:8px 10px;font-size:.75rem;color:var(--seo-muted,#64748B);text-align:center;width:70px'>Level</th>
                    <th style='padding:8px 10px;font-size:.75rem;color:var(--seo-muted,#64748B);text-align:left'>Heading Text</th>
                    <th style='padding:8px 10px;font-size:.75rem;color:var(--seo-muted,#64748B);text-align:center;width:80px'>Position</th>
                    <th style='padding:8px 10px;font-size:.75rem;color:var(--seo-muted,#64748B);text-align:center;width:90px'>Length</th>
                </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table></div>""", unsafe_allow_html=True)

    # ── Tab: Issues ───────────────────────────────────────────────────────
    with tab_issues:
        hdg_issues = hd.get("issues", [])
        if not hdg_issues:
            st.success("✅ No heading structure issues found.")
        else:
            sev_order = {"Critical":0,"High":1,"Warning":2,"Medium":3,"Low":4}
            for iss in sorted(hdg_issues, key=lambda x: sev_order.get(x.get("severity","Low"),5)):
                sev   = iss.get("severity","Low")
                sev_c = {"Critical":"#EF4444","High":"#F97316","Warning":"#F59E0B",
                          "Medium":"#EAB308","Low":"#3B82F6"}.get(sev,"#6B7280")
                st.markdown(f"""
                <div style='background:var(--seo-card-bg,#fff);border-left:5px solid {sev_c};
                     border-radius:0 10px 10px 0;padding:12px 16px;margin-bottom:8px;
                     border:1px solid var(--seo-border,rgba(148,163,184,.22))'>
                    <div style='display:flex;align-items:center;gap:8px;margin-bottom:4px'>
                        <span style='background:{sev_c};color:white;padding:2px 10px;border-radius:999px;
                              font-size:.7rem;font-weight:700'>{sev}</span>
                        <span style='font-weight:700;font-size:.85rem;color:var(--seo-heading,#0F172A)'>
                            {iss.get("issue","")}</span>
                    </div>
                    <div style='font-size:.78rem;color:var(--seo-info-text,#1D4ED8);margin-top:4px'>
                        ✅ {iss.get("recommendation","")}</div>
                    <div style='font-size:.72rem;color:var(--seo-muted,#64748B);margin-top:3px'>
                        Impact: {iss.get("impact_score",0)}/10 &nbsp;·&nbsp; Effort: {iss.get("effort","—")}
                    </div>
                </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# Export
# ════════════════════════════════════════════════════════════════════════════

def page_export():
    st.markdown("<h2 style='font-size:1.5rem;font-weight:700;color:var(--seo-heading,#0F172A)'>📤 Export Reports</h2>",
                unsafe_allow_html=True)
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
    st.markdown("""
    <div style='text-align:center;padding:16px 0 8px'>
        <div style='font-size:2rem' role='img' aria-label='Search icon'>🔍</div>
        <div style='font-size:1rem;font-weight:700;color:#F1F5F9'>SEO Audit Dashboard</div>
        <div style='font-size:.72rem;color:#94A3B8'>Enterprise SEO Platform</div>
    </div>""", unsafe_allow_html=True)
    st.markdown("---")

    page = st.radio("Navigation", [
        "📊 Dashboard Overview",
        "🚀 New Audit",
        "📋 Audit Results",
        "🔎 URL Detail",
        "🔗 Link Analysis",
        "📱 Mobile Audit",
        "🖼️ Image SEO",
        "📝 Heading Analysis",
        "📤 Export Reports",
    ], label_visibility="collapsed")

    if "page" in st.session_state and st.session_state.page == "URL Detail":
        page = "🔎 URL Detail"
        del st.session_state["page"]

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


# ════════════════════════════════════════════════════════════════════════════
# Router
# ════════════════════════════════════════════════════════════════════════════

if   page == "📊 Dashboard Overview": page_dashboard()
elif page == "🚀 New Audit":          page_new_audit()
elif page == "📋 Audit Results":      page_results()
elif page == "🔎 URL Detail":         page_url_detail()
elif page == "🔗 Link Analysis":      page_link_analysis()
elif page == "📱 Mobile Audit":       page_mobile_audit()
elif page == "🖼️ Image SEO":          page_image_seo()
elif page == "📝 Heading Analysis":   page_heading_analysis()
elif page == "📤 Export Reports":     page_export()

"""SEO Technical Audit Dashboard – Main Streamlit Application."""

import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Page config (must be first Streamlit call) ─────────────────────────────
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

# ── Session state init ─────────────────────────────────────────────────────
if "audit_results" not in st.session_state:
    st.session_state.audit_results = []
if "last_audit_date" not in st.session_state:
    st.session_state.last_audit_date = None
if "selected_url_idx" not in st.session_state:
    st.session_state.selected_url_idx = 0


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════

def _score_color(s):
    if s >= 90:
        return "#10B981"
    elif s >= 75:
        return "#3B82F6"
    elif s >= 50:
        return "#F59E0B"
    return "#EF4444"


def _score_label(s):
    if s >= 90:
        return "Excellent"
    elif s >= 75:
        return "Good"
    elif s >= 50:
        return "Needs Attention"
    return "Critical"


def _score_class(s):
    if s >= 90:
        return "score-excellent"
    elif s >= 75:
        return "score-good"
    elif s >= 50:
        return "score-needs"
    return "score-critical"


def _sev_class(sev):
    return f"sev-{sev.lower()}"


def metric_card(label, value, color="#3B82F6", delta=None):
    delta_html = f'<div class="metric-delta" style="color:{color}">{delta}</div>' if delta else ""
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-value" style="color:{color}">{value}</div>
            <div class="metric-label">{label}</div>
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def extract_urls_from_csv_xlsx(uploaded_file):
    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        url_cols = [c for c in df.columns if any(
            kw in c.lower() for kw in ["url", "link", "href", "address", "page"]
        )]
        col = url_cols[0] if url_cols else df.columns[0]
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
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
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
            "URL": r.get("url", ""),
            "Type": r.get("audit_type", "general").title(),
            "Status": r.get("status_code", 0),
            "SEO Score": r.get("seo_score", 0),
            "Score Label": _score_label(r.get("seo_score", 0)),
            "Total Issues": len(issues),
            "Critical": sum(1 for i in issues if i.get("severity") == "Critical"),
            "High": sum(1 for i in issues if i.get("severity") == "High"),
            "Word Count": r.get("content", {}).get("word_count", 0),
            "Int. Links": r.get("internal_links", {}).get("total_links", 0),
            "Ext. Links": r.get("external_links", {}).get("total_links", 0),
            "Broken Int.": r.get("internal_links", {}).get("broken_count", 0),
            "Broken Ext.": r.get("external_links", {}).get("broken_count", 0),
            "Indexable": r.get("indexability", {}).get("is_indexable", True),
            "Fetch Error": r.get("fetch_error") or "",
        })
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════════════════
# Pages
# ════════════════════════════════════════════════════════════════════════════

def page_dashboard():
    results = st.session_state.audit_results
    last_date = st.session_state.last_audit_date

    st.markdown(
        """
        <h1 style='font-size:1.8rem;font-weight:800;color:#0F172A;margin-bottom:2px'>
        🔍 SEO Technical Audit Dashboard</h1>
        <p style='color:#64748B;margin-bottom:20px'>
        Comprehensive SEO Audit for Courses and Blogs</p>
        """,
        unsafe_allow_html=True,
    )

    col_info1, col_info2 = st.columns(2)
    with col_info1:
        if last_date:
            st.caption(f"**Last Audit:** {last_date}")
    with col_info2:
        st.caption(f"**Total URLs Audited:** {len(results)}")

    if not results:
        st.markdown(
            """
            <div class="info-box">
            👆 No audit data yet. Go to <b>New Audit</b> in the sidebar to get started.
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    total = len(results)
    scores = [r.get("seo_score", 0) for r in results]
    avg_score = round(sum(scores) / total, 1) if total else 0
    healthy = sum(1 for s in scores if s >= 75)
    critical_urls = sum(1 for s in scores if s < 50)
    warnings = sum(1 for s in scores if 50 <= s < 75)
    all_issues = [i for r in results for i in r.get("all_issues", [])]
    critical_issues = sum(1 for i in all_issues if i.get("severity") == "Critical")
    broken_links = (
        sum(r.get("internal_links", {}).get("broken_count", 0) for r in results) +
        sum(r.get("external_links", {}).get("broken_count", 0) for r in results)
    )
    missing_meta = sum(
        1 for r in results
        if not r.get("metadata", {}).get("has_title") or not r.get("metadata", {}).get("has_description")
    )
    avg_wc = round(
        sum(r.get("content", {}).get("word_count", 0) for r in results) / total
    ) if total else 0

    # ── KPI Cards ────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">📊 Overview</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c5, c6, c7, c8 = st.columns(4)

    with c1: metric_card("Total URLs Audited", total, "#3B82F6")
    with c2: metric_card("Healthy URLs", healthy, "#10B981")
    with c3: metric_card("Critical URLs", critical_urls, "#EF4444")
    with c4: metric_card("URLs with Warnings", warnings, "#F59E0B")
    with c5: metric_card("Avg SEO Health Score", f"{avg_score}/100", _score_color(avg_score))
    with c6: metric_card("Avg Word Count", f"{avg_wc:,}", "#6366F1")
    with c7: metric_card("Total Broken Links", broken_links, "#EF4444")
    with c8: metric_card("Missing Meta Tags", missing_meta, "#F97316")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Charts ────────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">📈 Analytics</div>', unsafe_allow_html=True)
    ch1, ch2 = st.columns(2)

    with ch1:
        dist_data = {
            "Excellent (90-100)": sum(1 for s in scores if s >= 90),
            "Good (75-89)": sum(1 for s in scores if 75 <= s < 90),
            "Needs Attention (50-74)": sum(1 for s in scores if 50 <= s < 75),
            "Critical (<50)": sum(1 for s in scores if s < 50),
        }
        fig = px.pie(
            names=list(dist_data.keys()),
            values=list(dist_data.values()),
            color_discrete_sequence=["#10B981", "#3B82F6", "#F59E0B", "#EF4444"],
            title="SEO Health Distribution",
        )
        fig.update_layout(margin=dict(t=40, b=10, l=10, r=10), height=320)
        st.plotly_chart(fig, use_container_width=True)

    with ch2:
        sev_counts = {}
        for i in all_issues:
            s = i.get("severity", "Unknown")
            sev_counts[s] = sev_counts.get(s, 0) + 1
        fig2 = px.bar(
            x=list(sev_counts.keys()),
            y=list(sev_counts.values()),
            color=list(sev_counts.keys()),
            color_discrete_map={
                "Critical": "#EF4444", "High": "#F97316",
                "Medium": "#EAB308", "Warning": "#F59E0B", "Low": "#3B82F6",
            },
            title="Issue Severity Breakdown",
            labels={"x": "Severity", "y": "Count"},
        )
        fig2.update_layout(showlegend=False, margin=dict(t=40, b=10, l=10, r=10), height=320)
        st.plotly_chart(fig2, use_container_width=True)

    ch3, ch4 = st.columns(2)

    with ch3:
        cats = {}
        for i in all_issues:
            c = i.get("category", "Other")
            cats[c] = cats.get(c, 0) + 1
        top_cats = dict(sorted(cats.items(), key=lambda x: x[1], reverse=True)[:10])
        fig3 = px.bar(
            x=list(top_cats.values()),
            y=list(top_cats.keys()),
            orientation="h",
            title="Top Issue Categories",
            labels={"x": "Count", "y": "Category"},
            color=list(top_cats.values()),
            color_continuous_scale="Reds",
        )
        fig3.update_layout(showlegend=False, margin=dict(t=40, b=10, l=10, r=10),
                           height=340, coloraxis_showscale=False)
        st.plotly_chart(fig3, use_container_width=True)

    with ch4:
        types = {}
        for r in results:
            t = r.get("audit_type", "general").title()
            types[t] = types.get(t, 0) + 1
        int_total = sum(r.get("internal_links", {}).get("total_links", 0) for r in results)
        ext_total = sum(r.get("external_links", {}).get("total_links", 0) for r in results)
        fig4 = go.Figure()
        fig4.add_trace(go.Bar(name="Internal Links", x=["Link Distribution"], y=[int_total],
                              marker_color="#3B82F6"))
        fig4.add_trace(go.Bar(name="External Links", x=["Link Distribution"], y=[ext_total],
                              marker_color="#8B5CF6"))
        fig4.update_layout(title="Internal vs External Links",
                           margin=dict(t=40, b=10, l=10, r=10), height=340, barmode="group")
        st.plotly_chart(fig4, use_container_width=True)

    # Score scatter
    if total > 1:
        st.markdown('<div class="section-header">📉 Score Distribution</div>', unsafe_allow_html=True)
        df_plot = pd.DataFrame([{
            "URL": r.get("url", "")[-60:],
            "SEO Score": r.get("seo_score", 0),
            "Word Count": r.get("content", {}).get("word_count", 0),
            "Type": r.get("audit_type", "general").title(),
            "Issues": len(r.get("all_issues", [])),
        } for r in results])

        fig5 = px.scatter(
            df_plot, x="Word Count", y="SEO Score",
            color="Type", size="Issues", hover_data=["URL", "Issues"],
            title="SEO Score vs Word Count",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig5.add_hline(y=75, line_dash="dot", line_color="#3B82F6",
                       annotation_text="Good threshold (75)")
        fig5.add_hline(y=50, line_dash="dot", line_color="#EF4444",
                       annotation_text="Critical threshold (50)")
        fig5.update_layout(height=380, margin=dict(t=40, b=10, l=10, r=10))
        st.plotly_chart(fig5, use_container_width=True)


def page_new_audit():
    st.markdown(
        "<h2 style='font-size:1.5rem;font-weight:700;color:#0F172A'>🚀 New Audit</h2>",
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3 = st.tabs(["Single URL", "Bulk Upload (CSV/XLSX)", "Sitemap XML"])

    # ── Audit settings (shared) ──────────────────────────────────────────
    with st.sidebar:
        st.markdown("---")
        st.markdown("**⚙️ Audit Settings**")
        audit_type = st.selectbox(
            "Page Type", ["Auto-Detect", "Course", "Blog", "General"],
            help="Auto-Detect analyses the URL to determine type."
        )
        check_links = st.toggle("Audit Links", value=True)
        validate_links = st.toggle(
            "Validate Link Status Codes",
            value=False,
            help="Makes HTTP requests to each link. Slower but finds broken links.",
        )
        max_workers = st.slider("Concurrent Workers", 2, 16, 6,
                                help="Higher = faster bulk audits (may trigger rate limits)")
        st.markdown("---")

    audit_type_map = {
        "Auto-Detect": "auto", "Course": "course", "Blog": "blog", "General": "general"
    }
    atype = audit_type_map[audit_type]

    from modules.auditor import audit_url, audit_urls_bulk

    # ── Tab 1: Single URL ─────────────────────────────────────────────────
    with tab1:
        st.markdown("#### Enter a URL to audit")
        single_url = st.text_input(
            "URL", placeholder="https://example.com/courses/python-for-beginners",
            label_visibility="collapsed",
        )
        col_btn, col_info = st.columns([1, 3])
        with col_btn:
            run_single = st.button("🔍 Run Audit", type="primary", key="btn_single")

        if run_single:
            if not single_url.strip():
                st.warning("Please enter a URL.")
            elif not single_url.strip().startswith("http"):
                st.warning("URL must start with http:// or https://")
            else:
                with st.spinner(f"Auditing {single_url} ..."):
                    result = audit_url(
                        single_url.strip(), atype, check_links, validate_links
                    )
                # Merge or append
                existing = [r["url"] for r in st.session_state.audit_results]
                if single_url.strip() in existing:
                    idx = existing.index(single_url.strip())
                    st.session_state.audit_results[idx] = result
                else:
                    st.session_state.audit_results.insert(0, result)
                st.session_state.last_audit_date = datetime.now().strftime("%Y-%m-%d %H:%M")
                st.session_state.selected_url_idx = 0
                st.session_state["single_result"] = result

        # ── Inline results (persists across reruns) ───────────────────────
        result = st.session_state.get("single_result")
        if result:
            _render_inline_result(result)

    # ── Tab 2: Bulk Upload ────────────────────────────────────────────────
    with tab2:
        st.markdown("#### Upload a CSV or Excel file containing URLs")
        st.caption("The tool auto-detects a URL column. Supports .csv and .xlsx files.")
        bulk_file = st.file_uploader(
            "Upload file", type=["csv", "xlsx"], label_visibility="collapsed"
        )

        if bulk_file:
            urls, detected_col = extract_urls_from_csv_xlsx(bulk_file)
            if urls:
                st.success(f"Found **{len(urls)}** valid URLs in column '**{detected_col}**'")
                with st.expander("Preview URLs", expanded=False):
                    st.dataframe(pd.DataFrame({"URL": urls[:20]}), use_container_width=True)

                if st.button("🚀 Start Bulk Audit", type="primary", key="btn_bulk"):
                    progress_bar = st.progress(0.0)
                    status_text = st.empty()

                    def update(done, total_n):
                        progress_bar.progress(done / total_n)
                        status_text.text(f"Auditing URL {done}/{total_n} …")

                    new_results = audit_urls_bulk(
                        urls, atype, check_links, validate_links,
                        max_workers=max_workers,
                        progress_callback=update,
                    )
                    progress_bar.progress(1.0)
                    status_text.text("Audit complete!")
                    st.session_state.audit_results = new_results + st.session_state.audit_results
                    st.session_state.last_audit_date = datetime.now().strftime("%Y-%m-%d %H:%M")
                    st.success(f"✅ Audited {len(new_results)} URLs. View results in **Audit Results**.")
            else:
                st.warning("No valid URLs found. Ensure the file has URLs starting with http.")

    # ── Tab 3: Sitemap ────────────────────────────────────────────────────
    with tab3:
        st.markdown("#### Upload an XML Sitemap")
        sitemap_file = st.file_uploader(
            "Upload sitemap", type=["xml"], label_visibility="collapsed"
        )

        if sitemap_file:
            sitemap_urls = extract_urls_from_sitemap(sitemap_file)
            if sitemap_urls:
                st.success(f"Extracted **{len(sitemap_urls)}** URLs from sitemap.")
                select_all = st.checkbox("Select All URLs", value=True)
                if not select_all:
                    chosen = st.multiselect(
                        "Choose URLs to audit",
                        sitemap_urls,
                        default=sitemap_urls[:10],
                    )
                else:
                    chosen = sitemap_urls

                st.info(f"**{len(chosen)}** URL(s) selected for audit.")

                if st.button("🚀 Audit Sitemap URLs", type="primary", key="btn_sitemap"):
                    if not chosen:
                        st.warning("Select at least one URL.")
                    else:
                        progress_bar = st.progress(0.0)
                        status_text = st.empty()

                        def update_s(done, total_n):
                            progress_bar.progress(done / total_n)
                            status_text.text(f"Auditing URL {done}/{total_n} …")

                        new_results = audit_urls_bulk(
                            chosen, atype, check_links, validate_links,
                            max_workers=max_workers,
                            progress_callback=update_s,
                        )
                        progress_bar.progress(1.0)
                        status_text.text("Audit complete!")
                        st.session_state.audit_results = new_results + st.session_state.audit_results
                        st.session_state.last_audit_date = datetime.now().strftime("%Y-%m-%d %H:%M")
                        st.success(f"✅ Audited {len(new_results)} URLs.")
            else:
                st.warning("No URLs found in the sitemap.")


def page_results():
    st.markdown(
        "<h2 style='font-size:1.5rem;font-weight:700;color:#0F172A'>📋 Audit Results</h2>",
        unsafe_allow_html=True,
    )
    results = st.session_state.audit_results

    if not results:
        st.info("No audit results yet. Run a **New Audit** first.")
        return

    df = build_results_df(results)

    # ── Filters ───────────────────────────────────────────────────────────
    with st.expander("🔽 Filters", expanded=False):
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            type_filter = st.multiselect(
                "Page Type", df["Type"].unique().tolist(), default=df["Type"].unique().tolist()
            )
        with fc2:
            score_filter = st.slider("Min SEO Score", 0, 100, 0)
        with fc3:
            sev_filter = st.selectbox("Has Issue Severity", ["Any", "Critical", "High", "Medium"])
        with fc4:
            broken_only = st.checkbox("Has Broken Links")

    mask = (
        df["Type"].isin(type_filter) &
        (df["SEO Score"] >= score_filter)
    )
    if sev_filter != "Any":
        sev_col = sev_filter
        if sev_col in df.columns:
            mask &= df[sev_col] > 0
    if broken_only:
        mask &= (df["Broken Int."] + df["Broken Ext."]) > 0

    df_filtered = df[mask].reset_index(drop=True)
    st.caption(f"Showing **{len(df_filtered)}** of {len(df)} URLs")

    # ── Colour score column ───────────────────────────────────────────────
    def color_score(val):
        if val >= 90:
            return "background-color:#D1FAE5;color:#065F46;font-weight:600"
        elif val >= 75:
            return "background-color:#DBEAFE;color:#1E40AF;font-weight:600"
        elif val >= 50:
            return "background-color:#FEF3C7;color:#92400E;font-weight:600"
        return "background-color:#FEE2E2;color:#991B1B;font-weight:600"

    def color_critical(val):
        if val > 0:
            return "color:#EF4444;font-weight:700"
        return ""

    styled = df_filtered.style.applymap(color_score, subset=["SEO Score"]) \
                               .applymap(color_critical, subset=["Critical", "Broken Int.", "Broken Ext."])

    st.dataframe(styled, use_container_width=True, height=450)

    # ── Select URL for detail ─────────────────────────────────────────────
    st.markdown("---")
    selected_url = st.selectbox(
        "🔎 Open URL Detail",
        options=[r.get("url", "") for r in results],
        index=st.session_state.selected_url_idx,
    )
    if st.button("Open Detail View →", type="primary"):
        idx = next((i for i, r in enumerate(results) if r.get("url") == selected_url), 0)
        st.session_state.selected_url_idx = idx
        st.session_state.page = "URL Detail"
        st.rerun()

    # ── Clear results ─────────────────────────────────────────────────────
    if st.button("🗑️ Clear All Results", type="secondary"):
        st.session_state.audit_results = []
        st.session_state.last_audit_date = None
        st.rerun()


def page_url_detail():
    results = st.session_state.audit_results
    if not results:
        st.info("No audit results yet.")
        return

    idx = st.session_state.selected_url_idx
    if idx >= len(results):
        idx = 0
    r = results[idx]

    # URL selector
    url_list = [res.get("url", "") for res in results]
    chosen = st.selectbox("Select URL", url_list, index=idx)
    if chosen != r.get("url"):
        idx = url_list.index(chosen)
        st.session_state.selected_url_idx = idx
        r = results[idx]

    url = r.get("url", "")
    score = r.get("seo_score", 0)
    issues = r.get("all_issues", [])

    # ── Header ────────────────────────────────────────────────────────────
    sc1, sc2, sc3, sc4 = st.columns([3, 1, 1, 1])
    with sc1:
        st.markdown(f"**URL:** [{url[:80]}]({url})")
        st.caption(
            f"Type: {r.get('audit_type','').title()} | "
            f"HTTP {r.get('status_code',0)} | "
            f"Response: {r.get('response_time',0):.2f}s | "
            f"Redirects: {r.get('redirect_count',0)}"
        )
    with sc2:
        color = _score_color(score)
        st.markdown(
            f"<div style='text-align:center'>"
            f"<div style='font-size:2.4rem;font-weight:800;color:{color}'>{score}</div>"
            f"<div style='font-size:.75rem;color:#64748B'>/ 100</div>"
            f"<span class='{_score_class(score)} score-badge'>{_score_label(score)}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with sc3:
        metric_card("Total Issues", len(issues), "#6366F1")
    with sc4:
        crit = sum(1 for i in issues if i.get("severity") == "Critical")
        metric_card("Critical", crit, "#EF4444")

    st.markdown("---")

    # ── Tabs ──────────────────────────────────────────────────────────────
    tabs = st.tabs([
        "📊 Score Breakdown", "⚠️ Issues", "🔗 Links",
        "📄 Content & Images", "🎓 Course / Blog", "💡 Recommendations"
    ])

    # ── Tab: Score Breakdown ──────────────────────────────────────────────
    with tabs[0]:
        bd = r.get("score_breakdown", {})
        from modules.scoring import WEIGHTS
        labels = list(bd.keys())
        values = [bd.get(k, 100) for k in labels]

        fig = go.Figure()
        fig.add_trace(go.Scatterpolar(
            r=values,
            theta=[l.replace("_", " ").title() for l in labels],
            fill="toself",
            name="Score",
            line_color="#3B82F6",
            fillcolor="rgba(59,130,246,0.15)",
        ))
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=False,
            height=380,
            margin=dict(t=20, b=20, l=20, r=20),
        )
        col_r1, col_r2 = st.columns([1, 1])
        with col_r1:
            st.plotly_chart(fig, use_container_width=True)
        with col_r2:
            st.markdown("**Category Scores**")
            for k, v in bd.items():
                color = _score_color(v)
                st.markdown(
                    f"""
                    <div style='display:flex;justify-content:space-between;
                    align-items:center;padding:6px 0;border-bottom:1px solid #F1F5F9'>
                        <span style='font-size:.85rem;color:#374151'>
                            {k.replace("_"," ").title()}
                        </span>
                        <span style='font-size:.9rem;font-weight:700;color:{color}'>{v:.0f}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        # Metadata quick view
        st.markdown('<div class="section-header">Metadata</div>', unsafe_allow_html=True)
        meta = r.get("metadata", {})
        m1, m2 = st.columns(2)
        with m1:
            st.markdown(f"**Title ({meta.get('title_length',0)} chars)**")
            st.code(meta.get("title", "—"), language=None)
        with m2:
            st.markdown(f"**Description ({meta.get('description_length',0)} chars)**")
            st.code(meta.get("description", "—"), language=None)

        # Heading structure
        st.markdown('<div class="section-header">Heading Structure</div>', unsafe_allow_html=True)
        head = r.get("headings", {})
        hc1, hc2, hc3, hc4 = st.columns(4)
        hc1.metric("H1", head.get("h1_count", 0))
        hc2.metric("H2", head.get("h2_count", 0))
        hc3.metric("H3", head.get("h3_count", 0))
        hc4.metric("H4", head.get("h4_count", 0))
        if head.get("h1_texts"):
            st.caption(f"H1: {' | '.join(head['h1_texts'][:3])}")

    # ── Tab: Issues ───────────────────────────────────────────────────────
    with tabs[1]:
        if not issues:
            st.success("🎉 No issues found! This page looks great.")
        else:
            sev_order = ["Critical", "High", "Medium", "Warning", "Low"]
            for sev in sev_order:
                sev_issues = [i for i in issues if i.get("severity") == sev]
                if not sev_issues:
                    continue
                with st.expander(
                    f"**{sev}** — {len(sev_issues)} issue(s)",
                    expanded=sev in ["Critical", "High"],
                ):
                    for iss in sev_issues:
                        st.markdown(
                            f"""
                            <div style='padding:10px;background:#F8FAFC;border-radius:8px;
                            margin-bottom:8px;border-left:4px solid {_score_color(0 if sev in ["Critical","High"] else 75)}'>
                                <div style='font-weight:600;font-size:.88rem;color:#0F172A'>
                                    {iss.get('issue','')}
                                </div>
                                <div style='font-size:.78rem;color:#64748B;margin-top:2px'>
                                    Category: {iss.get('category','')}
                                </div>
                                <div style='font-size:.82rem;color:#1D4ED8;margin-top:6px'>
                                    💡 {iss.get('recommendation','')}
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

    # ── Tab: Links ────────────────────────────────────────────────────────
    with tabs[2]:
        il = r.get("internal_links", {})
        el = r.get("external_links", {})

        lc1, lc2 = st.columns(2)
        with lc1:
            st.markdown('<div class="section-header">🔵 Internal Links</div>', unsafe_allow_html=True)
            i1, i2, i3, i4 = st.columns(4)
            i1.metric("Total", il.get("total_links", 0))
            i2.metric("Unique", il.get("unique_links", 0))
            i3.metric("Dofollow", il.get("dofollow_count", 0))
            i4.metric("Broken", il.get("broken_count", 0), delta=None if il.get("broken_count",0)==0 else "⚠️")
            st.caption(
                f"Nofollow: {il.get('nofollow_count',0)} | "
                f"New Tab: {il.get('new_tab_count',0)} | "
                f"Redirects: {il.get('redirect_count',0)} | "
                f"Weak Anchors: {il.get('weak_anchor_count',0)}"
            )

        with lc2:
            st.markdown('<div class="section-header">🟣 External Links</div>', unsafe_allow_html=True)
            e1, e2, e3, e4 = st.columns(4)
            e1.metric("Total", el.get("total_links", 0))
            e2.metric("Unique Domains", el.get("unique_domains", 0))
            e3.metric("Dofollow", el.get("dofollow_count", 0))
            e4.metric("Broken", el.get("broken_count", 0))
            st.caption(
                f"Nofollow: {el.get('nofollow_count',0)} | "
                f"Sponsored: {el.get('sponsored_count',0)} | "
                f"UGC: {el.get('ugc_count',0)} | "
                f"Missing noopener: {el.get('missing_noopener_count',0)}"
            )

        # Internal link table
        if il.get("links"):
            st.markdown('<div class="section-header">Internal Link Details</div>', unsafe_allow_html=True)
            il_df = pd.DataFrame([{
                "URL": lk.get("url", "")[:80],
                "Anchor": lk.get("anchor_text", "")[:40],
                "Dofollow": "✅" if lk.get("is_dofollow") else "❌",
                "New Tab": "✅" if lk.get("opens_new_tab") else "—",
                "Noopener": "✅" if lk.get("has_noopener") else "❌",
                "Status": lk.get("status_code") or "—",
                "Broken": "🔴" if lk.get("is_broken") else ("—" if lk.get("is_broken") is None else "✅"),
            } for lk in il["links"][:30]])
            st.dataframe(il_df, use_container_width=True, height=280)

        # External link table
        if el.get("links"):
            st.markdown('<div class="section-header">External Link Details</div>', unsafe_allow_html=True)
            el_df = pd.DataFrame([{
                "URL": lk.get("url", "")[:80],
                "Anchor": lk.get("anchor_text", "")[:40],
                "Dofollow": "✅" if lk.get("is_dofollow") else "❌",
                "Nofollow": "✅" if lk.get("is_nofollow") else "—",
                "Sponsored": "✅" if lk.get("is_sponsored") else "—",
                "New Tab": "✅" if lk.get("opens_new_tab") else "❌",
                "Noopener": "✅" if lk.get("has_noopener") else "❌",
                "Noreferrer": "✅" if lk.get("has_noreferrer") else "❌",
                "Status": lk.get("status_code") or "—",
            } for lk in el["links"][:30]])
            st.dataframe(el_df, use_container_width=True, height=280)

    # ── Tab: Content & Images ─────────────────────────────────────────────
    with tabs[3]:
        cont = r.get("content", {})
        imgs = r.get("images", {})
        can = r.get("canonical", {})
        idx_data = r.get("indexability", {})
        url_data = r.get("url_structure", {})

        ct1, ct2 = st.columns(2)
        with ct1:
            st.markdown('<div class="section-header">Content Quality</div>', unsafe_allow_html=True)
            c_a, c_b, c_c = st.columns(3)
            c_a.metric("Word Count", cont.get("word_count", 0))
            c_b.metric("Reading Time", f"{cont.get('reading_time', 0)} min")
            c_c.metric("Content Ratio", f"{cont.get('content_ratio', 0)}%")
            st.markdown(
                f"Thin Content: {'⚠️ Yes' if cont.get('is_thin') else '✅ No'}"
            )

        with ct2:
            st.markdown('<div class="section-header">Images</div>', unsafe_allow_html=True)
            i_a, i_b, i_c = st.columns(3)
            i_a.metric("Total Images", imgs.get("total_images", 0))
            i_b.metric("Missing Alt", imgs.get("missing_alt_count", 0))
            i_c.metric("Empty Alt", imgs.get("empty_alt_count", 0))

        ct3, ct4 = st.columns(2)
        with ct3:
            st.markdown('<div class="section-header">Canonical & Indexability</div>', unsafe_allow_html=True)
            st.markdown(f"**Canonical URL:** `{can.get('canonical_url','—') or '—'}`")
            st.markdown(f"**Self-Referencing:** {'✅' if can.get('is_self_referencing') else '❌'}")
            st.markdown(f"**Indexable:** {'✅' if idx_data.get('is_indexable', True) else '🔴 Noindex'}")
            st.markdown(f"**Meta Robots:** `{idx_data.get('robots_meta','—') or 'Not set'}`")

        with ct4:
            st.markdown('<div class="section-header">URL Structure</div>', unsafe_allow_html=True)
            st.markdown(f"**Length:** {url_data.get('length', 0)} chars")
            st.markdown(f"**HTTPS:** {'✅' if url_data.get('is_https') else '🔴 No'}")
            st.markdown(f"**Slug:** `{url_data.get('slug','—')}`")
            st.markdown(f"**Path:** `{url_data.get('path','—')}`")

    # ── Tab: Course / Blog ────────────────────────────────────────────────
    with tabs[4]:
        audit_t = r.get("audit_type", "general")
        if audit_t == "course":
            ca = r.get("course_audit", {})
            st.markdown('<div class="section-header">🎓 Course Page Audit</div>', unsafe_allow_html=True)
            st.metric("Section Completeness", f"{ca.get('sections_score', 0):.0f}%")
            st.metric("Course Schema", "✅ Present" if ca.get("has_course_schema") else "❌ Missing")

            sec = ca.get("sections_found", {})
            conv = ca.get("conversion_elements", {})
            s1, s2 = st.columns(2)
            with s1:
                st.markdown("**Required Sections**")
                for name, found in sec.items():
                    icon = "✅" if found else "❌"
                    st.markdown(f"{icon} {name}")
            with s2:
                st.markdown("**Conversion Elements**")
                for name, found in conv.items():
                    icon = "✅" if found else "❌"
                    st.markdown(f"{icon} {name}")

        elif audit_t == "blog":
            ba = r.get("blog_audit", {})
            st.markdown('<div class="section-header">📝 Blog Page Audit</div>', unsafe_allow_html=True)
            b1, b2, b3 = st.columns(3)
            b1.metric("Elements Score", f"{ba.get('elements_score', 0):.0f}%")
            b2.metric("Word Count", ba.get("word_count", 0))
            b3.metric("Readability", ba.get("readability_score", "—"))
            st.metric("Article Schema", "✅ Present" if ba.get("has_article_schema") else "❌ Missing")
            st.metric("OG Tags", "✅ Present" if ba.get("has_og_tags") else "❌ Missing")

            elems = ba.get("elements_found", {})
            st.markdown("**Blog Elements**")
            col_e1, col_e2 = st.columns(2)
            items = list(elems.items())
            for i, (name, found) in enumerate(items):
                col = col_e1 if i % 2 == 0 else col_e2
                col.markdown(f"{'✅' if found else '❌'} {name}")
        else:
            st.info("This URL was audited as a General page. Select 'Course' or 'Blog' in audit settings for type-specific checks.")

    # ── Tab: Recommendations ──────────────────────────────────────────────
    with tabs[5]:
        st.markdown('<div class="section-header">💡 AI SEO Recommendations</div>', unsafe_allow_html=True)
        if not issues:
            st.success("🎉 No recommendations — this page is well optimised!")
        else:
            sev_priority = {"Critical": 0, "High": 1, "Medium": 2, "Warning": 3, "Low": 4}
            sorted_issues = sorted(issues, key=lambda x: sev_priority.get(x.get("severity", "Low"), 4))
            for i, iss in enumerate(sorted_issues, 1):
                sev = iss.get("severity", "Low")
                color = {"Critical": "#EF4444", "High": "#F97316", "Medium": "#EAB308",
                         "Warning": "#F59E0B", "Low": "#3B82F6"}.get(sev, "#6B7280")
                st.markdown(
                    f"""
                    <div style='padding:12px 16px;background:#F8FAFC;border-radius:10px;
                    margin-bottom:10px;border-left:4px solid {color}'>
                        <div style='display:flex;justify-content:space-between;align-items:center'>
                            <span style='font-weight:700;font-size:.88rem;color:#0F172A'>
                                {i}. {iss.get('issue','')}
                            </span>
                            <span class='{_sev_class(sev)} sev-{sev.lower()}'>{sev}</span>
                        </div>
                        <div style='font-size:.78rem;color:#64748B;margin:4px 0'>
                            📂 {iss.get('category','')}
                        </div>
                        <div style='font-size:.84rem;color:#1D4ED8;margin-top:6px'>
                            ✅ {iss.get('recommendation','')}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def page_link_analysis():
    st.markdown(
        "<h2 style='font-size:1.5rem;font-weight:700;color:#0F172A'>🔗 Link Analysis</h2>",
        unsafe_allow_html=True,
    )
    results = st.session_state.audit_results
    if not results:
        st.info("No audit results yet.")
        return

    all_int = [(r.get("url",""), lk) for r in results for lk in r.get("internal_links",{}).get("links",[])]
    all_ext = [(r.get("url",""), lk) for r in results for lk in r.get("external_links",{}).get("links",[])]

    tab_i, tab_e = st.tabs(["🔵 Internal Links", "🟣 External Links"])

    with tab_i:
        total_int = sum(r.get("internal_links",{}).get("total_links",0) for r in results)
        broken_int = sum(r.get("internal_links",{}).get("broken_count",0) for r in results)
        redir_int = sum(r.get("internal_links",{}).get("redirect_count",0) for r in results)
        nofollow_int = sum(r.get("internal_links",{}).get("nofollow_count",0) for r in results)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Internal Links", total_int)
        c2.metric("Broken", broken_int)
        c3.metric("Redirecting", redir_int)
        c4.metric("Nofollow", nofollow_int)

        if all_int:
            rows = [{
                "Source Page": src[-60:],
                "Link URL": lk.get("url","")[:80],
                "Anchor Text": lk.get("anchor_text","")[:40],
                "Dofollow": "✅" if lk.get("is_dofollow") else "❌",
                "New Tab": "✅" if lk.get("opens_new_tab") else "—",
                "Noopener": "✅" if lk.get("has_noopener") else "❌",
                "Status": lk.get("status_code") or "—",
                "Broken": "🔴 Yes" if lk.get("is_broken") else ("—" if lk.get("is_broken") is None else "✅ OK"),
            } for src, lk in all_int[:500]]
            df_int = pd.DataFrame(rows)
            search_int = st.text_input("Search internal links", key="search_int")
            if search_int:
                df_int = df_int[df_int.apply(lambda row: search_int.lower() in str(row).lower(), axis=1)]
            st.dataframe(df_int, use_container_width=True, height=450)

    with tab_e:
        total_ext = sum(r.get("external_links",{}).get("total_links",0) for r in results)
        broken_ext = sum(r.get("external_links",{}).get("broken_count",0) for r in results)
        dofollow_ext = sum(r.get("external_links",{}).get("dofollow_count",0) for r in results)
        domains = list({d for r in results for d in r.get("external_links",{}).get("domains",[])})

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total External Links", total_ext)
        c2.metric("Broken", broken_ext)
        c3.metric("Dofollow", dofollow_ext)
        c4.metric("Unique Domains", len(domains))

        if domains:
            st.markdown("**Top External Domains**")
            domain_counts = {}
            for r in results:
                for lk in r.get("external_links",{}).get("links",[]):
                    from modules.link_auditor import get_base_domain
                    d = get_base_domain(lk.get("url",""))
                    domain_counts[d] = domain_counts.get(d, 0) + 1
            top_domains = dict(sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:15])
            fig = px.bar(x=list(top_domains.values()), y=list(top_domains.keys()),
                         orientation="h", labels={"x":"Links","y":"Domain"},
                         color=list(top_domains.values()), color_continuous_scale="Blues")
            fig.update_layout(showlegend=False, height=380, coloraxis_showscale=False,
                               margin=dict(t=10,b=10,l=10,r=10))
            st.plotly_chart(fig, use_container_width=True)

        if all_ext:
            rows = [{
                "Source Page": src[-60:],
                "Link URL": lk.get("url","")[:80],
                "Anchor": lk.get("anchor_text","")[:40],
                "Dofollow": "✅" if lk.get("is_dofollow") else "❌",
                "Nofollow": "✅" if lk.get("is_nofollow") else "—",
                "Sponsored": "✅" if lk.get("is_sponsored") else "—",
                "New Tab": "✅" if lk.get("opens_new_tab") else "❌",
                "Noopener": "✅" if lk.get("has_noopener") else "❌",
                "Status": lk.get("status_code") or "—",
            } for src, lk in all_ext[:500]]
            df_ext = pd.DataFrame(rows)
            search_ext = st.text_input("Search external links", key="search_ext")
            if search_ext:
                df_ext = df_ext[df_ext.apply(lambda row: search_ext.lower() in str(row).lower(), axis=1)]
            st.dataframe(df_ext, use_container_width=True, height=450)


def page_export():
    st.markdown(
        "<h2 style='font-size:1.5rem;font-weight:700;color:#0F172A'>📤 Export Reports</h2>",
        unsafe_allow_html=True,
    )
    results = st.session_state.audit_results
    if not results:
        st.info("No audit results to export. Run an audit first.")
        return

    st.markdown(
        f"""
        <div class="info-box">
        Ready to export <b>{len(results)}</b> audited URLs.
        Choose your format below.
        </div>
        """,
        unsafe_allow_html=True,
    )

    from modules.report_generator import generate_csv, generate_excel, generate_pdf

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### 📄 CSV Report")
        st.caption("Flat table with all audit metrics. Best for quick data analysis.")
        with st.spinner("Preparing CSV…"):
            csv_data = generate_csv(results)
        st.download_button(
            "⬇️ Download CSV",
            data=csv_data,
            file_name=f"seo_audit_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            type="primary",
        )

    with col2:
        st.markdown("#### 📊 Excel Report")
        st.caption("Multi-sheet workbook: Summary + Issues + Link Audit with colour coding.")
        with st.spinner("Preparing Excel…"):
            excel_data = generate_excel(results)
        st.download_button(
            "⬇️ Download Excel",
            data=excel_data,
            file_name=f"seo_audit_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

    with col3:
        st.markdown("#### 📑 PDF Report")
        st.caption("Executive summary and URL-level table with colour-coded scores.")
        with st.spinner("Preparing PDF…"):
            pdf_data = generate_pdf(results)
        st.download_button(
            "⬇️ Download PDF",
            data=pdf_data,
            file_name=f"seo_audit_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            type="primary",
        )

    # Preview table
    st.markdown("---")
    st.markdown("#### Preview")
    df = build_results_df(results)
    st.dataframe(df, use_container_width=True, height=350)


# ════════════════════════════════════════════════════════════════════════════
# Sidebar Navigation
# ════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown(
        """
        <div style='text-align:center;padding:16px 0 8px'>
            <div style='font-size:2rem'>🔍</div>
            <div style='font-size:1rem;font-weight:700;color:#F1F5F9'>SEO Audit Dashboard</div>
            <div style='font-size:.72rem;color:#94A3B8'>Enterprise SEO Platform</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("---")

    page = st.radio(
        "Navigation",
        [
            "📊 Dashboard Overview",
            "🚀 New Audit",
            "📋 Audit Results",
            "🔎 URL Detail",
            "🔗 Link Analysis",
            "📤 Export Reports",
        ],
        label_visibility="collapsed",
    )

    # Store page choice for cross-page navigation
    if "page" in st.session_state and st.session_state.page == "URL Detail":
        page = "🔎 URL Detail"
        del st.session_state["page"]

    results = st.session_state.audit_results
    if results:
        st.markdown("---")
        st.markdown("**📌 Audit Status**")
        st.caption(f"URLs: {len(results)}")
        if st.session_state.last_audit_date:
            st.caption(f"Last run: {st.session_state.last_audit_date}")
        avg = sum(r.get("seo_score", 0) for r in results) / len(results)
        color = _score_color(avg)
        st.markdown(
            f"<div style='color:{color};font-weight:700;font-size:.9rem'>Avg Score: {avg:.1f}/100</div>",
            unsafe_allow_html=True,
        )


# ════════════════════════════════════════════════════════════════════════════
# Router
# ════════════════════════════════════════════════════════════════════════════

if page == "📊 Dashboard Overview":
    page_dashboard()
elif page == "🚀 New Audit":
    page_new_audit()
elif page == "📋 Audit Results":
    page_results()
elif page == "🔎 URL Detail":
    page_url_detail()
elif page == "🔗 Link Analysis":
    page_link_analysis()
elif page == "📤 Export Reports":
    page_export()

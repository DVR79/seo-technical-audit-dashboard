"""Export audit results to CSV, Excel, and PDF formats."""

import io
from datetime import datetime

import pandas as pd


def _score_label(score):
    if score >= 90:
        return "Excellent"
    elif score >= 75:
        return "Good"
    elif score >= 50:
        return "Needs Attention"
    return "Critical"


def flatten(result):
    issues = result.get("all_issues", [])
    sev = lambda s: sum(1 for i in issues if i.get("severity") == s)

    meta = result.get("metadata", {})
    head = result.get("headings", {})
    cont = result.get("content", {})
    imgs = result.get("images", {})
    can = result.get("canonical", {})
    idx = result.get("indexability", {})
    il = result.get("internal_links", {})
    el = result.get("external_links", {})

    return {
        "URL": result.get("url", ""),
        "Audit Type": result.get("audit_type", "").title(),
        "Status Code": result.get("status_code", ""),
        "SEO Score": result.get("seo_score", 0),
        "Score Label": _score_label(result.get("seo_score", 0)),
        "Response Time (s)": round(result.get("response_time", 0), 2),
        "Redirects": result.get("redirect_count", 0),
        "Total Issues": len(issues),
        "Critical": sev("Critical"),
        "High": sev("High"),
        "Medium": sev("Medium"),
        "Low": sev("Low") + sev("Warning"),
        "Meta Title": meta.get("title", ""),
        "Title Length": meta.get("title_length", ""),
        "Meta Description": (meta.get("description", "")[:120] + "...") if len(meta.get("description", "")) > 120 else meta.get("description", ""),
        "Desc Length": meta.get("description_length", ""),
        "H1 Count": head.get("h1_count", ""),
        "H2 Count": head.get("h2_count", ""),
        "Word Count": cont.get("word_count", ""),
        "Reading Time (min)": cont.get("reading_time", ""),
        "Thin Content": cont.get("is_thin", ""),
        "Total Images": imgs.get("total_images", ""),
        "Images Missing Alt": imgs.get("missing_alt_count", ""),
        "Canonical URL": can.get("canonical_url", ""),
        "Is Indexable": idx.get("is_indexable", ""),
        "Internal Links": il.get("total_links", ""),
        "Broken Internal": il.get("broken_count", ""),
        "External Links": el.get("total_links", ""),
        "Broken External": el.get("broken_count", ""),
        "Fetch Error": result.get("fetch_error", ""),
    }


def generate_csv(results):
    rows = [flatten(r) for r in results]
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def generate_excel(results):
    buf = io.BytesIO()
    summary_rows = [flatten(r) for r in results]
    summary_df = pd.DataFrame(summary_rows)

    issue_rows = []
    for r in results:
        url = r.get("url", "")
        for iss in r.get("all_issues", []):
            issue_rows.append({
                "URL": url,
                "Issue": iss.get("issue", ""),
                "Category": iss.get("category", ""),
                "Severity": iss.get("severity", ""),
                "Recommendation": iss.get("recommendation", ""),
            })
    issues_df = pd.DataFrame(issue_rows) if issue_rows else pd.DataFrame(
        columns=["URL", "Issue", "Category", "Severity", "Recommendation"]
    )

    link_rows = []
    for r in results:
        url = r.get("url", "")
        for link in r.get("internal_links", {}).get("links", []):
            link_rows.append({
                "Source URL": url,
                "Type": "Internal",
                "Link URL": link.get("url", ""),
                "Anchor Text": link.get("anchor_text", ""),
                "Dofollow": link.get("is_dofollow", ""),
                "Opens New Tab": link.get("opens_new_tab", ""),
                "Has Noopener": link.get("has_noopener", ""),
                "Status Code": link.get("status_code", "N/A"),
                "Is Broken": link.get("is_broken", "N/A"),
            })
        for link in r.get("external_links", {}).get("links", []):
            link_rows.append({
                "Source URL": url,
                "Type": "External",
                "Link URL": link.get("url", ""),
                "Anchor Text": link.get("anchor_text", ""),
                "Dofollow": link.get("is_dofollow", ""),
                "Opens New Tab": link.get("opens_new_tab", ""),
                "Has Noopener": link.get("has_noopener", ""),
                "Status Code": link.get("status_code", "N/A"),
                "Is Broken": link.get("is_broken", "N/A"),
            })
    links_df = pd.DataFrame(link_rows) if link_rows else pd.DataFrame()

    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        summary_df.to_excel(writer, sheet_name="Audit Summary", index=False)
        issues_df.to_excel(writer, sheet_name="All Issues", index=False)
        if not links_df.empty:
            links_df.to_excel(writer, sheet_name="Link Audit", index=False)

        wb = writer.book

        hdr_fmt = wb.add_format({"bold": True, "font_color": "white", "bg_color": "#1E3A5F",
                                  "border": 1, "text_wrap": True, "valign": "vcenter"})
        green = wb.add_format({"bg_color": "#D1FAE5", "font_color": "#065F46"})
        blue  = wb.add_format({"bg_color": "#DBEAFE", "font_color": "#1E40AF"})
        amber = wb.add_format({"bg_color": "#FEF3C7", "font_color": "#92400E"})
        red   = wb.add_format({"bg_color": "#FEE2E2", "font_color": "#991B1B"})
        sev_fmts = {
            "Critical": wb.add_format({"bg_color": "#FEE2E2", "font_color": "#991B1B", "bold": True}),
            "High":     wb.add_format({"bg_color": "#FED7AA", "font_color": "#9A3412"}),
            "Medium":   wb.add_format({"bg_color": "#FEF9C3", "font_color": "#713F12"}),
            "Warning":  wb.add_format({"bg_color": "#FEF3C7", "font_color": "#92400E"}),
            "Low":      wb.add_format({"bg_color": "#DBEAFE", "font_color": "#1E40AF"}),
        }

        # Format summary sheet
        ws = writer.sheets["Audit Summary"]
        for ci, cn in enumerate(summary_df.columns):
            ws.write(0, ci, cn, hdr_fmt)
            ws.set_column(ci, ci, max(14, len(str(cn)) + 2))

        score_col = list(summary_df.columns).index("SEO Score") if "SEO Score" in summary_df.columns else -1
        if score_col >= 0:
            for ri, sc in enumerate(summary_df["SEO Score"], 1):
                fmt = green if sc >= 90 else (blue if sc >= 75 else (amber if sc >= 50 else red))
                ws.write(ri, score_col, sc, fmt)

        # Format issues sheet
        wi = writer.sheets["All Issues"]
        for ci, cn in enumerate(issues_df.columns):
            wi.write(0, ci, cn, hdr_fmt)
            wi.set_column(ci, ci, 35)

        sev_col = list(issues_df.columns).index("Severity") if "Severity" in issues_df.columns else -1
        if sev_col >= 0:
            for ri, sv in enumerate(issues_df["Severity"], 1):
                fmt = sev_fmts.get(sv)
                if fmt:
                    wi.write(ri, sev_col, sv, fmt)

    buf.seek(0)
    return buf.getvalue()


def generate_pdf(results):
    try:
        from fpdf import FPDF

        class PDF(FPDF):
            def header(self):
                self.set_fill_color(30, 58, 95)
                self.set_text_color(255, 255, 255)
                self.set_font("Helvetica", "B", 14)
                self.cell(0, 12, "SEO Technical Audit Report", ln=True, align="C", fill=True)
                self.set_text_color(0, 0, 0)
                self.ln(4)

            def footer(self):
                self.set_y(-14)
                self.set_font("Helvetica", "I", 8)
                self.set_text_color(120, 120, 120)
                self.cell(0, 8, f"Page {self.page_no()} | SEO Audit Dashboard", align="C")

        pdf = PDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        total = len(results)
        avg_score = sum(r.get("seo_score", 0) for r in results) / total if total else 0
        critical = sum(1 for r in results if r.get("seo_score", 0) < 50)
        healthy = sum(1 for r in results if r.get("seo_score", 0) >= 75)
        issues_total = sum(len(r.get("all_issues", [])) for r in results)

        pdf.set_font("Helvetica", "B", 11)
        pdf.set_fill_color(235, 245, 255)
        pdf.cell(0, 8, "Executive Summary", ln=True, fill=True)
        pdf.ln(1)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 6, f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True)
        pdf.cell(0, 6, f"Total URLs Audited: {total}", ln=True)
        pdf.cell(0, 6, f"Average SEO Score: {avg_score:.1f}/100", ln=True)
        pdf.cell(0, 6, f"Healthy URLs (Score >= 75): {healthy}", ln=True)
        pdf.cell(0, 6, f"Critical URLs (Score < 50): {critical}", ln=True)
        pdf.cell(0, 6, f"Total Issues Found: {issues_total}", ln=True)
        pdf.ln(6)

        # Results table
        col_w = [72, 18, 18, 18, 54]
        headers = ["URL", "Score", "HTTP", "Issues", "Top Issue"]

        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(30, 58, 95)
        pdf.set_text_color(255, 255, 255)
        for w, h in zip(col_w, headers):
            pdf.cell(w, 7, h, border=1, align="C", fill=True)
        pdf.ln()
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 7)

        for r in results[:150]:
            url = (r.get("url", ""))[:65]
            sc = r.get("seo_score", 0)
            status = str(r.get("status_code", ""))
            n_issues = len(r.get("all_issues", []))
            top = next(
                (i.get("issue", "")[:50] for i in r.get("all_issues", [])
                 if i.get("severity") == "Critical"),
                (r.get("all_issues", [{}])[0].get("issue", "") if r.get("all_issues") else ""),
            )

            if sc >= 90:
                pdf.set_fill_color(209, 250, 229)
            elif sc >= 75:
                pdf.set_fill_color(219, 234, 254)
            elif sc >= 50:
                pdf.set_fill_color(254, 243, 199)
            else:
                pdf.set_fill_color(254, 226, 226)

            fill = True
            pdf.cell(col_w[0], 6, url, border=1, fill=fill)
            pdf.cell(col_w[1], 6, str(sc), border=1, align="C", fill=fill)
            pdf.cell(col_w[2], 6, status, border=1, align="C", fill=fill)
            pdf.cell(col_w[3], 6, str(n_issues), border=1, align="C", fill=fill)
            pdf.cell(col_w[4], 6, top[:50], border=1, fill=fill)
            pdf.ln()

        return bytes(pdf.output())

    except ImportError:
        lines = [
            "SEO Audit Report",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "=" * 70,
            "",
        ]
        for r in results:
            lines.append(f"URL: {r.get('url', '')}")
            lines.append(f"  SEO Score: {r.get('seo_score', 0)}")
            lines.append(f"  Issues: {len(r.get('all_issues', []))}")
            lines.append("-" * 40)
        return "\n".join(lines).encode("utf-8")

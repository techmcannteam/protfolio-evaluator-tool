"""Email-safe HTML with inline styles, no remote assets, and escaped content."""

from html import escape

from .config import DISCLAIMER

# Match frontend/assets/evaluator.css; fallbacks keep the theme in email clients
# that do not support the site's web fonts. No font downloads are required.
SERIF = "'Cormorant Garamond',Georgia,serif"
SANS = "Lato,Arial,Helvetica,sans-serif"
RED = "#b40101"


def _money(value):
    return "Unavailable" if value is None else f"${value:,.0f}"


def _cap(value):
    return "Unavailable" if value is None else f"{value:.2%}"


def _paragraph(text, color="#666666"):
    return (
        f'<p style="margin:0 0 24px;color:{color};font-size:15px;'
        f'line-height:26px;overflow-wrap:anywhere;">{escape(str(text))}</p>'
    )


def _heading(text):
    return (
        f'<h2 style="margin:0 0 20px;font-family:{SERIF};font-size:26px;line-height:34px;'
        f'color:#000000;">{escape(text)}</h2>'
    )


def _rows(items, *, financial=True):
    value_style = (
        f"font-family:{SERIF};font-size:20px;line-height:26px;white-space:nowrap;"
        if financial
        else f"font-family:{SANS};font-size:15px;line-height:24px;overflow-wrap:anywhere;"
    )
    rows = "".join(
        '<tr><th scope="row" align="left" valign="top" '
        'style="padding:14px 12px 14px 0;border-bottom:1px solid #e6e6e6;'
        'font-size:14px;line-height:22px;font-weight:400;color:#666666;">'
        f'{escape(str(label))}</th><td align="right" valign="top" '
        'style="padding:14px 0;border-bottom:1px solid #e6e6e6;'
        f'{value_style}font-weight:700;color:#000000;">{escape(str(value))}</td></tr>'
        for label, value in items
    )
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;margin:0 0 28px;">{rows}</table>'
    )


def email_html(result, mode, contact, *, routing=None, agent_link=None):
    """Render owner or internal email; routing is supplied only for the team."""
    internal = routing is not None
    title = f"New {mode} evaluation" if internal else f"Your {mode} evaluation"
    sections = []
    if internal:
        sections.append(_heading("Owner details"))
        sections.append(
            _rows(
                [
                    ("Name", contact["name"]),
                    ("Email", contact["email"]),
                    ("Phone", contact.get("phone") or "Not provided"),
                ],
                financial=False,
            )
        )
        sections.append(_heading("Agent link & routing"))
        sections.append(_paragraph(agent_link))
        sections.append(_paragraph(f"Routing: {routing['kind']} ({routing['status']})"))
    else:
        sections.append(_paragraph(f"Hello {contact['name']},", "#000000"))

    for row in result["properties"]:
        value = row.get("value") or {}
        display = row.get("display_value") or {}
        sections.append(
            '<div style="padding:28px 18px 8px;margin:0 0 32px;'
            'border:1px solid #e6e6e6;text-align:center;">'
        )
        sections.append(_heading(row["address"]))
        sections.append(
            f'<p style="margin:28px 0 12px;color:{RED};font-size:11px;'
            "line-height:20px;letter-spacing:2px;text-transform:uppercase;"
            'font-weight:700;">Most likely value</p>'
            f'<p style="margin:0 0 24px;color:#000000;font-family:{SERIF};font-size:48px;'
            'line-height:54px;font-weight:700;">'
            f"{_money(display.get('most_likely'))}</p>"
        )
        sections.append(
            '<div style="padding:20px;background:#f9f9f9;'
            'margin:0 0 24px;">'
            '<p style="margin:0 0 12px;font-size:14px;line-height:22px;'
            'color:#000000;font-weight:700;">Condition guide</p>'
            f'<p style="margin:0;font-size:15px;line-height:28px;color:#666666;">'
            f"{_money(value.get('low'))} needs work<br>"
            f"{_money(value.get('high'))} renovated / updated</p></div>"
        )
        sections.append(
            _paragraph(
                display.get("explanation", "Whole-building value needs agent review.")
            )
        )
        sections.append(
            _rows(
                [
                    ("Provider estimate", _money(value.get("estimate"))),
                    ("Monthly rent", _money((row.get("rent") or {}).get("estimate"))),
                    ("Cap rate", _cap((row.get("operating") or {}).get("cap_rate"))),
                ]
            )
        )
        sections.extend(_paragraph(warning) for warning in row.get("warnings", []))
        sections.append("</div>")

    totals = result["totals"]
    indicated = [
        row["display_value"]["most_likely"]
        for row in result["properties"]
        if row.get("display_value")
    ]
    sections.append(_heading("Evaluation totals"))
    sections.append(
        _rows(
            [
                (
                    "Properties valued",
                    f"{totals['properties_valued']} of {totals['properties_requested']}",
                ),
                (
                    "Most likely total (available values)",
                    _money(sum(indicated) if indicated else None),
                ),
                (
                    "Provider total (available values)",
                    _money(
                        totals["estimated_value"]
                        if totals["properties_valued"]
                        else None
                    ),
                ),
                ("Total monthly rent", _money(totals["monthly_rent"])),
                (
                    "Cap rate" if mode == "home" else "Portfolio cap rate",
                    _cap(totals["cap_rate"]),
                ),
            ]
        )
    )
    sections.append(
        _paragraph(
            "Cap rates use the provider estimate and operating assumptions; "
            "condition guidance changes only the displayed indication."
        )
    )
    sections.append(
        '<div style="padding:20px;background:#f9f9f9;margin:8px 0 28px;'
        'font-size:13px;line-height:24px;color:#4d4d4d;text-align:center;">'
        f"{escape(DISCLAIMER)}</div>"
    )
    body = "".join(sections)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title></head>
<body style="margin:0;padding:0;background:#f9f9f9;font-family:{SANS};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f9f9f9;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;background:#ffffff;">
<tr><td style="padding:36px 28px;background:#000000;border-bottom:3px solid {RED};text-align:center;">
<p style="margin:0 0 20px;color:#ffffff;font-size:11px;line-height:20px;letter-spacing:2px;">THE MIKE McCANN TEAM</p>
<h1 style="margin:0;font-family:{SERIF};font-size:38px;line-height:44px;color:#ffffff;">{escape(title)}</h1>
</td></tr><tr><td style="padding:32px 28px 8px;">{body}</td></tr>
<tr><td style="padding:32px 24px;background:#000000;color:#ffffff;text-align:center;">
<p style="margin:0 0 12px;font-family:{SERIF};font-size:24px;line-height:30px;font-weight:700;">The Mike McCann Team</p>
<p style="margin:0;color:#bdbdbd;font-size:10px;line-height:20px;letter-spacing:1.5px;">KELLER WILLIAMS EMPOWER · PHILADELPHIA &amp; MAIN LINE</p>
</td></tr>
</table></td></tr></table></body></html>"""

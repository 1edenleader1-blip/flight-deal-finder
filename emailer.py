"""
emailer.py

Builds an HTML summary of this week's flight deals and sends it via
Gmail SMTP using an app password (not your real Gmail password).

Setup: https://myaccount.google.com/apppasswords

Note: Duffel is a booking-platform API, not a metasearch site, so there's
no public "click to book" link to include. Each entry gives you the exact
price, dates, and airline(s) — you then search those same dates on the
airline's site (or Google Flights) to actually book.
"""

import os
import smtplib
import datetime as dt
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _gmail_credentials():
    address = os.environ.get("GMAIL_ADDRESS")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not address or not app_password:
        raise RuntimeError(
            "GMAIL_ADDRESS and/or GMAIL_APP_PASSWORD environment variables "
            "are not set. Add them as GitHub Secrets (see README.md)."
        )
    return address, app_password


def build_html(results_by_search: dict) -> str:
    today_str = dt.date.today().strftime("%d %b %Y")
    sections = []

    for search_name, itineraries in results_by_search.items():
        if not itineraries:
            sections.append(
                f"<h2 style='color:#1a1a1a'>{search_name}</h2>"
                f"<p style='color:#888'>No results found this week.</p>"
            )
            continue

        rows = ""
        for it in itineraries:
            is_self_transfer = it["booking_type"] == "self_transfer"
            badge = (
                "<span style='background:#fff3cd;color:#856404;padding:2px 8px;"
                "border-radius:10px;font-size:12px;margin-left:6px'>2 separate bookings</span>"
                if is_self_transfer else
                "<span style='background:#e6f4ea;color:#1e7e34;padding:2px 8px;"
                "border-radius:10px;font-size:12px;margin-left:6px'>single ticket</span>"
            )
            rows += f"""
            <tr style='border-bottom:1px solid #eee'>
              <td style='padding:10px 8px'>
                <strong style='font-size:16px'>{it['price']:.2f} {it['currency']}</strong>{badge}
              </td>
              <td style='padding:10px 8px'>{it['depart_date']} → {it['return_date']}</td>
              <td style='padding:10px 8px'>{', '.join(it['airlines']) or '—'}</td>
              <td style='padding:10px 8px'>
                {it['stops']} stop(s) total<br>
                <span style='color:#888;font-size:12px'>~{it['duration_hours']}h total flying time</span>
              </td>
            </tr>"""

        sections.append(f"""
        <h2 style='color:#1a1a1a;margin-bottom:4px'>{search_name}</h2>
        <table style='border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:14px'>
          <thead>
            <tr style='background:#f5f5f5;text-align:left'>
              <th style='padding:8px'>Price</th>
              <th style='padding:8px'>Dates</th>
              <th style='padding:8px'>Airline(s)</th>
              <th style='padding:8px'>Stops / Duration</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        """)

    body = "".join(sections)
    return f"""
    <html>
      <body style='font-family:Arial,sans-serif;color:#333;max-width:800px;margin:0 auto'>
        <h1 style='color:#0b5fff'>Weekly Flight Deals — {today_str}</h1>
        {body}
        <p style='color:#999;font-size:12px;margin-top:30px'>
          Fares from the Duffel API, sampled across your search window — verify
          exact price and availability before booking (search these dates
          directly on the airline's site or Google Flights, since there's no
          booking link here). "2 separate bookings" itineraries combine an
          outbound and inbound flight from different airlines as two
          independent tickets — if the first flight is delayed and you miss
          the second, neither airline is obligated to rebook you the way
          they would on a single ticket, so build in a buffer or extra
          travel insurance if you go this route.
        </p>
      </body>
    </html>
    """


def send_email(subject: str, html_body: str, recipients: list[str]):
    from_address, app_password = _gmail_credentials()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(from_address, app_password)
        server.sendmail(from_address, recipients, msg.as_string())

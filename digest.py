import anthropic
import feedparser
import smtplib
import ssl
import requests
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import os
import json
from urllib.parse import quote

# ── Configuration ────────────────────────────────────────────────────────────

CLAUDE_API_KEY      = os.environ["CLAUDE_API_KEY"]
SENDER_EMAIL        = os.environ["SENDER_EMAIL"]
SENDER_PASSWORD     = os.environ["SENDER_PASSWORD"]
SLACK_CHANNEL_EMAIL = os.environ["SLACK_CHANNEL_EMAIL"]
SLACK_WEBHOOK_URL   = os.environ["SLACK_WEBHOOK_URL"]
GITHUB_TOKEN        = os.environ["GITHUB_TOKEN"]
GITHUB_REPO         = os.environ["GITHUB_REPO"]  # e.g. "NanditaSaily/nium-fintech-digest"

COMPETITORS = [
    "Airwallex", "Wise", "Thunes", "Rapyd", "Payoneer", "dLocal",
    "Currencycloud", "Volt", "Modulr", "Stripe", "Adyen", "Checkout.com",
    "Revolut Business", "Brex", "Ebury", "Banking Circle", "TerraPay"
]

RSS_FEEDS = [
    "https://sifted.eu/feed",
    "https://www.finextra.com/rss/headlines.aspx",
    "https://www.pymnts.com/feed/",
    "https://techcrunch.com/category/fintech/feed/",
    "https://fintechnexus.com/feed/",
    "https://news.crunchbase.com/feed/",
    "https://news.google.com/rss/search?q=fintech+acquisition+OR+merger&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=fintech+funding+OR+raises+OR+Series&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=cross-border+payments+news&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=embedded+finance+news&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=fintech+earnings+results&hl=en-US&gl=US&ceid=US:en",
]

for competitor in COMPETITORS:
    encoded = quote(competitor)
    RSS_FEEDS.append(
        f"https://news.google.com/rss/search?q={encoded}+fintech&hl=en-US&gl=US&ceid=US:en"
    )

# ── Fetch News ───────────────────────────────────────────────────────────────

def fetch_news():
    cutoff = datetime.now() - timedelta(days=7)
    articles = []
    seen_titles = set()

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)

                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    import time
                    published = datetime.fromtimestamp(time.mktime(entry.published_parsed))

                if published and published < cutoff:
                    continue

                summary = entry.get("summary", entry.get("description", ""))[:500]
                link = entry.get("link", "")

                articles.append({
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "source": feed.feed.get("title", feed_url),
                    "published": published.strftime("%d %b %Y") if published else "This week"
                })
        except Exception as e:
            print(f"Error fetching {feed_url}: {e}")
            continue

    print(f"Fetched {len(articles)} articles total")
    return articles

# ── Summarise with Claude ─────────────────────────────────────────────────────

def summarise_with_claude(articles):
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    articles = articles[:60]

    articles_text = "\n\n".join([
        f"Title: {a['title']}\nSource: {a['source']}\nDate: {a['published']}\nSummary: {a['summary'][:300]}\nLink: {a['link']}"
        for a in articles
    ])

    competitors_str = ", ".join(COMPETITORS)
    week_str = datetime.now().strftime("%d %B %Y")

    prompt = f"""You are a strategic finance analyst at Nium, a leading B2B cross-border payments and card issuance company.
Your job is to produce a sharp, executive-level weekly fintech intelligence digest for Nium's CEO.

Today's date: {week_str}
Competitors to specifically watch: {competitors_str}

Here are this week's fintech news articles:

{articles_text}

Instructions:
1. Select only the 8-15 most important and relevant stories. Drop anything irrelevant to fintech, payments, FX, card issuance, embedded finance, or B2B financial infrastructure.
2. Categorise each story into one of: M&A, Fundraising, Competitor Moves, Regulatory, Market Signals, Earnings
3. For each story write: a one-line headline, ONE sentence of context (keep it tight — executives want speed), and a "So what for Nium" insight (1 sentence, specific and strategic)
4. For the Earnings section — only include if any tracked competitor published earnings this week. For each company format it as:
   - Company name and period (e.g. "Wise — Q3 FY2026")
   - A metrics table with these columns: Metric, Value, YoY. Include rows for: Revenue, Volume/TPV, Gross Profit, EBITDA margin, Profitability margin, Take rate (if applicable), EV/Revenue multiple. Only include rows where data is available.
   - A one sentence takeaway summarising the key story from the results
   - A "So what for Nium" insight (1 sentence, specific and strategic)
   Leave the earnings array empty [] if no competitor earnings this week.
5. Write a TLDR section — 4-5 bullet points max, one per category, single punchy sentence each. This is the first thing the CEO reads.
6. End with a "One to Watch" wildcard — the most interesting or surprising story.
7. Be direct and concise. Every word must earn its place. Max 1-2 sentences per story.

Format your response as valid JSON with this exact structure:
{{
  "week": "{week_str}",
  "tldr": [
    "M&A: ...",
    "Fundraising: ...",
    "Competitor moves: ...",
    "Regulatory: ...",
    "One to watch: ..."
  ],
  "sections": {{
    "ma": [
      {{"headline": "...", "context": "...", "so_what": "...", "source": "...", "link": "..."}}
    ],
    "fundraising": [
      {{"headline": "...", "context": "...", "so_what": "...", "source": "...", "link": "..."}}
    ],
    "competitor_moves": [
      {{"headline": "...", "context": "...", "so_what": "...", "source": "...", "link": "..."}}
    ],
    "regulatory": [
      {{"headline": "...", "context": "...", "so_what": "...", "source": "...", "link": "..."}}
    ],
    "market_signals": [
      {{"headline": "...", "context": "...", "so_what": "...", "source": "...", "link": "..."}}
    ],
    "earnings": [
      {{
        "company": "...",
        "period": "...",
        "metrics": [
          {{"metric": "Revenue", "value": "...", "yoy": "..."}},
          {{"metric": "Volume/TPV", "value": "...", "yoy": "..."}},
          {{"metric": "Gross profit", "value": "...", "yoy": "..."}},
          {{"metric": "EBITDA margin", "value": "...", "yoy": "..."}},
          {{"metric": "Take rate", "value": "...", "yoy": "..."}},
          {{"metric": "EV / Revenue", "value": "...", "yoy": "..."}}
        ],
        "takeaway": "...",
        "so_what": "...",
        "source": "...",
        "link": "..."
      }}
    ]
  }},
  "one_to_watch": {{
    "headline": "...",
    "context": "...",
    "so_what": "...",
    "source": "...",
    "link": "..."
  }}
}}

Return only valid JSON. No preamble, no markdown, no backticks."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ── Build HTML Report ─────────────────────────────────────────────────────────

def build_html_report(digest, report_url):
    week     = digest["week"]
    sections = digest["sections"]
    otw      = digest["one_to_watch"]
    tldr     = digest.get("tldr", [])

    tldr_items = "".join([
        f'<li style="margin:6px 0;font-size:14px;color:#1a1a1a;line-height:1.6;">{item}</li>'
        for item in tldr
    ])
    tldr_html = f"""
    <div style="padding:20px 28px;border-bottom:1px solid #f0f0f0;background:#f0faf5;">
      <p style="margin:0 0 10px;font-size:12px;font-weight:600;color:#0F6E56;text-transform:uppercase;letter-spacing:0.07em;">⚡ TL;DR — This week in fintech</p>
      <ul style="margin:0;padding-left:18px;">{tldr_items}</ul>
    </div>"""

    section_config = [
        ("ma",              "M&A",               "#E24B4A", "#F09595"),
        ("fundraising",     "Fundraising",        "#185FA5", "#85B7EB"),
        ("competitor_moves","Competitor moves",   "#854F0B", "#FAC775"),
        ("regulatory",      "Regulatory",         "#534AB7", "#AFA9EC"),
        ("market_signals",  "Market signals",     "#0F6E56", "#5DCAA5"),
    ]

    sections_html = ""
    for key, label, dot_color, border_color in section_config:
        items = sections.get(key, [])
        if not items:
            continue

        items_html = ""
        for item in items:
            link_html = f'<a href="{item["link"]}" style="color:{dot_color};font-size:11px;font-weight:500;text-decoration:none;">Read more →</a>' if item.get("link") else ""
            items_html += f"""
            <div style="border-left:3px solid {border_color};padding-left:14px;margin-bottom:16px;border-radius:0;">
              <p style="margin:0;font-size:14px;font-weight:600;color:#1a1a1a;">{item['headline']}</p>
              <p style="margin:6px 0 4px;font-size:13px;color:#444;line-height:1.6;">{item['context']}</p>
              <p style="margin:0 0 4px;font-size:12px;color:{dot_color};font-weight:500;">▸ So what for Nium: {item['so_what']}</p>
              <p style="margin:4px 0 0;font-size:11px;color:#888;">Source: {item.get('source','')} &nbsp; {link_html}</p>
            </div>"""

        sections_html += f"""
        <div style="padding:20px 28px;border-bottom:1px solid #f0f0f0;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">
            <div style="width:9px;height:9px;border-radius:50%;background:{dot_color};flex-shrink:0;"></div>
            <p style="margin:0;font-size:12px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:0.07em;">{label}</p>
          </div>
          {items_html}
        </div>"""

    # Earnings section
    earnings_items = sections.get("earnings", [])
    earnings_html = ""
    if earnings_items:
        earnings_content = ""
        for item in earnings_items:
            metrics_rows = ""
            for i, m in enumerate(item.get("metrics", [])):
                bg = "background:#f9f9f9;" if i % 2 == 1 else ""
                yoy_color = "#3B6D11" if "+" in str(m.get("yoy","")) else ("#A32D2D" if "-" in str(m.get("yoy","")) else "#888")
                metrics_rows += f"""
                <tr style="{bg}">
                  <td style="padding:6px 10px;color:#444;border:0.5px solid #e0e0e0;">{m['metric']}</td>
                  <td style="padding:6px 10px;text-align:right;font-weight:600;color:#1a1a1a;border:0.5px solid #e0e0e0;">{m['value']}</td>
                  <td style="padding:6px 10px;text-align:right;font-weight:500;color:{yoy_color};border:0.5px solid #e0e0e0;">{m['yoy']}</td>
                </tr>"""

            src_link = f'<a href="{item["link"]}" style="color:#3B6D11;font-size:11px;">Source: {item.get("source","")} →</a>' if item.get("link") else f'Source: {item.get("source","")}'
            earnings_content += f"""
            <div style="border-left:3px solid #97C459;padding-left:14px;margin-bottom:24px;border-radius:0;">
              <p style="margin:0 0 12px;font-size:14px;font-weight:600;color:#1a1a1a;">{item.get('company','')} — {item.get('period','')}</p>
              <table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:12px;">
                <thead>
                  <tr style="background:#EAF3DE;">
                    <th style="padding:6px 10px;text-align:left;font-weight:600;color:#3B6D11;border:0.5px solid #C0DD97;">Metric</th>
                    <th style="padding:6px 10px;text-align:right;font-weight:600;color:#3B6D11;border:0.5px solid #C0DD97;">Value</th>
                    <th style="padding:6px 10px;text-align:right;font-weight:600;color:#3B6D11;border:0.5px solid #C0DD97;">YoY</th>
                  </tr>
                </thead>
                <tbody>{metrics_rows}</tbody>
              </table>
              <p style="margin:0 0 4px;font-size:12px;color:#444;line-height:1.6;">{item.get('takeaway','')}</p>
              <p style="margin:6px 0 4px;font-size:12px;color:#3B6D11;font-weight:500;">▸ So what for Nium: {item.get('so_what','')}</p>
              <p style="margin:4px 0 0;font-size:11px;color:#888;">{src_link}</p>
            </div>"""

        earnings_html = f"""
        <div style="padding:20px 28px;border-bottom:1px solid #f0f0f0;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">
            <div style="width:9px;height:9px;border-radius:50%;background:#3B6D11;flex-shrink:0;"></div>
            <p style="margin:0;font-size:12px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:0.07em;">Earnings</p>
          </div>
          {earnings_content}
        </div>"""

    otw_link = f'<a href="{otw["link"]}" style="color:#854F0B;font-size:11px;font-weight:500;text-decoration:none;">Read more →</a>' if otw.get("link") else ""
    otw_html = f"""
    <div style="padding:20px 28px;border-bottom:1px solid #f0f0f0;background:#fffbf0;">
      <p style="margin:0 0 12px;font-size:12px;font-weight:600;color:#854F0B;text-transform:uppercase;letter-spacing:0.07em;">⚑ One to watch</p>
      <div style="border-left:3px solid #FAC775;padding-left:14px;border-radius:0;">
        <p style="margin:0;font-size:14px;font-weight:600;color:#1a1a1a;">{otw['headline']}</p>
        <p style="margin:6px 0 4px;font-size:13px;color:#444;line-height:1.6;">{otw['context']}</p>
        <p style="margin:0 0 4px;font-size:12px;color:#854F0B;font-weight:500;">▸ So what for Nium: {otw['so_what']}</p>
        <p style="margin:4px 0 0;font-size:11px;color:#888;">Source: {otw.get('source','')} &nbsp; {otw_link}</p>
      </div>
    </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta property="og:title" content="Nium Fintech Intel — Week of {week}">
  <meta property="og:description" content="Weekly fintech & competitor intelligence digest for Nium leadership.">
  <meta property="og:image" content="https://logo.clearbit.com/nium.com">
  <title>Nium Fintech Intel — Week of {week}</title>
</head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:660px;margin:24px auto;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e8e8e8;">

    <div style="background:#0F6E56;padding:24px 28px;">
      <p style="margin:0;font-size:11px;color:#9FE1CB;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;">Weekly intelligence · Nium</p>
      <p style="margin:6px 0 0;font-size:22px;font-weight:600;color:#ffffff;">Fintech & Competitor Digest</p>
      <p style="margin:6px 0 0;font-size:13px;color:#9FE1CB;">Week of {week} · Auto-generated every Friday</p>
    </div>

    {tldr_html}
    {sections_html}
    {earnings_html}
    {otw_html}

    <div style="padding:16px 28px;background:#fafafa;text-align:center;">
      <p style="margin:0;font-size:11px;color:#aaa;">Auto-generated by Nium Intelligence · Powered by Claude AI<br>
      Sources: Sifted · Finextra · TechCrunch · PYMNTS · Crunchbase News · Google News</p>
    </div>

  </div>
</body>
</html>"""
    return html

# ── Publish to GitHub Pages ───────────────────────────────────────────────────

def publish_to_github_pages(html_content, week):
    filename = "docs/index.html"
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # Check if file exists to get its SHA
    sha = None
    response = requests.get(api_url, headers=headers)
    if response.status_code == 200:
        sha = response.json().get("sha")

    content_b64 = base64.b64encode(html_content.encode("utf-8")).decode("utf-8")

    payload = {
        "message": f"Weekly digest — {week}",
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha

    response = requests.put(api_url, headers=headers, json=payload)
    if response.status_code in (200, 201):
        repo_name = GITHUB_REPO.split("/")[1]
        username = GITHUB_REPO.split("/")[0]
        report_url = f"https://{username}.github.io/{repo_name}/"
        print(f"Published to GitHub Pages: {report_url}")
        return report_url
    else:
        print(f"Failed to publish: {response.status_code} {response.text}")
        return None

# ── Post to Slack via Webhook ─────────────────────────────────────────────────

def post_to_slack(digest, report_url):
    week = digest["week"]
    tldr = digest.get("tldr", [])

    tldr_text = "\n".join([f"• {item}" for item in tldr])

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📊 Fintech & Competitor Intel — Week of {week}",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*⚡ TL;DR — This week in fintech*\n{tldr_text}"
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"📋 *Full digest with detailed analysis, source links, earnings tables and So what for Nium insights:*\n<{report_url}|👉 Read the full report here>"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Auto-generated every Friday · Powered by Claude AI · Sources: Sifted, Finextra, TechCrunch, PYMNTS, Crunchbase News"
                }
            ]
        }
    ]

    payload = {"blocks": blocks}
    response = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if response.status_code == 200:
        print("Posted to Slack successfully")
    else:
        print(f"Slack post failed: {response.status_code} {response.text}")

# ── Send Email to Slack channel (backup) ─────────────────────────────────────

def send_email(html_content, week):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Fintech & Competitor Intel — Week of {week}"
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = SLACK_CHANNEL_EMAIL
    msg.attach(MIMEText(html_content, "html"))

    smtp_server = "smtp.gmail.com" if "gmail" in SENDER_EMAIL.lower() else "smtp.office365.com"
    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_server, 587) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, SLACK_CHANNEL_EMAIL, msg.as_string())
    print("Email sent to Slack channel")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Starting Fintech Digest — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    print("Fetching news...")
    articles = fetch_news()
    if not articles:
        print("No articles found. Exiting.")
        return

    print(f"Summarising {len(articles)} articles with Claude...")
    digest = summarise_with_claude(articles)

    print("Publishing to GitHub Pages...")
    report_url = publish_to_github_pages(
        build_html_report(digest, ""),
        digest["week"]
    )

    if report_url:
        print("Building final report with URL...")
        html = build_html_report(digest, report_url)
        # Re-publish with correct URL embedded
        publish_to_github_pages(html, digest["week"])

        print("Posting TL;DR to Slack via webhook...")
        post_to_slack(digest, report_url)

    print("Done!")

if __name__ == "__main__":
    main()

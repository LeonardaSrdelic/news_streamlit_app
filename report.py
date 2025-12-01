import os
import smtplib
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List

import feedparser


# RSS izvori (isti koncept kao u app.py; prosiri po potrebi)
RSS_FEEDS: Dict[str, str] = {
    "N1": "https://n1info.hr/feed/",
    "Index": "https://www.index.hr/rss",
    "Jutarnji": "https://www.jutarnji.hr/rss",
    "Vecernji": "https://www.vecernji.hr/rss",
    "Tportal": "https://www.tportal.hr/rss",
    "Poslovni": "https://www.poslovni.hr/feed",
}

# Tematski profili; koristi sve zajedno kao bazne kljucne rijeci
KEYWORD_PROFILES: Dict[str, List[str]] = {
    "Porezi i proracun": [
        "porezna reforma",
        "porez na dohodak",
        "porez na dobit",
        "pdv",
        "proracun",
        "fiskalna politika",
    ],
    "Mirovine i socijalna politika": [
        "mirovinska reforma",
        "mirovinski sustav",
        "socijalna pomoc",
        "djecji doplatak",
        "minimalna placa",
        "zaposljavanje",
    ],
    "Klimatske politike i energija": [
        "klimatska politika",
        "co2",
        "ugljicna taksa",
        "obnovljivi izvori",
        "energija",
        "energetska tranzicija",
    ],
    "Subvencije i drzavne potpore": [
        "subvencije",
        "drzavne potpore",
        "potpore poduzecima",
        "nacionalni plan oporavka",
        "europski fondovi",
        "eu fondovi",
    ],
}


def presscut_score(
    title: str,
    summary: str,
    base_keywords: List[str],
    must_have: List[str],
    nice_to_have: List[str],
    exclude: List[str],
    published_at: datetime,
    ref_date: date,
) -> int | None:
    """
    Score s tezinama za naslov/sazetak i bonusom za svjezinu.
    """
    title = title or ""
    summary = summary or ""

    t_title = title.lower()
    t_summary = summary.lower()

    for w in exclude:
        lw = w.lower()
        if lw in t_title or lw in t_summary:
            return None

    for w in must_have:
        lw = w.lower()
        if lw not in t_title and lw not in t_summary:
            return None

    score = 0
    base_hit = False
    nice_hit = False

    def count_hits(text: str, word: str) -> int:
        return text.count(word.lower())

    for w in must_have:
        lw = w.lower()
        score += count_hits(t_title, lw) * 5
        score += count_hits(t_summary, lw) * 3

    for w in base_keywords:
        lw = w.lower()
        hits_title = count_hits(t_title, lw)
        hits_summary = count_hits(t_summary, lw)
        if hits_title or hits_summary:
            base_hit = True
        score += hits_title * 3
        score += hits_summary * 2

    for w in nice_to_have:
        lw = w.lower()
        hits_title = count_hits(t_title, lw)
        hits_summary = count_hits(t_summary, lw)
        if hits_title or hits_summary:
            nice_hit = True
        score += hits_title * 2
        score += hits_summary * 1

    if not must_have and not (base_hit or nice_hit):
        return None

    age_days = (ref_date - published_at.date()).days
    if age_days < 0:
        age_days = 0
    score += max(0, 5 - age_days)

    return score if score > 0 else None


def normalize_datetime(entry) -> datetime:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6])
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime(*entry.updated_parsed[:6])
    return datetime.utcnow()


def fetch_articles(
    date_from: date,
    date_to: date,
    keywords: List[str],
    must_have: List[str],
    nice_to_have: List[str],
    exclude: List[str],
) -> List[dict]:
    ref_date = date_to
    results: List[dict] = []

    for source, url in RSS_FEEDS.items():
        feed = feedparser.parse(url)

        for entry in feed.entries:
            pub_dt = normalize_datetime(entry)
            if not (date_from <= pub_dt.date() <= date_to):
                continue

            title = getattr(entry, "title", "") or ""
            summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""

            score = presscut_score(
                title=title,
                summary=summary,
                base_keywords=keywords,
                must_have=must_have,
                nice_to_have=nice_to_have,
                exclude=exclude,
                published_at=pub_dt,
                ref_date=ref_date,
            )

            if score is None:
                continue

            link = getattr(entry, "link", "") or ""

            results.append(
                {
                    "source": source,
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "published": pub_dt,
                    "score": score,
                }
            )

    results.sort(key=lambda x: (x["score"], x["published"]), reverse=True)
    return results


def build_html_report(articles: List[dict], date_from: date, date_to: date) -> str:
    html: List[str] = []
    html.append("<html><body>")
    html.append(f"<h2>Dnevni pregled vijesti ({date_from} — {date_to})</h2>")
    if not articles:
        html.append("<p>Nema pronadenih clanaka.</p>")
        html.append("</body></html>")
        return "\n".join(html)

    html.append("<ol>")
    for art in articles:
        html.append("<li>")
        html.append(f'<p><strong><a href="{art["link"]}">{art["title"]}</a></strong></p>')
        meta = []
        if art.get("source"):
            meta.append(art["source"])
        if art.get("published"):
            meta.append(art["published"].strftime("%Y-%m-%d %H:%M"))
        meta.append(f"Score: {art['score']}")
        html.append("<p>" + " | ".join(meta) + "</p>")
        if art.get("summary"):
            html.append(f"<p>{art['summary']}</p>")
        html.append("</li><hr>")
    html.append("</ol>")
    html.append("</body></html>")
    return "\n".join(html)


def send_email(html_body: str, subject: str):
    sender = os.environ["EMAIL_SENDER"]
    recipient = os.environ["EMAIL_RECIPIENT"]
    smtp_server = os.environ["SMTP_SERVER"]
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_username = os.environ["SMTP_USERNAME"]
    smtp_password = os.environ["SMTP_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.sendmail(sender, [recipient], msg.as_string())


def main():
    date_to = date.today()
    date_from = date_to - timedelta(days=1)

    base_keywords: List[str] = []
    for words in KEYWORD_PROFILES.values():
        base_keywords.extend(words)

    must_have: List[str] = []
    nice_to_have: List[str] = ["hnb", "vlada", "sabor", "ek"]
    exclude: List[str] = ["sport", "nogomet", "rukomet"]

    articles = fetch_articles(
        date_from=date_from,
        date_to=date_to,
        keywords=base_keywords,
        must_have=must_have,
        nice_to_have=nice_to_have,
        exclude=exclude,
    )

    html = build_html_report(articles, date_from, date_to)
    send_email(html, subject="Dnevni pregled vijesti")


if __name__ == "__main__":
    main()

import os
import smtplib
import re
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List
from urllib.parse import urljoin, urlparse
from io import BytesIO

import feedparser
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

MIN_SCORE = 23


# RSS izvori (isti koncept kao u app.py; prosiri po potrebi)
# Širi popis iz app.py (HR portali + HRT + Slobodna)
RSS_FEEDS: Dict[str, str] = {
    # Opći i vijesti
    "N1": "https://n1info.hr/feed/",
    "Index Vijesti": "https://www.index.hr/rss/vijesti",
    "Index Novac": "https://www.index.hr/rss/vijesti-novac",
    "Jutarnji Vijesti": "http://www.jutarnji.hr/rss",
    "Vecernji": "https://www.vecernji.hr/rss",
    "Tportal": "https://www.tportal.hr/rss",
    "24sata News": "https://www.24sata.hr/feeds/news.xml",
    # Biznis/ekonomija
    "Poslovni": "https://www.poslovni.hr/feed",
    "Lider": "https://lidermedia.hr/rss",
    # Slobodna Dalmacija sekcije
    "Slobodna Vijesti": "https://slobodnadalmacija.hr/feed/category/119",
    "Slobodna Biznis": "https://slobodnadalmacija.hr/feed/category/244",
    # HRT
    "HRT Vijesti": "https://vijesti.hrt.hr/rss",
    # Vladini i EU izvori (ako su dostupni)
    "Vlada RH": "https://vlada.gov.hr/rss",
    "EU Komunikacije": "https://ec.europa.eu/commission/presscorner/home/en/rss.xml",
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
        "porezni prihodi",
        "porezni rasterecenje",
        "porezne olaksice",
        "trosarine",
        "doprinosi",
        "proracunski deficit",
        "proracunski prihodi",
        "javne financije",
        "fiskalna pravila",
    ],
    "Mirovine i socijalna politika": [
        "mirovinska reforma",
        "mirovinski sustav",
        "socijalna pomoc",
        "djecji doplatak",
        "minimalna placa",
        "zaposljavanje",
    ],
    "Klimatske promjene, kruzna ekonomija i energija": [
        "klimatska politika",
        "klimatske promjene",
        "co2",
        "porez na ugljik",
        "ugljicni porez",
        "obnovljivi izvori",
        "obnovljiva energija",
        "energija",
        "energetska tranzicija",
        "odrzivi razvoj",
        "zelena tranzicija",
        "eu ets",
        "niskougljicni rast",
        "niskoemisijski rast",
        "klimatska neutralnost",
        "cop",
        "kruzna ekonomija",
        "plava ekonomija",
        "bioraznolikost",
        "dekarbonizacija",
        "emisije staklenickih plinova",
        "ugljicni otisak",
    ],
    "Subvencije i drzavne potpore": [
        "subvencije",
        "drzavne potpore",
        "potpore poduzecima",
        "nacionalni plan oporavka",
        "europski fondovi",
        "eu fondovi",
    ],
    "Europodrucje i monetarna politika": [
        "europodrucje",
        "eurozona",
        "europska sredisnja banka",
        "esb",
        "ecb",
        "monetarna politika",
        "kamatne stope",
        "inflacija",
        "euribor",
        "tecaj eura",
        "europski semestar",
    ],
    "Geopolitika i sigurnost": [
        "geopolitika",
        "geopoliticko okruzenje",
        "rat",
        "rat u ukrajini",
        "ukrajina",
        "rusija",
        "sankcije",
        "nato",
        "europska sigurnost",
        "donald trump",
        "trump",
        "sjedinjene drzave",
        "sad izbori",
        "globalna sigurnost",
    ],
}

GOV_PAGES = [
    "https://vlada.gov.hr/vijesti/8",
    "https://vlada.gov.hr/istaknute-teme/odrzivi-razvoj/14969",
]

GOV_MANUAL_DOCS = [
    "https://vlada.gov.hr/UserDocsImages/Vijesti/2025/Studeni/20_studenoga/III._sjednica_Nacionalnog_vijeca_za_odrzivi_razvoj.pdf",
]


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


def guess_pub_date_from_url(url: str) -> datetime:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    year = None
    month = None
    day = None

    months = {
        "sijecanj": 1, "veljaca": 2, "ozujak": 3, "travanj": 4, "svibanj": 5, "lipanj": 6,
        "srpanj": 7, "kolovoz": 8, "rujan": 9, "listopad": 10, "studeni": 11, "prosinac": 12,
    }
    for p in parts:
        if p.isdigit() and len(p) == 4 and p.startswith("20"):
            year = int(p)
        lower = p.lower()
        if lower in months:
            month = months[lower]
        if "_" in p or "-" in p:
            for token in p.replace("-", "_").split("_"):
                if token.isdigit():
                    day = int(token)
                    break
    if not (year and month and day):
        m = re.search(r"(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})", url)
        if m:
            try:
                year = int(m.group(1))
                month = int(m.group(2))
                day = int(m.group(3))
            except Exception:
                pass
    try:
        if year and month and day:
            return datetime(year, month, day)
        if year and month:
            return datetime(year, month, 1)
    except Exception:
        pass
    return datetime.min


def extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article") or soup.find("main") or soup
    for tag in article.find_all(["script", "style", "nav", "footer", "header", "form"]):
        tag.decompose()
    text = article.get_text(separator=" ", strip=True)
    words = text.split()
    return " ".join(words)


def clean_html_text(text: str) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    for img in soup.find_all("img"):
        img.decompose()
    return soup.get_text(separator=" ", strip=True)


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
            summary_raw = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
            summary = clean_html_text(summary_raw)

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


def fetch_gov_articles(
    date_from: date,
    date_to: date,
    keywords: List[str],
    must_have: List[str],
    nice_to_have: List[str],
    exclude: List[str],
) -> List[dict]:
    ref_date = date_to
    results: List[dict] = []
    seen_links = set()

    paginated_urls: List[str] = []
    for base in GOV_PAGES:
        paginated_urls.append(base)
        for p in range(1, 6):
            paginated_urls.append(f"{base}?page={p}")

    for base_url in paginated_urls:
        try:
            resp = requests.get(base_url, timeout=20)
            resp.raise_for_status()
        except Exception:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full_url = urljoin(base_url, href)
            title = a.get_text(strip=True) or full_url

            if full_url in seen_links:
                continue
            seen_links.add(full_url)

            lower_title = title.lower()
            if lower_title in {"vijesti", "pristupacnost", "preskoci na glavni sadrzaj"}:
                continue

            is_pdf = full_url.lower().endswith(".pdf")
            if ("vlada.gov.hr" not in full_url) and not is_pdf:
                continue
            if not is_pdf:
                if ("/vijesti/" not in full_url) and ("UserDocsImages" not in full_url):
                    continue
                if "?page=" in full_url:
                    continue
            if len(title) < 5 or "preskoci" in title.lower():
                continue
            if full_url.rstrip("/") in {"https://vlada.gov.hr", "https://vlada.gov.hr/"}:
                continue

            pub_dt = guess_pub_date_from_url(full_url)
            if not (date_from <= pub_dt.date() <= date_to):
                continue

            summary = ""
            if is_pdf:
                try:
                    pdf_resp = requests.get(full_url, timeout=30)
                    pdf_resp.raise_for_status()
                    reader = PdfReader(BytesIO(pdf_resp.content))
                    pages_text = []
                    for page in reader.pages[:6]:
                        pages_text.append(page.extract_text() or "")
                    summary = " ".join(pages_text)
                except Exception:
                    summary = ""
            else:
                try:
                    page_resp = requests.get(full_url, timeout=20)
                    page_resp.raise_for_status()
                    summary = extract_text_from_html(page_resp.text)
                except Exception:
                    summary = ""

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

            results.append(
                {
                    "source": "Vlada/EU",
                    "title": title,
                    "link": full_url,
                    "summary": summary,
                    "published": pub_dt,
                    "score": score,
                }
            )

    for url in GOV_MANUAL_DOCS:
        pub_dt = guess_pub_date_from_url(url)
        if not (date_from <= pub_dt.date() <= date_to):
            continue
        title = url.rsplit("/", 1)[-1]
        score = presscut_score(
            title=title,
            summary="",
            base_keywords=keywords,
            must_have=must_have,
            nice_to_have=nice_to_have,
            exclude=exclude,
            published_at=pub_dt,
            ref_date=ref_date,
        )
        if score is None:
            continue
        results.append(
            {
                "source": "Vlada/EU",
                "title": title,
                "link": url,
                "summary": "",
                "published": pub_dt,
                "score": score,
            }
        )

    results.sort(key=lambda x: (x["score"], x["published"]), reverse=True)
    return results


def build_html_report(articles: List[dict], date_from: date, date_to: date) -> str:
    def summarize(text: str, limit: int = 60) -> str:
        words = (text or "").split()
        if len(words) <= limit:
            return " ".join(words)
        return " ".join(words[:limit]) + " …"

    # grupiranje po profilu (dodijeli prvi koji pogodi)
    buckets = {p: [] for p in KEYWORD_PROFILES.keys()}
    buckets["Ostalo"] = []
    for art in articles:
        text = (art.get("title", "") + " " + art.get("summary", "")).lower()
        target_profile = None
        for profile, kws in KEYWORD_PROFILES.items():
            hits = sum(1 for k in kws if k.lower() in text)
            if hits >= 1:
                target_profile = profile
                break
        if target_profile:
            buckets[target_profile].append(art)
        else:
            buckets["Ostalo"].append(art)

    html: List[str] = []
    html.append("<html><body>")
    html.append(f"<h2>Dnevni pregled vijesti ({date_from} — {date_to})</h2>")

    total = sum(len(v) for v in buckets.values())
    html.append(f"<p>Ukupno članka: {total}</p>")

    for profile, items in buckets.items():
        if not items:
            continue
        html.append(f"<h3>{profile}</h3>")
        html.append("<ol>")
        for a in items:
            html.append("<li>")
            html.append(f'<p><strong><a href="{a["link"]}">{a["title"]}</a></strong></p>')
            meta = []
            if a.get("source"):
                meta.append(a["source"])
            if a.get("published"):
                meta.append(a["published"].strftime("%Y-%m-%d %H:%M"))
            meta.append(f"Score: {a['score']}")
            html.append("<p>" + " | ".join(meta) + "</p>")
            html.append(f"<p>{summarize(a.get('summary', ''), limit=80)}</p>")
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
    # Ponedjeljkom pokrij petak-subotu-nedjelju-ponedjeljak, ostale dane zadnjih 24h
    if date_to.weekday() == 0:  # Monday
        date_from = date_to - timedelta(days=3)
    else:
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

    gov_articles = fetch_gov_articles(
        date_from=date_from,
        date_to=date_to,
        keywords=base_keywords,
        must_have=must_have,
        nice_to_have=nice_to_have,
        exclude=exclude,
    )
    if gov_articles:
        seen = {a["link"] for a in articles}
        for g in gov_articles:
            if g["link"] not in seen:
                articles.append(g)
                seen.add(g["link"])
        articles.sort(key=lambda x: (x["score"], x["published"]), reverse=True)

    # minimalni score filter
    articles = [a for a in articles if a.get("score", 0) >= MIN_SCORE]

    html = build_html_report(articles, date_from, date_to)
    send_email(html, subject="Dnevni pregled vijesti")


if __name__ == "__main__":
    main()

import calendar
import os
import smtplib
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List
from urllib.parse import urljoin, urlparse
from io import BytesIO

import feedparser
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import create_engine

# Ako budemo ponovno trebali web/Serper modul, importi ostaju.
from newsmonitor.blog import BlogPost, fetch_blog_posts
from newsmonitor.search import search_for_reposts
from newsmonitor.utils import estimate_reading_time

DB_PATH = "articles.db"
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)

# Tematski profili za presscut stil praćenja vijesti.
KEYWORD_PROFILES = {
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
        "porez na ugljik",
        "ugljicni porez",
        "obnovljivi izvori",
        "energija",
        "energetska tranzicija",
        "odrzivi razvoj",
        "zelena tranzicija",
        "eu ets",
        "niskougljicni rast",
        "niskoemisijski rast",
        "klimatska neutralnost",
        "cop",
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

# RSS izvori hrvatskih portala; lako prosirivo.
RSS_FEEDS = {
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

# Dodatne vladine/EU stranice (bez RSS) koje cemo scrapati za PDF/objave
GOV_PAGES = [
    "https://vlada.gov.hr/vijesti/8",
    "https://vlada.gov.hr/istaknute-teme/odrzivi-razvoj/14969",
]

# Manualni vladini dokumenti koje zelimo ukljuciti (npr. PDF objave)
GOV_MANUAL_DOCS = [
    "https://vlada.gov.hr/UserDocsImages/Vijesti/2025/Studeni/20_studenoga/III._sjednica_Nacionalnog_vijeca_za_odrzivi_razvoj.pdf",
]


def parse_list(text: str) -> List[str]:
    return [w.strip() for w in text.split(",") if w.strip()]


def save_articles_to_db(articles):
    if not articles:
        return
    df = pd.DataFrame(articles)
    if "matched_url" in df.columns:
        df.drop_duplicates(subset=["matched_url"], inplace=True)
    elif "link" in df.columns:
        df.drop_duplicates(subset=["link"], inplace=True)
    df["fetched_at"] = datetime.utcnow()
    df.to_sql("articles", engine, if_exists="append", index=False)


def load_articles_from_db():
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    try:
        return pd.read_sql("SELECT * FROM articles", engine)
    except Exception:
        return pd.DataFrame()


def load_rss_from_db(date_from: date, date_to: date, sources: List[str]) -> List[dict]:
    if not os.path.exists(DB_PATH):
        return []
    try:
        df = pd.read_sql(
            "SELECT * FROM articles WHERE date(published_at) BETWEEN :d_from AND :d_to",
            engine,
            params={"d_from": date_from.isoformat(), "d_to": date_to.isoformat()},
            parse_dates=["published_at", "fetched_at"],
        )
    except Exception:
        return []

    if sources:
        df = df[df["source"].isin(sources)]

    return df.to_dict(orient="records")


def build_html_report(articles, date_from, date_to, selected_profiles, all_keywords):
    """Gradnja jednostavnog HTML izvjestaja od clanaka."""
    period_str = f"{date_from.isoformat()} do {date_to.isoformat()}"
    profiles_str = ", ".join(selected_profiles) if selected_profiles else "bez profila"

    html_parts = []

    html_parts.append("<html><body>")
    html_parts.append("<h2>Dnevni pregled vijesti</h2>")
    html_parts.append(f"<p>Razdoblje: {period_str}</p>")
    html_parts.append(f"<p>Profili: {profiles_str}</p>")
    html_parts.append(
        "<p>Aktivne kljucne rijeci: "
        + ", ".join(sorted(set(all_keywords)))
        + "</p>"
    )

    if not articles:
        html_parts.append("<p>Nema pronadenih clanaka za zadane kriterije.</p>")
        html_parts.append("</body></html>")
        return "\n".join(html_parts)

    html_parts.append("<hr>")
    html_parts.append("<ol>")

    for art in articles:
        title = art.get("title", "")
        link = art.get("link", "")
        source = art.get("source", "")
        published_at = art.get("published_at")
        score = art.get("score", "")
        summary = art.get("summary", "")

        date_str = published_at.strftime("%Y-%m-%d %H:%M") if published_at else ""

        html_parts.append("<li>")
        html_parts.append(
            f'<p><strong><a href="{link}">{title}</a></strong></p>'
        )
        meta_items = []
        if source:
            meta_items.append(f"Izvor: {source}")
        if date_str:
            meta_items.append(f"Objavljeno: {date_str}")
        if score != "":
            meta_items.append(f"Score: {score}")
        if meta_items:
            html_parts.append("<p>" + "  |  ".join(meta_items) + "</p>")

        if summary:
            html_parts.append(f"<p>{summary}</p>")

        html_parts.append("</li>")
        html_parts.append("<hr>")

    html_parts.append("</ol>")
    html_parts.append("</body></html>")

    return "\n".join(html_parts)


def send_email_report(subject: str, html_body: str):
    """Slanje HTML izvjestaja emailom koristeci podatke iz st.secrets."""
    sender = st.secrets.get("EMAIL_SENDER")
    recipient = st.secrets.get("EMAIL_RECIPIENT")
    smtp_server = st.secrets.get("SMTP_SERVER")
    smtp_port = int(st.secrets.get("SMTP_PORT", 587))
    smtp_username = st.secrets.get("SMTP_USERNAME")
    smtp_password = st.secrets.get("SMTP_PASSWORD")

    missing = [
        name
        for name, value in [
            ("EMAIL_SENDER", sender),
            ("EMAIL_RECIPIENT", recipient),
            ("SMTP_SERVER", smtp_server),
            ("SMTP_USERNAME", smtp_username),
            ("SMTP_PASSWORD", smtp_password),
        ]
        if not value
    ]
    if missing:
        st.error(
            "Nedostaju postavke u secrets.toml: "
            + ", ".join(missing)
        )
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    part_html = MIMEText(html_body, "html", "utf-8")
    msg.attach(part_html)

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(sender, [recipient], msg.as_string())
        st.success(f"Email izvjestaj poslan na {recipient}.")
    except Exception as e:
        st.error(f"Greska pri slanju emaila: {e}")


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
    Vraca brojcani score clanka ili None ako treba biti izbacen.
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
        hits_title = count_hits(t_title, lw)
        hits_summary = count_hits(t_summary, lw)
        score += hits_title * 5
        score += hits_summary * 3

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

    # Striktno: ako nema obveznih, zahtijevaj barem jedan pogodak iz temeljnih.
    if not must_have and not base_hit:
        return None

    age_days = (ref_date - published_at.date()).days
    if age_days < 0:
        age_days = 0
    recency_bonus = max(0, 5 - age_days)

    score += recency_bonus

    return score if score > 0 else None


def guess_pub_date_from_url(url: str) -> datetime:
    """
    Gruba heuristika za datume u URL-u vlade (npr. .../2025/Studeni/20_studenoga/...)
    Ako ne uspije, vrati utcnow.
    """
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    year = None
    month = None
    day = None

    # mapiranje hrvatskih mjeseci
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
        # dan iz recimo "20_studenoga"
        if "_" in p or "-" in p:
            for token in p.replace("-", "_").split("_"):
                if token.isdigit():
                    day = int(token)
                    break

    try:
        if year and month and day:
            return datetime(year, month, day)
        if year and month:
            return datetime(year, month, 1)
    except Exception:
        pass
    return datetime.utcnow()


def extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article") or soup.find("main") or soup
    for tag in article.find_all(["script", "style", "nav", "footer", "header", "form"]):
        tag.decompose()
    text = article.get_text(separator=" ", strip=True)
    words = text.split()
    return " ".join(words)


def normalize_datetime(entry) -> datetime:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime.fromtimestamp(calendar.timegm(entry.published_parsed))
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime.fromtimestamp(calendar.timegm(entry.updated_parsed))
    if hasattr(entry, "published") and entry.published:
        try:
            return datetime.fromisoformat(entry.published)
        except Exception:
            pass
    return datetime.utcnow()


def search_rss_articles(
    keywords: List[str],
    date_from: date,
    date_to: date,
    sources: List[str],
    must_have: List[str],
    nice_to_have: List[str],
    exclude: List[str],
) -> List[dict]:
    """
    Pretrazuje zadane RSS kanale i vraca listu clanaka koji zadovoljavaju:
      datum objave u zadanom rasponu (ukljucivo)
      Presscut stil filtriranja i bodovanja s tezinama za naslov i svjezinu
    """
    results: List[dict] = []
    ref_date = date_to

    for source_name in sources:
        feed_url = RSS_FEEDS.get(source_name)
        if not feed_url:
            continue

        feed = feedparser.parse(feed_url)

        for entry in feed.entries:
            pub_dt = normalize_datetime(entry)
            pub_date = pub_dt.date()

            if pub_date < date_from or pub_date > date_to:
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
                    "title": title,
                    "link": link,
                    "source": source_name,
                    "published_at": pub_dt,
                    "summary": summary,
                    "score": score,
                }
            )

    results.sort(key=lambda x: (x["score"], x["published_at"]), reverse=True)
    return results


def search_gov_pages(
    keywords: List[str],
    date_from: date,
    date_to: date,
    must_have: List[str],
    nice_to_have: List[str],
    exclude: List[str],
) -> List[dict]:
    """
    Scrape vladinih stranica (s paginacijom) za linkove na vijesti/PDF i presscut filtriranje.
    """
    results: List[dict] = []
    ref_date = date_to
    seen_links = set()

    # proširi paginaciju za vlada.gov.hr vijesti (par stranica)
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

            is_pdf = full_url.lower().endswith(".pdf")
            # dozvoli vlada.gov.hr vijesti ili UserDocsImages PDF
            if ("vlada.gov.hr" not in full_url) and not is_pdf:
                continue
            if not is_pdf:
                if ("/vijesti/" not in full_url) and ("UserDocsImages" not in full_url):
                    continue
            if len(title) < 5:
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
                    "title": title,
                    "link": full_url,
                    "source": "Vlada/EU",
                    "published_at": pub_dt,
                    "summary": summary,
                    "score": score,
                }
            )

    # Manualni linkovi (npr. specificni PDF-ovi)
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
                "title": title,
                "link": url,
                "source": "Vlada/EU",
                "published_at": pub_dt,
                "summary": "",
                "score": score,
            }
        )

    results.sort(key=lambda x: (x["score"], x["published_at"]), reverse=True)
    return results


def render_rss_mode():
    st.subheader("Presscut stil pracenja vijesti (RSS)")

    today = date.today()
    default_from = today - timedelta(days=2)

    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("Datum od", value=default_from)
    with col2:
        date_to = st.date_input("Datum do", value=today)

    mode = st.radio(
        "Nacin rada",
        options=["Dohvati svjeze iz RSS-a", "Koristi arhivu (SQLite)"],
        index=0,
        help="Live pretraga ili citanje iz arhive spremljene u SQLite.",
    )

    selected_sources = st.multiselect(
        "Izvori vijesti (RSS)",
        options=list(RSS_FEEDS.keys()),
        default=list(RSS_FEEDS.keys()),
    )

    selected_profiles = st.multiselect(
        "Tematski profili (odaberi jedan ili vise)",
        options=list(KEYWORD_PROFILES.keys()),
        default=list(KEYWORD_PROFILES.keys()),
    )

    extra_keywords_text = st.text_input(
        "Dodatne kljucne rijeci (zarezima odvojeno)",
        value="",
    )

    all_keywords: List[str] = []
    for prof in selected_profiles:
        all_keywords.extend(KEYWORD_PROFILES.get(prof, []))

    if extra_keywords_text.strip():
        extra_keywords = [k.strip() for k in extra_keywords_text.split(",") if k.strip()]
        all_keywords.extend(extra_keywords)

    with st.expander("Prikazi aktivne kljucne rijeci"):
        st.write(sorted(set(all_keywords)))

    st.subheader("Napredno filtriranje u Presscut stilu")

    must_have_text = st.text_input(
        "Obvezne rijeci (mora se pojaviti SVAKA, odvojene zarezima)",
        value="porezna reforma, mirovinska reforma",
        help="Ako je prazno, nijedna rijec nije obvezna.",
    )

    nice_to_have_text = st.text_input(
        "Pozeljne rijeci (povecavaju relevantnost, ali nisu obvezne)",
        value="HNB, Europska komisija, Vlada, Sabor",
        help="Clanci s ovim rijecima rangirat ce se vise.",
    )

    exclude_text = st.text_input(
        "Iskljucene rijeci (ako se pojave, clanak se izbacuje)",
        value="sport, nogomet, rukomet",
        help="Koristi za filtriranje sportskih i slicnih nerelevantnih vijesti.",
    )

    must_have_words = parse_list(must_have_text)
    nice_to_have_words = parse_list(nice_to_have_text)
    exclude_words = parse_list(exclude_text)

    save_to_db = st.checkbox("Spremi rezultate u bazu (SQLite)", value=True)

    if st.button("Pretrazi vijesti"):
        articles: List[dict] = []

        if mode == "Koristi arhivu (SQLite)":
            stored = load_rss_from_db(date_from=date_from, date_to=date_to, sources=selected_sources)
            if not stored:
                st.warning("Arhiva je prazna za zadani raspon ili izvore.")
                return

            ref_date = date_to
            for art in stored:
                pub_dt = pd.to_datetime(art.get("published_at", datetime.utcnow()))
                score = presscut_score(
                    title=art.get("title", ""),
                    summary=art.get("summary", ""),
                    base_keywords=all_keywords,
                    must_have=must_have_words,
                    nice_to_have=nice_to_have_words,
                    exclude=exclude_words,
                    published_at=pub_dt,
                    ref_date=ref_date,
                )
                if score is None:
                    continue
                art["published_at"] = pub_dt
                art["score"] = score
                articles.append(art)

            articles.sort(key=lambda x: (x["score"], x.get("published_at", datetime.min)), reverse=True)
        else:
            if not all_keywords and not must_have_words and not nice_to_have_words:
                st.warning(
                    "Nema aktivnih kljucnih rijeci. "
                    "Odaberi barem jedan profil ili dodaj kljucne rijeci, "
                    "ili postavi obvezne/pozeljne rijeci."
                )
                return

            if not selected_sources:
                st.warning("Odaberi barem jedan izvor.")
                return

            with st.spinner("Pretrazujem RSS kanale..."):
                articles = search_rss_articles(
                    keywords=all_keywords,
                    date_from=date_from,
                    date_to=date_to,
                    sources=selected_sources,
                    must_have=must_have_words,
                    nice_to_have=nice_to_have_words,
                    exclude=exclude_words,
                )

                # Dodaj rezultate s vladinih/EU stranica (PDF/objave)
                gov_articles = search_gov_pages(
                    keywords=all_keywords,
                    date_from=date_from,
                    date_to=date_to,
                    must_have=must_have_words,
                    nice_to_have=nice_to_have_words,
                    exclude=exclude_words,
                )
                if gov_articles:
                    # izbjegni duplikate po linku
                    seen = {a["link"] for a in articles}
                    for g in gov_articles:
                        if g["link"] not in seen:
                            articles.append(g)
                            seen.add(g["link"])

                articles.sort(key=lambda x: (x["score"], x["published_at"]), reverse=True)

        if mode == "Dohvati svjeze iz RSS-a" and save_to_db and articles:
            try:
                save_articles_to_db(articles)
                st.success("Rezultati spremljeni u SQLite bazu.")
            except Exception as exc:
                st.warning(f"Nisam uspjela spremiti rezultate: {exc}")

        st.subheader(f"Pronadeno clanaka: {len(articles)}")

        if not articles:
            st.info("Nema clanaka koji zadovoljavaju zadane kriterije.")
            return

        for idx, art in enumerate(articles, start=1):
            st.markdown(f"### {idx}. [{art['title']}]({art['link']})")
            meta_parts = []
            if art.get("source"):
                meta_parts.append(f"Izvor: {art['source']}")
            if art.get("published_at"):
                meta_parts.append("Objavljeno: " + art["published_at"].strftime("%Y-%m-%d %H:%M"))
            meta_parts.append(f"Score: {art['score']} (vece je relevantnije)")
            if meta_parts:
                st.caption("  |  ".join(meta_parts))

            if art.get("summary"):
                st.write(art["summary"])

            st.write("---")

        if articles:
            csv = pd.DataFrame(articles).to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(
                "Preuzmi rezultate kao CSV",
                data=csv,
                file_name="presscut_light_rezultati.csv",
                mime="text/csv",
            )

            if st.button("Posalji dnevni izvjestaj emailom"):
                html_body = build_html_report(
                    articles=articles,
                    date_from=date_from,
                    date_to=date_to,
                    selected_profiles=selected_profiles,
                    all_keywords=all_keywords,
                )
                subject = (
                    f"Dnevni pregled vijesti "
                    f"{date_from.isoformat()} do {date_to.isoformat()}"
                )
                send_email_report(subject=subject, html_body=html_body)


def main():
    st.set_page_config(page_title="Presscut stil: vijesti", layout="wide")

    st.title("Pracenje vijesti: porezi, mirovine, klimatske politike, subvencije")
    st.write(
        "Aplikacija pretrazuje RSS kanale hrvatskih portala prema tematskim profilima kljucnih rijeci i zadanom razdoblju. "
        "Rezultate filtrira presscut stilom (obvezne/pozeljne/iskljucene rijeci, scoring, bonus za svjezinu) i omogucuje slanje dnevnog izvjestaja emailom."
    )

    render_rss_mode()


if __name__ == "__main__":
    main()

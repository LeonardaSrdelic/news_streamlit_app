import streamlit as st
import feedparser
from datetime import datetime, date
from typing import List, Dict

# RSS kanali hrvatskih portala
RSS_FEEDS: Dict[str, str] = {
    "HRT Vijesti": "https://vijesti.hrt.hr/rss",
    "Index Vijesti": "https://www.index.hr/rss/vijesti",
    "Index Novac": "https://www.index.hr/rss/vijesti-novac",
    "Jutarnji Vijesti": "http://www.jutarnji.hr/rss",
    "Slobodna Dalmacija Vijesti": "https://slobodnadalmacija.hr/feed/category/119",
    "Slobodna Dalmacija Biznis": "https://slobodnadalmacija.hr/feed/category/244",
    "24sata News": "https://www.24sata.hr/feeds/news.xml",
    "Poslovni dnevnik": "http://www.poslovni.hr/Content/RSS.aspx",
}

# Tematski profili ključnih riječi
KEYWORD_PROFILES: Dict[str, List[str]] = {
    "Porezi i proračun": [
        "porez",
        "porezi",
        "porezni sustav",
        "porezna reforma",
        "porezne stope",
        "PDV",
        "porez na dohodak",
        "porez na dobit",
        "porezni prihodi",
        "porezni raster",
        "porezno opterećenje",
        "porezne olakšice",
        "proračun",
        "državni proračun",
        "proračunski deficit",
        "proračunski suficit",
        "javne financije",
        "fiskalna pravila",
        "fiskalna konsolidacija",
    ],
    "Mirovine i socijalna davanja": [
        "mirovine",
        "mirovinski sustav",
        "mirovinska reforma",
        "mirovinski fondovi",
        "drugi stup",
        "treći stup",
        "HZMO",
        "Hrvatski zavod za mirovinsko osiguranje",
        "socijalna davanja",
        "socijalne naknade",
        "novčane naknade",
        "socijalna pomoć",
        "dječji doplatak",
        "rodiljne naknade",
        "roditeljske naknade",
        "nacionalna naknada za starije osobe",
        "doplatak",
        "socijalna politika",
    ],
    "Klimatska politika i subvencije energenata": [
        "klimatske promjene",
        "klimatska politika",
        "dekarbonizacija",
        "emisije stakleničkih plinova",
        "staklenički plinovi",
        "EU ETS",
        "tržište emisijskih jedinica",
        "trgovanje emisijama",
        "subvencije cijena energenata",
        "subvencije energenata",
        "energetske subvencije",
        "plinske subvencije",
        "subvencije struje",
        "energetske potpore",
        "fiksiranje cijena energenata",
        "plinski paket",
        "energetska tranzicija",
        "zeleni plan",
        "europski zeleni plan",
        "zeleni prijelaz",
    ],
    "Gospodarski rast i makroekonomija": [
        "BDP",
        "gospodarski rast",
        "gospodarska aktivnost",
        "recesija",
        "usporavanje rasta",
        "nezaposlenost",
        "zaposlenost",
        "stopa zaposlenosti",
        "investicije",
        "kapitalna ulaganja",
        "industrijska proizvodnja",
        "izvoz",
        "uvoz",
        "trgovinska bilanca",
        "domaća potražnja",
        "potrošnja kućanstava",
        "javna ulaganja",
        "produktivnost",
        "realne plaće",
        "plaće",
        "nadnice",
    ],
}


def normalize_datetime(entry) -> datetime:
    """Pokušava izvući datum objave iz RSS entryja."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6])
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime(*entry.updated_parsed[:6])
    return datetime(1970, 1, 1)


def matches_keywords(text: str, keywords: List[str]) -> bool:
    """Provjerava sadrži li tekst bilo koju od ključnih riječi, case insensitive."""
    if not text:
        return False
    lower_text = text.lower()
    for kw in keywords:
        if kw.lower() in lower_text:
            return True
    return False


def search_rss_articles(
    keywords: List[str],
    date_from: date,
    date_to: date,
    sources: List[str],
) -> List[dict]:
    """
    Pretražuje zadane RSS kanale i vraća listu članaka koji zadovoljavaju:
    - datum objave u zadanom rasponu (uključivo)
    - naslov ili opis sadrže neku od ključnih riječi
    """
    results = []

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

            title = getattr(entry, "title", "")
            summary = getattr(entry, "summary", "")

            if not matches_keywords(title + " " + summary, keywords):
                continue

            link = getattr(entry, "link", "")
            results.append(
                {
                    "title": title,
                    "link": link,
                    "source": source_name,
                    "published_at": pub_dt,
                    "summary": summary,
                }
            )

    results.sort(key=lambda x: x["published_at"], reverse=True)
    return results


def main():
    st.title("Praćenje vijesti: porezi, mirovine, klimatske politike, subvencije")

    st.write(
        "Aplikacija pretražuje RSS kanale hrvatskih portala prema tematskim "
        "profilima ključnih riječi i zadanom razdoblju."
    )

    st.subheader("1. Tematski profili")
    selected_profiles = st.multiselect(
        "Odaberi jedan ili više profila",
        options=list(KEYWORD_PROFILES.keys()),
        default=[
            "Porezi i proračun",
            "Mirovine i socijalna davanja",
            "Klimatska politika i subvencije energenata",
        ],
    )

    st.subheader("2. Dodatne ključne riječi")
    extra_keywords_text = st.text_input(
        "Dodatne ključne riječi odvojene zarezima (opcionalno)",
        value="naknade, socijalna pomoć, porezni prihodi, subvencije cijena energenata",
    )

    st.subheader("3. Razdoblje pretraživanja")
    today = date.today()
    date_from, date_to = st.date_input(
        "Razdoblje",
        value=(today, today),
        help="Možeš zadati jedan dan ili raspon datuma",
    )

    st.subheader("4. Izvori vijesti")
    selected_sources = st.multiselect(
        "Izvori",
        options=list(RSS_FEEDS.keys()),
        default=list(RSS_FEEDS.keys()),
    )

    all_keywords = []
    for prof in selected_profiles:
        all_keywords.extend(KEYWORD_PROFILES.get(prof, []))

    if extra_keywords_text.strip():
        extra_keywords = [
            k.strip()
            for k in extra_keywords_text.split(",")
            if k.strip()
        ]
        all_keywords.extend(extra_keywords)

    with st.expander("Prikaži aktivne ključne riječi"):
        st.write(sorted(set(all_keywords)))

    if st.button("Pretraži vijesti"):
        if not all_keywords:
            st.warning("Nema aktivnih ključnih riječi. Odaberi barem jedan profil ili dodaj ključne riječi.")
            return

        if not selected_sources:
            st.warning("Odaberi barem jedan izvor.")
            return

        with st.spinner("Pretražujem RSS kanale..."):
            articles = search_rss_articles(
                keywords=all_keywords,
                date_from=date_from,
                date_to=date_to,
                sources=selected_sources,
            )

        st.subheader(f"Pronađeno članaka: {len(articles)}")

        for idx, art in enumerate(articles, start=1):
            st.markdown(f"### {idx}. [{art['title']}]({art['link']})")
            meta_parts = []
            if art["source"]:
                meta_parts.append(f"Izvor: {art['source']}")
            if art["published_at"]:
                meta_parts.append(
                    "Objavljeno: "
                    + art["published_at"].strftime("%Y-%m-%d %H:%M")
                )
            if meta_parts:
                st.caption("  |  ".join(meta_parts))

            if art["summary"]:
                st.write(art["summary"])

            st.write("---")


if __name__ == "__main__":
    main()

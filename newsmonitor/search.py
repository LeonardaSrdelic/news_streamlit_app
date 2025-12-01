from typing import List, Dict
import re
from collections import Counter
import requests

from .blog import BlogPost
from .similarity import text_similarity
from .utils import clean_snippet


SERPER_ENDPOINT = "https://google.serper.dev/search"


def serper_search(query: str, api_key: str, count: int = 10) -> List[Dict]:
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "q": query,
        "num": count,
    }
    resp = requests.post(SERPER_ENDPOINT, headers=headers, json=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("organic", []):
        results.append(
            {
                "name": item.get("title"),
                "url": item.get("link"),
                "snippet": clean_snippet(item.get("snippet", "")),
            }
        )
    return results


def extract_keywords(text: str, top_n: int = 8, window_words: int = 120) -> List[str]:
    # Jednostavan hrvatski stoplist za filtriranje čestih riječi
    stopwords = {
        "i", "u", "na", "za", "se", "je", "su", "od", "do", "da", "s", "sa", "o",
        "kao", "koji", "što", "kako", "će", "ćeš", "ćeu", "sam", "si", "smo", "ste",
        "biti", "bila", "bio", "bilo", "te", "ali", "ili", "pa", "dok", "no", "ne",
        "nije", "nisu", "može", "mogu", "njih", "njihov", "ova", "ovaj", "ovo", "tu",
        "tamo", "više", "manje"
    }
    # Uzmi prvih window_words riječi da fokus ostane na uvodu
    words = re.findall(r"[A-Za-zÀ-ÿČĆŠĐŽčćšđž]+", text.lower())
    words = words[:window_words]
    filtered = [w for w in words if w not in stopwords and len(w) > 3]
    counts = Counter(filtered)
    return [w for w, _ in counts.most_common(top_n)]


TARGET_DOMAINS = [
    "lidermedia.hr",
    "lider.media",
    "lider.media.hr",
    "tportal.hr",
    "index.hr",
    "n1info.hr",
    "jutarnji.hr",
    "vecernji.hr",
    "poslovni.hr",
]


def build_queries(post: BlogPost) -> List[str]:
    queries: List[str] = []

    title_clean = post.title.replace("\n", " ").strip()
    if title_clean:
        # Varijante s i bez imena autorice radi šireg pokrivanja
        queries.append(f"\"{title_clean}\" \"Leonarda Srdelić\"")
        queries.append(f"\"{title_clean}\"")

    # Dodaj kratki uvodni snippet bez navodnika oko imena
    intro_words = post.text.split()
    if intro_words:
        intro_snippet = " ".join(intro_words[:16])
        if len(intro_snippet.split()) > 6:
            queries.append(f"\"{intro_snippet}\"")

    # Dodaj kombinacije ključnih riječi iz uvoda
    keywords = extract_keywords(post.text)
    if len(keywords) >= 3:
        queries.append(f"\"{' '.join(keywords[:3])}\"")
    if len(keywords) >= 4:
        queries.append(f"\"{' '.join(keywords[:4])}\"")

    sentences = post.text.split(".")
    for sent in sentences[:3]:
        sent_clean = sent.strip()
        if len(sent_clean.split()) > 6:
            queries.append(f"\"{sent_clean}\" \"Leonarda Srdelić\"")
            queries.append(f"\"{sent_clean}\"")

    # Domain-targeted upiti za brži pogodak na medijskim stranicama
    domain_queries: List[str] = []
    for domain in TARGET_DOMAINS:
        for q in queries:
            domain_queries.append(f"site:{domain} {q}")

    return list(dict.fromkeys(queries + domain_queries))


def search_for_reposts(
    blog_posts: List[BlogPost],
    api_key: str,
    similarity_threshold: float = 0.6,
    max_results_per_query: int = 15,
    max_queries_per_post: int = 25,
) -> List[Dict]:
    findings: List[Dict] = []
    seen_urls = set()

    for post in blog_posts:
        queries = build_queries(post)[:max_queries_per_post]
        for query in queries:
            try:
                results = serper_search(query, api_key=api_key, count=max_results_per_query)
            except Exception:
                continue

            for r in results:
                url = r["url"]
                if not url:
                    continue
                if "leonardasrdelic.github.io" in url:
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                is_target_domain = any(d in url for d in TARGET_DOMAINS)

                try:
                    from .blog import extract_article_text

                    candidate_text = extract_article_text(url)
                    sim_source = "full"
                except Exception:
                    candidate_text = ""
                    sim_source = "none"

                if not candidate_text or len(candidate_text.split()) < 60:
                    # Fallback na snippet i naslov kad je sadržaj kratak (paywall/JS)
                    fallback_text = " ".join(
                        t for t in [r.get("name", ""), r.get("snippet", "")] if t
                    )
                    if fallback_text:
                        sim = text_similarity(post.text, fallback_text)
                        sim_source = "snippet"
                    else:
                        sim = 0.0
                        sim_source = "none"
                else:
                    sim = text_similarity(post.text, candidate_text)

                # Popusti prag za ciljne medijske domene
                effective_threshold = similarity_threshold - 0.15 if is_target_domain else similarity_threshold
                if is_target_domain or sim >= effective_threshold:
                    findings.append(
                        {
                            "source_post_title": post.title,
                            "source_post_url": post.url,
                            "matched_title": r["name"],
                            "matched_url": url,
                            "snippet": r["snippet"],
                            "similarity": round(float(sim), 3),
                            "match_source": sim_source,
                        }
                    )

    return findings

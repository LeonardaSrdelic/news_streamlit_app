from dataclasses import dataclass
from typing import List
from urllib.parse import urljoin, urlparse
from io import BytesIO

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


@dataclass
class BlogPost:
    title: str
    url: str
    text: str


def extract_article_text(url: str) -> str:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    content_type = resp.headers.get("content-type", "").lower()
    is_pdf = "pdf" in content_type or url.lower().endswith(".pdf")
    if is_pdf:
        try:
            reader = PdfReader(BytesIO(resp.content))
            pages_text = []
            for page in reader.pages[:6]:
                page_text = page.extract_text() or ""
                pages_text.append(page_text)
            text = " ".join(pages_text)
            words = text.split()
            return " ".join(words)
        except Exception:
            return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    article = soup.find("article")
    if article is None:
        main = soup.find("main")
        if main is not None:
            article = main
        else:
            article = soup

    for tag in article.find_all(["script", "style", "nav", "footer", "header", "form"]):
        tag.decompose()

    text = article.get_text(separator=" ", strip=True)
    words = text.split()
    return " ".join(words)


def fetch_blog_posts(index_url: str) -> List[BlogPost]:
    resp = requests.get(index_url, timeout=20)
    resp.raise_for_status()

    content_type = resp.headers.get("content-type", "").lower()
    is_pdf = "pdf" in content_type or index_url.lower().endswith(".pdf")
    if is_pdf:
        text = extract_article_text(index_url)
        if text:
            title = index_url.rsplit("/", 1)[-1] or "Dokument"
            return [BlogPost(title=title, url=index_url, text=text)]
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Normalize base URL for relative links
    parsed = urlparse(resp.url if hasattr(resp, "url") else index_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    # Heuristika: ako nema liste bloga i sama stranica ima dovoljno teksta,
    # tretiraj uneseni URL kao jedan post (izbjegavamo hvatanje navigacije).
    blog_list = soup.find(class_="blog-list")
    if not blog_list:
        try:
            single_text = extract_article_text(index_url)
            if len(single_text.split()) >= 80:
                page_title = soup.title.get_text(strip=True) if soup.title else index_url
                return [BlogPost(title=page_title, url=index_url, text=single_text)]
        except Exception:
            pass

    links = set()
    # Prefer structured blog list if present
    if blog_list:
        for a in blog_list.select("a.blog-list-title"):
            href = a.get("href")
            text = a.get_text(strip=True)
            if not href or not text:
                continue
            full_url = urljoin(base_url, href)
            links.add((text, full_url))
    # Fallback: any internal links that look like posts
    if not links:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if not text:
                continue
            if href.startswith("http") and parsed.netloc not in href:
                continue
            if href.startswith("/") and href.rstrip("/") not in ("/hr", "/hr/", "/hr/blog"):
                full_url = urljoin(base_url, href)
                links.add((text, full_url))

    posts: List[BlogPost] = []
    for title, url in links:
        try:
            text = extract_article_text(url)
            if len(text.split()) < 40:
                continue
            posts.append(BlogPost(title=title, url=url, text=text))
        except Exception:
            continue

    # If still nothing, treat index_url as single post
    if not posts:
        try:
            fallback_text = extract_article_text(index_url)
            if fallback_text:
                page_title = soup.title.get_text(strip=True) if soup.title else index_url
                posts.append(BlogPost(title=page_title, url=index_url, text=fallback_text))
        except Exception:
            pass

    return posts

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def text_similarity(text_a: str, text_b: str) -> float:
    vectorizer = TfidfVectorizer(
        max_features=5000,
        ngram_range=(1, 2),
    )
    tfidf = vectorizer.fit_transform([text_a, text_b])
    sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0, 0]
    return float(sim)
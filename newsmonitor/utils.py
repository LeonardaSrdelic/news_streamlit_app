def clean_snippet(snippet: str) -> str:
    snippet = snippet.replace("\n", " ").strip()
    parts = snippet.split()
    if len(parts) > 60:
        parts = parts[:60]
    return " ".join(parts)


def estimate_reading_time(text: str, wpm: int = 200) -> int:
    words = text.split()
    minutes = max(1, int(len(words) / wpm))
    return minutes
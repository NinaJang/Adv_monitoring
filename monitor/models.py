from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TAG_RE = re.compile(r"<[^>]+>")
_TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "igshid", "igsh", "si", "ref")
# 이 호스트들은 쿼리스트링이 게시물 식별과 무관하므로 통째로 제거
_STRIP_QUERY_HOSTS = ("cafe.naver.com", "instagram.com", "threads.net", "x.com", "twitter.com")


def clean_text(text: str | None) -> str:
    """검색 API가 돌려주는 <b> 태그와 HTML 엔티티를 제거한다."""
    if not text:
        return ""
    return " ".join(html.unescape(_TAG_RE.sub("", text)).split())


def normalize_url(url: str) -> str:
    """같은 게시물이 다른 URL 형태로 중복 기록되지 않도록 정규화한다."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    path = parts.path.rstrip("/") or "/"
    if any(host == h or host.endswith("." + h) for h in _STRIP_QUERY_HOSTS):
        query = ""
    else:
        kept = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith(_TRACKING_PARAMS)
        ]
        query = urlencode(kept)
    return urlunsplit(("https", host, path, query, ""))


@dataclass
class Post:
    source: str          # naver_blog, naver_cafearticle, brave_web, brave_site:instagram.com ...
    keyword: str
    title: str
    url: str
    description: str = ""
    author: str = ""
    published: str = ""  # YYYY-MM-DD 또는 원문 그대로(알 수 없으면 빈 값)
    institution_mentioned: bool = False
    promo_score: int = 0
    promo_words: list[str] = field(default_factory=list)
    first_seen: str = ""

    @property
    def key(self) -> str:
        return normalize_url(self.url)

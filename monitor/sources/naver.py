"""네이버 검색 Open API (https://developers.naver.com/docs/serviceapi/search/blog/blog.md)."""
from __future__ import annotations

import logging
import time

import requests

from monitor.models import Post, clean_text

log = logging.getLogger(__name__)

API_URL = "https://openapi.naver.com/v1/search/{type}.json"
PAGE_SIZE = 100


def _format_date(yyyymmdd: str) -> str:
    if yyyymmdd and len(yyyymmdd) == 8 and yyyymmdd.isdigit():
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
    return ""


def _to_post(search_type: str, keyword: str, item: dict) -> Post:
    if search_type == "blog":
        author = clean_text(item.get("bloggername"))
        published = _format_date(item.get("postdate", ""))
    else:  # cafearticle 은 작성일을 제공하지 않음
        author = clean_text(item.get("cafename"))
        published = ""
    return Post(
        source=f"naver_{search_type}",
        keyword=keyword,
        title=clean_text(item.get("title")),
        url=item.get("link", ""),
        description=clean_text(item.get("description")),
        author=author,
        published=published,
    )


def search(keyword: str, cfg: dict, client_id: str, client_secret: str,
           session: requests.Session | None = None) -> list[Post]:
    session = session or requests.Session()
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    pages = max(1, min(int(cfg.get("pages", 3)), 10))
    posts: list[Post] = []

    for search_type in cfg.get("types", ["blog", "cafearticle"]):
        for page in range(pages):
            params = {
                "query": keyword,
                "display": PAGE_SIZE,
                "start": page * PAGE_SIZE + 1,
                "sort": "date",
            }
            try:
                resp = session.get(API_URL.format(type=search_type), headers=headers,
                                   params=params, timeout=20)
                resp.raise_for_status()
            except requests.RequestException as exc:
                log.warning("네이버 %s 검색 실패 (%s, page %d): %s", search_type, keyword, page + 1, exc)
                break
            data = resp.json()
            items = data.get("items", [])
            posts.extend(_to_post(search_type, keyword, it) for it in items)
            if len(items) < PAGE_SIZE or params["start"] + PAGE_SIZE > data.get("total", 0):
                break
            time.sleep(0.2)
    return posts

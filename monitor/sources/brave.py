"""Brave Search API (https://api-dashboard.search.brave.com/app/documentation/web-search)."""
from __future__ import annotations

import logging
import time

import requests

from monitor.models import Post, clean_text

log = logging.getLogger(__name__)

API_URL = "https://api.search.brave.com/res/v1/web/search"
PAGE_SIZE = 20
REQUEST_INTERVAL = 1.1  # 무료 요금제는 초당 1회 제한


def _queries(keyword: str, cfg: dict) -> list[tuple[str, str]]:
    """(source 이름, 검색어) 목록"""
    phrase = f'"{keyword}"'
    queries = []
    if cfg.get("web_search", True):
        queries.append(("brave_web", phrase))
    for site in cfg.get("sites", []) or []:
        queries.append((f"brave_site:{site}", f"{phrase} site:{site}"))
    return queries


def search(keyword: str, cfg: dict, api_key: str,
           session: requests.Session | None = None) -> list[Post]:
    session = session or requests.Session()
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    pages = max(1, min(int(cfg.get("pages", 2)), 10))
    posts: list[Post] = []

    for source, query in _queries(keyword, cfg):
        for page in range(pages):
            params = {
                "q": query,
                "count": PAGE_SIZE,
                "offset": page,
                "country": "KR",
                "search_lang": "ko",
            }
            if cfg.get("freshness"):
                params["freshness"] = cfg["freshness"]
            try:
                resp = session.get(API_URL, headers=headers, params=params, timeout=20)
                resp.raise_for_status()
            except requests.RequestException as exc:
                log.warning("Brave 검색 실패 (%s, page %d): %s", query, page + 1, exc)
                break
            finally:
                time.sleep(REQUEST_INTERVAL)
            data = resp.json()
            results = (data.get("web") or {}).get("results", [])
            for r in results:
                posts.append(Post(
                    source=source,
                    keyword=keyword,
                    title=clean_text(r.get("title")),
                    url=r.get("url", ""),
                    description=clean_text(r.get("description")),
                    author=clean_text((r.get("profile") or {}).get("name")),
                    published=(r.get("page_age") or "")[:10],
                ))
            if not (data.get("query") or {}).get("more_results_available"):
                break
    return posts

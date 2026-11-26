"""네이버 검색 API.

- hub    : NAVER API HUB (네이버 클라우드 플랫폼). 신규 발급은 여기서만 가능.
- legacy : 기존 네이버 개발자센터(openapi.naver.com). 기존에 발급받은 키가 있을 때만.
"""
from __future__ import annotations

import logging
import time

import requests

from monitor.models import Post, clean_text

log = logging.getLogger(__name__)

ENDPOINTS = {
    "hub": {
        "url": "https://naverapihub.apigw.ntruss.com/search/v1/{type}",
        "id_header": "X-NCP-APIGW-API-KEY-ID",
        "secret_header": "X-NCP-APIGW-API-KEY",
    },
    "legacy": {
        "url": "https://openapi.naver.com/v1/search/{type}.json",
        "id_header": "X-Naver-Client-Id",
        "secret_header": "X-Naver-Client-Secret",
    },
}
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
           session: requests.Session | None = None, errors: list[str] | None = None) -> list[Post]:
    session = session or requests.Session()
    ep = dict(ENDPOINTS[cfg.get("api", "hub")])
    if cfg.get("url"):
        ep["url"] = cfg["url"]
    headers = {ep["id_header"]: client_id, ep["secret_header"]: client_secret}
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
                resp = session.get(ep["url"].format(type=search_type), headers=headers,
                                   params=params, timeout=20)
                resp.raise_for_status()
            except requests.RequestException as exc:
                body = getattr(getattr(exc, "response", None), "text", "") or ""
                msg = f"네이버 {search_type} 검색 실패 ('{keyword}'): {exc} {body[:200]}".strip()
                log.warning(msg)
                if errors is not None:
                    errors.append(msg)
                break
            data = resp.json()
            items = data.get("items", [])
            posts.extend(_to_post(search_type, keyword, it) for it in items)
            if len(items) < PAGE_SIZE or params["start"] + PAGE_SIZE > data.get("total", 0):
                break
            time.sleep(0.2)
    return posts

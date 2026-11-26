from datetime import datetime
from pathlib import Path

import pytest

from monitor import main
from monitor.models import Post, clean_text, normalize_url
from monitor.sources import brave, naver


class FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, params))
        return FakeResp(self.pages.pop(0) if self.pages else {})


def test_clean_text_and_normalize():
    assert clean_text("<b>한국기관</b> &amp; 업체") == "한국기관 & 업체"
    assert normalize_url("https://m.blog.naver.com/abc/123/?utm_source=x#top") == \
        "https://blog.naver.com/abc/123"
    assert normalize_url("http://www.instagram.com/p/XYZ/?igsh=1") == "https://instagram.com/p/XYZ"
    assert normalize_url("https://cafe.naver.com/c/1?art=abc") == "https://cafe.naver.com/c/1"
    assert normalize_url("https://shop.com/item?id=3&utm_medium=a") == "https://shop.com/item?id=3"


def test_naver_parses_and_pages(monkeypatch):
    monkeypatch.setattr(naver.time, "sleep", lambda s: None)
    blog = {"total": 1, "items": [{
        "title": "<b>한국기관</b> 지정 업체", "link": "https://blog.naver.com/a/1",
        "description": "상담 문의", "bloggername": "홍보맨", "postdate": "20261120"}]}
    cafe = {"total": 1, "items": [{
        "title": "후기", "link": "https://cafe.naver.com/c/2", "description": "한국기관",
        "cafename": "맘카페"}]}
    s = FakeSession([blog, cafe])
    posts = naver.search("한국기관", {"types": ["blog", "cafearticle"], "pages": 3}, "id", "sec", s)
    assert len(s.calls) == 2  # total이 적어서 다음 페이지는 요청하지 않음
    assert posts[0].published == "2026-11-20" and posts[0].title == "한국기관 지정 업체"
    assert posts[1].source == "naver_cafearticle" and posts[1].author == "맘카페"
    assert s.calls[0][0] == "https://naverapihub.apigw.ntruss.com/search/v1/blog"


def test_naver_error_reported():
    class Boom:
        def get(self, *a, **k):
            raise naver.requests.ConnectionError("401 Unauthorized")
    errors = []
    assert naver.search("라스북", {"types": ["blog"], "api": "legacy"}, "i", "s", Boom(), errors) == []
    assert "401" in errors[0] and "blog" in errors[0]


def test_brave_queries_sites(monkeypatch):
    monkeypatch.setattr(brave.time, "sleep", lambda s: None)
    page = {"web": {"results": [{"title": "한국기관 협약", "url": "https://instagram.com/p/1",
                                 "description": "DM 주세요", "page_age": "2026-11-21T00:00:00"}]},
            "query": {"more_results_available": False}}
    s = FakeSession([page, page])
    posts = brave.search("라스북 한국기관", {"web_search": True, "sites": ["instagram.com"], "pages": 2}, "k", s)
    assert [c[1]["q"] for c in s.calls] == ['"라스북" "한국기관"', '"라스북" "한국기관" site:instagram.com']
    assert posts[1].source == "brave_site:instagram.com" and posts[1].published == "2026-11-21"


def _cfg(**kw):
    cfg = {"required_words": ["라스북"], "keywords": ["국립중앙과학관", "중앙과학관"],
           "queries": ["라스북 국립중앙과학관"], "claim_words": ["입점", "인증"],
           "promo_words": ["할인", "구매"], "exclude_url_contains": ["science.go.kr"],
           "exclude_text_contains": ["채용"]}
    cfg.update(kw)
    return cfg


def test_requires_company_name_and_scores():
    cfg = _cfg()
    posts = [
        Post("naver_blog", "q", "국립중앙과학관 관람 후기", "https://blog.naver.com/x/1"),        # 라스북 없음 → 제외
        Post("naver_blog", "q", "라스 북 국립중앙과학관 공식 입점!", "https://blog.naver.com/a/1",
             published="2026-11-01"),                                                       # 띄어쓰기 무시
        Post("naver_blog", "q", "라스북 신간 할인", "https://m.blog.naver.com/b/2/",
             published="2026-11-20"),                                                       # 기관명 안 보임
        Post("naver_blog", "q", "도서 리뷰", "https://blog.naver.com/c/3", author="라스북"),    # 작성자로 매칭
        Post("naver_blog", "q", "라스북 국립중앙과학관", "https://blog.naver.com/a/1/"),        # 중복 URL
        Post("brave_web", "q", "라스북 국립중앙과학관", "https://www.science.go.kr/x"),         # 공식 사이트
        Post("brave_web", "q", "라스북 채용", "https://jobs.com/1"),                          # 제외 단어
        Post("brave_web", "q", "라스북 중앙과학관", "https://seen.com/1"),                    # 이미 기록됨
    ]
    new = main.select_new(posts, {"https://seen.com/1"}, cfg, "2026-11-26")
    assert [p.url for p in new] == ["https://blog.naver.com/a/1", "https://m.blog.naver.com/b/2/",
                                    "https://blog.naver.com/c/3"]
    top = new[0]
    assert top.institution_mentioned and top.promo_score == 5 + 5 + 3  # 기관명 2개 + 입점
    assert top.promo_words == ["국립중앙과학관", "중앙과학관", "입점"]
    assert not new[1].institution_mentioned and new[1].promo_score == 1
    assert new[0].first_seen == "2026-11-26"

    report = main.render_report(new, "2026-11-26", 4, [])
    assert "기관명이 보이는 게시물: **1건**" in report and "확인 필요" in report


def test_load_config_requires_company(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("keywords: [국립중앙과학관]\nqueries: [라스북]\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main.load_config(p)


def test_repo_config_is_valid():
    cfg = main.load_config(Path(__file__).parent.parent / "config.yaml")
    assert cfg["required_words"] == ["라스북"]
    assert all("라스북" in q for q in cfg["queries"])


def test_run_end_to_end(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("required_words: [라스북]\nkeywords: [국립중앙과학관]\nqueries: [라스북]\n"
                        "sources: {}\n", encoding="utf-8")
    batches = [
        [Post("naver_blog", "라스북", "라스북 국립중앙과학관", "https://blog.naver.com/a/1")],
        [Post("naver_blog", "라스북", "라스북 국립중앙과학관", "https://blog.naver.com/a/1"),
         Post("naver_blog", "라스북", "라스북 새글", "https://blog.naver.com/a/2")],
    ]
    monkeypatch.setattr(main, "collect", lambda cfg: (batches.pop(0), []))
    data, reports = tmp_path / "data", tmp_path / "reports"

    first = main.run(cfg_path, data, reports, now=datetime(2026, 11, 25))
    second = main.run(cfg_path, data, reports, now=datetime(2026, 11, 26))

    assert len(first) == 1 and [p.url for p in second] == ["https://blog.naver.com/a/2"]
    assert len(main.load_seen(data / "posts.csv")) == 2
    assert (reports / "2026-11-26.md").read_text(encoding="utf-8").count("blog.naver.com/a/2") == 1
    assert "누적 기록: 2건" in (reports / "latest.md").read_text(encoding="utf-8")

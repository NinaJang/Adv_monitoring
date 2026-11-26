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


def test_brave_queries_sites(monkeypatch):
    monkeypatch.setattr(brave.time, "sleep", lambda s: None)
    page = {"web": {"results": [{"title": "한국기관 협약", "url": "https://instagram.com/p/1",
                                 "description": "DM 주세요", "page_age": "2026-11-21T00:00:00"}]},
            "query": {"more_results_available": False}}
    s = FakeSession([page, page])
    posts = brave.search("한국기관", {"web_search": True, "sites": ["instagram.com"], "pages": 2}, "k", s)
    assert [c[1]["q"] for c in s.calls] == ['"한국기관"', '"한국기관" site:instagram.com']
    assert posts[1].source == "brave_site:instagram.com" and posts[1].published == "2026-11-21"


def _cfg(**kw):
    cfg = {"keywords": ["한국 기관"], "require_keyword_match": True,
           "promo_words": ["상담", "할인", "협찬"], "claim_words": ["입점"], "watch_companies": ["라스북"], "exclude_url_contains": ["official.go.kr"],
           "exclude_text_contains": ["채용"]}
    cfg.update(kw)
    return cfg


def test_filter_score_and_dedupe():
    cfg = _cfg()
    posts = [
        Post("naver_blog", "한국 기관", "한국기관 협찬 할인", "https://blog.naver.com/a/1", published="2026-11-01"),
        Post("naver_blog", "한국 기관", "한국기관 상담", "https://m.blog.naver.com/a/1/"),  # 중복 URL
        Post("naver_blog", "한국 기관", "한국기관 소개", "https://blog.naver.com/b/2", published="2026-11-02"),
        Post("naver_blog", "한국 기관", "무관한 글", "https://blog.naver.com/c/3"),           # 키워드 없음
        Post("brave_web", "한국 기관", "한국 기관", "https://official.go.kr/x"),             # 공식 사이트
        Post("brave_web", "한국 기관", "한국 기관 채용", "https://jobs.com/1"),              # 제외 단어
        Post("brave_web", "한국 기관", "한국 기관", "https://seen.com/1"),                  # 이미 기록됨
    ]
    new = main.select_new(posts, {"https://seen.com/1"}, cfg, "2026-11-26")
    assert [p.url for p in new] == ["https://blog.naver.com/a/1", "https://blog.naver.com/b/2"]
    assert new[0].promo_score == 2 and new[0].promo_words == ["할인", "협찬"]
    assert new[0].first_seen == "2026-11-26"


def test_watch_company_and_claim_rank_first():
    cfg = _cfg()
    posts = [
        Post("naver_blog", "q", "한국기관 할인 상담", "https://a.com/1"),
        Post("naver_blog", "q", "라스북 한국 기관 공식 입점!", "https://a.com/2", author="라스 북"),
    ]
    new = main.select_new(posts, set(), cfg, "2026-11-26")
    assert new[0].url == "https://a.com/2"
    assert new[0].promo_score == 8 and new[0].promo_words == ["라스북", "입점"]
    report = main.render_report(new, "2026-11-26", 2, [], min_score=3)
    assert "a.com/2" in report and "a.com/1" not in report and "3점 미만 1건" in report


def test_search_queries_include_extras():
    cfg = {"keywords": ["국립중앙과학관"], "extra_queries": ["국립중앙과학관 라스북", "국립중앙과학관"]}
    assert main.search_queries(cfg) == ["국립중앙과학관", "국립중앙과학관 라스북"]


def test_run_end_to_end(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("keywords: [한국기관]\npromo_words: [상담]\nsources: {}\n", encoding="utf-8")
    batches = [
        [Post("naver_blog", "한국기관", "한국기관 상담", "https://blog.naver.com/a/1")],
        [Post("naver_blog", "한국기관", "한국기관 상담", "https://blog.naver.com/a/1"),
         Post("naver_blog", "한국기관", "한국기관 새글", "https://blog.naver.com/a/2")],
    ]
    monkeypatch.setattr(main, "collect", lambda cfg: (batches.pop(0), []))
    data, reports = tmp_path / "data", tmp_path / "reports"

    first = main.run(cfg_path, data, reports, now=datetime(2026, 11, 25))
    second = main.run(cfg_path, data, reports, now=datetime(2026, 11, 26))

    assert len(first) == 1 and [p.url for p in second] == ["https://blog.naver.com/a/2"]
    assert len(main.load_seen(data / "posts.csv")) == 2
    assert (reports / "2026-11-26.md").read_text(encoding="utf-8").count("blog.naver.com/a/2") == 1
    assert "누적 기록: 2건" in (reports / "latest.md").read_text(encoding="utf-8")


def test_placeholder_keyword_rejected(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("keywords: [기관명을 입력하세요]\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main.load_config(p)

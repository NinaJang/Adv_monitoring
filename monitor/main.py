"""기관명 도용 홍보 게시물 모니터링.

사용법:  python -m monitor.main [--config config.yaml] [--data-dir data] [--reports-dir reports]

- data/posts.csv   : 지금까지 발견된 모든 게시물 (URL 기준 중복 제거, first_seen = 처음 발견한 날짜)
- reports/YYYY-MM-DD.md : 해당 실행에서 새로 발견된 게시물 리포트 (홍보 점수 높은 순)
- reports/latest.md     : 가장 최근 실행 결과 요약
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from monitor.models import Post, normalize_url
from monitor.sources import brave, naver

log = logging.getLogger("monitor")
KST = timezone(timedelta(hours=9))
CSV_FIELDS = ["first_seen", "promo_score", "promo_words", "source", "keyword",
              "published", "author", "title", "url", "description"]
PLACEHOLDER_KEYWORD = "기관명을 입력하세요"


# ---------------------------------------------------------------- 설정/저장
def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg["keywords"] = [k.strip() for k in cfg.get("keywords") or [] if k and k.strip()]
    if not cfg["keywords"] or PLACEHOLDER_KEYWORD in cfg["keywords"]:
        raise SystemExit("config.yaml 의 keywords 에 기관 이름을 입력해 주세요.")
    return cfg


def load_seen(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        return {normalize_url(row["url"]) for row in csv.DictReader(f) if row.get("url")}


def append_posts(csv_path: Path, posts: list[Post]) -> None:
    new_file = not csv_path.exists()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: 엑셀에서 바로 열어도 한글이 깨지지 않도록
    with open(csv_path, "a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            w.writeheader()
        for p in posts:
            w.writerow({
                "first_seen": p.first_seen, "promo_score": p.promo_score,
                "promo_words": ", ".join(p.promo_words), "source": p.source,
                "keyword": p.keyword, "published": p.published, "author": p.author,
                "title": p.title, "url": p.url, "description": p.description,
            })


# ---------------------------------------------------------------- 필터/점수
def _squash(text: str) -> str:
    return "".join(text.lower().split())


def keep_post(post: Post, cfg: dict) -> bool:
    if not post.url:
        return False
    url = post.url.lower()
    if any(x.lower() in url for x in cfg.get("exclude_url_contains") or [] if x):
        return False
    text = f"{post.title} {post.description}"
    if any(x.lower() in text.lower() for x in cfg.get("exclude_text_contains") or [] if x):
        return False
    if cfg.get("require_keyword_match", True):
        # 기관명 중 하나라도 포함돼야 함. 띄어쓰기 차이는 무시 ("국립 중앙과학관" == "국립중앙과학관").
        haystack = _squash(text + " " + post.author)
        if not any(_squash(k) in haystack or k.lower() in url for k in cfg["keywords"]):
            return False
    return True


# 단어 종류별 가중치
WEIGHTS = {"watch_companies": 5, "claim_words": 3, "promo_words": 1}


def score_post(post: Post, cfg: dict) -> None:
    text = _squash(f"{post.title} {post.description} {post.author} {post.url}")
    matched, score = [], 0
    for group, weight in WEIGHTS.items():
        for w in cfg.get(group) or []:
            if w and _squash(w) in text and w not in matched:
                matched.append(w)
                score += weight
    post.promo_words = matched
    post.promo_score = score


def search_queries(cfg: dict) -> list[str]:
    """기관명 단독 검색 + 기관명과 관심업체/공식주장 단어 조합 검색"""
    queries = list(cfg["keywords"])
    queries += [q for q in cfg.get("extra_queries") or [] if q and q not in queries]
    return queries


# ---------------------------------------------------------------- 수집
def collect(cfg: dict) -> tuple[list[Post], list[str]]:
    posts: list[Post] = []
    notes: list[str] = []
    src = cfg.get("sources") or {}

    ncfg = src.get("naver") or {}
    if ncfg.get("enabled"):
        cid, secret = os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET")
        if cid and secret:
            for kw in search_queries(cfg):
                found = naver.search(kw, ncfg, cid, secret)
                log.info("네이버 '%s': %d건", kw, len(found))
                posts += found
        else:
            notes.append("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 없어 네이버 검색을 건너뜀")

    bcfg = src.get("brave") or {}
    if bcfg.get("enabled"):
        key = os.getenv("BRAVE_API_KEY")
        if key:
            queries = search_queries(cfg) if bcfg.get("use_extra_queries") else cfg["keywords"]
            for kw in queries:
                found = brave.search(kw, bcfg, key)
                log.info("Brave '%s': %d건", kw, len(found))
                posts += found
        else:
            notes.append("BRAVE_API_KEY 가 없어 웹/SNS 검색을 건너뜀")

    for n in notes:
        log.warning(n)
    return posts, notes


def select_new(posts: list[Post], seen: set[str], cfg: dict, today: str) -> list[Post]:
    new: dict[str, Post] = {}
    for p in posts:
        if not keep_post(p, cfg):
            continue
        key = p.key
        if key in seen or key in new:
            continue
        score_post(p, cfg)
        p.first_seen = today
        new[key] = p
    # 홍보 점수 높은 순, 같은 점수면 최신 작성일 순
    result = sorted(new.values(), key=lambda p: p.published, reverse=True)
    return sorted(result, key=lambda p: p.promo_score, reverse=True)


# ---------------------------------------------------------------- 리포트
def _md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_report(new: list[Post], today: str, total_seen: int, notes: list[str],
                  min_score: int = 0) -> str:
    shown = [p for p in new if p.promo_score >= min_score]
    hidden = len(new) - len(shown)
    lines = [f"# 모니터링 결과 {today}", "",
             f"- 새로 발견된 게시물: **{len(new)}건** (의심 게시물 {len(shown)}건"
             + (f", 홍보점수 {min_score}점 미만 {hidden}건은 `data/posts.csv`에만 기록" if hidden else "")
             + ")",
             f"- 누적 기록: {total_seen}건 (`data/posts.csv`)", ""]
    for n in notes:
        lines.append(f"> ⚠️ {n}")
    if notes:
        lines.append("")
    if not shown:
        lines.append("새 의심 게시물이 없습니다.")
        return "\n".join(lines) + "\n"
    lines += ["| 홍보점수 | 출처 | 작성일 | 작성자 | 제목 | 매칭 단어 |",
              "|---:|---|---|---|---|---|"]
    for p in shown:
        lines.append(
            f"| {p.promo_score} | {p.source} | {p.published or '-'} | {_md(p.author) or '-'} "
            f"| [{_md(p.title) or p.url}]({p.url}) | {_md(', '.join(p.promo_words)) or '-'} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 실행
def run(config_path: Path, data_dir: Path, reports_dir: Path, now: datetime | None = None) -> list[Post]:
    cfg = load_config(config_path)
    today = (now or datetime.now(KST)).strftime("%Y-%m-%d")
    csv_path = data_dir / "posts.csv"

    seen = load_seen(csv_path)
    posts, notes = collect(cfg)
    new = select_new(posts, seen, cfg, today)
    if new:
        append_posts(csv_path, new)

    report = render_report(new, today, len(seen) + len(new), notes,
                           int(cfg.get("report_min_score", 0)))
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest.md").write_text(report, encoding="utf-8")
    if new:
        (reports_dir / f"{today}.md").write_text(report, encoding="utf-8")

    log.info("수집 %d건 / 신규 %d건", len(posts), len(new))
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report)
    return new


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yaml", type=Path)
    ap.add_argument("--data-dir", default="data", type=Path)
    ap.add_argument("--reports-dir", default="reports", type=Path)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run(args.config, args.data_dir, args.reports_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

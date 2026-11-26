# 기관명 도용 홍보 게시물 모니터링

업체가 기관 이름을 홍보에 쓰는 온라인 게시물을 매일 검색합니다. **새로 올라온 게시물**만 골라 기록합니다.

| 대상 | 방법 |
|---|---|
| 네이버 블로그, 네이버 카페 | 네이버 검색 Open API (최신순) |
| 일반 웹페이지 | Brave Search API |
| 인스타그램, 페이스북, 유튜브, 스레드, X, 티스토리 | Brave Search API `site:` 검색 |

> 구글 Custom Search API는 신규 가입이 막혀 있고 2027-01-01에 종료됩니다. 그래서 웹/SNS 검색에는 Brave Search API를 씁니다.
> 인스타그램 같은 SNS는 직접 크롤링하면 약관에 위반되고 로그인 차단도 걸립니다. 그래서 검색엔진에 색인된 공개 게시물만 찾습니다. 색인이 늦거나 빠지는 게시물이 있을 수 있습니다.

## 현재 설정 (국립중앙과학관)

- 검색어
  - 기관명 단독: `국립중앙과학관`
  - 기관명 + 업체·주장 표현: `국립중앙과학관 라스북` / `국립중앙과학관 입점` / `국립중앙과학관 공식 입점` / `국립중앙과학관 인증`
  - 조합 검색어는 네이버에서만 돌립니다. Brave 무료 크레딧을 아끼기 위해서입니다.
- 홍보 점수
  - 관심 업체(`라스북`) +5점
  - 공식 관계 주장 표현(입점·공식·인증·지정·협약·납품 등) +3점
  - 일반 홍보 단어 +1점
- 리포트에는 **3점 이상**만 표시됩니다. 일반 관람 후기는 `data/posts.csv`에만 쌓입니다.
- 공식 홈페이지(`science.go.kr`)는 결과에서 제외합니다.

## 결과물

- `reports/latest.md`: 가장 최근 실행 결과
- `reports/YYYY-MM-DD.md`: 새 게시물이 있던 날의 리포트. **홍보 점수**가 높은 순서로 정렬됩니다.
- `data/posts.csv`: 지금까지 발견한 모든 게시물의 누적 기록. 엑셀에서 바로 열 수 있습니다.
  - `first_seen`: 처음 발견한 날짜
  - `promo_score` / `promo_words`: 제목·요약에 들어 있는 홍보성 단어의 개수와 목록
- 각 실행의 요약은 GitHub **Actions → 실행 기록 → Summary**에도 표시됩니다.

같은 게시물은 URL 기준으로 한 번만 기록됩니다. 모바일 주소, `utm_` 같은 추적 파라미터 차이는 무시합니다.

## 설정 방법

### 1. `config.yaml` 수정
- `keywords`: 기관의 정식 명칭, 약칭, 영문명을 적습니다. **필수**
- `exclude_url_contains`: 기관 공식 홈페이지, 공식 블로그, 공식 SNS 주소를 적습니다. 자기 게시물이 결과에서 빠집니다.
- `exclude_text_contains`: 동명 단체처럼 무관한 결과를 거를 단어를 적습니다.
- `promo_words`: 홍보성 판별 단어를 필요에 맞게 고칩니다.

### 2. API 키 발급
- **네이버**: https://developers.naver.com/apps/#/register 에서 애플리케이션을 등록합니다. 사용 API는 '검색'을 고르고, Client ID와 Client Secret을 받습니다. 무료이며 하루 25,000회까지 호출할 수 있습니다.
- **Brave**: https://api-dashboard.search.brave.com 에 가입해 Search 요금제의 API 키를 받습니다. 매월 무료 크레딧이 있습니다.
  - 기본 설정에서 키워드 1개당 하루 호출량은 최대 14회입니다(7개 쿼리 × 2페이지). 키워드가 많으면 `pages` 값이나 `sites` 목록을 줄이세요.

키가 없는 소스는 자동으로 건너뜁니다. 건너뛴 사실은 리포트에 경고로 표시됩니다.

### 3. GitHub Secrets 등록
저장소의 **Settings → Secrets and variables → Actions → New repository secret**에서 아래 세 값을 등록합니다.

| 이름 | 값 |
|---|---|
| `NAVER_CLIENT_ID` | 네이버 Client ID |
| `NAVER_CLIENT_SECRET` | 네이버 Client Secret |
| `BRAVE_API_KEY` | Brave API 키 |

### 4. 실행
- 이 브랜치가 **기본 브랜치(main)에 병합되어야** 예약 실행이 동작합니다. 실행 시각은 매일 오전 9시 17분(한국시간)입니다.
- **Actions → 기관명 홍보 게시물 모니터링 → Run workflow**로 언제든 수동 실행할 수 있습니다.
- 첫 실행에서는 현재 검색되는 게시물이 전부 '신규'로 기록됩니다. 이후 실행부터 새 게시물만 기록됩니다.

## 로컬 실행

```bash
pip install -r requirements.txt
export NAVER_CLIENT_ID=... NAVER_CLIENT_SECRET=... BRAVE_API_KEY=...
python -m monitor.main
python -m pytest   # 테스트
```

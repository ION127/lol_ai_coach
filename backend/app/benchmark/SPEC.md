# Benchmark Module — SPEC

> `backend/app/benchmark/`  
> 챌린저 TOP 100 경기 데이터 자동 수집 + 집계 통계 구축.  
> 원본 Riot API 응답은 저장하지 않음 (Riot Developer Policy §7 준수).

---

## 파일 목록

```
benchmark/
├── collector.py      # 챌린저 경기 수집 Celery Beat 작업
├── riot_client.py    # Riot API 클라이언트 (Rate Limit 준수)
├── aggregator.py     # match + timeline → BenchmarkStat/MatchupStat upsert
└── comparator.py     # 유저 stats vs 벤치마크 비교 (stat_gaps 계산)
```

---

## collector.py — 수집 파이프라인

### 수집 주기
| 작업 | 주기 | API |
|------|------|-----|
| 챌린저 목록 갱신 | 매일 1회 | league-v4 /challengerleagues |
| 새 경기 감지 | 30분마다 | match-v5 /matchlist |
| 경기 상세 수집 | 위 감지 후 즉시 | match-v5 /match + /timeline |

### Rate Limit 계산 (Production Key 기준)
```
match-v5 /match:          100 req / 2min
match-v5 /matchlist:      100 req / 2min
league-v4 /challenger:     30 req / 10min

챌린저 100명 × 5경기 = 500 경기
→ 500 req × 2 (match + timeline) = 1,000 req
→ 100 req/2min → 20분 소요
→ sleep(2.5) 로 안전 마진 확보
```

```python
@celery_app.task(name="benchmark.collect_challenger")
def collect_challenger_data(region: str = "KR"):
    """
    Celery Beat 스케줄: 매일 04:00 KST
    챌린저 100명의 최신 5경기씩 수집 → aggregator.aggregate_and_store()
    """
    with SyncSessionLocal() as db:
        challengers = riot_client.get_challenger_list(region)[:100]
        for player in challengers:
            match_ids = riot_client.get_match_list(player["puuid"], count=5, region=region)
            for match_id in match_ids:
                # 이미 수집된 경기 skip (중복 방지)
                if _already_collected(db, match_id):
                    continue
                match    = riot_client.get_match(match_id, region=region)
                timeline = riot_client.get_timeline(match_id, region=region)
                aggregator.aggregate_and_store(db, match, timeline)
                time.sleep(2.5)   # Rate limit 안전 마진
```

---

## riot_client.py

```python
class RiotAPIClient:
    """
    Riot API 호출 래퍼.
    - Rate limit 준수: 요청 간 sleep 포함
    - 재시도: 429(Rate Limit) / 503(서버 오류) → 지수 백오프 3회
    - Riot Developer Policy 준수: 원본 응답 캐시 24시간 후 삭제
    """

    BASE_URLS = {
        "KR":   "https://kr.api.riotgames.com",
        "EUW1": "https://euw1.api.riotgames.com",
        "NA1":  "https://na1.api.riotgames.com",
    }
    ROUTING_URLS = {
        "KR":   "https://asia.api.riotgames.com",
        "EUW1": "https://europe.api.riotgames.com",
        "NA1":  "https://americas.api.riotgames.com",
    }

    def get_challenger_list(self, region: str) -> list[dict]:
        """league-v4 /challengerleagues/by-queue/RANKED_SOLO_5x5"""

    def get_match_list(self, puuid: str, count: int = 5, region: str = "KR") -> list[str]:
        """match-v5 /matches/by-puuid/{puuid}/ids"""

    def get_match(self, match_id: str, region: str = "KR") -> dict:
        """match-v5 /matches/{matchId}"""

    def get_timeline(self, match_id: str, region: str = "KR") -> dict:
        """match-v5 /matches/{matchId}/timeline"""

    def get_match_timeline(self, match_id: str) -> dict:
        """parser Resilience Layer에서 호출 (비동기 버전)"""

    def _request(self, url: str, retries: int = 3) -> dict:
        """
        requests.get() + 재시도 로직.
        429 → Retry-After 헤더값 sleep
        503 → 지수 백오프 (1s, 2s, 4s)
        """
```

---

## aggregator.py

```python
def aggregate_and_store(db, match: dict, timeline: dict) -> None:
    """
    Riot API 원본에서 집계 통계만 추출 → BenchmarkStat / MatchupStat upsert.
    원본(match/timeline)은 저장 안 함 — Riot Policy §7 준수.

    upsert 전략: PostgreSQL ON CONFLICT DO UPDATE
    누적 방식: EMA(α=0.05)로 새 경기 데이터를 기존 통계에 블렌딩
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    for participant in match["info"]["participants"]:
        # 통계 추출
        cs_per_min = _calc_cs_per_min(participant, match)
        vision     = participant.get("visionScore", 0)
        damage     = participant.get("totalDamageDealtToChampions", 0)
        wards      = participant.get("wardsPlaced", 0)

        stmt = (
            pg_insert(BenchmarkStat)
            .values(champion_id=..., role=..., patch=..., region=...,
                    avg_cs_per_min=cs_per_min, ...)
            .on_conflict_do_update(
                index_elements=["champion_id", "role", "patch", "region"],
                set_={
                    "avg_cs_per_min": BenchmarkStat.avg_cs_per_min * 0.95 + cs_per_min * 0.05,
                    "sample_count":   BenchmarkStat.sample_count + 1,
                    # ... 다른 필드도 동일하게 EMA 업데이트
                }
            )
        )
        db.execute(stmt)

    # MatchupStat도 동일한 upsert 패턴
    _upsert_matchup_stats(db, match, timeline)
    db.commit()
```

---

## comparator.py

```python
def compare_to_benchmark(
    db,
    player_stats: dict,
    champion_id: int,
    role: str,
    region: str,
) -> dict:
    """
    유저 경기 stats vs 챌린저 벤치마크 비교.
    Returns: {"cs_per_min_diff": float, "vision_score_diff": float, ...}

    리전별 폴백:
    1. 유저 리전 벤치마크 (sample_count >= 30)
    2. KR 폴백
    3. None (데이터 없음 — LLM 전용 모드)
    """
    bench = _get_benchmark_with_fallback(db, champion_id, role, region)
    if not bench:
        return {}

    return {
        "cs_per_min_diff":    round(player_stats["cs_per_min"] - bench.avg_cs_per_min, 2),
        "vision_score_diff":  round(player_stats["vision_score"] - bench.avg_vision_score, 2),
        "damage_dealt_diff":  round(player_stats["damage_dealt"] - bench.avg_damage_dealt, 0),
        "ward_placed_diff":   round(player_stats["ward_placed"] - bench.avg_ward_placed, 2),
        "sample_count":       bench.sample_count,
        "benchmark_region":   bench.region,
    }

def get_matchup_stats(
    db, player_champ: str, enemy_champ: str, role: str
) -> "MatchupStats | None":
    """
    매치업 통계 조회.
    데이터 부족(sample_count < 10) 시 None → LLM 동적 텍스트로 폴백.
    """
```

---

## 리전별 벤치마크 분리

| 리전 | 특징 | 라우팅 |
|------|------|--------|
| KR | CS 집착, 기술 중심 | asia.api.riotgames.com |
| EUW1 | 공격적 교전, 시야 강조 | europe.api.riotgames.com |
| NA1 | 느린 템포, 한타 위주 | americas.api.riotgames.com |
| EUN1 | EUW와 유사 | europe.api.riotgames.com |

> KR/EUW 벤치마크를 혼합하면 CS 기대치 왜곡 → 리전별 완전 분리

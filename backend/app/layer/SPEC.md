# Layer Module — SPEC

> `backend/app/layer/`  
> GameContext 분석 결과를 LLM 입력에 최적화된 계층적 텍스트로 정제.  
> 8,000 토큰 상한 내에서 가장 중요한 정보를 담는다.

---

## 파일 목록

```
layer/
├── layer1.py     # 수치 요약 (CS/골드/킬/시야 — 구조화 JSON)
├── layer2.py     # 핵심 이벤트 타임라인 (킬/데스/오브젝트 — 시간순)
├── layer3.py     # 분석 인사이트 (엔진 결과 → 자연어 요약)
├── layer4.py     # 전체 원본 데이터 (디테일 질문 대응용, 선택적 첨부)
└── builder.py    # LayerBuilder — 4개 레이어 일괄 생성 진입점
```

---

## 레이어 구조 개요

| Layer | 내용 | 토큰 예산 | 항상 포함? |
|-------|------|-----------|-----------|
| L1 | 수치 요약 JSON | ~800 | 항상 |
| L2 | 핵심 이벤트 타임라인 | ~1,500 | 항상 |
| L3 | 분석 인사이트 | ~2,500 | 항상 |
| L4 | 전체 원본 (선택) | ~4,000 | 디테일 질문 시 |
| LP | 플레이어 모델 | ~500 | 항상 |

> **총합: 8,000 토큰 이하 강제** — LLM 컨텍스트 초과 방지

---

## layer1.py — 수치 요약

```python
def build_layer1(ctx: GameContext) -> dict:
    """
    경기 전체의 수치 요약.
    LLM이 "이 경기 CS 얼마나 했어?" 같은 기본 질문에 답할 수 있도록.

    반환 구조:
    {
      "game_duration_min": float,
      "result": "WIN" | "LOSE",
      "player": {
        "champion": str,
        "role": str,
        "kda": {"kills": int, "deaths": int, "assists": int},
        "cs_total": int,
        "cs_per_min": float,
        "gold_earned": int,
        "gold_per_min": float,
        "vision_score": int,
        "damage_dealt": int,
        "damage_taken": int,
      },
      "benchmark_comparison": {
        "cs_per_min_diff": float,    # 챌린저 대비 차이
        "vision_score_diff": float,
        "damage_dealt_diff": float,
      },
      "timeline_summary": [
        {"minute": 5,  "gold_diff": -120, "cs_diff": -8, "kills": 0, "deaths": 1},
        {"minute": 10, "gold_diff":  350, ...},
        ...
      ],
      "data_quality": "FULL" | "PARTIAL" | "FALLBACK",
    }
    """
```

---

## layer2.py — 핵심 이벤트 타임라인

```python
def build_layer2(ctx: GameContext) -> list[dict]:
    """
    경기에서 중요한 이벤트만 추출 (킬/데스/오브젝트/리콜/아이템 완성).
    LLM이 "6분에 뭐 했어?" 같은 시점 기반 질문에 답할 수 있도록.

    각 항목:
    {
      "timestamp_sec": int,
      "type": "KILL" | "DEATH" | "DRAGON" | "BARON" | "TOWER" |
               "RECALL" | "ITEM_COMPLETE" | "FIGHT" | "ROAM",
      "description": str,   # "06:23 — 적 Ahri에게 죽음 (와드 없이 진입)"
      "verdict": str | None, # FightResult.verdict (교전 이벤트만)
      "context": dict,       # wave_state, game_state 스냅샷 등
    }

    우선순위 필터링:
    1. 데스 이벤트 (항상 포함)
    2. 킬 이벤트
    3. 오브젝트 (드래곤/바론/타워)
    4. 나쁜 교전 (verdict=RED|ORANGE)
    5. 나쁜 리콜 (recall_eval=DANGEROUS|WASTEFUL)
    → 토큰 1,500 초과 시 하위 우선순위부터 제거
    """
```

---

## layer3.py — 분석 인사이트

```python
def build_layer3(ctx: GameContext) -> dict:
    """
    9개 엔진 결과를 LLM이 이해하기 쉬운 자연어 인사이트로 변환.
    "이 경기의 가장 큰 문제는?" 같은 종합 질문에 답할 수 있도록.

    반환 구조:
    {
      "top_mistakes": [
        {
          "type": "wave_fight_while_behind",
          "count": 3,
          "worst_instance": "08:45 — LOSING_WAVE(미니언 -4) 상태에서 교전 → 사망",
          "coaching": "웨이브 열세에서 교전 자제 — 먼저 정리 후 교전"
        },
        ...
      ],
      "wave_analysis": {
        "avg_state": "EVEN",
        "losing_fight_rate": 0.6,   # LOSING_WAVE 상태 교전 비율
        "freeze_missed": 2,          # 프리즈 기회 놓친 횟수
        "summary": "웨이브 관리 전반적으로 무난. LOSING_WAVE 상태 교전이 3회 있었음."
      },
      "macro_analysis": {
        "objective_miss_count": 1,
        "best_macro": "14:20 바론 스택 후 타워 압박 — 올바른 선택",
        "worst_macro": "18:40 킬 후 서폿 대신 사이드 — 오브젝트 2개 놓침",
        "summary": "..."
      },
      "vision_analysis": {
        "avg_dominance": 0.42,
        "unwarded_engage_count": 2,
        "summary": "..."
      },
      "intent_analysis": {
        "wrong_intent_count": 2,
        "wrong_execution_count": 1,
        "summary": "..."
      },
      "composition_insight": {
        "my_archetype": "SCALING",
        "phase_advantage": {"early": "ENEMY", "mid": "EVEN", "late": "PLAYER"},
        "summary": "상대가 초반 강함 — 20분 전 교전 최소화 필요했음."
      },
      "game_state_insight": {
        "peak_phase": "EVEN",
        "gold_trend": "초반 열세 → 중반 회복",
        "summary": "..."
      },
    }
    """
```

---

## layer4.py — 전체 원본

```python
def build_layer4(ctx: GameContext) -> dict:
    """
    원본 수준 상세 데이터. 디테일 질문 대응용.
    "3분 57초에 정확히 내 HP가 얼마였어?" 같은 질문.

    항상 첨부하지 않음 — 질문 분류기가 L4 필요 여부 판단.
    data_quality=FALLBACK 이면 snapshots가 없으므로 L4 불가.

    반환 구조:
    {
      "snapshots_sample": [snap_dict, ...],   # 1분 간격 샘플 (30개 이하)
      "full_events": [event_dict, ...],        # 전체 이벤트 목록
      "fight_details": [FightResult_dict, ...],
      "wave_timeline": {ts: WaveState_dict, ...},
    }
    """
```

---

## builder.py

```python
class LayerBuilder:
    """
    GameContext → 4개 레이어 일괄 생성.
    analysis_worker.py (Celery)에서 호출.
    """

    def build_all(self, ctx: GameContext) -> dict:
        """
        Returns:
            {
                "layer1": dict,
                "layer2": list,
                "layer3": dict,
                "layer4": dict | None,   # FALLBACK 시 None
                "script": dict,          # coaching/에서 생성 (여기선 None)
                "token_counts": {"l1": int, "l2": int, "l3": int}
            }
        """
        l1 = build_layer1(ctx)
        l2 = build_layer2(ctx)
        l3 = build_layer3(ctx)
        l4 = build_layer4(ctx) if ctx.data_quality != "FALLBACK" else None

        return {
            "layer1": l1,
            "layer2": l2,
            "layer3": l3,
            "layer4": l4,
        }
```

---

## 토큰 예산 관리

```python
MAX_TOKENS = 8_000
LAYER_BUDGETS = {
    "l1": 800,
    "l2": 1_500,
    "l3": 2_500,
    "lp": 500,     # 플레이어 모델 컨텍스트
    "reserve": 500, # 시스템 프롬프트 여유분
}
# l4 = 나머지 (최대 ~2,200) — 디테일 질문 시에만 추가

def estimate_tokens(text: str) -> int:
    """tiktoken 또는 len(text)//4 근사"""
    return len(text) // 4
```

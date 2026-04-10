# Models Module — SPEC

> `backend/app/models/`  
> SQLAlchemy ORM 모델 전체 정의. DB 테이블 스키마의 단일 진실 원천(Single Source of Truth).

---

## 파일 목록

```
models/
├── user.py           # User (계정), RefreshToken
├── analysis.py       # AnalysisRecord (분석 작업 레코드)
├── benchmark.py      # BenchmarkStat, MatchupStat (챌린저 집계 통계)
└── player_model.py   # PlayerModel (다경기 개인화 모델)
```

---

## user.py

```python
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean, DateTime
from datetime import datetime
from app.core.database import Base

class User(Base):
    """
    서비스 계정.
    - Riot 계정 연동은 선택 사항 (puuid 별도 테이블)
    - refresh_token: 단일 기기. 다중 기기 지원 시 UserSession 테이블 분리 필요
    """
    __tablename__ = "users"

    id: Mapped[str]      = mapped_column(String(36), primary_key=True)   # UUID v4
    email: Mapped[str]   = mapped_column(String(320), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool]      = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Refresh Token (DB 저장 → 탈취 시 서버에서 즉시 폐기 가능)
    refresh_token: Mapped[str | None]      = mapped_column(String(128), nullable=True)
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

---

## analysis.py

```python
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Text, ForeignKey, DateTime
from datetime import datetime
from app.core.database import Base

class AnalysisRecord(Base):
    """
    .rofl 분석 작업 레코드.

    status 전이:
        "pending" → "processing" → "complete"
                                 → "failed"

    layer1_json ~ script_json: 분석 완료 후 채워짐 (nullable)
    metadata_json: 분석 파라미터 (champion_id, player_id, puuid, role, opponent 등)
    s3_key: 원본 .rofl 위치 → 분석 완료 즉시 삭제 (Riot Policy §7)
    data_quality: "FULL" | "PARTIAL" | "FALLBACK"
    """
    __tablename__ = "analysis_records"

    id: Mapped[str]      = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    status: Mapped[str]       = mapped_column(String(20), default="pending")
    data_quality: Mapped[str | None] = mapped_column(String(10), nullable=True)

    s3_key: Mapped[str | None]       = mapped_column(String(512), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    layer1_json: Mapped[str | None]  = mapped_column(Text, nullable=True)
    layer2_json: Mapped[str | None]  = mapped_column(Text, nullable=True)
    layer3_json: Mapped[str | None]  = mapped_column(Text, nullable=True)
    layer4_json: Mapped[str | None]  = mapped_column(Text, nullable=True)
    script_json: Mapped[str | None]  = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime]   = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

---

## benchmark.py

```python
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Integer, Float, String, Text
from app.core.database import Base

class BenchmarkStat(Base):
    """
    챌린저 챔피언별 집계 통계.
    Riot API 원본 미저장 (Policy §7 준수) — 우리가 계산한 값만 저장.

    복합 PK: (champion_id, role, patch, region)
    리전별 분리: KR/EUW/NA 플레이 스타일 차이로 혼합 시 왜곡
    """
    __tablename__ = "benchmark_stats"

    champion_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role:        Mapped[str] = mapped_column(String(20), primary_key=True)
    patch:       Mapped[str] = mapped_column(String(10), primary_key=True)
    region:      Mapped[str] = mapped_column(String(10), primary_key=True)

    avg_cs_per_min:   Mapped[float] = mapped_column(Float, default=0.0)
    avg_vision_score: Mapped[float] = mapped_column(Float, default=0.0)
    avg_damage_dealt: Mapped[float] = mapped_column(Float, default=0.0)
    avg_ward_placed:  Mapped[float] = mapped_column(Float, default=0.0)
    sample_count:     Mapped[int]   = mapped_column(Integer, default=0)


class MatchupStat(Base):
    """
    챔피언 대 챔피언 매치업별 집계 통계.
    복합 PK: (champion, opponent, role, patch, region)

    gold_timeline: JSON 문자열 [{minute: int, gold_diff: float}, ...]
                   → derive_strong_phase()로 강세 구간 도출
    """
    __tablename__ = "matchup_stats"

    champion: Mapped[str] = mapped_column(String(50), primary_key=True)
    opponent: Mapped[str] = mapped_column(String(50), primary_key=True)
    role:     Mapped[str] = mapped_column(String(20), primary_key=True)
    patch:    Mapped[str] = mapped_column(String(10), primary_key=True)
    region:   Mapped[str] = mapped_column(String(10), primary_key=True)

    winrate:       Mapped[float] = mapped_column(Float, default=0.5)
    cs_diff_10:    Mapped[float] = mapped_column(Float, default=0.0)
    gold_diff_15:  Mapped[float] = mapped_column(Float, default=0.0)
    gold_timeline: Mapped[str]   = mapped_column(Text, default="[]")
    sample_count:  Mapped[int]   = mapped_column(Integer, default=0)
```

---

## player_model.py

```python
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, JSON, DateTime
from datetime import datetime
from app.core.database import Base

class PlayerModel(Base):
    """
    다경기 플레이어 약점 모델.

    JSON 컬럼 스키마:
    - recurring_mistakes: list[MistakePattern dict]
        {"mistake_type": str, "frequency": float, "severity": str,
         "trend": str, "first_seen": str, "last_seen": str, "game_count": int}
    - current_focus: list[FocusTask dict]
        {"title": str, "description": str, "metric": str,
         "target": float, "current": float, "progress": float, "deadline_games": int}
    - growth_history: list[GrowthSnapshot dict]
        {"recorded_at": str, "games_analyzed": int, "cs_per_min": float,
         "vision_score": float, "wave_behind_fight_rate": float,
         "optimal_recall_rate": float, "kda": float, "overall_score": float}

    동시 업데이트 보호:
    - PlayerModelEngine.update_model()에서 SELECT ... FOR UPDATE 사용
    - JSON 컬럼 in-place 수정 후 반드시 재할당 (SQLAlchemy 변경 감지 한계)
    """
    __tablename__ = "player_models"

    puuid: Mapped[str]       = mapped_column(String(78), primary_key=True)  # Riot PUUID = 78자
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    recurring_mistakes: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    stat_gaps:          Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    strengths:          Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    current_focus:      Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    growth_history:     Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
```

---

## DB 마이그레이션 (Alembic)

```
alembic/versions/
├── 0001_initial_schema.py       # users, analysis_records
├── 0002_add_benchmark.py        # benchmark_stats, matchup_stats
├── 0003_add_player_model.py     # player_models
└── 0004_add_game_state_col.py   # analysis_records.data_quality 컬럼 추가
```

### 운영 배포 순서
1. nullable 컬럼 추가 (기존 행 영향 없음)
2. 코드 배포
3. 백그라운드 백필
4. NOT NULL 제약 추가 (필요 시)

```bash
alembic upgrade head   # CI/CD 배포 전 자동 실행
```

---

## 관계 다이어그램

```
users ──< analysis_records   (1:N, CASCADE DELETE)
users ──  player_models      (1:1, puuid 별도 연동)
benchmark_stats              (독립 테이블)
matchup_stats                (독립 테이블)
```

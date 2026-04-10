from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BenchmarkStat(Base):
    """
    챌린저 챔피언별 집계 통계 ORM.

    Riot API 원본 미저장 — Policy §7 준수.
    우리가 계산한 집계 통계(평균값)만 저장.

    복합 PK: (champion_id, role, patch, region)
    리전별 분리: KR/EUW/NA 플레이 스타일 차이로 혼합 시 수치 왜곡
    """

    __tablename__ = "benchmark_stats"

    # ── 복합 PK ───────────────────────────────────────────────────
    champion_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(
        String(20), primary_key=True,
        comment="TOP | JUNGLE | MID | ADC | SUPPORT"
    )
    patch: Mapped[str] = mapped_column(
        String(10), primary_key=True,
        comment="e.g. 14.5"
    )
    region: Mapped[str] = mapped_column(
        String(10), primary_key=True,
        comment="KR | EUW1 | NA1 | EUN1"
    )

    # ── 집계 통계 (EMA로 누적 업데이트) ─────────────────────────
    avg_cs_per_min: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    avg_vision_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    avg_damage_dealt: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    avg_ward_placed: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="집계에 사용된 경기 수"
    )

    def __repr__(self) -> str:
        return (
            f"<BenchmarkStat champ={self.champion_id} role={self.role!r} "
            f"patch={self.patch!r} region={self.region!r} n={self.sample_count}>"
        )


class MatchupStat(Base):
    """
    챔피언 대 챔피언 매치업별 집계 통계 ORM.

    복합 PK: (champion, opponent, role, patch, region)
    gold_timeline: JSON 문자열 [{minute: int, gold_diff: float}, ...]
                   → derive_strong_phase()로 강세 구간(EARLY/MID/LATE) 도출
    """

    __tablename__ = "matchup_stats"

    # ── 복합 PK ───────────────────────────────────────────────────
    champion: Mapped[str] = mapped_column(String(50), primary_key=True)
    opponent: Mapped[str] = mapped_column(String(50), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), primary_key=True)
    patch: Mapped[str] = mapped_column(String(10), primary_key=True)
    region: Mapped[str] = mapped_column(String(10), primary_key=True)

    # ── 집계 통계 ─────────────────────────────────────────────────
    winrate: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5,
        comment="이 매치업에서 champion의 챌린저 평균 승률"
    )
    cs_diff_10: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="10분 CS 격차 평균 (양수 = 유리)"
    )
    gold_diff_15: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="15분 골드 격차 평균"
    )
    gold_timeline: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]",
        comment="JSON: [{minute, gold_diff}] — derive_strong_phase() 입력"
    )
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    def __repr__(self) -> str:
        return (
            f"<MatchupStat {self.champion!r} vs {self.opponent!r} "
            f"role={self.role!r} wr={self.winrate:.2f} n={self.sample_count}>"
        )

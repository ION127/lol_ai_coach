"""
파서 데이터 모델.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ── 예외 ─────────────────────────────────────────────────────────
class RoflParseError(Exception):
    """기본 .rofl 파싱 오류"""


class RoflMagicError(RoflParseError):
    """파일 시그니처(Magic bytes) 불일치"""


class RoflVersionMismatch(RoflParseError):
    """패치로 인한 포맷 버전 변경 — PARTIAL 폴백 트리거"""


class RoflCorruptedError(RoflParseError):
    """파일 손상 (체크섬 불일치 등)"""


# ── 데이터 모델 ───────────────────────────────────────────────────
@dataclass
class ParseResult:
    """
    파싱 결과 통합 컨테이너.

    attributes:
        events:    게임 내 이벤트 목록 [{timestamp, type, data}]
        snapshots: 타임스탬프별 스냅샷 {timestamp_ms: snap_dict}
                   FALLBACK 시 {} (위치 정보 없음)
        quality:   "FULL" | "PARTIAL" | "FALLBACK"
        metadata:  champion_id, player_id, puuid, match_id, patch, region 등
    """
    events: list[dict]
    snapshots: dict[int, dict]              # {timestamp_ms: snap_dict}
    quality: str = "FALLBACK"
    metadata: dict = field(default_factory=dict)

    def event_count(self) -> int:
        return len(self.events)

    def snapshot_count(self) -> int:
        return len(self.snapshots)

    def is_full(self) -> bool:
        return self.quality == "FULL"


@dataclass
class ValidationReport:
    """파싱 결과 검증 보고서"""
    issues: list[str]
    is_valid: bool

    def __str__(self) -> str:
        if self.is_valid:
            return "Valid"
        return f"Invalid ({len(self.issues)} issues): {'; '.join(self.issues[:3])}"

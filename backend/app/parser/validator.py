"""
파싱 결과 일관성 검증.
"""
from __future__ import annotations

from app.parser.models import ParseResult, ValidationReport

# LoL 맵 좌표 범위 (SRU 기준)
_MAP_MIN = -500
_MAP_MAX = 15500

# 타임스탬프 갭 임계값 (밀리초)
_MAX_TIMESTAMP_GAP_MS = 10_000  # 10초 이상 갭이면 문제로 간주


class DataValidator:
    """ParseResult 데이터 품질 검증"""

    def validate(self, result: ParseResult) -> ValidationReport:
        issues: list[str] = []

        self._check_events(result, issues)
        self._check_snapshots(result, issues)

        return ValidationReport(issues=issues, is_valid=len(issues) == 0)

    def _check_events(self, result: ParseResult, issues: list[str]) -> None:
        """이벤트 목록 검증"""
        if not result.events:
            if result.quality == "FULL":
                issues.append("FULL 품질인데 이벤트가 없습니다")
            return

        # 타임스탬프 단조 증가 확인
        prev_ts = -1
        for i, event in enumerate(result.events):
            ts = event.get("timestamp", -1)
            if not isinstance(ts, (int, float)):
                issues.append(f"이벤트[{i}] 타임스탬프 타입 오류: {type(ts)}")
                continue
            if ts < prev_ts:
                issues.append(
                    f"이벤트 타임스탬프 역순: [{i}] {ts} < {prev_ts}"
                )
            prev_ts = ts

    def _check_snapshots(self, result: ParseResult, issues: list[str]) -> None:
        """스냅샷 검증"""
        if not result.snapshots:
            return  # FALLBACK은 snapshots 없음이 정상

        timestamps = sorted(result.snapshots.keys())

        # 타임스탬프 갭 확인
        gaps = [
            (t1, t2, t2 - t1)
            for t1, t2 in zip(timestamps, timestamps[1:])
            if t2 - t1 > _MAX_TIMESTAMP_GAP_MS
        ]
        if gaps:
            max_gap = max(g[2] for g in gaps)
            issues.append(
                f"스냅샷 타임스탬프 갭 {len(gaps)}개 "
                f"(최대 {max_gap / 1000:.1f}초)"
            )

        # 좌표 범위 확인 (최대 100개 스냅샷만 샘플링)
        sample = list(result.snapshots.values())[:100]
        coord_errors = 0
        for snap in sample:
            for player in snap.get("players", []):
                pos = player.get("position", {})
                x = pos.get("x", 0)
                y = pos.get("y", 0)
                if not (_MAP_MIN <= x <= _MAP_MAX and _MAP_MIN <= y <= _MAP_MAX):
                    coord_errors += 1

        if coord_errors > 0:
            issues.append(f"맵 범위 밖 좌표 {coord_errors}개")

        # 플레이어 수 확인 (10명이 정상)
        for ts, snap in list(result.snapshots.items())[:10]:
            players = snap.get("players", [])
            if len(players) not in (0, 10):
                issues.append(
                    f"비정상 플레이어 수: {len(players)} (ts={ts})"
                )
                break

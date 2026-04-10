"""
RoflResilienceLayer — 3단계 폴백 파싱 오케스트레이션.

Celery 동기 컨텍스트에서 실행되므로 모든 메서드 동기.
Riot API 호출은 httpx.Client(동기) 사용.

폴백 순서:
  1. .rofl 완전 파싱 → FULL
  2. 메타데이터 + Riot API 타임라인 병합 → PARTIAL
  3. Riot API 타임라인 단독 → FALLBACK
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import settings
from app.parser.metadata import parse_metadata_only
from app.parser.models import ParseResult, RoflMagicError, RoflVersionMismatch
from app.parser.rofl_parser import RoflParser

logger = logging.getLogger(__name__)


class RoflResilienceLayer:
    """
    .rofl 파싱 실패에 강건한 오케스트레이터.

    모든 메서드는 동기(Celery 워커 호환).
    """

    def __init__(self, riot_api_key: str | None = None) -> None:
        self._riot_api_key = riot_api_key or settings.RIOT_API_KEY
        self._parser = RoflParser()

    # ── 메인 진입점 ───────────────────────────────────────────────
    def parse_with_fallback(
        self,
        rofl_path: str | Path,
        match_id: str,
        puuid: str = "",
    ) -> ParseResult:
        """
        3단계 폴백으로 ParseResult 반환.
        어떤 상황에서도 최소한 FALLBACK 품질의 결과를 반환.

        Args:
            rofl_path: .rofl 파일 경로 (빈 문자열이면 1단계 스킵)
            match_id:  Riot 매치 ID (2~3단계에서 사용)
            puuid:     플레이어 PUUID

        Returns:
            ParseResult (quality: "FULL" | "PARTIAL" | "FALLBACK")
        """
        rofl_path = Path(rofl_path) if rofl_path else None

        # ── 1단계: .rofl 완전 파싱 ────────────────────────────────
        if rofl_path and rofl_path.exists():
            try:
                result = self._parser.parse(rofl_path, puuid=puuid)
                if result.quality in ("FULL", "PARTIAL"):
                    logger.info(
                        "파싱 성공 (quality=%s, match=%s)",
                        result.quality, match_id,
                    )
                    return result
            except RoflVersionMismatch:
                logger.warning("버전 불일치 (match=%s) → PARTIAL 시도", match_id)
            except RoflMagicError as e:
                logger.warning("매직 오류 (match=%s): %s → PARTIAL 시도", match_id, e)
            except Exception as e:
                logger.warning("파싱 실패 (match=%s): %s → PARTIAL 시도", match_id, e)

        # ── 2단계: 메타데이터 + Riot API 타임라인 병합 ────────────
        if match_id and self._riot_api_key:
            try:
                meta = {}
                if rofl_path and rofl_path.exists():
                    meta = parse_metadata_only(rofl_path)

                timeline = self._fetch_timeline(match_id)
                result = self._merge_meta_and_timeline(meta, timeline, puuid)
                result.quality = "PARTIAL"
                logger.info("PARTIAL 파싱 성공 (match=%s)", match_id)
                return result
            except Exception as e:
                logger.warning("PARTIAL 실패 (match=%s): %s → FALLBACK 시도", match_id, e)

        # ── 3단계: Riot API 타임라인 단독 ─────────────────────────
        if match_id and self._riot_api_key:
            try:
                timeline = self._fetch_timeline(match_id)
                result = self._timeline_to_parse_result(timeline)
                result.metadata["puuid"] = puuid
                logger.info("FALLBACK 파싱 성공 (match=%s)", match_id)
                return result
            except Exception as e:
                logger.error("FALLBACK 실패 (match=%s): %s", match_id, e)

        # ── 최후 수단: 빈 결과 ────────────────────────────────────
        logger.error("모든 파싱 단계 실패 (match=%s)", match_id)
        return ParseResult(
            events=[],
            snapshots={},
            quality="FALLBACK",
            metadata={"match_id": match_id, "puuid": puuid, "parse_failed": True},
        )

    # ── Riot API 호출 ─────────────────────────────────────────────
    def _fetch_timeline(self, match_id: str) -> dict:
        """
        Riot API에서 매치 타임라인 조회 (동기).
        region은 match_id prefix로 자동 결정.
        """
        import httpx

        region = _match_id_to_routing(match_id)
        url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
        headers = {"X-Riot-Token": self._riot_api_key}

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    # ── 변환 헬퍼 ────────────────────────────────────────────────
    def _timeline_to_parse_result(self, timeline: dict) -> ParseResult:
        """Riot API 타임라인 → ParseResult 변환. snapshots = {} (위치 없음)"""
        events = [
            {
                "timestamp": e.get("timestamp", 0),
                "type": e.get("type", "UNKNOWN"),
                "data": e,
            }
            for frame in timeline.get("info", {}).get("frames", [])
            for e in frame.get("events", [])
        ]
        events.sort(key=lambda e: e["timestamp"])
        return ParseResult(events=events, snapshots={}, quality="FALLBACK")

    def _merge_meta_and_timeline(
        self, meta: dict, timeline: dict, puuid: str
    ) -> ParseResult:
        """
        .rofl 메타데이터 + Riot API 타임라인 → ParseResult 병합.
        위치 정보는 없지만 이벤트 + 메타데이터 조합.
        """
        result = self._timeline_to_parse_result(timeline)
        result.metadata.update(meta)
        result.metadata["puuid"] = puuid
        return result


# ── 헬퍼 함수 ────────────────────────────────────────────────────
def _match_id_to_routing(match_id: str) -> str:
    """match_id prefix로 Riot API 라우팅 지역 결정"""
    prefix = match_id.split("_")[0].upper() if "_" in match_id else ""
    routing_map = {
        "KR": "asia",
        "JP1": "asia",
        "EUW1": "europe",
        "EUN1": "europe",
        "TR1": "europe",
        "RU": "europe",
        "NA1": "americas",
        "BR1": "americas",
        "LA1": "americas",
        "LA2": "americas",
        "OC1": "sea",
        "PH2": "sea",
        "SG2": "sea",
        "TH2": "sea",
        "TW2": "sea",
        "VN2": "sea",
    }
    return routing_map.get(prefix, "asia")

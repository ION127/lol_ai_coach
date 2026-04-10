"""
.rofl 바이너리 파싱 메인.

현재 구현 범위:
- 메타데이터 헤더 추출 (완전 구현)
- 청크 헤더 파싱 (완전 구현)
- 청크 데이터 압축 해제 (완전 구현)
- 청크 데이터 복호화 → TODO (Riot API 복호화 키 필요)
- 스냅샷 역직렬화 → TODO (암호화 해제 후 포맷 확정)

복호화 없이도 메타데이터 + 청크 구조 정보 제공 가능.
"""
from __future__ import annotations

import json
import logging
import struct
from pathlib import Path

from app.parser.chunk_decoder import decompress_chunk, parse_chunk_header
from app.parser.metadata import _parse_from_bytes, parse_metadata_only
from app.parser.models import (
    ParseResult,
    RoflCorruptedError,
    RoflMagicError,
    RoflVersionMismatch,
)

logger = logging.getLogger(__name__)

# .rofl 헤더의 청크 헤더 시작 오프셋 (고정 헤더 이후)
_CHUNK_COUNT_OFFSET = 14   # 청크 수 (2 bytes LE) 위치
_CHUNK_HEADERS_OFFSET = 16  # 청크 헤더 배열 시작


class RoflParser:
    """
    .rofl 파일 파서.

    사용법:
        parser = RoflParser()
        result = parser.parse(path, puuid="...")
    """

    def parse(self, rofl_path: str | Path, puuid: str = "") -> ParseResult:
        """
        .rofl 파일 전체 파싱.

        현재는 메타데이터 + 청크 구조만 추출.
        복호화 키가 있으면 스냅샷 역직렬화 가능.

        Returns:
            ParseResult (quality="FULL" 또는 청크 복호화 실패 시 메타데이터만)

        Raises:
            RoflMagicError: 파일 시그니처 오류
            RoflVersionMismatch: 지원되지 않는 버전
            RoflCorruptedError: 파일 손상
        """
        rofl_path = Path(rofl_path)
        logger.info("파싱 시작: %s (size=%d bytes)", rofl_path.name, rofl_path.stat().st_size)

        with open(rofl_path, "rb") as f:
            data = f.read()

        return self._parse_bytes(data, puuid)

    def _parse_bytes(self, data: bytes, puuid: str) -> ParseResult:
        # 1. 메타데이터 추출
        metadata = _parse_from_bytes(data)

        # 2. 청크 헤더 파싱 (복호화 없이 구조만)
        chunk_headers = self._parse_chunk_headers(data)
        logger.debug("청크 수: %d", len(chunk_headers))

        # 3. 청크 복호화 + 스냅샷 역직렬화
        # TODO: Riot API 매치 암호화 키 수신 후 구현
        # snapshots, events = self._decode_chunks(data, chunk_headers, decryption_key)
        snapshots: dict[int, dict] = {}
        events: list[dict] = []

        # 청크 구조만 파싱 가능한 현재: PARTIAL 수준으로 처리
        quality = "PARTIAL" if chunk_headers else "FALLBACK"

        result = ParseResult(
            events=events,
            snapshots=snapshots,
            quality=quality,
            metadata={
                **metadata,
                "puuid": puuid,
                "chunk_count": len(chunk_headers),
            },
        )
        logger.info(
            "파싱 완료: quality=%s chunks=%d",
            result.quality,
            len(chunk_headers),
        )
        return result

    def _parse_chunk_headers(self, data: bytes) -> list[dict]:
        """청크 헤더 목록 파싱"""
        if len(data) < _CHUNK_HEADERS_OFFSET + 2:
            return []

        try:
            chunk_count = struct.unpack_from("<H", data, _CHUNK_COUNT_OFFSET)[0]
        except struct.error:
            return []

        # 비정상적으로 큰 청크 수는 잘못된 오프셋일 가능성
        if chunk_count > 10_000:
            logger.warning("비정상 청크 수: %d → 스킵", chunk_count)
            return []

        headers = []
        offset = _CHUNK_HEADERS_OFFSET
        for _ in range(chunk_count):
            try:
                header = parse_chunk_header(data, offset)
                headers.append(header)
                offset += 17  # 청크 헤더 크기
            except RoflCorruptedError:
                break

        return headers

    def parse_events_only(self, rofl_path: str | Path) -> list[dict]:
        """
        이벤트만 빠르게 추출 (스냅샷 스킵).
        복호화 키 없이는 빈 리스트 반환.
        TODO: 복호화 구현 후 활성화.
        """
        return []

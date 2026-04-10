"""
.rofl 파일 헤더 메타데이터 추출.

청크 데이터 복호화 없이 헤더 구조만 읽어 빠르게 메타데이터 반환.
파싱 실패율이 낮아 PARTIAL 폴백에서도 신뢰성 있게 사용 가능.

.rofl 헤더 구조 (오프셋 기준):
  0x00 - 0x05 : Magic "RIOT\x00\x00" (6 bytes)
  0x06 - 0x09 : Signature offset (4 bytes LE)
  0x0A - 0x0D : Header length (4 bytes LE)
  0x0E - 0x11 : File length (4 bytes LE)
  0x12 - ...  : Metadata JSON (가변 길이, null-terminated 또는 길이 prefix)

실제 오프셋은 클라이언트 버전에 따라 달라질 수 있으므로
매직 검증 후 JSON 블록을 스캔 방식으로 탐색.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from app.parser.models import RoflCorruptedError, RoflMagicError

# .rofl 파일 시그니처 후보 (버전별 차이 존재)
_MAGIC_CANDIDATES = [
    b"RIOT\x00\x00",
    b"RIOT\x01\x00",
    b"RIOT\x02\x00",
]

_HEADER_FIXED_SIZE = 288  # 일반적인 고정 헤더 크기


def parse_metadata_only(rofl_path: str | Path) -> dict:
    """
    .rofl 전체 파싱 없이 헤더 메타데이터만 빠르게 추출.

    Returns:
        {
            "match_id": str,
            "game_version": str,
            "game_length": int,            # 밀리초
            "participants": [...],
            "stats_json": str,             # 원본 JSON 문자열
            ...
        }

    Raises:
        RoflMagicError: 파일 시그니처 불일치 (rofl 파일 아님)
        RoflCorruptedError: 메타데이터 JSON 파싱 실패
    """
    rofl_path = Path(rofl_path)
    with open(rofl_path, "rb") as f:
        data = f.read()

    return _parse_from_bytes(data)


def _parse_from_bytes(data: bytes) -> dict:
    """bytes에서 메타데이터 추출 (테스트 용이성을 위해 분리)"""
    if len(data) < 32:
        raise RoflMagicError(f"파일이 너무 작습니다: {len(data)} bytes")

    # ── 매직 검증 ─────────────────────────────────────────────────
    magic = data[:6]
    if not any(magic == m for m in _MAGIC_CANDIDATES):
        raise RoflMagicError(
            f"유효하지 않은 .rofl 시그니처: {magic!r} "
            f"(예상: {_MAGIC_CANDIDATES[0]!r})"
        )

    # ── 헤더에서 오프셋 읽기 ──────────────────────────────────────
    # 오프셋 0x06: metadata_offset (4 bytes LE)
    # 오프셋 0x0A: metadata_length (4 bytes LE)
    try:
        metadata_offset = struct.unpack_from("<I", data, 6)[0]
        metadata_length = struct.unpack_from("<I", data, 10)[0]
    except struct.error as e:
        raise RoflCorruptedError(f"헤더 오프셋 읽기 실패: {e}") from e

    # ── 메타데이터 JSON 추출 ──────────────────────────────────────
    # 헤더 오프셋이 비정상이면 스캔 방식으로 폴백
    json_bytes = _extract_json_block(data, metadata_offset, metadata_length)
    if json_bytes is None:
        # 스캔 방식: 첫 번째 '{' 에서 JSON 블록 탐색
        json_bytes = _scan_for_json(data)

    if json_bytes is None:
        raise RoflCorruptedError("메타데이터 JSON 블록을 찾을 수 없습니다")

    try:
        metadata = json.loads(json_bytes.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise RoflCorruptedError(f"메타데이터 JSON 파싱 실패: {e}") from e

    return _normalize_metadata(metadata)


def _extract_json_block(data: bytes, offset: int, length: int) -> bytes | None:
    """헤더 오프셋 기반 JSON 블록 추출"""
    if offset <= 0 or length <= 0:
        return None
    end = offset + length
    if end > len(data):
        return None
    block = data[offset:end].rstrip(b"\x00")
    # JSON 유효성 빠른 체크
    if block.startswith(b"{") and block.endswith(b"}"):
        return block
    return None


def _scan_for_json(data: bytes) -> bytes | None:
    """파일 전체에서 JSON 블록 스캔 (폴백)"""
    start_idx = data.find(b"{")
    if start_idx < 0:
        return None
    # 중첩 브레이스 카운팅으로 JSON 끝 탐색
    depth = 0
    for i, byte in enumerate(data[start_idx:], start=start_idx):
        if byte == ord("{"):
            depth += 1
        elif byte == ord("}"):
            depth -= 1
            if depth == 0:
                return data[start_idx: i + 1]
    return None


def _normalize_metadata(raw: dict) -> dict:
    """
    다양한 .rofl 버전의 메타데이터 키를 표준화.
    키 이름이 버전마다 다를 수 있으므로 여러 후보 키 시도.
    """
    # match_id 후보 키
    match_id = (
        raw.get("gameId")
        or raw.get("matchId")
        or raw.get("game_id")
        or ""
    )
    if match_id:
        match_id = str(match_id)

    # game_version 후보 키
    game_version = (
        raw.get("gameVersion")
        or raw.get("game_version")
        or raw.get("clientVersion")
        or ""
    )

    # game_length (밀리초)
    game_length_ms = (
        raw.get("gameLength")
        or raw.get("game_length")
        or 0
    )

    participants = raw.get("participants") or raw.get("statsJson") or []
    if isinstance(participants, str):
        # statsJson이 JSON 문자열인 경우
        try:
            participants = json.loads(participants)
        except json.JSONDecodeError:
            participants = []

    return {
        "match_id": match_id,
        "game_version": game_version,
        "game_length_ms": int(game_length_ms),
        "participants": participants,
        "raw": raw,  # 원본 보존
    }

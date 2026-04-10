"""
.rofl 청크 데이터 디코딩.

.rofl 청크는 암호화(XOR/AES) + 압축(zstd/zlib) 되어 있음.
복호화 키는 Riot API 매치 데이터에서 가져와야 함 (현재 미지원).
이 모듈은 압축 해제만 담당 (복호화는 별도 구현 필요).
"""
from __future__ import annotations

import zlib
from typing import Literal

from app.parser.models import RoflCorruptedError

# 청크 타입
ChunkType = Literal["KEYFRAME", "REGULAR"]

# zstd 옵션 임포트 (없으면 zlib만 사용)
try:
    import zstandard as zstd
    _HAS_ZSTD = True
except ImportError:
    _HAS_ZSTD = False


def decompress_chunk(data: bytes, algorithm: str = "auto") -> bytes:
    """
    청크 데이터 압축 해제.

    Args:
        data: 압축된 청크 bytes
        algorithm: "zstd" | "zlib" | "auto" (자동 탐지)

    Returns:
        압축 해제된 bytes

    Raises:
        RoflCorruptedError: 압축 해제 실패
    """
    if algorithm == "auto":
        algorithm = _detect_algorithm(data)

    if algorithm == "zstd":
        return _decompress_zstd(data)
    elif algorithm == "zlib":
        return _decompress_zlib(data)
    else:
        raise RoflCorruptedError(f"알 수 없는 압축 알고리즘: {algorithm!r}")


def _detect_algorithm(data: bytes) -> str:
    """매직 바이트로 압축 알고리즘 자동 탐지"""
    if len(data) < 4:
        return "zlib"
    # zstd 매직: 0xFD2FB528
    if data[:4] == b"\x28\xb5\x2f\xfd":
        return "zstd"
    # zlib 매직: 0x789C, 0x78DA, 0x7801
    if data[0] == 0x78 and data[1] in (0x01, 0x9C, 0xDA, 0x5E):
        return "zlib"
    # deflate (raw, no header)
    return "zlib"


def _decompress_zstd(data: bytes) -> bytes:
    if not _HAS_ZSTD:
        raise RoflCorruptedError(
            "zstd 라이브러리가 없습니다. pip install zstandard 실행 후 재시도하세요."
        )
    try:
        dctx = zstd.ZstdDecompressor()
        return dctx.decompress(data, max_output_size=64 * 1024 * 1024)  # 64MB 제한
    except zstd.ZstdError as e:
        raise RoflCorruptedError(f"zstd 압축 해제 실패: {e}") from e


def _decompress_zlib(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except zlib.error:
        try:
            # raw deflate (헤더 없음)
            return zlib.decompress(data, -zlib.MAX_WBITS)
        except zlib.error as e:
            raise RoflCorruptedError(f"zlib 압축 해제 실패: {e}") from e


def parse_chunk_header(data: bytes, offset: int) -> dict:
    """
    청크 헤더 파싱.

    청크 헤더 구조 (17 bytes):
      0: chunk_id (4 bytes LE)
      4: type (1 byte): 1=KEYFRAME, 2=REGULAR
      5: length (4 bytes LE) — 압축된 데이터 크기
      9: next_chunk_id (4 bytes LE)
     13: offset (4 bytes LE) — 파일 내 데이터 오프셋

    Returns:
        {"chunk_id": int, "type": str, "length": int, "next_chunk_id": int, "offset": int}
    """
    import struct

    if offset + 17 > len(data):
        raise RoflCorruptedError(f"청크 헤더 읽기 실패: 오프셋 {offset}에서 데이터 부족")

    chunk_id, type_byte, length, next_chunk_id, chunk_offset = struct.unpack_from(
        "<IBIII", data, offset
    )
    chunk_type = "KEYFRAME" if type_byte == 1 else "REGULAR"

    return {
        "chunk_id": chunk_id,
        "type": chunk_type,
        "length": length,
        "next_chunk_id": next_chunk_id,
        "offset": chunk_offset,
    }

"""
parser 모듈 단위 테스트.

실제 .rofl 파일 없이 테스트:
- 모델/예외 클래스
- validator (데이터 구조 검증)
- metadata (바이너리 파싱 — 테스트용 합성 데이터)
- chunk_decoder (압축 해제)
- resilience (폴백 로직 — Riot API mock)
"""
from __future__ import annotations

import json
import struct
import zlib

import pytest

from app.parser.chunk_decoder import decompress_chunk, _detect_algorithm, parse_chunk_header
from app.parser.metadata import _parse_from_bytes, _normalize_metadata
from app.parser.models import (
    ParseResult,
    RoflCorruptedError,
    RoflMagicError,
    ValidationReport,
)
from app.parser.validator import DataValidator
from app.parser.resilience import RoflResilienceLayer, _match_id_to_routing


# ── ParseResult / models ──────────────────────────────────────────
class TestParseResult:
    def test_defaults(self):
        r = ParseResult(events=[], snapshots={})
        assert r.quality == "FALLBACK"
        assert r.metadata == {}

    def test_event_count(self):
        r = ParseResult(events=[{"type": "A"}, {"type": "B"}], snapshots={})
        assert r.event_count() == 2

    def test_snapshot_count(self):
        r = ParseResult(events=[], snapshots={1000: {}, 2000: {}})
        assert r.snapshot_count() == 2

    def test_is_full(self):
        r = ParseResult(events=[], snapshots={}, quality="FULL")
        assert r.is_full() is True

    def test_not_full(self):
        r = ParseResult(events=[], snapshots={}, quality="PARTIAL")
        assert r.is_full() is False


# ── DataValidator ────────────────────────────────────────────────
class TestDataValidator:
    def _make_player(self, x=5000, y=5000):
        return {"position": {"x": x, "y": y}, "id": 1}

    def test_valid_empty(self):
        r = ParseResult(events=[], snapshots={})
        report = DataValidator().validate(r)
        assert report.is_valid

    def test_valid_with_events(self):
        events = [{"timestamp": i * 1000, "type": "KILL", "data": {}} for i in range(5)]
        r = ParseResult(events=events, snapshots={})
        report = DataValidator().validate(r)
        assert report.is_valid

    def test_event_timestamp_not_monotonic(self):
        events = [
            {"timestamp": 5000, "type": "A", "data": {}},
            {"timestamp": 3000, "type": "B", "data": {}},  # 역순
        ]
        r = ParseResult(events=events, snapshots={})
        report = DataValidator().validate(r)
        assert not report.is_valid
        assert any("역순" in issue for issue in report.issues)

    def test_snapshot_timestamp_gap(self):
        snapshots = {
            0: {"players": [], "wards": [], "minions": [], "towers": [], "events": []},
            15000: {"players": [], "wards": [], "minions": [], "towers": [], "events": []},  # 15초 갭
        }
        r = ParseResult(events=[], snapshots=snapshots)
        report = DataValidator().validate(r)
        assert not report.is_valid
        assert any("갭" in issue for issue in report.issues)

    def test_out_of_bounds_coordinate(self):
        snap = {
            "players": [self._make_player(x=99999, y=99999)],
            "wards": [], "minions": [], "towers": [], "events": [],
        }
        r = ParseResult(events=[], snapshots={0: snap})
        report = DataValidator().validate(r)
        assert not report.is_valid
        assert any("좌표" in issue for issue in report.issues)

    def test_valid_normal_coordinate(self):
        # 10명 플레이어 (정상 게임 구성)
        snap = {
            "players": [self._make_player(x=5000, y=5000) for _ in range(10)],
            "wards": [], "minions": [], "towers": [], "events": [],
        }
        r = ParseResult(events=[], snapshots={0: snap})
        report = DataValidator().validate(r)
        assert report.is_valid

    def test_abnormal_player_count(self):
        snap = {
            "players": [self._make_player() for _ in range(3)],  # 3명 (10명이 정상)
            "wards": [], "minions": [], "towers": [], "events": [],
        }
        r = ParseResult(events=[], snapshots={0: snap})
        report = DataValidator().validate(r)
        assert not report.is_valid


# ── metadata._parse_from_bytes ────────────────────────────────────
class TestParseFromBytes:
    def _make_rofl_bytes(self, meta: dict) -> bytes:
        """테스트용 최소 .rofl 바이너리 생성"""
        meta_json = json.dumps(meta).encode("utf-8")
        magic = b"RIOT\x00\x00"
        # metadata_offset = 14 (6 magic + 4 sig_offset + 4 header_len)
        # 실제로는 더 복잡하지만 테스트용으로 단순화
        metadata_offset = 14
        metadata_length = len(meta_json)
        header = magic + struct.pack("<II", metadata_offset, metadata_length)
        # 14 - 6 - 4 - 4 = 0 → offset 14까지 패딩
        padding = b"\x00" * (metadata_offset - len(header))
        return header + padding + meta_json

    def test_valid_rofl_with_metadata(self):
        meta = {"gameId": "KR_12345", "gameVersion": "14.1.0", "gameLength": 1800000}
        data = self._make_rofl_bytes(meta)
        result = _parse_from_bytes(data)
        assert result["match_id"] == "KR_12345"
        assert result["game_version"] == "14.1.0"
        assert result["game_length_ms"] == 1800000

    def test_invalid_magic_raises(self):
        data = b"NOTROFL" + b"\x00" * 100
        with pytest.raises(RoflMagicError):
            _parse_from_bytes(data)

    def test_too_small_raises(self):
        with pytest.raises(RoflMagicError):
            _parse_from_bytes(b"RIOT")

    def test_scan_fallback_for_json(self):
        """헤더 오프셋이 잘못되어도 JSON 스캔으로 찾아야 함"""
        meta_json = json.dumps({"gameId": "NA1_999"}).encode()
        # metadata_offset=0, length=0 → 스캔 폴백 트리거
        data = b"RIOT\x00\x00" + struct.pack("<II", 0, 0) + b"\x00\x00" + meta_json
        result = _parse_from_bytes(data)
        assert result["match_id"] == "NA1_999"


# ── _normalize_metadata ───────────────────────────────────────────
class TestNormalizeMetadata:
    def test_gameid_key(self):
        result = _normalize_metadata({"gameId": "KR_1"})
        assert result["match_id"] == "KR_1"

    def test_matchid_key(self):
        result = _normalize_metadata({"matchId": "EUW1_2"})
        assert result["match_id"] == "EUW1_2"

    def test_missing_keys(self):
        result = _normalize_metadata({})
        assert result["match_id"] == ""
        assert result["game_version"] == ""
        assert result["game_length_ms"] == 0


# ── chunk_decoder ─────────────────────────────────────────────────
class TestChunkDecoder:
    def test_detect_zlib(self):
        data = zlib.compress(b"hello world")
        assert _detect_algorithm(data) == "zlib"

    def test_decompress_zlib(self):
        original = b"League of Legends replay data " * 10
        compressed = zlib.compress(original)
        result = decompress_chunk(compressed, algorithm="zlib")
        assert result == original

    def test_decompress_auto(self):
        original = b"test data for auto detection"
        compressed = zlib.compress(original)
        result = decompress_chunk(compressed, algorithm="auto")
        assert result == original

    def test_invalid_data_raises(self):
        with pytest.raises(RoflCorruptedError):
            decompress_chunk(b"\x00" * 20, algorithm="zlib")

    def test_parse_chunk_header_valid(self):
        # chunk_id=1, type=1(KEYFRAME), length=100, next_chunk_id=2, offset=500
        data = struct.pack("<IBIII", 1, 1, 100, 2, 500) + b"\x00" * 100
        header = parse_chunk_header(data, 0)
        assert header["chunk_id"] == 1
        assert header["type"] == "KEYFRAME"
        assert header["length"] == 100
        assert header["next_chunk_id"] == 2
        assert header["offset"] == 500

    def test_parse_chunk_header_regular(self):
        data = struct.pack("<IBIII", 5, 2, 200, 6, 1000) + b"\x00" * 100
        header = parse_chunk_header(data, 0)
        assert header["type"] == "REGULAR"

    def test_parse_chunk_header_insufficient_data(self):
        with pytest.raises(RoflCorruptedError):
            parse_chunk_header(b"\x00" * 5, 0)


# ── resilience._match_id_to_routing ──────────────────────────────
class TestMatchIdRouting:
    def test_kr(self):
        assert _match_id_to_routing("KR_12345") == "asia"

    def test_euw(self):
        assert _match_id_to_routing("EUW1_99") == "europe"

    def test_na(self):
        assert _match_id_to_routing("NA1_55") == "americas"

    def test_unknown_prefix(self):
        assert _match_id_to_routing("UNKNOWN_1") == "asia"  # 기본값

    def test_no_underscore(self):
        assert _match_id_to_routing("NOMATCH") == "asia"


# ── RoflResilienceLayer (폴백 로직) ──────────────────────────────
class TestRoflResilienceLayer:
    def test_fallback_when_no_rofl_no_api(self):
        """파일 없고 API 키도 없으면 빈 FALLBACK 반환"""
        layer = RoflResilienceLayer(riot_api_key="")
        result = layer.parse_with_fallback("", match_id="KR_1")
        assert result.quality == "FALLBACK"
        assert result.metadata.get("parse_failed") is True

    def test_partial_when_riot_api_returns_timeline(self, monkeypatch):
        """Riot API 호출 성공 시 PARTIAL 반환 (2단계 폴백)"""
        timeline = {
            "info": {
                "frames": [
                    {
                        "events": [
                            {"timestamp": 1000, "type": "CHAMPION_KILL", "killerId": 1},
                            {"timestamp": 5000, "type": "WARD_PLACED", "wardType": "YELLOW_TRINKET"},
                        ]
                    }
                ]
            }
        }

        layer = RoflResilienceLayer(riot_api_key="test-key")
        monkeypatch.setattr(layer, "_fetch_timeline", lambda match_id: timeline)

        # .rofl 없이 match_id만으로 → step 2 (PARTIAL)
        result = layer.parse_with_fallback("", match_id="KR_999")
        assert result.quality == "PARTIAL"
        assert len(result.events) == 2
        assert result.events[0]["type"] == "CHAMPION_KILL"

    def test_fallback_when_riot_api_fails(self, monkeypatch):
        """Riot API 실패 시 빈 FALLBACK 반환"""
        layer = RoflResilienceLayer(riot_api_key="test-key")
        monkeypatch.setattr(
            layer, "_fetch_timeline",
            lambda match_id: (_ for _ in ()).throw(Exception("API 오류"))
        )

        result = layer.parse_with_fallback("", match_id="KR_1")
        assert result.quality == "FALLBACK"
        assert result.metadata.get("parse_failed") is True

    def test_timeline_to_parse_result(self):
        """타임라인 변환 결과 검증"""
        layer = RoflResilienceLayer(riot_api_key="")
        timeline = {
            "info": {
                "frames": [
                    {"events": [{"timestamp": 100, "type": "A"}]},
                    {"events": [{"timestamp": 50, "type": "B"}]},  # 역순
                ]
            }
        }
        result = layer._timeline_to_parse_result(timeline)
        # 타임스탬프 오름차순 정렬 확인
        assert result.events[0]["timestamp"] == 50
        assert result.events[1]["timestamp"] == 100
        assert result.quality == "FALLBACK"
        assert result.snapshots == {}

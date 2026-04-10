"""
analysis/ 모듈 테스트.

utils, game_context, game_state_engine, wave_engine 중심.
"""
import pytest

# ── 픽스처 헬퍼 ──────────────────────────────────────────────────

def _make_snap(ts: int, player_id: int = 1, team: str = "blue", **overrides) -> dict:
    """테스트용 단일 스냅샷 생성"""
    players = [
        {"id": p_id, "team": "blue" if p_id <= 5 else "red",
         "hp": 1000, "max_hp": 1000, "level": 1, "gold": 1000, "cs": 0,
         "position": {"x": 1000.0 * p_id, "y": 1000.0}}
        for p_id in range(1, 11)  # 10명
    ]
    # player_id 오버라이드
    for p in players:
        if p["id"] == player_id:
            p["team"] = team
            p.update(overrides)
    return {"players": players, "minions": []}


def _make_snapshots(*timestamps, player_id: int = 1, **overrides) -> dict:
    return {ts: _make_snap(ts, player_id=player_id, **overrides) for ts in timestamps}


def _make_event(ts: int, etype: str, **data) -> dict:
    return {"timestamp": ts, "type": etype, "data": data}


# ══════════════════════════════════════════════════════════════════
# utils.py
# ══════════════════════════════════════════════════════════════════

class TestGetSnapshotAt:
    def test_exact_match(self):
        from app.analysis.utils import get_snapshot_at
        snaps = {1000: {"a": 1}, 2000: {"a": 2}}
        assert get_snapshot_at(1000, snaps)["a"] == 1

    def test_nearest_before(self):
        from app.analysis.utils import get_snapshot_at
        snaps = {1000: {"a": 1}, 3000: {"a": 3}}
        assert get_snapshot_at(1400, snaps)["a"] == 1

    def test_nearest_after(self):
        from app.analysis.utils import get_snapshot_at
        snaps = {1000: {"a": 1}, 3000: {"a": 3}}
        assert get_snapshot_at(2600, snaps)["a"] == 3

    def test_empty_returns_empty(self):
        from app.analysis.utils import get_snapshot_at
        assert get_snapshot_at(1000, {}) == {}

    def test_single_snapshot(self):
        from app.analysis.utils import get_snapshot_at
        snaps = {5000: {"v": 99}}
        assert get_snapshot_at(1, snaps)["v"] == 99
        assert get_snapshot_at(9999, snaps)["v"] == 99


class TestEuclideanDistance:
    def test_zero_distance(self):
        from app.analysis.utils import euclidean_distance
        assert euclidean_distance({"x": 1, "y": 1}, {"x": 1, "y": 1}) == 0.0

    def test_3_4_5_triangle(self):
        from app.analysis.utils import euclidean_distance
        dist = euclidean_distance({"x": 0, "y": 0}, {"x": 3, "y": 4})
        assert abs(dist - 5.0) < 1e-9


class TestNormalizePosition:
    def test_center(self):
        from app.analysis.utils import normalize_position
        result = normalize_position({"x": 7500, "y": 7500})
        assert result == {"x": 0.5, "y": 0.5}

    def test_clamp(self):
        from app.analysis.utils import normalize_position
        result = normalize_position({"x": -100, "y": 20000})
        assert result["x"] == 0.0
        assert result["y"] == 1.0


class TestGetPlayerTeam:
    def test_found(self):
        from app.analysis.utils import get_player_team
        snap = {"players": [{"id": 1, "team": "blue"}, {"id": 2, "team": "red"}]}
        assert get_player_team(snap, 1) == "blue"
        assert get_player_team(snap, 2) == "red"

    def test_not_found(self):
        from app.analysis.utils import get_player_team
        assert get_player_team({"players": []}, 99) == "unknown"


class TestGetPlayerPosition:
    def test_found(self):
        from app.analysis.utils import get_player_position
        snap = {"players": [{"id": 1, "position": {"x": 100.0, "y": 200.0}}]}
        pos = get_player_position(snap, 1)
        assert pos == {"x": 100.0, "y": 200.0}

    def test_not_found_returns_center(self):
        from app.analysis.utils import get_player_position
        pos = get_player_position({"players": []}, 99)
        assert pos == {"x": 7500.0, "y": 7500.0}


class TestAnyWardCovers:
    def test_within_radius(self):
        from app.analysis.utils import any_ward_covers
        wards = [{"position": {"x": 0.0, "y": 0.0}}]
        assert any_ward_covers(wards, {"x": 500.0, "y": 0.0}, radius=900.0)

    def test_outside_radius(self):
        from app.analysis.utils import any_ward_covers
        wards = [{"position": {"x": 0.0, "y": 0.0}}]
        assert not any_ward_covers(wards, {"x": 1000.0, "y": 0.0}, radius=900.0)

    def test_empty_wards(self):
        from app.analysis.utils import any_ward_covers
        assert not any_ward_covers([], {"x": 0.0, "y": 0.0})


class TestFilterEventsInWindow:
    def test_filters_by_time(self):
        from app.analysis.utils import filter_events_in_window
        events = [
            {"timestamp": 1000, "type": "A"},
            {"timestamp": 2000, "type": "A"},
            {"timestamp": 3000, "type": "A"},
        ]
        result = filter_events_in_window(events, 1500, 2500)
        assert len(result) == 1
        assert result[0]["timestamp"] == 2000

    def test_filters_by_type(self):
        from app.analysis.utils import filter_events_in_window
        events = [
            {"timestamp": 1000, "type": "KILL"},
            {"timestamp": 1500, "type": "WARD"},
        ]
        result = filter_events_in_window(events, 0, 2000, event_type="KILL")
        assert len(result) == 1

    def test_inclusive_bounds(self):
        from app.analysis.utils import filter_events_in_window
        events = [{"timestamp": 1000, "type": "X"}, {"timestamp": 2000, "type": "X"}]
        result = filter_events_in_window(events, 1000, 2000)
        assert len(result) == 2


class TestEstimateCrashTime:
    def test_equal_waves_returns_nonzero(self):
        from app.analysis.utils import estimate_crash_time
        minions = [{"type": "MELEE"} for _ in range(3)] + [{"type": "CASTER"} for _ in range(3)]
        t = estimate_crash_time(minions, minions)
        assert t > 0

    def test_empty_returns_30(self):
        from app.analysis.utils import estimate_crash_time
        assert estimate_crash_time([], []) == 30.0

    def test_one_side_empty(self):
        from app.analysis.utils import estimate_crash_time
        minions = [{"type": "MELEE"}]
        assert estimate_crash_time(minions, []) == 30.0


# ══════════════════════════════════════════════════════════════════
# game_context.py
# ══════════════════════════════════════════════════════════════════

class TestGameContext:
    def _make_ctx(self, snapshots=None, events=None, metadata=None):
        from app.analysis.game_context import GameContext
        return GameContext(
            snapshots=snapshots or {},
            events=events or [],
            metadata=metadata or {"player_id": 1, "champion_id": 67},
            data_quality="FULL",
        )

    def test_player_id_property(self):
        ctx = self._make_ctx(metadata={"player_id": 42})
        assert ctx.player_id == 42

    def test_has_snapshots_false(self):
        ctx = self._make_ctx()
        assert not ctx.has_snapshots()

    def test_has_snapshots_true(self):
        ctx = self._make_ctx(snapshots={1000: {"players": []}})
        assert ctx.has_snapshots()

    def test_game_duration_from_snapshots(self):
        ctx = self._make_ctx(snapshots={60_000: {}, 120_000: {}})
        assert ctx.game_duration_ms() == 120_000

    def test_game_duration_from_events(self):
        ctx = self._make_ctx(events=[{"timestamp": 90_000}])
        assert ctx.game_duration_ms() == 90_000

    def test_game_duration_empty(self):
        ctx = self._make_ctx()
        assert ctx.game_duration_ms() == 0

    def test_snapshot_timestamps_sorted(self):
        ctx = self._make_ctx(snapshots={3000: {}, 1000: {}, 2000: {}})
        assert ctx.snapshot_timestamps() == [1000, 2000, 3000]

    def test_from_parse_result(self):
        from dataclasses import dataclass, field
        from app.analysis.game_context import GameContext

        @dataclass
        class FakeParseResult:
            snapshots: dict = field(default_factory=dict)
            events: list = field(default_factory=list)
            quality: str = "FULL"
            metadata: dict = field(default_factory=dict)

        pr = FakeParseResult(
            snapshots={1000: {}},
            events=[{"timestamp": 1000}],
            quality="PARTIAL",
            metadata={"player_id": 5},
        )
        ctx = GameContext.from_parse_result(pr, metadata={"role": "MID"})
        assert ctx.player_id == 5
        assert ctx.role == "MID"
        assert ctx.data_quality == "PARTIAL"


# ══════════════════════════════════════════════════════════════════
# game_state_engine.py
# ══════════════════════════════════════════════════════════════════

class TestGameStateEngine:
    def _make_ctx(self, duration_ms: int = 300_000):
        from app.analysis.game_context import GameContext
        snaps = _make_snapshots(*range(60_000, duration_ms + 60_000, 60_000))
        return GameContext(
            snapshots=snaps,
            events=[],
            metadata={"player_id": 1, "champion_id": 67},
            data_quality="FULL",
        )

    def test_run_returns_dict(self):
        from app.analysis.game_state_engine import GameStateEngine
        ctx = self._make_ctx()
        result = GameStateEngine().run(ctx)
        assert "game_state_timeline" in result
        assert isinstance(result["game_state_timeline"], list)

    def test_timeline_length(self):
        from app.analysis.game_state_engine import GameStateEngine
        ctx = self._make_ctx(duration_ms=300_000)  # 5분
        result = GameStateEngine().run(ctx)
        # 1분 간격: 1~6분 → 최대 6개
        assert len(result["game_state_timeline"]) >= 1

    def test_game_state_fields(self):
        from app.analysis.game_state_engine import GameState, GameStateEngine
        ctx = self._make_ctx()
        result = GameStateEngine().run(ctx)
        state = result["game_state_timeline"][0]
        assert isinstance(state, GameState)
        assert state.phase in ("AHEAD", "EVEN", "BEHIND", "SNOWBALL", "COMEBACK")
        assert 0.0 <= state.confidence <= 1.0

    def test_empty_context_returns_empty_timeline(self):
        from app.analysis.game_context import GameContext
        from app.analysis.game_state_engine import GameStateEngine
        ctx = GameContext(snapshots={}, events=[], metadata={}, data_quality="FALLBACK")
        result = GameStateEngine().run(ctx)
        assert result["game_state_timeline"] == []

    def test_fallback_no_snapshots(self):
        """스냅샷 없어도 이벤트만으로 동작"""
        from app.analysis.game_context import GameContext
        from app.analysis.game_state_engine import GameStateEngine
        events = [
            _make_event(60_000, "CHAMPION_KILL", killerId=1, victimId=6),
            _make_event(120_000, "CHAMPION_KILL", killerId=1, victimId=7),
        ]
        ctx = GameContext(
            snapshots={},
            events=events,
            metadata={"player_id": 1, "participant_id": 1},
            data_quality="FALLBACK",
        )
        result = GameStateEngine().run(ctx)
        # 이벤트 기반 duration으로 타임라인 생성
        assert len(result["game_state_timeline"]) >= 1

    def test_classify_phase_snowball(self):
        from app.analysis.game_state_engine import GameStateEngine
        engine = GameStateEngine()
        phase = engine._classify_phase(5000, 10, 3, 4)
        assert phase == "SNOWBALL"

    def test_classify_phase_behind(self):
        from app.analysis.game_state_engine import GameStateEngine
        engine = GameStateEngine()
        # score = -2500/500 = -5 → BEHIND (> COMEBACK threshold of -6)
        phase = engine._classify_phase(-2500, 0, 0, 0)
        assert phase == "BEHIND"

    def test_classify_phase_even(self):
        from app.analysis.game_state_engine import GameStateEngine
        engine = GameStateEngine()
        phase = engine._classify_phase(0, 0, 0, 0)
        assert phase == "EVEN"

    def test_gold_lead_calculated(self):
        """골드 리드가 스냅샷에서 올바르게 계산되는지"""
        from app.analysis.game_context import GameContext
        from app.analysis.game_state_engine import GameStateEngine

        snap = {
            "players": [
                {"id": i, "team": "blue", "gold": 2000} for i in range(1, 6)
            ] + [
                {"id": i, "team": "red", "gold": 1000} for i in range(6, 11)
            ]
        }
        ctx = GameContext(
            snapshots={60_000: snap},
            events=[],
            metadata={"player_id": 1},
            data_quality="FULL",
        )
        result = GameStateEngine().run(ctx)
        states = result["game_state_timeline"]
        assert len(states) >= 1
        # 블루팀 골드 10000, 레드팀 골드 5000 → gold_lead = 5000
        assert states[0].gold_lead == 5000

    def test_kill_events_accumulated(self):
        """킬 이벤트가 올바르게 누적되는지"""
        from app.analysis.game_context import GameContext
        from app.analysis.game_state_engine import GameStateEngine

        snap = _make_snap(60_000, player_id=1, team="blue")
        events = [
            _make_event(30_000, "CHAMPION_KILL", killerId=1, victimId=6),
            _make_event(45_000, "CHAMPION_KILL", killerId=1, victimId=7),
        ]
        ctx = GameContext(
            snapshots={60_000: snap},
            events=events,
            metadata={"player_id": 1, "participant_id": 1},
            data_quality="FULL",
        )
        result = GameStateEngine().run(ctx)
        states = result["game_state_timeline"]
        assert states[0].kill_lead >= 2

    def test_dragon_stacks_accumulated(self):
        """드래곤 이벤트가 올바르게 누적되는지"""
        from app.analysis.game_context import GameContext
        from app.analysis.game_state_engine import GameStateEngine

        snap = _make_snap(60_000, player_id=1)
        events = [
            _make_event(30_000, "ELITE_MONSTER_KILL",
                        monsterType="DRAGON", killerId=1),
        ]
        ctx = GameContext(
            snapshots={60_000: snap},
            events=events,
            metadata={"player_id": 1, "participant_id": 1},
            data_quality="FULL",
        )
        result = GameStateEngine().run(ctx)
        assert result["game_state_timeline"][0].dragon_stacks == 1

    def test_confidence_with_snapshots(self):
        from app.analysis.game_state_engine import GameStateEngine
        ctx = self._make_ctx()
        result = GameStateEngine().run(ctx)
        assert result["game_state_timeline"][0].confidence == 1.0

    def test_confidence_without_snapshots(self):
        from app.analysis.game_context import GameContext
        from app.analysis.game_state_engine import GameStateEngine
        ctx = GameContext(
            snapshots={},
            events=[_make_event(60_000, "CHAMPION_KILL", killerId=1, victimId=6)],
            metadata={"player_id": 1, "participant_id": 1},
            data_quality="FALLBACK",
        )
        result = GameStateEngine().run(ctx)
        assert result["game_state_timeline"][0].confidence == 0.4


# ══════════════════════════════════════════════════════════════════
# wave_engine.py
# ══════════════════════════════════════════════════════════════════

class TestWaveEngine:
    def _make_ctx_with_minions(
        self,
        duration_ms: int = 60_000,
        my_minions: int = 3,
        enemy_minions: int = 3,
        player_id: int = 1,
    ):
        from app.analysis.game_context import GameContext

        minions = (
            [{"team": "blue", "type": "MELEE", "position": {"x": 7000.0, "y": 7000.0}}
             for _ in range(my_minions)]
            + [{"team": "red", "type": "MELEE", "position": {"x": 8000.0, "y": 7000.0}}
               for _ in range(enemy_minions)]
        )
        snap = _make_snap(60_000, player_id=player_id)
        snap["minions"] = minions

        return GameContext(
            snapshots={60_000: snap},
            events=[],
            metadata={"player_id": player_id},
            data_quality="FULL",
        )

    def test_run_returns_dict(self):
        from app.analysis.wave_engine import WaveEngine
        ctx = self._make_ctx_with_minions()
        result = WaveEngine().run(ctx)
        assert "wave_timeline" in result
        assert isinstance(result["wave_timeline"], dict)

    def test_no_snapshots_returns_empty(self):
        from app.analysis.game_context import GameContext
        from app.analysis.wave_engine import WaveEngine
        ctx = GameContext(
            snapshots={}, events=[], metadata={"player_id": 1}, data_quality="FALLBACK"
        )
        result = WaveEngine().run(ctx)
        assert result["wave_timeline"] == {}

    def test_wave_state_fields(self):
        from app.analysis.wave_engine import WaveEngine, WaveState
        ctx = self._make_ctx_with_minions()
        result = WaveEngine().run(ctx)
        assert len(result["wave_timeline"]) > 0
        state = next(iter(result["wave_timeline"].values()))
        assert isinstance(state, WaveState)
        assert state.state in ("FAST_PUSH", "SLOW_PUSH", "FREEZE", "EVEN", "CRASHING", "LOSING_WAVE")
        assert state.fight_risk_modifier >= 0.5

    def test_fast_push_classification(self):
        from app.analysis.wave_engine import _classify_wave
        assert _classify_wave(advantage=5, wave_pos=0.3) == "FAST_PUSH"

    def test_slow_push_classification(self):
        from app.analysis.wave_engine import _classify_wave
        assert _classify_wave(advantage=2, wave_pos=0.3) == "SLOW_PUSH"

    def test_losing_wave_classification(self):
        from app.analysis.wave_engine import _classify_wave
        assert _classify_wave(advantage=-5, wave_pos=0.3) == "LOSING_WAVE"

    def test_crashing_classification(self):
        from app.analysis.wave_engine import _classify_wave
        assert _classify_wave(advantage=0, wave_pos=0.8) == "CRASHING"

    def test_freeze_classification(self):
        from app.analysis.wave_engine import _classify_wave
        assert _classify_wave(advantage=-3, wave_pos=0.2) == "FREEZE"

    def test_even_classification(self):
        from app.analysis.wave_engine import _classify_wave
        assert _classify_wave(advantage=1, wave_pos=0.5) == "EVEN"

    def test_detect_wave_state_no_player(self):
        """플레이어 없는 스냅샷 → 기본 WaveState"""
        from app.analysis.wave_engine import detect_wave_state
        snaps = {1000: {"players": [], "minions": []}}
        state = detect_wave_state(1000, snaps, player_id=99)
        assert state.state == "EVEN"
        assert state.my_minion_count == 0

    def test_max_samples_limit(self):
        """360개 최대 샘플 제한"""
        from app.analysis.game_context import GameContext
        from app.analysis.wave_engine import WaveEngine, _MAX_SAMPLES

        # 40분짜리 게임 (480개 이론 샘플)
        duration_ms = 40 * 60 * 1000
        snap = _make_snap(5000, player_id=1)
        snaps = {ts: snap for ts in range(5_000, duration_ms + 5_000, 5_000)}

        ctx = GameContext(
            snapshots=snaps, events=[],
            metadata={"player_id": 1}, data_quality="FULL",
        )
        result = WaveEngine().run(ctx)
        assert len(result["wave_timeline"]) <= _MAX_SAMPLES

    def test_fight_risk_modifier_losing_wave(self):
        from app.analysis.wave_engine import _calc_fight_risk
        assert _calc_fight_risk("LOSING_WAVE", 0.3) > 1.0

    def test_fight_risk_modifier_crashing(self):
        from app.analysis.wave_engine import _calc_fight_risk
        assert _calc_fight_risk("CRASHING", 0.8) < 1.0


# ══════════════════════════════════════════════════════════════════
# fight_simulator.py
# ══════════════════════════════════════════════════════════════════

class TestFightSimulator:
    def _make_fighter(self, hp=1000, ad=80, armor=50, attack_speed=0.7):
        return {"hp": hp, "max_hp": 1000, "ad": ad, "ap": 0,
                "armor": armor, "mr": 40, "attack_speed": attack_speed,
                "armor_pen": 0}

    def test_basic_fight_returns_result(self):
        from app.analysis.fight_simulator import simulate_full_fight_basic
        me = self._make_fighter()
        enemy = self._make_fighter(hp=300)
        env = {"minion_count": 0, "jungler_arrival_sec": 10.0}
        result = simulate_full_fight_basic(me, enemy, env)
        assert result.can_kill
        assert result.verdict in ("GREEN", "YELLOW", "ORANGE", "RED")

    def test_hp_ratios_in_range(self):
        from app.analysis.fight_simulator import simulate_full_fight_basic
        me = self._make_fighter()
        enemy = self._make_fighter()
        result = simulate_full_fight_basic(me, enemy, {})
        assert 0.0 <= result.my_hp_remaining <= 1.0
        assert 0.0 <= result.enemy_hp_remaining <= 1.0

    def test_weak_enemy_can_be_killed(self):
        from app.analysis.fight_simulator import simulate_full_fight_basic
        me = self._make_fighter(hp=1000, ad=200)
        enemy = self._make_fighter(hp=100)
        result = simulate_full_fight_basic(me, enemy, {})
        assert result.can_kill

    def test_minion_damage_positive(self):
        from app.analysis.fight_simulator import calc_minion_damage
        dmg = calc_minion_damage(3, 5.0, 50.0, "CASTER")
        assert dmg > 0

    def test_determine_verdict_green(self):
        from app.analysis.fight_simulator import _determine_verdict
        assert _determine_verdict(0.8, 0.0) == "GREEN"

    def test_determine_verdict_red(self):
        from app.analysis.fight_simulator import _determine_verdict
        assert _determine_verdict(0.0, 0.5) == "RED"

    def test_simulate_full_fight_wave_context(self):
        from app.analysis.fight_simulator import simulate_full_fight
        from app.analysis.wave_engine import _default_wave_state
        me = self._make_fighter()
        enemy = self._make_fighter()
        wave = _default_wave_state()
        result = simulate_full_fight(me, enemy, {}, wave_state=wave)
        assert result.wave_context is wave


# ══════════════════════════════════════════════════════════════════
# pipeline (run_analysis_pipeline)
# ══════════════════════════════════════════════════════════════════

class TestRunAnalysisPipeline:
    def _make_ctx(self):
        from app.analysis.game_context import GameContext
        snap = _make_snap(60_000, player_id=1)
        snap["minions"] = []
        return GameContext(
            snapshots={60_000: snap, 120_000: snap},
            events=[
                _make_event(30_000, "CHAMPION_KILL", killerId=1, victimId=6),
            ],
            metadata={"player_id": 1, "champion_id": 67, "participant_id": 1},
            data_quality="FULL",
        )

    def test_pipeline_runs_without_error(self):
        from app.analysis.game_context import run_analysis_pipeline
        ctx = self._make_ctx()
        result = run_analysis_pipeline(ctx)
        assert result is not None

    def test_pipeline_fills_stage1(self):
        from app.analysis.game_context import run_analysis_pipeline
        ctx = self._make_ctx()
        run_analysis_pipeline(ctx)
        assert ctx.game_state_timeline is not None
        assert ctx.wave_timeline is not None
        assert ctx.composition is not None

    def test_pipeline_fills_player_model(self):
        from app.analysis.game_context import run_analysis_pipeline
        ctx = self._make_ctx()
        run_analysis_pipeline(ctx)
        assert ctx.player_model is not None
        assert "pending_update" in ctx.player_model

    def test_pipeline_fallback_no_snapshots(self):
        """스냅샷 없어도 파이프라인 완료"""
        from app.analysis.game_context import GameContext, run_analysis_pipeline
        ctx = GameContext(
            snapshots={},
            events=[_make_event(60_000, "CHAMPION_KILL", killerId=1, victimId=6)],
            metadata={"player_id": 1, "participant_id": 1},
            data_quality="FALLBACK",
        )
        result = run_analysis_pipeline(ctx)
        assert result.player_model is not None


# ══════════════════════════════════════════════════════════════════
# composition_engine.py
# ══════════════════════════════════════════════════════════════════

class TestCompositionEngine:
    def test_analyze_returns_report(self):
        from app.analysis.composition_engine import analyze
        my_team = [67, 54, 89, 64, 40]   # Vayne, Malphite, Leona, Lee Sin, Janna
        enemy_team = [23, 75, 114, 59, 12]
        report = analyze(my_team, enemy_team)
        assert report.my_archetype != ""
        assert report.enemy_archetype != ""
        assert "early" in report.phase_advantage

    def test_scaling_archetype(self):
        from app.analysis.composition_engine import _determine_team_archetype
        assert _determine_team_archetype([67, 96, 136]) == "SCALING"

    def test_empty_team(self):
        from app.analysis.composition_engine import _determine_team_archetype
        result = _determine_team_archetype([])
        assert result == "EVEN"

    def test_phase_advantage_scaling_vs_engage(self):
        from app.analysis.composition_engine import _calc_phase_advantage
        adv = _calc_phase_advantage("SCALING", "ENGAGE")
        # SCALING은 후반 강세
        assert adv.get("late") == "PLAYER"


# ══════════════════════════════════════════════════════════════════
# player_model_engine.py
# ══════════════════════════════════════════════════════════════════

class TestPlayerModelEngine:
    def test_update_mistake_pattern(self):
        from app.analysis.player_model_engine import _update_mistake_pattern
        mistakes = [{"type": "macro"}, {"type": "macro"}, {"type": "positioning"}]
        result = _update_mistake_pattern({}, mistakes)
        assert result["macro"] > result["positioning"]

    def test_ema_decay_missing_type(self):
        """이번 경기에 없는 실수 타입은 EMA 감소"""
        from app.analysis.player_model_engine import _update_mistake_pattern
        existing = {"macro": 0.5}
        result = _update_mistake_pattern(existing, [])
        assert result["macro"] < 0.5

    def test_refresh_focus_tasks_top3(self):
        from app.analysis.player_model_engine import _refresh_focus_tasks
        patterns = {"macro": 0.8, "positioning": 0.6, "wave": 0.4, "vision": 0.2}
        tasks = _refresh_focus_tasks(patterns)
        assert len(tasks) == 3
        assert tasks[0]["type"] == "macro"
        assert tasks[0]["priority"] == 1

    def test_update_stat_gaps(self):
        from app.analysis.player_model_engine import _CHALLENGER_BENCHMARK, _update_stat_gaps
        stats = {"gold_lead": 0, "kill_lead": 0}
        result = _update_stat_gaps({}, stats, _CHALLENGER_BENCHMARK)
        assert result["gold_lead"] > 0  # 챌린저보다 부족

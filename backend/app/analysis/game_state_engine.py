"""
게임 국면 분류 엔진.

이벤트 로그(킬, 타워, 오브젝트)와 스냅샷(골드)을 기반으로
시간대별 게임 국면(AHEAD/EVEN/BEHIND/SNOWBALL/COMEBACK)을 분류한다.

FALLBACK/PARTIAL 모두 지원 (이벤트만으로도 동작).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.analysis.utils import filter_events_in_window, get_snapshot_at

logger = logging.getLogger(__name__)

# 국면 판단 임계값
_GOLD_LEAD_AHEAD = 1500     # 1500골드 이상 리드 → AHEAD
_GOLD_LEAD_SNOWBALL = 3000  # 3000골드 이상 → SNOWBALL
_GOLD_LEAD_BEHIND = -1500   # -1500 이하 → BEHIND
_GOLD_COMEBACK = -3000      # -3000 이하지만 회복 중 → COMEBACK

# 분석 간격 (ms)
_SAMPLE_INTERVAL_MS = 60_000  # 1분마다 GameState 생성


@dataclass
class GameState:
    """특정 시점의 게임 국면 스냅샷"""
    timestamp_ms: int
    phase: str              # AHEAD / EVEN / BEHIND / SNOWBALL / COMEBACK
    gold_lead: int          # 양수 = 내 팀 앞섬
    tower_lead: int         # 양수 = 내 팀 타워 더 많이 파괴
    kill_lead: int          # 양수 = 내 팀 킬 앞섬
    dragon_stacks: int      # 내 팀 드래곤 스택
    baron_active: bool      # 내 팀 바론 버프 중
    scaling_type: str       # PLAYER_SCALING / ENEMY_SCALING / EVEN
    confidence: float       # 0.0~1.0 (데이터 충분도)


class GameStateEngine:
    """
    GameContext → game_state_timeline 생성.

    인터페이스: run(ctx) -> {"game_state_timeline": list[GameState]}
    """

    def run(self, ctx) -> dict:
        """
        Args:
            ctx: GameContext

        Returns:
            {"game_state_timeline": list[GameState]}
        """
        try:
            timeline = self._build_timeline(ctx)
            return {"game_state_timeline": timeline}
        except Exception:
            logger.exception("GameStateEngine 실패")
            return {"game_state_timeline": []}

    def _build_timeline(self, ctx) -> list[GameState]:
        """1분 간격으로 GameState 생성"""
        duration_ms = ctx.game_duration_ms()
        if duration_ms <= 0:
            return []

        player_team = self._detect_player_team(ctx)
        timeline: list[GameState] = []

        # 누적 카운터
        my_kills = 0
        enemy_kills = 0
        my_towers = 0
        enemy_towers = 0
        my_dragons = 0
        my_baron_active = False

        ts = _SAMPLE_INTERVAL_MS
        while ts <= duration_ms + _SAMPLE_INTERVAL_MS:
            # 이 시점까지의 누적 이벤트 처리
            window_events = filter_events_in_window(
                ctx.events, ts - _SAMPLE_INTERVAL_MS, ts
            )
            for e in window_events:
                data = e.get("data", e)
                etype = e.get("type", "")

                if etype == "CHAMPION_KILL":
                    killer_team = self._get_event_team(data, "killerId", player_team, ctx)
                    if killer_team == "player":
                        my_kills += 1
                    else:
                        enemy_kills += 1

                elif etype == "BUILDING_KILL":
                    killer_team = self._get_event_team(data, "killerId", player_team, ctx)
                    if killer_team == "player":
                        my_towers += 1
                    else:
                        enemy_towers += 1

                elif etype == "ELITE_MONSTER_KILL":
                    monster = data.get("monsterType", "")
                    killer_team = self._get_event_team(data, "killerId", player_team, ctx)
                    if monster == "DRAGON" and killer_team == "player":
                        my_dragons += 1
                    elif monster == "BARON_NASHOR":
                        if killer_team == "player":
                            my_baron_active = True
                        else:
                            my_baron_active = False

            # 바론 버프 만료 (3분)
            # (단순화: 바론 획득 후 3분 이내 타임스탬프 구간에서만 True)
            # 실제로는 이벤트로 추적해야 하지만 여기서는 근사

            # 골드 리드 계산 (스냅샷 기반)
            gold_lead = self._calc_gold_lead(ts, ctx, player_team)
            confidence = 1.0 if ctx.has_snapshots() else 0.4

            kill_lead = my_kills - enemy_kills
            tower_lead = my_towers - enemy_towers

            phase = self._classify_phase(
                gold_lead, kill_lead, tower_lead, my_dragons
            )
            scaling = self._classify_scaling(ctx)

            state = GameState(
                timestamp_ms=ts,
                phase=phase,
                gold_lead=gold_lead,
                tower_lead=tower_lead,
                kill_lead=kill_lead,
                dragon_stacks=my_dragons,
                baron_active=my_baron_active,
                scaling_type=scaling,
                confidence=confidence,
            )
            timeline.append(state)
            ts += _SAMPLE_INTERVAL_MS

        return timeline

    def _detect_player_team(self, ctx) -> str:
        """메타데이터에서 플레이어 팀 반환"""
        if ctx.has_snapshots():
            first_snap = get_snapshot_at(0, ctx.snapshots)
            from app.analysis.utils import get_player_team
            team = get_player_team(first_snap, ctx.player_id)
            if team in ("blue", "red"):
                return team
        return ctx.metadata.get("team", "blue")

    def _get_event_team(
        self, data: dict, key: str, player_team: str, ctx
    ) -> str:
        """이벤트의 특정 키(killerId 등)가 플레이어 팀인지 적 팀인지 반환"""
        actor_id = data.get(key, -1)
        if actor_id == ctx.player_id:
            return "player"

        # 스냅샷이 있으면 팀 정보 조회
        if ctx.has_snapshots():
            ts = data.get("timestamp", 0)
            snap = get_snapshot_at(ts, ctx.snapshots)
            from app.analysis.utils import get_player_team
            team = get_player_team(snap, actor_id)
            if team == player_team:
                return "player"
            elif team in ("blue", "red"):
                return "enemy"

        # 스냅샷 없으면 participant ID 홀수/짝수로 추정 (근사)
        # 파티시팬트 1~5 = 팀 1, 6~10 = 팀 2
        if ctx.metadata.get("participant_id"):
            my_participant = int(ctx.metadata["participant_id"])
            my_team_range = range(1, 6) if my_participant <= 5 else range(6, 11)
            if actor_id in my_team_range:
                return "player"
            return "enemy"

        return "unknown"

    def _calc_gold_lead(self, ts: int, ctx, player_team: str) -> int:
        """골드 리드 계산. 스냅샷 없으면 0."""
        if not ctx.has_snapshots():
            return 0

        snap = get_snapshot_at(ts, ctx.snapshots)
        players = snap.get("players", [])
        if not players:
            return 0

        my_gold = sum(
            p.get("gold", 0) for p in players if p.get("team") == player_team
        )
        enemy_gold = sum(
            p.get("gold", 0) for p in players if p.get("team") != player_team
        )
        return my_gold - enemy_gold

    def _classify_phase(
        self, gold_lead: int, kill_lead: int, tower_lead: int, dragon_stacks: int
    ) -> str:
        """골드/킬/타워/드래곤 종합 국면 분류"""
        score = gold_lead / 500 + kill_lead * 100 + tower_lead * 200

        if score >= _GOLD_LEAD_SNOWBALL / 500:
            return "SNOWBALL"
        elif score >= _GOLD_LEAD_AHEAD / 500:
            return "AHEAD"
        elif score <= _GOLD_COMEBACK / 500:
            return "COMEBACK"
        elif score <= _GOLD_LEAD_BEHIND / 500:
            return "BEHIND"
        return "EVEN"

    def _classify_scaling(self, ctx) -> str:
        """
        조합 아키타입 기반 스케일링 분류.
        composition 결과가 없으면 메타데이터 기반 근사.
        """
        if ctx.composition:
            archetype = getattr(ctx.composition, "my_archetype", "")
            if archetype in ("SCALING", "PEEL"):
                return "PLAYER_SCALING"
            elif archetype in ("POKE", "ENGAGE", "DIVE"):
                return "ENEMY_SCALING"

        # champion_id로 단순 분류 (더미 데이터)
        late_game_champs = {
            67, 96, 22, 29, 51, 42,  # ADC 스케일러 일부
            136, 101, 161,            # 미드 스케일러 일부
        }
        if ctx.champion_id in late_game_champs:
            return "PLAYER_SCALING"
        return "EVEN"

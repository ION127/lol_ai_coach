# Coaching Module — SPEC

> `backend/app/coaching/`  
> Layer 데이터 → LLM 프롬프트 빌드 → 코칭 스크립트 생성 → 응답 검증

---

## 파일 목록

```
coaching/
├── script_generator.py   # 코칭 스크립트 자동 생성 (분석 완료 후 1회)
├── prompt_builder.py     # 레이어 → 시스템/유저 프롬프트 조립
├── llm_client.py         # Claude/GPT API 호출 래퍼
├── validator.py          # LLMAnswerValidator — 응답 사실 검증
└── chat_handler.py       # 대화형 코칭 세션 관리 (질문/답변)
```

---

## script_generator.py

```python
class CoachingScriptGenerator:
    """
    분석 완료 후 자동 생성되는 코칭 리포트.
    재생 오버레이에서 타임코드 동기화로 재생됨.

    출력 구조:
    {
        "summary": str,          # 경기 전체 2~3줄 요약
        "top_mistakes": [...],   # 핵심 실수 3개 (타임코드 + 설명)
        "focus_tasks": [...],    # 다음 3게임 집중 과제 (PlayerModel 기반)
        "highlights": [...],     # 잘한 장면 (긍정 강화)
        "script_items": [
            {
                "timestamp_sec": int,
                "type": "mistake" | "good" | "tip",
                "title": str,
                "body": str,
                "layer_ref": "L2" | "L3",  # 근거 데이터 출처
            }
        ]
    }
    """

    async def generate(self, ctx: GameContext, layers: dict, player_model: PlayerModel) -> dict:
        prompt = prompt_builder.build_script_prompt(layers, player_model)
        raw = await llm_client.complete(prompt)
        validated = await validator.validate(raw, layers["layer2"])
        return validated
```

---

## prompt_builder.py

```python
class PromptBuilder:
    """
    레이어 데이터 → LLM 시스템/유저 프롬프트 조립.
    토큰 예산 8,000 이하 강제.
    """

    SYSTEM_PROMPT = """
    당신은 LoL 전문 코치입니다. 플레이어의 경기 데이터를 바탕으로
    구체적이고 실행 가능한 피드백을 제공하세요.

    규칙:
    1. 수치를 인용할 때는 항상 정확한 값 사용 (근사값 사용 금지)
    2. 시간 언급 시 MM:SS 포맷 사용
    3. 비판적 피드백은 구체적 대안 제시와 함께
    4. 잘한 점도 반드시 언급 (동기 유지)
    5. 한국어로 응답
    """

    def build_script_prompt(self, layers: dict, player_model: PlayerModel) -> dict:
        """분석 완료 후 코칭 스크립트 생성용 프롬프트"""
        context = self._build_context(layers)
        user_msg = f"""
        다음 경기 데이터를 분석하고 코칭 스크립트를 생성하세요.

        [경기 요약]
        {json.dumps(layers["layer1"], ensure_ascii=False, indent=2)}

        [주요 이벤트]
        {json.dumps(layers["layer2"][:20], ensure_ascii=False, indent=2)}

        [분석 인사이트]
        {json.dumps(layers["layer3"], ensure_ascii=False, indent=2)}

        [플레이어 약점 패턴]
        {self._format_player_model(player_model)}
        """
        return {"system": self.SYSTEM_PROMPT, "user": user_msg}

    def build_chat_prompt(self, question: str, layers: dict, history: list[dict]) -> dict:
        """대화형 코칭 질문 응답용 프롬프트"""
        # 질문 분류: L4 첨부 필요 여부 판단
        needs_l4 = self._needs_detail(question)
        context = layers["layer1"] | layers["layer3"]
        if needs_l4 and layers.get("layer4"):
            context["detail"] = layers["layer4"]

        return {
            "system": self.SYSTEM_PROMPT,
            "history": history[-10:],  # 최근 10턴
            "user": f"[경기 데이터]\n{json.dumps(context, ensure_ascii=False)}\n\n[질문]\n{question}"
        }

    def _needs_detail(self, question: str) -> bool:
        """질문에 특정 시점/수치가 포함되면 L4 필요"""
        import re
        return bool(re.search(r"\d+분|\d+:\d+|정확히|몇 HP|몇 골드", question))
```

---

## llm_client.py

```python
import anthropic

class LLMClient:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.LLM_API_KEY)
        self.model = settings.LLM_MODEL   # "claude-sonnet-4-6"

    async def complete(self, prompt: dict, max_tokens: int = 2000) -> str:
        """단발성 완성 (코칭 스크립트 생성용)"""
        msg = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=prompt["system"],
                messages=[{"role": "user", "content": prompt["user"]}],
            )
        )
        return msg.content[0].text

    async def stream(self, prompt: dict, history: list[dict]):
        """스트리밍 응답 (대화형 코칭용) — AsyncGenerator[str]"""
        messages = [
            *[{"role": h["role"], "content": h["content"]} for h in history],
            {"role": "user", "content": prompt["user"]},
        ]
        with self.client.messages.stream(
            model=self.model,
            max_tokens=1500,
            system=prompt["system"],
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text
```

---

## validator.py — LLMAnswerValidator

```python
class LLMAnswerValidator:
    """
    LLM 응답에서 수치 주장을 추출해 Layer2 이벤트와 대조.
    잘못된 수치 포함 시 재생성 요청 (최대 2회 재시도).
    """

    async def validate(self, response: str, layer2: list[dict], max_retries: int = 2) -> str:
        validation = ValidationResult(valid=True)
        for attempt in range(max_retries + 1):
            claims = self._extract_numeric_claims(response)
            errors = [c for c in claims if not self._verify_claim(c, layer2)]
            if not errors:
                return response
            if attempt < max_retries:
                response = await self._request_correction(response, errors)
        return response   # 2회 실패해도 최선의 응답 반환

    def _extract_numeric_claims(self, text: str) -> list[dict]:
        """
        정규식으로 수치 주장 추출.
        패턴: 데미지/HP/골드/쿨다운/타임스탬프
        예: "06:23에 사망", "2,400 데미지", "300 골드 앞섬"
        """
        import re
        patterns = [
            (r"(\d+:\d+)(?:에|에서|초)", "timestamp"),
            (r"(\d[\d,]+)\s*(?:데미지|damage)", "damage"),
            (r"(\d[\d,]+)\s*(?:골드|gold)", "gold"),
            (r"(\d+)%\s*(?:체력|HP|hp)", "hp_pct"),
        ]
        claims = []
        for pattern, claim_type in patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                claims.append({"type": claim_type, "value": m.group(1), "raw": m.group(0)})
        return claims

    def _event_exists(self, timestamp_sec: int, layer2: list[dict]) -> bool:
        """Layer2에서 ±15초 내 이벤트 존재 확인"""
        return any(
            abs(e["timestamp_sec"] - timestamp_sec) <= 15
            for e in layer2
        )
```

---

## chat_handler.py

```python
class ChatHandler:
    """
    대화형 코칭 세션.
    분석 결과(layers)를 컨텍스트로 유지하며 자유 질문에 답변.
    """

    async def chat(
        self,
        question: str,
        analysis_id: str,
        history: list[dict],
        layers: dict,
    ) -> AsyncGenerator[str, None]:
        """
        스트리밍 응답.
        API 라우터의 SSE/WebSocket 엔드포인트에서 호출.
        """
        prompt = prompt_builder.build_chat_prompt(question, layers, history)
        full_response = ""
        async for chunk in llm_client.stream(prompt, history):
            full_response += chunk
            yield chunk

        # 검증은 스트리밍 완료 후 백그라운드로 (UX 저하 방지)
        asyncio.create_task(
            validator.validate_async(full_response, layers["layer2"])
        )
```

---

## 토큰 예산 / 프롬프트 길이 관리

```
시스템 프롬프트:    ~300 토큰
Layer1 (수치):     ~800 토큰
Layer2 (이벤트):  ~1,500 토큰
Layer3 (인사이트): ~2,500 토큰
LP (플레이어모델):   ~500 토큰
대화 히스토리:     ~1,000 토큰 (최근 10턴)
───────────────────────────────
합계:             ~6,600 토큰  (8,000 상한 이하)
```

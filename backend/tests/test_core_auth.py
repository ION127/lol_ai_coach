"""
app.core.auth 단위 테스트.

DB/HTTP 없이 순수 함수만 테스트 (hash, verify, JWT encode/decode).
"""
from __future__ import annotations

import time

import pytest
from jose import ExpiredSignatureError, jwt

from app.core.auth import (
    ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.core.config import settings


# ── 비밀번호 해싱 ────────────────────────────────────────────────
class TestPasswordHashing:
    def test_hash_returns_bcrypt_string(self):
        hashed = hash_password("MyPassword1!")
        assert hashed.startswith("$2b$")

    def test_same_plain_different_hashes(self):
        """bcrypt 솔팅: 같은 평문이라도 매번 다른 해시"""
        h1 = hash_password("password")
        h2 = hash_password("password")
        assert h1 != h2

    def test_verify_correct_password(self):
        plain = "correct-horse-battery-staple"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("rightpassword")
        assert verify_password("wrongpassword", hashed) is False

    def test_verify_empty_string(self):
        hashed = hash_password("nonempty")
        assert verify_password("", hashed) is False


# ── JWT ───────────────────────────────────────────────────────────
class TestJWT:
    def test_create_access_token_returns_string(self):
        token = create_access_token("user-123")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decode_access_token_contains_sub(self):
        user_id = "user-abc-def"
        token = create_access_token(user_id)
        payload = decode_access_token(token)
        assert payload["sub"] == user_id

    def test_decode_access_token_contains_exp(self):
        token = create_access_token("user-1")
        payload = decode_access_token(token)
        assert "exp" in payload
        # exp는 현재 시각보다 미래여야 함
        assert payload["exp"] > time.time()

    def test_decode_access_token_contains_iat(self):
        token = create_access_token("user-1")
        payload = decode_access_token(token)
        assert "iat" in payload

    def test_tampered_token_raises(self):
        from jose import JWTError

        token = create_access_token("user-1")
        # 서명 부분 조작
        tampered = token[:-4] + "xxxx"
        with pytest.raises(JWTError):
            decode_access_token(tampered)

    def test_wrong_secret_raises(self):
        from jose import JWTError

        # 다른 시크릿으로 서명된 토큰
        payload = {"sub": "user-1"}
        bad_token = jwt.encode(payload, "wrong-secret", algorithm=ALGORITHM)
        with pytest.raises(JWTError):
            decode_access_token(bad_token)

    def test_different_users_get_different_tokens(self):
        t1 = create_access_token("user-1")
        t2 = create_access_token("user-2")
        assert t1 != t2

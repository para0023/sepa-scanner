"""
SEPA Scanner — JWT 인증 모듈
Supabase Auth 토큰 검증 + 사용자 역할 확인
"""
import os
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Header

SUPABASE_JWT_SECRET = os.environ.get(
    "SUPABASE_JWT_SECRET",
    "FJHVZwB4aEne5TatdKXDmUKwIBk5HWP2Mmkkm/7dvhE6LDvh1S3Dns27osMS3eXu/c6m+KZgdENhSyXoF2WOSg==",
)
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL",
    "https://gccpnklkmzngkuwmmqus.supabase.co",
)
SUPABASE_ANON_KEY = os.environ.get(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdjY3Bua2xrbXpuZ2t1d21tcXVzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU2MzkyNjEsImV4cCI6MjA5MTIxNTI2MX0.tXVk7Xi4NZ1o9IndU9tHpmRUpdSPFw7VUQoCYR1F7l0",
)

# 역할 캐시 (user_id → role) — 매번 DB 조회 방지
_role_cache: dict = {}


@dataclass
class CurrentUser:
    id: str
    email: str
    role: str  # 'master' or 'user'


def _decode_token(token: str) -> dict:
    """Supabase JWT 토큰 디코딩"""
    from jose import jwt, JWTError
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def _get_role(user_id: str) -> str:
    """profiles 테이블에서 role 조회 (캐시 사용)"""
    if user_id in _role_cache:
        return _role_cache[user_id]
    try:
        import httpx
        res = httpx.get(
            f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}&select=role",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
            },
            timeout=5,
        )
        data = res.json()
        role = data[0]["role"] if data else "user"
    except Exception:
        role = "user"
    _role_cache[user_id] = role
    return role


async def get_current_user(authorization: Optional[str] = Header(None)) -> CurrentUser:
    """인증된 사용자 추출 — 모든 보호 엔드포인트에서 사용"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = authorization.replace("Bearer ", "")
    payload = _decode_token(token)
    user_id = payload.get("sub", "")
    email = payload.get("email", "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    role = _get_role(user_id)
    return CurrentUser(id=user_id, email=email, role=role)


async def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[CurrentUser]:
    """인증 선택적 — 공용 엔드포인트에서 사용 (로그인 안 해도 접근 가능)"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return await get_current_user(authorization)
    except HTTPException:
        return None


def require_master(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """마스터 전용 엔드포인트"""
    if user.role != "master":
        raise HTTPException(status_code=403, detail="Master access required")
    return user

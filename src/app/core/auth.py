import time
import base64
import logging
from typing import Any, Dict, Optional

import httpx
from jose import jwt, JWTError
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from .config import Settings

logger = logging.getLogger(__name__)

_jwks_cache: Dict[str, Any] = {"keys": None, "expires_at": 0}

class User(BaseModel):
    sub: str
    email: Optional[str] = None
    role: Optional[str] = None
    aal: Optional[Any] = None


def _b64url_to_int(val: str) -> int:
    pad = "=" * (-len(val) % 4)
    data = base64.urlsafe_b64decode(val + pad)
    return int.from_bytes(data, "big")


def _jwk_to_pem(jwk: Dict[str, Any]) -> bytes:
    # Convert RSA JWK (n, e) to PEM public key
    n = _b64url_to_int(jwk["n"])
    e = _b64url_to_int(jwk["e"])
    public_numbers = rsa.RSAPublicNumbers(e, n)
    public_key = public_numbers.public_key()
    pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pem


async def _fetch_jwks(settings: Settings) -> Dict[str, Any]:
    now = int(time.time())
    if _jwks_cache["keys"] and _jwks_cache["expires_at"] > now:
        return _jwks_cache["keys"]

    url = settings.supabase_jwks_url
    logger.info("Fetching JWKS from %s", url)
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()

    _jwks_cache["keys"] = data
    _jwks_cache["expires_at"] = now + int(settings.jwks_cache_ttl)
    return data


async def _get_jwk_by_kid(kid: str, settings: Settings) -> Optional[Dict[str, Any]]:
    jwks = await _fetch_jwks(settings)
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


async def verify_jwt(token: str, settings: Settings) -> Dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        logger.debug("Invalid JWT header: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token")

    kid = header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="Token missing kid header")

    jwk = await _get_jwk_by_kid(kid, settings)
    if not jwk:
        raise HTTPException(status_code=401, detail="Unknown kid")

    pem = _jwk_to_pem(jwk)

    try:
        payload = jwt.decode(
            token,
            pem,
            algorithms=["RS256"],
            audience=settings.supabase_aud,
            issuer=settings.supabase_iss,
        )
        return payload
    except JWTError as exc:
        logger.debug("JWT verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Token verification failed")


async def get_current_user(
    authorization: Optional[str] = Header(None), settings: Settings = Depends(Settings)
) -> User:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    token = parts[1]
    payload = await verify_jwt(token, settings)

    user = User(
        sub=payload.get("sub"),
        email=payload.get("email"),
        role=payload.get("role"),
        aal=payload.get("aal"),
    )
    return user

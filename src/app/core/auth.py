import logging
from typing import Any, Dict, Optional

import jwt
from jwt import PyJWKClient, PyJWKClientConnectionError, PyJWKClientError
from fastapi import Header, HTTPException
from pydantic import BaseModel

from .config import settings

logger = logging.getLogger(__name__)

_ALLOWED_ALGORITHMS = ["RS256", "ES256", "ES384", "ES512"]

_jwk_client: Optional[PyJWKClient] = None
_jwk_client_url: Optional[str] = None


def _get_jwk_client() -> PyJWKClient:
    """Lazy-init a PyJWKClient with built-in JWKS caching."""
    global _jwk_client, _jwk_client_url
    if _jwk_client is None or _jwk_client_url != settings.supabase_jwks_url:
        _jwk_client = PyJWKClient(
            settings.supabase_jwks_url,
            cache_jwk_set=True,
            lifespan=settings.jwks_cache_ttl,
        )
        _jwk_client_url = settings.supabase_jwks_url
    return _jwk_client


class User(BaseModel):
    sub: str
    email: Optional[str] = None
    role: Optional[str] = None
    aal: Optional[Any] = None


async def verify_jwt(token: str) -> Dict[str, Any]:
    client = _get_jwk_client()

    # --- 1. Read header (no verification yet) ---
    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        logger.debug("Invalid JWT header: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token")

    alg = header.get("alg")
    kid = header.get("kid")

    if settings.app_env == "development":
        logger.debug("[auth:diag] JWT header -> alg=%s, kid=%s", alg, kid)

    if alg not in _ALLOWED_ALGORITHMS:
        logger.warning("[auth] Rejected token with alg=%s (allowed: %s)", alg, _ALLOWED_ALGORITHMS)
        raise HTTPException(status_code=401, detail="Invalid token")

    # --- 2. Resolve signing key from JWKS by kid ---
    try:
        signing_key = client.get_signing_key_from_jwt(token)
    except PyJWKClientConnectionError as exc:
        logger.error("[auth] JWKS fetch error: %s", exc)
        raise HTTPException(status_code=503, detail="JWKS unavailable")
    except (PyJWKClientError, jwt.DecodeError) as exc:
        logger.warning("[auth] Failed to resolve signing key: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token")

    if settings.app_env == "development":
        logger.debug(
            "[auth:diag] Resolved signing key type=%s for kid=%s",
            type(signing_key.key).__name__, kid,
        )

    # --- 3. Decode & verify ---
    try:
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALLOWED_ALGORITHMS,
            audience=settings.supabase_aud,
            issuer=settings.supabase_iss,
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("JWT expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError as exc:
        logger.debug("JWT verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(
    authorization: Optional[str] = Header(None),
) -> User:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    token = parts[1]

    try:
        payload = await verify_jwt(token)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[auth] Unexpected error during token verification: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = User(
        sub=sub,
        email=payload.get("email"),
        role=payload.get("role"),
        aal=payload.get("aal"),
    )
    return user

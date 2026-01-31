import time
import base64
import asyncio
import pytest
from jose import jwt

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from src.app.core.auth import _b64url_to_int, _jwk_to_pem, verify_jwt, _jwks_cache
from src.app.core.config import Settings


def _b64url_no_padding(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_rsa_jwk_and_pem():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_numbers = private_key.public_key().public_numbers()
    n = pub_numbers.n
    e = pub_numbers.e
    n_b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    e_b = e.to_bytes((e.bit_length() + 7) // 8, "big")
    jwk = {
        "kty": "RSA",
        "kid": "test-kid",
        "use": "sig",
        "alg": "RS256",
        "n": _b64url_no_padding(n_b),
        "e": _b64url_no_padding(e_b),
    }
    return jwk, priv_pem


@pytest.mark.asyncio
async def test_jwk_to_pem_and_verify():
    jwk, priv_pem = make_rsa_jwk_and_pem()

    # Build token
    now = int(time.time())
    payload = {
        "sub": "user-1",
        "email": "dev@example.com",
        "role": "authenticated",
        "aal": "1",
        "iss": "https://omjayofpzxfmnqsfnioe.supabase.co/auth/v1",
        "aud": "authenticated",
        "exp": now + 60,
    }
    token = jwt.encode(payload, priv_pem, algorithm="RS256", headers={"kid": "test-kid"})

    # Monkeypatch JWKS cache directly
    _jwks_cache["keys"] = {"keys": [jwk]}
    _jwks_cache["expires_at"] = int(time.time()) + 60

    settings = Settings(
        supabase_iss="https://omjayofpzxfmnqsfnioe.supabase.co/auth/v1",
        supabase_aud="authenticated",
        supabase_jwks_url="https://omjayofpzxfmnqsfnioe.supabase.co/auth/v1/.well-known/jwks.json",
        jwks_cache_ttl=3600,
    )

    payload_verified = await verify_jwt(token, settings)
    assert payload_verified["sub"] == "user-1"
    assert payload_verified["email"] == "dev@example.com"


@pytest.mark.asyncio
async def test_expired_token_fails():
    jwk, priv_pem = make_rsa_jwk_and_pem()

    now = int(time.time())
    payload = {
        "sub": "user-1",
        "iss": "https://omjayofpzxfmnqsfnioe.supabase.co/auth/v1",
        "aud": "authenticated",
        "exp": now - 10,
    }
    token = jwt.encode(payload, priv_pem, algorithm="RS256", headers={"kid": "test-kid"})

    _jwks_cache["keys"] = {"keys": [jwk]}
    _jwks_cache["expires_at"] = int(time.time()) + 60

    settings = Settings(
        supabase_iss="https://omjayofpzxfmnqsfnioe.supabase.co/auth/v1",
        supabase_aud="authenticated",
        supabase_jwks_url="https://omjayofpzxfmnqsfnioe.supabase.co/auth/v1/.well-known/jwks.json",
        jwks_cache_ttl=3600,
    )

    with pytest.raises(Exception):
        await verify_jwt(token, settings)

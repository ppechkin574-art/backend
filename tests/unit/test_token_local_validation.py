"""Unit tests for local JWT validation in IdentityProviderClientKeycloak.

`get_user_sub_from_token` used to call Keycloak's `/userinfo` endpoint on
every request (a network round-trip per authenticated call). It now verifies
the access token locally against the realm public key (cached process-wide).

These tests use a generated RSA keypair and a fake KeycloakOpenID whose
`public_key()` returns the base64 DER body (exactly the shape Keycloak's
`public_key()` returns), so no network is involved.
"""

import base64
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import jwt

from clients.identity_provider.client import IdentityProviderClientKeycloak
from clients.identity_provider.exceptions import InvalidAccessTokenError


def _gen_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    # Keycloak's public_key() returns base64 of the DER SubjectPublicKeyInfo,
    # WITHOUT the PEM header/footer — reproduce that exactly.
    der = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_b64 = base64.b64encode(der).decode()
    return private_pem, public_b64


class _FakeOpenID:
    """Stands in for KeycloakOpenID — only public_key() is used here."""

    def __init__(self, public_b64: str):
        self._public_b64 = public_b64
        self.public_key_calls = 0

        self.userinfo_calls = 0
        self.userinfo_return = None

    def public_key(self) -> str:
        self.public_key_calls += 1
        return self._public_b64

    def userinfo(self, token):
        self.userinfo_calls += 1
        return self.userinfo_return or {}


def _make_client(public_b64: str) -> tuple[IdentityProviderClientKeycloak, _FakeOpenID]:
    # Bypass __init__ (it would construct real Keycloak clients / hit network).
    client = object.__new__(IdentityProviderClientKeycloak)
    fake_openid = _FakeOpenID(public_b64)
    client._keycloak_openid = fake_openid
    return client, fake_openid


@pytest.fixture(autouse=True)
def _reset_class_cache():
    # The public key is cached at the class level — reset around each test so
    # tests don't leak a cached key into one another.
    IdentityProviderClientKeycloak._cached_public_key_pem = None
    yield
    IdentityProviderClientKeycloak._cached_public_key_pem = None


def _token(private_pem: str, *, sub="5615ee6c-f8e5-4d65-bc79-3ecf5129a876", exp_offset=300):
    now = int(time.time())
    payload = {"sub": sub, "iat": now, "exp": now + exp_offset, "aud": "account"}
    return jwt.encode(payload, private_pem, algorithm="RS256")


def test_valid_token_returns_sub():
    private_pem, public_b64 = _gen_keypair()
    client, _ = _make_client(public_b64)
    token = _token(private_pem)

    sub = client.get_user_sub_from_token(token)

    assert str(sub) == "5615ee6c-f8e5-4d65-bc79-3ecf5129a876"


def test_expired_token_raises_invalid():
    private_pem, public_b64 = _gen_keypair()
    client, _ = _make_client(public_b64)
    token = _token(private_pem, exp_offset=-10)  # already expired

    with pytest.raises(InvalidAccessTokenError):
        client.get_user_sub_from_token(token)


def test_token_signed_by_wrong_key_raises_invalid():
    # Token signed by a DIFFERENT key than the realm advertises.
    attacker_private, _ = _gen_keypair()
    _, realm_public_b64 = _gen_keypair()
    client, fake_openid = _make_client(realm_public_b64)
    token = _token(attacker_private)

    with pytest.raises(InvalidAccessTokenError):
        client.get_user_sub_from_token(token)
    # The refresh-once retry path should have refetched the key (still wrong),
    # i.e. public_key() called more than once.
    assert fake_openid.public_key_calls >= 2


def test_lightweight_token_without_sub_falls_back_to_userinfo():
    # Keycloak 26 "lightweight access tokens" (admin panel client) are valid
    # RS256 JWTs but omit `sub` — it must be fetched from /userinfo.
    private_pem, public_b64 = _gen_keypair()
    client, fake_openid = _make_client(public_b64)
    fake_openid.userinfo_return = {"sub": str(SUB := "11111111-2222-3333-4444-555555555555")}
    now = int(time.time())
    token = jwt.encode(
        {"iat": now, "exp": now + 300, "aud": "account"},  # no sub in token
        private_pem,
        algorithm="RS256",
    )

    sub = client.get_user_sub_from_token(token)

    assert str(sub) == SUB
    assert fake_openid.userinfo_calls == 1  # fallback was used


def test_token_without_sub_and_userinfo_empty_raises_invalid():
    private_pem, public_b64 = _gen_keypair()
    client, fake_openid = _make_client(public_b64)
    fake_openid.userinfo_return = {}  # userinfo also has no sub
    now = int(time.time())
    token = jwt.encode(
        {"iat": now, "exp": now + 300, "aud": "account"},
        private_pem,
        algorithm="RS256",
    )

    with pytest.raises(InvalidAccessTokenError):
        client.get_user_sub_from_token(token)


def test_public_key_cached_across_calls():
    private_pem, public_b64 = _gen_keypair()
    client, fake_openid = _make_client(public_b64)
    token = _token(private_pem)

    client.get_user_sub_from_token(token)
    client.get_user_sub_from_token(token)

    # Key fetched from Keycloak only once, then served from the class cache.
    assert fake_openid.public_key_calls == 1

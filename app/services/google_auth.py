"""Verify Google Sign-In ID tokens (OpenID Connect) without the Google SDK.

The app obtains an ID token from Google and sends it here; we check its
signature against Google's published keys, its issuer, audience (one of our
OAuth client IDs), expiry and that the email is verified.
"""
from typing import Optional

import jwt
from jwt import PyJWKClient

from app.core.config import settings

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

_jwk_client: Optional[PyJWKClient] = None


class GoogleTokenError(Exception):
    pass


def client_ids() -> list[str]:
    return [c.strip() for c in settings.GOOGLE_OAUTH_CLIENT_IDS.split(",") if c.strip()]


def is_configured() -> bool:
    return bool(client_ids())


def _signing_key(token: str):
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(GOOGLE_CERTS_URL, cache_keys=True, lifespan=3600)
    return _jwk_client.get_signing_key_from_jwt(token).key


def verify_id_token(token: str) -> dict:
    """Return the verified claims (sub, email, name, ...) or raise GoogleTokenError."""
    try:
        key = _signing_key(token)
    except jwt.PyJWKClientError as e:
        raise GoogleTokenError(f"Could not fetch Google signing keys or match the token's key ({e.__class__.__name__}).")
    except jwt.PyJWTError:
        # Not even a well-formed JWT (bad segments, missing header "kid", ...).
        raise GoogleTokenError("Invalid Google sign-in token.")
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=client_ids(),
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=30,
        )
    except jwt.ExpiredSignatureError:
        raise GoogleTokenError("Google sign-in expired. Please try again.")
    except jwt.InvalidAudienceError:
        raise GoogleTokenError("This Google sign-in was issued for a different app.")
    except jwt.PyJWTError:
        raise GoogleTokenError("Invalid Google sign-in token.")
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleTokenError("Invalid Google sign-in token issuer.")
    if not claims.get("email") or claims.get("email_verified") not in (True, "true"):
        raise GoogleTokenError("Your Google account email is not verified.")
    return claims

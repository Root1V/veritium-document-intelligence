"""Connected systems (VRT-65): the per-client quota and the guard against
running production with the development JWT key."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from idp.auth.rate_limit import RateLimiter
from idp.config import Settings


def test_quota_per_client_and_per_minute():
    limiter = RateLimiter()
    assert [limiter.check("a", 2, now=0.0), limiter.check("a", 2, now=1.0)] == [None, None]
    assert limiter.check("a", 2, now=20.0) == 40, "seconds until the window resets"
    assert limiter.check("b", 2, now=20.0) is None, "another client has its own quota"
    assert limiter.check("a", 2, now=60.0) is None, "a new minute"


def test_production_refuses_the_development_jwt_key_and_an_unsigned_agent_card():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(environment="prod", jwt_secret_key="dev-insecure-change-me")
    with pytest.raises(ValidationError, match="A2A_SIGNING_KEY"):
        Settings(environment="prod", jwt_secret_key="una-clave-propia")
    assert Settings(environment="prod", jwt_secret_key="una-clave-propia", a2a_signing_key="pem").environment == "prod"

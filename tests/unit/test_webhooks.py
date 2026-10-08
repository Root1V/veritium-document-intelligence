"""Unit tests for VRT-28: Standard Webhooks signing (against the spec's test
vector), the retry schedule, the CloudEvents envelope and secret encryption.
No DB, no network."""

from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from idp.config import Settings
from idp.persistence.models import OutboxEvent
from idp.webhooks.cipher import MissingEncryptionKey, decrypt, encrypt
from idp.webhooks.dispatcher import RETRY_DELAYS, next_delay
from idp.webhooks.events import body_bytes, cloudevent
from idp.webhooks.signing import generate_secret, sign, verify

SPEC_SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
SPEC_ID = "msg_p5jXN8AQM9LWM0D4loKWxJek"
SPEC_TS = 1614265330
SPEC_BODY = b'{"test": 2432232314}'
SPEC_SIGNATURE = "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="


# --- signing ---------------------------------------------------------------


def test_signature_matches_the_standard_webhooks_test_vector():
    assert sign(SPEC_SECRET, SPEC_ID, SPEC_TS, SPEC_BODY) == SPEC_SIGNATURE


def test_verify_accepts_the_vector_and_rejects_tampering():
    assert verify(SPEC_SECRET, SPEC_ID, str(SPEC_TS), SPEC_SIGNATURE, SPEC_BODY, now=SPEC_TS)
    assert not verify(SPEC_SECRET, SPEC_ID, str(SPEC_TS), SPEC_SIGNATURE, b'{"test": 1}', now=SPEC_TS)
    assert not verify(generate_secret(), SPEC_ID, str(SPEC_TS), SPEC_SIGNATURE, SPEC_BODY, now=SPEC_TS)
    assert not verify(SPEC_SECRET, "otro-id", str(SPEC_TS), SPEC_SIGNATURE, SPEC_BODY, now=SPEC_TS)


def test_verify_rejects_a_stale_timestamp():
    assert not verify(SPEC_SECRET, SPEC_ID, str(SPEC_TS), SPEC_SIGNATURE, SPEC_BODY, now=SPEC_TS + 10 * 60)


def test_any_of_several_signatures_is_enough_for_key_rotation():
    rotated = f"v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= {SPEC_SIGNATURE}"
    assert verify(SPEC_SECRET, SPEC_ID, str(SPEC_TS), rotated, SPEC_BODY, now=SPEC_TS)


def test_generated_secrets_have_the_whsec_prefix_and_differ():
    a, b = generate_secret(), generate_secret()
    assert a.startswith("whsec_") and a != b


# --- retries ---------------------------------------------------------------


def test_retry_schedule_spans_about_three_days_with_bounded_jitter():
    total = sum(d.total_seconds() for d in RETRY_DELAYS)
    assert 2.5 * 86400 < total < 3.5 * 86400
    rng = random.Random(7)
    for attempts, base in enumerate(RETRY_DELAYS, start=1):
        delay = next_delay(attempts, rng=rng)
        assert delay is not None
        assert 0.8 * base.total_seconds() <= delay.total_seconds() <= 1.2 * base.total_seconds()


def test_no_retry_after_the_schedule_is_exhausted():
    assert next_delay(len(RETRY_DELAYS) + 1) is None


# --- envelope --------------------------------------------------------------


def _event() -> OutboxEvent:
    return OutboxEvent(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        tenant="default",
        type="pe.veritium.case.verdict.changed",
        subject="case-1",
        data={"case_id": "case-1", "verdict": "continue"},
        created_at=datetime(2026, 10, 7, 12, 0, tzinfo=UTC),
    )


def test_cloudevent_envelope():
    ce = cloudevent(_event())
    assert ce["specversion"] == "1.0" and ce["source"] == "veritium"
    assert ce["id"] == "11111111-1111-1111-1111-111111111111"
    assert ce["time"] == "2026-10-07T12:00:00Z"
    assert ce["data"] == {"case_id": "case-1", "verdict": "continue"}


def test_body_is_deterministic_so_every_attempt_signs_the_same_bytes():
    assert body_bytes(_event()) == body_bytes(_event())
    assert json.loads(body_bytes(_event()))["type"] == "pe.veritium.case.verdict.changed"


# --- secrets at rest -------------------------------------------------------


def test_secret_encryption_roundtrip_and_missing_key():
    settings = Settings(_env_file=None, secrets_encryption_key=SecretStr(Fernet.generate_key().decode()))
    ciphertext = encrypt(settings, "whsec_abc")
    assert ciphertext != "whsec_abc" and decrypt(settings, ciphertext) == "whsec_abc"
    with pytest.raises(MissingEncryptionKey):
        encrypt(Settings(_env_file=None, secrets_encryption_key=None), "x")


def test_retry_delays_are_increasing():
    assert all(a < b for a, b in zip(RETRY_DELAYS, RETRY_DELAYS[1:]))
    assert RETRY_DELAYS[0] == timedelta(seconds=5)

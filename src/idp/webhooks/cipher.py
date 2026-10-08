"""Encryption at rest for webhook signing secrets (Fernet, key from
``SECRETS_ENCRYPTION_KEY``). The plaintext secret is shown to the consumer
once, when the endpoint is created; afterwards only the dispatcher reads it."""

from __future__ import annotations

from cryptography.fernet import Fernet

from idp.config import Settings


class MissingEncryptionKey(RuntimeError):
    pass


def _fernet(settings: Settings) -> Fernet:
    if settings.secrets_encryption_key is None:
        raise MissingEncryptionKey(
            "SECRETS_ENCRYPTION_KEY no está configurada; generar con: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(settings.secrets_encryption_key.get_secret_value().encode())


def encrypt(settings: Settings, plaintext: str) -> str:
    return _fernet(settings).encrypt(plaintext.encode()).decode()


def decrypt(settings: Settings, ciphertext: str) -> str:
    return _fernet(settings).decrypt(ciphertext.encode()).decode()

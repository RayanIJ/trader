"""Encrypted local secret storage.

Secrets (e.g. IB account id, optional API keys) are encrypted at rest with a
Fernet key. The key itself comes from the ``TRADER_SECRET_KEY`` environment
variable; if absent, a key file is generated under the data directory with
owner-only permissions. Nothing is ever sent off-box. Credentials are never
hardcoded.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.logging import get_logger

logger = get_logger("secrets")

_ENV_KEY = "TRADER_SECRET_KEY"


class SecretStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._key_path = self._data_dir / "secret.key"
        self._store_path = self._data_dir / "secrets.enc"
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        env_key = os.environ.get(_ENV_KEY)
        if env_key:
            return env_key.encode() if not env_key.endswith("=") else env_key.encode()
        if self._key_path.exists():
            return self._key_path.read_bytes()
        key = Fernet.generate_key()
        self._key_path.write_bytes(key)
        try:
            os.chmod(self._key_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            logger.warning("could not restrict permissions on key file")
        logger.info("generated new local secret key at %s", self._key_path)
        return key

    def _read_all(self) -> dict[str, Any]:
        if not self._store_path.exists():
            return {}
        try:
            decrypted = self._fernet.decrypt(self._store_path.read_bytes())
            return json.loads(decrypted)
        except (InvalidToken, ValueError):
            logger.error("secret store could not be decrypted (wrong key?)")
            return {}

    def _write_all(self, data: dict[str, Any]) -> None:
        token = self._fernet.encrypt(json.dumps(data).encode())
        self._store_path.write_bytes(token)
        try:
            os.chmod(self._store_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def get(self, name: str, default: Any = None) -> Any:
        return self._read_all().get(name, default)

    def set(self, name: str, value: Any) -> None:
        data = self._read_all()
        data[name] = value
        self._write_all(data)

    def delete(self, name: str) -> None:
        data = self._read_all()
        data.pop(name, None)
        self._write_all(data)

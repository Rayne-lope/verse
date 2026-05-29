from __future__ import annotations

import keyring
from keyring.errors import PasswordDeleteError


SERVICE_NAME = "verse"


def set_api_key(name: str, value: str) -> None:
    keyring.set_password(SERVICE_NAME, _account(name), value)


def get_api_key(name: str) -> str | None:
    return keyring.get_password(SERVICE_NAME, _account(name))


def delete_api_key(name: str) -> bool:
    try:
        keyring.delete_password(SERVICE_NAME, _account(name))
    except PasswordDeleteError:
        return False
    return True


def _account(name: str) -> str:
    account = name.strip()
    if not account:
        raise ValueError("Keychain account name cannot be empty")
    return account

from keyring.errors import PasswordDeleteError

from verse.persistence import keychain


def test_keychain_set_get_and_delete(monkeypatch):
    store = {}

    monkeypatch.setattr(
        keychain.keyring,
        "set_password",
        lambda service, account, value: store.__setitem__((service, account), value),
    )
    monkeypatch.setattr(
        keychain.keyring,
        "get_password",
        lambda service, account: store.get((service, account)),
    )

    def delete_password(service, account):
        try:
            del store[(service, account)]
        except KeyError as exc:
            raise PasswordDeleteError("missing") from exc

    monkeypatch.setattr(keychain.keyring, "delete_password", delete_password)

    keychain.set_api_key("deepseek", "secret")

    assert keychain.get_api_key("deepseek") == "secret"
    assert keychain.delete_api_key("deepseek") is True
    assert keychain.get_api_key("deepseek") is None
    assert keychain.delete_api_key("deepseek") is False

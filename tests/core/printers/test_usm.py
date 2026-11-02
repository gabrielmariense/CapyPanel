import pytest

from capypanel.core.printers import usm

RFC_ENGINE = bytes.fromhex("000000000000000000000002")  # RFC 3414 A.3's example engine


def test_keys_match_rfc_3414s_md5_example() -> None:
    master = usm.master_key(usm.Auth.MD5, "maplesyrup")
    assert master.hex() == "9faf3283884e92834ebc9847d8edd963"
    assert usm.localized(usm.Auth.MD5, master, RFC_ENGINE).hex() == (
        "526f5eed9fcce26f8964c2930787d82b"
    )


def test_keys_match_rfc_3414s_sha_example() -> None:
    master = usm.master_key(usm.Auth.SHA, "maplesyrup")
    assert master.hex() == "9fb5cc0381497b3793528939ff788d5d79145211"
    assert usm.localized(usm.Auth.SHA, master, RFC_ENGINE).hex() == (
        "6695febc9288e36282235fc7151f128497b38f3f"
    )


def test_a_signature_is_checked_against_the_message_with_zeros_in_its_place() -> None:
    account = usm.Account("sample", usm.Auth.SHA256, "auth-pass-1")
    keys = usm.keys(account, RFC_ENGINE)
    message = b"head" + bytes(usm.Auth.SHA256.length) + b"tail"
    signed = usm.signed(keys, message, 4)
    assert signed != message and len(signed) == len(message)
    assert usm.verified(keys, signed, 4)
    assert not usm.verified(keys, signed[:-1] + b"X", 4)  # changed in transit
    other = usm.keys(usm.Account("sample", usm.Auth.SHA256, "auth-pass-2"), RFC_ENGINE)
    assert not usm.verified(other, signed, 4)


def test_aes_round_trips_and_never_reuses_a_salt() -> None:
    account = usm.Account("sample", usm.Auth.SHA, "auth-pass-1", usm.Privacy.AES128, "priv-pass-1")
    keys = usm.keys(account, RFC_ENGINE)
    assert len(keys.privacy_key) == 16
    first, salt = usm.encrypt(keys, 7, 5000, b"scoped PDU")
    second, other_salt = usm.encrypt(keys, 7, 5000, b"scoped PDU")
    assert salt != other_salt and first != second
    assert usm.decrypt(keys, 7, 5000, salt, first) == b"scoped PDU"


def test_an_account_checks_its_passwords_and_never_shows_them() -> None:
    with pytest.raises(ValueError, match="8 characters"):
        usm.Account("sample", usm.Auth.SHA, "short")
    with pytest.raises(ValueError, match="authentication too"):
        usm.Account("sample", privacy=usm.Privacy.AES128, privacy_password="priv-pass-1")
    account = usm.Account("sample", usm.Auth.SHA, "auth-pass-1", usm.Privacy.AES128, "priv-pass-1")
    assert "pass" not in repr(account) and "pass" not in repr(usm.keys(account, RFC_ENGINE))

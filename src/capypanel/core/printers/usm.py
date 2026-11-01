"""SNMP v3's user-based security model (RFC 3414, with RFC 7860's SHA-2 and RFC 3826's AES):
an account's passwords turned into keys for one printer, each message signed and each answer's
signature checked, and the request's contents encrypted. Passwords stay in memory: never in a
log, a repr or an error message."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache

from cryptography.hazmat.decrepit.ciphers.modes import CFB  # RFC 3826 names this mode
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

MIN_PASSWORD = 8  # RFC 3414: shorter passwords are refused
_STRETCH = 1_048_576  # bytes of repeated password hashed into a key (RFC 3414 A.2)


class Auth(Enum):
    """How messages are signed: the hash, and how many bytes of the signature travel."""

    MD5 = ("MD5", "md5", 12)
    SHA = ("SHA", "sha1", 12)
    SHA224 = ("SHA-224", "sha224", 16)
    SHA256 = ("SHA-256", "sha256", 24)
    SHA384 = ("SHA-384", "sha384", 32)
    SHA512 = ("SHA-512", "sha512", 48)

    def __init__(self, label: str, hash_name: str, length: int) -> None:
        self.label, self.hash_name, self.length = label, hash_name, length


class Privacy(Enum):
    AES128 = "AES-128"  # the one RFC 3826 defines, which printers offer


@dataclass(frozen=True)
class Account:
    """An SNMP v3 user. Without `auth` it's sent unsigned; `privacy` needs `auth` too."""

    user: str
    auth: Auth | None = None
    auth_password: str = field(default="", repr=False)
    privacy: Privacy | None = None
    privacy_password: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.user:
            raise ValueError("an SNMP v3 account needs a user name")
        if self.privacy and not self.auth:
            raise ValueError("encryption needs authentication too")
        if self.auth and len(self.auth_password.encode()) < MIN_PASSWORD:
            raise ValueError("the authentication password needs at least 8 characters")
        if self.privacy and len(self.privacy_password.encode()) < MIN_PASSWORD:
            raise ValueError("the encryption password needs at least 8 characters")


@dataclass(frozen=True)
class Keys:
    """An account's keys for one printer (its engine ID)."""

    auth: Auth | None = None
    auth_key: bytes = field(default=b"", repr=False)
    privacy_key: bytes = field(default=b"", repr=False)


def keys(account: Account, engine_id: bytes) -> Keys:
    if account.auth is None:
        return Keys()
    auth_key = localized(account.auth, master_key(account.auth, account.auth_password), engine_id)
    privacy_key = b""
    if account.privacy:
        # RFC 3826: the privacy password goes through the authentication hash; AES-128 uses
        # the first 16 bytes.
        master = master_key(account.auth, account.privacy_password)
        privacy_key = localized(account.auth, master, engine_id)[:16]
    return Keys(account.auth, auth_key, privacy_key)


@lru_cache(maxsize=8)
def master_key(auth: Auth, password: str) -> bytes:
    """A password stretched into a key (RFC 3414 A.2.1). It hashes a megabyte, so each
    password is worked out once, not for every printer."""
    data = password.encode()
    repeated = data * (_STRETCH // len(data) + 1)
    return hashlib.new(auth.hash_name, repeated[:_STRETCH]).digest()


def localized(auth: Auth, master: bytes, engine_id: bytes) -> bytes:
    """The key for one printer, so a key read off one can't sign for another (RFC 3414 A.2.2)."""
    return hashlib.new(auth.hash_name, master + engine_id + master).digest()


def signature(keys: Keys, message: bytes) -> bytes:
    """The signature for a whole message, worked out with its signature field still zeros."""
    assert keys.auth is not None
    digest = hmac.new(keys.auth_key, message, keys.auth.hash_name).digest()
    return digest[: keys.auth.length]


def signed(keys: Keys, message: bytes, signature_at: int) -> bytes:
    assert keys.auth is not None
    end = signature_at + keys.auth.length
    return message[:signature_at] + signature(keys, message) + message[end:]


def verified(keys: Keys, message: bytes, signature_at: int) -> bool:
    """Whether the answer was signed with this account's key: the signature is checked against
    the message with that field put back to zeros."""
    assert keys.auth is not None
    end = signature_at + keys.auth.length
    zeroed = message[:signature_at] + bytes(keys.auth.length) + message[end:]
    return hmac.compare_digest(message[signature_at:end], signature(keys, zeroed))


def encrypt(keys: Keys, boots: int, time: int, plain: bytes) -> tuple[bytes, bytes]:
    """AES-128 in CFB mode (RFC 3826): the encrypted bytes, and the salt the printer needs to
    decrypt them. The salt is random, so no two messages share an IV."""
    salt = secrets.token_bytes(8)
    return _cipher(keys, boots, time, salt, plain, encrypting=True), salt


def decrypt(keys: Keys, boots: int, time: int, salt: bytes, data: bytes) -> bytes:
    if len(salt) != 8:
        raise ValueError("bad salt")
    return _cipher(keys, boots, time, salt, data, encrypting=False)


def _cipher(
    keys: Keys, boots: int, time: int, salt: bytes, data: bytes, *, encrypting: bool
) -> bytes:
    iv = boots.to_bytes(4, "big") + time.to_bytes(4, "big") + salt
    cipher = Cipher(algorithms.AES(keys.privacy_key), CFB(iv))
    worker = cipher.encryptor() if encrypting else cipher.decryptor()
    return worker.update(data) + worker.finalize()

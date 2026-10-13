"""
TOTP (RFC 6238) multi-factor authentication helpers.

Self-contained (HMAC-SHA1, 30 s steps, 6 digits) so it works with any
authenticator app (Google Authenticator, Microsoft Authenticator, Aegis, ...).

Security properties implemented here:
  * +/- one step of clock drift accepted, no more
  * a code can be used once: callers pass the last accepted step and a step
    <= that is refused (replay protection)
  * comparison is constant-time
  * the shared secret is stored encrypted at rest (Fernet, key derived from
    SECRET_KEY); recovery codes are stored only as SHA-256 hashes
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Iterable, Optional
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10
ISSUER = "DroneArjuna"


# ── secret generation / protection ───────────────────────────────────

def generate_secret() -> str:
    """160-bit random secret, base32 (the format authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _fernet() -> Fernet:
    digest = hashlib.sha256(b"dronearjuna-totp-secret-v1|" + get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ValueError("stored TOTP secret cannot be decrypted (SECRET_KEY changed?)") from e


def provisioning_uri(secret: str, account: str, issuer: str = ISSUER) -> str:
    label = quote(f"{issuer}:{account}")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


# ── code computation / verification ──────────────────────────────────

def _hotp(secret_b32: str, counter: int) -> str:
    padded = secret_b32 + "=" * (-len(secret_b32) % 8)
    key = base64.b32decode(padded, casefold=True)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    binary = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** DIGITS)).zfill(DIGITS)


def code_at(secret_b32: str, at: Optional[float] = None) -> str:
    return _hotp(secret_b32, int((time.time() if at is None else at) // STEP_SECONDS))


def verify_totp(secret_b32: str, code: str, *, last_step: Optional[int] = None,
                now: Optional[float] = None) -> Optional[int]:
    """
    Returns the accepted time step, or None if the code is wrong / already used.
    Callers must persist the returned step and pass it back as last_step.
    """
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    current = int((time.time() if now is None else now) // STEP_SECONDS)
    matched: Optional[int] = None
    for step in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
        # evaluate every candidate so timing does not reveal which step matched
        if hmac.compare_digest(_hotp(secret_b32, step), code) and matched is None:
            matched = step
    if matched is None:
        return None
    if last_step is not None and matched <= last_step:
        return None                                  # replay
    return matched


# ── recovery codes ───────────────────────────────────────────────────

def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    return [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(count)]


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()


def consume_recovery_code(code: str, hashed_codes: Iterable[str]) -> Optional[list[str]]:
    """Returns the remaining hashes if `code` matched one (which is removed), else None."""
    target = hash_recovery_code(code)
    remaining = list(hashed_codes)
    for h in remaining:
        if hmac.compare_digest(h, target):
            remaining.remove(h)
            return remaining
    return None

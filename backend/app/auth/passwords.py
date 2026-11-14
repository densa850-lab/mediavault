"""Password hashing with argon2id (argon2-cffi) and the password policy."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 12
# Upper bound keeps hashing cost bounded (no multi-megabyte "passwords").
MAX_PASSWORD_LENGTH = 128

# argon2-cffi defaults are RFC 9106 "low memory" argon2id parameters.
_hasher = PasswordHasher()
# Verified against when the email is unknown, so both paths cost the same time.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-equalisation")


def password_policy_problem(password: str) -> str | None:
    """Return a user-facing reason the password is unacceptable, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    if not password.strip():
        return "Password must not be only whitespace."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-work verification. Pass None for an unknown user."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)

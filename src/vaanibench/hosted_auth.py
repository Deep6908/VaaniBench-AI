"""Single-owner password verification. Hashes stay in deployment secrets."""
import base64
import getpass
import hashlib
import hmac
import secrets


def password_hash(password: str) -> str:
    if len(password) < 16:
        raise ValueError("Use at least 16 characters")
    salt = secrets.token_bytes(24)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return "pbkdf2_sha256$600000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 600_000 <= int(rounds) <= 2_000_000 or len(password) > 1024:
            return False
        salt_bytes = base64.b64decode(salt, validate=True)
        expected_bytes = base64.b64decode(expected, validate=True)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_bytes, int(rounds))
        return hmac.compare_digest(actual, expected_bytes)
    except (ValueError, TypeError):
        return False


def main():
    password = getpass.getpass("Owner password (16+ characters): ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords did not match")
    print(password_hash(password))


if __name__ == "__main__":
    main()

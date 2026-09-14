from core.auth import generate_salt, hash_password, verify_password


def test_hash_verify_roundtrip():
    salt = generate_salt()
    h = hash_password("correct horse", salt)
    assert verify_password("correct horse", h, salt) is True


def test_wrong_password_rejected():
    salt = generate_salt()
    h = hash_password("correct horse", salt)
    assert verify_password("wrong password", h, salt) is False


def test_empty_stored_hash_rejected():
    # First-run state: no password set yet - must never verify as True.
    assert verify_password("anything", "", generate_salt()) is False


def test_empty_salt_rejected():
    # Defends against a pre-salt config.json (missing admin_password_salt)
    # silently accepting any password once the field defaults to "".
    h = hash_password("correct horse", "somesalt")
    assert verify_password("correct horse", h, "") is False


def test_salts_are_unique():
    salts = {generate_salt() for _ in range(50)}
    assert len(salts) == 50


def test_same_password_different_salt_gives_different_hash():
    h1 = hash_password("same password", "salt-one")
    h2 = hash_password("same password", "salt-two")
    assert h1 != h2

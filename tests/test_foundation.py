from bac.core.auth import create_user, hash_password, verify_password, new_session


def test_migrations_repeat_without_data_loss(services):
    db = services.db
    id = create_user(db, "Student@example.com", "Strong-password-1", "Student")
    db.migrate()
    assert (
        db.one("SELECT email FROM users WHERE id=?", (id,))["email"]
        == "student@example.com"
    )
    assert len(db.rows("SELECT * FROM migrations")) == 12


def test_password_not_plain_and_session_hash_only(services):
    password = "Strong-password-2"
    hashed = hash_password(password)
    assert verify_password(password, hashed) and not verify_password("wrong", hashed)
    id = create_user(services.db, "a@example.com", password, "A")
    token, csrf = new_session(services.db, id, services.settings)
    row = services.db.one("SELECT * FROM sessions")
    assert token != row["token_hash"] and len(csrf) > 20


def test_durable_rate_limit(services):
    assert services.db.rate("key", 1, 60)
    assert not services.db.rate("key", 1, 60)

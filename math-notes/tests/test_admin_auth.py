import admin_auth


def test_make_cookie_value_is_valid():
    assert admin_auth.is_valid(admin_auth.make_cookie_value())


def test_none_is_not_valid():
    assert not admin_auth.is_valid(None)


def test_empty_string_is_not_valid():
    assert not admin_auth.is_valid("")


def test_malformed_value_without_separator_is_not_valid():
    assert not admin_auth.is_valid("no-dot-here")


def test_tampered_signature_is_not_valid():
    value = admin_auth.make_cookie_value()
    expires_at, _, _sig = value.partition(".")
    assert not admin_auth.is_valid(f"{expires_at}.0000000000000000000000000000000000000000000000000000000000000000")


def test_non_numeric_expiry_is_not_valid():
    fake_sig = admin_auth._sign("not-a-number")
    assert not admin_auth.is_valid(f"not-a-number.{fake_sig}")


def test_expired_value_is_not_valid():
    expired_at = "1"  # 1970-01-01, long past
    signed = f"{expired_at}.{admin_auth._sign(expired_at)}"
    assert not admin_auth.is_valid(signed)

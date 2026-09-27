"""A lightweight, purely cosmetic "am I logged in" signal for the public site -- NOT the
actual access control for /admin/*, which stays exactly what it always was: Caddy's
basic_auth, re-checked independently on every single request to that path prefix. This
module only decides whether to show the Admin nav item and per-post Edit links on PUBLIC
pages, since basic_auth is scoped to /admin/* and the browser has no reason to send those
credentials -- and this app has no way to see them -- on any other page.

Every /admin/* GET request that reaches this app has, by construction, already passed
Caddy's basic_auth (nothing else can reach this app on that path prefix) -- so those
routes set a signed cookie on their response, site-wide (Path=/), so a later request to a
PUBLIC page in the same browser session can also see it and render the same "you're
logged in" chrome. It's HMAC-signed so a visitor can't just set their own cookie to fake
it -- but forging it would only ever change what they SEE, never what they can DO, since
every real admin action still goes through Caddy's basic_auth independently either way.
"""

import hashlib
import hmac
import os
import time

COOKIE_NAME = "mn_admin"
_SECRET = os.environ.get("ADMIN_COOKIE_SECRET", "")
MAX_AGE_SECONDS = 60 * 60 * 12  # 12 hours


def _sign(value):
    return hmac.new(_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def make_cookie_value():
    expires_at = str(int(time.time()) + MAX_AGE_SECONDS)
    return f"{expires_at}.{_sign(expires_at)}"


def is_valid(cookie_value):
    if not cookie_value or "." not in cookie_value:
        return False
    expires_at, _, signature = cookie_value.partition(".")
    if not expires_at.isdigit():
        return False
    if not hmac.compare_digest(signature, _sign(expires_at)):
        return False
    return int(expires_at) > time.time()

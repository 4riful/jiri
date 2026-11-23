from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Never let the developer's real .env (hosted-AI keys) leak into the test run.
import os  # noqa: E402

os.environ.setdefault("JIRI_ENV_FILE", str(ROOT / "tests" / ".env.does-not-exist"))
# Keep the laptop usage-push config (~/.config/jiri/usage.env) out of tests too.
os.environ["XDG_CONFIG_HOME"] = str(ROOT / "tests" / ".config-does-not-exist")

# The web admin refuses every login unless a non-default password is set.
TEST_ADMIN_PASSWORD = "jiri-test-admin-pw"
os.environ["JIRI_ADMIN_PASSWORD"] = TEST_ADMIN_PASSWORD
os.environ.pop("JIRI_WEB_SECRET_KEY", None)
os.environ.pop("JIRI_DEV", None)


def csrf_token_for(client) -> str:
    """Make sure the test client's session has a CSRF token and return it."""
    with client.session_transaction() as sess:
        token = sess.get("jiri_csrf_token")
        if not token:
            import secrets

            token = secrets.token_urlsafe(32)
            sess["jiri_csrf_token"] = token
    return token


def login_client(client, password: str = TEST_ADMIN_PASSWORD, follow_redirects: bool = True):
    """Log a Flask test client in with a valid CSRF token, then make every
    later request from it carry the session's token as X-CSRF-Token."""
    response = client.post(
        "/admin/login",
        data={"password": password, "csrf_token": csrf_token_for(client)},
        follow_redirects=follow_redirects,
    )
    client.environ_base["HTTP_X_CSRF_TOKEN"] = csrf_token_for(client)
    return response

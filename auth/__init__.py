"""Auth module — session guard + login page.

session_guard() verifica app.storage.user['player_id'] en cada página protegida.
Si no hay sesión, redirige a /login. Sin encriptación en esta fase (§8).
"""

from nicegui import app, ui


def session_guard() -> bool:
    """Verify player_id in app.storage.user. Redirect to /login if missing.

    Returns True if session is valid, False if redirected.
    Call at the top of every protected @ui.page handler:

        @ui.page("/")
        def index():
            if not session_guard():
                return
            # ... protected content ...
    """
    if not app.storage.user.get("player_id"):
        ui.navigate.to("/login")
        return False
    return True

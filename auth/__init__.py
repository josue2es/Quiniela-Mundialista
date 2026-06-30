"""Auth module — session guard + login page.

session_guard() verifica app.storage.user['player_id'] en cada página protegida.
Si no hay sesión, redirige a /login. Sin encriptación en esta fase (§8).
"""

from nicegui import app, ui


def client_ip() -> str:
    """IP del cliente actual, honrando X-Forwarded-For (proxy/Docker).

    NiceGUI guarda el request inicial en context.client. Detrás de un reverse
    proxy, request.client.host es la IP del proxy, así que preferimos el primer
    valor de X-Forwarded-For cuando viene presente. Devuelve 'unknown' si no se
    puede determinar (p.ej. fuera de un contexto de página).
    """
    from nicegui import context

    try:
        client = context.client
        request = getattr(client, "request", None)
        if request is not None:
            xff = request.headers.get("x-forwarded-for")
            if xff:
                return xff.split(",")[0].strip()
            real = request.headers.get("x-real-ip")
            if real:
                return real.strip()
        ip = getattr(client, "ip", None)
        return ip or "unknown"
    except Exception:
        return "unknown"


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


def is_admin() -> bool:
    """True if the logged-in player has is_admin=True. False if no session."""
    player_id = app.storage.user.get("player_id")
    if not player_id:
        return False
    # Local imports to avoid a circular import at module load time.
    from data.database import SessionLocal
    from data.models import Player

    with SessionLocal() as session:
        player = session.get(Player, player_id)
        return bool(player and player.is_admin)

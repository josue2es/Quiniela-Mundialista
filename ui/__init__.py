"""UI package — helpers compartidos entre las pantallas."""

from nicegui import ui


def safe_timer(interval: float, callback):
    """ui.timer cuyo callback no rompe el event loop si el cliente se fue.

    Cuando una pestaña/cliente NiceGUI cierra, refrescar sus elementos lanza
    RuntimeError ("The parent slot of the element has been deleted"). Acá lo
    atrapamos y cancelamos el timer para no seguir intentando (y no spam-ear).
    """
    state: dict = {}

    def tick():
        try:
            callback()
        except RuntimeError:
            timer = state.get("timer")
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    pass

    state["timer"] = ui.timer(interval, tick)
    return state["timer"]


def player_avatar(avatar_url: str | None, *, size: int = 28):
    """Renderiza el avatar (.webp) del jugador, o un placeholder si no tiene.

    Pensado para contextos de fila/tarjeta (header, editor admin). Para tablas
    de Quasar se usa un slot body-cell con <img> (ver standings/apuestas).
    """
    if avatar_url:
        return ui.image(avatar_url).classes("player-avatar").style(
            f"width:{size}px;height:{size}px;border-radius:8px;"
            f"object-fit:cover;flex:0 0 auto"
        )
    return ui.label("👤").style(
        f"width:{size}px;height:{size}px;display:flex;align-items:center;"
        f"justify-content:center;opacity:0.4;flex:0 0 auto;"
        f"font-size:{int(size * 0.7)}px"
    )

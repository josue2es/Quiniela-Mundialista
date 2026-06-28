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

"""Login page — dropdown de nombres + password (4 dígitos) + primer-login bandera.

§8 del doc: auth/sesión con NiceGUI app.storage.user['player_id'].

Registra la ruta /login. Importar desde main.py activa el registro.
"""

from nicegui import app, ui

from data.database import SessionLocal
from data.models import Player

# ── Banderas disponibles (emoji bandera + nombre país) ──────────────────────
FLAGS: list[tuple[str, str]] = [
    ("🇦🇷", "Argentina"),
    ("🇧🇷", "Brasil"),
    ("🇩🇪", "Alemania"),
    ("🇫🇷", "Francia"),
    ("🇪🇸", "España"),
    ("🇬🇧", "Inglaterra"),
    ("🇮🇹", "Italia"),
    ("🇳🇱", "Países Bajos"),
    ("🇵🇹", "Portugal"),
    ("🇧🇪", "Bélgica"),
    ("🇺🇾", "Uruguay"),
    ("🇲🇽", "México"),
    ("🇺🇸", "Estados Unidos"),
    ("🇨🇦", "Canadá"),
    ("🇯🇵", "Japón"),
    ("🇰🇷", "Corea del Sur"),
    ("🇸🇻", "El Salvador"),
    ("🇨🇴", "Colombia"),
    ("🇨🇱", "Chile"),
    ("🇵🇪", "Perú"),
    ("🇪🇨", "Ecuador"),
    ("🇨🇷", "Costa Rica"),
    ("🇵🇦", "Panamá"),
    ("🇭🇳", "Honduras"),
    ("🇵🇾", "Paraguay"),
    ("🇧🇴", "Bolivia"),
    ("🇻🇪", "Venezuela"),
    ("🇸🇳", "Senegal"),
    ("🇳🇬", "Nigeria"),
    ("🇬🇭", "Ghana"),
    ("🇲🇦", "Marruecos"),
    ("🇩🇿", "Argelia"),
    ("🇹🇳", "Túnez"),
    ("🇨🇲", "Camerún"),
    ("🇭🇷", "Croacia"),
    ("🇩🇰", "Dinamarca"),
    ("🇸🇪", "Suecia"),
    ("🇵🇱", "Polonia"),
    ("🇨🇭", "Suiza"),
    ("🇦🇹", "Austria"),
    ("🇦🇺", "Australia"),
    ("🇸🇦", "Arabia Saudita"),
    ("🇶🇦", "Catar"),
]
FLAGS.sort(key=lambda x: x[1])


def _get_player_names() -> list[str]:
    """Return sorted list of player names from DB."""
    with SessionLocal() as session:
        return [row[0] for row in session.query(Player.name).order_by(Player.name).all()]


# ── Dark Theme CSS (keep in sync with main.py) ─────────────────────────
DARK_CSS = """<style>
  :root {
    --bg: #0a0e14; --surface: #141820; --card: #1a1f2b;
    --border: #252b38; --accent: #00c853; --accent2: #ffc107;
    --text: #e2e8f0; --text-dim: #94a3b8; --danger: #ef5350;
  }
  body { background: var(--bg) !important; color: var(--text) !important; }
  .q-card { background: var(--card) !important; border: 1px solid var(--border) !important; border-radius: 14px !important; }
  .q-field__native, .q-field__label { color: var(--text) !important; }
  .page-title { background: linear-gradient(135deg, var(--accent), var(--accent2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 800; }
</style>"""


@ui.page("/login")
def login_page():
    """Login: dropdown de nombres + password 4 dígitos + primer-login bandera."""
    state: dict = {"step": "login", "player": None}

    # Inject dark theme
    ui.add_head_html(DARK_CSS)

    # ── Paso 1: Login ──
    login_card = ui.card().classes("mx-auto mt-20 w-96 p-6")

    with login_card:
        ui.label("⚽ Quiniela Mundialista").classes("text-2xl font-bold text-center w-full mb-1 page-title")

        names = _get_player_names()
        if not names:
            ui.label("⚠️ No hay jugadores en la BD. Ejecutá el seed primero.").classes("text-red-500 text-center")
            return

        player_select = ui.select(
            label="Nombre",
            options=names,
            value=names[0],
        ).classes("w-full").props("outlined")

        pw_input = ui.input(
            label="Contraseña (4 dígitos)",
            password=True,
            password_toggle_button=True,
        ).props('type="number" maxlength="4"').classes("w-full")

        login_error = ui.label("").classes("text-red-500 text-sm mt-0 hidden")

        def do_login():
            name = player_select.value
            pw_val = pw_input.value or ""
            with SessionLocal() as session:
                player = session.query(Player).filter_by(name=name).first()
                if player and player.password == pw_val:
                    state["player"] = player
                    if player.is_setup:
                        # Ya configurado → sesión y redirect
                        app.storage.user["player_id"] = player.id
                        app.storage.user["player_name"] = player.name
                        app.storage.user["avatar_flag"] = player.avatar_flag
                        ui.navigate.to("/")
                    else:
                        # Primer login → elegir bandera
                        state["step"] = "setup"
                        login_card.clear()
                        with login_card:
                            _render_flag_selector(player)
                else:
                    login_error.set_text("❌ Nombre o contraseña incorrectos.")
                    login_error.classes(remove="hidden")

        with ui.row().classes("w-full justify-center mt-2"):
            ui.button("Ingresar", icon="login", on_click=do_login).props("unelevated").classes("w-32")


def _render_flag_selector(player: Player):
    """Segundo paso: elegir bandera como avatar."""
    ui.label(f"🎉 ¡Bienvenido, {player.name}!").classes("text-xl font-bold text-center w-full")
    ui.label("Elegí tu bandera (avatar):").classes("text-sm text-gray-500 text-center w-full mt-1")

    flag_map = {f"{emoji}  {name}": emoji for emoji, name in FLAGS}
    flag_labels = list(flag_map.keys())

    flag_select = ui.select(
        label="Bandera",
        options=flag_labels,
        value=flag_labels[0],
    ).classes("w-full mt-2").props("outlined")

    def save_flag():
        emoji_flag = flag_map.get(flag_select.value, "🏳️")
        with SessionLocal() as session:
            db_player = session.query(Player).filter_by(id=player.id).first()
            if db_player:
                db_player.avatar_flag = emoji_flag
                db_player.is_setup = True
                session.commit()
        app.storage.user["player_id"] = player.id
        app.storage.user["player_name"] = player.name
        app.storage.user["avatar_flag"] = emoji_flag
        ui.navigate.to("/")

    with ui.row().classes("w-full justify-center mt-4"):
        ui.button("¡Listo!", icon="check_circle", on_click=save_flag).props("unelevated").classes("w-32")

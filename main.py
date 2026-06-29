"""Quiniela Mundialista — NiceGUI app.

Auth (F1): login con dropdown + password 4 dígitos + primer-login bandera.
Sesión: app.storage.user['player_id'] con guard en "/".
Scheduler (D1): APScheduler async — sync_fixtures refresca matches cada 6h.
"""

import asyncio
import logging
import os
import secrets

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from nicegui import app, ui

from data.database import init_db, seed_players, SessionLocal
from auth import session_guard, is_admin
from ui.standings import standings_page
from ui.manana import manana_page
from ui.hoy import hoy_page
from ui.apuestas import apuestas_page
from ui.admin import admin_page
import auth.login  # noqa: F401 — registers /login page

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Seed on startup ─────────────────────────────────────────────────────────
init_db()
seed_players()

# Optional demo data (round of 32) — only when SEED_DEMO is set AND the DB has
# no players yet. Idempotent across restarts: existing data is never wiped.
if os.environ.get("SEED_DEMO", "").strip().lower() in ("1", "true", "yes"):
    from data.models import Player

    with SessionLocal() as _s:
        _is_empty = _s.query(Player).first() is None
    if _is_empty:
        from scripts.seed import seed as _seed_demo

        _seed_demo()
        logger.info("SEED_DEMO: datos de demostración cargados (dieciseisavos)")
    else:
        logger.info("SEED_DEMO activo pero la BD ya tiene jugadores — se omite")

# Cleanup al arrancar: recupera partidos zombi (FINISHED sin goles) que pudieron
# quedar si la app estuvo caída mientras un sync los marcó finished sin que el
# poll los procesara. Se resetean a SCHEDULED para que el próximo poll los puntúe.
from scheduler.poll_results import reset_zombie_matches as _reset_zombies

_zombies = _reset_zombies(SessionLocal)
if _zombies:
    logger.warning("Startup: %d partido(s) zombi reseteados a SCHEDULED", _zombies)

# ── Storage secret (requerido para app.storage.user) ────────────────────────
STORAGE_SECRET = os.environ.get("STORAGE_SECRET", secrets.token_hex(32))

# ── Scheduler setup (D1/D2/D3) ───────────────────────────────────────────────
scheduler = AsyncIOScheduler()


async def _sync_fixtures_job():
    """Job wrapper: create provider → sync_fixtures → log result."""
    from scheduler.sync import sync_fixtures
    from provider.api_football import ApiFootballProvider

    try:
        async with ApiFootballProvider() as provider:
            result = await sync_fixtures(provider, SessionLocal)
            logger.info("sync_fixtures done: %s", result)
    except Exception:
        logger.exception("sync_fixtures job failed")


async def _poll_results_job():
    """Job wrapper: create provider → poll_results → log result.

    D2+D3: polls match results every ~10 min, triggers scoring
    (match_scores for all 11 players) when a match transitions to finished.
    """
    from scheduler.poll_results import poll_results
    from provider.api_football import ApiFootballProvider

    try:
        async with ApiFootballProvider() as provider:
            result = await poll_results(provider, SessionLocal)
            if result["scored_matches"] > 0:
                logger.info(
                    "poll_results: %d scored, %d rows inserted out of %d active",
                    result["scored_matches"],
                    result["rows_inserted"],
                    result["active_matches"],
                )
            else:
                logger.debug("poll_results: no finished matches (active=%d)", result["active_matches"])
    except Exception:
        logger.exception("poll_results job failed")


async def _daily_snapshot_job():
    """Job wrapper: compute standings snapshot at midnight ES (§7 D4)."""
    from scripts.daily_snapshot import compute_standings

    try:
        rows = compute_standings()
        logger.info("daily_snapshot done: %d player rows stored", len(rows))
    except Exception:
        logger.exception("daily_snapshot job failed")


# ── Global Dark Theme CSS ──────────────────────────────────────────────────
DARK_CSS = """
<style>
  :root {
    --bg: #0a0e14;
    --surface: #141820;
    --card: #1a1f2b;
    --card-hover: #1e2533;
    --border: #252b38;
    --accent: #00c853;
    --accent2: #ffc107;
    --accent3: #00bcd4;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --danger: #ef5350;
    --warning: #ff9800;
  }
  body {
    background: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'Inter', system-ui, sans-serif;
  }
  .q-tab--active {
    color: var(--accent) !important;
    border-bottom: 2px solid var(--accent) !important;
  }
  .q-tab {
    color: var(--text-dim) !important;
  }
  /* Tab panels default to white — force transparent so the dark bg shows */
  .q-tab-panels, .q-tab-panel, .q-panel {
    background: transparent !important;
  }
  .nicegui-content, .q-page, .q-page-container {
    background: transparent !important;
  }
  .q-table {
    background: var(--card) !important;
    border-radius: 12px !important;
    overflow: hidden;
  }
  .q-table th {
    background: var(--surface) !important;
    color: var(--accent2) !important;
    font-weight: 700;
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .q-table td {
    color: var(--text) !important;
    border-color: var(--border) !important;
  }
  .q-card {
    background: var(--card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 14px !important;
    box-shadow: 0 4px 24px rgba(0,0,0,0.3) !important;
    transition: box-shadow 0.2s;
  }
  .q-card:hover {
    box-shadow: 0 6px 32px rgba(0,0,0,0.5) !important;
  }
  .match-card:hover {
    border-color: var(--accent) !important;
  }
  .q-field__native, .q-field__label {
    color: var(--text) !important;
  }
  .text-dim { color: var(--text-dim) !important; }
  /* Team row: flag + country name, truncates on small screens */
  .team-name {
    font-weight: 700;
    font-size: 1rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* Team crest rendered from a logo URL (real API matches) */
  .flag-img {
    width: 26px !important;
    height: 26px !important;
    min-width: 26px;
    flex: 0 0 auto;
  }
  .flag-img img, .flag-img .q-img__image {
    object-fit: contain !important;
  }
  .score-input {
    width: 72px !important;
    flex: 0 0 auto;
  }
  .score-input input[type=number] {
    font-size: 1.2rem !important;
    font-weight: 800 !important;
    text-align: center !important;
    padding: 6px 4px !important;
  }
  .score-final {
    font-size: 1.5rem !important;
    font-weight: 800 !important;
    color: var(--accent) !important;
    flex: 0 0 auto;
    min-width: 32px;
    text-align: center;
  }
  input[type=number] {
    color: var(--text) !important;
    font-weight: 700 !important;
    text-align: center !important;
  }
  /* Hide number spin buttons for a cleaner mobile look */
  input[type=number]::-webkit-inner-spin-button,
  input[type=number]::-webkit-outer-spin-button {
    -webkit-appearance: none; margin: 0;
  }
  .standings-table { font-size: 0.95rem; }
  .standings-table td, .standings-table th { padding: 6px 8px !important; }
  .stage-badge {
    font-size: 0.7rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.08em !important;
    border-radius: 6px !important;
    padding: 2px 10px !important;
    text-transform: uppercase;
  }
  .stage-group { background: #1a3a2a !important; color: #4ade80 !important; }
  .stage-knockout { background: #3a1a1a !important; color: #f87171 !important; }
  .stage-amistoso { background: #1a2a3a !important; color: #60a5fa !important; }
  .btn-save {
    background: linear-gradient(135deg, var(--accent), #00a844) !important;
    color: #000 !important;
    font-weight: 700 !important;
    border-radius: 8px !important;
  }
  .btn-logout {
    color: var(--text-dim) !important;
    opacity: 0.7;
  }
  .btn-logout:hover {
    color: var(--danger) !important;
    opacity: 1;
  }
  .header-bar {
    background: linear-gradient(180deg, var(--surface) 0%, transparent 100%);
    padding-bottom: 12px;
  }
  .flag-display {
    font-size: 2rem;
    filter: drop-shadow(0 2px 4px rgba(0,0,0,0.5));
  }
  .vs-divider {
    color: var(--text-dim);
    font-weight: 300;
    font-size: 0.85rem;
  }
  .match-time {
    background: var(--surface);
    padding: 4px 12px;
    border-radius: 20px;
    font-weight: 600;
    font-size: 0.85rem;
    color: var(--accent2);
  }
  .page-title {
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    font-weight: 800;
  }
  .points-badge {
    background: linear-gradient(135deg, #b45309, #d97706);
    color: #fef3c7;
    font-weight: 800;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.9rem;
  }
</style>
"""

# ── UI ──────────────────────────────────────────────────────────────────────

@ui.page("/")
def index():
    """Main page — protected by session guard."""
    if not session_guard():
        return

    # Inject dark theme
    ui.add_head_html(DARK_CSS)

    player_name = app.storage.user.get("player_name", "???")
    avatar = app.storage.user.get("avatar_flag", "🏳️")

    # ── Header ──
    with ui.header(elevated=False).classes("header-bar"):
        with ui.row().classes(
            "w-full max-w-4xl mx-auto items-center justify-between px-3 py-2 "
            "flex-nowrap gap-2"
        ):
            with ui.row().classes("items-center gap-1 min-w-0"):
                ui.label("⚽").classes("text-xl")
                ui.label("Quiniela").classes("text-lg font-bold page-title")
            with ui.row().classes("items-center gap-2 min-w-0 flex-nowrap"):
                ui.label(avatar).classes("text-xl")
                ui.label(player_name).classes(
                    "text-base font-semibold text-white team-name"
                )
                ui.button(
                    icon="logout",
                    on_click=lambda: (
                        app.storage.user.clear(),
                        ui.navigate.to("/login"),
                    ),
                ).props("flat dense round").classes("btn-logout")

    # Admin tab only for admins (checked at render time)
    show_admin = is_admin()

    # ── Tabs ──
    with ui.row().classes("w-full max-w-4xl mx-auto mt-4 px-2"):
        with ui.tabs().classes("w-full") as tabs:
            ui.tab("Hoy", icon="sports_soccer")
            ui.tab("Tabla", icon="leaderboard")
            ui.tab("Mañana", icon="event")
            ui.tab("Apuestas", icon="receipt_long")
            if show_admin:
                ui.tab("Admin", icon="admin_panel_settings")

    with ui.tab_panels(tabs, value="Hoy").classes(
        "w-full max-w-4xl mx-auto mt-2 px-2 mb-8"
    ):
        with ui.tab_panel("Hoy"):
            hoy_page()
        with ui.tab_panel("Tabla"):
            standings_page()
        with ui.tab_panel("Mañana"):
            manana_page()
        with ui.tab_panel("Apuestas"):
            apuestas_page()
        if show_admin:
            with ui.tab_panel("Admin"):
                admin_page()


# ── Startup hook ───────────────────────────────────────────────────────────

@app.on_startup
async def on_startup():
    """Start the APScheduler background jobs."""
    if not scheduler.running:
        # sync_fixtures every 6 hours
        scheduler.add_job(
            _sync_fixtures_job,
            "interval",
            hours=6,
            id="sync_fixtures",
            next_run_time=None,
        )
        # poll_results every 10 minutes (§7)
        scheduler.add_job(
            _poll_results_job,
            "interval",
            minutes=10,
            id="poll_results",
            next_run_time=None,
        )
        # daily_snapshot at midnight ES (06:00 UTC) (§7 D4)
        from zoneinfo import ZoneInfo as _ZI
        scheduler.add_job(
            _daily_snapshot_job,
            "cron",
            hour=6,
            minute=0,
            timezone=_ZI("America/El_Salvador"),
            id="daily_snapshot",
        )
        scheduler.start()
        logger.info("APScheduler started — sync_fixtures every 6h, poll_results every 10min, daily_snapshot at midnight ES")

    # Fire first runs shortly after startup
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    scheduler.add_job(
        _sync_fixtures_job,
        "date",
        run_date=now + _dt.timedelta(seconds=30),
        id="sync_fixtures_startup",
        replace_existing=True,
    )
    scheduler.add_job(
        _poll_results_job,
        "date",
        run_date=now + _dt.timedelta(seconds=60),
        id="poll_results_startup",
        replace_existing=True,
    )


@app.on_shutdown
def on_shutdown():
    """Gracefully stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down")


# ── Entrypoint ──────────────────────────────────────────────────────────────

if __name__ in ("__main__", "__mp_main__"):
    ui.run(
        title="Quiniela Mundialista",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8091")),
        storage_secret=STORAGE_SECRET,
        reload=False,
    )

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
from auth import session_guard
from ui.standings import standings_page
from ui.manana import manana_page
from ui.hoy import hoy_page
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


# ── UI ──────────────────────────────────────────────────────────────────────

@ui.page("/")
def index():
    """Main page — protected by session guard."""
    if not session_guard():
        return

    player_name = app.storage.user.get("player_name", "???")
    avatar = app.storage.user.get("avatar_flag", "🏳️")

    # ── Header ──
    with ui.row().classes(
        "w-full max-w-4xl mx-auto items-center justify-between mt-4 px-4"
    ):
        ui.label(f"{avatar}  {player_name}").classes("text-xl font-bold")
        ui.button(
            "Salir",
            icon="logout",
            on_click=lambda: (
                app.storage.user.clear(),
                ui.navigate.to("/login"),
            ),
        ).props("flat")

    ui.separator().classes("w-full max-w-4xl mx-auto my-2")

    # ── Tabs ──
    with ui.tabs().classes("w-full max-w-4xl mx-auto") as tabs:
        ui.tab("Hoy", icon="today")
        ui.tab("Tabla", icon="leaderboard")
        ui.tab("Mañana", icon="event")

    with ui.tab_panels(tabs, value="Tabla").classes(
        "w-full max-w-4xl mx-auto"
    ):
        with ui.tab_panel("Hoy"):
            hoy_page()
        with ui.tab_panel("Tabla"):
            standings_page()
        with ui.tab_panel("Mañana"):
            manana_page()


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
        port=int(os.environ.get("PORT", "8090")),
        storage_secret=STORAGE_SECRET,
        reload=False,
    )

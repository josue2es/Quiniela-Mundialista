"""Scheduler — background jobs for Quiniela Mundialista.

D1: sync_fixtures — refresh today/tomorrow matches, resolve TBD.
D2: poll_results  — poll for finished matches, update scores.
"""

from scheduler.sync import sync_fixtures, es_today
from scheduler.poll_results import poll_results, _score_match, _is_finished_status

__all__ = ["sync_fixtures", "es_today", "poll_results", "_score_match", "_is_finished_status"]

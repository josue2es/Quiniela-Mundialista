#!/usr/bin/env python3
"""Insert test match: El Salvador vs Guatemala for today."""
import sys, os
sys.path.insert(0, '/home/hermes/Quiniela-Mundialista')

from datetime import datetime, date, timezone
from data.database import SessionLocal
from data.models import Match, MatchStatus

external_id = 'test-sv-gt-20260627'

with SessionLocal() as session:
    existing = session.query(Match).filter_by(external_id=external_id).first()
    if existing:
        print(f'ALREADY EXISTS: {existing.to_dict()}')
    else:
        m = Match(
            external_id=external_id,
            home='El Salvador',
            away='Guatemala',
            home_flag='🇸🇻',
            away_flag='🇬🇹',
            kickoff_utc=datetime(2026, 6, 28, 0, 0, tzinfo=timezone.utc),
            match_date_local=date(2026, 6, 27),
            stage='amistoso',
            status=MatchStatus.SCHEDULED,
        )
        session.add(m)
        session.commit()
        print(f'INSERTED: {m.to_dict()}')

# Verify
with SessionLocal() as session:
    matches_today = session.query(Match).filter(
        Match.match_date_local == date(2026, 6, 27)
    ).all()
    print(f'\nMatches for 2026-06-27: {len(matches_today)}')
    for m in matches_today:
        print(f'  {m.home} vs {m.away} - {m.status.value} @ {m.kickoff_utc}')

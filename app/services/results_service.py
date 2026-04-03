from flask import current_app
from sqlalchemy import text
from app import db
from app.models import Candidate


def get_vote_tallies():
    """
    Return a dict of {candidate_name: vote_count} from the database.
    Uses the voters engine if available (split-connection mode),
    falling back to the default bind.
    """
    try:
        voters_engine = db.engines.get('voters')
        if voters_engine is None:
            raise RuntimeError("Voters engine not configured")
        with voters_engine.connect() as conn:
            try:
                res = conn.execute(text(
                    "SELECT name, votes FROM vote_counts "
                    "ORDER BY votes DESC, name ASC"
                ))
            except Exception:
                res = conn.execute(text(
                    "SELECT c.name AS name, COUNT(v.id) AS votes "
                    "FROM candidate c "
                    "LEFT JOIN vote v ON v.candidate_id = c.id "
                    "GROUP BY c.id, c.name "
                    "ORDER BY votes DESC, c.name ASC"
                ))
            rows = list(res)
        return {r[0]: int(r[1] or 0) for r in rows}
    except Exception as e:
        current_app.logger.warning(f"Failed to load results from voters bind: {e}")
        return {c.name: 0 for c in Candidate.query.all()}

"""Fail-closed, election-scoped vote tally access."""

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import db


class ResultsUnavailableError(RuntimeError):
    """Raised when authoritative election tallies cannot be read."""


def get_vote_tallies(election_id):
    """Return identity-safe candidate tally rows for exactly one election.

    Database failures are surfaced to callers. Returning synthetic zeroes would
    make an unavailable database indistinguishable from a zero-turnout result.
    """
    try:
        election_id = int(election_id)
    except (TypeError, ValueError) as exc:
        raise ResultsUnavailableError("A valid election_id is required") from exc

    try:
        engine = db.engines.get("voters")
        if engine is None:
            engine = db.engine
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT c.id AS candidate_id, c.name AS name, "
                    "c.position AS position, c.region_id AS region_id, "
                    "r.name AS region, COUNT(v.id) AS votes "
                    "FROM candidate c "
                    "JOIN regions r ON r.id = c.region_id "
                    "LEFT JOIN vote v "
                    "ON v.candidate_id = c.id "
                    "AND v.election_id = c.election_id "
                    "WHERE c.election_id = :election_id "
                    "GROUP BY c.id, c.name, c.position, c.region_id, r.name "
                    "ORDER BY votes DESC, c.name ASC, c.id ASC"
                ),
                {"election_id": election_id},
            ).all()
    except (SQLAlchemyError, RuntimeError) as exc:
        current_app.logger.error(
            "Authoritative tallies are unavailable for election %s",
            election_id,
            exc_info=True,
        )
        raise ResultsUnavailableError(
            f"Tallies are unavailable for election {election_id}"
        ) from exc

    return [
        {
            "candidate_id": int(row[0]),
            "name": row[1],
            "position": row[2],
            "region_id": int(row[3]),
            "region": row[4],
            "votes": int(row[5] or 0),
        }
        for row in rows
    ]

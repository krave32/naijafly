"""Seed the database with West African routes for immediate worker coverage.

Run once after deployment to pre-populate tracked routes so the worker
starts ingesting fares immediately, even before any user sends a SUBSCRIBE.

Usage:
    python -m app.seed_routes
    # Or from within the worker startup (called automatically)
"""
import logging
import os

logger = logging.getLogger("naijafly.seed")

# All routes NaijaFly tracks across Nigeria and West Africa.
# Each tuple is (origin, destination) using IATA airport codes.
WEST_AFRICA_ROUTES = [
    # ---- Nigeria domestic ----
    ("LOS", "ABV"),  # Lagos -> Abuja (busiest route)
    ("ABV", "LOS"),  # Abuja -> Lagos
    ("LOS", "PHC"),  # Lagos -> Port Harcourt
    ("PHC", "LOS"),  # Port Harcourt -> Lagos
    ("LOS", "ENU"),  # Lagos -> Enugu
    ("ENU", "LOS"),  # Enugu -> Lagos
    ("LOS", "BNI"),  # Lagos -> Benin City
    ("BNI", "LOS"),  # Benin City -> Lagos
    ("LOS", "KAN"),  # Lagos -> Kano
    ("KAN", "LOS"),  # Kano -> Lagos
    ("LOS", "CBQ"),  # Lagos -> Calabar
    ("CBQ", "LOS"),  # Calabar -> Lagos
    ("ABV", "PHC"),  # Abuja -> Port Harcourt
    ("PHC", "ABV"),  # Port Harcourt -> Abuja
    ("ABV", "ENU"),  # Abuja -> Enugu
    ("ENU", "ABV"),  # Enugu -> Abuja
    ("ABV", "BNI"),  # Abuja -> Benin City
    ("BNI", "ABV"),  # Benin City -> Abuja
    ("ABV", "KAN"),  # Abuja -> Kano
    ("LOS", "ILR"),  # Lagos -> Ilorin
    ("LOS", "AKR"),  # Lagos -> Akure

    # ---- Nigeria <-> Ghana ----
    ("LOS", "ACC"),  # Lagos -> Accra
    ("ACC", "LOS"),  # Accra -> Lagos

    # ---- Ghana domestic ----
    ("ACC", "KMS"),  # Accra -> Kumasi
    ("KMS", "ACC"),  # Kumasi -> Accra
    ("ACC", "TML"),  # Accra -> Tamale

    # ---- West Africa regional ----
    ("LOS", "DKR"),  # Lagos -> Dakar (Senegal)
    ("DKR", "LOS"),  # Dakar -> Lagos
    ("ACC", "DKR"),  # Accra -> Dakar
    ("LOS", "ABJ"),  # Lagos -> Abidjan (Côte d'Ivoire)
    ("ABJ", "LOS"),  # Abidjan -> Lagos
    ("ACC", "ABJ"),  # Accra -> Abidjan
    ("LOS", "FNA"),  # Lagos -> Freetown (Sierra Leone)
    ("ACC", "OUA"),  # Accra -> Ouagadougou (Burkina Faso)
]


def seed(db=None):
    """Insert all West African routes into the database if they don't exist.

    Idempotent — safe to run multiple times. Only adds routes that are missing.
    Returns the number of new routes created.
    """
    from app.models.models import Route

    own_session = db is None
    if own_session:
        from app.core.database import SessionLocal
        db = SessionLocal()

    new_count = 0
    try:
        for origin, destination in WEST_AFRICA_ROUTES:
            existing = db.query(Route).filter_by(
                origin=origin, destination=destination).first()
            if not existing:
                db.add(Route(origin=origin, destination=destination))
                new_count += 1
                logger.info("Seeded route %s -> %s", origin, destination)
        db.commit()
        total = db.query(Route).count()
        logger.info(
            "Route seed complete: %d new, %d total routes in database.",
            new_count, total)
        return new_count
    except Exception as e:
        logger.error("Route seeding failed: %s", e)
        db.rollback()
        raise
    finally:
        if own_session:
            db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed()

"""Seed the database with Nigeria-domestic routes for immediate worker coverage.

Run once after deployment to pre-populate tracked routes so the worker
starts ingesting fares immediately, even before any user sends a SUBSCRIBE.

Usage:
    python -m app.seed_routes
    # Or from within the worker startup (called automatically)
"""
import logging

logger = logging.getLogger("naijafly.seed")

# Nigeria-domestic routes only. Each tuple is (origin, destination) using
# IATA airport codes. Cross-border routes (Ghana, Senegal, Côte d'Ivoire,
# etc.) were removed — NaijaFly now focuses exclusively on Nigerian domestic
# flights served by Air Peace, Arik Air, Ibom Air, United Nigeria Airlines,
# Green Africa Airways, ValueJet, and other Nigerian carriers.
NIGERIA_DOMESTIC_ROUTES = [
    # ---- Lagos hub (busiest) ----
    ("LOS", "ABV"),  # Lagos -> Abuja
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
    ("LOS", "ILR"),  # Lagos -> Ilorin
    ("ILR", "LOS"),  # Ilorin -> Lagos
    ("LOS", "QOW"),  # Lagos -> Owerri (Sam Mbakwe Airport)
    ("QOW", "LOS"),  # Owerri -> Lagos

    # ---- Abuja hub ----
    ("ABV", "PHC"),  # Abuja -> Port Harcourt
    ("PHC", "ABV"),  # Port Harcourt -> Abuja
    ("ABV", "ENU"),  # Abuja -> Enugu
    ("ENU", "ABV"),  # Enugu -> Abuja
    ("ABV", "BNI"),  # Abuja -> Benin City
    ("BNI", "ABV"),  # Benin City -> Abuja
    ("ABV", "KAN"),  # Abuja -> Kano
    ("KAN", "ABV"),  # Kano -> Abuja
    ("ABV", "CBQ"),  # Abuja -> Calabar
    ("CBQ", "ABV"),  # Calabar -> Abuja

    # ---- Secondary routes ----
    ("PHC", "ENU"),  # Port Harcourt -> Enugu
    ("ENU", "PHC"),  # Enugu -> Port Harcourt
]


def seed(db=None):
    """Insert all Nigeria-domestic routes into the database if they don't exist.

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
        for origin, destination in NIGERIA_DOMESTIC_ROUTES:
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

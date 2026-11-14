"""Small, safe schema upgrade that runs on every start-up.

db.create_all() creates missing TABLES but never adds new COLUMNS to a
table that already exists. This module adds any missing columns to an
existing database so older database files keep working. It is
idempotent: running it again changes nothing.
"""

from sqlalchemy import inspect, text

# table -> [(column name, SQLite column definition)]
NEW_COLUMNS = {
    "users": [
        ("department", "VARCHAR(100)"),
        ("contact_details", "VARCHAR(150)"),
    ],
    "courses": [
        ("status", "VARCHAR(20) NOT NULL DEFAULT 'active'"),
    ],
    "examinations": [
        ("examination_type", "VARCHAR(30) NOT NULL DEFAULT 'Assessment'"),
        ("slot_creation_opens_at", "DATETIME"),
        ("slot_creation_closes_at", "DATETIME"),
    ],
    "exam_slots": [
        ("examiner_id", "INTEGER REFERENCES users(id)"),
        ("status", "VARCHAR(20) NOT NULL DEFAULT 'available'"),
    ],
}


def upgrade_schema(db):
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    added_slot_columns = False

    for table, columns in NEW_COLUMNS.items():
        if table not in tables:
            continue

        existing = {c["name"] for c in inspector.get_columns(table)}

        for name, definition in columns:
            if name not in existing:
                db.session.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                )
                if table == "exam_slots":
                    added_slot_columns = True

    db.session.commit()

    # Fill in the new slot columns for slots created before the upgrade.
    if "exam_slots" in tables:
        db.session.execute(text(
            "UPDATE exam_slots SET examiner_id = ("
            "  SELECT ea.examiner_id FROM examiner_assignments ea"
            "  WHERE ea.examination_id = exam_slots.examination_id"
            "  ORDER BY ea.id LIMIT 1"
            ") WHERE examiner_id IS NULL"
        ))

        if added_slot_columns:
            db.session.execute(text(
                "UPDATE exam_slots SET status = 'full' "
                "WHERE capacity <= ("
                "  SELECT COUNT(*) FROM exam_bookings b"
                "  WHERE b.slot_id = exam_slots.id AND b.status = 'booked'"
                ")"
            ))

        db.session.commit()

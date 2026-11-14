
import sqlite3
from pathlib import Path

db_path = Path("instance/examination.db")

if not db_path.exists():
    raise FileNotFoundError(
        f"Database not found: {db_path.resolve()}"
    )

connection = sqlite3.connect(db_path)

try:
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(examinations)"
        ).fetchall()
    }

    if not columns:
        raise RuntimeError(
            "The examinations table was not found."
        )

    new_columns = [
        "slot_creation_opens_at",
        "slot_creation_closes_at",
    ]

    for column in new_columns:
        if column not in columns:
            connection.execute(
                f"ALTER TABLE examinations "
                f"ADD COLUMN {column} DATETIME"
            )
            print(f"Added column: {column}")
        else:
            print(f"Column already exists: {column}")

    connection.commit()
    print("Database migration completed successfully.")

except Exception:
    connection.rollback()
    raise

finally:
    connection.close()


import sqlite3
from pathlib import Path

db_path = Path(__file__).parent / "instance" / "examination.db"

connection = sqlite3.connect(db_path)

try:
    cursor = connection.cursor()

    cursor.execute("PRAGMA table_info(examinations)")
    columns = [column[1] for column in cursor.fetchall()]

    if "examination_type" not in columns:
        cursor.execute("""
            ALTER TABLE examinations
            ADD COLUMN examination_type
            VARCHAR(30) NOT NULL DEFAULT 'Assessment'
        """)
        print("Added examination_type column successfully.")
    else:
        print("examination_type column already exists.")

    connection.commit()

    cursor.execute("""
        SELECT id, title, examination_type
        FROM examinations
    """)
    for examination in cursor.fetchall():
        print(examination)

except Exception:
    connection.rollback()
    raise

finally:
    connection.close()

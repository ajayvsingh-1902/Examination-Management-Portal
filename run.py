
from app import create_app
from app.reminders import start_reminder_scheduler

app = create_app()

if __name__ == "__main__":
    scheduler = start_reminder_scheduler(app)

    try:
        app.run(debug=False, use_reloader=False)
    finally:
        scheduler.shutdown(wait=False)

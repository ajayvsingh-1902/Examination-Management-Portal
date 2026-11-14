
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.extensions import db
from app.models import ExamBooking, Notification


def check_due_exam_reminders(app):
    """Create reminders for students with upcoming booked examinations."""

    with app.app_context():
        now = datetime.now()

        try:
            bookings = db.session.scalars(
                db.select(ExamBooking).where(
                    ExamBooking.status == "booked"
                )
            ).all()

            for booking in bookings:
                slot = booking.slot

                if slot is None:
                    continue

                exam_start = datetime.combine(
                    slot.slot_date,
                    slot.start_time
                )

                time_remaining = exam_start - now

                if time_remaining <= timedelta(0):
                    continue

                if time_remaining <= timedelta(hours=1):
                    category = "exam_reminder_1h"
                elif time_remaining <= timedelta(hours=24):
                    category = "exam_reminder_24h"
                else:
                    continue

                # Include the booking ID to prevent duplicate reminders
                # for the same booking and reminder category.
                message = (
                    f"Upcoming examination reminder: "
                    f"'{booking.examination.title}' is scheduled for "
                    f"{slot.slot_date.strftime('%d %b %Y')} at "
                    f"{slot.start_time.strftime('%I:%M %p')}. "
                    f"Booking reference: #{booking.id}."
                )

                existing = db.session.scalar(
                    db.select(Notification.id).where(
                        Notification.user_id == booking.student_id,
                        Notification.category == category,
                        Notification.message == message
                    ).limit(1)
                )

                if existing is not None:
                    continue

                db.session.add(
                    Notification(
                        user_id=booking.student_id,
                        message=message,
                        category=category,
                        is_read=False
                    )
                )

            db.session.commit()

        except Exception:
            db.session.rollback()
            app.logger.exception(
                "Could not generate examination reminders."
            )


def start_reminder_scheduler(app):
    """Run the reminder check immediately and every five minutes."""

    scheduler = BackgroundScheduler()

    scheduler.add_job(
        check_due_exam_reminders,
        trigger="interval",
        minutes=5,
        args=[app],
        id="exam_reminder_checker",
        replace_existing=True,
        next_run_time=datetime.now()
    )

    scheduler.start()
    return scheduler

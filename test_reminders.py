
from datetime import datetime, timedelta
from unittest.mock import patch

from app import create_app
from app.reminders import check_due_exam_reminders
from app.extensions import db
from app.models import ExamBooking, Notification

app = create_app()

with app.app_context():
    booking = db.session.scalar(
        db.select(ExamBooking).where(
            ExamBooking.status == "booked",
            ExamBooking.slot_id.is_not(None)
        ).limit(1)
    )

    if booking is None:
        print("No booked examination with a slot exists.")
    else:
        slot = booking.slot

        # Simulate the clock as 30 minutes before the exam.
        simulated_now = datetime.combine(
            slot.slot_date,
            slot.start_time
        ) - timedelta(minutes=30)

        before_ids = set(
            db.session.scalars(
                db.select(Notification.id).where(
                    Notification.user_id == booking.student_id
                )
            ).all()
        )

        try:
            with patch(
                "app.reminders.datetime"
            ) as mock_datetime:
                mock_datetime.now.return_value = simulated_now
                mock_datetime.combine = datetime.combine
                mock_datetime.timedelta = timedelta

                check_due_exam_reminders(app)

            db.session.expire_all()

            new_notifications = db.session.scalars(
                db.select(Notification).where(
                    Notification.user_id == booking.student_id,
                    Notification.category == "exam_reminder_1h"
                )
            ).all()

            created = [
                notification
                for notification in new_notifications
                if notification.id not in before_ids
            ]

            if created:
                print("PASS: Reminder notification created.")
                print(created[-1].message)
            else:
                print(
                    "No new reminder found. "
                    "We will inspect the result before changing anything."
                )
        except Exception as error:
            print("Test error:", repr(error))

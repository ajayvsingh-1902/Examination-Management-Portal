
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import UniqueConstraint

from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(
        db.String(150),
        unique=True,
        nullable=False,
        index=True
    )
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False)

    # Examiner profile details (optional for students and admin).
    department = db.Column(db.String(100), nullable=True)
    contact_details = db.Column(db.String(150), nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(
        db.String(20),
        nullable=False,
        default="active",
        server_default="active"
    )


class Examination(db.Model):
    __tablename__ = "examinations"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    examination_type = db.Column(
    db.String(30),
    nullable=False,
    default="Assessment"
)
    course_id = db.Column(
        db.Integer,
        db.ForeignKey("courses.id"),
        nullable=False
    )
    duration_minutes = db.Column(db.Integer, nullable=False)
    max_marks = db.Column(db.Integer, nullable=False)
    booking_opens_at = db.Column(db.DateTime(timezone=True))
    booking_closes_at = db.Column(db.DateTime(timezone=True))

    slot_creation_opens_at = db.Column(db.DateTime(timezone=True))
    slot_creation_closes_at = db.Column(db.DateTime(timezone=True))

    status = db.Column(db.String(20), default="draft", nullable=False)

    course = db.relationship("Course", backref="examinations")

    @property
    def lifecycle_status(self):
        """Draft / Slot Creation / Booking Open / Closed / Completed.

        Derived from the stored status, the two date windows and the
        published results. "Scheduled" is shown while the examination
        is published but waiting for its next window to open.
        """
        if self.status != "published":
            return "Draft"

        now = datetime.now()

        def naive(value):
            if value is not None and value.tzinfo is not None:
                return value.replace(tzinfo=None)
            return value

        def in_window(opens, closes):
            opens, closes = naive(opens), naive(closes)
            return (
                (opens is None or now >= opens)
                and (closes is None or now < closes)
            )

        active_bookings = [
            booking for booking in self.bookings
            if booking.status == "booked"
        ]

        if active_bookings and all(
            booking.result is not None
            and booking.result.status == "published"
            for booking in active_bookings
        ):
            return "Completed"

        if in_window(self.booking_opens_at, self.booking_closes_at):
            return "Booking Open"

        if in_window(
            self.slot_creation_opens_at, self.slot_creation_closes_at
        ):
            return "Slot Creation"

        windows_over = all(
            closes is not None and now >= naive(closes)
            for closes in (
                self.slot_creation_closes_at,
                self.booking_closes_at
            )
        )

        return "Closed" if windows_over else "Scheduled"


class ExamRubric(db.Model):
    __tablename__ = "exam_rubrics"

    id = db.Column(db.Integer, primary_key=True)

    examination_id = db.Column(
        db.Integer,
        db.ForeignKey("examinations.id"),
        nullable=False
    )

    criterion_name = db.Column(
        db.String(150),
        nullable=False
    )

    max_marks = db.Column(
        db.Float,
        nullable=False
    )

    weightage = db.Column(
        db.Float,
        nullable=False,
        default=1.0
    )

    description = db.Column(db.Text, nullable=True)

    examination = db.relationship(
        "Examination",
        backref=db.backref(
            "rubrics",
            cascade="all, delete-orphan"
        )
    )

class ExamSlot(db.Model):
    __tablename__ = "exam_slots"

    id = db.Column(db.Integer, primary_key=True)
    examination_id = db.Column(
        db.Integer,
        db.ForeignKey("examinations.id"),
        nullable=False
    )
    slot_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    capacity = db.Column(db.Integer, nullable=False, default=30)

    # Examiner who created the slot.
    examiner_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True
    )

    # Stored status: available / full / cancelled / completed.
    status = db.Column(
        db.String(20),
        nullable=False,
        default="available",
        server_default="available"
    )

    examination = db.relationship("Examination", backref="slots")
    examiner = db.relationship("User", foreign_keys=[examiner_id])

    @property
    def booked_count(self):
        return sum(
            1 for booking in self.bookings if booking.status == "booked"
        )

    @property
    def available_seats(self):
        return max(self.capacity - self.booked_count, 0)

    @property
    def display_status(self):
        """Status shown to users (always up to date)."""
        if self.status == "cancelled":
            return "Cancelled"

        slot_end = datetime.combine(self.slot_date, self.end_time)

        if slot_end <= datetime.now():
            return "Completed"

        if self.booked_count >= self.capacity:
            return "Full"

        return "Available"

    def sync_status(self):
        """Keep the stored status in step with the booking count.

        A slot is closed automatically (status "full") when capacity
        is reached and reopened if a seat becomes free again.
        """
        if self.status == "cancelled":
            return

        booked = db.session.scalar(
            db.select(db.func.count(ExamBooking.id)).where(
                ExamBooking.slot_id == self.id,
                ExamBooking.status == "booked"
            )
        ) or 0

        self.status = "full" if booked >= self.capacity else "available"


class ExamBooking(db.Model):
    __tablename__ = "exam_bookings"

    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "examination_id",
            name="uq_student_examination_booking"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    student_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )
    examination_id = db.Column(
        db.Integer,
        db.ForeignKey("examinations.id"),
        nullable=False
    )
    slot_id = db.Column(
        db.Integer,
        db.ForeignKey("exam_slots.id"),
        nullable=True
    )

    booked_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )
    status = db.Column(
        db.String(20),
        default="booked",
        nullable=False
    )

    student = db.relationship("User", backref="exam_bookings")
    examination = db.relationship("Examination", backref="bookings")
    slot = db.relationship("ExamSlot", backref="bookings")


class ExaminerAssignment(db.Model):
    __tablename__ = "examiner_assignments"

    __table_args__ = (
        UniqueConstraint(
            "examiner_id",
            "examination_id",
            name="uq_examiner_examination_assignment"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    examiner_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    examination_id = db.Column(
        db.Integer,
        db.ForeignKey("examinations.id"),
        nullable=False
    )

    assigned_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    examiner = db.relationship("User", backref="examiner_assignments")
    examination = db.relationship(
        "Examination",
        backref="examiner_assignments"
    )

class ExamResult(db.Model):
    __tablename__ = "exam_results"

    id = db.Column(db.Integer, primary_key=True)

    booking_id = db.Column(
        db.Integer,
        db.ForeignKey("exam_bookings.id"),
        unique=True,
        nullable=False
    )

    marks_obtained = db.Column(db.Float, nullable=False)
    feedback = db.Column(db.Text, nullable=True)

    status = db.Column(
        db.String(20),
        default="draft",
        nullable=False
    )

    published_at = db.Column(
        db.DateTime(timezone=True),
        nullable=True
    )

    booking = db.relationship(
        "ExamBooking",
        backref=db.backref("result", uselist=False)
    )


class ExamRubricAssessment(db.Model):
    __tablename__ = "exam_rubric_assessments"

    __table_args__ = (
        UniqueConstraint(
            "booking_id",
            "rubric_id",
            name="uq_booking_rubric_assessment"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    booking_id = db.Column(
        db.Integer,
        db.ForeignKey("exam_bookings.id"),
        nullable=False
    )

    rubric_id = db.Column(
        db.Integer,
        db.ForeignKey("exam_rubrics.id"),
        nullable=False
    )

    marks_obtained = db.Column(
        db.Float,
        nullable=False
    )

    remarks = db.Column(db.Text, nullable=True)

    assessed_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    assessed_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    booking = db.relationship(
        "ExamBooking",
        backref=db.backref(
            "rubric_assessments",
            cascade="all, delete-orphan"
        )
    )

    rubric = db.relationship(
        "ExamRubric",
        backref="assessments"
    )

    examiner = db.relationship(
        "User",
        foreign_keys=[assessed_by]
    )

class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    message = db.Column(db.String(255), nullable=False)

    category = db.Column(
        db.String(30),
        default="general",
        nullable=False
    )

    is_read = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    user = db.relationship("User", backref="notifications")

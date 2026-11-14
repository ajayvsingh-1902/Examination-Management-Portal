from datetime import date, datetime, timezone, timedelta
import math
from io import BytesIO
from xml.sax.saxutils import escape

from flask import (
    abort, current_app, flash, redirect, render_template, request, url_for, send_file
)
from flask_login import login_user, logout_user, current_user, login_required
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from sqlalchemy import select

from app.extensions import db
from app.models import (
    User, Course, Examination, ExamSlot, ExamBooking, ExamResult, Notification,
    ExaminerAssignment, ExamRubric, ExamRubricAssessment
)
from app.routes import main, role_required, search_conditions, booking_has_started


@main.route("/student")
@role_required("student")
def student_dashboard():
    now = datetime.now()

    # Examinations this student has already booked.
    my_bookings_list = db.session.scalars(
        db.select(ExamBooking).where(
            ExamBooking.student_id == current_user.id,
            ExamBooking.status == "booked"
        )
    ).all()

    booked_exam_ids = {
        booking.examination_id for booking in my_bookings_list
    }

    def slot_is_upcoming(slot):
        return datetime.combine(slot.slot_date, slot.end_time) > now

    # Upcoming examinations (booked, with a slot that has not passed).
    upcoming_bookings = sorted(
        (
            booking for booking in my_bookings_list
            if booking.slot is not None and slot_is_upcoming(booking.slot)
        ),
        key=lambda booking: (
            booking.slot.slot_date, booking.slot.start_time
        )
    )

    # Published examinations whose booking window is open.
    published_exams = db.session.scalars(
        db.select(Examination)
        .where(Examination.status == "published")
        .order_by(Examination.id.desc())
    ).all()

    available_exams = []
    available_slots = []

    for exam in published_exams:
        if exam.id in booked_exam_ids:
            continue

        if (
            exam.booking_opens_at is not None
            and now < exam.booking_opens_at
        ) or (
            exam.booking_closes_at is not None
            and now >= exam.booking_closes_at
        ):
            continue

        open_slots = [
            slot for slot in exam.slots
            if slot_is_upcoming(slot)
            and slot.booked_count < slot.capacity
        ]

        available_exams.append((exam, len(open_slots)))
        available_slots.extend(open_slots)

    available_slots.sort(
        key=lambda slot: (slot.slot_date, slot.start_time)
    )

    return render_template(
        "student_dashboard.html",
        available_exams=available_exams,
        available_slots=available_slots,
        upcoming_bookings=upcoming_bookings,
    )


@main.route("/student/examinations")
@role_required("student")
def student_examinations():
    # Read search and filter values.
    search_query = request.args.get("q", "").strip()
    course_id = request.args.get("course_id", type=int)
    examination_type = request.args.get("examination_type", "").strip()
    examiner_id = request.args.get("examiner_id", type=int)
    exam_date_text = request.args.get("exam_date", "").strip()

    selected_date = None

    if exam_date_text:
        try:
            selected_date = date.fromisoformat(exam_date_text)
        except ValueError:
            flash("Please select a valid examination date.", "warning")
            return redirect(url_for("main.student_examinations"))

    # Fetch only published examinations.
    examination_query = (
        db.select(Examination)
        .join(Course)
        .filter(Examination.status == "published")
    )

    # Search by examination title, course name, or course code.
    if search_query:
        search_pattern = f"%{search_query}%"

        examination_query = examination_query.where(
            db.or_(
                Examination.title.ilike(search_pattern),
                Course.name.ilike(search_pattern),
                Course.code.ilike(search_pattern)
            )
        )

    # Filter by course.
    if course_id:
        examination_query = examination_query.where(
            Examination.course_id == course_id
        )

    # Filter by examination type.
    allowed_types = [
        "Viva",
        "Practical",
        "Project Demo",
        "Assessment"
    ]

    if examination_type:
        if examination_type in allowed_types:
            examination_query = examination_query.where(
                Examination.examination_type == examination_type
            )
        else:
            flash("Please select a valid examination type.", "warning")
            return redirect(url_for("main.student_examinations"))

    # Filter by assigned examiner.
    if examiner_id:
        assigned_exam_ids = (
            db.select(ExaminerAssignment.examination_id)
            .where(ExaminerAssignment.examiner_id == examiner_id)
        )

        examination_query = examination_query.where(
            Examination.id.in_(assigned_exam_ids)
        )

    # Filter examinations by the selected slot date.
    if selected_date:
        matching_exam_ids = (
            db.select(ExamSlot.examination_id)
            .where(ExamSlot.slot_date == selected_date)
        )

        examination_query = examination_query.where(
            Examination.id.in_(matching_exam_ids)
        )

    examinations = db.session.execute(
        examination_query
        .distinct()
        .order_by(Examination.id.desc())
    ).scalars().all()

    # Load filter dropdown options.
    courses = db.session.execute(
        db.select(Course).order_by(Course.name)
    ).scalars().all()

    
    examiners = db.session.execute(
        db.select(User)
        .join(
            ExaminerAssignment,
            User.id == ExaminerAssignment.examiner_id
        )
        .join(
            Examination,
            Examination.id == ExaminerAssignment.examination_id
        )
        .where(
            User.role == "examiner",
            User.is_active.is_(True),
            User.is_approved.is_(True),
            Examination.status == "published"
        )
        .distinct()
        .order_by(User.name)
    ).scalars().all()

    # Find examinations already booked by this student.
    booked_ids = db.session.execute(
        db.select(ExamBooking.examination_id).filter_by(
            student_id=current_user.id,
            status="booked"
        )
    ).scalars().all()

    now = datetime.now()
    today = date.today()
    current_time = now.time()

    # Count active bookings for every slot.
    booking_counts = dict(
        db.session.execute(
            db.select(
                ExamBooking.slot_id,
                db.func.count(ExamBooking.id)
            )
            .filter(
                ExamBooking.status == "booked",
                ExamBooking.slot_id.is_not(None)
            )
            .group_by(ExamBooking.slot_id)
        ).all()
    )

    available_slots = {}

    for exam in examinations:
        available_slots[exam.id] = []

        # Check the booking window.
        opens_at = exam.booking_opens_at
        closes_at = exam.booking_closes_at

        if opens_at is not None and now < opens_at:
            continue

        if closes_at is not None and now >= closes_at:
            continue

        # Include only future slots with available capacity.
        for slot in exam.slots:
            if selected_date and slot.slot_date != selected_date:
                continue

            if slot.slot_date < today:
                continue

            if (
                slot.slot_date == today
                and slot.end_time <= current_time
            ):
                continue

            booked_count = booking_counts.get(slot.id, 0)

            if booked_count < slot.capacity:
                available_slots[exam.id].append(slot)

    return render_template(
        "student_examinations.html",
        examinations=examinations,
        booked_ids=booked_ids,
        available_slots=available_slots,
        booking_counts=booking_counts,
        search_query=search_query,
        courses=courses,
        examiners=examiners,
        selected_course_id=course_id,
        selected_examination_type=examination_type,
        selected_examiner_id=examiner_id,
        selected_exam_date=exam_date_text
    )


@main.route("/student/timetable")
@role_required("student")
def student_timetable():
    now = datetime.now()
    today = now.date()

    bookings = db.session.scalars(
        db.select(ExamBooking)
        .join(
            Examination,
            ExamBooking.examination_id == Examination.id
        )
        .where(
            ExamBooking.student_id == current_user.id,
            ExamBooking.status == "booked",
            Examination.status == "published",
        )
    ).all()

    timetable = []

    for booking in bookings:
        exam = booking.examination
        slot = booking.slot

        if slot is None:
            continue

        exam_start = datetime.combine(
            slot.slot_date,
            slot.start_time
        )

        timetable.append({
            "booking": booking,
            "exam": exam,
            "slot": slot,
            "upcoming": exam_start > now,
        })

    timetable.sort(
        key=lambda item: (
            item["slot"].slot_date,
            item["slot"].start_time
        )
    )

    return render_template(
        "student_timetable.html",
        timetable=timetable,
        today=today,
    )


@main.route("/student/notifications")
@role_required("student")
def student_notifications():
    from datetime import timezone, timedelta

    ist = timezone(timedelta(hours=5, minutes=30))

    notifications = db.session.scalars(
        db.select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
    ).all()

    for notification in notifications:
        created_at = notification.created_at

        if created_at is not None:
            # Treat naive database timestamps as UTC
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            notification.created_at_ist = created_at.astimezone(ist)

    unread_count = sum(
        1 for notification in notifications
        if not notification.is_read
    )

    return render_template(
        "student_notifications.html",
        notifications=notifications,
        unread_count=unread_count,
    )


@main.route(
    "/student/notifications/<int:notification_id>/read",
    methods=["POST"]
)
@role_required("student")
def mark_notification_read(notification_id):
    notification = db.session.scalar(
        db.select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
    )

    if notification is None:
        abort(404)

    notification.is_read = True
    db.session.commit()

    return redirect(url_for("main.student_notifications"))


@main.route(
    "/student/examinations/<int:examination_id>/book",
    methods=["POST"]
)
@role_required("student")
def book_examination(examination_id):
    examination = db.session.get(Examination, examination_id)

    if examination is None or examination.status != "published":
        abort(404)

    now = datetime.now()

    # Check booking window.
    if (
        examination.booking_opens_at is not None
        and now < examination.booking_opens_at
    ) or (
        examination.booking_closes_at is not None
        and now >= examination.booking_closes_at
    ):
        flash(
            "The booking window is not currently open.",
            "warning"
        )
        return redirect(url_for("main.student_examinations"))

    slot_id = request.form.get("slot_id", type=int)

    if slot_id is None:
        flash("Please select an exam slot.", "warning")
        return redirect(url_for("main.student_examinations"))

    slot = db.session.get(ExamSlot, slot_id)

    if slot is None or slot.examination_id != examination.id:
        flash("Please select a valid slot.", "danger")
        return redirect(url_for("main.student_examinations"))

    if slot.slot_date < date.today() or (
        slot.slot_date == date.today()
        and slot.end_time <= now.time()
    ):
        flash("This exam slot has already passed.", "warning")
        return redirect(url_for("main.student_examinations"))

    try:
        # SQLite: serialize capacity checks to prevent overselling seats.
        db.session.execute(db.text("BEGIN IMMEDIATE"))

        slot = db.session.get(ExamSlot, slot_id)
        examination = db.session.get(Examination, examination_id)

        if (
            slot is None
            or examination is None
            or slot.examination_id != examination.id
            or examination.status != "published"
        ):
            db.session.rollback()
            flash("This examination slot is no longer available.", "warning")
            return redirect(url_for("main.student_examinations"))

        now = datetime.now()

        if (
            examination.booking_opens_at is not None
            and now < examination.booking_opens_at
        ) or (
            examination.booking_closes_at is not None
            and now >= examination.booking_closes_at
        ):
            db.session.rollback()
            flash("The booking window is not currently open.", "warning")
            return redirect(url_for("main.student_examinations"))

        if slot.slot_date < date.today() or (
            slot.slot_date == date.today()
            and slot.end_time <= now.time()
        ):
            db.session.rollback()
            flash("This exam slot has already passed.", "warning")
            return redirect(url_for("main.student_examinations"))

        existing_booking = db.session.execute(
            db.select(ExamBooking).where(
                ExamBooking.student_id == current_user.id,
                ExamBooking.examination_id == examination.id
            )
        ).scalar_one_or_none()

        if existing_booking and existing_booking.status == "booked":
            db.session.rollback()
            flash(
                "You have already booked this examination.",
                "warning"
            )
            return redirect(url_for("main.student_examinations"))

        if existing_booking and existing_booking.result is not None:
            db.session.rollback()
            flash(
                "This booking already has an examination result "
                "and cannot be reactivated.",
                "warning"
            )
            return redirect(url_for("main.student_examinations"))

        booked_count = db.session.scalar(
            db.select(db.func.count(ExamBooking.id)).where(
                ExamBooking.slot_id == slot.id,
                ExamBooking.status == "booked"
            )
        ) or 0

        if booked_count >= slot.capacity:
            db.session.rollback()
            flash(
                "This exam slot is full. Please select another slot.",
                "warning"
            )
            return redirect(url_for("main.student_examinations"))

        if existing_booking:
            existing_booking.slot_id = slot.id
            existing_booking.status = "booked"
            existing_booking.booked_at = now
        else:
            existing_booking = ExamBooking(
                student_id=current_user.id,
                examination_id=examination.id,
                slot_id=slot.id,
                status="booked"
            )
            db.session.add(existing_booking)

        db.session.flush()

        # Automatically close the slot when capacity is reached.
        slot.sync_status()

        db.session.add(
            Notification(
                user_id=current_user.id,
                message=(
                    f"Your booking for '{examination.title}' was successful. "
                    f"Exam date: {slot.slot_date.strftime('%d %b %Y')}, "
                    f"{slot.start_time.strftime('%I:%M %p')} - "
                    f"{slot.end_time.strftime('%I:%M %p')}. "
                    f"Booking reference: #{existing_booking.id}."
                ),
                category="booking",
                is_read=False
            )
        )

        db.session.commit()

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Examination booking failed.")
        flash(
            "Booking could not be completed. Please try again.",
            "danger"
        )
        return redirect(url_for("main.student_examinations"))

    flash("Examination booked successfully!", "success")
    return redirect(url_for("main.my_bookings"))


@main.route("/student/my-bookings")
@role_required("student")
def my_bookings():
    bookings = db.session.execute(
        db.select(ExamBooking)
        .where(ExamBooking.student_id == current_user.id)
        .order_by(ExamBooking.booked_at.desc())
    ).scalars().all()

    ist = timezone(timedelta(hours=5, minutes=30))

    for booking in bookings:
        if booking.booked_at:
            timestamp = booking.booked_at

            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)

            booking.booking_time_ist = timestamp.astimezone(ist)

    return render_template(
        "my_bookings.html",
        bookings=bookings
    )


@main.route(
    "/student/my-bookings/<int:booking_id>/cancel",
    methods=["POST"]
)
@role_required("student")
def cancel_booking(booking_id):
    booking = db.session.execute(
        db.select(ExamBooking).where(
            ExamBooking.id == booking_id,
            ExamBooking.student_id == current_user.id
        )
    ).scalar_one_or_none()

    if booking is None:
        abort(404)

    if booking.status != "booked":
        flash("This booking cannot be cancelled.", "warning")
        return redirect(url_for("main.my_bookings"))

    # Protect both draft and published results.
    if booking.result is not None:
        flash(
            "This booking cannot be cancelled because an "
            "examination result already exists.",
            "warning"
        )
        return redirect(url_for("main.my_bookings"))

    try:
        booking.status = "cancelled"

        # Re-open the slot if the cancellation freed a seat.
        if booking.slot is not None:
            booking.slot.sync_status()

        db.session.add(
            Notification(
                user_id=current_user.id,
                message=(
                    f"Your booking for '{booking.examination.title}' "
                    "has been cancelled successfully."
                ),
                category="booking",
                is_read=False
            )
        )

        db.session.commit()

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Booking cancellation failed.")
        flash(
            "Cancellation could not be completed. Please try again.",
            "danger"
        )
        return redirect(url_for("main.my_bookings"))

    flash(
        "Your examination booking has been cancelled.",
        "success"
    )
    return redirect(url_for("main.my_bookings"))


@main.route("/student/results")
@role_required("student")
def student_results():
    results = db.session.scalars(
        db.select(ExamResult)
        .join(ExamBooking, ExamResult.booking_id == ExamBooking.id)
        .where(
            ExamBooking.student_id == current_user.id,
            ExamResult.status == "published"
        )
        .order_by(ExamResult.published_at.desc())
    ).all()

    result_details = []

    for result in results:
        max_marks = result.booking.examination.max_marks
        marks = result.marks_obtained

        percentage = (marks / max_marks * 100) if max_marks else 0

        result_details.append({
            "result": result,
            "percentage": round(percentage, 2),
            "passed": percentage >= 40
        })

    return render_template(
        "student_results.html",
        result_details=result_details
    )


@main.route("/student/results/<int:result_id>/download")
@role_required("student")
def download_student_result(result_id):
    result = db.session.get(ExamResult, result_id)

    # Ensure the result and its booking exist.
    if result is None or result.booking is None:
        abort(404)

    # Students can download only their own published results.
    if (
        result.status != "published"
        or result.booking.student_id != current_user.id
    ):
        abort(404)

    exam = result.booking.examination

    if exam is None:
        abort(404)

    max_marks = exam.max_marks
    marks = result.marks_obtained

    if max_marks is None or max_marks <= 0 or marks is None:
        abort(404)

    percentage = marks / max_marks * 100

    pdf_buffer = BytesIO()

    document = SimpleDocTemplate(
        pdf_buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            textColor=colors.HexColor("#17365D"),
            spaceAfter=16,
        )
    )

    story = [
        Paragraph(
            "EXAMINATION RESULT REPORT",
            styles["ReportTitle"]
        ),
        Paragraph(
            f"<b>Student:</b> {escape(current_user.name)}",
            styles["Normal"],
        ),
        Spacer(1, 8),
        Paragraph(
            f"<b>Examination:</b> {escape(exam.title)}",
            styles["Normal"],
        ),
        Spacer(1, 16),
    ]

    published_date = (
        result.published_at.strftime("%d %b %Y, %I:%M %p")
        if result.published_at
        else "Not available"
    )

    data = [
        ["Result Details", "Value"],
        ["Marks Obtained", f"{marks} / {max_marks}"],
        ["Percentage", f"{percentage:.2f}%"],
        ["Status", "Pass" if percentage >= 40 else "Fail"],
        ["Published Date", published_date],
    ]

    table = Table(data, colWidths=[55 * mm, 95 * mm])

    table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#17365D"),
                ),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                (
                    "BACKGROUND",
                    (0, 1),
                    (0, -1),
                    colors.HexColor("#EAF0F6"),
                ),
                ("PADDING", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )

    story.extend(
        [
            table,
            Spacer(1, 20),
            Paragraph(
                "Examiner Feedback",
                styles["Heading2"]
            ),
            Paragraph(
                escape(
                    result.feedback or "No feedback provided."
                ).replace("\n", "<br/>"),
                styles["Normal"],
            ),
        ]
    )

    document.build(story)
    pdf_buffer.seek(0)

    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"result_{result.id}.pdf",
    )


@main.route("/student/profile")
@login_required
@role_required("student")
def student_profile():
    return render_template("student_profile.html")


@main.route("/student/profile/edit", methods=["GET", "POST"])
@login_required
@role_required("student")
def edit_profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()

        form_data = {
            "name": name,
            "email": email,
        }

        if not name or not email:
            flash("Name and email are required.", "danger")
            return render_template("edit_profile.html", **form_data)

        if len(name) > 100 or len(email) > 150:
            flash("Name or email exceeds the allowed length.", "danger")
            return render_template("edit_profile.html", **form_data)

        if email.count("@") != 1 or "." not in email.rsplit("@", 1)[-1]:
            flash("Please enter a valid email address.", "danger")
            return render_template("edit_profile.html", **form_data)

        existing_user = db.session.execute(
            db.select(User).where(
                db.func.lower(User.email) == email,
                User.id != current_user.id
            )
        ).scalar_one_or_none()

        if existing_user:
            flash("This email address is already registered.", "danger")
            return render_template("edit_profile.html", **form_data)

        current_user.name = name
        current_user.email = email

        try:
            db.session.commit()
            flash("Your profile was updated successfully.", "success")
            return redirect(url_for("main.student_profile"))
        except Exception:
            db.session.rollback()
            flash("Could not update your profile. Please try again.", "danger")

    return render_template(
        "edit_profile.html",
        name=current_user.name,
        email=current_user.email,
    )

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


@main.route("/admin/bookings")
@role_required("admin")
def admin_bookings():
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()

    query = (
        db.select(ExamBooking)
        .join(User, ExamBooking.student_id == User.id)
        .join(Examination, ExamBooking.examination_id == Examination.id)
        .join(Course, Examination.course_id == Course.id)
        .outerjoin(ExamSlot, ExamBooking.slot_id == ExamSlot.id)
    )

    if search:
        query = query.filter(
            db.or_(
                *search_conditions(
                    search,
                    [
                        User.name,
                        User.email,
                        Examination.title,
                        Course.name,
                    ],
                    [ExamBooking.id, User.id, Examination.id],
                )
            )
        )

    if status in ("booked", "cancelled"):
        query = query.filter(ExamBooking.status == status)

    bookings = db.session.execute(
        query.order_by(ExamBooking.booked_at.desc())
    ).scalars().all()

    return render_template(
        "admin_bookings.html",
        bookings=bookings,
        search=search,
        status=status,
    )


@main.route("/admin/slots")
@role_required("admin")
def admin_exam_slots():
    slots = db.session.scalars(
        db.select(ExamSlot)
        .join(Examination)
        .order_by(
            ExamSlot.slot_date,
            ExamSlot.start_time
        )
    ).all()

    booking_counts = {}

    for slot in slots:
        booking_counts[slot.id] = (
            db.session.scalar(
                db.select(db.func.count(ExamBooking.id)).where(
                    ExamBooking.slot_id == slot.id,
                    ExamBooking.status == "booked"
                )
            ) or 0
        )

    return render_template(
        "admin_exam_slots.html",
        slots=slots,
        booking_counts=booking_counts
    )


@main.route("/admin/bookings/<int:booking_id>/reschedule", methods=["GET", "POST"])
@role_required("admin")
def admin_reschedule_booking(booking_id):
    booking = db.session.get(ExamBooking, booking_id)

    if booking is None:
        abort(404)

    if booking.status != "booked":
        flash("Only active bookings can be rescheduled.", "warning")
        return redirect(url_for("main.admin_bookings"))

    if booking.result is not None:
        flash(
            "A booking with an existing result cannot be rescheduled.",
            "warning"
        )
        return redirect(url_for("main.admin_bookings"))

    examination = booking.examination
    now = datetime.now()

    available_slots = db.session.scalars(
        db.select(ExamSlot)
        .where(ExamSlot.examination_id == examination.id)
        .order_by(ExamSlot.slot_date, ExamSlot.start_time)
    ).all()

    valid_slots = []

    for slot in available_slots:
        if slot.id == booking.slot_id:
            continue

        if slot.slot_date < now.date():
            continue

        if (
            slot.slot_date == now.date()
            and slot.end_time <= now.time()
        ):
            continue

        occupied = db.session.scalar(
            db.select(db.func.count())
            .select_from(ExamBooking)
            .where(
                ExamBooking.slot_id == slot.id,
                ExamBooking.status == "booked",
                ExamBooking.id != booking.id,
            )
        ) or 0

        if occupied < slot.capacity:
            valid_slots.append(slot)

    if request.method == "POST":
        slot_id = request.form.get("slot_id", type=int)

        selected_slot = (
            db.session.get(ExamSlot, slot_id)
            if slot_id is not None
            else None
        )

        if (
            selected_slot is None
            or selected_slot.examination_id != examination.id
            or selected_slot not in valid_slots
        ):
            flash(
                "Please select a valid slot with available capacity.",
                "danger"
            )
            return redirect(
                url_for(
                    "main.admin_reschedule_booking",
                    booking_id=booking.id
                )
            )

        # Recheck capacity immediately before saving.
        occupied_now = db.session.scalar(
            db.select(db.func.count())
            .select_from(ExamBooking)
            .where(
                ExamBooking.slot_id == selected_slot.id,
                ExamBooking.status == "booked",
                ExamBooking.id != booking.id,
            )
        ) or 0

        if occupied_now >= selected_slot.capacity:
            flash(
                "That slot has just become full. Please select another slot.",
                "warning"
            )
            return redirect(
                url_for(
                    "main.admin_reschedule_booking",
                    booking_id=booking.id
                )
            )

        old_slot = booking.slot

        if old_slot is None or old_slot.id == selected_slot.id:
            flash("No schedule change was made.", "info")
            return redirect(url_for("main.admin_bookings"))

        old_date = old_slot.slot_date.strftime("%d %b %Y")
        old_time = old_slot.start_time.strftime("%I:%M %p")
        new_date = selected_slot.slot_date.strftime("%d %b %Y")
        new_time = selected_slot.start_time.strftime("%I:%M %p")

        notification = Notification(
            user_id=booking.student_id,
            category="schedule_change",
            is_read=False,
            message=(
                f"Your examination '{examination.title}' has been rescheduled. "
                f"Previous slot: {old_date} at {old_time}. "
                f"New slot: {new_date} at {new_time}. "
                f"Booking reference: #{booking.id}."
            )
        )

        try:
            booking.slot_id = selected_slot.id
            old_slot.sync_status()
            selected_slot.sync_status()
            db.session.add(notification)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash(
                "Could not reschedule the booking. Please try again.",
                "danger"
            )
            return redirect(
                url_for(
                    "main.admin_reschedule_booking",
                    booking_id=booking.id
                )
            )

        flash(
            "Booking rescheduled and student notified successfully.",
            "success"
        )
        return redirect(url_for("main.admin_bookings"))

    return render_template(
        "admin_reschedule_booking.html",
        booking=booking,
        valid_slots=valid_slots,
    )

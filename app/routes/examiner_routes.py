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


@main.route("/examiner")
@role_required("examiner")
def examiner_dashboard():
    assignments = db.session.scalars(
        db.select(ExaminerAssignment).filter_by(
            examiner_id=current_user.id
        )
    ).all()

    examination_ids = [
        assignment.examination_id
        for assignment in assignments
    ]

    total_examinations = len(set(examination_ids))

    total_slots = 0
    total_bookings = 0
    pending_evaluations = 0

    if examination_ids:
        total_slots = db.session.scalar(
            db.select(db.func.count(ExamSlot.id)).where(
                ExamSlot.examination_id.in_(examination_ids)
            )
        ) or 0

        total_bookings = db.session.scalar(
            db.select(db.func.count(ExamBooking.id))
            .where(
                ExamBooking.examination_id.in_(examination_ids),
                ExamBooking.status == "booked"
            )
        ) or 0

        pending_evaluations = db.session.scalar(
            db.select(db.func.count(ExamBooking.id))
            .outerjoin(
                ExamResult,
                ExamResult.booking_id == ExamBooking.id
            )
            .where(
                ExamBooking.examination_id.in_(examination_ids),
                ExamBooking.status == "booked",
                db.or_(
                    ExamResult.id.is_(None),
                    ExamResult.status != "published"
                )
            )
        ) or 0

    return render_template(
        "examiner_dashboard.html",
        total_examinations=total_examinations,
        total_slots=total_slots,
        total_bookings=total_bookings,
        pending_evaluations=pending_evaluations
    )


@main.route("/admin/assignments", methods=["GET", "POST"])
@role_required("admin")
def manage_examiner_assignments():
    if request.method == "POST":
        examiner_id = request.form.get("examiner_id", "").strip()
        examination_id = request.form.get("examination_id", "").strip()

        try:
            examiner_id = int(examiner_id)
            examination_id = int(examination_id)
        except (ValueError, TypeError):
            flash("Please select a valid examiner and examination.", "danger")
            return redirect(url_for("main.manage_examiner_assignments"))

        examiner = db.session.get(User, examiner_id)
        examination = db.session.get(Examination, examination_id)

        if (
            examiner is None
            or examiner.role != "examiner"
            or not examiner.is_approved
            or not examiner.is_active
        ):
            flash("Select an active, approved examiner.", "danger")
            return redirect(url_for("main.manage_examiner_assignments"))

        if examination is None:
            flash("Select a valid examination.", "danger")
            return redirect(url_for("main.manage_examiner_assignments"))

        existing = db.session.scalar(
            db.select(ExaminerAssignment).where(
                ExaminerAssignment.examiner_id == examiner_id,
                ExaminerAssignment.examination_id == examination_id
            )
        )

        if existing:
            flash("This examination is already assigned to that examiner.", "warning")
            return redirect(url_for("main.manage_examiner_assignments"))

        assignment = ExaminerAssignment(
            examiner_id=examiner_id,
            examination_id=examination_id
        )

        try:
            db.session.add(assignment)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Assignment could not be saved. Please try again.", "danger")
            return redirect(url_for("main.manage_examiner_assignments"))

        flash("Examination assigned successfully!", "success")
        return redirect(url_for("main.manage_examiner_assignments"))

    examiners = db.session.scalars(
        db.select(User)
        .where(
            User.role == "examiner",
            User.is_approved.is_(True),
            User.is_active.is_(True)
        )
        .order_by(User.name)
    ).all()

    examinations = db.session.scalars(
        db.select(Examination).order_by(Examination.title)
    ).all()

    assignments = db.session.scalars(
        db.select(ExaminerAssignment)
        .order_by(ExaminerAssignment.assigned_at.desc())
    ).all()

    return render_template(
        "manage_examiner_assignments.html",
        examiners=examiners,
        examinations=examinations,
        assignments=assignments
    )


@main.route(
    "/admin/assignments/<int:assignment_id>/reassign",
    methods=["GET", "POST"]
)
@role_required("admin")
def reassign_examiner(assignment_id):
    assignment = db.session.get(ExaminerAssignment, assignment_id)

    if assignment is None:
        abort(404)

    examination = assignment.examination

    if request.method == "POST":
        examiner_id = request.form.get("examiner_id", "").strip()

        try:
            examiner_id = int(examiner_id)
        except (ValueError, TypeError):
            flash("Please select a valid examiner.", "danger")
            return redirect(
                url_for("main.reassign_examiner",
                        assignment_id=assignment.id)
            )

        new_examiner = db.session.get(User, examiner_id)

        if (
            new_examiner is None
            or new_examiner.role != "examiner"
            or not new_examiner.is_active
            or not new_examiner.is_approved
        ):
            flash(
                "Select an active, approved examiner.",
                "danger"
            )
            return redirect(
                url_for("main.reassign_examiner",
                        assignment_id=assignment.id)
            )

        if new_examiner.id == assignment.examiner_id:
            flash(
                "This examiner is already assigned.",
                "warning"
            )
            return redirect(
                url_for("main.reassign_examiner",
                        assignment_id=assignment.id)
            )

        duplicate = db.session.scalar(
            db.select(ExaminerAssignment).where(
                ExaminerAssignment.examination_id == examination.id,
                ExaminerAssignment.examiner_id == new_examiner.id
            )
        )

        if duplicate:
            flash(
                "The selected examiner is already assigned "
                "to this examination.",
                "warning"
            )
            return redirect(
                url_for("main.reassign_examiner",
                        assignment_id=assignment.id)
            )

        active_booking = db.session.scalar(
            db.select(ExamBooking.id)
            .join(
                ExamBooking.examination,
            )
            .where(
                ExamBooking.examination_id == examination.id,
                ExamBooking.status == "booked"
            )
            .limit(1)
        )

        unpublished_result = db.session.scalar(
            db.select(ExamResult.id)
            .join(ExamBooking)
            .where(
                ExamBooking.examination_id == examination.id,
                ExamResult.status != "published"
            )
            .limit(1)
        )

        if active_booking or unpublished_result:
            flash(
                "Reassignment is blocked while active bookings "
                "or unpublished results exist. Resolve them first.",
                "warning"
            )
            return redirect(
                url_for("main.manage_examiner_assignments")
            )

        old_examiner_name = assignment.examiner.name

        try:
            assignment.examiner_id = new_examiner.id
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash(
                "Examiner reassignment failed. Please try again.",
                "danger"
            )
            return redirect(
                url_for("main.manage_examiner_assignments")
            )

        flash(
            f"Examiner changed from {old_examiner_name} "
            f"to {new_examiner.name}.",
            "success"
        )
        return redirect(
            url_for("main.manage_examiner_assignments")
        )

    examiners = db.session.scalars(
        db.select(User)
        .where(
            User.role == "examiner",
            User.is_approved.is_(True),
            User.is_active.is_(True),
            User.id != assignment.examiner_id
        )
        .order_by(User.name)
    ).all()

    return render_template(
        "reassign_examiner.html",
        assignment=assignment,
        examination=examination,
        examiners=examiners
    )


@main.route(
    "/admin/assignments/<int:assignment_id>/delete",
    methods=["POST"]
)
@role_required("admin")
def delete_examiner_assignment(assignment_id):
    assignment = db.session.get(ExaminerAssignment, assignment_id)

    if assignment is None:
        abort(404)

    examination_id = assignment.examination_id
    examiner_id = assignment.examiner_id

    # Protect active bookings that belong to this examination.
    active_booking_count = db.session.scalar(
        db.select(db.func.count())
        .select_from(ExamBooking)
        .join(
            Examination,
            Examination.id == ExamBooking.examination_id
        )
        .where(
            ExamBooking.examination_id == examination_id,
            ExamBooking.status == "booked"
        )
    ) or 0

    if active_booking_count:
        flash(
            "This assignment cannot be removed while active bookings "
            "exist for the examination. Reschedule or resolve those "
            "bookings first.",
            "warning"
        )
        return redirect(url_for("main.manage_examiner_assignments"))

    # Protect results that have not yet been published.
    draft_result_count = db.session.scalar(
        db.select(db.func.count())
        .select_from(ExamResult)
        .join(
            ExamBooking,
            ExamBooking.id == ExamResult.booking_id
        )
        .where(
            ExamBooking.examination_id == examination_id,
            ExamResult.status != "published"
        )
    ) or 0

    if draft_result_count:
        flash(
            "This assignment cannot be removed while unpublished "
            "results exist for the examination.",
            "warning"
        )
        return redirect(url_for("main.manage_examiner_assignments"))

    try:
        db.session.delete(assignment)
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Assignment could not be removed.", "danger")
        return redirect(url_for("main.manage_examiner_assignments"))

    flash("Examiner assignment removed.", "success")
    return redirect(url_for("main.manage_examiner_assignments"))


@main.route("/examiner/slots", methods=["GET", "POST"])
@role_required("examiner")
def manage_exam_slots():
    now = datetime.now()

    # Get examination IDs assigned to the logged-in examiner.
    assigned_exam_ids = db.session.scalars(
        db.select(ExaminerAssignment.examination_id).where(
            ExaminerAssignment.examiner_id == current_user.id
        )
    ).all()

    if request.method == "POST":
        examination_id = request.form.get("examination_id", "").strip()
        slot_date_text = request.form.get("slot_date", "").strip()
        start_time_text = request.form.get("start_time", "").strip()
        end_time_text = request.form.get("end_time", "").strip()
        capacity_text = request.form.get("capacity", "").strip()

        try:
            examination_id = int(examination_id)
            capacity = int(capacity_text)
            slot_date = datetime.strptime(
                slot_date_text, "%Y-%m-%d"
            ).date()
            start_time = datetime.strptime(
                start_time_text, "%H:%M"
            ).time()
            end_time = datetime.strptime(
                end_time_text, "%H:%M"
            ).time()
        except (ValueError, TypeError):
            flash("Please enter valid slot details.", "danger")
            return redirect(url_for("main.manage_exam_slots"))

        # Only allow examinations assigned to this examiner.
        if examination_id not in assigned_exam_ids:
            flash(
                "You can manage slots only for examinations assigned to you.",
                "danger"
            )
            return redirect(url_for("main.manage_exam_slots"))

        examination = db.session.get(Examination, examination_id)

        if examination is None:
            flash("Please select a valid examination.", "danger")
            return redirect(url_for("main.manage_exam_slots"))

        # Enforce the admin-configured slot-creation window.
        if (
            examination.slot_creation_opens_at is not None
            and now < examination.slot_creation_opens_at
        ):
            flash(
                "Slot creation has not opened for this examination yet.",
                "warning"
            )
            return redirect(url_for("main.manage_exam_slots"))

        if (
            examination.slot_creation_closes_at is not None
            and now >= examination.slot_creation_closes_at
        ):
            flash(
                "The slot-creation window for this examination has closed.",
                "warning"
            )
            return redirect(url_for("main.manage_exam_slots"))

        if slot_date < date.today():
            flash("Exam slot date cannot be in the past.", "danger")
            return redirect(url_for("main.manage_exam_slots"))

        if end_time <= start_time:
            flash("End time must be later than start time.", "danger")
            return redirect(url_for("main.manage_exam_slots"))

        if capacity < 1 or capacity > 10000:
            flash(
                "Capacity must be between 1 and 10000 seats.",
                "danger"
            )
            return redirect(url_for("main.manage_exam_slots"))

        # Prevent overlapping slots for the same examination.
        overlapping_slot = db.session.scalars(
            db.select(ExamSlot).where(
                ExamSlot.examination_id == examination_id,
                ExamSlot.slot_date == slot_date,
                ExamSlot.start_time < end_time,
                ExamSlot.end_time > start_time
            )
        ).first()

        if overlapping_slot:
            flash(
                "This slot overlaps with an existing slot for "
                "the same examination. Choose another time.",
                "danger"
            )
            return redirect(url_for("main.manage_exam_slots"))

        exam_slot = ExamSlot(
            examination_id=examination_id,
            slot_date=slot_date,
            start_time=start_time,
            end_time=end_time,
            capacity=capacity,
            examiner_id=current_user.id,
            status="available"
        )

        try:
            db.session.add(exam_slot)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash(
                "The slot could not be saved. Please try again.",
                "danger"
            )
            return redirect(url_for("main.manage_exam_slots"))

        flash("Exam slot created successfully!", "success")
        return redirect(url_for("main.manage_exam_slots"))

    # Display only assigned examinations in the dropdown.
    examinations = db.session.scalars(
        db.select(Examination)
        .where(Examination.id.in_(assigned_exam_ids))
        .order_by(Examination.title)
    ).all()

    # Display only slots for assigned examinations.
    slots = db.session.scalars(
        db.select(ExamSlot)
        .where(ExamSlot.examination_id.in_(assigned_exam_ids))
        .order_by(ExamSlot.slot_date, ExamSlot.start_time)
    ).all()

    # Tell the template whether slot creation is currently allowed.
    slot_creation_allowed = {}
    for examination in examinations:
        slot_creation_allowed[examination.id] = (
            (
                examination.slot_creation_opens_at is None
                or now >= examination.slot_creation_opens_at
            )
            and (
                examination.slot_creation_closes_at is None
                or now < examination.slot_creation_closes_at
            )
        )

    return render_template(
        "manage_exam_slots.html",
        examinations=examinations,
        slots=slots,
        slot_creation_allowed=slot_creation_allowed,
        now=now
    )


@main.route("/examiner/assessments")
@role_required("examiner")
def examiner_assessments():
    assigned_exam_ids = db.session.scalars(
        db.select(ExaminerAssignment.examination_id).where(
            ExaminerAssignment.examiner_id == current_user.id
        )
    ).all()

    bookings = []

    if assigned_exam_ids:
        bookings = db.session.scalars(
            db.select(ExamBooking)
            .where(
                ExamBooking.examination_id.in_(assigned_exam_ids),
                ExamBooking.status == "booked"
            )
            .order_by(ExamBooking.id.desc())
        ).all()

    return render_template(
        "examiner_assessments.html",
        bookings=bookings
    )


@main.route("/examiner/slots/<int:slot_id>/edit", methods=["GET", "POST"])
@role_required("examiner")
def edit_exam_slot(slot_id):
    slot = db.session.get(ExamSlot, slot_id)

    if slot is None:
        abort(404)

    now = datetime.now()

    # Verify assignment to the slot's current examination.
    is_assigned = db.session.scalar(
        db.select(ExaminerAssignment.id).where(
            ExaminerAssignment.examiner_id == current_user.id,
            ExaminerAssignment.examination_id == slot.examination_id
        )
    )

    if is_assigned is None:
        abort(403)

    # Do not edit slots with active bookings.
    booking_count = db.session.scalar(
        db.select(db.func.count())
        .select_from(ExamBooking)
        .where(
            ExamBooking.slot_id == slot.id,
            ExamBooking.status == "booked"
        )
    ) or 0

    if booking_count:
        flash(
            "This slot cannot be edited because bookings are linked to it.",
            "warning"
        )
        return redirect(url_for("main.manage_exam_slots"))

    current_exam = db.session.get(Examination, slot.examination_id)

    if current_exam is None:
        abort(404)

    # Slots can only be updated before student booking starts.
    if booking_has_started(current_exam, now):
        flash(
            "Student booking has already started for this examination, "
            "so its slots can no longer be edited.",
            "warning"
        )
        return redirect(url_for("main.manage_exam_slots"))

    # Editing is also subject to the current examination's window.
    if (
        current_exam.slot_creation_opens_at is not None
        and now < current_exam.slot_creation_opens_at
    ) or (
        current_exam.slot_creation_closes_at is not None
        and now >= current_exam.slot_creation_closes_at
    ):
        flash(
            "This examination's slot-creation window is closed. "
            "The slot cannot be edited.",
            "warning"
        )
        return redirect(url_for("main.manage_exam_slots"))

    examinations = db.session.scalars(
        db.select(Examination)
        .join(
            ExaminerAssignment,
            ExaminerAssignment.examination_id == Examination.id
        )
        .where(ExaminerAssignment.examiner_id == current_user.id)
        .order_by(Examination.title)
    ).all()

    if request.method == "POST":
        examination_id_text = request.form.get(
            "examination_id", ""
        ).strip()
        slot_date_text = request.form.get("slot_date", "").strip()
        start_time_text = request.form.get("start_time", "").strip()
        end_time_text = request.form.get("end_time", "").strip()
        capacity_text = request.form.get("capacity", "").strip()

        try:
            examination_id = int(examination_id_text)
            slot_date = datetime.strptime(
                slot_date_text, "%Y-%m-%d"
            ).date()
            start_time = datetime.strptime(
                start_time_text, "%H:%M"
            ).time()
            end_time = datetime.strptime(
                end_time_text, "%H:%M"
            ).time()
            capacity = int(capacity_text)
        except (ValueError, TypeError):
            flash("Please enter valid slot details.", "danger")
            return redirect(
                url_for("main.edit_exam_slot", slot_id=slot.id)
            )

        examination = db.session.get(Examination, examination_id)

        if examination is None:
            flash("Please select a valid examination.", "danger")
            return redirect(
                url_for("main.edit_exam_slot", slot_id=slot.id)
            )

        new_assignment = db.session.scalar(
            db.select(ExaminerAssignment.id).where(
                ExaminerAssignment.examiner_id == current_user.id,
                ExaminerAssignment.examination_id == examination_id
            )
        )

        if new_assignment is None:
            abort(403)

        # Check the selected examination's creation window too.
        if (
            examination.slot_creation_opens_at is not None
            and now < examination.slot_creation_opens_at
        ) or (
            examination.slot_creation_closes_at is not None
            and now >= examination.slot_creation_closes_at
        ):
            flash(
                "The selected examination's slot-creation window is closed.",
                "warning"
            )
            return redirect(
                url_for("main.edit_exam_slot", slot_id=slot.id)
            )

        if slot_date < date.today():
            flash("Exam slot date cannot be in the past.", "danger")
            return redirect(
                url_for("main.edit_exam_slot", slot_id=slot.id)
            )

        if end_time <= start_time:
            flash("End time must be later than start time.", "danger")
            return redirect(
                url_for("main.edit_exam_slot", slot_id=slot.id)
            )

        if capacity < 1 or capacity > 10000:
            flash(
                "Capacity must be between 1 and 10000 seats.",
                "danger"
            )
            return redirect(
                url_for("main.edit_exam_slot", slot_id=slot.id)
            )

        overlapping_slot = db.session.scalars(
            db.select(ExamSlot).where(
                ExamSlot.id != slot.id,
                ExamSlot.examination_id == examination_id,
                ExamSlot.slot_date == slot_date,
                ExamSlot.start_time < end_time,
                ExamSlot.end_time > start_time
            )
        ).first()

        if overlapping_slot:
            flash(
                "This slot overlaps with another slot for the same "
                "examination. Choose another time.",
                "danger"
            )
            return redirect(
                url_for("main.edit_exam_slot", slot_id=slot.id)
            )

        slot.examination_id = examination_id
        slot.slot_date = slot_date
        slot.start_time = start_time
        slot.end_time = end_time
        slot.capacity = capacity

        if slot.examiner_id is None:
            slot.examiner_id = current_user.id

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash(
                "The slot could not be updated. Please try again.",
                "danger"
            )
            return redirect(
                url_for("main.edit_exam_slot", slot_id=slot.id)
            )

        flash("Exam slot updated successfully!", "success")
        return redirect(url_for("main.manage_exam_slots"))

    return render_template(
        "edit_exam_slot.html",
        slot=slot,
        examinations=examinations
    )


@main.route("/examiner/slots/<int:slot_id>/delete", methods=["POST"])
@role_required("examiner")
def delete_exam_slot(slot_id):
    slot = db.session.get(ExamSlot, slot_id)

    if slot is None:
        abort(404)

    is_assigned = db.session.scalar(
        db.select(ExaminerAssignment.id).where(
            ExaminerAssignment.examiner_id == current_user.id,
            ExaminerAssignment.examination_id == slot.examination_id
        )
    )

    if is_assigned is None:
        abort(403)

    
    booking_count = db.session.scalar(
        db.select(db.func.count())
        .select_from(ExamBooking)
        .where(
            ExamBooking.slot_id == slot.id,
            ExamBooking.status == "booked"
        )
    ) or 0

    result_count = db.session.scalar(
        db.select(db.func.count())
        .select_from(ExamBooking)
        .join(
            ExamResult,
            ExamResult.booking_id == ExamBooking.id
        )
        .where(ExamBooking.slot_id == slot.id)
    ) or 0


    if booking_count or result_count:
        flash(
            "This slot cannot be deleted because active bookings "
            "or examination results are linked to it.",
            "warning"
        )
        return redirect(url_for("main.manage_exam_slots"))

    examination = db.session.get(Examination, slot.examination_id)

    if examination is None:
        abort(404)

    now = datetime.now()

    if (
        examination.slot_creation_opens_at is not None
        and now < examination.slot_creation_opens_at
    ) or (
        examination.slot_creation_closes_at is not None
        and now >= examination.slot_creation_closes_at
    ):
        flash(
            "This examination's slot-creation window is closed. "
            "The slot cannot be deleted.",
            "warning"
        )
        return redirect(url_for("main.manage_exam_slots"))

    if booking_has_started(examination, now):
        flash(
            "Student booking has already started for this examination, "
            "so its slots can no longer be removed.",
            "warning"
        )
        return redirect(url_for("main.manage_exam_slots"))

    try:
        db.session.delete(slot)
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash(
            "The slot could not be deleted. Please try again.",
            "danger"
        )
        return redirect(url_for("main.manage_exam_slots"))

    flash("Exam slot deleted successfully!", "success")
    return redirect(url_for("main.manage_exam_slots"))


@main.route("/examiner/results")
@role_required("examiner")
def examiner_results():
    bookings = db.session.execute(
        db.select(ExamBooking)
        .join(
            Examination,
            ExamBooking.examination_id == Examination.id
        )
        .filter(ExamBooking.status == "booked")
        .order_by(Examination.title, ExamBooking.student_id)
    ).scalars().all()

    return render_template(
        "examiner_results.html",
        bookings=bookings
    )


@main.route(
    "/examiner/results/<int:booking_id>",
    methods=["GET", "POST"]
)
@role_required("examiner")
def enter_exam_result(booking_id):
    booking = db.session.get(ExamBooking, booking_id)

    if booking is None or booking.status != "booked":
        abort(404)

    examination = booking.examination

    # Only an examiner assigned to this examination may assess it.
    assignment = db.session.scalar(
        db.select(ExaminerAssignment.id).where(
            ExaminerAssignment.examiner_id == current_user.id,
            ExaminerAssignment.examination_id == examination.id
        )
    )

    if assignment is None:
        abort(403)

    result = booking.result

    rubrics = db.session.scalars(
        db.select(ExamRubric)
        .where(ExamRubric.examination_id == examination.id)
        .order_by(ExamRubric.id)
    ).all()

    assessments = {
        assessment.rubric_id: assessment
        for assessment in booking.rubric_assessments
    }

    if request.method == "POST":
        if result is not None and result.status == "published":
            flash(
                "This result is already published and cannot be edited here.",
                "warning"
            )
            return redirect(url_for("main.examiner_results"))

        if not rubrics:
            flash(
                "The administrator must create rubric criteria before assessment.",
                "warning"
            )
            return redirect(url_for("main.examiner_results"))

        feedback = request.form.get("feedback", "").strip()

        if len(feedback) > 5000:
            flash("Feedback must be 5000 characters or fewer.", "danger")
            return render_template(
                "enter_result.html",
                booking=booking,
                examination=examination,
                result=result,
                rubrics=rubrics,
                assessments=assessments
            )

        entered_assessments = []
        total_marks = 0.0

        for rubric in rubrics:
            raw_marks = request.form.get(
                f"rubric_marks_{rubric.id}", ""
            ).strip()

            remarks = request.form.get(
                f"rubric_remarks_{rubric.id}", ""
            ).strip()

            try:
                marks = float(raw_marks)
            except (ValueError, TypeError):
                flash(
                    f"Enter valid marks for '{rubric.criterion_name}'.",
                    "danger"
                )
                return render_template(
                    "enter_result.html",
                    booking=booking,
                    examination=examination,
                    result=result,
                    rubrics=rubrics,
                    assessments=assessments
                )

            if (
                not math.isfinite(marks)
                or marks < 0
                or marks > rubric.max_marks
            ):
                flash(
                    f"Marks for '{rubric.criterion_name}' must be between "
                    f"0 and {rubric.max_marks}.",
                    "danger"
                )
                return render_template(
                    "enter_result.html",
                    booking=booking,
                    examination=examination,
                    result=result,
                    rubrics=rubrics,
                    assessments=assessments
                )

            if len(remarks) > 2000:
                flash(
                    f"Remarks for '{rubric.criterion_name}' must be "
                    "2000 characters or fewer.",
                    "danger"
                )
                return render_template(
                    "enter_result.html",
                    booking=booking,
                    examination=examination,
                    result=result,
                    rubrics=rubrics,
                    assessments=assessments
                )

            entered_assessments.append((rubric, marks, remarks))
            total_marks += marks

        if total_marks > examination.max_marks:
            flash(
                "The total rubric marks exceed the examination's maximum marks. "
                "Please ask the administrator to review the rubric configuration.",
                "danger"
            )
            return render_template(
                "enter_result.html",
                booking=booking,
                examination=examination,
                result=result,
                rubrics=rubrics,
                assessments=assessments
            )

        try:
            if result is None:
                result = ExamResult(
                    booking_id=booking.id,
                    marks_obtained=total_marks,
                    feedback=feedback or None,
                    status="draft"
                )
                db.session.add(result)
            else:
                result.marks_obtained = total_marks
                result.feedback = feedback or None
                result.status = "draft"
                result.published_at = None

            for rubric, marks, remarks in entered_assessments:
                assessment = assessments.get(rubric.id)

                if assessment is None:
                    assessment = ExamRubricAssessment(
                        booking_id=booking.id,
                        rubric_id=rubric.id,
                        assessed_by=current_user.id,
                        marks_obtained=marks,
                        remarks=remarks or None
                    )
                    db.session.add(assessment)
                else:
                    assessment.marks_obtained = marks
                    assessment.remarks = remarks or None
                    assessment.assessed_by = current_user.id
                    assessment.assessed_at = datetime.now(timezone.utc)

            db.session.commit()

        except Exception:
            db.session.rollback()
            flash(
                "The assessment could not be saved. Please try again.",
                "danger"
            )
            return redirect(
                url_for(
                    "main.enter_exam_result",
                    booking_id=booking.id
                )
            )

        flash(
            "Rubric assessments and total marks saved as a draft.",
            "success"
        )
        return redirect(url_for("main.examiner_results"))

    return render_template(
        "enter_result.html",
        booking=booking,
        examination=examination,
        result=result,
        rubrics=rubrics,
        assessments=assessments
    )


@main.route(
    "/examiner/results/<int:result_id>/publish",
    methods=["POST"]
)
@role_required("examiner")
def publish_exam_result(result_id):
    result = db.session.get(ExamResult, result_id)

    if result is None:
        abort(404)

    booking = result.booking

    if booking is None or booking.status != "booked":
        flash(
            "A result can only be published for an active booking.",
            "warning"
        )
        return redirect(url_for("main.examiner_results"))

    examination = booking.examination

    # Only an assigned examiner may publish this result.
    assignment = db.session.scalar(
        db.select(ExaminerAssignment.id).where(
            ExaminerAssignment.examiner_id == current_user.id,
            ExaminerAssignment.examination_id == examination.id
        )
    )

    if assignment is None:
        abort(403)

    # Prevent duplicate publication.
    if result.status == "published":
        flash(
            "This result has already been published.",
            "info"
        )
        return redirect(url_for("main.examiner_results"))

    # Require rubric criteria.
    rubrics = db.session.scalars(
        db.select(ExamRubric).where(
            ExamRubric.examination_id == examination.id
        ).order_by(ExamRubric.id)
    ).all()

    if not rubrics:
        flash(
            "The administrator must configure rubric criteria "
            "before publication.",
            "warning"
        )
        return redirect(url_for("main.examiner_results"))

    required_rubric_ids = {rubric.id for rubric in rubrics}

    # Load all saved assessments for this booking.
    assessments = db.session.scalars(
        db.select(ExamRubricAssessment).where(
            ExamRubricAssessment.booking_id == booking.id
        )
    ).all()

    assessment_map = {
        assessment.rubric_id: assessment
        for assessment in assessments
    }

    # Ensure every current rubric has exactly one assessment.
    if (
        len(assessments) != len(required_rubric_ids)
        or set(assessment_map) != required_rubric_ids
    ):
        flash(
            "Complete all rubric assessments before publishing this result.",
            "warning"
        )
        return redirect(
            url_for(
                "main.enter_exam_result",
                booking_id=booking.id
            )
        )

    # Validate the saved total marks.
    maximum = examination.max_marks
    marks = result.marks_obtained

    if (
        maximum is None
        or maximum <= 0
        or marks is None
        or not math.isfinite(marks)
        or marks < 0
        or marks > maximum
    ):
        flash(
            "The saved marks are invalid. Edit the draft before publishing.",
            "danger"
        )
        return redirect(
            url_for(
                "main.enter_exam_result",
                booking_id=booking.id
            )
        )

    # Validate individual rubric scores and calculate their total.
    rubric_map = {rubric.id: rubric for rubric in rubrics}
    calculated_total = 0.0

    for assessment in assessments:
        rubric = rubric_map.get(assessment.rubric_id)
        score = assessment.marks_obtained

        if (
            rubric is None
            or score is None
            or not math.isfinite(score)
            or score < 0
            or score > rubric.max_marks
        ):
            flash(
                "A rubric assessment contains invalid marks. "
                "Correct it before publishing.",
                "danger"
            )
            return redirect(
                url_for(
                    "main.enter_exam_result",
                    booking_id=booking.id
                )
            )

        calculated_total += score

    # Ensure the saved total matches the individual rubric scores.
    if not math.isclose(
        marks,
        calculated_total,
        rel_tol=1e-9,
        abs_tol=1e-6
    ):
        flash(
            "The saved total does not match the rubric scores. "
            "Save the assessment again before publishing.",
            "warning"
        )
        return redirect(
            url_for(
                "main.enter_exam_result",
                booking_id=booking.id
            )
        )

    student = booking.student

    if student is None:
        abort(404)

    # Publish the result and notify the student in one transaction.
    result.status = "published"
    result.published_at = datetime.now(timezone.utc)

    db.session.add(
        Notification(
            user_id=student.id,
            message=(
                f"Your result for '{examination.title}' has been published. "
                "You can now view your marks and examiner feedback "
                "in My Examination Results."
            ),
            category="result",
            is_read=False
        )
    )

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash(
            "The result could not be published. Please try again.",
            "danger"
        )
        return redirect(url_for("main.examiner_results"))

    flash(
        "Result published successfully. The student has been notified.",
        "success"
    )
    return redirect(url_for("main.examiner_results"))


@main.route("/examiner/profile")
@role_required("examiner")
def examiner_profile():
    return render_template("examiner_profile.html")


@main.route("/examiner/profile/edit", methods=["GET", "POST"])
@role_required("examiner")
def edit_examiner_profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        department = request.form.get("department", "").strip()
        contact_details = request.form.get("contact_details", "").strip()

        form_data = {
            "name": name,
            "email": email,
            "department": department,
            "contact_details": contact_details,
        }

        if not name or not email or not department or not contact_details:
            flash("All fields are required.", "danger")
            return render_template("edit_examiner_profile.html", **form_data)

        if (
            len(name) > 100 or len(email) > 150
            or len(department) > 100 or len(contact_details) > 150
        ):
            flash("One of the fields exceeds the allowed length.", "danger")
            return render_template("edit_examiner_profile.html", **form_data)

        if email.count("@") != 1 or "." not in email.rsplit("@", 1)[-1]:
            flash("Please enter a valid email address.", "danger")
            return render_template("edit_examiner_profile.html", **form_data)

        existing_user = db.session.execute(
            db.select(User).where(
                db.func.lower(User.email) == email,
                User.id != current_user.id
            )
        ).scalar_one_or_none()

        if existing_user:
            flash("This email address is already registered.", "danger")
            return render_template("edit_examiner_profile.html", **form_data)

        current_user.name = name
        current_user.email = email
        current_user.department = department
        current_user.contact_details = contact_details

        try:
            db.session.commit()
            flash("Your profile was updated successfully.", "success")
            return redirect(url_for("main.examiner_profile"))
        except Exception:
            db.session.rollback()
            flash("Could not update your profile. Please try again.", "danger")

    return render_template(
        "edit_examiner_profile.html",
        name=current_user.name,
        email=current_user.email,
        department=current_user.department or "",
        contact_details=current_user.contact_details or "",
    )


@main.route("/examiner/bookings")
@login_required
@role_required("examiner")
def examiner_bookings():
    assignments = db.session.execute(
        db.select(ExaminerAssignment).filter_by(
            examiner_id=current_user.id
        )
    ).scalars().all()

    examination_ids = [
        assignment.examination_id
        for assignment in assignments
    ]

    bookings = []
    history_bookings = []

    if examination_ids:
        all_bookings = db.session.execute(
            db.select(ExamBooking)
            .join(ExamBooking.examination)
            .join(ExamBooking.student)
            .filter(
                ExamBooking.examination_id.in_(examination_ids)
            )
            .order_by(ExamBooking.booked_at.desc())
        ).scalars().unique().all()

        for booking in all_bookings:
            slot = booking.slot
            exam_has_ended = False

            if slot is not None:
                now = datetime.now()
                exam_has_ended = (
                    slot.slot_date < now.date()
                    or (
                        slot.slot_date == now.date()
                        and slot.end_time <= now.time()
                    )
                )

            if booking.status == "booked" and not exam_has_ended:
                bookings.append(booking)
            else:
                history_bookings.append(booking)

    return render_template(
        "examiner_bookings.html",
        bookings=bookings,
        history_bookings=history_bookings
    )

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


@main.route("/admin")
@role_required("admin")
def admin_dashboard():
    total_users = db.session.scalar(
        db.select(db.func.count()).select_from(User)
    ) or 0

    total_students = db.session.scalar(
        db.select(db.func.count())
        .select_from(User)
        .filter_by(role="student")
    ) or 0

    total_examiners = db.session.scalar(
        db.select(db.func.count())
        .select_from(User)
        .filter_by(role="examiner")
    ) or 0

    pending_examiners = db.session.scalar(
        db.select(db.func.count())
        .select_from(User)
        .filter_by(role="examiner", is_approved=False)
    ) or 0

    total_courses = db.session.scalar(
        db.select(db.func.count()).select_from(Course)
    ) or 0

    total_examinations = db.session.scalar(
        db.select(db.func.count()).select_from(Examination)
    ) or 0

    published_examinations = db.session.scalar(
        db.select(db.func.count())
        .select_from(Examination)
        .filter_by(status="published")
    ) or 0

    draft_examinations = db.session.scalar(
        db.select(db.func.count())
        .select_from(Examination)
        .filter_by(status="draft")
    ) or 0

    total_exam_slots = db.session.scalar(
        db.select(db.func.count()).select_from(ExamSlot)
    ) or 0

    total_bookings = db.session.scalar(
        db.select(db.func.count()).select_from(ExamBooking)
    ) or 0

    active_bookings = db.session.scalar(
        db.select(db.func.count())
        .select_from(ExamBooking)
        .filter_by(status="booked")
    ) or 0

    # Results Overview
    total_results = db.session.scalar(
        db.select(db.func.count()).select_from(ExamResult)
    ) or 0

    published_results = db.session.scalar(
        db.select(db.func.count())
        .select_from(ExamResult)
        .filter_by(status="published")
    ) or 0

    draft_results = db.session.scalar(
        db.select(db.func.count())
        .select_from(ExamResult)
        .filter_by(status="draft")
    ) or 0

    return render_template(
        "admin_dashboard.html",
        total_users=total_users,
        total_students=total_students,
        total_examiners=total_examiners,
        pending_examiners=pending_examiners,
        total_courses=total_courses,
        total_examinations=total_examinations,
        published_examinations=published_examinations,
        draft_examinations=draft_examinations,
        total_exam_slots=total_exam_slots,
        total_bookings=total_bookings,
        active_bookings=active_bookings,
        total_results=total_results,
        published_results=published_results,
        draft_results=draft_results,
    )


@main.route("/admin/students")
@role_required("admin")
def manage_students():
    search = request.args.get("search", "").strip()

    query = db.select(User).filter_by(role="student")

    if search:
        query = query.where(
            db.or_(
                *search_conditions(
                    search, [User.name, User.email], [User.id]
                )
            )
        )

    students = db.session.scalars(
        query.order_by(User.name.asc())
    ).all()

    return render_template(
        "manage_students.html",
        students=students,
        search=search
    )


@main.route("/admin/students/<int:user_id>/toggle-status", methods=["POST"])
@role_required("admin")
def toggle_student_status(user_id):
    student = db.session.get(User, user_id)

    if student is None or student.role != "student":
        abort(404)

    student.is_active = not student.is_active

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Unable to update the student account. Please try again.", "danger")
        return redirect(url_for("main.manage_students"))

    status_message = "activated" if student.is_active else "deactivated"
    flash(f"Student account {status_message} successfully.", "success")

    return redirect(url_for("main.manage_students"))


@main.route("/admin/examiners/<int:user_id>/toggle-status", methods=["POST"])
@role_required("admin")
def toggle_examiner_status(user_id):
    examiner = db.session.get(User, user_id)

    if examiner is None or examiner.role != "examiner":
        abort(404)

    examiner.is_active = not examiner.is_active

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash(
            "Unable to update the examiner account. Please try again.",
            "danger"
        )
        return redirect(url_for("main.manage_examiners"))

    status_message = "activated" if examiner.is_active else "deactivated"
    flash(f"Examiner account {status_message} successfully.", "success")

    return redirect(url_for("main.manage_examiners"))


@main.route("/admin/examiners", methods=["GET", "POST"])
@role_required("admin")
def manage_examiners():
    if request.method == "POST":
        examiner_id = request.form.get("examiner_id", type=int)
        examination_id = request.form.get("examination_id", type=int)

        examiner = db.session.get(User, examiner_id) if examiner_id else None
        examination = (
            db.session.get(Examination, examination_id)
            if examination_id else None
        )

        if not examiner or examiner.role != "examiner" or not examiner.is_approved:
            flash("Please select an approved examiner.", "danger")
            return redirect(url_for("main.manage_examiners"))

        if not examination:
            flash("Please select a valid examination.", "danger")
            return redirect(url_for("main.manage_examiners"))

        existing_assignment = db.session.scalar(
            db.select(ExaminerAssignment).where(
                ExaminerAssignment.examiner_id == examiner.id,
                ExaminerAssignment.examination_id == examination.id,
            )
        )

        if existing_assignment:
            flash("This examination is already assigned to that examiner.", "warning")
            return redirect(url_for("main.manage_examiners"))

        assignment = ExaminerAssignment(
            examiner_id=examiner.id,
            examination_id=examination.id,
        )

        try:
            db.session.add(assignment)
            db.session.commit()
            flash("Examination assigned successfully!", "success")
        except Exception:
            db.session.rollback()
            flash("Assignment could not be saved. Please try again.", "danger")

        return redirect(url_for("main.manage_examiners"))

    search = request.args.get("search", "").strip()

    pending_query = db.select(User).filter_by(
        role="examiner", is_approved=False
    )
    approved_query = db.select(User).filter_by(
        role="examiner", is_approved=True
    )

    if search:
        search_filter = db.or_(
            *search_conditions(
                search,
                [User.name, User.email, User.department],
                [User.id]
            )
        )
        pending_query = pending_query.where(search_filter)
        approved_query = approved_query.where(search_filter)

    pending_examiners = db.session.scalars(
        pending_query.order_by(User.created_at.desc())
    ).all()

    approved_examiners = db.session.scalars(
        approved_query.order_by(User.name)
    ).all()

    # Unfiltered totals and the list used by the "assign" drop-down.
    pending_total = db.session.scalar(
        db.select(db.func.count(User.id)).filter_by(
            role="examiner", is_approved=False
        )
    ) or 0

    approved_total = db.session.scalar(
        db.select(db.func.count(User.id)).filter_by(
            role="examiner", is_approved=True
        )
    ) or 0

    examiner_options = db.session.scalars(
        db.select(User)
        .filter_by(role="examiner", is_approved=True, is_active=True)
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
        "manage_examiners.html",
        pending_examiners=pending_examiners,
        approved_examiners=approved_examiners,
        pending_total=pending_total,
        approved_total=approved_total,
        examiner_options=examiner_options,
        examinations=examinations,
        assignments=assignments,
        search=search,
    )


@main.route("/admin/examiners/<int:user_id>/approve", methods=["POST"])
@role_required("admin")
def approve_examiner(user_id):
    examiner = db.session.get(User, user_id)

    if examiner is None or examiner.role != "examiner":
        abort(404)

    examiner.is_approved = True
    db.session.commit()

    flash(f"{examiner.name} has been approved successfully.", "success")
    return redirect(url_for("main.manage_examiners"))


@main.route("/admin/examiners/<int:user_id>/reject", methods=["POST"])
@role_required("admin")
def reject_examiner(user_id):
    examiner = db.session.get(User, user_id)

    if examiner is None or examiner.role != "examiner":
        abort(404)

    if examiner.is_approved:
        flash(
            "This examiner is already approved and cannot be rejected as pending.",
            "warning"
        )
        return redirect(url_for("main.manage_examiners"))

    try:
        db.session.delete(examiner)
        db.session.commit()
        flash("Pending examiner registration rejected.", "success")
    except Exception:
        db.session.rollback()
        flash(
            "Could not reject this examiner. Please try again.",
            "danger"
        )

    return redirect(url_for("main.manage_examiners"))

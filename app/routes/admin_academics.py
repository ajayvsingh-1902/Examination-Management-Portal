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


@main.route("/admin/results")
@role_required("admin")
def admin_results():
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()

    query = (
        db.select(ExamResult)
        .join(ExamBooking, ExamResult.booking_id == ExamBooking.id)
        .join(User, ExamBooking.student_id == User.id)
        .join(
            Examination,
            ExamBooking.examination_id == Examination.id
        )
    )

    # Search by student name or examination title.
    if search:
        search_term = f"%{search}%"
        query = query.where(
            User.name.ilike(search_term)
            | Examination.title.ilike(search_term)
        )

    # Filter by publication status.
    if status in ("draft", "published"):
        query = query.where(ExamResult.status == status)

    results = db.session.scalars(
        query.order_by(ExamResult.id.desc())
    ).all()

    return render_template(
        "admin_results.html",
        results=results,
        search=search,
        status=status
    )


@main.route("/admin/courses", methods=["GET", "POST"])
@role_required("admin")
def manage_courses():
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not code or not name:
            flash("Course code and course name are required.", "danger")
            return redirect(url_for("main.manage_courses"))

        if len(code) > 20:
            flash("Course code must be 20 characters or fewer.", "danger")
            return redirect(url_for("main.manage_courses"))

        if len(name) > 150:
            flash("Course name must be 150 characters or fewer.", "danger")
            return redirect(url_for("main.manage_courses"))

        if len(description) > 1000:
            flash("Description must be 1000 characters or fewer.", "danger")
            return redirect(url_for("main.manage_courses"))

        if not all(
            char.isascii() and (char.isalnum() or char in "_-")
            for char in code
        ):
            flash(
                "Course code may contain only letters, numbers, hyphens, "
                "and underscores.",
                "danger"
            )
            return redirect(url_for("main.manage_courses"))

        existing_course = db.session.execute(
            db.select(Course).filter_by(code=code)
        ).scalar_one_or_none()

        if existing_course:
            flash("A course with this code already exists.", "danger")
            return redirect(url_for("main.manage_courses"))

        course = Course(
            code=code,
            name=name,
            description=description or None
        )

        try:
            db.session.add(course)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash(
                "The course could not be added due to a database error. "
                "Please try again.",
                "danger"
            )
            return redirect(url_for("main.manage_courses"))

        flash("Course added successfully!", "success")
        return redirect(url_for("main.manage_courses"))

    search = request.args.get("search", "").strip()

    course_query = db.select(Course)

    if search:
        course_query = course_query.where(
            db.or_(
                *search_conditions(
                    search,
                    [Course.code, Course.name, Course.description],
                    [Course.id]
                )
            )
        )

    courses = db.session.execute(
        course_query.order_by(Course.code)
    ).scalars().all()

    return render_template(
        "manage_courses.html",
        courses=courses,
        search=search
    )


@main.route("/admin/courses/<int:course_id>/toggle-status", methods=["POST"])
@role_required("admin")
def toggle_course_status(course_id):
    course = db.session.get(Course, course_id)

    if course is None:
        abort(404)

    course.status = "inactive" if course.status == "active" else "active"

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Course status could not be updated.", "danger")
        return redirect(url_for("main.manage_courses"))

    flash(f"Course marked as {course.status}.", "success")
    return redirect(url_for("main.manage_courses"))


@main.route("/admin/courses/<int:course_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def edit_course(course_id):
    course = db.session.get(Course, course_id)

    if course is None:
        abort(404)

    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not code or not name:
            flash("Course code and name are required.", "danger")
            return redirect(url_for("main.edit_course", course_id=course.id))

        if len(code) > 20 or len(name) > 150 or len(description) > 1000:
            flash("One or more fields exceed the allowed length.", "danger")
            return redirect(url_for("main.edit_course", course_id=course.id))

        if not all(
            char.isascii() and (char.isalnum() or char in "_-")
            for char in code
        ):
            flash("Invalid course code format.", "danger")
            return redirect(url_for("main.edit_course", course_id=course.id))

        duplicate = db.session.scalar(
            db.select(Course).where(
                Course.code == code,
                Course.id != course.id
            )
        )

        if duplicate:
            flash("Another course already uses this code.", "danger")
            return redirect(url_for("main.edit_course", course_id=course.id))

        new_status = request.form.get("status", course.status).strip()

        if new_status not in ("active", "inactive"):
            flash("Please select a valid course status.", "danger")
            return redirect(url_for("main.edit_course", course_id=course.id))

        course.code = code
        course.name = name
        course.description = description or None
        course.status = new_status

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Course could not be updated. Please try again.", "danger")
            return redirect(url_for("main.edit_course", course_id=course.id))

        flash("Course updated successfully.", "success")
        return redirect(url_for("main.manage_courses"))

    return render_template("edit_course.html", course=course)


@main.route("/admin/courses/<int:course_id>/delete", methods=["POST"])
@role_required("admin")
def delete_course(course_id):
    course = db.session.get(Course, course_id)

    if course is None:
        abort(404)

    linked_examinations = db.session.scalar(
        db.select(db.func.count())
        .select_from(Examination)
        .where(Examination.course_id == course.id)
    ) or 0

    if linked_examinations:
        flash(
            "This course cannot be deleted because examinations are linked to it.",
            "warning"
        )
        return redirect(url_for("main.manage_courses"))

    try:
        db.session.delete(course)
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Course could not be deleted. Please try again.", "danger")
        return redirect(url_for("main.manage_courses"))

    flash("Course deleted successfully.", "success")
    return redirect(url_for("main.manage_courses"))


@main.route("/admin/examinations", methods=["GET", "POST"])
@role_required("admin")
def manage_examinations():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        examination_type = request.form.get(
            "examination_type", ""
        ).strip()

        allowed_types = {
            "Viva",
            "Practical",
            "Project Demo",
            "Assessment",
        }

        if examination_type not in allowed_types:
            flash("Please select a valid examination type.", "danger")
            return redirect(url_for("main.manage_examinations"))

        course_id = request.form.get("course_id", "").strip()
        duration = request.form.get("duration_minutes", "").strip()
        max_marks = request.form.get("max_marks", "").strip()

        opens_text = request.form.get("booking_opens_at", "").strip()
        closes_text = request.form.get("booking_closes_at", "").strip()

        slot_opens_text = request.form.get(
            "slot_creation_opens_at", ""
        ).strip()
        slot_closes_text = request.form.get(
            "slot_creation_closes_at", ""
        ).strip()

        if not title or not course_id or not duration or not max_marks:
            flash("Please fill in all required fields.", "danger")
            return redirect(url_for("main.manage_examinations"))

        if len(title) > 150:
            flash(
                "Examination title must be 150 characters or fewer.",
                "danger",
            )
            return redirect(url_for("main.manage_examinations"))

        try:
            course_id = int(course_id)
            duration = int(duration)
            max_marks = int(max_marks)

            booking_opens_at = (
                datetime.fromisoformat(opens_text) if opens_text else None
            )
            booking_closes_at = (
                datetime.fromisoformat(closes_text) if closes_text else None
            )
            slot_creation_opens_at = (
                datetime.fromisoformat(slot_opens_text)
                if slot_opens_text else None
            )
            slot_creation_closes_at = (
                datetime.fromisoformat(slot_closes_text)
                if slot_closes_text else None
            )
        except (ValueError, TypeError):
            flash(
                "Please enter valid numeric values and dates.",
                "danger",
            )
            return redirect(url_for("main.manage_examinations"))

        course = db.session.get(Course, course_id)

        if course is None:
            flash("Please select a valid course.", "danger")
            return redirect(url_for("main.manage_examinations"))

        if course.status != "active":
            flash(
                "Examinations can only be created for active courses.",
                "danger"
            )
            return redirect(url_for("main.manage_examinations"))

        if not 1 <= duration <= 1440 or max_marks <= 0:
            flash(
                "Duration must be between 1 and 1440 minutes, "
                "and maximum marks must be greater than zero.",
                "danger",
            )
            return redirect(url_for("main.manage_examinations"))

        if (
            booking_opens_at is not None
            and booking_closes_at is not None
            and booking_opens_at >= booking_closes_at
        ):
            flash(
                "Booking closing time must be after opening time.",
                "danger",
            )
            return redirect(url_for("main.manage_examinations"))

        if (
            slot_creation_opens_at is not None
            and slot_creation_closes_at is not None
            and slot_creation_opens_at >= slot_creation_closes_at
        ):
            flash(
                "Slot-creation closing time must be after opening time.",
                "danger",
            )
            return redirect(url_for("main.manage_examinations"))

        examination = Examination(
            title=title,
            examination_type=examination_type,
            course_id=course_id,
            duration_minutes=duration,
            max_marks=max_marks,
            booking_opens_at=booking_opens_at,
            booking_closes_at=booking_closes_at,
            slot_creation_opens_at=slot_creation_opens_at,
            slot_creation_closes_at=slot_creation_closes_at,
            status="draft",
        )

        try:
            db.session.add(examination)
            db.session.commit()
            flash("Examination created successfully!", "success")
        except Exception:
            db.session.rollback()
            flash("Could not create the examination.", "danger")

        return redirect(url_for("main.manage_examinations"))

    search = request.args.get("search", "").strip()

    courses = db.session.scalars(
        db.select(Course)
        .where(Course.status == "active")
        .order_by(Course.code)
    ).all()

    examination_query = db.select(Examination).join(Course)

    if search:
        examination_query = examination_query.where(
            db.or_(
                *search_conditions(
                    search,
                    [
                        Examination.title,
                        Examination.examination_type,
                        Course.code,
                        Course.name
                    ],
                    [Examination.id]
                )
            )
        )

    examinations = db.session.scalars(
        examination_query.order_by(Examination.id.desc())
    ).all()

    return render_template(
        "manage_examinations.html",
        courses=courses,
        examinations=examinations,
        search=search,
    )


@main.route("/admin/rubrics", methods=["GET", "POST"])
@role_required("admin")
def manage_rubrics():
    if request.method == "POST":
        examination_id = request.form.get("examination_id", "").strip()
        criterion_name = request.form.get("criterion_name", "").strip()
        max_marks = request.form.get("max_marks", "").strip()
        weightage = request.form.get("weightage", "1").strip()
        description = request.form.get("description", "").strip()

        try:
            examination_id = int(examination_id)
            max_marks = float(max_marks)
            weightage = float(weightage)
        except (ValueError, TypeError):
            flash("Enter valid examination, maximum marks, and weightage.", "danger")
            return redirect(url_for("main.manage_rubrics"))

        examination = db.session.get(Examination, examination_id)

        if examination is None:
            flash("Please select a valid examination.", "danger")
            return redirect(url_for("main.manage_rubrics"))

        if not criterion_name or len(criterion_name) > 150:
            flash("Criterion name is required and must be at most 150 characters.", "danger")
            return redirect(url_for("main.manage_rubrics"))

        if max_marks <= 0 or weightage <= 0:
            flash("Maximum marks and weightage must be greater than zero.", "danger")
            return redirect(url_for("main.manage_rubrics"))

        if max_marks > examination.max_marks:
            flash("Criterion maximum marks cannot exceed the examination's maximum marks.", "danger")
            return redirect(url_for("main.manage_rubrics"))

        if len(description) > 2000:
            flash("Description must be at most 2000 characters.", "danger")
            return redirect(url_for("main.manage_rubrics"))

        rubric = ExamRubric(
            examination_id=examination_id,
            criterion_name=criterion_name,
            max_marks=max_marks,
            weightage=weightage,
            description=description or None
        )

        try:
            db.session.add(rubric)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Could not save the rubric. Please try again.", "danger")
            return redirect(url_for("main.manage_rubrics"))

        flash("Rubric criterion added successfully.", "success")
        return redirect(url_for("main.manage_rubrics"))

    examinations = db.session.scalars(
        db.select(Examination).order_by(Examination.title)
    ).all()

    rubrics = db.session.scalars(
        db.select(ExamRubric)
        .order_by(ExamRubric.examination_id, ExamRubric.id)
    ).all()

    return render_template(
        "manage_rubrics.html",
        examinations=examinations,
        rubrics=rubrics
    )


@main.route(
    "/admin/rubrics/<int:rubric_id>/delete",
    methods=["POST"]
)
@main.route(
    "/admin/rubrics/<int:rubric_id>/edit",
    methods=["GET", "POST"]
)
@role_required("admin")
def edit_rubric(rubric_id):
    rubric = db.session.get(ExamRubric, rubric_id)

    if rubric is None:
        abort(404)

    examinations = db.session.scalars(
        db.select(Examination).order_by(Examination.title)
    ).all()

    if request.method == "POST":
        criterion_name = request.form.get(
            "criterion_name", ""
        ).strip()
        max_marks_text = request.form.get(
            "max_marks", ""
        ).strip()
        weightage_text = request.form.get(
            "weightage", "1"
        ).strip()
        description = request.form.get(
            "description", ""
        ).strip()

        try:
            max_marks = float(max_marks_text)
            weightage = float(weightage_text)
        except (ValueError, TypeError):
            flash(
                "Enter valid maximum marks and weightage.",
                "danger"
            )
            return render_template(
                "edit_rubric.html",
                rubric=rubric,
                examinations=examinations
            )

        if not criterion_name or len(criterion_name) > 150:
            flash(
                "Criterion name is required and must be at most 150 characters.",
                "danger"
            )
            return render_template(
                "edit_rubric.html",
                rubric=rubric,
                examinations=examinations
            )

        if (
            not math.isfinite(max_marks)
            or not math.isfinite(weightage)
            or max_marks <= 0
            or weightage <= 0
        ):
            flash(
                "Maximum marks and weightage must be positive valid numbers.",
                "danger"
            )
            return render_template(
                "edit_rubric.html",
                rubric=rubric,
                examinations=examinations
            )

        if max_marks > rubric.examination.max_marks:
            flash(
                "Criterion maximum marks cannot exceed the examination's maximum marks.",
                "danger"
            )
            return render_template(
                "edit_rubric.html",
                rubric=rubric,
                examinations=examinations
            )

        if len(description) > 2000:
            flash(
                "Description must be at most 2000 characters.",
                "danger"
            )
            return render_template(
                "edit_rubric.html",
                rubric=rubric,
                examinations=examinations
            )

        rubric.criterion_name = criterion_name
        rubric.max_marks = max_marks
        rubric.weightage = weightage
        rubric.description = description or None

        try:
            db.session.commit()
            flash(
                "Rubric criterion updated successfully.",
                "success"
            )
            return redirect(url_for("main.manage_rubrics"))
        except Exception:
            db.session.rollback()
            flash(
                "Could not update the rubric criterion.",
                "danger"
            )

    return render_template(
        "edit_rubric.html",
        rubric=rubric,
        examinations=examinations
    )


@main.route(
    "/admin/rubrics/<int:rubric_id>/delete",
    methods=["POST"]
)
@role_required("admin")
def delete_rubric(rubric_id):
    rubric = db.session.get(ExamRubric, rubric_id)

    if rubric is None:
        abort(404)

    try:
        db.session.delete(rubric)
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Could not delete the rubric criterion.", "danger")
        return redirect(url_for("main.manage_rubrics"))

    flash("Rubric criterion deleted successfully.", "success")
    return redirect(url_for("main.manage_rubrics"))


@main.route("/admin/examinations/<int:examination_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def edit_examination(examination_id):
    examination = db.session.get(Examination, examination_id)

    if examination is None:
        abort(404)

    # Only active bookings should prevent an examination from being edited.
    # Keep cancelled booking records for history, but do not count them here.
    booking_count = db.session.scalar(
        db.select(db.func.count())
        .select_from(ExamBooking)
        .where(
            ExamBooking.examination_id == examination.id,
            ExamBooking.status == "booked"
        )
    ) or 0

    if booking_count:
        flash(
            "This examination cannot be edited because bookings already exist.",
            "warning"
        )
        return redirect(url_for("main.manage_examinations"))

    allowed_types = {
        "Viva",
        "Practical",
        "Project Demo",
        "Assessment"
    }

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        examination_type = request.form.get(
            "examination_type", ""
        ).strip()
        course_id = request.form.get("course_id", "").strip()
        duration = request.form.get("duration_minutes", "").strip()
        max_marks = request.form.get("max_marks", "").strip()

        opens_text = request.form.get("booking_opens_at", "").strip()
        closes_text = request.form.get("booking_closes_at", "").strip()

        slot_opens_text = request.form.get(
            "slot_creation_opens_at", ""
        ).strip()
        slot_closes_text = request.form.get(
            "slot_creation_closes_at", ""
        ).strip()

        if (
            not title
            or not course_id
            or not duration
            or not max_marks
            or examination_type not in allowed_types
        ):
            flash(
                "Please complete all required fields and select a valid examination type.",
                "danger"
            )
            return redirect(url_for(
                "main.edit_examination",
                examination_id=examination.id
            ))

        if len(title) > 150:
            flash(
                "Examination title must be 150 characters or fewer.",
                "danger"
            )
            return redirect(url_for(
                "main.edit_examination",
                examination_id=examination.id
            ))

        try:
            course_id = int(course_id)
            duration = int(duration)
            max_marks = int(max_marks)

            booking_opens_at = (
                datetime.fromisoformat(opens_text) if opens_text else None
            )
            booking_closes_at = (
                datetime.fromisoformat(closes_text) if closes_text else None
            )
            slot_creation_opens_at = (
                datetime.fromisoformat(slot_opens_text)
                if slot_opens_text else None
            )
            slot_creation_closes_at = (
                datetime.fromisoformat(slot_closes_text)
                if slot_closes_text else None
            )

        except (ValueError, TypeError):
            flash(
                "Please enter valid numeric values and dates.",
                "danger"
            )
            return redirect(url_for(
                "main.edit_examination",
                examination_id=examination.id
            ))

        course = db.session.get(Course, course_id)

        if course is None:
            flash("Please select a valid course.", "danger")
            return redirect(url_for(
                "main.edit_examination",
                examination_id=examination.id
            ))

        if not 1 <= duration <= 1440 or max_marks <= 0:
            flash(
                "Duration must be 1–1440 minutes and maximum marks must be a positive whole number.",
                "danger"
            )
            return redirect(url_for(
                "main.edit_examination",
                examination_id=examination.id
            ))

        if (
            booking_opens_at is not None
            and booking_closes_at is not None
            and booking_opens_at >= booking_closes_at
        ):
            flash(
                "Booking closing time must be after opening time.",
                "danger"
            )
            return redirect(url_for(
                "main.edit_examination",
                examination_id=examination.id
            ))

        if (
            slot_creation_opens_at is not None
            and slot_creation_closes_at is not None
            and slot_creation_opens_at >= slot_creation_closes_at
        ):
            flash(
                "Slot-creation closing time must be after opening time.",
                "danger"
            )
            return redirect(url_for(
                "main.edit_examination",
                examination_id=examination.id
            ))

        examination.title = title
        examination.examination_type = examination_type
        examination.course_id = course_id
        examination.duration_minutes = duration
        examination.max_marks = int(max_marks)

        examination.booking_opens_at = booking_opens_at
        examination.booking_closes_at = booking_closes_at
        examination.slot_creation_opens_at = slot_creation_opens_at
        examination.slot_creation_closes_at = slot_creation_closes_at

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Examination could not be updated.", "danger")
            return redirect(url_for(
                "main.edit_examination",
                examination_id=examination.id
            ))

        flash("Examination updated successfully.", "success")
        return redirect(url_for("main.manage_examinations"))

    courses = db.session.scalars(
        db.select(Course).order_by(Course.code)
    ).all()

    return render_template(
        "edit_examination.html",
        examination=examination,
        courses=courses
    )


@main.route("/admin/examinations/<int:examination_id>/delete", methods=["POST"])
@role_required("admin")
def delete_examination(examination_id):
    examination = db.session.get(Examination, examination_id)

    if examination is None:
        abort(404)

    booking_count = db.session.scalar(
        db.select(db.func.count())
        .select_from(ExamBooking)
        .where(ExamBooking.examination_id == examination.id)
    ) or 0

    slot_count = db.session.scalar(
        db.select(db.func.count())
        .select_from(ExamSlot)
        .where(ExamSlot.examination_id == examination.id)
    ) or 0

    if booking_count or slot_count:
        flash(
            "This examination cannot be deleted because bookings or exam slots are linked to it.",
            "warning"
        )
        return redirect(url_for("main.manage_examinations"))

    try:
        db.session.delete(examination)
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Examination could not be deleted.", "danger")
        return redirect(url_for("main.manage_examinations"))

    flash("Examination deleted successfully.", "success")
    return redirect(url_for("main.manage_examinations"))


@main.route("/admin/examinations/<int:examination_id>/publish", methods=["POST"])
@role_required("admin")
def publish_examination(examination_id):
    examination = db.session.get(Examination, examination_id)

    if examination is None:
        abort(404)

    if examination.status == "published":
        flash("This examination is already published.", "info")
        return redirect(url_for("main.manage_examinations"))

    examination.status = "published"

    try:
        db.session.commit()
        flash("Examination published successfully.", "success")
    except Exception:
        db.session.rollback()
        flash("Could not publish the examination.", "danger")

    return redirect(url_for("main.manage_examinations"))

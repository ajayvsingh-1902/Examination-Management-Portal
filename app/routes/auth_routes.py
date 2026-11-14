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


@main.route("/")
def index():
    return render_template("index.html")


@main.route("/health")
def health():
    return {"status": "ok"}


@main.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "")
        department = request.form.get("department", "").strip()
        contact_details = request.form.get("contact_details", "").strip()

        if not name or not email or not password:
            flash("Please fill in all required fields.", "danger")
            return redirect(url_for("main.register"))

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")
            return redirect(url_for("main.register"))

        if role not in ("student", "examiner"):
            flash("Please select a valid account type.", "danger")
            return redirect(url_for("main.register"))

        if role == "examiner":
            if not department or not contact_details:
                flash(
                    "Examiners must provide a department and contact details.",
                    "danger"
                )
                return redirect(url_for("main.register"))

            if len(department) > 100 or len(contact_details) > 150:
                flash(
                    "Department or contact details exceed the allowed length.",
                    "danger"
                )
                return redirect(url_for("main.register"))

        existing_user = db.session.execute(
            db.select(User).filter_by(email=email)
        ).scalar_one_or_none()

        if existing_user:
            flash("An account with this email already exists.", "danger")
            return redirect(url_for("main.register"))

        user = User(
            name=name,
            email=email,
            role=role,
            is_active=True,
            is_approved=(role == "student"),
            department=department if role == "examiner" else None,
            contact_details=contact_details if role == "examiner" else None
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        if role == "examiner":
            flash(
                "Registration successful. Wait for administrator approval.",
                "info"
            )
        else:
            flash(
                "Registration successful. You can now log in.",
                "success"
            )

        return redirect(url_for("main.login"))

    return render_template("register.html")


@main.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = db.session.execute(
            db.select(User).filter_by(email=email)
        ).scalar_one_or_none()

        if user is None or not user.check_password(password):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("main.login"))

        if not user.is_active:
            flash(
                "This account is disabled. Contact the administrator.",
                "danger"
            )
            return redirect(url_for("main.login"))

        if user.role == "examiner" and not user.is_approved:
            flash(
                "Your examiner account is awaiting administrator approval.",
                "warning"
            )
            return redirect(url_for("main.login"))

        login_user(user)
        flash("Login successful!", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("login.html")


@main.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.index"))


@main.route("/dashboard")
@login_required
def dashboard():
    if current_user.role == "admin":
        return redirect(url_for("main.admin_dashboard"))
    elif current_user.role == "student":
        return redirect(url_for("main.student_dashboard"))
    elif current_user.role == "examiner":
        return redirect(url_for("main.examiner_dashboard"))

    abort(403)

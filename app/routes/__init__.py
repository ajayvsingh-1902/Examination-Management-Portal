from functools import wraps
from datetime import date, datetime, timezone, timedelta
import math

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import (
    login_user, logout_user, current_user, login_required
)

from app.extensions import db
from app.models import (
    User,
    Course,
    Examination,
    ExamSlot,
    ExamBooking,
    ExamResult,
    Notification,
    ExaminerAssignment,
    ExamRubric,
    ExamRubricAssessment
)

from io import BytesIO
from xml.sax.saxutils import escape

from flask import send_file, abort
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from sqlalchemy import select


main = Blueprint("main", __name__)


def role_required(required_role):
    def decorator(view_function):
        @wraps(view_function)
        @login_required
        def wrapped_view(*args, **kwargs):
            if current_user.role != required_role:
                abort(403)
            return view_function(*args, **kwargs)

        return wrapped_view
    return decorator


def search_conditions(search, text_columns, id_columns=()):
    """Build OR-conditions to search text columns and, if the search
    text is a number, also match the given ID columns exactly."""
    pattern = f"%{search}%"
    conditions = [column.ilike(pattern) for column in text_columns]

    if search.isdigit() and len(search) <= 9:
        number = int(search)
        conditions.extend(column == number for column in id_columns)

    return conditions


def booking_has_started(examination, now):
    """True once the examination's student booking period has begun."""
    return (
        examination.booking_opens_at is not None
        and now >= examination.booking_opens_at
    )




# Import route modules to register their endpoints on the shared blueprint.
from app.routes import auth_routes  # noqa: F401
from app.routes import admin_users  # noqa: F401
from app.routes import admin_academics  # noqa: F401
from app.routes import admin_bookings  # noqa: F401
from app.routes import examiner_routes  # noqa: F401
from app.routes import student_routes  # noqa: F401

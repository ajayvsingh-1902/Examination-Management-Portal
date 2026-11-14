# Examination Management Portal

Flask + SQLite application with three roles: Admin, Examiner and Student.

## Setup
```
python -m venv .venv
.venv\Scripts\activate        (Windows)   |   source .venv/bin/activate  (Mac/Linux)
pip install -r requirements.txt
python create_admin.py        # create the administrator account
python run.py                 # open http://127.0.0.1:5000
```

The SQLite database (`instance/examination.db`) is created automatically on
first start. If you already have a database from an older version, any
missing columns are added automatically at start-up (no manual migration).

## Roles
- **Admin:** manage courses, examinations, rubrics, examiners (approve /
  deactivate / assign), students, slots and bookings (search by name or ID).
- **Examiner:** register (department + contact details), wait for approval,
  create slots inside the slot-creation window (edit/delete only before
  booking starts), view booked students, enter rubric marks and results.
- **Student:** register, view available examinations/slots on the dashboard,
  book and cancel slots, view timetable, results and download scorecard.

## Code structure

Route handlers are organized under `app/routes/` by responsibility:
- `auth_routes.py`: home, registration, login and dashboard routing
- `admin_users.py`: student/examiner account administration
- `admin_academics.py`: courses, examinations, rubrics and results administration
- `admin_bookings.py`: booking lists, slot overview and rescheduling
- `examiner_routes.py`: examiner assignments, slots, assessments and results
- `student_routes.py`: student examinations, bookings, notifications and results
- `__init__.py`: shared Blueprint, authorization/helper functions and route-module registration

The routes use one shared Flask Blueprint, so existing `url_for('main...')` endpoint names are retained.

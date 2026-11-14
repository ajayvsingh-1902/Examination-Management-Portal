# Examination Management Portal

A role-based web application built with **Python, Flask, and SQLite** to manage examination scheduling, slot bookings, examiner assignments, assessments, and result publication.

## Overview

The Examination Management Portal centralizes the examination workflow for three roles:

- **Admin** — manages courses, examinations, slots, users, examiner assignments, rubrics, bookings, and results.
- **Examiner** — views assigned examinations/bookings, evaluates students, and records marks and feedback.
- **Student** — browses examinations, books available slots, checks booking status, and views published results and notifications.

The application uses Flask for server-side logic, Jinja2 for HTML templates, and SQLite through Flask-SQLAlchemy for persistence.

## Features

### Administrator
- Manage courses and examinations.
- Configure examination slots and booking windows.
- View and manage student bookings.
- Manage examiner accounts and examination assignments.
- Configure assessment rubrics.
- Manage examination results and view administrative information.

### Examiner
- Access a role-specific dashboard.
- View assigned examination bookings.
- Assess students using the available assessment workflow/rubrics.
- Enter marks and feedback.
- Review assessment and result information.

### Student
- Register and log in.
- Browse available examinations and slots.
- Book slots and view booking status.
- View personal bookings and timetable information.
- Access published results and feedback.
- Receive notifications and examination reminders.
- Manage profile information.

## Technology Stack

| Area | Technologies |
|---|---|
| Backend | Python, Flask |
| Frontend | HTML, CSS, Bootstrap |
| Templates | Jinja2 |
| Database | SQLite |
| ORM | Flask-SQLAlchemy |
| Authentication | Flask-Login |
| Forms and CSRF protection | Flask-WTF |
| PDF generation | ReportLab |
| Scheduled reminders | APScheduler |

## Project Structure

The route handlers are organized into a `routes/` package instead of keeping all request handlers in one large `routes.py` file. This separates the application workflows into smaller modules and makes the code easier to navigate and maintain.

```text
examination-portal/
├── app/
│   ├── __init__.py
│   ├── extensions.py
│   ├── models.py
│   ├── reminders.py
│   ├── schema_upgrade.py
│   ├── routes/
│   │   ├── __init__.py
│   │   └── ...                 # Route modules for application roles/features
│   ├── static/
│   │   └── css/
│   │       └── style.css
│   └── templates/
│       └── ...                 # Jinja2 HTML templates
├── instance/                   # Local SQLite database; normally excluded from Git
├── create_admin.py
├── migrate_examination_type.py
├── migrate_slot_window.py
├── requirements.txt
├── run.py
├── test_reminders.py           # Reminder test file, if included in this version
├── .gitignore
└── README.md
```

> The exact files present may vary slightly by project version. Keep the route package and its modules together; do not move individual route files without updating their imports.

## Requirements

- Python 3.10 or newer
- `pip`
- Git (only required if cloning the repository)

## Setup and Run

### 1. Clone the repository

```bash
git clone https://github.com/ajayvsingh-1902/Examination-Management-Portal-IITM-Project.git
cd Examination-Management-Portal-IITM-Project
```

If you already have the project files, open a terminal in the project root (the directory containing `run.py`).

### 2. Create a virtual environment

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can run the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

With the virtual environment activated:

```bash
python -m pip install -r requirements.txt
```

### 4. Initialize the database

The application uses SQLite and initializes its database through the Flask application setup. The local database is generally stored under `instance/`.

For a fresh setup:
- Ensure the application can create/write to the `instance/` directory.
- Follow the instructions in `create_admin.py` if an administrator account needs to be created.
- Use the migration scripts only when required by the database schema/version.

**Important:** A fresh clone may not contain existing users, courses, bookings, or results because local database files are normally excluded from Git. Do not overwrite an existing `instance/examination.db` if it contains data you need to keep.

### 5. Start the application

```bash
python run.py
```

Then open:

[http://127.0.0.1:5000](http://127.0.0.1:5000)

Stop the development server with `Ctrl + C`.

## Testing

If the test file and test dependencies are available in the checked-out version, run:

```bash
python -m pytest
```

The repository includes reminder-related test coverage in versions where `test_reminders.py` is present. A successful test run depends on the installed test dependencies and the project's test configuration.

## Security Notes

- Do not commit secret keys, passwords, tokens, or `.env` files.
- Keep private or populated SQLite database files out of public repositories.
- Use separate test accounts for Admin, Examiner, and Student roles.
- The built-in Flask development server is intended for local development, not production deployment.
- Before public deployment, configure production secrets, HTTPS, and a production-ready WSGI server.

## Future Improvements

- Expand automated tests for all roles and workflows.
- Add more reporting and analytics.
- Improve accessibility and responsive usability.
- Add production deployment and monitoring configuration.

## Author

**Ajay Vikram Singh**  
BS in Data Science & Programming Indian Insitute of Technology, Madras

## License

No license has been specified. Contact the repository owner before reusing or redistributing this project.

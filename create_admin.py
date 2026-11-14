
from getpass import getpass

from app import create_app
from app.extensions import db
from app.models import User


app = create_app()

with app.app_context():
    print("\n=== Create Administrator Account ===")

    name = input("Admin full name: ").strip()
    email = input("Admin email: ").strip().lower()

    if not name or not email:
        print("Name and email cannot be empty.")

    elif db.session.execute(
        db.select(User).filter_by(email=email)
    ).scalar_one_or_none():
        print("An account with this email already exists.")

    else:
        password = getpass(
            "Create password (minimum 8 characters): "
        )
        confirm = getpass("Confirm password: ")

        if len(password) < 8:
            print("Password must be at least 8 characters.")
        elif password != confirm:
            print("Passwords do not match.")
        else:
            admin = User(
                name=name,
                email=email,
                role="admin",
                is_active=True,
                is_approved=True
            )

            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()

            print("\nAdministrator account created successfully!")

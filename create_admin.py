from getpass import getpass

from sqlalchemy import select

from app.auth import hash_password
from app.database import SessionLocal
from app.models import User


def main():
    db = SessionLocal()

    try:
        # Check whether an Admin already exists.
        existing_admin = db.scalar(
            select(User).where(
                User.role == "Admin"
            )
        )

        if existing_admin is not None:
            print("An Admin account already exists.")
            print("Only one Admin account is allowed.")
            return

        # Get Admin credentials.
        email = input("Admin email: ").strip()
        password = getpass("Admin password: ")

        if not email:
            print("Admin email cannot be empty.")
            return

        if len(password) < 8:
            print("Admin password must contain at least 8 characters.")
            return

        if len(password.encode("utf-8")) > 72:
            print("Admin password must not exceed 72 UTF-8 bytes.")
            return

        # Create the single Admin account.
        admin = User(
            email=email,
            password_hash=hash_password(password),
            role="Admin",
            status="Active",
            is_active=True,
        )

        db.add(admin)
        db.commit()

        print()
        print("Admin account created successfully.")
        print(f"Admin email: {email}")

    except Exception as error:
        db.rollback()
        print()
        print("Failed to create Admin account.")
        print(f"Error: {error}")

    finally:
        db.close()


if __name__ == "__main__":
    main()

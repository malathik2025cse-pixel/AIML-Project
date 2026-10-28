
from getpass import getpass

from sqlalchemy import select

from app.auth import hash_password
from app.database import SessionLocal
from app.models import User


def main():
    db = SessionLocal()

    try:
        admins = db.scalars(
            select(User).where(User.role == "Admin")
        ).all()

        if not admins:
            print("No existing Admin account was found.")
            return

        if len(admins) > 1:
            print("Multiple Admin accounts found. No changes made.")
            return

        admin = admins[0]

        print(f"Existing Admin email: {admin.email}")
        password = getpass("Enter new Admin password: ")
        confirm = getpass("Confirm new password: ")

        if password != confirm:
            print("Passwords do not match. No changes made.")
            return

        if len(password) < 8:
            print("Password must contain at least 8 characters.")
            return

        if len(password.encode("utf-8")) > 72:
            print("Password must not exceed 72 UTF-8 bytes.")
            return

        admin.password_hash = hash_password(password)
        db.commit()

        print("Admin password reset successfully.")

    except Exception as error:
        db.rollback()
        print(f"Password reset failed: {error}")

    finally:
        db.close()


if __name__ == "__main__":
    main()

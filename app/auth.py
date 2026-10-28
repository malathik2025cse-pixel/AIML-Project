from datetime import datetime, timedelta, timezone
import secrets

from jose import JWTError, jwt
from passlib.context import CryptContext
from app.database import settings


pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


# Read from the same Pydantic settings instance that loads backend/.env. The
# fallback keeps local startup possible, while a configured key remains stable
# across reloads and worker processes.
SECRET_KEY = settings.jwt_secret_key or secrets.token_urlsafe(48)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(
    password: str,
    password_hash: str,
) -> bool:
    return pwd_context.verify(
        password,
        password_hash,
    )


def create_access_token(
    user_id: int,
    role: str,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
    }

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_access_token(
    token: str,
) -> dict | None:
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
        )

        return payload

    except JWTError:
        return None

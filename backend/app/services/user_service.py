import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


def get_user(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at.desc())))


def create_user(db: Session, user_in: UserCreate) -> User:
    user = User(
        username=user_in.username,
        email=str(user_in.email),
        full_name=user_in.full_name,
        hashed_password=hash_password(user_in.password),
        role=user_in.role,
        is_active=user_in.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, user: User, user_in: UserUpdate) -> User:
    update_data = user_in.model_dump(exclude_unset=True)
    password = update_data.pop("password", None)

    for field, value in update_data.items():
        setattr(user, field, str(value) if field == "email" else value)

    if password:
        user.hashed_password = hash_password(password)

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user: User) -> None:
    db.delete(user)
    db.commit()


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = get_user_by_username(db, username)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def count_users(db: Session) -> int:
    return len(list(db.scalars(select(User.id).limit(1))))


def seed_default_admin(db: Session) -> None:
    if count_users(db) > 0:
        return

    create_user(
        db,
        UserCreate(
            username="admin",
            email="admin@mdp.local",
            password="admin123",
            role="admin",
            is_active=True,
        ),
    )

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.bootstrap_admin import bootstrap_admin
from app.backend.database import Base, DirectoryPersonLocalAccountRecord, UserRecord
from app.backend.passwords import PASSWORD_HASH_SCHEME


class BootstrapAdminTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_creates_only_first_admin_and_directory_identity(self):
        with self.session_factory() as db:
            user = bootstrap_admin(
                db,
                name="  Project Owner  ",
                email=" Owner@Example.COM ",
                password="a-long-bootstrap-password",
            )
            self.assertEqual(user.name, "Project Owner")
            self.assertEqual(user.email, "owner@example.com")
            self.assertEqual(user.role, "admin")
            self.assertTrue(user.is_active)
            self.assertTrue(user.password_hash.startswith(f"{PASSWORD_HASH_SCHEME}$"))
            self.assertEqual(db.query(UserRecord).count(), 1)
            self.assertEqual(db.query(DirectoryPersonLocalAccountRecord).count(), 1)

            with self.assertRaisesRegex(RuntimeError, "only when.*empty"):
                bootstrap_admin(
                    db,
                    name="Second Owner",
                    email="second@example.com",
                    password="another-bootstrap-password",
                )

    def test_rejects_invalid_identity_or_weak_password_without_writes(self):
        cases = (
            {"name": "", "email": "owner@example.com", "password": "long-enough-password"},
            {"name": "Owner", "email": "not-an-email", "password": "long-enough-password"},
            {"name": "Owner", "email": "owner@example.com", "password": "too-short"},
        )
        for values in cases:
            with self.subTest(values=values), self.session_factory() as db:
                with self.assertRaises(ValueError):
                    bootstrap_admin(db, **values)
                db.rollback()
                self.assertEqual(db.query(UserRecord).count(), 0)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import Base, KbArticleRecord, UserRecord, get_db


class KnowledgeCategoryScopeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory() as db:
            db.add_all([
                UserRecord(id="admin", name="Admin", role="admin", is_active=True),
                UserRecord(id="agent", name="Agent", role="agent", is_active=True),
                KbArticleRecord(
                    id="published",
                    title="Published article",
                    slug="published",
                    status="published",
                    category="Shared category",
                ),
                KbArticleRecord(
                    id="draft",
                    title="Draft article",
                    slug="draft",
                    status="draft",
                    category="Draft-only category",
                ),
            ])
            db.commit()

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        self.current_user = UserRecord(
            id="agent", name="Agent", role="agent", is_active=True
        )
        main.app.dependency_overrides[get_db] = override_db
        main.app.dependency_overrides[main.get_authenticated_user] = (
            lambda: self.current_user
        )
        self.auth_patch = patch.object(
            main, "_auth_required_for_request", return_value=False
        )
        self.auth_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.auth_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_agents_only_see_published_categories(self):
        published = self.client.get("/kb/categories")
        all_categories = self.client.get("/kb/categories", params={"status": "all"})

        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json(), {"categories": ["Shared category"]})
        self.assertEqual(all_categories.status_code, 403, all_categories.text)

    def test_managers_can_filter_drafts_by_draft_only_category(self):
        self.current_user = UserRecord(
            id="admin", name="Admin", role="admin", is_active=True
        )

        response = self.client.get("/kb/categories", params={"status": "all"})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {"categories": ["Draft-only category", "Shared category"]},
        )


if __name__ == "__main__":
    unittest.main()

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://crm:crm@localhost:5433/crm_test"
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.base import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Company, Contact, Deal, User  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.enums import DealStage, RoleEnum  # noqa: E402

ADMIN_URL = "postgresql+psycopg://crm:crm@localhost:5433/postgres"


@pytest.fixture(scope="session", autouse=True)
def test_database():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        # DROP DATABASE blocks indefinitely on any other open connection -- a dev
        # server or a crashed run left connected turns `pytest` into a silent hang.
        # Evict them first so the suite is never at the mercy of a stray process.
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = 'crm_test' AND pid <> pg_backend_pid()"
            )
        )
        conn.execute(text("DROP DATABASE IF EXISTS crm_test"))
        conn.execute(text("CREATE DATABASE crm_test"))
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(test_database):
    Session = sessionmaker(bind=test_database, expire_on_commit=False)
    session = Session()
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
    session.commit()
    yield session
    session.close()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def users(db):
    admin = User(
        email="admin@test.com",
        hashed_password=hash_password("pw"),
        full_name="Admin",
        role=RoleEnum.admin,
    )
    rep = User(
        email="rep@test.com",
        hashed_password=hash_password("pw"),
        full_name="Rep",
        role=RoleEnum.rep,
    )
    other = User(
        email="other@test.com",
        hashed_password=hash_password("pw"),
        full_name="Other",
        role=RoleEnum.rep,
    )
    db.add_all([admin, rep, other])
    db.commit()
    return {"admin": admin, "rep": rep, "other": other}


@pytest.fixture
def token(client):
    def _token(email: str) -> dict[str, str]:
        resp = client.post("/auth/login", json={"email": email, "password": "pw"})
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    return _token


@pytest.fixture
def crm_data(db, users):
    company = Company(name="Acme", industry="Manufacturing", owner_id=users["rep"].id)
    db.add(company)
    db.commit()
    contact = Contact(
        company_id=company.id,
        first_name="Dana",
        last_name="Reyes",
        title="VP of Operations",
        owner_id=users["rep"].id,
    )
    db.add(contact)
    db.commit()
    rep_deal = Deal(
        name="Acme rollout",
        company_id=company.id,
        primary_contact_id=contact.id,
        owner_id=users["rep"].id,
        stage=DealStage.proposal,
        value=125000,
    )
    other_deal = Deal(
        name="Other rep deal",
        company_id=company.id,
        owner_id=users["other"].id,
        stage=DealStage.new,
        value=5000,
    )
    db.add_all([rep_deal, other_deal])
    db.commit()
    return {"company": company, "contact": contact, "deal": rep_deal, "other_deal": other_deal}


class FakeStructuredModel:
    """Stands in for `get_chat_model(...).with_structured_output(Schema)`."""

    def __init__(self, result):
        self._result = result

    def with_structured_output(self, schema):
        return self

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return self._result


@pytest.fixture
def fake_llm(monkeypatch):
    """Patch the single LLM construction point so no network call ever happens."""

    def _install(result):
        model = FakeStructuredModel(result)
        monkeypatch.setattr("app.agents.llm.get_chat_model", lambda name: model)
        monkeypatch.setattr(
            "app.agents.lead_scoring.graph.get_chat_model", lambda name: model
        )
        monkeypatch.setattr(
            "app.agents.follow_up.graph.get_chat_model", lambda name: model
        )
        monkeypatch.setattr(
            "app.agents.nl_query.graph.get_chat_model", lambda name: model
        )
        return model

    return _install

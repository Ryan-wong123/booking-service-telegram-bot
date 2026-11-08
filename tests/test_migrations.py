from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app import create_app
from app.extensions import db


def test_migrations_match_models(tmp_path):
    """Upgrading from scratch must give exactly the schema the models describe. If this fails, run
    `flask db migrate -m "..."` and commit the new file in migrations/versions/."""
    uri = f"sqlite:///{tmp_path / 'm.db'}"
    app = create_app({"SECRET_KEY": "x", "SQLALCHEMY_DATABASE_URI": uri})
    assert app.test_cli_runner().invoke(args=["init-db"]).exit_code == 0
    with create_engine(uri).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), db.metadata)
    assert diff == [], diff

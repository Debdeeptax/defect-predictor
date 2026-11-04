import pytest

from tests.helpers import PASSWORD, SAMPLE_DIR as SAMPLE, build_test_app  # noqa: F401


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    app = build_test_app(tmp_path_factory.mktemp("sdp"))
    yield app
    from app.extensions import db
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, email, password=PASSWORD, follow=True):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=follow)


@pytest.fixture
def dev(client):
    login(client, "dev@test.com")
    return client


@pytest.fixture
def qa(client):
    login(client, "qa@test.com")
    return client


@pytest.fixture
def admin(client):
    login(client, "admin@test.com")
    return client

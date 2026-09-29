import pytest
from httpx import AsyncClient

from app.core.limiter import limiter


@pytest.fixture(autouse=True)
def _fresh_limits():
    # Rate limits are per process; don't let other tests' sign-ups count here.
    limiter.reset()
    yield
    limiter.reset()


def _signup(email: str, **overrides) -> dict:
    return {"full_name": "Test User", "email": email, "phone": "0803 123 4567", "password": "testpassword", **overrides}


async def _register(client: AsyncClient, email: str, **overrides):
    return await client.post("/api/v1/auth/register", json=_signup(email, **overrides))


@pytest.mark.asyncio
async def test_register_user(client: AsyncClient):
    response = await _register(client, "Test@Example.com")
    assert response.status_code == 201, response.text
    data = response.json()
    # Signed straight in, with the account details.
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    user = data["user"]
    assert user["email"] == "test@example.com"
    assert user["phone"] == "08031234567"
    assert user["full_name"] == "Test User"
    assert user["is_active"] is True
    assert user["is_superuser"] is False
    assert user["email_verified"] is False
    assert "id" in user
    assert "hashed_password" not in user


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(client: AsyncClient):
    assert (await _register(client, "dup@example.com")).status_code == 201
    again = await _register(client, "DUP@example.com")
    assert again.status_code == 409
    assert again.json()["detail"] == "An account with this email already exists."


@pytest.mark.asyncio
@pytest.mark.parametrize("field, value", [
    ("phone", "12345"),
    ("password", "short"),
    ("full_name", " "),
    ("email", "not-an-email"),
])
async def test_register_validates_input(client: AsyncClient, field, value):
    body = {**_signup("valid@example.com"), field: value}
    response = await client.post("/api/v1/auth/register", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_user(client: AsyncClient):
    await _register(client, "login@example.com")

    # OAuth2 form login (as used by the API docs)...
    response = await client.post(
        "/api/v1/auth/login", data={"username": "login@example.com", "password": "testpassword"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"

    # ...and the JSON login the storefront uses.
    response = await client.post(
        "/api/v1/auth/login/json", json={"email": "Login@Example.com", "password": "testpassword"}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


@pytest.mark.asyncio
async def test_login_rejects_wrong_password_and_unknown_email(client: AsyncClient):
    await _register(client, "wrong@example.com")
    wrong = await client.post("/api/v1/auth/login/json", json={"email": "wrong@example.com", "password": "not-it-at-all"})
    unknown = await client.post("/api/v1/auth/login/json", json={"email": "nobody@example.com", "password": "testpassword"})
    # Same answer either way, so the endpoint can't be used to find accounts.
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


@pytest.mark.asyncio
async def test_read_users_me(client: AsyncClient):
    token = (await _register(client, "me@example.com")).json()["access_token"]

    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"

    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"})).status_code == 401

"""Auth tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_signup(client: AsyncClient):
    response = await client.post("/auth/signup", json={
        "email": "new@example.com",
        "password": "password123",
        "name": "New User",
    })
    assert response.status_code == 201
    data = response.json()
    assert "token" in data
    assert data["user"]["email"] == "new@example.com"


@pytest.mark.asyncio
async def test_signup_duplicate_email(client: AsyncClient):
    await client.post("/auth/signup", json={
        "email": "dup@example.com",
        "password": "password123",
        "name": "User 1",
    })
    response = await client.post("/auth/signup", json={
        "email": "dup@example.com",
        "password": "password456",
        "name": "User 2",
    })
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    await client.post("/auth/signup", json={
        "email": "login@example.com",
        "password": "password123",
        "name": "Login User",
    })
    response = await client.post("/auth/login", json={
        "email": "login@example.com",
        "password": "password123",
    })
    assert response.status_code == 200
    assert "token" in response.json()


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient):
    response = await client.post("/auth/login", json={
        "email": "nonexistent@example.com",
        "password": "wrongpassword",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient):
    signup_response = await client.post("/auth/signup", json={
        "email": "me@example.com",
        "password": "password123",
        "name": "Me User",
    })
    token = signup_response.json()["token"]

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


@pytest.mark.asyncio
async def test_get_me_no_token(client: AsyncClient):
    response = await client.get("/auth/me")
    assert response.status_code == 401

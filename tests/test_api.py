from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app


def test_authenticated_data_flow_requires_real_model() -> None:
    with TestClient(app) as client:
        catalog = client.get("/api/v1/catalog")
        assert catalog.status_code == 200
        assert len(catalog.json()["regions"]) == 5

        registration = client.post("/api/v1/auth/register", json={
            "email": "test@forenode.example",
            "password": "secure-password-2026",
            "full_name": "Test Analyst",
        })
        assert registration.status_code in (201, 409)
        if registration.status_code == 409:
            registration = client.post("/api/v1/auth/login", data={
                "username": "test@forenode.example", "password": "secure-password-2026"
            })
        token = registration.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        inventory = client.post("/api/v1/inventory", headers=headers, json={
            "product_code": "papa-pastusa",
            "region_code": "pasto",
            "quantity_kg": 1250,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "source_reference": "test-inventory-ledger",
        })
        assert inventory.status_code == 201
        matching = client.post("/api/v1/matching/engine", headers=headers, json={
            "product_code": "papa-pastusa", "region_code": "pasto", "target_date": datetime.now(timezone.utc).date().isoformat()
        })
        assert matching.status_code == 409
        assert "modelo entrenado" in matching.json()["detail"]

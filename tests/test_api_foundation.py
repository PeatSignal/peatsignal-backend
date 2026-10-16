from conftest import AsgiClient


def test_health_is_public_and_contains_no_database_claim(client: AsgiClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "PeatSignal API",
        "version": "0.1.0",
        "environment": "development",
    }


def test_authentication_resolves_both_demo_roles(client: AsgiClient) -> None:
    coordinator = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer demo-coordinator-token"}
    )
    officer = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer demo-field-officer-token"}
    )

    assert coordinator.status_code == 200
    assert coordinator.json()["role"] == "coordinator"
    assert officer.status_code == 200
    assert officer.json()["role"] == "field_officer"


def test_authentication_rejects_missing_and_invalid_tokens(client: AsgiClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer definitely-invalid"}
        ).status_code
        == 401
    )


def test_task_creation_enforces_coordinator_role_before_data_access(
    client: AsgiClient,
) -> None:
    payload = {
        "mode": "CURRENT_MONITORING",
        "title": "Periksa anomali",
        "priority": "HIGH",
        "hotspot_id": "11111111-1111-4111-8111-111111111111",
    }
    officer = client.post(
        "/api/v1/tasks",
        headers={"Authorization": "Bearer demo-field-officer-token"},
        json=payload,
    )

    assert officer.status_code == 403


def test_openapi_publishes_planned_contracts_without_tokens(client: AsgiClient) -> None:
    document = client.get("/openapi.json").json()
    paths = document["paths"]
    expected_paths = {
        "/health",
        "/api/v1/auth/me",
        "/api/v1/stations",
        "/api/v1/stations/{station_id}/groundwater",
        "/api/v1/hotspots",
        "/api/v1/priorities",
        "/api/v1/users",
        "/api/v1/tasks",
        "/api/v1/tasks/{task_id}",
        "/api/v1/tasks/{task_id}/reports",
        "/api/v1/ml/metrics",
        "/api/v1/ml/forecast",
    }

    assert expected_paths <= set(paths)
    rendered = str(document)
    assert "demo-coordinator-token" not in rendered
    assert "demo-field-officer-token" not in rendered


def test_cors_allows_configured_frontend_origin(client: AsgiClient) -> None:
    response = client.request(
        "OPTIONS",
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


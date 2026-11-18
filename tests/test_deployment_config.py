from pathlib import Path

import yaml


def test_public_blueprint_cannot_enable_paid_execution_or_embed_secrets():
    service=yaml.safe_load((Path(__file__).resolve().parents[1]/"render.yaml").read_text(encoding="utf-8"))["services"][0]
    environment={entry["key"]:entry.get("value") for entry in service["envVars"]}
    assert environment["VAANIBENCH_ENV"]=="production"
    assert environment["VAANIBENCH_LIVE_ENABLED"]=="false"
    assert environment["VAANIBENCH_PERSISTENT_STORAGE"]=="false"
    assert not any("API_KEY" in key or "PASSWORD" in key for key in environment)
    assert service["numInstances"]==1
    assert "--workers 1" in service["startCommand"]
    assert "--host 0.0.0.0" in service["startCommand"] and "$PORT" in service["startCommand"]
    assert "--locked" in service["buildCommand"] and "--no-dev" in service["buildCommand"]
    assert service["healthCheckPath"]=="/healthz" and service["autoDeployTrigger"]=="checksPass"

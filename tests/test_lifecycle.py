from __future__ import annotations

import json

import pytest

from setup.lifecycle import build_lifecycle_update, configured_instances


@pytest.mark.parametrize(
    ("action", "policy"),
    [("resume", "ALWAYS"), ("suspend", "NEVER")],
)
def test_lifecycle_update_is_narrow_and_parameterized(action, policy):
    update = build_lifecycle_update(
        project="sample-project",
        region="us-central1",
        cluster="sample-cluster",
        instance="sample-instance",
        action=action,
    )
    assert update.url.endswith("?updateMask=activationPolicy")
    assert "/v1/projects/sample-project/locations/us-central1/" in update.url
    assert json.loads(update.body)["activationPolicy"] == policy


def test_lifecycle_update_rejects_unknown_actions():
    with pytest.raises(ValueError, match="resume or suspend"):
        build_lifecycle_update(
            project="sample-project",
            region="us-central1",
            cluster="sample-cluster",
            instance="sample-instance",
            action="delete",
        )


def test_lifecycle_manages_primary_and_read_pool_once():
    assert configured_instances(
        "productivity-instance",
        "productivity-read-pool,productivity-instance",
    ) == ("productivity-instance", "productivity-read-pool")


def test_lifecycle_rejects_unsafe_instance_names():
    with pytest.raises(ValueError, match="unsupported"):
        configured_instances("primary", "other/instance")

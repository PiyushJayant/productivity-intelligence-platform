from __future__ import annotations

import json
import uuid

import pytest

from productivity_intelligence import membership

TENANT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
SUBJECT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


def test_decode_rows_accepts_toolbox_result_shapes():
    assert membership._decode_rows(json.dumps([{"role": "member"}])) == [
        {"role": "member"}
    ]
    assert membership._decode_rows(json.dumps({"rows": [{"role": "viewer"}]})) == [
        {"role": "viewer"}
    ]


def test_authorize_requires_one_active_valid_role(monkeypatch):
    store = membership.ToolboxMembershipStore()
    monkeypatch.setattr(store, "_invoke", lambda *_args, **_kwargs: [{"role": "admin"}])
    assert store.authorize(
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        issuer="issuer",
        external_subject="external",
    ) == "admin"
    monkeypatch.setattr(store, "_invoke", lambda *_args, **_kwargs: [])
    with pytest.raises(membership.MembershipDeniedError):
        store.authorize(
            tenant_id=TENANT_ID,
            subject_id=SUBJECT_ID,
            issuer="issuer",
            external_subject="external",
        )


def test_membership_role_input_is_allowlisted():
    store = membership.ToolboxMembershipStore()
    with pytest.raises(ValueError, match="unsupported"):
        store.update_role(
            tenant_id=TENANT_ID,
            actor_subject_id=SUBJECT_ID,
            target_subject_id=SUBJECT_ID,
            role="superuser",
        )


def test_agent_toolsets_exclude_identity_administration():
    source = __import__("pathlib").Path("mcp_toolbox/tools.yaml").read_text()
    agent_section, private_section = source.split("  identity-admin-tools:", 1)
    assert "authorize_identity" in source
    assert "provision_tenant_member" in private_section
    for toolset in ("task-tools", "notes-tools", "calendar-tools"):
        start = agent_section.index(f"  {toolset}:")
        block = agent_section[start:]
        assert "authorize_identity" not in block
        assert "provision_tenant_member" not in block

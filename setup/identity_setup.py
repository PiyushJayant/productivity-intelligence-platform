"""Phase 0 Identity Platform configuration and bootstrap-user validation."""

from __future__ import annotations

import argparse
import json
import os

import google.auth
from google.auth.transport.requests import AuthorizedSession


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def configure(*, apply: bool) -> dict[str, object]:
    project = required("IDENTITY_PLATFORM_PROJECT_ID")
    subject = required("BOOTSTRAP_IDP_SUBJECT")
    if subject.startswith("replace-"):
        raise ValueError("BOOTSTRAP_IDP_SUBJECT is still a placeholder")
    desired = {
        "project": project,
        "signIn": {
            "email": {
                "enabled": True,
                "passwordRequired": True,
            },
            "allowDuplicateEmails": False,
        },
        "bootstrap_subject": subject,
        "public_signup_disabled": True,
    }
    if not apply:
        return desired
    if required("PHASE5_ACTIVE").lower() != "true":
        raise RuntimeError("Identity Platform mutation is restricted to Phase 5")
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    session = AuthorizedSession(credentials)
    config_url = (
        "https://identitytoolkit.googleapis.com/admin/v2/"
        f"projects/{project}/config?updateMask=signIn.email,signIn.allowDuplicateEmails"
    )
    response = session.patch(config_url, json={"signIn": desired["signIn"]}, timeout=30)
    response.raise_for_status()
    user_url = (
        "https://identitytoolkit.googleapis.com/v1/"
        f"projects/{project}/accounts:lookup"
    )
    lookup = session.post(user_url, json={"localId": [subject]}, timeout=30)
    lookup.raise_for_status()
    users = lookup.json().get("users", [])
    if len(users) != 1:
        raise RuntimeError("bootstrap Identity Platform subject does not exist")
    claims = {
        required("IDENTITY_TENANT_CLAIM"): required("DEFAULT_TENANT_ID"),
        required("IDENTITY_ROLE_CLAIM"): "owner",
    }
    update = session.post(
        f"https://identitytoolkit.googleapis.com/v1/projects/{project}/accounts:update",
        json={"localId": subject, "customAttributes": json.dumps(claims)},
        timeout=30,
    )
    update.raise_for_status()
    return {**desired, "validated": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(configure(apply=args.apply))


if __name__ == "__main__":
    main()

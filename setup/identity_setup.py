"""Phase 1 Identity Platform configuration and bootstrap-user validation."""

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


def boolean(name: str) -> bool:
    value = required(name).lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def integer(name: str, minimum: int, maximum: int) -> int:
    try:
        value = int(required(name))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def configure(*, apply: bool) -> dict[str, object]:
    project = required("IDENTITY_PLATFORM_PROJECT_ID")
    subject = required("BOOTSTRAP_IDP_SUBJECT")
    if subject.startswith("replace-"):
        raise ValueError("BOOTSTRAP_IDP_SUBJECT is still a placeholder")
    controlled_registration = boolean("IDENTITY_CONTROLLED_REGISTRATION")
    before_create_url = os.getenv("IDENTITY_BEFORE_CREATE_URL", "").strip()
    min_password_length = integer("IDENTITY_PASSWORD_MIN_LENGTH", 6, 30)
    max_password_length = integer("IDENTITY_PASSWORD_MAX_LENGTH", 6, 4096)
    if min_password_length > max_password_length:
        raise ValueError("IDENTITY_PASSWORD_MIN_LENGTH cannot exceed the maximum")
    password_policy = {
        "enforcementState": "ENFORCE",
        "forceUpgradeOnSignin": True,
        "constraints": {
            "requireUppercase": True,
            "requireLowercase": True,
            "requireNonAlphanumeric": True,
            "requireNumeric": True,
            "minLength": min_password_length,
            "maxLength": max_password_length,
        },
    }
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
        "controlled_registration": controlled_registration,
        "public_signup_disabled": controlled_registration and bool(before_create_url),
        "before_create_url_configured": bool(before_create_url),
        "passwordPolicyConfig": password_policy,
    }
    if not apply:
        return desired
    if required("PHASE5_ACTIVE").lower() != "true":
        raise RuntimeError("Identity Platform mutation is restricted to Phase 5")
    if controlled_registration and not before_create_url:
        raise ValueError(
            "IDENTITY_BEFORE_CREATE_URL is required for controlled registration"
        )
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    session = AuthorizedSession(credentials)
    update_mask = "signIn.email,signIn.allowDuplicateEmails,passwordPolicyConfig"
    config_body = {
        "signIn": desired["signIn"],
        "passwordPolicyConfig": password_policy,
    }
    if controlled_registration:
        update_mask += ",blockingFunctions"
        config_body["blockingFunctions"] = {
            "triggers": {"beforeCreate": {"functionUri": before_create_url}}
        }
    config_url = (
        "https://identitytoolkit.googleapis.com/admin/v2/"
        f"projects/{project}/config?updateMask={update_mask}"
    )
    response = session.patch(config_url, json=config_body, timeout=30)
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

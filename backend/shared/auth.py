"""Caller identity from the API Gateway JWT authorizer (Cognito)."""

import os


def _claims(event: dict) -> dict:
    authz = (event.get("requestContext") or {}).get("authorizer") or {}
    # HTTP API payload 2.0 -> authorizer.jwt.claims ; payload 1.0 -> authorizer.claims
    return (authz.get("jwt") or {}).get("claims") or authz.get("claims") or {}


def caller_groups(event: dict) -> set:
    raw = _claims(event).get("cognito:groups", "")
    if isinstance(raw, list):
        return {str(g) for g in raw}
    # API Gateway flattens arrays to "[admins other]"
    return {g for g in str(raw).strip("[]").replace(",", " ").split() if g}


def caller_id(event: dict) -> str:
    c = _claims(event)
    return c.get("email") or c.get("username") or c.get("sub") or "anonymous"


def is_admin(event: dict) -> bool:
    """When auth is disabled (local dev) everyone is treated as admin."""
    if os.environ.get("AUTH_ENABLED", "false").lower() != "true":
        return True
    return "admins" in caller_groups(event)

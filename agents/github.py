"""Post (or update) the triage report as a single PR comment.

Uses GITHUB_TOKEN, GITHUB_REPOSITORY and PR_NUMBER (set automatically in the
workflow). Without them the report is only written locally.
"""

from __future__ import annotations

import json
import os
import urllib.request

API = "https://api.github.com"


def _req(method: str, url: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "policycraft-triage",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"null")


def post_pr_comment(markdown: str, marker: str) -> str:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr = os.environ.get("PR_NUMBER")
    if not (token and repo and pr):
        return "local (no GITHUB_TOKEN/GITHUB_REPOSITORY/PR_NUMBER)"

    comments = _req("GET", f"{API}/repos/{repo}/issues/{pr}/comments?per_page=100", token) or []
    existing = next((c for c in comments if marker in (c.get("body") or "")), None)
    if existing:
        _req("PATCH", f"{API}/repos/{repo}/issues/comments/{existing['id']}", token, {"body": markdown})
        return f"PR #{pr} (updated comment {existing['id']})"
    created = _req("POST", f"{API}/repos/{repo}/issues/{pr}/comments", token, {"body": markdown})
    return f"PR #{pr} (comment {created.get('id')})"

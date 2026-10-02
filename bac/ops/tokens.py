"""External source credentials retired: sources are owner/worker-only."""

from fastapi import HTTPException


def issue(s, user, label, documents, days):
    raise HTTPException(403, "External source access is disabled")


def authenticate(request):
    raise HTTPException(403, "External source access is disabled")

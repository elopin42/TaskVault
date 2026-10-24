from functools import wraps
from urllib.parse import quote

from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from .identity import get_wallet


def _wants_json(request) -> bool:
    accept = request.headers.get("Accept", "")
    return "application/json" in accept or request.headers.get("X-Requested-With") == "fetch"


def wallet_required(view):
    """Require a signed-in wallet. Browsers bounce to the landing page with ?next=;
    fetch() callers get a 401 JSON body."""

    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if get_wallet(request) is None:
            if _wants_json(request):
                return JsonResponse({"ok": False, "error": "wallet_required"}, status=401)
            return redirect(f"{reverse('core:landing')}?next={quote(request.get_full_path())}")
        return view(request, *args, **kwargs)

    return _wrapped

"""Dashboard (signed-in home) and public wallet profiles. No models of its own: everything is
read from projects through dashboard/services.py."""

import logging

from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render

from accounts.decorators import wallet_required
from accounts.identity import get_wallet
from accounts.models import WalletUser

from . import services

logger = logging.getLogger(__name__)

MAX_DISPLAY_NAME = 80


@wallet_required
def home(request: HttpRequest) -> HttpResponse:
    wallet = get_wallet(request)
    todo = services.todo_items(wallet)
    return render(
        request,
        "dashboard/home.html",
        {
            "wallet": wallet,
            "todo": todo,
            "todo_act": sum(1 for it in todo if it["tone"] == "act"),
            "company_stats": services.company_stats(wallet),
            "freelancer_stats": services.freelancer_stats(wallet),
            "activity": services.recent_activity(wallet),
        },
    )


def profile(request: HttpRequest, address: str) -> HttpResponse:
    """Public page for a wallet (no login). The owner can edit their display name here (POST)."""
    wallet = WalletUser.objects.filter(stellar_address=address).first()
    if wallet is None:
        raise Http404("wallet inconnu")
    viewer = get_wallet(request)
    is_me = viewer is not None and viewer.pk == wallet.pk

    if request.method == "POST":
        if not is_me:
            return HttpResponseForbidden("Seul le propriétaire du wallet peut modifier ce profil.")
        name = (request.POST.get("display_name") or "").strip()[:MAX_DISPLAY_NAME]
        wallet.display_name = name
        wallet.save(update_fields=["display_name"])
        logger.info("profile renamed wallet=%s", wallet.pk)
        messages.success(request, "Nom affiché mis à jour." if name else "Nom affiché effacé.")
        return redirect("dashboard:profile", address=wallet.stellar_address)

    return render(
        request,
        "dashboard/profile.html",
        {"profile": wallet, "is_me": is_me, "stats": services.profile_stats(wallet), "max_name": MAX_DISPLAY_NAME},
    )

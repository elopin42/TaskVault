"""Dashboard (signed-in home) and public wallet profiles. No models of its own: everything is
read from auctions / payments. Skeleton — the view-model builders land in services.py."""

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

from accounts.decorators import wallet_required
from accounts.identity import get_wallet
from accounts.models import WalletUser


@wallet_required
def home(request: HttpRequest) -> HttpResponse:
    wallet = get_wallet(request)
    return render(request, "dashboard/home.html", {"wallet": wallet})


def profile(request: HttpRequest, address: str) -> HttpResponse:
    wallet = WalletUser.objects.filter(stellar_address=address).first()
    if wallet is None:
        raise Http404("wallet inconnu")
    return render(request, "dashboard/profile.html", {"profile": wallet, "is_me": get_wallet(request) == wallet})

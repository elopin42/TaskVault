"""Who is calling? The session carries the wallet; this resolves it once per request."""

from django.http import HttpRequest

from .models import WalletUser

SESSION_ADDRESS_KEY = "wallet_address"
SESSION_USER_KEY = "wallet_user_id"
SESSION_CHALLENGE_KEY = "wallet_challenge"


def get_wallet_address(request: HttpRequest) -> str:
    return request.session.get(SESSION_ADDRESS_KEY, "") or ""


def get_wallet(request: HttpRequest) -> WalletUser | None:
    """The signed-in WalletUser, or None. Cached on the request object."""
    cached = getattr(request, "_lowbid_wallet", None)
    if cached is not None:
        return cached or None
    user_id = request.session.get(SESSION_USER_KEY)
    wallet = WalletUser.objects.filter(pk=user_id).first() if user_id else None
    request._lowbid_wallet = wallet or False
    return wallet


def login_wallet(request: HttpRequest, wallet: WalletUser) -> None:
    request.session.cycle_key()
    request.session[SESSION_ADDRESS_KEY] = wallet.stellar_address
    request.session[SESSION_USER_KEY] = wallet.pk
    request.session.pop(SESSION_CHALLENGE_KEY, None)
    request._lowbid_wallet = wallet


def logout_wallet(request: HttpRequest) -> None:
    request.session.flush()
    request._lowbid_wallet = False

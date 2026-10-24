from .identity import get_wallet, get_wallet_address


def wallet(request):
    return {
        "wallet_address": get_wallet_address(request),
        "wallet_user": get_wallet(request),
    }

"""Template context shared by every page (base.html, navbar)."""

from django.conf import settings
from django.urls import NoReverseMatch, reverse


def site(request):
    return {
        "LOWBID_ASSET_VERSION": settings.LOWBID_ASSET_VERSION,
        "STELLAR_NETWORK": settings.STELLAR_NETWORK,
        "STELLAR_NETWORK_PASSPHRASE": settings.STELLAR_NETWORK_PASSPHRASE,
        "STELLAR_HORIZON_URL": settings.STELLAR_HORIZON_URL,
        "STELLAR_SOROBAN_RPC_URL": settings.STELLAR_SOROBAN_RPC_URL,
        "STELLAR_USDC_ISSUER": settings.STELLAR_USDC_ISSUER,
        "STELLAR_USDC_CODE": settings.STELLAR_USDC_CODE,
    }


# Navbar entries. Each one names the URL the `auctions` app is expected to
# register; until it exists the literal fallback path is used, so the shell
# renders before the domain apps land. `wallet` marks links that need a session.
# `short` is the label of the mobile tab bar (partials/tabbar.html); `primary` renders the raised tab.
NAV_LINKS = (
    {"label": "Besoins", "short": "Besoins", "url_name": "auctions:need_list", "fallback": "/besoins/", "icon": "fa-list-ul", "wallet": False},
    {"label": "Mes enchères", "short": "Enchères", "url_name": "auctions:my_bids", "fallback": "/mes-encheres/", "icon": "fa-gavel", "wallet": True},
    {"label": "Poster un besoin", "short": "Poster", "url_name": "auctions:need_create", "fallback": "/besoins/nouveau/", "icon": "fa-plus", "wallet": True, "primary": True},
    {"label": "Mes besoins", "short": "Mes besoins", "url_name": "auctions:my_needs", "fallback": "/mes-besoins/", "icon": "fa-folder-open", "wallet": True},
    {"label": "Tableau de bord", "short": "Tableau", "url_name": "dashboard:home", "fallback": "/tableau-de-bord/", "icon": "fa-gauge-high", "wallet": True},
)


def _resolve(url_name: str, fallback: str) -> str:
    try:
        return reverse(url_name)
    except NoReverseMatch:
        return fallback


def nav_links(request):
    path = request.path
    links = []
    for item in NAV_LINKS:
        href = _resolve(item["url_name"], item["fallback"])
        links.append(
            {
                "label": item["label"],
                "short": item.get("short", item["label"]),
                "href": href,
                "icon": item["icon"],
                "wallet": item["wallet"],
                "primary": item.get("primary", False),
                "active": False,
            }
        )
    # Only the most specific match is active: /besoins/nouveau/ must not also light up "Besoins".
    matching = [link for link in links if link["href"] != "/" and path.startswith(link["href"])]
    if matching:
        max(matching, key=lambda link: len(link["href"]))["active"] = True
    return {"nav_links": links}

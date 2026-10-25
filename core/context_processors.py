"""Template context shared by every page (base.html, navbar)."""

from django.conf import settings
from django.urls import NoReverseMatch, reverse

from payments import stellar


def site(request):
    """Per-request constants for base.html (window.LOWBID) + the payment asset label (`asset_code`)."""
    return {
        "LOWBID_ASSET_VERSION": settings.LOWBID_ASSET_VERSION,
        "STELLAR_NETWORK": settings.STELLAR_NETWORK,
        "STELLAR_NETWORK_PASSPHRASE": settings.STELLAR_NETWORK_PASSPHRASE,
        "STELLAR_HORIZON_URL": settings.STELLAR_HORIZON_URL,
        "STELLAR_SOROBAN_RPC_URL": settings.STELLAR_SOROBAN_RPC_URL,
        "asset_code": stellar.asset_code(),
        "asset_issuer": stellar.asset_issuer(),
        "asset_native": stellar.is_native(),
        "payment_mode": stellar.payment_mode(),
    }


# Navbar entries. Each one names the URL the `projects` / `dashboard` app registers; until it
# exists the literal fallback path is used, so the shell renders before the domain apps land.
# `wallet` marks links that need a session. `short` is the label of the mobile tab bar
# (partials/tabbar.html); `primary` renders the raised tab.
NAV_LINKS = (
    {"label": "Projects", "short": "Projects", "url_name": "projects:project_list", "fallback": "/projets/", "icon": "fa-diagram-project", "wallet": False},
    {"label": "Board", "short": "Board", "url_name": "projects:board", "fallback": "/taches/", "icon": "fa-table-columns", "wallet": True},
    {"label": "New project", "short": "Create", "url_name": "projects:project_create", "fallback": "/projets/nouveau/", "icon": "fa-plus", "wallet": True, "primary": True},
    {"label": "My projects", "short": "My projects", "url_name": "projects:my_projects", "fallback": "/mes-projets/", "icon": "fa-folder-open", "wallet": True},
    {"label": "Dashboard", "short": "Home", "url_name": "dashboard:home", "fallback": "/tableau-de-bord/", "icon": "fa-gauge-high", "wallet": True},
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
    # Only the most specific match is active: /projets/nouveau/ must not also light up "Projects".
    matching = [link for link in links if link["href"] != "/" and path.startswith(link["href"])]
    if matching:
        max(matching, key=lambda link: len(link["href"]))["active"] = True
    return {"nav_links": links}

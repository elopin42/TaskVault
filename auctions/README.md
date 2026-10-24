# auctions (placeholder)

Owned by the auctions agent: Need / Bid models, scoring (40 % price, 30 % delay,
30 % tag match), the "Recommandé" badge, winner selection.

The navbar already points at these URL names — register them here and the links
light up (see `core/context_processors.py::NAV_LINKS`):

| URL name                | Expected path        |
|-------------------------|----------------------|
| `auctions:need_list`    | `/besoins/`          |
| `auctions:need_create`  | `/besoins/nouveau/`  |
| `auctions:my_bids`      | `/mes-encheres/`     |

Mounted at `/` in `lowbid/urls.py`. Templates go in `templates/auctions/`.
Protect views with `@wallet_required` and read the caller with
`accounts.identity.get_wallet(request)`.

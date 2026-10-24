# auctions

Need / Bid, the rules R1–R14 (`services.py`), the score (`scoring.py`), the pages and the JSON
endpoints the detail page polls. Full map in `docs/ARCHITECTURE.md` → **Auctions**.

```bash
python manage.py seed_demo --flush      # 3 wallets, 2 open needs, 1 closed (ready to award), 1 awarded
python manage.py test auctions
```

| URL name | Path |
|----------|------|
| `auctions:need_list` | `/besoins/` |
| `auctions:need_create` | `/besoins/nouveau/` (`?demo=1` → 5-min deadline) |
| `auctions:need_detail` | `/besoins/<pk>/` |
| `auctions:my_bids` | `/mes-encheres/` |
| `auctions:my_needs` | `/mes-besoins/` |
| `auctions:need_bids_json` | `GET /besoins/<pk>/encheres.json` |
| `auctions:bid_create` | `POST /besoins/<pk>/encherir/` |
| `auctions:need_close` | `POST /besoins/<pk>/cloturer/` |
| `auctions:need_award` | `POST /besoins/<pk>/choisir/<bid_pk>/` |
| `auctions:need_cancel` | `POST /besoins/<pk>/annuler/` |

Templates live in `templates/auctions/`; `templates/payments/_escrow_panel.html` is included on an
awarded need with `need` + `winning_bid` (the payments app owns that file).

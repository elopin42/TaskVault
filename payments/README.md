# payments

Escrow (Trustless Work) and Plan B (direct USDC payment) for an awarded `auctions.Need`.

- `models.py` — `Escrow`, one per need (`need.escrow`): mode, contract id, every tx hash, status.
- `services.py` — the flow: `prepare_<step>` / `confirm_<step>` per step, role + state gates, `next_action()`.
  **The state table for both modes is in its module docstring.**
- `views.py` / `urls.py` — JSON endpoints under `/pay/` driven by `static/js/lowbid-pay.js`.
- `trustless_work.py` — Trustless Work v1 REST client. `stellar.py` — XDR builders / parser / Horizon.
- `templatetags/payments_extras.py` — `{% escrow_panel need wallet %}` → `templates/payments/_escrow_panel.html`.
- Tests: `tests.py` (clients, offline) and `tests_flow.py` (HTTP flow, both modes, mocked network).

Switch to Plan B: `LOWBID_PAYMENT_MODE=direct`. Full write-up: `docs/ARCHITECTURE.md` → Payments.

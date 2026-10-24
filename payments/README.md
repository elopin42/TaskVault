# payments

One Trustless Work single-release escrow **per task** (escrow mode) or one signed payment at
validation (direct mode) for a `projects.Task`.

- `models.py` — `Escrow`, one per task (`task.escrow`): mode, contract id, every tx hash, status.
- `services.py` — the flow: `prepare_<step>` / `confirm_<step>` per step, role + state gates,
  `next_action()`, `project_funding()`, the `on_task_validated` hook. **The state table for both
  modes is in its module docstring.**
- `views.py` / `urls.py` — JSON endpoints under `/pay/` driven by `static/js/lowbid-pay.js`.
- `trustless_work.py` — Trustless Work v1 REST client. `stellar.py` — asset, XDR builders / parser / Horizon.
- `templatetags/payments_extras.py` — `{% escrow_panel task wallet %}` → `templates/payments/_escrow_panel.html`.
- Tests: `tests.py` (clients, offline) and `tests_flow.py` (HTTP flow, both modes, mocked network).

Switch to the fallback: `LOWBID_PAYMENT_MODE=direct`. Full write-up: `docs/ARCHITECTURE.md` → Payments.

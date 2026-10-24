# projects

The task board: a company's `Project` is split into fixed-price `Task`s, freelances send an
`Application` (message + tags, no price), the company chooses one per task, the chosen freelance
delivers a link, the company validates with a `Rating` (1–5). Nothing Stellar-related lives here.

- `models.py` — `Project` (`draft → funded → closed`, `with_totals()`), `Task` (`open → taken → delivered → paid`),
  `Application` (`pending → chosen | rejected`, stored `score`, one per freelance per task), `Rating` (one per task).
- `services.py` — **every rule** (`create_project`, `add_task`, `delete_task`, `apply`, `choose`, `deliver`,
  `validate`, `mark_paid`, `rescore`), raising `ProjectError(code, message)`. Payment hooks: `mark_paid(task)` is the
  only way a task becomes `paid` (called by payments); `_after_validate` hands over to
  `payments.services.on_task_validated`; `_before_deliver` refuses a DB-only delivery in escrow mode. `payments` is
  imported lazily (it imports this module).
- `scoring.py` — `40 × [paid task with this company] + 8 × average rating from this company + 20 × tag ratio`,
  `is_validated` (« Validé »), `recommended_pk` (« Recommandé »).
- `views.py` / `urls.py` — pages (`/projets/…`, `/taches/…`, `/mes-projets/`) and the JSON endpoints called through
  `Lowbid.api` (add/delete task, apply, choose, deliver, validate, `candidats.json`); `ERROR_STATUS` maps codes to HTTP.
- `forms.py` — `ProjectForm`. `management/commands/seed_demo.py` — the demo dataset (`make seed`).
- Templates in `templates/projects/`, page JS in `static/js/lowbid-projects.js`. Tests: `tests.py`.

Rules R1–R24 and the worked score example: `docs/PRODUCT.md`. Flows and hooks: `docs/ARCHITECTURE.md`.

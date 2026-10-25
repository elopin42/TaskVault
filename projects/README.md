# projects

The task board: a company's `Project` is split into `Task`s with a budget, freelances send an
`Application` (price ≤ budget + message + tags), the company chooses one per task at that price, the chosen freelance
delivers a link, the company validates with a `Rating` (1–5). Nothing Stellar-related lives here.

- `models.py` — `Project` (`draft → funded → closed`, queryset `with_totals()` / `active()`), `Task` (`open → taken → delivered → paid`),
  `Application` (`pending → chosen | rejected`, shown « Not selected », stored `score`, one per freelance per task), `Rating` (one per task, note 1–5).
- `services.py` — **every rule** (`create_project`, `add_task`, `delete_task`, `apply`, `choose`, `deliver`,
  `validate`, `mark_paid`, `rescore`), raising `ProjectError(code, message)`. Payment hooks: `mark_paid(task)` is the
  only way a task becomes `paid` (called by payments); `_after_validate` hands over to
  `payments.services.on_task_validated`; `_before_deliver` refuses a DB-only delivery in escrow mode. `payments` is
  imported lazily (it imports this module).
- `scoring.py` — `40 × [paid task with this company] + 8 × average rating from this company + 20 × tag ratio`,
  `is_validated` (« Validated »: ≥ 1 paid task and average ≥ 3), `recommended_pk` (« Recommended »: best pending score, earliest on ties).
- `views.py` / `urls.py` — pages (`/projets/…`, `/taches/…`, `/mes-projets/`) and the JSON endpoints called through
  `Lowbid.api` (`projets/<pk>/taches/ajouter/`, `taches/<pk>/supprimer/`, `postuler/`, `choisir/<app_pk>/`, `livrer/`,
  `valider/`, `candidats.json`); `ERROR_STATUS` maps codes to HTTP, `BOARD_COLUMNS` / `LIST_SORTS` drive the kanban and the list.
- `forms.py` — `ProjectForm`. `management/commands/seed_demo.py` — the demo dataset (`make seed`).
- Templates in `templates/projects/`, page JS in `static/js/lowbid-projects.js`. Tests: `tests.py`.

Rules R1–R24 and the worked score example: `docs/PRODUCT.md`. Flows and hooks: `docs/ARCHITECTURE.md`.

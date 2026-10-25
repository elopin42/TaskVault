"""Task.budget: the company's maximum survives the choice of a cheaper freelance ("up to 500 → 480")."""
from decimal import Decimal

from django.urls import reverse

from . import services
from .models import Task
from .tests import BaseProjectTest, app_of


class BudgetTests(BaseProjectTest):
    def choose_t2_at(self, price: str) -> Task:
        services.apply(self.t2, self.a, "A", ["stellar"], price=price)
        return services.choose(self.t2, app_of(self.t2, self.a), self.company)

    def test_add_task_sets_budget_to_price(self):
        self.assertEqual(self.t2.budget, Decimal("500"))
        self.assertEqual(self.t2.price, Decimal("500"))
        self.assertFalse(self.t2.negotiated)

    def test_choose_lower_bid_keeps_budget(self):
        task = self.choose_t2_at("480")
        task.refresh_from_db()
        self.assertEqual(task.price, Decimal("480"))
        self.assertEqual(task.budget, Decimal("500"))
        self.assertTrue(task.negotiated)

    def test_create_without_budget_falls_back_to_price(self):
        task = Task.objects.create(project=self.project, title="Extra", price=Decimal("120"))
        task.refresh_from_db()
        self.assertEqual(task.budget, Decimal("120"))

    def test_project_page_shows_budget_only_for_negotiated_tasks(self):
        self.choose_t2_at("480")
        services.apply(self.t1, self.b, "B", ["django"])  # full budget (300)
        services.choose(self.t1, app_of(self.t1, self.b), self.company)
        html = self.client.get(reverse("projects:project_detail", args=[self.project.pk])).content.decode()
        self.assertIn('data-task-budget="500"', html)
        self.assertNotIn('data-task-budget="300"', html)
        self.assertIn("up to 500", html)
        # [data-kpi-total] stays the sum of prices (300 + 480 + 400); the Budget line shows the maxima.
        self.assertEqual(self.project.total_amount, Decimal("1180"))
        self.assertIn('data-total-budget="1200"', html)
        self.assertIn("Budget 1", html)

    def test_project_page_no_budget_line_when_equal(self):
        html = self.client.get(reverse("projects:project_detail", args=[self.project.pk])).content.decode()
        self.assertNotIn("data-total-budget", html)
        self.assertNotIn("data-task-budget", html)
        self.assertIn("Total budget", html)

    def test_task_page_kpi_agreed_price_and_budget(self):
        task = self.choose_t2_at("480")
        html = self.client.get(reverse("projects:task_detail", args=[task.pk])).content.decode()
        self.assertIn("Agreed price", html)
        self.assertIn("budget was up to 500", html)
        self.assertIn('data-task-budget="500"', html)

    def test_task_page_full_budget_has_no_budget_hint(self):
        services.apply(self.t2, self.a, "A", ["stellar"])
        services.choose(self.t2, app_of(self.t2, self.a), self.company)
        html = self.client.get(reverse("projects:task_detail", args=[self.t2.pk])).content.decode()
        self.assertIn("Agreed price", html)
        self.assertNotIn("budget was up to", html)

    def test_apply_caps_at_budget(self):
        with self.assertRaises(services.ProjectError) as ctx:
            services.apply(self.t2, self.a, "A", ["stellar"], price="501")
        self.assertEqual(ctx.exception.code, "over_budget")

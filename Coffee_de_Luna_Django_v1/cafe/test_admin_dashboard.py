"""Admin dashboard permissions, reporting dates, and operational shortcuts."""
from datetime import timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from .models import Ingredient, Order, Product, StockMovement
from .services import change_order_status
from .tests import CafeFixture
from .views import chart_days


class AdminDashboardTests(CafeFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_superuser('administrator', password='Moonlit!7529', first_name='Luna')

    def admin_get(self, **params):
        self.client.force_login(self.admin)
        return self.client.get(reverse('admin_dashboard'), params)

    def complete(self, **kwargs):
        order = self.order(**kwargs)
        for status in ['preparing', 'ready', 'completed']:
            change_order_status(order.pk, status, self.cashier)
        return order

    def test_dashboard_requires_an_administrator(self):
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
        for user in [self.cashier, self.manager]:
            self.client.force_login(user)
            response = self.client.get(reverse('admin_dashboard'))
            self.assertEqual(response.status_code, 403)
            self.assertContains(response, 'administrator', status_code=403)

    def test_admin_lands_on_custom_dashboard_after_login(self):
        response = self.client.post(reverse('login'), {
            'username': 'administrator', 'password': 'Moonlit!7529'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.resolver_match.url_name, 'admin_dashboard')
        self.assertContains(response, 'Admin dashboard')
        self.assertContains(response, 'Administrator')
        self.assertContains(response, 'v1.10')
        self.assertIn('no-store', response['Cache-Control'])

    def test_existing_staff_home_keeps_manager_and_cashier_overviews(self):
        for user in [self.manager, self.cashier]:
            self.client.force_login(user)
            response = self.client.get(reverse('dashboard'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['page'], 'dashboard')
            self.assertNotContains(response, '>Admin dashboard</a>')
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('admin_dashboard'))

    def test_login_preserves_a_requested_staff_page(self):
        response = self.client.post(reverse('login') + '?next=' + reverse('orders'), {
            'username': 'administrator', 'password': 'Moonlit!7529'}, follow=True)
        self.assertEqual(response.resolver_match.url_name, 'orders')

    def test_empty_dashboard_has_zero_totals_and_useful_actions(self):
        response = self.admin_get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['revenue'], 0)
        self.assertEqual(response.context['gross_profit'], 0)
        self.assertEqual(response.context['completed_count'], 0)
        self.assertIsNone(response.context['revenue_change'])
        self.assertContains(response, 'Your first order starts here.')
        self.assertContains(response, reverse('stock_add'))
        self.assertContains(response, reverse('staff_add'))
        self.assertEqual(len(response.context['chart']), 7)

    def test_sales_use_paid_completed_orders_and_completion_dates(self):
        current = self.complete(discount_percent=10)
        # An order created long ago but completed now belongs to current sales.
        Order.objects.filter(pk=current.pk).update(created_at=timezone.now() - timedelta(days=100))
        self.order(paid=False)
        cancelled = self.order()
        change_order_status(cancelled.pk, 'cancelled', self.cashier)
        older = self.complete()
        Order.objects.filter(pk=older.pk).update(completed_at=timezone.now() - timedelta(days=14))
        future = self.complete()
        Order.objects.filter(pk=future.pk).update(completed_at=timezone.now() + timedelta(days=1))
        response = self.admin_get()
        self.assertEqual(response.context['revenue'], Decimal('135.00'))
        self.assertEqual(response.context['completed_count'], 1)
        self.assertEqual(response.context['recipe_cost'], Decimal('41.0000'))
        self.assertEqual(response.context['gross_profit'], Decimal('94.00'))
        self.assertEqual(response.context['average_order'], Decimal('135.00'))
        self.assertEqual(response.context['refund_count'], 1)
        self.assertEqual(response.context['refund_total'], Decimal('150.00'))
        self.assertEqual(response.context['best_sellers'][0]['sold'], 1)
        self.assertEqual(sum(row['total'] for row in response.context['payments']), Decimal('135.00'))
        self.assertEqual(sum(row['amount'] for row in response.context['chart']), Decimal('135.00'))
        longer = self.admin_get(period='30')
        self.assertEqual(longer.context['revenue'], Decimal('285.00'))
        self.assertEqual(longer.context['completed_count'], 2)
        self.assertEqual(len(longer.context['chart']), 30)

    def test_period_comparison_uses_the_previous_equal_length_period(self):
        self.complete()
        prior = self.complete()
        Order.objects.filter(pk=prior.pk).update(total=100, completed_at=timezone.now() - timedelta(days=8))
        response = self.admin_get()
        self.assertEqual(response.context['previous_revenue'], Decimal('100.00'))
        self.assertEqual(response.context['revenue_change'], Decimal('50.0'))
        self.assertEqual(response.context['trend_direction'], 'up')
        self.assertContains(response, '50.0%')

    def test_no_current_sales_with_previous_sales_shows_a_decline(self):
        prior = self.complete()
        Order.objects.filter(pk=prior.pk).update(completed_at=timezone.now() - timedelta(days=8))
        response = self.admin_get()
        self.assertEqual(response.context['revenue'], 0)
        self.assertEqual(response.context['revenue_change'], Decimal('-100.0'))
        self.assertEqual(response.context['trend_direction'], 'down')
        self.assertContains(response, '100.0%')

    def test_stock_snapshot_excludes_archived_ingredients(self):
        Ingredient.objects.filter(pk=self.beans.pk).update(reorder_level=1200)
        Ingredient.objects.filter(pk=self.milk.pk).update(quantity=0)
        Ingredient.objects.filter(pk=self.cups.pk).update(is_active=False)
        Ingredient.objects.create(name='Archived syrup', sku='OLD', unit='ml', quantity=0, is_active=False)
        response = self.admin_get()
        self.assertEqual(response.context['stock_alert_count'], 2)
        self.assertEqual(response.context['out_of_stock_count'], 1)
        self.assertEqual(response.context['ingredient_count'], 2)
        self.assertEqual(response.context['inventory_value'], Decimal('1000'))
        self.assertEqual(response.context['team_count'], 3)
        self.assertEqual({item.name for item in response.context['stock_alerts']}, {'Coffee', 'Milk'})

    def test_queue_and_unpaid_orders_include_older_open_orders(self):
        pending = self.order(paid=False)
        Order.objects.filter(pk=pending.pk).update(created_at=timezone.now() - timedelta(days=60))
        preparing = self.order(paid=False)
        change_order_status(preparing.pk, 'preparing', self.cashier)
        ready = self.order()
        change_order_status(ready.pk, 'preparing', self.cashier)
        change_order_status(ready.pk, 'ready', self.cashier)
        response = self.admin_get()
        self.assertEqual(response.context['active_order_count'], 3)
        self.assertEqual(response.context['unpaid_count'], 2)
        self.assertEqual(response.context['unpaid_total'], Decimal('300'))
        self.assertEqual({r['status']: r['count'] for r in response.context['order_queue']},
                         {'pending': 1, 'preparing': 1, 'ready': 1})

    def test_payment_shortcuts_show_the_correct_orders(self):
        unpaid = self.order(paid=False)
        cancelled_unpaid = self.order(paid=False)
        change_order_status(cancelled_unpaid.pk, 'cancelled', self.cashier)
        paid = self.order()
        refund = self.order()
        change_order_status(refund.pk, 'cancelled', self.cashier)
        self.client.force_login(self.admin)
        for payment, expected in [('unpaid', unpaid), ('paid', paid), ('refund', refund)]:
            response = self.client.get(reverse('orders'), {'payment': payment})
            self.assertEqual({o.pk for o in response.context['orders']}, {expected.pk})

    def test_unknown_sales_period_falls_back_to_seven_days(self):
        response = self.admin_get(period='999999')
        self.assertEqual(response.context['period'], '7')
        self.assertEqual(len(response.context['chart']), 7)

    def test_dashboard_get_does_not_change_operational_data(self):
        self.order()
        self.client.force_login(self.admin)
        before = (list(Ingredient.objects.values_list('pk', 'quantity', 'cost_per_unit')),
                  list(Order.objects.values_list('pk', 'status', 'total', 'paid')), StockMovement.objects.count())
        self.client.get(reverse('admin_dashboard'), {'period': '30'})
        after = (list(Ingredient.objects.values_list('pk', 'quantity', 'cost_per_unit')),
                 list(Order.objects.values_list('pk', 'status', 'total', 'paid')), StockMovement.objects.count())
        self.assertEqual(before, after)

    def test_daily_chart_aggregates_a_month_with_one_query(self):
        self.complete()
        today = timezone.localdate()
        with self.assertNumQueries(1):
            chart = chart_days(today - timedelta(days=29), today)
        self.assertEqual(len(chart), 30)
        self.assertEqual(sum(row['amount'] for row in chart), Decimal('150'))

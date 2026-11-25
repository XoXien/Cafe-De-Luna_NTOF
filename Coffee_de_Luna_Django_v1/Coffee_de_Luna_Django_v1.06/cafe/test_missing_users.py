"""Regressions for guest orders and audit records whose staff user was deleted."""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
import json
from django.contrib.auth.models import User
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from .models import Order, Purchase
from .services import add_stock
from .tests import CafeFixture


class MissingUserPageTests(CafeFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_superuser('siteowner', password='Moonrise!6249')

    def guest_order(self):
        return self.order(source='online', user=None, paid=False, customer_name='Guest customer')

    def test_guest_order_detail_renders_without_a_linked_user(self):
        order = self.guest_order()
        self.assertIsNone(order.events.get().user_id)
        self.client.force_login(self.manager)
        response = self.client.get(reverse('order_detail', args=[order.pk]))
        self.assertContains(response, 'Guest', status_code=200)

    def test_admin_activity_renders_guest_events(self):
        self.guest_order()
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertContains(response, 'Guest', status_code=200)

    def test_stock_history_renders_guest_movements(self):
        self.guest_order()
        self.client.force_login(self.manager)
        response = self.client.get(reverse('movements'))
        self.assertContains(response, 'Guest', status_code=200)

    def test_delivery_journal_renders_a_missing_recipient(self):
        add_stock(Purchase(ingredient=self.beans,
                         quantity=Decimal('50'), unit_cost=Decimal('1')), None)
        self.client.force_login(self.manager)
        response = self.client.get(reverse('stock_receipts'))
        self.assertContains(response, '—', status_code=200)

    def test_order_and_audit_pages_survive_deleting_the_original_staff_user(self):
        former = User.objects.create_user('formerbarista', password='Moonrise!7134', first_name='Former staff')
        order = self.order(user=former)
        add_stock(Purchase(ingredient=self.beans,
                         quantity=Decimal('50'), unit_cost=Decimal('1')), former)
        former.delete()
        self.assertIsNone(order.events.get().user_id)
        self.client.force_login(self.admin)
        for url in [reverse('order_detail', args=[order.pk]), reverse('admin_dashboard'),
                    reverse('movements'), reverse('stock_receipts')]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_expired_guest_orders_render_system_events(self):
        order = self.guest_order()
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=45))
        call_command('expire_pending_orders', minutes=30, stdout=StringIO())
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')
        self.client.force_login(self.admin)
        for url in [reverse('order_detail', args=[order.pk]), reverse('admin_dashboard'), reverse('movements')]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_staff_without_a_first_name_falls_back_to_username(self):
        self.cashier.first_name = ''
        self.cashier.save(update_fields=['first_name'])
        order = self.order()
        self.client.force_login(self.manager)
        response = self.client.get(reverse('order_detail', args=[order.pk]))
        self.assertContains(response, 'barista', status_code=200)

    def test_staff_names_remain_html_escaped(self):
        self.cashier.first_name = '<script>alert(1)</script>'
        self.cashier.save(update_fields=['first_name'])
        order = self.order()
        self.client.force_login(self.manager)
        response = self.client.get(reverse('order_detail', args=[order.pk]))
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')

    def test_real_public_checkout_can_be_opened_by_staff(self):
        self.client.get(reverse('shop'))
        key = self.client.session['checkout_keys'][-1]
        response = self.client.post(reverse('submit_order'), json.dumps({
            'source': 'online', 'submission_key': key, 'items': [{'id': self.product.pk, 'quantity': 1}],
            'customer_name': 'Pickup guest', 'phone': '09123456789', 'order_type': 'pickup'}),
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        order = Order.objects.get()
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('order_detail', args=[order.pk])).status_code, 200)

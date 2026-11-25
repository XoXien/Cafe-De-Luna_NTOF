"""Direct stock entry without supplier records or mandatory cost entry."""
from decimal import Decimal
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.urls import reverse
from .models import Ingredient, Purchase, StockMovement
from .services import add_stock
from .tests import CafeFixture


class StockAdditionTests(CafeFixture):
    def setUp(self):
        self.client.force_login(self.manager)

    def test_only_ingredient_and_quantity_are_required(self):
        response = self.client.get(reverse('stock_add'))
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertEqual({name for name, field in form.fields.items() if field.required}, {'ingredient', 'quantity'})
        self.assertNotIn('supplier', form.fields)
        self.assertNotContains(response, 'Suppliers')
        self.assertContains(response, 'Add supply stock')

    def test_add_stock_without_cost_uses_the_current_ingredient_cost(self):
        response = self.client.post(reverse('stock_add'), {'ingredient': self.beans.pk, 'quantity': '100'})
        self.assertRedirects(response, reverse('stock_receipts'))
        self.beans.refresh_from_db()
        self.assertEqual(self.beans.quantity, Decimal('1100'))
        self.assertEqual(self.beans.cost_per_unit, Decimal('1'))
        receipt = Purchase.objects.get()
        self.assertEqual(receipt.unit_cost, Decimal('1'))
        self.assertEqual(receipt.received_by, self.manager)
        movement = StockMovement.objects.get()
        self.assertEqual(movement.kind, 'receive')
        self.assertEqual(movement.quantity, Decimal('100'))
        self.assertEqual(movement.balance_after, Decimal('1100'))

    def test_explicit_unit_cost_updates_weighted_average_and_history(self):
        response = self.client.post(reverse('stock_add'), {
            'ingredient': self.beans.pk, 'quantity': '1000', 'unit_cost': '2', 'notes': 'Fresh coffee supply'})
        self.assertEqual(response.status_code, 302)
        self.beans.refresh_from_db()
        self.assertEqual(self.beans.quantity, Decimal('2000'))
        self.assertEqual(self.beans.cost_per_unit, Decimal('1.5000'))
        self.assertEqual(Purchase.objects.get().total, Decimal('2000'))
        self.assertIn('Fresh coffee supply', StockMovement.objects.get().note)
        history = self.client.get(reverse('stock_receipts'))
        self.assertContains(history, 'Fresh coffee supply')
        self.assertNotContains(history, 'Supplier')

    def test_invalid_quantities_do_not_change_stock(self):
        for quantity in ['0', '-1', 'abc', '1.0001']:
            with self.subTest(quantity=quantity):
                response = self.client.post(reverse('stock_add'), {'ingredient': self.beans.pk, 'quantity': quantity})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
        self.assertEqual(self.balance(self.beans), Decimal('1000'))
        self.assertFalse(Purchase.objects.exists())
        self.assertFalse(StockMovement.objects.exists())

    def test_inactive_ingredient_is_rejected(self):
        Ingredient.objects.filter(pk=self.beans.pk).update(is_active=False)
        response = self.client.post(reverse('stock_add'), {'ingredient': self.beans.pk, 'quantity': '100'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('ingredient', response.context['form'].errors)
        self.assertFalse(Purchase.objects.exists())
        self.assertEqual(self.balance(self.beans), Decimal('1000'))

    def test_invalid_costs_cannot_add_inventory(self):
        for cost in ['-1', 'NaN', 'Infinity', '1.00001']:
            with self.subTest(cost=cost):
                response = self.client.post(reverse('stock_add'), {
                    'ingredient': self.beans.pk, 'quantity': '100', 'unit_cost': cost})
                self.assertEqual(response.status_code, 200)
                self.assertIn('unit_cost', response.context['form'].errors)
        self.assertEqual(self.balance(self.beans), Decimal('1000'))
        self.assertFalse(Purchase.objects.exists())

    def test_cashier_cannot_add_stock(self):
        self.client.force_login(self.cashier)
        response = self.client.post(reverse('stock_add'), {'ingredient': self.beans.pk, 'quantity': '100'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.balance(self.beans), Decimal('1000'))
        self.assertFalse(Purchase.objects.exists())

    def test_inventory_and_admin_offer_add_stock_without_supplier_links(self):
        self.assertContains(self.client.get(reverse('inventory')), reverse('stock_add'))
        self.assertNotContains(self.client.get(reverse('ingredient_add')), 'name="supplier"')
        admin = User.objects.create_superuser('siteadmin', password='Moonrise!5289')
        self.client.force_login(admin)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertContains(response, 'Add stock')
        self.assertContains(response, reverse('stock_add'))
        self.assertNotContains(response, 'Supplier')
        self.assertEqual(self.client.get('/app/suppliers/').status_code, 404)

    def test_legacy_stock_bookmarks_still_work(self):
        self.assertEqual(self.client.get('/app/purchases/').status_code, 200)
        self.assertEqual(self.client.get('/app/purchases/receive/').status_code, 200)

    def test_service_resolves_a_blank_cost_at_the_time_stock_is_added(self):
        receipt = Purchase(ingredient=self.beans, quantity=Decimal('100'), unit_cost=None)
        Ingredient.objects.filter(pk=self.beans.pk).update(cost_per_unit=Decimal('1.75'))
        add_stock(receipt, self.manager)
        self.beans.refresh_from_db()
        self.assertEqual(self.beans.cost_per_unit, Decimal('1.7500'))
        self.assertEqual(receipt.unit_cost, Decimal('1.75'))

    def test_direct_service_rejects_invalid_cost_without_partial_records(self):
        with self.assertRaises(ValidationError):
            add_stock(Purchase(ingredient=self.beans, quantity=Decimal('100'), unit_cost=Decimal('NaN')), self.manager)
        self.assertEqual(self.balance(self.beans), Decimal('1000'))
        self.assertFalse(Purchase.objects.exists())
        self.assertFalse(StockMovement.objects.exists())

"""Existing inventory and receipt history survive removal of supplier fields."""
from decimal import Decimal
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class DirectStockMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_stock_orders_and_stock_addition_history(self):
        before = [('cafe', '0001_initial')]
        after = [('cafe', '0006_builtin_menu')]
        from .test_helpers import empty_catalog
        empty_catalog()
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            apps = executor.loader.project_state(before).apps
            supplier = apps.get_model('cafe', 'Supplier').objects.create(name='Historical supply contact')
            ingredient = apps.get_model('cafe', 'Ingredient').objects.create(
                name='Coffee beans', sku='UPGRADE-BN', unit='g', quantity=123, cost_per_unit=Decimal('.75'), supplier=supplier)
            receipt = apps.get_model('cafe', 'Purchase').objects.create(
                ingredient=ingredient, supplier=supplier, quantity=23, unit_cost=Decimal('.8'), reference='OLD-REF')
            order = apps.get_model('cafe', 'Order').objects.create(subtotal=150, total=150, customer_name='Existing guest')
            apps.get_model('cafe', 'StockMovement').objects.create(
                ingredient=ingredient, kind='receive', quantity=23, balance_after=123, note='Historical stock receipt')
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            from .models import Ingredient, Order, Purchase, StockMovement
            saved = Ingredient.objects.get(pk=ingredient.pk)
            self.assertEqual(saved.quantity, Decimal('123'))
            self.assertEqual(saved.cost_per_unit, Decimal('.75'))
            self.assertEqual(Purchase.objects.get(pk=receipt.pk).reference, 'OLD-REF')
            self.assertEqual(Purchase.objects.get(pk=receipt.pk).quantity, Decimal('23'))
            self.assertEqual(Order.objects.get(pk=order.pk).total, Decimal('150'))
            self.assertEqual(StockMovement.objects.get(note='Historical stock receipt').note, 'Historical stock receipt')
            self.assertNotIn('cafe_supplier', connection.introspection.table_names())
        finally:
            MigrationExecutor(connection).migrate(after)

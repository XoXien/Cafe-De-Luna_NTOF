"""Per-drink extras, real milk replacement, stock snapshots and safe upgrades."""
import json
import uuid
from decimal import Decimal
from io import StringIO
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from .models import Ingredient, Order, OrderItem, Product, RecipeItem, StockMovement
from .services import create_order, change_order_status


class DrinkCustomizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('load_coffee_menu', stdout=StringIO())

    def product(self, key):
        return Product.objects.get(menu_key='menu:' + key)

    def line(self, drink='flavoured-vanilla-iced16', quantity=1, extras=()):
        return {'id': self.product(drink).pk, 'quantity': quantity,
                'add_ons': [{'id': self.product(key).pk, 'quantity': amount} for key, amount in extras]}

    def order(self, lines, **kwargs):
        return create_order(source='online', submission_key=kwargs.pop('submission_key', uuid.uuid4()), lines=lines, **kwargs)

    def stock(self, sku):
        return Ingredient.objects.get(sku=sku).quantity

    def test_extras_belong_to_their_drink_and_scale_with_quantity(self):
        order = self.order([self.line(quantity=2, extras=[('addon-espresso',2),('addon-syrup-caramel',1),('addon-whip',1)])])
        self.assertEqual(order.total, Decimal('470'))  # 2 × (110 + 80 + 20 + 25)
        base = order.items.get(parent_item=None)
        self.assertEqual(base.quantity, 2)
        self.assertEqual(base.add_ons.count(), 3)
        self.assertEqual(base.add_ons.get(product__menu_key='menu:addon-espresso').quantity, 4)
        self.assertEqual(self.stock('CDL-001'), 4000 - 18 * 6)
        self.assertEqual(self.stock('CDL-009'), 1970)
        self.assertEqual(self.stock('CDL-020'), 1940)
        self.assertEqual(order.drink_count, 2)
        self.assertIn('Extra espresso × 2', base.customization_summary)

    def test_different_configurations_of_same_drink_remain_separate(self):
        order = self.order([self.line(), self.line(extras=[('addon-whip',1)])])
        self.assertEqual(order.total, 245)
        bases = list(order.items.filter(parent_item=None))
        self.assertEqual(len(bases), 2)
        self.assertEqual(bases[0].add_ons.count(), 0)
        self.assertEqual(bases[1].add_ons.count(), 1)

    def test_identical_configurations_merge_regardless_of_extra_order(self):
        order = self.order([self.line(extras=[('addon-espresso',1),('addon-whip',1)]),
                            self.line(extras=[('addon-whip',1),('addon-espresso',1)])])
        self.assertEqual(order.items.filter(parent_item=None).get().quantity, 2)
        self.assertEqual(order.items.count(), 3)
        self.assertEqual(order.total, 350)

    def test_oat_milk_replaces_equal_amount_of_whole_milk_and_cost(self):
        order = self.order([self.line(quantity=2, extras=[('addon-oat',1)])])
        self.assertEqual(order.total, 290)
        self.assertEqual(self.stock('CDL-002'), 12000)
        self.assertEqual(self.stock('CDL-003'), 3640)
        self.assertFalse(order.ingredients_used.filter(ingredient__sku='CDL-002').exists())
        child = order.items.get(parent_item__isnull=False)
        self.assertIn('replaces whole milk', child.name)
        self.assertEqual(child.unit_cost, Decimal('27'))  # 180 ml × .15
        base = order.items.get(parent_item=None)
        expected = self.product('flavoured-vanilla-iced16').recipe_cost - Decimal('180') * Decimal('.085')
        self.assertEqual(base.unit_cost, expected)

    def test_hot_oat_swap_uses_hot_recipe_quantity(self):
        self.order([self.line('flavoured-vanilla-hot8', extras=[('addon-oat',1)])])
        self.assertEqual(self.stock('CDL-003'), 3850)
        self.assertEqual(self.stock('CDL-002'), 12000)

    def test_americano_gets_an_extra_milk_portion_instead_of_replacement(self):
        order = self.order([self.line('americano-iced16', extras=[('addon-oat',1)])])
        self.assertEqual(order.total, 120)
        self.assertEqual(self.stock('CDL-003'), 3900)
        self.assertIn('Add Oat Milk', order.items.get(parent_item__isnull=False).name)

    def test_swap_works_with_zero_or_inactive_whole_milk(self):
        Ingredient.objects.filter(sku='CDL-002').update(quantity=0, is_active=False)
        self.order([self.line(extras=[('addon-oat',1)])])
        self.assertEqual(self.stock('CDL-003'), 3820)
        self.assertEqual(self.stock('CDL-002'), 0)
        response = self.client.get(reverse('shop'))
        entry = next(p for p in response.context['products_data'] if p['id'] == self.product('flavoured-vanilla-iced16').pk)
        self.assertEqual(entry['default_capacity'], 0)
        self.assertGreater(entry['capacity'], 0)

    def test_condensed_milk_and_included_frappe_topping_stay_in_recipe(self):
        order = self.order([self.line('spanish-latte-iced16', extras=[('addon-oat',1)]),
                            self.line('frappe-coffee-caramel', extras=[('addon-whip',1)])])
        self.assertTrue(order.ingredients_used.filter(ingredient__sku='CDL-004').exists())
        self.assertEqual(self.stock('CDL-020'), 1950)  # Included 20 + extra 30

    def test_shared_ingredients_across_base_and_extra_are_checked_atomically(self):
        Ingredient.objects.filter(sku='CDL-001').update(quantity=35)
        before = StockMovement.objects.count()
        with self.assertRaises(ValidationError):
            self.order([self.line(extras=[('addon-espresso',1)])])
        self.assertEqual(self.stock('CDL-001'), 35)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(StockMovement.objects.count(), before)

    def test_milk_swap_checks_actual_replacement_volume_not_extra_portion(self):
        Ingredient.objects.filter(sku='CDL-003').update(quantity=150)
        with self.assertRaises(ValidationError):
            self.order([self.line(extras=[('addon-oat',1)])])
        self.assertEqual(self.stock('CDL-003'), 150)
        self.assertFalse(Order.objects.exists())

    def test_addons_cannot_be_flat_lines_or_use_drinks_as_extras(self):
        for lines in [[self.line(),self.line('addon-whip')],
                      [self.line(extras=[('americano-hot8',1)])]]:
            with self.subTest(lines=lines), self.assertRaises(ValidationError):
                self.order(lines)
        self.assertFalse(Order.objects.exists())

    def test_addon_validation_rejects_duplicates_bad_types_and_limits(self):
        drink = self.line()
        espresso, whip = self.product('addon-espresso').pk, self.product('addon-whip').pk
        bad = [None, {}, 'extra', [{'id':espresso,'quantity':True}], [{'id':True,'quantity':1}],
               [{'id':espresso,'quantity':1.5}], [{'id':espresso,'quantity':4}], [{'id':espresso,'quantity':0}],
               [{'id':espresso,'quantity':1},{'id':espresso,'quantity':1}], [{'id':whip,'quantity':2}],
               [{'id':999999,'quantity':1}], [None]]
        for extras in bad:
            with self.subTest(extras=extras), self.assertRaises(ValidationError):
                self.order([{**drink, 'add_ons':extras}])
        self.assertFalse(Order.objects.exists())

    def test_only_one_extra_syrup_flavour_per_drink(self):
        with self.assertRaises(ValidationError):
            self.order([self.line(extras=[('addon-syrup-caramel',1),('addon-syrup-vanilla',1)])])

    def test_total_quantity_limit_applies_across_drink_configurations(self):
        with self.assertRaises(ValidationError):
            self.order([self.line(quantity=50),self.line(quantity=50,extras=[('addon-whip',1)])])
        self.assertFalse(Order.objects.exists())

    def test_disabled_extra_and_bad_replacement_recipe_are_rejected(self):
        addon = self.product('addon-oat')
        addon.is_active = False; addon.save()
        with self.assertRaises(ValidationError):
            self.order([self.line(extras=[('addon-oat',1)])])
        addon.is_active = True; addon.save()
        RecipeItem.objects.create(product=addon, ingredient=Ingredient.objects.get(sku='CDL-001'), quantity=1)
        with self.assertRaises(ValidationError):
            self.order([self.line(extras=[('addon-oat',1)])])

    def test_cancellation_restores_effective_recipe_after_recipe_edits_once(self):
        order = self.order([self.line(quantity=2, extras=[('addon-oat',1),('addon-espresso',2)])])
        RecipeItem.objects.filter(product=self.product('addon-oat')).update(quantity=5)
        RecipeItem.objects.filter(product=self.product('flavoured-vanilla-iced16'), ingredient__sku='CDL-002').update(quantity=50)
        change_order_status(order.pk, 'cancelled', None)
        change_order_status(order.pk, 'cancelled', None)
        self.assertEqual(self.stock('CDL-001'), 4000)
        self.assertEqual(self.stock('CDL-002'), 12000)
        self.assertEqual(self.stock('CDL-003'), 4000)

    def test_repeated_checkout_key_keeps_one_configured_order(self):
        key = uuid.uuid4()
        order = self.order([self.line(extras=[('addon-oat',1)])], submission_key=key)
        again = self.order([self.line(extras=[('addon-espresso',1)])], submission_key=key)
        self.assertEqual(order.pk, again.pk)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self.stock('CDL-003'), 3820)

    def test_grouped_details_tracking_and_receipt_render_with_guest_actor(self):
        order = self.order([self.line(extras=[('addon-oat',1),('addon-whip',1)])])
        owner = User.objects.create_superuser('customizerowner', password='Coffee!81742')
        self.client.force_login(owner)
        for url in [reverse('order_detail',args=[order.pk]),reverse('receipt',args=[order.pk]),reverse('tracking',args=[order.token])]:
            response = self.client.get(url)
            self.assertEqual(response.status_code,200)
            self.assertContains(response,'replaces whole milk')
            self.assertContains(response,'For Vanilla Latte')
        self.assertContains(self.client.get(reverse('order_detail',args=[order.pk])),'Guest')

    def test_menu_metadata_and_repeat_import_keep_custom_settings(self):
        extra = self.product('addon-oat')
        self.assertEqual(extra.customization_type,'milk')
        self.assertEqual(extra.replaces_ingredient.sku,'CDL-002')
        espresso = self.product('addon-espresso')
        self.assertEqual(espresso.max_per_drink,3)
        espresso.max_per_drink = 2;espresso.save()
        call_command('load_coffee_menu', stdout=StringIO())
        espresso.refresh_from_db();self.assertEqual(espresso.max_per_drink,2)

    def test_customer_and_counter_have_customizer_with_no_separate_extra_cards(self):
        owner = User.objects.create_superuser('counterowner', password='Coffee!72931')
        self.client.force_login(owner)
        for url in [reverse('shop'),reverse('pos')]:
            response = self.client.get(url)
            self.assertContains(response,'id="drink-customizer"')
            self.assertContains(response,'id="customizer-breakdown"')
            self.assertContains(response,'data-customize=',count=33)
            self.assertNotContains(response,'class="menu-addons"')

    def test_favourites_exclude_addons_but_cost_report_keeps_them(self):
        order = self.order([self.line(extras=[('addon-espresso',3)])])
        order.status='completed';order.paid=True
        from django.utils import timezone
        order.completed_at=timezone.now();order.save()
        owner = User.objects.create_superuser('reportowner',password='Coffee!81742');self.client.force_login(owner)
        response=self.client.get(reverse('admin_dashboard'))
        self.assertEqual(len(response.context['best_sellers']),1)
        self.assertEqual(response.context['best_sellers'][0]['sold'],1)
        self.assertEqual(response.context['recipe_cost'],sum(i.unit_cost*i.quantity for i in order.items.all()))


class CustomizationMigrationTests(TransactionTestCase):
    def test_existing_menu_metadata_upgrades_without_changing_business_records(self):
        before=[('cafe','0003_provided_menu_and_storage')]
        after=[('cafe','0004_drink_customizations')]
        executor=MigrationExecutor(connection);executor.migrate(before)
        try:
            apps=executor.loader.project_state(before).apps
            I,P,C,O,OI=[apps.get_model('cafe',name) for name in ['Ingredient','Product','Category','Order','OrderItem']]
            milk=I.objects.create(name='Whole milk',sku='CDL-002',unit='ml',quantity=123)
            oat=I.objects.create(name='Oat',sku='CDL-003',unit='ml',quantity=456,notes='My own notes')
            category=C.objects.create(name='Extras')
            product=P.objects.create(name='My oat',menu_key='menu:addon-oat',category=category,price=39,is_add_on=True)
            apps.get_model('cafe','RecipeItem').objects.create(product=product,ingredient=oat,quantity=77)
            order=O.objects.create(subtotal=39,total=39)
            item=OI.objects.create(order=order,product=product,name='Historical extra',quantity=1,unit_price=39)
            MigrationExecutor(connection).migrate(after)
            saved=Product.objects.get(pk=product.pk)
            self.assertEqual(saved.customization_type,'milk')
            self.assertEqual(saved.replaces_ingredient_id,milk.pk)
            self.assertEqual(saved.price,39)
            self.assertEqual(saved.recipe_items.get().quantity,77)
            self.assertEqual(Ingredient.objects.get(pk=oat.pk).quantity,456)
            self.assertEqual(Ingredient.objects.get(pk=oat.pk).notes,'My own notes')
            self.assertIsNone(OrderItem.objects.get(pk=item.pk).parent_item_id)
            self.assertEqual(Order.objects.get(pk=order.pk).total,39)
        finally:
            MigrationExecutor(connection).migrate(after)

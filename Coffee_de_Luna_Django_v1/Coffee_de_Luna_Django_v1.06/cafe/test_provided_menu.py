"""Prices from the supplied image; assumed recipes remain editable and repeatable."""
import json
import uuid
from decimal import Decimal
from io import StringIO
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from .models import Ingredient, Order, Product, RecipeItem, StockMovement
from .services import create_order, change_order_status


class ProvidedMenuTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('load_coffee_menu', stdout=StringIO())

    def item(self, key):
        return Product.objects.get(menu_key='menu:' + key)

    def test_import_has_menu_and_inventory_without_fake_accounts_or_orders(self):
        self.assertEqual(Product.objects.filter(is_add_on=False).count(), 52)
        self.assertEqual(Product.objects.filter(is_add_on=True).count(), 8)
        self.assertEqual(Ingredient.objects.count(), 34)
        self.assertEqual(StockMovement.objects.filter(kind='opening').count(), 34)
        self.assertFalse(User.objects.exists())
        self.assertFalse(Order.objects.exists())

    def test_coffee_prices_match_the_hot_and_iced_menu(self):
        prices = {'americano': (75, 85), 'cappuccino': (80, None), 'dark-mocha': (95, 115),
                  'white-mocha': (95, 115), 'flat-white': (90, None), 'espresso-matcha': (95, 120),
                  'caramel-macchiato': (95, 115), 'spanish-latte': (90, 110)}
        for key, (hot, iced) in prices.items():
            with self.subTest(item=key):
                self.assertEqual(self.item(key+'-hot8').price, hot)
                if iced is None:
                    self.assertFalse(Product.objects.filter(menu_key='menu:'+key+'-iced16').exists())
                else:
                    self.assertEqual(self.item(key+'-iced16').price, iced)
        for flavour in ['caramel', 'salted', 'vanilla', 'hazelnut']:
            self.assertEqual(self.item('flavoured-'+flavour+'-hot8').price, 90)
            self.assertEqual(self.item('flavoured-'+flavour+'-iced16').price, 110)

    def test_noncoffee_prices_match_the_photo(self):
        expected = {'dark-chocolate-hot8': 85, 'dark-chocolate-iced16': 105,
                    'matcha-latte-hot8': 85, 'matcha-latte-iced16': 110,
                    'strawberry-matcha-iced16': 120, 'strawberry-chocolate-iced16': 115,
                    'strawberry-milk-iced16': 105, 'mango-milk-iced16': 105}
        for key, price in expected.items():
            with self.subTest(item=key): self.assertEqual(self.item(key).price, price)

    def test_frappe_fruit_tea_and_extra_prices_match_the_photo(self):
        coffee = {'caramel':120,'salted':120,'vanilla':120,'hazelnut':120,'dark-mocha':125,'white-mocha':125,'dark-mocha-crumble':135}
        noncoffee = {'dark-chocolate':115,'matcha':120,'strawberry-matcha':130,'cookies-cream':120,
                     'dark-chocolate-crumble':125,'strawberry-milk':120,'mango-milk':120}
        for key, price in coffee.items(): self.assertEqual(self.item('frappe-coffee-'+key).price, price)
        for key, price in noncoffee.items(): self.assertEqual(self.item('frappe-noncoffee-'+key).price, price)
        for flavour in ['lemon','lychee','kiwi','passion']:
            for topping in ['crystals','chia']:
                self.assertEqual(self.item('tea-'+flavour+'-'+topping).price, 80)
        for key, price in {'espresso':40,'whip':25,'oat':35,'sea-salt':20}.items():
            self.assertEqual(self.item('addon-'+key).price, price)
        for flavour in ['caramel','salted','vanilla','hazelnut']:
            self.assertEqual(self.item('addon-syrup-'+flavour).price, 20)

    def test_all_menu_recipes_are_estimates_and_initially_available(self):
        for product in Product.objects.prefetch_related('recipe_items__ingredient'):
            with self.subTest(product=product.name):
                self.assertTrue(product.recipe_is_estimated)
                self.assertTrue(product.recipe_items.exists())
                self.assertGreater(product.capacity, 0)
        self.assertEqual(Ingredient.objects.filter(is_estimated=True).count(), 34)

    def test_frozen_purees_and_prepared_supplies_are_marked(self):
        for name in ['Strawberry purée (frozen)','Mango purée (frozen)']:
            ingredient=Ingredient.objects.get(name=name)
            self.assertEqual(ingredient.storage_type,'frozen')
            self.assertIn('not fresh',ingredient.notes)
        self.assertEqual(Ingredient.objects.get(name='Prepared whipped topping').storage_type,'chilled')
        self.assertEqual(Ingredient.objects.get(name='Black tea leaves').storage_type,'dry')

    def test_reloading_does_not_reset_prices_recipes_or_current_stock(self):
        beans=Ingredient.objects.get(sku='CDL-001')
        beans.quantity=1234;beans.cost_per_unit=Decimal('1.25');beans.save()
        product=self.item('americano-hot8')
        product.price=76;product.name='My confirmed Americano';product.save()
        RecipeItem.objects.filter(product=product,ingredient=beans).update(quantity=17)
        before=StockMovement.objects.count()
        call_command('load_coffee_menu', stdout=StringIO())
        beans.refresh_from_db();product.refresh_from_db()
        self.assertEqual(beans.quantity,1234)
        self.assertEqual(beans.cost_per_unit,Decimal('1.25'))
        self.assertEqual(product.price,76)
        self.assertEqual(product.name,'My confirmed Americano')
        self.assertEqual(product.recipe_items.get(ingredient=beans).quantity,17)
        self.assertEqual(Product.objects.count(),60)
        self.assertEqual(StockMovement.objects.count(),before)

    def test_menu_groups_sizes_flavours_and_tea_toppings(self):
        response=self.client.get(reverse('shop'))
        self.assertEqual(response.status_code,200)
        groups=response.context['drink_groups']
        self.assertEqual(len(groups),33)
        self.assertEqual(len(response.context['add_on_groups']),5)
        flavoured=next(g for g in groups if g['name']=='Flavoured Latte')
        self.assertEqual(len(flavoured['variants']),8)
        lemon=next(g for g in groups if g['name']=='Lemon' and g['category']=='Fruit Tea')
        self.assertEqual({v['label'] for v in lemon['variants']},{'Crystals · 16oz','Chia seeds · 16oz'})
        self.assertContains(response,'data-customize')
        self.assertNotContains(response,'Use the order note to say where')
        self.assertIn(response.context['checkout_key'],self.client.session['checkout_keys'])

    def test_public_order_uses_selected_variant_and_extra_prices(self):
        response=self.client.get(reverse('shop'))
        key=response.context['checkout_key']
        drink=self.item('americano-iced16');extra=self.item('addon-oat')
        response=self.client.post(reverse('submit_order'),json.dumps({'source':'online','submission_key':key,
            'customer_name':'Pickup guest','phone':'09123456789','order_type':'pickup',
            'items':[{'id':drink.pk,'quantity':1,'add_ons':[{'id':extra.pk,'quantity':1}]}, {'id':drink.pk,'quantity':1}]}),content_type='application/json')
        self.assertEqual(response.status_code,200)
        order=Order.objects.get()
        self.assertEqual(order.total,205)
        self.assertEqual(order.items.count(),3)
        self.assertEqual(Ingredient.objects.get(sku='CDL-001').quantity,3964)
        self.assertEqual(Ingredient.objects.get(name='Oat milk').quantity,3900)
        self.assertEqual(Ingredient.objects.get(name='Cold cup · 16oz').quantity,298)

    def test_extras_cannot_be_ordered_without_a_drink(self):
        before=StockMovement.objects.count()
        with self.assertRaises(ValidationError):
            create_order(source='online',user=None,lines=[{'id':self.item('addon-whip').pk,'quantity':1}],submission_key=uuid.uuid4())
        self.assertFalse(Order.objects.exists())
        self.assertEqual(StockMovement.objects.count(),before)

    def test_shared_frozen_stock_is_checked_across_drinks(self):
        fruit=Ingredient.objects.get(name='Strawberry purée (frozen)')
        fruit.quantity=100;fruit.save()
        with self.assertRaises(ValidationError):
            create_order(source='online',user=None,submission_key=uuid.uuid4(),lines=[
                {'id':self.item('strawberry-milk-iced16').pk,'quantity':1},
                {'id':self.item('frappe-noncoffee-strawberry-milk').pk,'quantity':1}])
        fruit.refresh_from_db()
        self.assertEqual(fruit.quantity,100)
        self.assertFalse(Order.objects.exists())

    def test_cancellation_restores_frozen_stock_and_extra_ingredients(self):
        fruit=Ingredient.objects.get(name='Mango purée (frozen)')
        order=create_order(source='online',user=None,submission_key=uuid.uuid4(),lines=[
            {'id':self.item('mango-milk-iced16').pk,'quantity':1,'add_ons':[{'id':self.item('addon-whip').pk,'quantity':1}]}])
        fruit.refresh_from_db();self.assertEqual(fruit.quantity,2940)
        change_order_status(order.pk,'cancelled',None)
        fruit.refresh_from_db();self.assertEqual(fruit.quantity,3000)
        self.assertEqual(Ingredient.objects.get(name='Prepared whipped topping').quantity,2000)

    def test_inventory_can_filter_frozen_supplies(self):
        owner=User.objects.create_superuser('menuowner',password='Moonrise!7814')
        self.client.force_login(owner)
        response=self.client.get(reverse('inventory'),{'storage':'frozen'})
        self.assertEqual(response.status_code,200)
        self.assertEqual({row.storage_type for row in response.context['ingredients']},{'frozen'})
        self.assertContains(response,'Estimated setup')
        self.assertContains(response,'Strawberry purée (frozen)')
        export=self.client.get(reverse('export_csv',args=['inventory']))
        self.assertEqual(export.status_code,200)
        self.assertIn('Storage,Estimated stock/cost,Notes',export.content.decode())
        self.assertIn('Frozen',export.content.decode())

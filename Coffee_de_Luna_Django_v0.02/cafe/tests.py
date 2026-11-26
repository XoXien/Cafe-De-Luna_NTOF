"""Business tests focus on stock integrity, payment rules, and access boundaries."""
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from .models import (Category, Ingredient, LoginAttempt, Order, OrderItem, Product, Purchase,
                     RecipeItem, StockMovement)
from .services import (adjust_stock, change_order_status, create_order, add_stock,
                       record_payment, record_refund)

class CafeFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .test_helpers import empty_catalog
        empty_catalog()
        cls.manager = User.objects.create_user('owner', password='OwnerCoffee!2026', first_name='Luna')
        cls.manager.groups.add(Group.objects.create(name='Managers'))
        cls.cashier = User.objects.create_user('barista', password='BaristaCoffee!2026', first_name='Bea')
        cls.cashier.groups.add(Group.objects.get_or_create(name='Cashiers')[0])
        cls.beans = Ingredient.objects.create(name='Coffee', sku='BN-1', unit='g', quantity=1000, cost_per_unit=Decimal('1'))
        cls.milk = Ingredient.objects.create(name='Milk', sku='ML-1', unit='ml', quantity=2000, cost_per_unit=Decimal('.1'))
        cls.cups = Ingredient.objects.create(name='Cup', sku='CP-1', unit='pcs', quantity=20, cost_per_unit=5)
        cls.category = Category.objects.create(name='Coffee')
        cls.product = Product.objects.create(name='Latte', category=cls.category, price=150)
        for ingredient, qty in [(cls.beans,18),(cls.milk,180),(cls.cups,1)]:
            RecipeItem.objects.create(product=cls.product, ingredient=ingredient, quantity=qty)
    def order(self, **kwargs):
        data = {'lines':[{'id':self.product.pk,'quantity':1}], 'submission_key':uuid.uuid4(),
                'user':self.cashier, 'paid':True, 'amount_tendered':500}
        data.update(kwargs)
        return create_order(**data)
    def balance(self, ingredient):
        return Ingredient.objects.get(pk=ingredient.pk).quantity

class StockAndOrderTests(CafeFixture):
    def test_order_reserves_recipe_and_records_snapshots(self):
        order = self.order(lines=[{'id':self.product.pk,'quantity':2}])
        self.assertEqual(order.total,300)
        self.assertEqual(self.balance(self.beans),964)
        self.assertEqual(self.balance(self.milk),1640)
        self.assertEqual(self.balance(self.cups),18)
        self.assertEqual(order.ingredients_used.count(),3)
        self.assertEqual(order.items.get().unit_cost,41)
        self.assertEqual(StockMovement.objects.filter(order=order,kind='sale').count(),3)

    def test_server_price_ignores_browser_price(self):
        order=self.order(lines=[{'id':self.product.pk,'quantity':1,'price':'0.01'}])
        self.assertEqual(order.total,150)

    def test_shared_ingredients_are_combined(self):
        other=Product.objects.create(name='Flat white',category=self.category,price=160)
        RecipeItem.objects.create(product=other,ingredient=self.milk,quantity=1900)
        with self.assertRaises(ValidationError):
            self.order(lines=[{'id':self.product.pk,'quantity':1},{'id':other.pk,'quantity':1}])
        self.assertEqual(Order.objects.count(),0)
        self.assertEqual(self.balance(self.beans),1000)
        self.assertEqual(self.balance(self.milk),2000)

    def test_insufficient_stock_rolls_back_everything(self):
        with self.assertRaises(ValidationError):
            self.order(lines=[{'id':self.product.pk,'quantity':20}])
        self.assertFalse(Order.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assertEqual(self.balance(self.beans),1000)

    def test_repeated_submission_is_idempotent(self):
        key=uuid.uuid4()
        first=self.order(submission_key=key)
        second=self.order(submission_key=key)
        self.assertEqual(first.pk,second.pk)
        self.assertEqual(Order.objects.count(),1)
        self.assertEqual(self.balance(self.beans),982)

    def test_duplicate_product_rows_are_merged(self):
        order=self.order(lines=[{'id':self.product.pk,'quantity':1},{'id':self.product.pk,'quantity':2}])
        self.assertEqual(order.items.count(),1)
        self.assertEqual(order.items.get().quantity,3)
        self.assertEqual(self.balance(self.beans),946)

    def test_invalid_quantities_are_rejected(self):
        for quantity in [0,-1,1.5,True,100,'1.0','nan']:
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                self.order(lines=[{'id':self.product.pk,'quantity':quantity}])
        self.assertEqual(Order.objects.count(),0)

    def test_invalid_and_inactive_products_cannot_be_sold(self):
        with self.assertRaises(ValidationError):
            self.order(lines=[{'id':9999,'quantity':1}])
        Product.objects.filter(pk=self.product.pk).update(is_active=False)
        with self.assertRaises(ValidationError):
            self.order()

    def test_malformed_product_ids_are_rejected_without_database_errors(self):
        for product_id in [True,1.2,10**100,'NaN']:
            with self.subTest(product_id=product_id), self.assertRaises(ValidationError):
                self.order(lines=[{'id':product_id,'quantity':1}])

    def test_inactive_ingredient_or_empty_recipe_blocks_sale(self):
        Ingredient.objects.filter(pk=self.beans.pk).update(is_active=False)
        with self.assertRaises(ValidationError):
            self.order()
        self.product.recipe_items.all().delete()
        self.assertEqual(self.product.capacity,0)
        with self.assertRaises(ValidationError):
            self.order()

    def test_discount_and_change_use_decimal_rounding(self):
        Product.objects.filter(pk=self.product.pk).update(price=Decimal('149.99'))
        order=self.order(discount_percent=5)
        self.assertEqual(order.discount,Decimal('7.50'))
        self.assertEqual(order.total,Decimal('142.49'))
        self.assertEqual(order.change,Decimal('357.51'))

    def test_nonfinite_or_out_of_range_money_is_rejected(self):
        for value in ['NaN','Infinity',-1,21]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.order(discount_percent=value)

    def test_online_orders_cannot_mark_themselves_paid_or_discounted(self):
        order=self.order(source='online',user=None,discount_percent=20,paid=True,amount_tendered=1000,payment_method='card')
        self.assertFalse(order.paid)
        self.assertEqual(order.discount,0)
        self.assertEqual(order.total,150)
        self.assertEqual(order.amount_tendered,0)
        self.assertEqual(order.payment_method,'cash')

    def test_cash_requires_enough_tender(self):
        with self.assertRaises(ValidationError):
            self.order(amount_tendered=149)
        self.assertEqual(self.balance(self.beans),1000)

    def test_cancellation_restores_original_recipe_once(self):
        order=self.order()
        RecipeItem.objects.filter(product=self.product,ingredient=self.beans).update(quantity=100)
        change_order_status(order.pk,'cancelled',self.cashier)
        change_order_status(order.pk,'cancelled',self.cashier)
        self.assertEqual(self.balance(self.beans),1000)
        self.assertEqual(self.balance(self.milk),2000)
        self.assertEqual(StockMovement.objects.filter(order=order,kind='return').count(),3)
        order.refresh_from_db()
        self.assertTrue(order.refund_due)

    def test_manual_refund_is_recorded_without_another_stock_change(self):
        order=self.order()
        change_order_status(order.pk,'cancelled',self.cashier)
        record_refund(order.pk,self.manager)
        order.refresh_from_db()
        self.assertFalse(order.refund_due)
        self.assertEqual(self.balance(self.beans),1000)
        with self.assertRaises(ValidationError):
            record_refund(order.pk,self.manager)

    def test_order_progression_does_not_deduct_twice(self):
        order=self.order()
        for status in ['preparing','ready','completed']:
            change_order_status(order.pk,status,self.cashier)
        self.assertEqual(self.balance(self.beans),982)
        order.refresh_from_db()
        self.assertIsNotNone(order.completed_at)
        with self.assertRaises(ValidationError):
            change_order_status(order.pk,'cancelled',self.cashier)

    def test_unpaid_order_cannot_complete(self):
        order=self.order(paid=False)
        for status in ['preparing','ready']:
            change_order_status(order.pk,status,self.cashier)
        with self.assertRaises(ValidationError):
            change_order_status(order.pk,'completed',self.cashier)
        record_payment(order.pk,'cash',200,self.cashier)
        change_order_status(order.pk,'completed',self.cashier)
        order.refresh_from_db()
        self.assertEqual(order.status,'completed')
        self.assertEqual(order.change,50)

    def test_invalid_status_and_cancelled_payment_are_rejected(self):
        order=self.order(paid=False)
        with self.assertRaises(ValidationError):
            change_order_status(order.pk,'completed',self.cashier)
        change_order_status(order.pk,'cancelled',self.cashier)
        with self.assertRaises(ValidationError):
            record_payment(order.pk,'cash',500,self.cashier)

    def test_external_payment_records_exact_total(self):
        order=self.order(paid=False)
        record_payment(order.pk,'gcash',0,self.cashier)
        record_payment(order.pk,'gcash',0,self.cashier)
        order.refresh_from_db()
        self.assertEqual(order.amount_tendered,order.total)
        self.assertEqual(order.events.filter(message__startswith='Payment recorded').count(),1)

    def test_received_stock_updates_weighted_average(self):
        purchase=Purchase(ingredient=self.beans,quantity=Decimal('1000'),unit_cost=Decimal('2'))
        add_stock(purchase,self.manager)
        self.beans.refresh_from_db()
        self.assertEqual(self.beans.quantity,2000)
        self.assertEqual(self.beans.cost_per_unit,Decimal('1.5000'))
        self.assertEqual(purchase.total,2000)
        self.assertEqual(StockMovement.objects.get().kind,'receive')

    def test_adjustments_validate_sign_reason_and_nonnegative_balance(self):
        for delta,kind,note in [(0,'adjust','Count'),(-1001,'adjust','Count'),(1,'waste','Spill'),(1,'adjust','')]:
            with self.subTest(delta=delta,kind=kind), self.assertRaises(ValidationError):
                adjust_stock(self.beans.pk,delta,kind,self.manager,note)
        adjust_stock(self.beans.pk,-20,'waste',self.manager,'Spilled grounds')
        self.assertEqual(self.balance(self.beans),980)

    def test_recipe_cost_snapshot_survives_price_changes(self):
        order=self.order()
        Ingredient.objects.filter(pk=self.beans.pk).update(cost_per_unit=10)
        Product.objects.filter(pk=self.product.pk).update(price=200)
        self.assertEqual(order.items.get().unit_cost,41)
        self.assertEqual(order.items.get().unit_price,150)

    def test_expiry_releases_only_old_unpaid_pending_online_orders(self):
        expired=self.order(source='online',user=None,paid=False)
        preparing=self.order(source='online',user=None,paid=False)
        counter=self.order(paid=False)
        change_order_status(preparing.pk,'preparing',self.cashier)
        Order.objects.all().update(created_at=timezone.now()-timedelta(minutes=45))
        fresh=self.order(source='online',user=None,paid=False)
        call_command('expire_pending_orders',minutes=30,stdout=StringIO())
        expired.refresh_from_db();preparing.refresh_from_db();counter.refresh_from_db();fresh.refresh_from_db()
        self.assertEqual(expired.status,'cancelled')
        self.assertEqual(preparing.status,'preparing')
        self.assertEqual(counter.status,'pending')
        self.assertEqual(fresh.status,'pending')
        self.assertEqual(self.balance(self.beans),946)

class AccessAndPageTests(CafeFixture):
    def test_staff_pages_require_login(self):
        for name in ['dashboard','pos','orders','inventory','movements','menu','reports','team','stock_receipts','account']:
            with self.subTest(name=name):
                response=self.client.get(reverse(name))
                self.assertEqual(response.status_code,302)
                self.assertIn('/login/',response.url)

    def test_cashier_cannot_mutate_inventory_or_manage_accounts(self):
        self.client.force_login(self.cashier)
        for name in ['ingredient_add','adjustment','product_add','category_add','stock_add','stock_receipts','reports','team','staff_add']:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code,403)
        self.assertEqual(self.client.post(reverse('ingredient_edit',args=[self.beans.pk]),{'quantity':999}).status_code,403)
        self.assertEqual(self.balance(self.beans),1000)

    def test_manager_pages_render(self):
        self.client.force_login(self.manager)
        names=['dashboard','pos','orders','inventory','movements','menu','reports','team','stock_receipts',
               'account','ingredient_add','adjustment','product_add','category_add','stock_add','staff_add']
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code,200)
        self.assertEqual(self.client.get(reverse('ingredient_edit',args=[self.beans.pk])).status_code,200)
        self.assertEqual(self.client.get(reverse('product_edit',args=[self.product.pk])).status_code,200)

    def test_customer_pages_and_order_details_render(self):
        order=self.order()
        self.assertEqual(self.client.get(reverse('shop')).status_code,200)
        self.assertEqual(self.client.get(reverse('tracking',args=[order.token])).status_code,200)
        self.assertEqual(self.client.get(reverse('tracking',args=[uuid.uuid4()])).status_code,404)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse('order_detail',args=[order.pk])).status_code,200)
        self.assertEqual(self.client.get(reverse('receipt',args=[order.pk])).status_code,200)

    def test_counter_api_rejects_anonymous_requests(self):
        response=self.client.post(reverse('submit_order'),json.dumps({'source':'pos'}),content_type='application/json')
        self.assertEqual(response.status_code,403)

    def test_online_checkout_csrf_and_session_key(self):
        client=Client(enforce_csrf_checks=True)
        response=client.get(reverse('shop'))
        session=client.session
        payload={'source':'online','submission_key':session['checkout_keys'][-1],
                 'items':[{'id':self.product.pk,'quantity':1}], 'customer_name':'Sofia','phone':'09123456789',
                 'order_type':'pickup', 'paid':True, 'discount_percent':20}
        rejected=client.post(reverse('submit_order'),json.dumps(payload),content_type='application/json')
        self.assertEqual(rejected.status_code,403)
        accepted=client.post(reverse('submit_order'),json.dumps(payload),content_type='application/json',HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(accepted.status_code,200)
        order=Order.objects.get()
        self.assertEqual(order.total,150)
        self.assertFalse(order.paid)
        repeated=client.post(reverse('submit_order'),json.dumps(payload),content_type='application/json',HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(repeated.status_code,200)
        self.assertEqual(Order.objects.count(),1)

    def test_online_checkout_rejects_wrong_key_and_invalid_contact(self):
        self.client.get(reverse('shop'))
        key=self.client.session['checkout_keys'][-1]
        data={'source':'online','submission_key':str(uuid.uuid4()),'items':[{'id':self.product.pk,'quantity':1}],
              'customer_name':'Sofia','phone':'09123456789','order_type':'pickup'}
        self.assertEqual(self.client.post(reverse('submit_order'),json.dumps(data),content_type='application/json').status_code,400)
        data.update(submission_key=key,phone='abc')
        self.assertEqual(self.client.post(reverse('submit_order'),json.dumps(data),content_type='application/json').status_code,400)

    def test_staff_can_place_order_through_api(self):
        self.client.force_login(self.cashier)
        self.client.get(reverse('pos'))
        data={'source':'pos','submission_key':self.client.session['checkout_keys'][-1],
              'items':[{'id':self.product.pk,'quantity':1}], 'paid':True,'amount_tendered':'200', 'order_type':'takeaway'}
        response=self.client.post(reverse('submit_order'),json.dumps(data),content_type='application/json')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['ok'])
        self.assertEqual(Order.objects.get().created_by,self.cashier)

    def test_cashier_cannot_confirm_manager_refund(self):
        order=self.order()
        change_order_status(order.pk,'cancelled',self.cashier)
        self.client.force_login(self.cashier)
        response=self.client.post(reverse('order_action',args=[order.pk]),{'action':'refund'})
        self.assertEqual(response.status_code,403)
        order.refresh_from_db()
        self.assertTrue(order.refund_due)

    def test_logout_clears_access_and_private_pages_disable_cache(self):
        self.client.force_login(self.cashier)
        response=self.client.get(reverse('dashboard'))
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(self.client.get(reverse('logout')).status_code,405)
        self.client.post(reverse('logout'))
        self.assertEqual(self.client.get(reverse('dashboard')).status_code,302)

    def test_login_throttles_repeated_failures(self):
        for _ in range(5):
            self.client.post(reverse('login'),{'username':'barista','password':'wrong'})
        self.assertEqual(self.client.post(reverse('login'),{'username':'barista','password':'BaristaCoffee!2026'}).status_code,429)
        LoginAttempt.objects.update(last_attempt=timezone.now()-timedelta(minutes=16))
        self.assertEqual(self.client.post(reverse('login'),{'username':'barista','password':'BaristaCoffee!2026'}).status_code,302)

    def test_ingredient_edit_preserves_balance_and_base_unit(self):
        self.client.force_login(self.manager)
        response=self.client.post(reverse('ingredient_edit',args=[self.beans.pk]),{
            'name':'Coffee','sku':'BN-1','unit':'ml','reorder_level':'200','cost_per_unit':'1','is_active':'on','quantity':'1'})
        self.assertEqual(response.status_code,302)
        self.beans.refresh_from_db()
        self.assertEqual(self.beans.quantity,1000)
        self.assertEqual(self.beans.unit,'g')

    def test_csv_exports_and_formula_escaping(self):
        Ingredient.objects.filter(pk=self.beans.pk).update(name='=SUM(A1:A9)')
        self.client.force_login(self.manager)
        response=self.client.get(reverse('export_csv',args=['inventory']))
        self.assertEqual(response.status_code,200)
        self.assertIn("'=SUM(A1:A9)",response.content.decode())
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse('export_csv',args=['sales'])).status_code,403)

    def test_first_admin_setup_preserves_existing_stock_and_passwords(self):
        User.objects.create_superuser('existingadmin', password='Moonlight!8162')
        call_command('ensure_admin',interactive=False,stdout=StringIO())
        self.assertEqual(self.balance(self.beans),1000)
        self.assertTrue(User.objects.get(username='barista').check_password('BaristaCoffee!2026'))
        self.assertEqual(Product.objects.count(),1)

    def test_manager_can_reset_staff_password_and_cashier_cannot(self):
        self.client.force_login(self.manager)
        response=self.client.post(reverse('staff_password',args=[self.cashier.pk]),
            {'new_password1':'FreshCup!2027','new_password2':'FreshCup!2027'})
        self.assertEqual(response.status_code,302)
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.check_password('FreshCup!2027'))
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse('staff_password',args=[self.manager.pk])).status_code,403)

    def test_manager_cannot_reset_an_administrator_password(self):
        admin=User.objects.create_superuser('super',password='AdminCoffee!2026')
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('staff_password',args=[admin.pk])).status_code,403)

    def test_staff_creation_and_deactivation(self):
        self.client.force_login(self.manager)
        response=self.client.post(reverse('staff_add'),{'username':'newbarista','first_name':'Sofia','last_name':'Reyes',
            'email':'sofia@example.com','role':'cashier','password1':'Moonrise!4729','password2':'Moonrise!4729'})
        self.assertEqual(response.status_code,302, response.context['form'].errors if response.status_code==200 else '')
        user=User.objects.get(username='newbarista')
        self.assertFalse(user.is_superuser)
        self.client.post(reverse('staff_toggle',args=[user.pk]))
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(Client().login(username='newbarista',password='Moonrise!4729'))

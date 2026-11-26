"""Built-in catalog, customer ownership, role boundaries and paid receipts."""
import json
import uuid
from django.contrib.auth.models import Group, User
from django.core.management import get_commands
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TransactionTestCase
from django.urls import reverse
from .models import Ingredient, Order, Product, Purchase, StockMovement
from .services import create_order, record_payment
from .test_helpers import empty_catalog
from .tests import CafeFixture


class CustomerWorkflowTests(CafeFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        group=Group.objects.get_or_create(name='Customers')[0]
        cls.customer=User.objects.create_user('sofia@example.com',email='sofia@example.com',first_name='Sofia',last_name='Luna',password='RitualCoffee!9284')
        cls.customer.groups.add(group)
        cls.other=User.objects.create_user('other@example.com',email='other@example.com',first_name='Other',password='RitualCoffee!7283')
        cls.other.groups.add(group)

    def online(self, customer=None):
        return self.order(source='online',user=None,paid=False,customer=customer,customer_name='Coffee guest')

    def registration(self, **extra):
        return {'first_name':'Isabel','last_name':'Luna','email':'isabel@example.com',
                'password1':'MoonlitRitual!4729','password2':'MoonlitRitual!4729',**extra}

    def test_registration_is_a_customer_account_even_with_injected_role_fields(self):
        response=self.client.post(reverse('customer_register'),self.registration(is_staff=True,is_superuser=True,role='manager',groups=['Managers']))
        self.assertRedirects(response,reverse('customer_dashboard'))
        user=User.objects.get(username='isabel@example.com')
        self.assertFalse(user.is_staff);self.assertFalse(user.is_superuser)
        self.assertEqual(list(user.groups.values_list('name',flat=True)),['Customers'])
        self.assertEqual(int(self.client.session['_auth_user_id']),user.pk)

    def test_duplicate_email_is_rejected_case_insensitively(self):
        response=self.client.post(reverse('customer_register'),self.registration(email='SOFIA@example.com'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'already uses this email')
        self.assertEqual(User.objects.filter(email__iexact='sofia@example.com').count(),1)

    def test_customer_sign_in_accepts_email_case_and_logs_into_history(self):
        response=self.client.post(reverse('customer_login'),{'username':'SOFIA@EXAMPLE.COM','password':'RitualCoffee!9284'})
        self.assertRedirects(response,reverse('customer_dashboard'))
        self.assertEqual(int(self.client.session['_auth_user_id']),self.customer.pk)

    def test_customer_cannot_sign_in_through_staff_form(self):
        response=self.client.post(reverse('login'),{'username':self.customer.username,'password':'RitualCoffee!9284'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Use customer sign in')
        self.assertNotIn('_auth_user_id',self.client.session)

    def test_customer_has_no_access_to_staff_pages(self):
        self.client.force_login(self.customer)
        for name in ['dashboard','admin_dashboard','pos','orders','inventory','movements','menu','reports','team','account','stock_add']:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code,403)

    def test_customer_cannot_place_a_paid_counter_order(self):
        self.client.force_login(self.customer)
        key=self.client.get(reverse('shop')).context['checkout_key']
        response=self.client.post(reverse('submit_order'),json.dumps({'source':'pos','submission_key':key,
            'items':[{'id':self.product.pk,'quantity':1}],'paid':True,'amount_tendered':500}),content_type='application/json')
        self.assertEqual(response.status_code,403);self.assertFalse(Order.objects.exists())

    def test_online_order_is_owned_by_signed_in_customer_and_stays_unpaid(self):
        self.client.force_login(self.customer)
        key=self.client.get(reverse('shop')).context['checkout_key']
        response=self.client.post(reverse('submit_order'),json.dumps({'source':'online','submission_key':key,
            'items':[{'id':self.product.pk,'quantity':1}],'customer_name':'Sofia Luna','phone':'09123456789',
            'paid':True,'discount_percent':20,'amount_tendered':500,'customer_id':self.other.pk}),content_type='application/json')
        self.assertEqual(response.status_code,200)
        order=Order.objects.get()
        self.assertEqual(order.customer_id,self.customer.pk)
        self.assertIsNone(order.created_by_id)
        self.assertFalse(order.paid);self.assertEqual(order.discount,0);self.assertEqual(order.total,150)

    def test_history_only_lists_the_signed_in_customers_orders(self):
        mine=self.online(self.customer);other=self.online(self.other);guest=self.online()
        self.client.force_login(self.customer)
        response=self.client.get(reverse('my_orders'))
        self.assertContains(response,mine.number)
        self.assertNotContains(response,other.number)
        self.assertNotContains(response,guest.number)
        self.assertNotContains(response,reverse('customer_receipt',args=[mine.token]))

    def test_guest_history_only_lists_verified_session_orders(self):
        mine=self.online();other=self.online()
        session=self.client.session;session['online_orders']=[str(mine.token),'invalid-token'];session.save()
        response=self.client.get(reverse('my_orders'))
        self.assertContains(response,mine.number);self.assertNotContains(response,other.number)
        self.assertContains(response,'Recent orders placed in this browser')

    def test_guest_order_is_linked_to_account_on_registration(self):
        order=self.online()
        session=self.client.session;session['online_orders']=[str(order.token)];session.save()
        self.client.post(reverse('customer_register'),self.registration())
        order.refresh_from_db()
        self.assertEqual(order.customer_id,User.objects.get(username='isabel@example.com').pk)
        self.assertContains(self.client.get(reverse('my_orders')),order.number)

    def test_signing_in_claims_guest_orders_but_never_reassigns_another_customer(self):
        guest=self.online();owned=self.online(self.other)
        session=self.client.session;session['online_orders']=[str(guest.token),str(owned.token)];session.save()
        self.client.post(reverse('customer_login'),{'username':self.customer.username,'password':'RitualCoffee!9284'})
        guest.refresh_from_db();owned.refresh_from_db()
        self.assertEqual(guest.customer_id,self.customer.pk)
        self.assertEqual(owned.customer_id,self.other.pk)
        self.assertNotContains(self.client.get(reverse('my_orders')),owned.number)

    def test_paid_receipt_flow_after_staff_records_payment(self):
        order=self.online(self.customer)
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse('customer_receipt',args=[order.token])).status_code,404)
        staff=Client();staff.force_login(self.cashier)
        response=staff.post(reverse('order_action',args=[order.pk]),{'action':'payment','method':'cash','amount':'200'})
        self.assertRedirects(response,reverse('order_detail',args=[order.pk]))
        receipt=reverse('customer_receipt',args=[order.token])
        self.assertContains(self.client.get(reverse('my_orders')),receipt)
        self.assertContains(self.client.get(reverse('tracking',args=[order.token])),'View receipt')
        response=self.client.get(receipt)
        for value in ['₱150.00','₱200.00','₱50.00','Print / Save as PDF','>PAID</p>','Order status: Pending']:
            self.assertContains(response,value)

    def test_receipt_history_is_available_from_a_new_browser_after_sign_in(self):
        order=self.online(self.customer);record_payment(order.pk,'cash',200,self.cashier)
        new_browser=Client()
        new_browser.post(reverse('customer_login'),{'username':self.customer.username,'password':'RitualCoffee!9284'})
        self.assertContains(new_browser.get(reverse('my_orders')),reverse('customer_receipt',args=[order.token]))

    def test_receipt_history_filters_paid_and_unpaid(self):
        paid=self.online(self.customer);unpaid=self.online(self.customer)
        record_payment(paid.pk,'cash',200,self.cashier)
        self.client.force_login(self.customer)
        response=self.client.get(reverse('my_orders'),{'payment':'paid'})
        self.assertContains(response,paid.number);self.assertNotContains(response,unpaid.number)
        response=self.client.get(reverse('my_orders'),{'payment':'unpaid'})
        self.assertContains(response,unpaid.number);self.assertNotContains(response,paid.number)

    def test_staff_cannot_reset_customer_password_or_change_customer_access(self):
        self.client.force_login(self.manager)
        for name in ['staff_password','staff_toggle']:
            response=self.client.post(reverse(name,args=[self.customer.pk]),{})
            self.assertEqual(response.status_code,404)
        self.assertNotContains(self.client.get(reverse('team')),self.customer.email)

    def test_unassigned_account_cannot_access_counter(self):
        user=User.objects.create_user('unassigned',password='Unassigned!7258')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('pos')).status_code,403)

    def test_customer_logout_clears_authenticated_history(self):
        self.online(self.customer);self.client.force_login(self.customer)
        self.assertRedirects(self.client.post(reverse('customer_logout')),reverse('shop'))
        self.assertNotIn('_auth_user_id',self.client.session)
        self.assertEqual(len(self.client.get(reverse('my_orders')).context['orders']),0)


class BuiltInMenuMigrationTests(TransactionTestCase):
    def test_normal_migrations_install_the_menu_without_an_import_command(self):
        before=[('cafe','0005_customer_accounts')];after=[('cafe','0006_builtin_menu')]
        empty_catalog();executor=MigrationExecutor(connection);executor.migrate(before)
        try:
            self.assertEqual(Product.objects.count(),0)
            MigrationExecutor(connection).migrate(after)
            self.assertEqual(Product.objects.count(),60)
            self.assertEqual(Ingredient.objects.count(),34)
            self.assertFalse(Order.objects.exists());self.assertFalse(Purchase.objects.exists())
            self.assertNotIn('load_coffee_menu',get_commands())
            self.assertFalse(User.objects.exists())
            p=Product.objects.get(menu_key='menu:americano-hot8');p.price=79;p.save()
            count=StockMovement.objects.count()
            MigrationExecutor(connection).migrate(after)
            p.refresh_from_db();self.assertEqual(p.price,79)
            self.assertEqual(StockMovement.objects.count(),count)
        finally:
            MigrationExecutor(connection).migrate(after)

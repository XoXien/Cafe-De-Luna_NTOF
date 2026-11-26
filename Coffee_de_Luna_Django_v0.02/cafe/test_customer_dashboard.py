"""Customer account history, ownership, filters, and safe reordering."""
import json
from django.contrib.auth.models import Group, User
from django.test import Client
from django.urls import reverse
from .models import Order, Product, RecipeItem, StockMovement
from .services import record_payment, change_order_status
from .tests import CafeFixture


class CustomerDashboardTests(CafeFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        customers = Group.objects.get_or_create(name='Customers')[0]
        cls.customer = User.objects.create_user('sofia@example.com', email='sofia@example.com', first_name='Sofia', password='MoonlitRitual!4729')
        cls.other = User.objects.create_user('isabel@example.com', email='isabel@example.com', first_name='Isabel', password='MoonlitRitual!4729')
        cls.customer.groups.add(customers); cls.other.groups.add(customers)
        cls.shot = Product.objects.create(name='Extra shot', menu_name='Espresso', category=cls.category, price=40,
            is_add_on=True, customization_type='espresso', max_per_drink=3)
        RecipeItem.objects.create(product=cls.shot, ingredient=cls.beans, quantity=9)

    def online(self, customer=None, **kwargs):
        return self.order(source='online', user=None, customer=customer or self.customer, paid=False, **kwargs)

    def test_customers_land_on_their_cafe_dashboard_when_signing_in(self):
        response = self.client.post(reverse('customer_login'), {'username':self.customer.username, 'password':'MoonlitRitual!4729'})
        self.assertRedirects(response, reverse('customer_dashboard'))
        self.assertContains(self.client.get(reverse('customer_dashboard')), 'Your first coffee moment')

    def test_dashboard_requires_a_customer_account(self):
        response = self.client.get(reverse('customer_dashboard'))
        self.assertRedirects(response, reverse('customer_login') + '?next=' + reverse('customer_dashboard'))
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse('customer_dashboard')).status_code, 403)

    def test_dashboard_counts_and_lists_only_the_current_customers_orders(self):
        mine = self.online(customer_name='Sofia coffee')
        paid = self.online(customer_name='Another Sofia coffee'); record_payment(paid.pk, 'cash', 200, self.cashier)
        hidden = self.online(self.other, customer_name='PRIVATE OTHER CUSTOMER')
        guest = self.order(source='online', user=None, customer=None, paid=False, customer_name='PRIVATE GUEST')
        self.client.force_login(self.customer)
        response = self.client.get(reverse('customer_dashboard'))
        self.assertEqual(response.context['order_totals'], {'total':2, 'active':2, 'receipts':1})
        for order in [mine, paid]: self.assertContains(response, order.number)
        for order in [hidden, guest]: self.assertNotContains(response, order.number)
        self.assertNotContains(response, 'PRIVATE OTHER CUSTOMER')
        self.assertContains(response, reverse('customer_receipt', args=[paid.token]))
        self.assertNotContains(response, reverse('customer_receipt', args=[mine.token]))
        self.assertIn('no-store', response['Cache-Control'])

    def test_history_survives_logout_and_sign_in_from_a_new_browser(self):
        order = self.online(); record_payment(order.pk, 'cash', 200, self.cashier)
        self.client.force_login(self.customer)
        self.client.post(reverse('customer_logout'))
        fresh = Client()
        fresh.post(reverse('customer_login'), {'username':self.customer.username, 'password':'MoonlitRitual!4729'})
        self.assertContains(fresh.get(reverse('customer_dashboard')), order.number)
        self.assertContains(fresh.get(reverse('my_orders')), reverse('customer_receipt', args=[order.token]))
        fresh.post(reverse('customer_logout')); fresh.force_login(self.other)
        self.assertNotContains(fresh.get(reverse('my_orders')), order.number)

    def test_guest_checkout_is_claimed_then_retained_after_logging_out(self):
        key = self.client.get(reverse('shop')).context['checkout_key']
        response = self.client.post(reverse('submit_order'), json.dumps({'source':'online', 'submission_key':key,
            'customer_name':'Sofia', 'phone':'09170000000', 'items':[{'id':self.product.pk, 'quantity':1}]}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        order = Order.objects.get()
        self.assertIsNone(order.customer_id)
        self.client.post(reverse('customer_login'), {'username':self.customer.username, 'password':'MoonlitRitual!4729'})
        order.refresh_from_db(); self.assertEqual(order.customer_id, self.customer.pk)
        self.client.post(reverse('customer_logout'))
        self.client.post(reverse('customer_login'), {'username':self.customer.username, 'password':'MoonlitRitual!4729'})
        self.assertContains(self.client.get(reverse('my_orders')), order.number)

    def test_recent_drinks_use_actual_selections_and_exclude_cancelled_orders(self):
        self.online(); self.online()
        custom = self.online(lines=[{'id':self.product.pk, 'quantity':1, 'add_ons':[{'id':self.shot.pk, 'quantity':2}]}])
        cancelled = self.online(); change_order_status(cancelled.pk, 'cancelled', self.cashier)
        self.client.force_login(self.customer)
        response = self.client.get(reverse('customer_dashboard'))
        drinks = response.context['recent_drinks']
        self.assertEqual(len(drinks), 2)
        self.assertEqual(drinks[0].order_id, custom.pk)
        self.assertTrue(all(item.order_id != cancelled.pk for item in drinks))
        self.assertContains(response, 'Extra espresso × 2')

    def test_history_search_and_status_filters_stay_scoped_to_the_owner(self):
        unpaid = self.online(); paid = self.online(); record_payment(paid.pk, 'cash', 200, self.cashier)
        other = self.online(self.other)
        self.client.force_login(self.customer)
        response = self.client.get(reverse('my_orders'), {'q':'Latte', 'payment':'unpaid', 'status':'active'})
        self.assertEqual([o.pk for o in response.context['orders']], [unpaid.pk])
        self.assertNotContains(response, paid.number); self.assertNotContains(response, other.number)
        response = self.client.get(reverse('my_orders'), {'q':other.number})
        self.assertEqual(len(response.context['orders']), 0)
        response = self.client.get(reverse('my_orders'), {'q':paid.number})
        self.assertEqual([o.pk for o in response.context['orders']], [paid.pk])

    def test_pagination_keeps_order_filters(self):
        for _ in range(11): self.online()
        self.client.force_login(self.customer)
        response = self.client.get(reverse('my_orders'), {'q':'Latte', 'status':'pending'})
        self.assertEqual(response.context['orders'].paginator.count, 11)
        self.assertContains(response, 'q=Latte&amp;status=pending&amp;page=2')
        response = self.client.get(reverse('my_orders'), {'q':'Latte', 'status':'pending', 'page':2})
        self.assertEqual(len(response.context['orders']), 1)

    def test_reorder_is_post_only_and_requires_owner_and_csrf(self):
        order = self.online()
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse('reorder', args=[order.token])).status_code, 405)
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.customer)
        self.assertEqual(csrf.post(reverse('reorder', args=[order.token])).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('reorder', args=[order.token])).status_code, 404)
        self.assertNotIn('reorder_draft', self.client.session)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.post(reverse('reorder', args=[order.token])).status_code, 403)

    def test_reorder_preserves_exact_extras_and_reviews_current_prices_without_reserving_stock(self):
        order = self.online(lines=[{'id':self.product.pk, 'quantity':2, 'add_ons':[{'id':self.shot.pk, 'quantity':3}]}])
        stock, movements = self.balance(self.beans), StockMovement.objects.count()
        Product.objects.filter(pk=self.product.pk).update(price=175)
        Product.objects.filter(pk=self.shot.pk).update(price=45)
        self.client.force_login(self.customer)
        response = self.client.post(reverse('reorder', args=[order.token]))
        self.assertRedirects(response, reverse('shop') + '#menu', fetch_redirect_response=False)
        response = self.client.get(reverse('shop'))
        self.assertEqual(response.context['reorder_data']['items'], [{'id':self.product.pk, 'quantity':2,
            'add_ons':[{'id':self.shot.pk, 'quantity':3}]}])
        prices = {p['id']:p['price'] for p in response.context['products_data']}
        self.assertEqual(prices[self.product.pk], '175.00'); self.assertEqual(prices[self.shot.pk], '45.00')
        order.refresh_from_db(); self.assertEqual(order.total, 540)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self.balance(self.beans), stock)
        self.assertEqual(StockMovement.objects.count(), movements)
        self.assertIsNone(self.client.get(reverse('shop')).context['reorder_data'])

    def test_customer_forms_use_same_origin_policy_and_keep_csrf_protection(self):
        order = self.online()
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.customer)
        page = browser.get(reverse('customer_dashboard'))
        self.assertEqual(page['Referrer-Policy'], 'same-origin')
        token = browser.cookies['csrftoken'].value
        endpoint = reverse('reorder', args=[order.token])
        self.assertEqual(browser.post(endpoint, {'csrfmiddlewaretoken':token}, HTTP_ORIGIN='http://testserver').status_code, 302)
        self.assertEqual(browser.post(endpoint, {'csrfmiddlewaretoken':token}, HTTP_ORIGIN='null').status_code, 403)

    def test_one_recent_drink_can_be_reordered_without_the_rest_of_the_order(self):
        order = self.online(lines=[{'id':self.product.pk, 'quantity':1},
            {'id':self.product.pk, 'quantity':2, 'add_ons':[{'id':self.shot.pk, 'quantity':1}]}])
        bases = list(order.items.filter(parent_item__isnull=True))
        self.client.force_login(self.customer)
        self.client.post(reverse('reorder', args=[order.token]), {'item':bases[1].pk})
        response = self.client.get(reverse('shop'))
        self.assertEqual(response.context['reorder_data']['items'], [{'id':self.product.pk, 'quantity':2,
            'add_ons':[{'id':self.shot.pk, 'quantity':1}]}])

    def test_reorder_never_silently_drops_an_unavailable_extra(self):
        order = self.online(lines=[{'id':self.product.pk, 'quantity':1, 'add_ons':[{'id':self.shot.pk, 'quantity':1}]}])
        Product.objects.filter(pk=self.shot.pk).update(is_active=False)
        self.client.force_login(self.customer)
        response = self.client.post(reverse('reorder', args=[order.token]), follow=True)
        self.assertContains(response, 'An add-on is unavailable')
        self.assertNotIn('reorder_draft', self.client.session)
        self.assertEqual(Order.objects.count(), 1)

    def test_deleted_drink_remains_in_history_and_cannot_be_reordered(self):
        order = self.online(); self.product.delete()
        self.client.force_login(self.customer)
        response = self.client.get(reverse('customer_dashboard'))
        self.assertContains(response, 'Latte'); self.assertContains(response, 'Currently off the menu')
        response = self.client.post(reverse('reorder', args=[order.token]), follow=True)
        self.assertContains(response, 'A drink in that order is no longer available')
        self.assertNotIn('reorder_draft', self.client.session)

    def test_an_item_from_another_order_cannot_be_injected_into_a_reorder(self):
        order = self.online(); other = self.online(self.other)
        self.client.force_login(self.customer)
        response = self.client.post(reverse('reorder', args=[order.token]), {'item':other.items.get().pk}, follow=True)
        self.assertContains(response, 'This drink is no longer available')
        self.assertNotIn('reorder_draft', self.client.session)

    def test_collection_links_initialise_menu_category_and_search(self):
        response = self.client.get(reverse('shop'), {'category':'Coffee', 'q':'Latte'})
        self.assertEqual(response.context['initial_category'], 'Coffee')
        self.assertContains(response, 'data-initial-search="Latte"')
        response = self.client.get(reverse('shop'), {'category':'not-a-category'})
        self.assertEqual(response.context['initial_category'], 'all')

    def test_footer_and_customer_navigation_render_on_all_public_screens(self):
        self.client.force_login(self.customer)
        for name in ['shop','customer_dashboard','my_orders']:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, 'class="luna-footer"')
                self.assertContains(response, 'Mobile café navigation')
                self.assertContains(response, 'There’s always room')
                self.assertContains(response, 'css/customer.css?v=0.02')

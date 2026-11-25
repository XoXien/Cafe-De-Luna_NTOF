"""Customer receipts become available only after staff confirm payment."""
import uuid
from django.urls import reverse
from .models import Order, Product, RecipeItem, StockMovement
from .services import record_payment, change_order_status, record_refund
from .tests import CafeFixture


class CustomerReceiptTests(CafeFixture):
    def guest_order(self, **kwargs):
        return self.order(source='online', user=None, paid=False, customer_name='Sofia Luna', **kwargs)

    def confirm_payment(self, order, method='cash', amount=200):
        return record_payment(order.pk, method, amount, self.cashier)

    def test_unpaid_order_shows_receipt_hint_without_access(self):
        order=self.guest_order()
        response=self.client.get(reverse('tracking',args=[order.token]))
        self.assertContains(response,'Your receipt will appear here once payment is confirmed')
        self.assertNotContains(response,'data-customer-receipt')
        for query in ['', '?paid=true']:
            self.assertEqual(self.client.get(reverse('customer_receipt',args=[order.token])+query).status_code,404)
        order.refresh_from_db();self.assertFalse(order.paid)

    def test_receipt_is_linked_and_available_immediately_after_payment(self):
        order=self.guest_order()
        self.confirm_payment(order)
        # Receipt is available while the order is still pending; completion is not required.
        response=self.client.get(reverse('tracking',args=[order.token]))
        self.assertContains(response,reverse('customer_receipt',args=[order.token]))
        self.assertContains(response,'View receipt')
        receipt=self.client.get(reverse('customer_receipt',args=[order.token]))
        self.assertEqual(receipt.status_code,200)
        for text in [order.number,'Sofia Luna','Latte','₱150.00','₱200.00','Change','₱50.00','Cash']:
            self.assertContains(receipt,text)
        self.assertContains(receipt,'Print / Save as PDF')
        self.assertContains(receipt,'data-print')
        self.assertContains(receipt,reverse('tracking',args=[order.token]))
        self.assertContains(receipt,'Back to my order')
        self.assertNotContains(receipt,reverse('order_detail',args=[order.pk]))

    def test_non_cash_receipts_show_confirmed_method_without_cash_change(self):
        for method,label in [('gcash','GCash'),('card','Card')]:
            with self.subTest(method=method):
                order=self.guest_order();self.confirm_payment(order,method,0)
                response=self.client.get(reverse('customer_receipt',args=[order.token]))
                self.assertContains(response,label)
                self.assertNotContains(response,'>Change<')
                self.assertNotContains(response,'PAYMENT DUE AT COUNTER')

    def test_itemized_drink_extras_use_original_order_prices(self):
        extra=Product.objects.create(name='Whip cream',menu_name='Whip cream',category=self.category,
            price=25,is_add_on=True,customization_type='whip')
        RecipeItem.objects.create(product=extra,ingredient=self.milk,quantity=5)
        order=self.guest_order(lines=[{'id':self.product.pk,'quantity':2,
            'add_ons':[{'id':extra.pk,'quantity':1}]}])
        self.confirm_payment(order,amount=400)
        extra.price=99;extra.save()
        self.product.price=250;self.product.save()
        response=self.client.get(reverse('customer_receipt',args=[order.token]))
        for text in ['2 × Latte','Extra whipped cream','For Latte','₱25.00','₱350.00']:
            self.assertContains(response,text)
        self.assertNotContains(response,'₱99.00')
        self.assertNotContains(response,'₱250.00')

    def test_paid_cancellation_receipt_shows_refund_state(self):
        order=self.guest_order();self.confirm_payment(order)
        change_order_status(order.pk,'cancelled',self.manager)
        url=reverse('customer_receipt',args=[order.token])
        self.assertContains(self.client.get(url),'REFUND DUE')
        record_refund(order.pk,self.manager)
        self.assertContains(self.client.get(url),'REFUNDED')
        self.assertContains(self.client.get(reverse('tracking',args=[order.token])),'View receipt')

    def test_unpaid_cancellation_has_no_receipt(self):
        order=self.guest_order();change_order_status(order.pk,'cancelled',self.cashier)
        self.assertEqual(self.client.get(reverse('customer_receipt',args=[order.token])).status_code,404)
        self.assertNotContains(self.client.get(reverse('tracking',args=[order.token])),'data-customer-receipt')

    def test_private_token_required_and_staff_receipt_remains_staff_only(self):
        first=self.guest_order();self.confirm_payment(first)
        self.order(source='online',user=None,customer_name='Other guest')
        self.assertContains(self.client.get(reverse('customer_receipt',args=[first.token])),'Sofia Luna')
        self.assertNotContains(self.client.get(reverse('customer_receipt',args=[first.token])),'Other guest')
        self.assertEqual(self.client.get(reverse('customer_receipt',args=[uuid.uuid4()])).status_code,404)
        self.assertEqual(self.client.get(f'/order/receipt/{first.pk}/').status_code,404)
        self.assertEqual(self.client.get(reverse('receipt',args=[first.pk])).status_code,302)
        self.client.force_login(self.cashier)
        staff=self.client.get(reverse('receipt',args=[first.pk]))
        self.assertContains(staff,'Print receipt')
        self.assertContains(staff,reverse('order_detail',args=[first.pk]))

    def test_customer_receipt_and_status_cannot_write_payment(self):
        order=self.guest_order()
        for name in ['customer_receipt','tracking_status']:
            self.assertEqual(self.client.post(reverse(name,args=[order.token]),{'paid':True}).status_code,405)
        order.refresh_from_db();self.assertFalse(order.paid)

    def test_live_status_changes_after_payment_and_does_not_expose_contact_details(self):
        order=self.guest_order()
        url=reverse('tracking_status',args=[order.token])
        self.assertEqual(self.client.get(url).json(),{'paid':False,'status':'pending','refund_due':False})
        self.confirm_payment(order)
        self.assertEqual(self.client.get(url).json(),{'paid':True,'status':'pending','refund_due':False})
        change_order_status(order.pk,'cancelled',self.manager)
        self.assertEqual(self.client.get(url).json(),{'paid':True,'status':'cancelled','refund_due':True})
        self.assertEqual(self.client.get(reverse('tracking_status',args=[uuid.uuid4()])).status_code,404)

    def test_tracking_receipt_and_status_disable_cache_referrers_and_indexing(self):
        order=self.guest_order();self.confirm_payment(order)
        for name in ['tracking','tracking_status','customer_receipt']:
            with self.subTest(page=name):
                response=self.client.get(reverse(name,args=[order.token]))
                self.assertIn('no-store',response['Cache-Control'])
                self.assertIn('private',response['Cache-Control'])
                self.assertEqual(response['Referrer-Policy'],'no-referrer')
                self.assertEqual(response['X-Robots-Tag'],'noindex, nofollow')

    def test_tracking_includes_payment_refresh_script_and_no_receipt_reads_change_stock(self):
        order=self.guest_order();self.confirm_payment(order)
        count=StockMovement.objects.count();balance=self.balance(self.beans)
        response=self.client.get(reverse('tracking',args=[order.token]))
        self.assertContains(response,'data-order-tracking')
        self.assertContains(response,reverse('tracking_status',args=[order.token]))
        self.assertContains(response,'js/tracking.js')
        for name in ['customer_receipt','tracking_status']:
            for _ in range(2):
                self.assertEqual(self.client.get(reverse(name,args=[order.token])).status_code,200)
        self.assertEqual(StockMovement.objects.count(),count)
        self.assertEqual(self.balance(self.beans),balance)

"""Fresh installations start without business records or preset credentials."""
from io import StringIO
from django.contrib.auth.models import User
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from .test_helpers import ensure_catalog
from .models import Category, Ingredient, Order, Product, Purchase, StockMovement


class CleanStartTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_catalog()
    def test_new_schema_has_no_accounts_or_business_data(self):
        for model in [User, Order, Purchase]:
            with self.subTest(model=model.__name__):
                self.assertEqual(model.objects.count(), 0)
        response = self.client.get(reverse('shop'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Americano')
        self.assertEqual(Product.objects.count(), 60)
        self.assertEqual(Ingredient.objects.count(), 34)
        self.assertEqual(User.objects.count(), 0)

    def test_noninteractive_setup_requires_the_owner_to_create_an_account(self):
        with self.assertRaisesMessage(CommandError, 'createsuperuser'):
            call_command('ensure_admin', interactive=False, stdout=StringIO())
        self.assertFalse(User.objects.exists())
        self.assertEqual(Product.objects.count(), 60)

    def test_setup_does_not_silently_reactivate_a_disabled_administrator(self):
        user = User.objects.create_superuser('disabledowner', password='Moonlight!6281', is_active=False)
        with self.assertRaises(CommandError):
            call_command('ensure_admin', interactive=False, stdout=StringIO())
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(User.objects.count(), 1)

    def test_demo_data_loader_is_not_available(self):
        self.assertNotIn('seed_demo', get_commands())
        self.assertNotIn('load_coffee_menu', get_commands())

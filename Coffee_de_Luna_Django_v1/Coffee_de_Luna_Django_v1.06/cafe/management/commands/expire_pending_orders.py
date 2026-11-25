from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from cafe.models import Order
from cafe.services import change_order_status

class Command(BaseCommand):
    help = 'Cancel unpaid pending online orders older than the chosen time and release their stock.'
    def add_arguments(self, parser):
        parser.add_argument('--minutes', type=int, default=30)
    def handle(self, *args, **options):
        if options['minutes'] < 5:
            raise CommandError('Use an expiry of at least 5 minutes.')
        cutoff=timezone.now()-timedelta(minutes=options['minutes'])
        ids=list(Order.objects.filter(source='online', status='pending', paid=False, created_at__lt=cutoff).values_list('pk',flat=True))
        count=0
        from django.db import transaction
        for pk in ids:
            with transaction.atomic():
                order=Order.objects.select_for_update().get(pk=pk)
                if order.status=='pending' and not order.paid:
                    change_order_status(order.pk,'cancelled',None)
                    order.events.create(message='Unpaid online order expired; reserved ingredients released.')
                    count+=1
        self.stdout.write(self.style.SUCCESS(f'Expired {count} unpaid pending online order(s).'))

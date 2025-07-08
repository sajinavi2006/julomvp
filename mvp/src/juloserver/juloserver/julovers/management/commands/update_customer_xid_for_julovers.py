from django.core.management.base import BaseCommand
from juloserver.julo.models import Customer
from juloserver.julovers.models import Julovers

class Command(BaseCommand):
    help = "Command to update customer_xid from customer table to julover table"

    def handle(self, *args, **options):
        try:
            # Iterate over Julovers instances and update customer_xid
            for julover_instance in Julovers.objects.filter(customer_xid__isnull=True, is_sync_application=True):
                try:
                    # Retrieve customer_xid based on email
                    customer_xid = Customer.objects.filter(email=julover_instance.email).values('customer_xid').first()
                    if customer_xid:
                        # Update customer_xid in Julovers
                        Julovers.objects.filter(id=julover_instance.id).update(customer_xid=customer_xid['customer_xid'])

                except Customer.DoesNotExist:
                    # Handle the case where corresponding Customer does not exist
                    pass

            self.stdout.write(self.style.SUCCESS('Updated all customer_xid in Julovers from Customer'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))

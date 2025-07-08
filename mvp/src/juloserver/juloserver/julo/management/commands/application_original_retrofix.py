from django.core.management.base import BaseCommand
from juloserver.julo.models import Customer
from django.core.exceptions import ObjectDoesNotExist


class Command(BaseCommand):
    help = 'Try to match application_originals to application table'

    def handle(self, *args, **options):
        customers = Customer.objects.filter(applicationoriginal__isnull=False)
        for customer in customers:

            applications = customer.application_set.all()
            application_originals = customer.applicationoriginal_set.filter()

            count_orig_app = application_originals.count()
            count_app = applications.count()

            if count_orig_app == 1 and count_app == 1:
                app_original = application_originals.first()
                app_original.current_application = applications.first()
                app_original.save()
                continue
            for app_original in application_originals:
                if app_original.application_number:
                    try:
                        app_original.current_application = applications.get(application_number=app_original.application_number)
                        app_original.save()
                    except ObjectDoesNotExist:
                        pass
                elif app_original.application_xid:
                    try:
                        app_original.current_application = applications.get(application_xid=app_original.application_xid)
                        app_original.save()
                    except ObjectDoesNotExist:
                        pass

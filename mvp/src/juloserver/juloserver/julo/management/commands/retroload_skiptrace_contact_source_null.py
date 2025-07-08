from django.core.management.base import BaseCommand
from django.db.models import Q
from django.db import transaction
from juloserver.julo.models import Skiptrace
from juloserver.julo.utils import format_e164_indo_phone_number

class Command(BaseCommand):
    help = 'set value skiptrace contact source column if its null or blank'

    def handle(self, *args, **options):
        skiptraces=Skiptrace.objects.filter(
            Q(application__isnull=False)&(Q(contact_source__isnull=True)|Q(contact_source=''))
        ).exclude(phone_number__isnull=True)
        for skiptrace in skiptraces:
            with transaction.atomic():
                success_msg='skiptrace id %s berhasil diupdate'%skiptrace.id
                try:
                    if skiptrace.phone_number == format_e164_indo_phone_number(skiptrace.application.mobile_phone_1):
                        skiptrace.update_safely(contact_source='mobile_phone_1')
                        self.stdout.write(self.style.SUCCESS(success_msg))
                        continue
                    elif skiptrace.phone_number == format_e164_indo_phone_number(skiptrace.application.mobile_phone_2):
                        skiptrace.update_safely(contact_source='mobile_phone_2')
                        self.stdout.write(self.style.SUCCESS(success_msg))
                        continue
                    elif skiptrace.phone_number == format_e164_indo_phone_number(skiptrace.application.spouse_mobile_phone):
                        skiptrace.update_safely(contact_source='spouse_mobile_phone')
                        self.stdout.write(self.style.SUCCESS(success_msg))
                        continue
                    elif skiptrace.phone_number == format_e164_indo_phone_number(skiptrace.application.kin_mobile_phone):
                        skiptrace.update_safely(contact_source='kin_mobile_phone')
                        self.stdout.write(self.style.SUCCESS(success_msg))
                        continue
                    elif skiptrace.phone_number == format_e164_indo_phone_number(skiptrace.application.close_kin_mobile_phone):
                        skiptrace.update_safely(contact_source='close_kin_mobile_phone')
                        self.stdout.write(self.style.SUCCESS(success_msg))
                        continue
                    elif skiptrace.phone_number == format_e164_indo_phone_number(skiptrace.application.landlord_mobile_phone):
                        skiptrace.update_safely(contact_source='landlord_mobile_phone')
                        self.stdout.write(self.style.SUCCESS(success_msg))
                        continue
                    elif skiptrace.phone_number == format_e164_indo_phone_number(skiptrace.application.company_phone_number):
                        skiptrace.update_safely(contact_source='company_phone_number')
                        self.stdout.write(self.style.SUCCESS(success_msg))
                        continue
                except Exception as e:
                    self.stdout.write(self.style.ERROR(str(e)))
                else:
                    self.stdout.write(self.style.WARNING('skiptrace id %s tidak diupdate'%skiptrace.id))

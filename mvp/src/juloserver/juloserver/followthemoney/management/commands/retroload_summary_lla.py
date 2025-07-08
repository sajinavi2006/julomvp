from __future__ import division
from builtins import str
from builtins import range
from past.utils import old_div
import logging
import sys

from django.core.management.base import BaseCommand
from juloserver.julo.models import Application
from juloserver.followthemoney.tasks import (generate_summary_lender_loan_agreement,
                                             assign_lenderbucket_xid_to_lendersignature)
from juloserver.followthemoney.models import LenderBucket
from juloserver.followthemoney.utils import generate_lenderbucket_xid
from django.db.models import Sum

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

class Command(BaseCommand):
    def handle(self, **options):
        try:
            lender_bucket_id = 145
            n = 1

            lender_bucket = LenderBucket.objects.get_or_none(pk=lender_bucket_id)
            if not lender_bucket:
                logger.error({
                    'action_view': 'retroload_summary_lla',
                    'data': {'lender_bucket_id': lender_bucket_id},
                    'errors': "Lender Bucket tidak ditemukan."
                })
                return

            update_application_ids = dict(
                approved=[],
                rejected=lender_bucket.application_ids["rejected"],
            )
            application_ids = lender_bucket.application_ids["approved"]
            application_id_batches = [application_ids[i * n:(i + 1) * n] for i in range(old_div((len(application_ids) + n - 1), n) )]

            for application_id_batch in application_id_batches:
                new_application_ids = dict(
                    approved=application_id_batch,
                    rejected=[],
                )

                # total disbursement amount and total loan amount
                fields = ("loan_disbursement_amount", "loan_amount")
                total = {"loan_disbursement_amount": 0, "loan_amount": 0}

                for field in fields:
                    subtotal = Application.objects.filter(
                        id__in=new_application_ids['approved']).aggregate(
                        Sum( 'loan__%s' % (field) ))
                    if not subtotal['loan__%s__sum' % (field)]:
                        subtotal['loan__%s__sum' % (field)] = 0

                    total[field] = subtotal['loan__%s__sum' % (field)]

                new_lender_bucket = LenderBucket.objects.create(
                    partner=lender_bucket.partner,
                    total_approved=len(application_id_batch),
                    total_rejected=0,
                    total_disbursement=total['loan_disbursement_amount'],
                    total_loan_amount=total['loan_amount'],
                    application_ids=new_application_ids,
                    is_disbursed=lender_bucket.is_disbursed,
                    is_active=lender_bucket.is_active,
                    is_signed=lender_bucket.is_signed,
                    action_time=lender_bucket.action_time,
                    action_name=lender_bucket.action_name,
                    lender_bucket_xid=generate_lenderbucket_xid()
                )

                # generate summary lla
                assign_lenderbucket_xid_to_lendersignature(
                    application_id_batch, new_lender_bucket.lender_bucket_xid)
                generate_summary_lender_loan_agreement(new_lender_bucket.id, True)
                self.stdout.write(self.style.SUCCESS(
                    "Success create new Lender Bucket with xid: {} and application_ids: {}".format(
                        new_lender_bucket.lender_bucket_xid, application_id_batch
                    ))
                )

            lender_bucket.update_safely(
                application_ids=update_application_ids,
                total_approved=0,
                total_disbursement=0,
                total_loan_amount=0,
            )
            self.stdout.write(self.style.SUCCESS("Successfully regenerate LLA"))

        except Exception as e:
            logger.error({
                'action_view': 'FollowTheMoney - retroload_summary_lla',
                'data': {'lender_bucket_id': lender_bucket_id},
                'errors': str(e)
            })
            self.stdout.write(self.style.ERROR(str(e)))
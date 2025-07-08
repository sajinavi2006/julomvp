import logging
import sys

from django.core.management.base import BaseCommand
from django.utils import timezone

from juloserver.julo.models import Payment
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.clients import get_julo_centerix_client
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.services import sort_payments_by_collection_model
from juloserver.minisquad.services import (get_payment_details_for_calling,
                                            upload_payment_details,
                                            upload_ptp_agent_level_data)

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('-t', '--type', type=str, help='Define bucket type')

    def handle(self, **options):
        self.type = options['type']

        if self.type == 'T-1':
            payment_Tminus1 = get_payment_details_for_calling('JULO_T-1')
            payments_collection = sort_payments_by_collection_model(payment_Tminus1, '-1')

            if len(payments_collection) > 0:
                response = upload_payment_details(payments_collection, 'JULO_T-1')
            else:
                response = upload_payment_details(payment_Tminus1, 'JULO_T-1')

            logger.info({
                'status': response
            })
        if self.type == 'T0':
            payment_T0 = get_payment_details_for_calling('JULO_T0')
            payments_collection = sort_payments_by_collection_model(payment_T0, '0')

            if len(payments_collection) > 0:
                response = upload_payment_details(payments_collection, 'JULO_T0')
            else:
                response = upload_payment_details(payment_T0, 'JULO_T0')

            logger.info({
                'status': response
            })
        if self.type == 'T1-4':
            payment_T1to4 = get_payment_details_for_calling('JULO_T1-T4')
            payments_collection = sort_payments_by_collection_model(payment_T1to4, ['1', '2', '3', '4'])

            if len(payments_collection) > 0:
                response = upload_payment_details(payments_collection, 'JULO_T1-T4')
            else:
                response = upload_payment_details(payment_T1to4, 'JULO_T1-T4')

            logger.info({
                'status': response
            })
        if self.type == 'T5-10':
            payment_T5to10 = get_payment_details_for_calling('JULO_T5-T10')
            payments_collection = sort_payments_by_collection_model(payment_T5to10, ['5', '6', '7', '8', '9', '10'])

            if len(payments_collection) > 0:
                response = upload_payment_details(payments_collection, 'JULO_T5-T10')
            else:
                response = upload_payment_details(payment_T5to10, 'JULO_T5-T10')

            logger.info({
                'status': response
            })
        if self.type == 'JULO_B2':
            payments = get_payment_details_for_calling('JULO_B2')
            response = upload_payment_details(payments, 'JULO_B2')
            logger.info({
                'status': response
            })
        if self.type == 'JULO_B2.S1':
            payments = get_payment_details_for_calling('JULO_B2.S1')
            response = upload_payment_details(payments, 'JULO_B2.S1')
            logger.info({
                'status': response
            })
        if self.type == 'JULO_B2.S2':
            payments = get_payment_details_for_calling('JULO_B2.S2')
            response = upload_payment_details(payments, 'JULO_B2.S2')
            logger.info({
                'status': response
            })
        if self.type == 'JULO_B3':
            payments = get_payment_details_for_calling('JULO_B3')
            response = upload_payment_details(payments, 'JULO_B3')
            logger.info({
                'status': response
            })
        if self.type == 'JULO_B3.S1':
            payments = get_payment_details_for_calling('JULO_B3.S1')
            response = upload_payment_details(payments, 'JULO_B3.S1')
            logger.info({
                'status': response
            })
        if self.type == 'JULO_B3.S2':
            payments = get_payment_details_for_calling('JULO_B3.S2')
            response = upload_payment_details(payments, 'JULO_B3.S2')
            logger.info({
                'status': response
            })
        if self.type == 'JULO_B3.S3':
            payments = get_payment_details_for_calling('JULO_B3.S3')
            response = upload_payment_details(payments, 'JULO_B3.S3')
            logger.info({
                'status': response
            })
        if self.type == 'JULO_B4':
            payments = get_payment_details_for_calling('JULO_B4')
            response = upload_payment_details(payments, 'JULO_B4')
            logger.info({
                'status': response
            })
        if self.type == 'JULO_B4.S1':
            payments = get_payment_details_for_calling('JULO_B4.S1')
            response = upload_payment_details(payments, 'JULO_B4.S1')
            logger.info({
                'status': response
            })
        if self.type == 'PTP':
            payments = get_payment_details_for_calling('PTP')
            payment_groups = dict()
            for obj in payments:
                payment_groups.setdefault(obj.squad.squad_name, []).append(obj)

            upload_ptp_agent_level_data(payment_groups)

import logging
from rest_framework.views import APIView
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Loan, Partner

from juloserver.qris.services.user_related import (
    QrisListTransactionService,
)
from juloserver.qris.exceptions import QrisLinkageNotFound

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class QrisTransactionListViewV2(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        limit = int(self.request.query_params.get("limit", 0))
        partner_name = self.request.query_params.get("partner_name")
        partner = Partner.objects.get_or_none(name=partner_name)
        if not partner:
            return general_error_response("Partner not found")

        customer = request.user.customer
        try:
            qris_list_transaction_service = QrisListTransactionService(
                customer_id=customer.id, partner_id=partner.pk
            )
            transactions = qris_list_transaction_service.get_all_transactions(limit=limit)
            return success_response(transactions)
        except QrisLinkageNotFound:
            logger.info(
                {
                    'message': 'Qris linkage not found',
                    'action': 'QrisTransactionListViewV2',
                    'customer_id': customer.id,
                    'Partner_name': partner.name,
                }
            )
            return general_error_response("Qris User Linkage not found")

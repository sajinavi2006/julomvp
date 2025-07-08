import logging
from typing import Any

from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.workflows2.handlers import BaseActionHandler
from juloserver.merchant_financing.web_app.workflows import PartnershipMfWebAppWorkflowAction
from juloserver.fdc.services import check_fdc_inquiry
from juloserver.merchant_financing.services import (
    mf_generate_va_for_bank_bca,
)
from juloserver.partnership.clients import get_julo_sentry_client

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class PartnershipMfWebAppWorkflowHandler(BaseActionHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.action = PartnershipMfWebAppWorkflowAction(
            self.application,
            self.new_status_code,
            self.change_reason,
            self.note,
            self.old_status_code,
        )


class PartnershipMF100Handler(PartnershipMfWebAppWorkflowHandler):
    def async_task(self) -> None:
        if check_fdc_inquiry(self.application.id) and self.application.ktp:
            self.action.run_fdc_task()


class PartnershipMF105Handler(PartnershipMfWebAppWorkflowHandler):
    def async_task(self) -> None:
        self.action.check_fullname_with_DTTOT()
        self.action.check_customer_fraud()
        self.action.check_customer_delinquent()
        self.action.change_application_status()


class PartnershipMF130Handler(PartnershipMfWebAppWorkflowHandler):
    def post(self) -> None:
        self.action.generate_mf_partnership_credit_limit()


class PartnershipMF141Handler(PartnershipMfWebAppWorkflowHandler):
    def post(self) -> None:
        product_line_codes_list = [
            ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
            ProductLineCodes.AXIATA_WEB,
        ]
        if self.action.application.product_line_code in product_line_codes_list:
            # if there was another logic please add it before checking dukcapil fr due to on
            # dukcapil fr we move status to 190 on that logic
            try:
                self.action.dukcapil_fr_mf()
            except Exception as error:
                logger.info(
                    {
                        'action': "PartnershipMF141Handler",
                        'message': "Error dukcapil fr axiata webapp",
                        'application_id': self.application.id,
                        'error': str(error),
                    }
                )
                sentry_client.captureException()


class PartnershipMF190Handler(PartnershipMfWebAppWorkflowHandler):
    def post(self) -> None:
        self.action.activate_mf_partnership_web_app_account()

        mf_generate_va_for_bank_bca(self.application)


class PartnershipMF135Handler(PartnershipMfWebAppWorkflowHandler):
    def post(self) -> None:
        self.action.process_reapply_mf_webapp_application()


class PartnershipMF131Handler(PartnershipMfWebAppWorkflowHandler):
    pass


class PartnershipMF132Handler(PartnershipMfWebAppWorkflowHandler):
    pass


class PartnershipMF133Handler(PartnershipMfWebAppWorkflowHandler):
    pass

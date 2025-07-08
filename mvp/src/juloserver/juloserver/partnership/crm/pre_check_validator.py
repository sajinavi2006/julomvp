from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.partnership.constants import PartnershipPreCheckFlag
from juloserver.partnership.models import PartnershipCustomerData, PartnershipApplicationFlag

from typing import Dict


class PreCheckExistedValidator:

    def __init__(self, application_data: Dict) -> None:
        """
            application_data contains:
            - id(application_id): required
            - application_status: required
            - customer_id: required
            - application_xid: required
        """
        self.application_data = application_data
        self.passed_application_flag_name = {
            PartnershipPreCheckFlag.PASSED_PRE_CHECK,
            PartnershipPreCheckFlag.NOT_PASSED_BINARY_PRE_CHECK,
            PartnershipPreCheckFlag.PASSED_BINARY_PRE_CHECK,
            PartnershipPreCheckFlag.REGISTER_FROM_PORTAL,
            PartnershipPreCheckFlag.APPROVED,
        }
        self.passed_application_status = {
            ApplicationStatusCodes.FORM_CREATED,
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
        }

    def is_have_application_status(self) -> bool:
        if self.application_data.get('application_status'):
            return True
        return False

    def is_have_customer_id(self) -> bool:
        if self.application_data.get('customer_id'):
            return True
        return False

    def is_have_partnership_customer_data(self) -> bool:
        partnership_customer_data = PartnershipCustomerData.objects.filter(
            application_id=self.application_data.get('id')
        ).exists()
        return partnership_customer_data

    def is_application_have_flag(self) -> bool:
        application_id = self.application_data.get('id')
        application_flag_name = (
            PartnershipApplicationFlag.objects.filter(application_id=application_id)
            .values_list('name', flat=True)
            .last()
        )
        if not application_flag_name:
            return False

        if application_flag_name not in self.passed_application_flag_name:
            return False

        return True

    def is_passed_application(self) -> bool:
        if self.application_data.get('application_status') not in self.passed_application_status:
            return False

        return True

import logging

from django.db import transaction
from django.utils import timezone

from juloserver.account.constants import AccountConstant
from juloserver.account.models import Account, AccountLimit, AccountLookup
from juloserver.account.services.account_related import process_change_account_status
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.customer_module.models import CustomerLimit
from juloserver.julo.models import (
    CreditScore,
    BlacklistCustomer,
    Application,
    ApplicationHistory,
    ApplicationNote,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.workflows import WorkflowAction
from juloserver.merchant_financing.constants import MFStandardRejectReason
from juloserver.merchant_financing.web_app.services import store_account_property_mf_partnership
from juloserver.merchant_financing.web_app.tasks import dukcapil_fr_mf_trigger_task
from juloserver.partnership.clients import get_julo_sentry_client
from juloserver.partnership.constants import PartnershipFeatureNameConst
from juloserver.partnership.models import PartnershipCustomerData, PartnershipFeatureSetting
from juloserver.julo.utils import trim_name
from juloserver.dana.constants import INDONESIA
from juloserver.merchant_financing.web_app.services import update_application_reject_reason
from juloserver.partnership.utils import (
    partnership_detokenize_sync_object_model,
    generate_pii_filter_query_partnership,
)
from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class PartnershipMfWebAppWorkflowAction(WorkflowAction):
    def check_fullname_with_DTTOT(self) -> None:
        application = self.application
        detokenize_application = partnership_detokenize_sync_object_model(
            PiiSource.APPLICATION,
            application,
            application.customer.customer_xid,
            ['fullname'],
        )
        fullname = detokenize_application.fullname
        stripped_name = trim_name(fullname)
        black_list_customer = BlacklistCustomer.objects.filter(
            fullname_trim__iexact=stripped_name, citizenship__icontains=INDONESIA
        ).exists()
        if black_list_customer:
            if (
                application.product_line_code
                == ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
            ):
                reject_reason = {
                    "name": MFStandardRejectReason.BLACKLIST.get('name'),
                    "label": MFStandardRejectReason.BLACKLIST.get('label'),
                }
            else:
                reject_reason = {"name": "black_list_customer", "label": "Black List Customer"}
            update_application_reject_reason(application.id, reject_reason)

    def check_customer_fraud(self) -> None:
        """
        - NIK / Phone application exists
        - Check all data if fraud status (133) in application history, not current application and
        - If account status is fraud 440,441 also rejected
        """
        application = self.application
        partnership_customer_data = application.customer.partnershipcustomerdata_set.last()
        detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
            PiiSource.PARTNERSHIP_CUSTOMER_DATA,
            partnership_customer_data,
            application.customer.customer_xid,
            ['nik', 'phone_number'],
        )
        mobile_phone_1 = detokenize_partnership_customer_data.phone_number
        nik = detokenize_partnership_customer_data.nik
        fraud_status = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
        fraud_account_status = {
            AccountConstant.STATUS_CODE.fraud_reported,
            AccountConstant.STATUS_CODE.application_or_friendly_fraud,
        }

        pii_nik_filter_dict = generate_pii_filter_query_partnership(Application, {'ktp': nik})
        nik_applications = Application.objects.filter(**pii_nik_filter_dict).exclude(
            id=application.id
        )
        if nik_applications:
            """
            Application checking based nik with:
            - Application status 133 fraud
            - Account Status = 440,441
            """
            is_fraud_nik = False
            if nik_applications.filter(applicationhistory__status_new=fraud_status).exists():
                is_fraud_nik = True
            elif nik_applications.filter(account__status_id__in=fraud_account_status).exists():
                is_fraud_nik = True

            if is_fraud_nik:
                if (
                    application.product_line_code
                    == ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
                ):
                    reject_reason = {
                        "name": MFStandardRejectReason.FRAUD_NIK.get('name'),
                        "label": MFStandardRejectReason.FRAUD_NIK.get('label'),
                    }
                else:
                    reject_reason = {"name": "fraud_nik", "label": "Fraud NIK"}
                update_application_reject_reason(application.id, reject_reason)

                return

        pii_phone_filter_dict = generate_pii_filter_query_partnership(
            Application, {'mobile_phone_1': mobile_phone_1}
        )
        phone_applications = Application.objects.filter(**pii_phone_filter_dict).exclude(
            id=application.id
        )

        if phone_applications:
            """
            Application checking based phone with:
            - Application status 133 fraud
            - Account Status = 440,441
            """
            is_fraud_phone = False
            if phone_applications.filter(applicationhistory__status_new=fraud_status).exists():
                is_fraud_phone = True
            elif phone_applications.filter(account__status_id__in=fraud_account_status).exists():
                is_fraud_phone = True
            if is_fraud_phone:
                if (
                    application.product_line_code
                    == ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
                ):
                    reject_reason = {
                        "name": MFStandardRejectReason.FRAUD_PHONE.get('name'),
                        "label": MFStandardRejectReason.FRAUD_PHONE.get('label'),
                    }
                else:
                    reject_reason = {"name": "fraud_phone_number", "label": "Fraud Phone Number"}
                update_application_reject_reason(application.id, reject_reason)

        return

    def check_customer_delinquent(self) -> None:
        application = self.application
        partnership_customer_data = application.customer.partnershipcustomerdata_set.last()

        detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
            PiiSource.PARTNERSHIP_CUSTOMER_DATA,
            partnership_customer_data,
            application.customer.customer_xid,
            ['nik', 'phone_number'],
        )
        mobile_phone_1 = detokenize_partnership_customer_data.phone_number
        nik = detokenize_partnership_customer_data.nik

        pii_nik_filter_dict = generate_pii_filter_query_partnership(Application, {'ktp': nik})
        pii_phone_filter_dict = generate_pii_filter_query_partnership(
            Application, {'mobile_phone_1': mobile_phone_1}
        )

        delinquent_account_status = {
            AccountConstant.STATUS_CODE.active_in_grace,
            AccountConstant.STATUS_CODE.suspended,
        }
        is_delinquent = False
        if (
            Application.objects.filter(
                account__status_id__in=delinquent_account_status, **pii_nik_filter_dict
            )
            .exclude(id=application.id)
            .exists()
        ):
            is_delinquent = True
            if (
                application.product_line_code
                == ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
            ):
                reject_reason = {
                    "name": MFStandardRejectReason.DELINQUENT_NIK.get('name'),
                    "label": MFStandardRejectReason.DELINQUENT_NIK.get('label'),
                }
            else:
                reject_reason = {"name": "delinquent_nik", "label": "Delinquent NIK"}
        elif (
            Application.objects.filter(
                account__status_id__in=delinquent_account_status, **pii_phone_filter_dict
            )
            .exclude(id=application.id)
            .exists()
        ):
            is_delinquent = True
            if (
                application.product_line_code
                == ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
            ):
                reject_reason = {
                    "name": MFStandardRejectReason.DELINQUENT_PHONE.get('name'),
                    "label": MFStandardRejectReason.DELINQUENT_PHONE.get('label'),
                }
            else:
                reject_reason = {"name": "delinquent_phone", "label": "Delinquent Phone"}

        if is_delinquent:
            update_application_reject_reason(application.id, reject_reason)

    def change_application_status(self) -> None:
        self.application.change_status(ApplicationStatusCodes.DOCUMENTS_SUBMITTED)
        self.application.save()
        ApplicationHistory.objects.create(
            application=self.application,
            status_old=ApplicationStatusCodes.FORM_PARTIAL,
            status_new=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            change_reason='system_triggered')

        self.application.refresh_from_db()
        self.application.change_status(ApplicationStatusCodes.SCRAPED_DATA_VERIFIED)
        self.application.save()
        ApplicationHistory.objects.create(
            application=self.application,
            status_old=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            status_new=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            change_reason='system_triggered')

    @transaction.atomic
    def generate_mf_partnership_credit_limit(self) -> None:
        """
        MF Web APP Partnership from 105 to 130
        Create Credit Limit generation
        - Create Credit Score
        - Create Account
        - Create AccountLimit
        - Update PartnershipCustomerData Account
        - Update Application Account
        """
        partnership_customer_data = PartnershipCustomerData.objects.filter(
            customer=self.application.customer
        ).last()

        # Only for axiata, a credit_score is harcoded
        # Apart from axiata, a credit score is generated when a risk assessment is made
        detokenize_partner = partnership_detokenize_sync_object_model(
            PiiSource.PARTNER,
            partnership_customer_data.partner,
            customer_xid=None,
            fields_param=['name'],
            pii_type=PiiVaultDataType.KEY_VALUE,
        )
        if detokenize_partner.name in {
            PartnerConstant.AXIATA_PARTNER,
            PartnerNameConstant.AXIATA_WEB,
        }:
            CreditScore.objects.create(application_id=self.application.id, score='A+')

        account_lookup = AccountLookup.objects.filter(workflow=self.application.workflow).last()
        account = Account.objects.create(
            customer=self.application.customer,
            status_id=AccountConstant.STATUS_CODE.inactive,
            account_lookup=account_lookup,
            cycle_day=14,  # Not used but required, for Determine the cycle_day using dana formula
        )

        partner_application_data = partnership_customer_data.partnershipapplicationdata_set.last()
        limit = partner_application_data.proposed_limit

        # Create Credit Limit
        AccountLimit.objects.create(account=account, max_limit=limit, set_limit=limit)

        # Update or create customer Limit to newest
        CustomerLimit.objects.update_or_create(
            customer=self.application.customer, defaults={'max_limit': limit}
        )

        # Set partnership_customer_data & application with account
        partnership_customer_data.account = account
        partnership_customer_data.save(update_fields=['account'])
        self.application.update_safely(account=account)

        # generate account_property and history
        store_account_property_mf_partnership(self.application, limit)

        # Update Status to 141
        next_status_code = ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        process_application_status_change(
            self.application.id,
            new_status_code=next_status_code,
            change_reason="credit limit generated",
        )

    def activate_mf_partnership_web_app_account(self) -> None:
        account = self.application.account

        if not account:
            logger.info(
                {
                    'action': 'mf_partnership_web_app_customer_account_not_update_to_active_at_190',
                    'application_id': self.application.id,
                    'message': 'Account Not Found',
                }
            )
            return

        account_limit = AccountLimit.objects.filter(account=account).last()
        if not account_limit:
            logger.info(
                {
                    'action': 'mf_partnership_web_app_update_account_limit',
                    'application_id': self.application.id,
                    'message': 'Account Limit Not Found',
                }
            )
            return

        account_limit.update_safely(available_limit=account_limit.set_limit)

        # Update to active status
        process_change_account_status(
            account,
            AccountConstant.STATUS_CODE.active,
            change_reason="MF Partnerhsip Web App application approved",
        )

    @transaction.atomic
    def process_reapply_mf_webapp_application(self):
        customer = self.application.customer
        customer.can_reapply = True
        customer.can_reapply_date = timezone.localtime(timezone.now())
        customer.save()

        return

    def dukcapil_fr_mf(self):
        """
        Check dukcapil face recognition result for Merchant Financing
        """
        fn_name = "dukcapil_fr_mf"
        if not self.application.partner:
            raise ValueError(
                'Invalid application id: {} not have a partner id'.format(self.application.id)
            )

        partner_name = '_'.join(self.application.partner.name.split()).lower()

        # Using Partnership Config
        is_mfsp_partner = False
        if self.application.product_line_code == ProductLineCodes.AXIATA_WEB:
            setting = PartnershipFeatureSetting.objects.filter(
                feature_name=PartnershipFeatureNameConst.DUKCAPIL_FR_THRESHOLD_AXIATA,
            ).last()
        else:
            setting = PartnershipFeatureSetting.objects.filter(
                feature_name=PartnershipFeatureNameConst.DUKCAPIL_FR_THRESHOLD_MFSP,
            ).last()
            is_mfsp_partner = True

        if (
            setting
            and setting.is_active
            and setting.parameters.get(partner_name)
            and setting.parameters[partner_name].get("is_active")
        ):
            dukcapil_fr_parameters = setting.parameters[partner_name]
        else:
            logger.info(
                {
                    'action': fn_name,
                    "message": "dukcapil fr mf configuration not found",
                    "application_id": self.application.id,
                }
            )
            # No data found, go to next process
            note = "User bypassed to 190 due no feature setting configuration"

            ApplicationNote.objects.create(application_id=self.application.id, note_text=note)

            next_status_code = ApplicationStatusCodes.LOC_APPROVED
            process_application_status_change(
                self.application.id,
                new_status_code=next_status_code,
                change_reason="Success Dukcapil FR validation",
            )
            return

        if dukcapil_fr_parameters.get('is_async'):
            dukcapil_fr_mf_trigger_task.apply_async(
                kwargs={
                    'application': self.application,
                    'setting': dukcapil_fr_parameters,
                    'is_mfsp_partner': is_mfsp_partner,
                }
            )
        else:
            dukcapil_fr_mf_trigger_task.apply(
                kwargs={
                    'application': self.application,
                    'setting': dukcapil_fr_parameters,
                    'is_mfsp_partner': is_mfsp_partner,
                }
            )

        logger.info(
            {
                'action': fn_name,
                'message': "dukcapil_fr_mf process success",
                'application_id': self.application.id,
            }
        )

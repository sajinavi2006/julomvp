from bulk_update.helper import bulk_update
from django.db.models import Q
from django.utils import timezone

from juloserver.julo.models import Partner, ProductLookup
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.models import Loan
from juloserver.merchant_financing.constants import MFFeatureSetting
from juloserver.partnership.constants import LoanDurationType
from juloserver.partnership.models import (
    PartnerLoanRequest,
    PartnershipFeatureSetting,
)
from juloserver.portal.object.bulk_upload.constants import MerchantFinancingCSVUploadPartner


# referencing this mf_standard_loan_creation
def retroloaded_partner_loan_request_old_mf(partner_name):
    partner = Partner.objects.filter(name=partner_name).first()
    if not partner:
        print('partner doesnt exists')
        return
    if not partner.product_line_id:
        print('partner doesnt have product line code')
        return

    loans = (
        Loan.objects.select_related('product')
        .prefetch_related('partnerloanrequest_set')
        .filter(
            product__product_line__product_line_code=partner.product_line_id,
        )
    )

    update_loan_ids = []
    create_partner_loan_request = []
    update_partner_loan_request = []
    for loan in loans.iterator():
        provision_amount = loan.product.origination_fee_pct * loan.loan_amount
        is_manual_skrtp = False
        partnership_feature_setting = PartnershipFeatureSetting.objects.filter(
            feature_name=MFFeatureSetting.MF_MANUAL_SIGNATURE, is_active=True
        ).first()

        if partnership_feature_setting:
            for param in partnership_feature_setting.parameters:
                if param.get('is_manual') and param.get('partner_id') == partner.id:
                    is_manual_skrtp = True
                    break

        if partner.name == MerchantFinancingCSVUploadPartner.GAJIGESA:
            loan_type = 'IF'
        else:
            loan_type = 'SCF'

        if not loan.partnerloanrequest_set.exists():
            new_partner_loan_request = PartnerLoanRequest(
                loan=loan,
                partner=partner,
                loan_amount=loan.loan_amount,
                loan_disbursement_amount=loan.loan_disbursement_amount,
                loan_original_amount=loan.loan_amount,
                loan_duration_type=LoanDurationType.DAYS,
                provision_amount=round(provision_amount),
                is_manual_skrtp=is_manual_skrtp,
                funder='JULO',
                loan_type=loan_type,
                installment_number=1,
                financing_amount=loan.loan_amount,
                financing_tenure=loan.loan_duration,
                interest_rate=loan.product.interest_rate,
                provision_rate=loan.product.origination_fee_pct,
                loan_request_date=loan.cdate.date(),
            )
            create_partner_loan_request.append(new_partner_loan_request)
        else:
            partner_loan_request = loan.partnerloanrequest_set.all()[0]
            partner_loan_request.udate = timezone.localtime(timezone.now())
            partner_loan_request.provision_amount = round(provision_amount)
            partner_loan_request.is_manual_skrtp = is_manual_skrtp
            partner_loan_request.funder = 'JULO'
            partner_loan_request.loan_type = loan_type
            partner_loan_request.installment_number = 1
            partner_loan_request.financing_amount = loan.loan_amount
            partner_loan_request.financing_tenure = loan.loan_duration
            partner_loan_request.interest_rate = loan.product.interest_rate
            partner_loan_request.provision_rate = loan.product.origination_fee_pct
            partner_loan_request.loan_request_date = loan.cdate.date()
            update_partner_loan_request.append(partner_loan_request)

        update_loan_ids.append(loan)
        print("{} success di update".format(loan.id))

    bulk_update(
        update_loan_ids,
        update_fields=['account', 'application_id2', 'product', 'customer_id'],
        batch_size=200,
    )
    bulk_update(
        update_partner_loan_request,
        update_fields=[
            'udate',
            'provision_amount',
            'is_manual_skrtp',
            'funder',
            'loan_type',
            'installment_number',
            'financing_amount',
            'financing_tenure',
            'interest_rate',
            'provision_rate',
            'loan_request_date',
        ],
        batch_size=200,
    )
    PartnerLoanRequest.objects.bulk_create(create_partner_loan_request, batch_size=200)

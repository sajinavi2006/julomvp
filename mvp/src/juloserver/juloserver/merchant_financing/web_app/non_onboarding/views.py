import io
import logging
import csv
from datetime import datetime

from django.utils import timezone
from django.http import HttpResponse

import requests
from rest_framework import status

from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.generics import ListAPIView

from juloserver.account.models import AccountLimit
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Application,
    Loan,
    FeatureSetting,
    PaymentMethod,
    ProductLookup,
    SphpTemplate,
    UploadAsyncState,
    Agent,
)
from juloserver.julo.partners import PartnerConstant

from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.merchant_financing.constants import MF_STANDARD_PRODUCT_UPLOAD_MAPPING_FIELDS
from juloserver.merchant_financing.web_app.non_onboarding.forms import MFStandardUploadFileForm
from juloserver.merchant_financing.decorators import require_mf_api_v2, require_partner_agent_role

from juloserver.merchant_financing.web_app.non_onboarding.serializers import (
    CreateLoanSerializer,
    UpdateLoanSerializer,
    UploadDocumentMfSerializer,
)
from juloserver.merchant_financing.web_app.non_onboarding.services import (
    create_loan_mf_webapp,
    get_loan_detail,
    get_merchant_loan_detail,
    update_merchant_financing_webapp_loan,
    upload_partnership_document_mf,
)
from juloserver.merchant_financing.web_app.non_onboarding.tasks import (
    merchant_financing_max_platform_check,
    mf_standard_loan_submission,
)
from juloserver.merchant_financing.web_app.utils import (
    accepted_response_web_app,
    error_response_web_app,
    no_content_response_web_app,
    success_response_web_app,
    created_response_web_app,
    error_response_validation,
    get_partnership_imgs_and_docs,
    get_application_dictionaries,
)

from juloserver.merchant_financing.web_app.views import MFStandardAPIView, MFWebAppAPIView
from juloserver.merchant_financing.web_app.constants import (
    MFDashboardLoanStatus,
    WebAppErrorMessage,
    MFWebAppLoanStatus,
    MFLoanTypes,
    MFStdDocumentTypes,
    MFStdImageTypes,
)
from juloserver.partnership.constants import (
    CSV_DELIMITER_SIZE,
    ErrorMessageConst,
    PAYMENT_METHOD_NAME_BCA,
    PartnershipImageStatus,
)
from juloserver.partnership.models import (
    PartnerLoanRequest,
    PartnershipApplicationData,
    PartnershipCustomerData,
    PartnershipDistributor,
    PartnershipDocument,
    PartnershipImage,
    PartnershipUser,
)

from juloserver.merchant_financing.web_portal.paginations import WebPortalPagination
from juloserver.merchant_financing.utils import (
    compute_mf_amount,
    get_rounded_monthly_interest_rate,
    validate_max_file_size,
)
from juloserver.julo.constants import FeatureNameConst, UploadAsyncStateStatus, UploadAsyncStateType
from juloserver.followthemoney.tasks import generate_julo_one_loan_agreement
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.merchant_financing.web_app.crm.tasks import send_email_skrtp
from juloserver.partnership.services.services import is_partnership_lender_balance_sufficient
from juloserver.partnership.services.web_services import get_merchant_skrtp_agreement
from juloserver.merchant_financing.tasks import (
    mf_send_sms_skrtp,
    merchant_financing_generate_lender_agreement_document_task,
)
from juloserver.partnership.utils import (
    partnership_detokenize_sync_object_model,
    partnership_digisign_registration_status,
)

from juloserver.partnership.services.digisign import partnership_get_registration_status
from juloserver.partnership.tasks import (
    mf_partner_process_sign_document,
    partnership_register_digisign_task,
)
from juloserver.pii_vault.constants import PiiSource

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class WebAppNonOnboardingCreateLoan(MFWebAppAPIView):
    def post(self, request, *args, **kwargs) -> Response:
        try:
            form_create_loan = CreateLoanSerializer(request.POST, request.FILES)

            if not form_create_loan.is_valid():
                return error_response_web_app(
                    message='validation error', errors=form_create_loan.errors
                )

            user = request.user_obj
            data = {
                'request': form_create_loan.cleaned_data,
                'user': user,
            }

            error, loan_xid = create_loan_mf_webapp(data)
            if error:
                return error_response_web_app(message=error)

            return created_response_web_app(data={"loan_xid": loan_xid})

        except Exception as e:
            sentry_client.captureException()
            logger.error({"action": "WebAppNonOnboardingCreateLoan", "error": str(e)})
            return error_response_web_app(message=ErrorMessageConst.GENERAL_ERROR)


class WebAppNonOnboardingLoan(MFWebAppAPIView):
    serializer_loan = UpdateLoanSerializer

    # Loan Update
    def put(self, request, *args, **kwargs) -> Response:
        try:
            serializer = self.serializer_loan(data=request.data)

            user = request.user_obj
            user_id = user.id
            partnership_user = user.partnershipuser_set.first()
            partner_id = partnership_user.partner.id

            if not serializer.is_valid():
                return error_response_web_app(message='validation error', errors=serializer.errors)

            loan_update_kwargs = {
                'loan_xid': self.kwargs['loan_xid'],
                'distributor_code': serializer.validated_data['distributor_code'],
                'funder': serializer.validated_data['funder'],
                'interest_rate': serializer.validated_data['interest_rate'],
                'provision_rate': serializer.validated_data['provision_rate'],
                'user_id': user_id,
                'partner_id': partner_id,
            }

            is_success, message = update_merchant_financing_webapp_loan(**loan_update_kwargs)
            if not is_success:
                return error_response_web_app(message=message)

            return success_response_web_app(data={}, meta={})

        except Exception as e:
            sentry_client.captureException()
            logger.error({"action": "WebAppNonOnboardingUpdateLoan", "error": str(e)})
            return error_response_web_app(message=ErrorMessageConst.GENERAL_ERROR)

    # Get Loan Detail Partner/Agent
    def get(self, request, *args, **kwargs) -> Response:
        try:
            loan_xid = self.kwargs.get('loan_xid')
            user = request.user_obj
            partnership_user = user.partnershipuser_set.first()
            partner_id = partnership_user.partner.id
            is_success, message, loan_detail = get_loan_detail(loan_xid, partner_id)
            if not is_success:
                return error_response_web_app(status=status.HTTP_404_NOT_FOUND, message=message)
            return success_response_web_app(data=loan_detail)
        except Exception as e:
            sentry_client.captureException()
            logger.error({"action": "WebAppNonOnboardingGetLoanDetail", "error": str(e)})
            return error_response_web_app(message=ErrorMessageConst.GENERAL_ERROR)


class WebAppNonOnboardingLoanListView(MFWebAppAPIView, ListAPIView):
    pagination_class = WebPortalPagination

    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        loan_status = request.query_params.get('loan_status')

        loans = Loan.objects.select_related('customer', 'loan_status').filter(
            customer__user=user.id
        )

        if loan_status and loan_status.lower() == MFWebAppLoanStatus.IN_PROGRESS:
            loans = loans.filter(
                loan_status__status_code__in=LoanStatusCodes.mf_loan_status_in_progress()
            )
        elif loan_status and loan_status.lower() == MFWebAppLoanStatus.ACTIVE:
            loans = loans.filter(
                loan_status__status_code__in=LoanStatusCodes.mf_loan_status_active()
            )
        elif loan_status and loan_status.lower() == MFWebAppLoanStatus.DONE:
            loans = loans.filter(loan_status__status_code__in=LoanStatusCodes.mf_loan_status_done())

        loan_data = loans.order_by('-udate')
        queryset = self.filter_queryset(loan_data)

        try:
            data = []
            loan_pages = self.paginate_queryset(queryset)

            for loan in loan_pages:
                data.append(
                    {
                        'loan_xid': loan.loan_xid,
                        'loan_amount': loan.loan_amount,
                        'cdate': loan.cdate,
                        'loan_status': loan.loan_status.status_code,
                    }
                )

            return self.get_paginated_response(data)
        except Exception as e:
            if str(e) == WebAppErrorMessage.PAGE_NOT_FOUND:
                return Response(status=status.HTTP_404_NOT_FOUND)

            return error_response_web_app(message=str(e))


class WebAppNonOnboardingSignSkrtpView(MFWebAppAPIView):
    def post(self, request, *args, **kwargs) -> Response:
        loan_xid = self.kwargs['loan_xid']
        if not loan_xid:
            return error_response_web_app(message="loan_xid required")

        payload = request.data
        if 'is_agree_agreement' not in payload.keys():
            return error_response_web_app(message="is_agree_agreement required")

        is_agree_agreement = payload.get('is_agree_agreement')
        if not isinstance(is_agree_agreement, bool):
            return error_response_web_app(message="is_agree_agreement must be boolean")
        if not is_agree_agreement:
            return error_response_web_app(message="is_agree_agreement must be true")

        loan = Loan.objects.get_or_none(loan_xid=loan_xid)

        if not loan:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="Loan not found"
            )

        if loan.loan_status_id != LoanStatusCodes.INACTIVE:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="Invalid loan status"
            )

        now = datetime.now()
        loan.sphp_accepted_ts = timezone.localtime(now)
        loan.save()

        update_loan_status_and_loan_history(
            loan_id=loan.id,
            new_status_code=LoanStatusCodes.LENDER_APPROVAL,
            change_by_id=loan.customer.user.id,
            change_reason="SKRTP signed",
        )

        lender_auto_approve = FeatureSetting.objects.get_or_none(
            is_active=True, feature_name=FeatureNameConst.MF_LENDER_AUTO_APPROVE
        )

        if lender_auto_approve and lender_auto_approve.parameters.get('is_enable'):
            if is_partnership_lender_balance_sufficient(loan, True):
                update_loan_status_and_loan_history(
                    loan_id=loan.id,
                    new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                    change_by_id=loan.customer.user.id,
                    change_reason="Lender auto approve",
                )

                generate_julo_one_loan_agreement.delay(loan.id)
                merchant_financing_generate_lender_agreement_document_task.delay(loan.id)

        # register digisign
        is_delay_sign_document = False
        application = loan.account.get_active_application()
        if application.product_line.product_line_code == ProductLineCodes.AXIATA_WEB:
            registration_status = partnership_get_registration_status(application)
            is_registered = registration_status is not None
            if not is_registered:
                partnership_register_digisign_task.delay(application.id)
                is_delay_sign_document = True

        # trigger digisign service
        if is_delay_sign_document:
            """
            This condition checks if the customer is not yet registered
            for DigiSign and gives them time to register and sign the document,
            ensuring registration is completed before signing.
            """
            mf_partner_process_sign_document.apply_async((loan.id,), countdown=360)
        else:
            mf_partner_process_sign_document.delay(loan.id)

        return success_response_web_app()


class WebAppNonOnboardingDistributorListView(MFWebAppAPIView):
    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        if not partnership_user:
            return error_response_web_app(message=WebAppErrorMessage.INVALID_ACCESS_PARTNER)

        partner = partnership_user.partner

        distributor_name = request.GET.get('name', '')
        distributors = PartnershipDistributor.objects.filter(partner=partner)
        if distributor_name:
            distributors = PartnershipDistributor.objects.filter(
                partner=partner,
                distributor_name__icontains=distributor_name,
            ).exclude(is_deleted=True)
        else:
            distributors = PartnershipDistributor.objects.filter(
                partner=partner,
            ).exclude(is_deleted=True)

        data = []
        for distributor in distributors:
            data.append({"code": distributor.distributor_id, "name": distributor.distributor_name})

        return success_response_web_app(data)


class WebAppNonOnboardingLoanDetail(MFWebAppAPIView):
    # Get Loan Detail Merchant
    def get(self, request, *args, **kwargs) -> Response:
        try:
            loan_xid = self.kwargs.get('loan_xid')
            user_id = request.user_obj.id
            is_success, message, loan_detail = get_merchant_loan_detail(loan_xid, user_id)
            if not is_success:
                return error_response_web_app(status=status.HTTP_404_NOT_FOUND, message=message)

            return success_response_web_app(data=loan_detail)

        except Exception as e:
            sentry_client.captureException()
            logger.error({"action": "WebAppNonOnboardingGetMerchantLoanDetail", "error": str(e)})
            return error_response_web_app(message=ErrorMessageConst.GENERAL_ERROR)


class WebAppNonOnboardingShowSkrtpView(MFWebAppAPIView):
    def get(self, request, *args, **kwargs) -> Response:
        loan_xid = self.kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="Pinjaman tidak ditemukan"
            )

        if loan.loan_status_id == LoanStatusCodes.LENDER_APPROVAL:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="SKRTP sudah ditandatangani"
            )

        if loan.loan_status_id != LoanStatusCodes.INACTIVE:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="Status pinjaman tidak valid"
            )

        application = loan.get_application
        if not application:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="Application tidak ditemukan"
            )

        partner_loan_request = PartnerLoanRequest.objects.filter(loan=loan).last()
        if not partner_loan_request:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="PartnerLoanRequest tidak ditemukan"
            )

        # for AXIATA sphp
        product_name = PartnerConstant.AXIATA_PARTNER_SCF
        if partner_loan_request.loan_type.upper() == 'IF':
            product_name = PartnerConstant.AXIATA_PARTNER_IF

        distributor = PartnershipDistributor.objects.filter(
            id=partner_loan_request.partnership_distributor.id
        ).last()
        if not distributor:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="PartnershipDistributor tidak ditemukan"
            )

        payment_method = PaymentMethod.objects.filter(
            customer_id=application.customer,
            is_shown=True,
            payment_method_name=PAYMENT_METHOD_NAME_BCA,
        ).last()
        if not payment_method:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="PaymentMethod tidak ditemukan"
            )

        partnership_application_data = PartnershipApplicationData.objects.filter(
            application_id=loan.application_id2
        ).last()
        if not partnership_application_data:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND,
                message="PartnershipApplicationData tidak ditemukan",
            )

        html_template = SphpTemplate.objects.filter(product_name=product_name).last()
        if not html_template:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="SphpTemplate tidak ditemukan"
            )

        account_limit = AccountLimit.objects.filter(account=application.account).last()
        if not account_limit:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="AccountLimit tidak ditemukan"
            )

        content_skrtp = get_merchant_skrtp_agreement(
            loan,
            application,
            partner_loan_request,
            html_template,
            account_limit,
            partnership_application_data,
            distributor,
            payment_method,
        )

        return success_response_web_app(data=content_skrtp)


class WebAppNonOnboardingDigisignStatus(MFWebAppAPIView):
    def get(self, request, *args, **kwargs) -> Response:
        user = request.user_obj
        if not hasattr(user, 'customer'):
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="Data Customer tidak ditemukan"
            )
        customer = user.customer
        if not customer:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="Data Customer tidak ditemukan"
            )

        loan_xid = self.kwargs['loan_xid']
        loan = (
            Loan.objects.select_related('customer')
            .filter(loan_xid=loan_xid, customer=customer)
            .last()
        )
        if not loan:
            return error_response_web_app(
                status=status.HTTP_404_NOT_FOUND, message="Pinjaman tidak ditemukan"
            )

        is_registered = partnership_digisign_registration_status(loan.customer.id)

        return success_response_web_app(data={'is_registered': is_registered})


class DashboardNonOnboardingLoanListView(MFWebAppAPIView, ListAPIView):
    pagination_class = WebPortalPagination

    def get(self, request: Request, *args, **kwargs) -> Response:
        application_ids = set()
        application_dicts = {}

        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        loan_status = self.kwargs["loan_status"].lower()

        partner_loan_requests = PartnerLoanRequest.objects.select_related(
            "loan", "loan__loan_status"
        ).filter(partner_id=partnership_user.partner)

        for partner_loan_request in partner_loan_requests:
            application_ids.add(partner_loan_request.loan.application_id2)

        pl_filtered_app_ids = Application.objects.filter(
            id__in=application_ids, product_line=ProductLineCodes.AXIATA_WEB
        ).values_list("id", flat=True)

        if loan_status == MFDashboardLoanStatus.REQUEST:
            plr_data = partner_loan_requests.filter(
                loan__loan_status__status_code=LoanStatusCodes.DRAFT,
                loan__application_id2__in=pl_filtered_app_ids,
            ).order_by("cdate")
        elif loan_status == MFDashboardLoanStatus.APPROVED:
            plr_data = partner_loan_requests.filter(
                loan__loan_status__status_code__gt=LoanStatusCodes.DRAFT,
                loan__application_id2__in=pl_filtered_app_ids,
            ).order_by("-udate")
        else:
            plr_data = partner_loan_requests.filter(
                loan__application_id2__in=pl_filtered_app_ids
            ).order_by("-id")

        queryset = self.filter_queryset(plr_data)

        try:
            data = []
            plr_pages = self.paginate_queryset(queryset)

            partnership_customer_data = PartnershipCustomerData.objects.select_related(
                "customer"
            ).filter(application_id__in=pl_filtered_app_ids)
            partnership_application_data = PartnershipApplicationData.objects.filter(
                application_id__in=pl_filtered_app_ids
            )

            for pcd in partnership_customer_data:
                application_dicts[pcd.application_id] = {
                    "partnership_customer_data": pcd,
                }

            for pad in partnership_application_data:
                application_dicts[pad.application_id]["partnership_application_data"] = pad

            for plr in plr_pages:
                nik, borrower_name, company_name = "", "", ""
                application_dict = application_dicts.get(plr.loan.application_id2)

                if application_dict and application_dict.get("partnership_customer_data"):
                    pcd = application_dict.get("partnership_customer_data")

                    detokenized_pcd = partnership_detokenize_sync_object_model(
                        pii_source=PiiSource.PARTNERSHIP_CUSTOMER_DATA,
                        object_model=pcd,
                        customer_xid=pcd.customer.customer_xid,
                        fields_param=["nik"],
                    )

                    detokenized_customer = partnership_detokenize_sync_object_model(
                        pii_source=PiiSource.CUSTOMER,
                        object_model=pcd.customer,
                        customer_xid=pcd.customer.customer_xid,
                        fields_param=["fullname"],
                    )

                    nik = detokenized_pcd.nik
                    borrower_name = detokenized_customer.fullname

                if application_dict and application_dict.get("partnership_application_data"):
                    company_name = application_dict.get("partnership_application_data").company_name

                data.append(
                    {
                        "loan_xid": plr.loan.loan_xid,
                        "loan_amount": plr.loan.loan_amount,
                        "cdate": plr.loan.cdate,
                        "loan_status": plr.loan.loan_status.status_code,
                        "nik": nik,
                        "borrower_name": borrower_name,
                        "company_name": company_name,
                    }
                )

            return self.get_paginated_response(data)
        except Exception as e:
            if str(e) == WebAppErrorMessage.PAGE_NOT_FOUND:
                return Response(status=status.HTTP_404_NOT_FOUND)

            return error_response_web_app(message=str(e))


class DashboardInterestListView(MFWebAppAPIView, ListAPIView):
    def get(self, request: Request, *args, **kwargs) -> Response:
        loan_xid = self.kwargs['loan_xid'].lower()

        loan = Loan.objects.filter(loan_xid=loan_xid).last()
        application = (
            Application.objects.select_related('product_line')
            .filter(id=loan.application_id2)
            .values('product_line')
            .last()
        )
        product_lookups = (
            ProductLookup.objects.filter(
                product_line=application.get('product_line'), is_active=True
            )
            .distinct('interest_rate')
            .order_by('interest_rate')
        )

        data = []
        for pl in product_lookups:
            label = (
                str(get_rounded_monthly_interest_rate(pl.interest_rate)).rstrip("0").rstrip(".")
                + "%"
            )

            data.append(
                {
                    "label": label,
                    "value": pl.interest_rate,
                }
            )

        try:
            return Response(status=status.HTTP_200_OK, data={"data": data})
        except Exception as e:
            if str(e) == WebAppErrorMessage.PAGE_NOT_FOUND:
                return Response(status=status.HTTP_404_NOT_FOUND)

            return error_response_web_app(message=str(e))


class DashboardProvisionListView(MFWebAppAPIView, ListAPIView):
    def get(self, request: Request, *args, **kwargs) -> Response:
        loan_xid = self.kwargs['loan_xid'].lower()
        interest_rate = request.query_params.get('interest_rate')

        loan = Loan.objects.filter(loan_xid=loan_xid).last()
        application = (
            Application.objects.select_related('product_line')
            .filter(id=loan.application_id2)
            .values('product_line')
            .last()
        )
        product_lookups = (
            ProductLookup.objects.filter(
                product_line=application.get('product_line'),
                is_active=True,
                interest_rate=interest_rate,
            )
            .distinct('origination_fee_pct')
            .order_by('origination_fee_pct')
        )

        data = []
        for pl in product_lookups:
            data.append(pl.origination_fee_pct)

        try:
            return Response(status=status.HTTP_200_OK, data={'data': data})
        except Exception as e:
            if str(e) == WebAppErrorMessage.PAGE_NOT_FOUND:
                return Response(status=status.HTTP_404_NOT_FOUND)

            return error_response_web_app(message=str(e))


class MFStdNonOnboardingLoanDetail(MFStandardAPIView):
    @require_partner_agent_role
    @require_mf_api_v2
    def get(self, request, *args, **kwargs) -> Response:
        try:
            user = request.user_obj
            partnership_user = user.partnershipuser_set.first()
            loan_xid = self.kwargs["loan_xid"]

            if not loan_xid.isnumeric():
                return Response(
                    status=status.HTTP_404_NOT_FOUND,
                    data={"message": WebAppErrorMessage.INVALID_LOAN_XID},
                )

            plr = (
                PartnerLoanRequest.objects.select_related(
                    "partnership_distributor", "loan", "loan__loan_status"
                )
                .filter(loan__loan_xid=loan_xid, partner_id=partnership_user.partner)
                .last()
            )

            if not plr:
                return Response(
                    status=status.HTTP_404_NOT_FOUND,
                    data={"message": WebAppErrorMessage.INVALID_LOAN_XID},
                )

            imgs_docs_dict = get_partnership_imgs_and_docs([plr])
            application_dict = get_application_dictionaries([plr])

            distributor = ""

            if plr.partnership_distributor:
                distributor = (
                    str(plr.partnership_distributor.distributor_id)
                    + " - "
                    + plr.partnership_distributor.distributor_name
                )

            loan_detail = {
                "cdate": plr.loan.cdate,
                "loan_xid": plr.loan.loan_xid,
                "invoice_number": plr.invoice_number,
                "loan_type": getattr(MFLoanTypes, str(plr.loan_type), plr.loan_type),
                "distributor": distributor,
                "nik": application_dict[plr.loan.application_id2]["partnership_customer_data"][
                    "nik"
                ],
                "borrower_name": application_dict[plr.loan.application_id2][
                    "partnership_customer_data"
                ]["borrower_name"],
                "funder": plr.funder,
                "loan_amount": plr.loan.loan_amount,
                "installment_number": plr.installment_number,
                "tenor": plr.loan.loan_duration,
                "interest_rate": plr.interest_rate or 0.00,
                "provision_amount": float(plr.provision_rate or 0.00) * plr.loan.loan_amount,
                "installment_amount": plr.loan.installment_amount,
                "invoice": imgs_docs_dict[plr.loan.id][MFStdDocumentTypes.INVOICE],
                "bilyet": imgs_docs_dict[plr.loan.id][MFStdDocumentTypes.BILYET],
                "skrtp": imgs_docs_dict[plr.loan.id][MFStdDocumentTypes.SKRTP],
                "merchant_photo": imgs_docs_dict[plr.loan.id][MFStdImageTypes.MERCHANT_PHOTO],
                "loan_status": plr.loan.loan_status.status_code,
                "is_manual_skrtp": plr.is_manual_skrtp or False,
            }

            return success_response_web_app(data=loan_detail)

        except Exception as e:
            sentry_client.captureException()
            logger.error({"action": "MFStdNonOnboardingLoanDetail", "error": str(e)})
            return error_response_web_app(message=ErrorMessageConst.GENERAL_ERROR)


class WebAppNonOnboardingLoanCalculationView(MFWebAppAPIView):
    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        if not partnership_user:
            return error_response_web_app(message=WebAppErrorMessage.INVALID_ACCESS_PARTNER)

        loan_xid = self.kwargs['loan_xid']
        if not loan_xid:
            return error_response_web_app(message='loan_xid is required')

        interest_rate = request.GET.get('interest_rate', '')
        if not interest_rate:
            return error_response_web_app(message='interest_rate is required')
        try:
            interest_rate = float(interest_rate)
            if interest_rate < 0:
                return error_response_web_app(message='interest_rate must be positive value')
        except ValueError:
            return error_response_web_app(message='interest_rate must be must be a number')

        loan = Loan.objects.filter(loan_xid=loan_xid).last()
        if not loan:
            return error_response_web_app(message='loan not found')

        partner_loan_request = loan.partnerloanrequest_set.last()
        if not partner_loan_request:
            return error_response_web_app(message='partner_loan_request not found')

        _, installment_each_payment, _, _, _ = compute_mf_amount(
            interest_rate,
            partner_loan_request.financing_tenure,
            partner_loan_request.installment_number,
            loan.loan_amount,
        )

        return success_response_web_app(data={"installment_amount": installment_each_payment})


class WebAppNonOnboardingMaxPlatformCheckView(MFWebAppAPIView):
    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        application = user.customer.application_set.last()
        if not application:
            error_message = 'Application tidak di temukan'
            return error_response_web_app(message=error_message)

        merchant_financing_max_platform_check.delay(application.id)
        return no_content_response_web_app()


class MFStdNonOnboardingDocumentUploadMfView(MFStandardAPIView):
    @require_partner_agent_role
    @require_mf_api_v2
    def post(self, request, *args, **kwargs) -> Response:
        form_upload = UploadDocumentMfSerializer(request.POST, request.FILES)

        if not form_upload.is_valid():
            return error_response_validation(message='validation error', errors=form_upload.errors)

        if not form_upload.cleaned_data.get('file'):
            return error_response_web_app(message='no input file')

        try:
            loan_xid = self.kwargs['loan_xid']
            user = request.user_obj
            user_id = None
            if user:
                user_id = user.id
            data = {
                'request': form_upload.cleaned_data,
                'loan_xid': loan_xid,
                'user_id': user_id,
            }
            error, file_id, file_url = upload_partnership_document_mf(data)
            if error:
                return error_response_web_app(message=error)

            resp_data = {
                "file_id": file_id,
                "file_url": file_url,
            }
            return success_response_web_app(data=resp_data)

        except Exception as e:
            sentry_client.captureException()
            logger.error({"action": "WebAppNonOnboardingDocumentUploadMfView", "error": str(e)})
            return error_response_web_app(message=ErrorMessageConst.GENERAL_ERROR)


class MFStdNonOnboardingGetFileMfView(MFStandardAPIView):
    @require_partner_agent_role
    @require_mf_api_v2
    def get(self, request, *args, **kwargs) -> Response:
        loan_xid = self.kwargs['loan_xid']
        file_type = self.kwargs['file_type']
        file_id = self.kwargs['file_id']
        file_url = ""

        loan = Loan.objects.filter(loan_xid=loan_xid).last()
        if not loan:
            return error_response_web_app(message='loan not found')

        if file_type == "image":
            file = PartnershipImage.objects.filter(pk=file_id, loan_image_source=loan.id).last()
            if not file:
                return error_response_web_app(message='file not found')
            file_url = file.image_url_external
        else:
            file = PartnershipDocument.objects.filter(pk=file_id, document_source=loan.id).last()
            if not file:
                return error_response_web_app(message='file not found')
            file_url = file.document_url_external

        resp_data = {
            "file_id": file_id,
            "file_url": file_url,
        }
        return success_response_web_app(data=resp_data)


class MFStdNonOnboardingLoanUploadHistory(MFStandardAPIView, ListAPIView):
    pagination_class = WebPortalPagination

    @require_partner_agent_role
    @require_mf_api_v2
    def get(self, request, *args, **kwargs) -> Response:
        user = request.user_obj
        agent = Agent.objects.filter(user=user).last()
        if not agent:
            return error_response_web_app(message='agent not found')

        upload_status = request.GET.get('status', '')
        page = request.GET.get('page', '')
        limit = request.GET.get('limit', '')

        opts_upload_status = {'in_progress', 'completed', 'partial_completed', 'failed'}
        filter_upload_status = []
        if upload_status:
            if upload_status in opts_upload_status:
                if upload_status == 'in_progress':
                    filter_upload_status.append(UploadAsyncStateStatus.WAITING)
                    filter_upload_status.append(UploadAsyncStateStatus.PROCESSING)
                elif upload_status == 'completed':
                    filter_upload_status.append(UploadAsyncStateStatus.COMPLETED)
                elif upload_status == 'partial_completed':
                    filter_upload_status.append(UploadAsyncStateStatus.PARTIAL_COMPLETED)
                elif upload_status == 'failed':
                    filter_upload_status.append(UploadAsyncStateStatus.FAILED)
            else:
                return error_response_web_app(message='invalid status')

        if not page:
            return error_response_web_app(message='page is required')
        try:
            page = int(page)
            if page < 0:
                return error_response_web_app(message='page must be positive value')
        except ValueError:
            return error_response_web_app(message='page must be must be a number')
        page = request.GET.get('page', '')

        if not limit:
            return error_response_web_app(message='limit is required')
        try:
            limit = int(limit)
            if limit < 0:
                return error_response_web_app(message='limit must be positive value')
        except ValueError:
            return error_response_web_app(message='limit must be must be a number')

        upload_history = UploadAsyncState.objects.filter(
            agent=agent,
            task_type=UploadAsyncStateType.MF_STANDARD_CSV_LOAN_UPLOAD,
        )

        if len(filter_upload_status) > 0:
            upload_history = upload_history.filter(task_status__in=filter_upload_status)
        upload_history_data = upload_history.order_by('-udate')
        queryset = self.filter_queryset(upload_history_data)

        try:
            data = []
            upload_history_pages = self.paginate_queryset(queryset)
            for upload_history in upload_history_pages:
                document_url = upload_history.url or ''
                file_name = document_url.split("/")[-1]

                if upload_history.task_status in {
                    UploadAsyncStateStatus.WAITING,
                    UploadAsyncStateStatus.PROCESSING,
                }:
                    task_status = 'in_progress'
                else:
                    task_status = upload_history.task_status

                data.append(
                    {
                        'cdate': upload_history.cdate,
                        'filename': file_name,
                        'status': task_status,
                        'history_id': upload_history.id,
                    }
                )
            return self.get_paginated_response(data)

        except Exception as e:
            if str(e) == WebAppErrorMessage.PAGE_NOT_FOUND:
                return Response(status=status.HTTP_404_NOT_FOUND)
            return error_response_web_app(message=str(e))


class MFStdNonOnboardingGetLoanUploadHistoryFileView(MFStandardAPIView):
    @require_partner_agent_role
    @require_mf_api_v2
    def get(self, request, *args, **kwargs) -> Response:
        history_id = self.kwargs["history_id"]
        upload_async_state = (
            UploadAsyncState.objects.filter(id=history_id).select_related("agent__user").last()
        )
        if not upload_async_state:
            return error_response_web_app(message="history file not found")

        uploader = upload_async_state.agent.user
        uploader_pu_partner_id = (
            PartnershipUser.objects.filter(user=uploader)
            .values_list('partner_id', flat=True)
            .first()
        )
        login_user = request.user_obj
        login_pu_partner_id = (
            PartnershipUser.objects.filter(user=login_user)
            .values_list('partner_id', flat=True)
            .first()
        )
        if not login_pu_partner_id or login_pu_partner_id != uploader_pu_partner_id:
            return error_response_web_app(message="not have access")

        pdf_file_response = requests.get(upload_async_state.download_url)
        response = HttpResponse(pdf_file_response.content, content_type="text/csv")
        return response


class MFStdNonOnboardingLoanList(MFStandardAPIView, ListAPIView):
    pagination_class = WebPortalPagination

    @require_partner_agent_role
    @require_mf_api_v2
    def get(self, request, *args, **kwargs) -> Response:
        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        loan_status = self.kwargs["loan_status"].lower()

        partner_loan_requests = (
            PartnerLoanRequest.objects.select_related("loan", "loan__loan_status")
            .filter(partner_id=partnership_user.partner)
            .order_by("-loan__udate")
        )

        partner_loan_requests = self.apply_filter_to_plr(loan_status, partner_loan_requests)
        queryset = self.filter_queryset(partner_loan_requests)

        try:
            data = []
            plr_pages = self.paginate_queryset(queryset)
            imgs_docs_dict = get_partnership_imgs_and_docs(plr_pages)
            application_dicts = get_application_dictionaries(plr_pages)

            for plr_page in plr_pages:
                data.append(
                    {
                        "loan_xid": plr_page.loan.loan_xid,
                        "nik": application_dicts[plr_page.loan.application_id2][
                            "partnership_customer_data"
                        ]["nik"],
                        "borrower_name": application_dicts[plr_page.loan.application_id2][
                            "partnership_customer_data"
                        ]["borrower_name"],
                        "loan_type": getattr(
                            MFLoanTypes, str(plr_page.loan_type), plr_page.loan_type
                        ),
                        "loan_amount": plr_page.loan.loan_amount,
                        "tenor": plr_page.loan.loan_duration,
                        "installment_number": plr_page.installment_number,
                        "invoice_number": plr_page.invoice_number,
                        "invoice": imgs_docs_dict[plr_page.loan.id][MFStdDocumentTypes.INVOICE],
                        "bilyet": imgs_docs_dict[plr_page.loan.id][MFStdDocumentTypes.BILYET],
                        "skrtp": imgs_docs_dict[plr_page.loan.id][MFStdDocumentTypes.SKRTP],
                        "merchant_photo": imgs_docs_dict[plr_page.loan.id][
                            MFStdImageTypes.MERCHANT_PHOTO
                        ],
                        "loan_status": plr_page.loan.loan_status.status_code,
                        "is_manual_skrtp": plr_page.is_manual_skrtp or False,
                    }
                )

            return self.get_paginated_response(data)
        except Exception as e:
            if str(e) == WebAppErrorMessage.PAGE_NOT_FOUND:
                return Response(status=status.HTTP_404_NOT_FOUND, data={"message": str(e)})

            return error_response_web_app(message=str(e))

    @staticmethod
    def apply_filter_to_plr(loan_status, partner_loan_requests):
        if loan_status == MFDashboardLoanStatus.DRAFT:
            return partner_loan_requests.filter(
                loan__loan_status__status_code=LoanStatusCodes.mf_std_draft_loan()
            )
        elif loan_status == MFDashboardLoanStatus.NEED_SKRTP:
            return partner_loan_requests.filter(
                loan__loan_status__status_code=LoanStatusCodes.mf_std_need_skrtp_loan()
            )
        elif loan_status == MFDashboardLoanStatus.VERIFY:
            return partner_loan_requests.filter(
                loan__loan_status__status_code__in=LoanStatusCodes.mf_std_verify_loan()
            )
        elif loan_status == MFDashboardLoanStatus.APPROVED:
            return partner_loan_requests.filter(
                loan__loan_status__status_code__in=LoanStatusCodes.mf_std_approved_loan()
            )
        elif loan_status == MFDashboardLoanStatus.REJECTED:
            return partner_loan_requests.filter(
                loan__loan_status__status_code__in=LoanStatusCodes.mf_std_rejected_loan()
            )
        elif loan_status == MFDashboardLoanStatus.PAID_OFF:
            return partner_loan_requests.filter(
                loan__loan_status__status_code=LoanStatusCodes.mf_std_paid_off_loan()
            )
        else:
            return partner_loan_requests


class MFStdNonOnboardingLoanCreationCsvTemplateView(MFStandardAPIView):
    @require_partner_agent_role
    @require_mf_api_v2
    def get(self, request, *args, **kwargs) -> Response:
        response = HttpResponse(
            content_type="text/csv",
        )
        response['Content-Disposition'] = 'attachment; filename="loan-creation-template.csv"'

        writer = csv.writer(response)
        csv_header = {field[0] for field in MF_STANDARD_PRODUCT_UPLOAD_MAPPING_FIELDS}
        writer.writerow(csv_header)

        return response


class MFStdNonOnboardingDocumentSubmitMfView(MFStandardAPIView):
    @require_partner_agent_role
    @require_mf_api_v2
    def post(self, request, *args, **kwargs) -> Response:
        invoice = request.data.get("invoice")
        bilyet = request.data.get("bilyet")
        manual_skrtp = request.data.get("manual_skrtp")
        merchant_photo = request.data.get("merchant_photo")
        new_loan_status = 0

        loan_xid = self.kwargs['loan_xid']
        loan = Loan.objects.filter(loan_xid=loan_xid).last()
        if not loan:
            return error_response_web_app(message='loan not found')

        if loan.loan_status_id == LoanStatusCodes.DRAFT:
            if not invoice:
                return error_response_web_app(message='invoice required')

            doc_invoice = PartnershipDocument.objects.filter(
                pk=invoice, document_source=loan.id
            ).last()
            if not doc_invoice:
                return error_response_web_app(message='invoice not found')

            doc_invoice.document_status = PartnershipImageStatus.ACTIVE
            doc_invoice.save()
            if bilyet:
                doc_bilyet = PartnershipDocument.objects.filter(
                    pk=bilyet, document_source=loan.id
                ).last()
                if not doc_bilyet:
                    return error_response_web_app(message='bilyet not found')
                doc_bilyet.document_status = PartnershipImageStatus.ACTIVE
                doc_bilyet.save()

            new_loan_status = LoanStatusCodes.INACTIVE

        elif loan.loan_status_id == LoanStatusCodes.INACTIVE:
            if not manual_skrtp:
                return error_response_web_app(message='manual_skrtp required')
            if not merchant_photo:
                return error_response_web_app(message='merchant_photo required')

            doc_manual_skrtp = PartnershipDocument.objects.filter(
                pk=manual_skrtp, document_source=loan.id
            ).last()
            if not doc_manual_skrtp:
                return error_response_web_app(message='manual_skrtp not found')
            doc_manual_skrtp.document_status = PartnershipImageStatus.ACTIVE
            doc_manual_skrtp.save()

            img_merchant_photo = PartnershipImage.objects.filter(
                pk=merchant_photo, loan_image_source=loan.id
            ).last()
            if not img_merchant_photo:
                return error_response_web_app(message='merchant_photo not found')
            img_merchant_photo.image_status = PartnershipImageStatus.ACTIVE
            img_merchant_photo.save()

            new_loan_status = LoanStatusCodes.LENDER_APPROVAL

        else:
            return error_response_web_app(message='invalid loan status')

        if new_loan_status:
            update_loan_status_and_loan_history(
                loan_id=loan.id,
                new_status_code=new_loan_status,
                change_by_id=loan.customer.user.id,
            )
            if new_loan_status == LoanStatusCodes.INACTIVE:
                is_manual_sign = True
                partner_loan_request = loan.partnerloanrequest_set.last()
                if partner_loan_request:
                    is_manual_sign = partner_loan_request.is_manual_skrtp

                if not is_manual_sign:
                    partner_loan_request = PartnerLoanRequest.objects.filter(loan_id=loan.id).last()
                    if not partner_loan_request:
                        return error_response_web_app(message='partner_loan_request not found')

                    interest_rate = 0.00
                    if partner_loan_request.interest_rate:
                        interest_rate = get_rounded_monthly_interest_rate(
                            partner_loan_request.interest_rate
                        )
                    loan_request_date = partner_loan_request.loan_request_date.strftime('%d/%m/%Y')
                    timestamp = datetime.now()
                    send_email_skrtp.delay(
                        loan_id=loan.id,
                        interest_rate=interest_rate,
                        loan_request_date=loan_request_date,
                        timestamp=timestamp,
                    )
                    mf_send_sms_skrtp.delay(loan.id, timestamp=timestamp)

            elif new_loan_status == LoanStatusCodes.LENDER_APPROVAL:
                now = timezone.localtime(datetime.now())
                loan.update_safely(
                    sphp_sent_ts=now,
                    sphp_accepted_ts=now,
                )
                auto_approval_fs = FeatureSetting.objects.get_or_none(
                    is_active=True, feature_name=FeatureNameConst.MF_LENDER_AUTO_APPROVE
                )
                if (
                    auto_approval_fs
                    and auto_approval_fs.parameters.get("is_enable")
                    and is_partnership_lender_balance_sufficient(loan, True)
                ):
                    update_loan_status_and_loan_history(
                        loan_id=loan.id,
                        new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                        change_by_id=loan.customer.user.id,
                        change_reason="Lender auto approve",
                    )
                    merchant_financing_generate_lender_agreement_document_task.delay(loan.id)

            return no_content_response_web_app()


class MFStandardNonOnboardingLoanUploadSubmit(MFStandardAPIView):
    @require_partner_agent_role
    @require_mf_api_v2
    def post(self, request, *args, **kwargs) -> Response:
        try:
            logs = ""
            in_processed_status = {
                UploadAsyncStateStatus.WAITING,
                UploadAsyncStateStatus.PROCESSING,
            }
            user = request.user_obj
            partnership_user = user.partnershipuser_set.first()
            if not partnership_user:
                return error_response_web_app(message=WebAppErrorMessage.INVALID_ACCESS_PARTNER)

            partner = partnership_user.partner

            upload_form = MFStandardUploadFileForm(request.POST, request.FILES)
            if not upload_form.is_valid():
                for key in upload_form.errors:
                    logs += upload_form.errors[key][0]
                return error_response_web_app(message=logs)
            file_ = upload_form.cleaned_data['file']

            # Validate file size
            file_size = 2
            message = validate_max_file_size(file_, file_size)
            if message:
                err_message = message + ", harap upload file CSV di bawah {}MB".format(file_size)
                return error_response_web_app(
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, message=err_message
                )

            extension = file_.name.split('.')[-1]
            if extension != 'csv':
                return error_response_web_app(
                    status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    message='Pastikan kamu meng-upload file dengan format CSV, ya.',
                )

            decoded_file = file_.read().decode('utf-8')
            sniffer = csv.Sniffer()
            delimiter = str(sniffer.sniff(decoded_file[:CSV_DELIMITER_SIZE]).delimiter)

            reader = csv.DictReader(io.StringIO(decoded_file), delimiter=delimiter)

            mapping_fields_set = {field[0] for field in MF_STANDARD_PRODUCT_UPLOAD_MAPPING_FIELDS}
            fieldnames_set = set(reader.fieldnames)

            # Check if headers from MF_STANDARD_PRODUCT_UPLOAD_MAPPING_FIELDS exist in the CSV
            not_exist_headers = [
                field for field in mapping_fields_set if field not in fieldnames_set
            ]

            if len(not_exist_headers) == len(MF_STANDARD_PRODUCT_UPLOAD_MAPPING_FIELDS):
                return error_response_web_app(
                    status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    message='Format CSV tidak sesuai',
                )

            if not_exist_headers:
                message = 'Format CSV tidak sesuai. Header tidak ada: %s' % not_exist_headers
                return error_response_web_app(message=message)

            agent = Agent.objects.filter(user=user).last()
            task_type = UploadAsyncStateType.MF_STANDARD_CSV_LOAN_UPLOAD
            is_upload_in_waiting = UploadAsyncState.objects.filter(
                task_type=task_type,
                task_status__in=in_processed_status,
                agent=agent,
                service='oss',
            ).exists()

            if is_upload_in_waiting:
                message = (
                    'Proses lain sedang menunggu atau sedang berjalan, '
                    'harap tunggu dan coba lagi nanti'
                )
                return error_response_web_app(message=message)

            upload_async_state = UploadAsyncState(
                task_type=task_type,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(upload_async_state.full_upload_name(upload.name), upload)
            upload_async_state_id = upload_async_state.id
            mf_standard_loan_submission.delay(upload_async_state_id, partner.id)

            return accepted_response_web_app(message='File akan segera diproses.')

        except Exception as e:
            sentry_client.captureException()
            logger.error({"action": "MFStandardNonOnboardingLoanUploadSubmit", "error": str(e)})
            return error_response_web_app(message=ErrorMessageConst.GENERAL_ERROR)

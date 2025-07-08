import json
import logging
import re
from collections import defaultdict
from datetime import datetime

from bs4 import BeautifulSoup
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from hashids import Hashids
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from juloserver.account.models import Account
from juloserver.account.views import AccountLoansView, AccountPaymentDpd
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.views.views_api_v1 import PaymentMethodUpdateView
from juloserver.digisign.constants import RegistrationStatus
from juloserver.account_payment.views.views_api_v4 import PaymentMethodRetrieveView
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import BankAccountDestination
from juloserver.digisign.models import DigisignRegistration
from juloserver.partnership.tasks import partnership_register_digisign_task
from juloserver.partnership.services.digisign import partnership_get_registration_status
from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Customer,
    Loan,
    LoanPurpose,
    Partner,
    Payment,
    PaymentMethod,
    PaymentMethodLookup,
    ProductLine,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.loan.services.sphp import accept_julo_sphp
from juloserver.loan.views.views_api_v1 import (
    ActivePlatformRuleCheckView,
    LoanUploadSignatureView,
    ProductListView,
)
from juloserver.loan.views.views_api_v3 import (
    LoanAgreementContentView,
    LoanCalculation,
    LoanJuloOne,
)
from juloserver.loan.views.views_dbr_v1 import LoanDbrCalculation
from juloserver.partnership.api_response import error_response, success_response
from juloserver.partnership.constants import (
    DateFormatString,
    HashidsConstant,
    LoanDurationType,
    PartnershipHttpStatusCode,
    PartnershipRedisPrefixKey,
)
from juloserver.partnership.leadgenb2b.decorators import (
    allowed_leadgen_partner,
    make_request_mutable,
)
from juloserver.partnership.leadgenb2b.non_onboarding.constants import (
    LeadgenJ1RequestKeysMapping,
    LeadgenLoanActionOptions,
    LeadgenLoanCancelChangeReason,
    PaymentMethodName,
    PaymentMethodTypes,
    TransactionStatusLSP,
)
from juloserver.partnership.leadgenb2b.non_onboarding.serializers import (
    LeadgenLoanSignatureUploadSerializer,
)
from juloserver.partnership.leadgenb2b.non_onboarding.services import (
    get_list_loan_by_account_payment,
)
from juloserver.partnership.leadgenb2b.non_onboarding.utils import (
    j1_partnership_message_mapping_dict,
    mapping_message,
    mapping_status_payment,
    rename_request_keys,
)
from juloserver.partnership.leadgenb2b.security import LeadgenAPIAuthentication
from juloserver.partnership.leadgenb2b.views import LeadgenStandardAPIView
from juloserver.partnership.models import PartnerLoanRequest
from juloserver.partnership.utils import date_format_to_localtime, reformat_date
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class LeadgenDbrCheck(LoanDbrCalculation, LeadgenStandardAPIView):
    permission_classes = []
    authentication_classes = [LeadgenAPIAuthentication]

    @allowed_leadgen_partner
    def post(self, request, *args, **kwargs):
        request.data['transactionTypeCode'] = TransactionMethodCode.SELF.code
        if not request.data.get('installmentAmount') or not request.data.get('duration'):
            return error_response(
                message='duration atau installmentAmount tidak boleh 0 atau kosong'
            )

        rename_request_keys(request.data, LeadgenJ1RequestKeysMapping.DBR_CHECK)

        response = super().post(request)
        if isinstance(response, JsonResponse):
            res_content = json.loads(response.content.decode("utf-8"))
        else:
            res_content = response.data

        if res_content["success"]:
            popup_active = res_content['data']['popup_banner']['is_active']
            if not popup_active:
                status_code = status.HTTP_204_NO_CONTENT
                meta = {}
            else:
                status_code = status.HTTP_403_FORBIDDEN
                meta = {
                    "link": res_content['data']['popup_banner']['additional_information']['link']
                }

            return success_response(status=status_code, meta=meta)

        else:
            message = res_content['error']
            mapped_message = mapping_message(message, j1_partnership_message_mapping_dict)
            return error_response(data=res_content['data'], message=mapped_message)


class LoanPurposes(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def get(self, request: Request, *args, **kwargs) -> Response:
        product_line = ProductLine.objects.get_or_none(pk=ProductLineCodes.J1)

        loan_purposes = (
            LoanPurpose.objects.filter(product_lines=product_line)
            .values_list('purpose', flat=True)
            .order_by('id')
        )

        return success_response(data=list(loan_purposes))


class LeadgenLoanUploadSignature(LoanUploadSignatureView, LeadgenStandardAPIView):
    permission_classes = []
    authentication_classes = [LeadgenAPIAuthentication]

    @allowed_leadgen_partner
    @make_request_mutable
    def create(self, request, *args, **kwargs):
        loan_xid = self.kwargs['loan_xid']
        self.loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not self.loan:
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                message="Loan_xid {} tidak ditemukan".format(loan_xid),
            )
        if self.loan.status != LoanStatusCodes.INACTIVE:
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                message="Loan status harus {}".format(LoanStatusCodes.INACTIVE),
            )

        serializer = LeadgenLoanSignatureUploadSerializer(data=request.data)
        errors_validation = serializer.validate()
        if errors_validation:
            return error_response(message=serializer.errors)

        response = super().create(request, *args, **kwargs)
        data = response.data
        if data.get('errors'):
            message = data.get('errors')
            translated_message = mapping_message(message, j1_partnership_message_mapping_dict)
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                message=translated_message,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)

    def perform_create(self, serializer):
        from juloserver.digisign.services.digisign_document_services import (
            is_eligible_for_sign_document,
        )
        from juloserver.digisign.tasks import initial_record_digisign_document, sign_document

        try:
            super().perform_create(serializer)
        except Exception as e:
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                errors={"errorMsg": str(e)},
            )
        if is_eligible_for_sign_document(self.loan):
            try:
                digisign_document = initial_record_digisign_document(self.loan.id)
                sign_document.delay(digisign_document.id)
            except Exception as e:
                return error_response(
                    status=status.HTTP_400_BAD_REQUEST,
                    errors={"errorMsg": str(e)},
                )
        else:
            accept_julo_sphp(self.loan, "JULO")


class LeadgenLoanCalculation(LoanCalculation, LeadgenStandardAPIView):
    permission_classes = []
    authentication_classes = [LeadgenAPIAuthentication]

    @allowed_leadgen_partner
    def post(self, request, *args, **kwargs):
        try:
            user = request.user_obj
            customer = Customer.objects.get_or_none(user=user)
            account = Account.objects.get_or_none(customer=customer)
            if not account:
                return error_response(message='Account tidak ditemukan')

            request.data['accountId'] = account.id
            request.data['selfBankAccount'] = True
            request.data['isPaymentPoint'] = False
            request.data['transactionTypeCode'] = TransactionMethodCode.SELF.code
            request.data['isDbr'] = True
            request.data['isShowSavingAmount'] = True
            request.data['isTax'] = True
            rename_request_keys(request.data, LeadgenJ1RequestKeysMapping.LOAN_CALCULATION)

            response = super().post(request)
            if isinstance(response, JsonResponse):
                res_content = json.loads(response.content.decode("utf-8"))
            else:
                res_content = response.data

            if res_content["success"]:
                res_content_data = res_content.get('data')
                mapped_data = dict()
                if res_content_data:
                    loan_choices = res_content_data.get('loan_choice', [])
                    mapped_data = [
                        {
                            "loanDuration": item["duration"],
                            "loanAmountRequest": item["loan_amount"],
                            "disbursementAmount": item["disbursement_amount"],
                            "installmentAmount": item["monthly_installment"],
                            "firstInstallmentAmount": item["first_monthly_installment"],
                            "adminFee": item["provision_amount"],
                            "taxAmount": item["tax"],
                            "availableLimit": item["available_limit"],
                            "limitAfterUsage": item["available_limit_after_transaction"],
                            "cashback": item["cashback"],
                            "juloInterest": round(
                                item['saving_information']['monthly_interest_rate'], 5
                            ),
                            "otherInterest": item['saving_information'][
                                'other_platform_monthly_interest_rate'
                            ],
                            "juloInstallmentAmount": item['saving_information'][
                                'regular_monthly_installment'
                            ],
                            "otherInstallmentAmount": item['saving_information'][
                                'other_platform_regular_monthly_installment'
                            ],
                            "saveAmount": item['saving_information'][
                                'saving_amount_per_transaction'
                            ],
                        }
                        for item in loan_choices
                    ]

                return success_response(data=mapped_data)
            else:
                message = res_content.get('errors')
                mapped_message = mapping_message(message, j1_partnership_message_mapping_dict)
                return error_response(message=mapped_message)

        except Exception as e:
            return error_response(message=str(e))


class LeadgenLoanCreation(LoanJuloOne, LeadgenStandardAPIView):
    permission_classes = []
    authentication_classes = [LeadgenAPIAuthentication]

    @allowed_leadgen_partner
    def post(self, request, *args, **kwargs):
        try:
            user = request.user_obj
            customer = Customer.objects.get_or_none(user=user)
            account = Account.objects.get_or_none(customer=customer)

            hashids = Hashids(
                min_length=HashidsConstant.MIN_LENGTH, salt=settings.PARTNERSHIP_HASH_ID_SALT
            )

            request.data["accountId"] = account.id
            request.data["gcmRegId"] = hashids.encode(customer.customer_xid)
            request.data["selfBankAccount"] = True
            request.data["transactionTypeCode"] = TransactionMethodCode.SELF.code
            rename_request_keys(request.data, LeadgenJ1RequestKeysMapping.LOAN_CREATION)

            partner = Partner.objects.get_or_none(name=request.data["partner"])

            product_line = ProductLine.objects.get_or_none(pk=ProductLineCodes.J1)
            loan_purposes = LoanPurpose.objects.filter(product_lines=product_line).values_list(
                "purpose", flat=True
            )

            if not partner:
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message="Partner tidak ditemukan",
                )

            if request.data["loan_purpose"] not in list(loan_purposes):
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message="Loan purpose tidak ditemukan",
                )

            response = super().post(request, *args, **kwargs)

            if isinstance(response, JsonResponse):
                res_content = json.loads(response.content.decode("utf-8"))
            else:
                res_content = response.data

            if res_content["success"]:
                loan = Loan.objects.get_or_none(id=res_content["data"]["loan_id"])

                PartnerLoanRequest.objects.create(
                    loan=loan,
                    partner=partner,
                    loan_amount=loan.loan_amount,
                    loan_disbursement_amount=loan.loan_amount,
                    loan_original_amount=loan.loan_disbursement_amount,
                    loan_request_date=loan.cdate,
                    loan_duration_type=LoanDurationType.MONTH,
                    installment_number=loan.loan_duration,
                )

                return success_response(
                    status=status.HTTP_201_CREATED,
                    data={
                        "id": res_content["data"]["loan_id"],
                        "status": res_content["data"]["loan_status"],
                        "amount": res_content["data"]["loan_amount"],
                        "disbursementAmount": res_content["data"]["disbursement_amount"],
                        "tax": res_content["data"]["tax"],
                        "duration": res_content["data"]["loan_duration"],
                        "installmentAmount": res_content["data"]["installment_amount"],
                        "monthlyInterest": res_content["data"]["monthly_interest"],
                        "xid": res_content["data"]["loan_xid"],
                    },
                )
            else:
                err_message_resp = res_content["errors"][0]
                mapped_message = mapping_message(
                    err_message_resp, j1_partnership_message_mapping_dict
                )

                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=mapped_message,
                )
        except Exception as e:
            return error_response(message=str(e))


class LeadgenBankAccountDestination(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        customer = Customer.objects.get_or_none(user=user)

        bad = (
            BankAccountDestination.objects.filter(
                customer=customer,
                bank__is_active=True,
                bank_account_category__category=BankAccountCategoryConst.SELF,
            )
            .exclude(is_deleted=True)
            .select_related("bank", "bank_account_category", "name_bank_validation")
            .last()
        )

        try:
            if bad:
                return success_response(
                    data={
                        "accountDestinationId": bad.id,
                        "accountName": bad.name_bank_validation.name_in_bank,
                        "accountNumber": bad.account_number,
                        "name": bad.bank.bank_name_frontend,
                        "logo": bad.bank.bank_logo,
                        "accountCategory": bad.bank_account_category.display_label,
                    }
                )
            else:
                return success_response(data={}, is_display_data_field=True)
        except Exception as e:
            return error_response(status=status.HTTP_400_BAD_REQUEST, errors=str(e))


class LeadgenProductListView(ProductListView, LeadgenStandardAPIView):
    permission_classes = []
    authentication_classes = [LeadgenAPIAuthentication]

    @allowed_leadgen_partner
    def get(self, request, *args, **kwargs):
        redis_key = "{}-{}".format(
            PartnershipRedisPrefixKey.LEADGEN_PRODUCT_LIST, request.user.customer.id
        )
        try:
            redis_client = get_redis_client()
            json_product_lists = redis_client.get(redis_key)
            product_lists = json.loads(json_product_lists)
            return success_response(status=status.HTTP_200_OK, data=product_lists)
        except Exception:
            pass

        response = super().get(request, *args, **kwargs)
        products = response.data['data']['product']
        product_lists = []
        product_codes = []
        for product in products:
            product_codes.append(product["code"])

        transaction_methods = TransactionMethod.objects.filter(id__in=product_codes)
        transaction_method_dicts = {}
        for transaction_method in transaction_methods:
            transaction_method_dicts[transaction_method.id] = transaction_method

        for product in products:
            # TODO: create a feature setting so that
            # it can locked and unlocked dynamically
            # or include/exclude from TransactionMethod
            # manually based on future request
            if (
                product["code"] != TransactionMethodCode.ALL_PRODUCT
                and product["name"] != "Tarik Dana"
            ):
                is_locked = True
                icon = transaction_method_dicts[product["code"]].foreground_locked_icon_url
            else:
                is_locked = product["is_locked"]
                icon = product["foreground_icon"]

            new_product = {
                "name": "-".join(product["name"].lower().split()),
                "label": product["name"],
                "isLocked": is_locked,
                "icon": icon,
                "backgroundIcon": product["background_icon"],
            }
            product_lists.append(new_product)

        try:
            redis_client = get_redis_client()
            json_product_list = json.dumps(product_lists)
            redis_client.set(redis_key, json_product_list, expire_time=3600)
        except Exception:
            pass

        return success_response(status=status.HTTP_200_OK, data=product_lists)


class LeadgenLoanCancellation(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        loan_xid = self.kwargs["loan_xid"]

        loan = Loan.objects.filter(loan_xid=loan_xid).select_related("customer").last()

        if not loan:
            return error_response(
                status=status.HTTP_404_NOT_FOUND,
                message="Loan tidak ditemukan",
            )

        if user.id != loan.customer.user.id:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message="Loan tidak valid",
            )

        if loan.status != LoanStatusCodes.INACTIVE:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message="Loan status tidak valid",
            )

        update_loan_status_and_loan_history(
            loan_id=loan.id,
            new_status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            change_reason="Leadgen process to 216 - loan_cancellation",
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


class LeadgenLoanAgreementContentView(LoanAgreementContentView, LeadgenStandardAPIView):
    permission_classes = []
    authentication_classes = [LeadgenAPIAuthentication]

    @make_request_mutable
    @allowed_leadgen_partner
    def get(self, request, *args, **kwargs):
        request.query_params["document_type"] = LoanAgreementType.SKRTP

        response = super().get(request, *args, **kwargs)
        res_content = response.data

        if response.status_code == status.HTTP_200_OK and res_content.get("data"):
            agreement_html = res_content.get("data")

            agreement_html = re.sub(
                r"(\s*)<!doctype html>(\s*)(\s*)<html>(\s*)", "", agreement_html
            )
            agreement_html = re.sub(r"(\s*)</html>(\s*)", "", agreement_html)
            agreement_html = re.sub(r"(\s*)<body>(\s*)", "", agreement_html)
            agreement_html = re.sub(r"(\s*)</body>(\s*)", "", agreement_html)
            agreement_html = re.sub(r"padding-top: ([0-9A-za-z]*);(\s*)", "", agreement_html)

            soup = BeautifulSoup(agreement_html, "html.parser")

            link_tag = soup.find("link")
            soup.insert(0, link_tag)

            style_str_list = soup.find("style").get_text().split()

            for tag in soup(["head", "script"]):
                tag.decompose()

            start_idx, end_idx = 0, 0
            cleaned_style_str_list = []
            for idx, i_style_str in enumerate(style_str_list):
                if i_style_str == "body":
                    start_idx = idx
                    for jdx, j_style_str in enumerate(style_str_list):
                        if j_style_str == "}":
                            end_idx = jdx
                            break

            for idx, i in enumerate(style_str_list):
                if idx < start_idx or idx > end_idx:
                    cleaned_style_str_list.append(i)

            cleaned_style_str = " ".join(cleaned_style_str_list)

            new_style = soup.new_tag("style")
            new_style.string = cleaned_style_str

            soup.insert(1, new_style)

            return success_response(status=response.status_code, data=soup.prettify())
        elif response.status_code == status.HTTP_404_NOT_FOUND:
            return error_response(
                status=response.status_code,
                message="Loan tidak ditemukan",
            )
        elif response.status_code == status.HTTP_403_FORBIDDEN:
            error_msg = mapping_message(
                res_content.get("errors"), j1_partnership_message_mapping_dict
            )

            return error_response(
                status=response.status_code,
                message=error_msg,
            )
        else:
            return error_response(
                status=response.status_code,
                message=res_content.get("errors"),
            )


class LeadgenMaxPlatformCheck(ActivePlatformRuleCheckView, LeadgenStandardAPIView):
    permission_classes = []
    authentication_classes = [LeadgenAPIAuthentication]

    @allowed_leadgen_partner
    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        if response.status_code == status.HTTP_400_BAD_REQUEST:
            message = response.data['errors'][0]
            return error_response(status=status.HTTP_500_INTERNAL_SERVER_ERROR, message=message)

        # is_button_enable = True mean eligible
        is_eligible = response.data['data']['is_button_enable']
        if is_eligible:
            status_code = status.HTTP_204_NO_CONTENT
            meta = {}
        else:
            status_code = status.HTTP_403_FORBIDDEN
            meta = {"link": response.data['data']["popup"]["additional_information"]["link"]}

        return success_response(status=status_code, meta=meta)


class LeadgenLoanDetail(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        loan_xid = self.kwargs["loan_xid"]
        customer = Customer.objects.get_or_none(user=user)

        loan = (
            Loan.objects.filter(
                loan_xid=loan_xid, customer=customer, bank_account_destination__bank__is_active=True
            )
            .select_related(
                "product",
                "bank_account_destination",
                "bank_account_destination__bank",
                "bank_account_destination__name_bank_validation",
            )
            .first()
        )
        if not loan:
            return error_response(
                status=status.HTTP_404_NOT_FOUND,
                message="Loan tidak ditemukan",
            )

        payment = Payment.objects.filter(loan=loan).first()
        if not payment:
            return error_response(
                status=status.HTTP_404_NOT_FOUND,
                message="Payment tidak ditemukan",
            )

        bad = loan.bank_account_destination

        bank_detail = {}
        if bad:
            bank_detail = {
                "name": bad.bank.bank_name_frontend,
                "accountName": bad.name_bank_validation.name_in_bank,
                "accountNumber": bad.account_number,
            }
        disbursement_date = None
        if loan.disbursement_date:
            disbursement_date = timezone.localtime(loan.disbursement_date).strftime(
                "%Y-%m-%dT%H:%M:%S:%f"
            )

        is_digisign_registered = False
        digisign_registration = DigisignRegistration.objects.filter(
            customer_id=customer.id
        ).exists()
        if digisign_registration:
            is_digisign_registered = True

        loan_status = ""
        if loan.status <= LoanStatusCodes.CURRENT:
            loan_status = TransactionStatusLSP.IN_PROGRESS
        elif LoanStatusCodes.CURRENT < loan.status < LoanStatusCodes.PAID_OFF:
            loan_status = TransactionStatusLSP.LATE
        elif loan.status == LoanStatusCodes.PAID_OFF:
            loan_status = TransactionStatusLSP.PAID_OFF
        elif loan.status == LoanStatusCodes.SELL_OFF:
            loan_status = TransactionStatusLSP.LATE

        date_format = DateFormatString.DATE_WITH_TIME
        data_resp = {
            "xid": loan_xid,
            "transactionDate": date_format_to_localtime(loan.cdate, date_format),
            "amount": loan.loan_amount,
            "duration": loan.loan_duration,
            "monthlyInterestRate": loan.product.monthly_interest_rate,
            "disbursementAmount": loan.loan_disbursement_amount,
            "disbursementDate": disbursement_date,
            "installmentAmount": loan.installment_amount,
            "firstPaymentDate": reformat_date(payment.due_date, date_format),
            "transactionStatus": loan_status,
            "bank": bank_detail,
            "isDigisignRegistered": is_digisign_registered,
        }

        return success_response(data=data_resp)


class LeadgenPaymentDetail(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        account_payment_id = self.kwargs["account_payment_id"]
        payment_id = self.kwargs["payment_id"]
        customer = Customer.objects.get_or_none(user=user)

        payment = (
            Payment.objects.filter(
                id=payment_id, loan__customer=customer.id, account_payment=account_payment_id
            )
            .select_related("loan")
            .first()
        )
        if not payment:
            return error_response(
                status=status.HTTP_404_NOT_FOUND,
                message="Payment tidak ditemukan",
            )

        loan = payment.loan
        if not loan:
            return error_response(
                status=status.HTTP_404_NOT_FOUND,
                message="Loan tidak ditemukan",
            )

        bad = (
            BankAccountDestination.objects.filter(
                customer=customer,
                bank_account_category__category=BankAccountCategoryConst.SELF,
                bank__is_active=True,
            )
            .exclude(is_deleted=True)
            .select_related("bank", "name_bank_validation")
            .first()
        )

        bank_detail = {}
        if bad:
            bank_detail = {
                "name": bad.bank.bank_name_frontend,
                "accountName": bad.name_bank_validation.name_in_bank,
                "accountNumber": bad.account_number,
            }

        payment_status = mapping_status_payment(payment.status)

        date_format = DateFormatString.DATE_WITH_TIME
        first_payment_date = (
            Payment.objects.filter(loan=loan)
            .order_by('due_date')
            .values_list('due_date', flat=True)
            .first()
        )
        data_resp = {
            "id": payment_id,
            "loanXid": loan.loan_xid,
            "transactionDate": date_format_to_localtime(loan.cdate, date_format),
            "amount": loan.loan_amount,
            "duration": loan.loan_duration,
            "disbursementAmount": loan.loan_disbursement_amount,
            "firstPaymentDate": reformat_date(first_payment_date, date_format),
            "paymentStatus": payment_status,
            "bank": bank_detail,
        }

        return success_response(data=data_resp)


class LeadgenInactiveLoan(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def get(self, request: Request, *args, **kwargs) -> Response:
        loans = Loan.objects.filter(
            account__customer__user=request.user_obj,
            loan_status=LoanStatusCodes.INACTIVE,
        )

        exclude_self_loans = loans.exclude(transaction_method=TransactionMethodCode.SELF.code)
        for loan in exclude_self_loans:
            update_loan_status_and_loan_history(
                loan_id=loan.id,
                new_status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                change_reason=LeadgenLoanCancelChangeReason.LEADGEN_INACTIVE_LOAN,
            )

        self_loans = loans.filter(transaction_method=TransactionMethodCode.SELF.code)

        if not self_loans:
            return success_response(status=status.HTTP_200_OK, data={}, is_display_data_field=True)

        if len(self_loans) == 1:
            return success_response(
                status=status.HTTP_200_OK, data={"xid": self_loans.last().loan_xid}
            )
        else:
            j1_loans = []
            plr_loans = []

            for self_loan in self_loans:
                if self_loan.partnerloanrequest_set.exists():
                    plr_loans.append(self_loan)
                else:
                    j1_loans.append(self_loan)

            if plr_loans:
                loan_xid = plr_loans[0].loan_xid
                plr_loans.remove(plr_loans[0])
            else:
                loan_xid = j1_loans[0].loan_xid
                j1_loans.remove(j1_loans[0])

            for j1_loan in j1_loans:
                update_loan_status_and_loan_history(
                    loan_id=j1_loan.id,
                    new_status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                    change_reason=LeadgenLoanCancelChangeReason.LEADGEN_INACTIVE_LOAN,
                )

            for plr_loan in plr_loans:
                update_loan_status_and_loan_history(
                    loan_id=plr_loan.id,
                    new_status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                    change_reason=LeadgenLoanCancelChangeReason.LEADGEN_INACTIVE_LOAN,
                )

            return success_response(status=status.HTTP_200_OK, data={"xid": loan_xid})


class LeadgenAccountPaymentList(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def get(self, request: Request, *args, **kwargs) -> Response:
        try:
            ap_list = []

            user = self.request.user_obj
            customer = user.customer

            account = Account.objects.filter(customer=customer).last()
            if not account:
                return error_response(
                    status=status.HTTP_404_NOT_FOUND,
                    message="Account untuk customer id {} tidak ditemukan".format(customer.id),
                )

            payments = (
                Payment.objects.filter(
                    account_payment__status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
                    account_payment__account=account,
                )
                .select_related("loan", "account_payment", "loan__transaction_method")
                .exclude(account_payment__due_amount=0)
                .order_by("due_date")
            )

            if not payments.exists():
                return success_response(
                    status=status.HTTP_200_OK, data=ap_list, is_display_data_field=True
                )

            ap_data = dict()
            for payment in payments:
                if payment.loan.transaction_method.id == TransactionMethodCode.SELF.code:
                    if payment.account_payment.id in ap_data:
                        ap_data[payment.account_payment.id]["dueAmount"] += (
                            payment.remaining_principal
                            + payment.remaining_interest
                            + payment.remaining_late_fee
                        )
                    else:
                        ap_data.update(
                            {
                                payment.account_payment.id: {
                                    "id": payment.account_payment.id,
                                    "dueAmount": payment.remaining_principal
                                    + payment.remaining_interest
                                    + payment.remaining_late_fee,
                                    "dpd": payment.account_payment.dpd,
                                    "dueDate": payment.account_payment.due_date,
                                    "dueStatus": mapping_status_payment(
                                        payment.account_payment.status_id
                                    ),
                                }
                            }
                        )

            for ap_id in ap_data:
                ap_list.append(ap_data.get(ap_id))

            return success_response(
                status=status.HTTP_200_OK, data=ap_list, is_display_data_field=True
            )
        except Exception as e:
            return error_response(message=str(e))


class LeadgenAccountPaymentDetail(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def get(self, request: Request, *args, **kwargs) -> Response:
        account_payment_id = self.kwargs["account_payment_id"]

        user = self.request.user_obj
        customer = user.customer
        account = Account.objects.filter(customer=customer).last()
        if not account:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message="Account tidak ditemukan",
            )

        account_payment = AccountPayment.objects.filter(id=account_payment_id).last()
        if not account_payment:
            return success_response(is_display_data_field=True)

        if account_payment.account != account:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message="Data ini bukan milik Anda",
            )

        application = account_payment.account.application_set.last()
        if application.product_line_code != ProductLineCodes.J1:
            return Response(status=status.HTTP_204_NO_CONTENT)

        resp_data = {
            "id": account_payment.id,
            "dueAmount": account_payment.due_amount,
            "dpd": account_payment.dpd,
            "dueDate": account_payment.due_date,
            "dueStatus": mapping_status_payment(account_payment.status_id),
            "loans": [],
        }

        try:
            loans = get_list_loan_by_account_payment(account_payment_id)
            total_due_amount = 0
            if loans:
                for loan in loans:
                    total_due_amount += loan["remainingInstallmentAmount"]
                resp_data["loans"] = loans
            resp_data["dueAmount"] = total_due_amount
        except Exception as e:
            return error_response(status=status.HTTP_500_INTERNAL_SERVER_ERROR, message=str(e))

        return success_response(status=status.HTTP_200_OK, data=resp_data)


class LeadgenActiveAccountPayment(AccountPaymentDpd, LeadgenStandardAPIView):
    permission_classes = []
    authentication_classes = [LeadgenAPIAuthentication]

    @allowed_leadgen_partner
    def get(self, request: Request, *args, **kwargs) -> Response:
        response = super().get(request, *args, **kwargs)
        response_data = response.data.get("data")
        if response.status_code == status.HTTP_404_NOT_FOUND or not response_data.get("due_date"):
            return Response(status=status.HTTP_200_OK, data={"data": {}})

        due_date = response_data["due_date"].strftime("%Y-%m-%dT%H:%M:%S:%f")
        if response_data.get("cashback_counter"):
            cashback_rate = response_data.get("cashback_counter") / 100
        else:
            cashback_rate = 0

        new_response = {
            "dueAmount": response_data.get("total_loan_amount"),
            "dpd": response_data.get("dpd"),
            "dueDate": due_date,
            "cashbackRate": cashback_rate,
        }
        return success_response(status=status.HTTP_200_OK, data=new_response)


class LeadgenLoanTransactionResult(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def get(self, request: Request, *args, **kwargs) -> Response:
        loan_xid = self.kwargs["loan_xid"]
        customer_id = request.user.customer.id
        loan = (
            Loan.objects.select_related('transaction_method', 'bank_account_destination')
            .filter(
                loan_xid=loan_xid,
                customer_id=customer_id,
                loan_status__gte=211,
                loan_status__lte=220,
            )
            .last()
        )
        if not loan:
            return success_response(is_display_data_field=True)

        if (
            LoanStatusCodes.DRAFT
            <= loan.loan_status_id
            <= LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING
        ):
            disbursement_status = TransactionStatusLSP.PENDING
        elif loan.loan_status_id >= LoanStatusCodes.CURRENT:
            disbursement_status = TransactionStatusLSP.SUCCESS
        elif (
            LoanStatusCodes.TRANSACTION_FAILED
            <= loan.loan_status_id
            <= LoanStatusCodes.LENDER_REJECT
        ):
            disbursement_status = TransactionStatusLSP.FAILED
        else:
            disbursement_status = None

        response_data = {
            "productName": loan.transaction_method.fe_display_name,
            "amount": loan.loan_amount,
            "status": loan.loan_status_id,
            "disbursementStatus": disbursement_status,
            "disbursementDate": date_format_to_localtime(
                loan.cdate, DateFormatString.DATE_WITH_TIME
            ),
            "disbursementAmount": loan.loan_disbursement_amount,
            "bank": {
                "name": loan.bank_account_destination.bank.bank_name_frontend,
                "accountName": loan.bank_account_destination.name_bank_validation.validated_name,
                "accountNumber": loan.bank_account_destination.account_number,
                "logo": loan.bank_account_destination.bank.bank_logo,
            },
        }

        return success_response(status=status.HTTP_200_OK, data=response_data)


class LeadgenSetPrimaryPaymentMethod(PaymentMethodUpdateView, LeadgenStandardAPIView):
    permission_classes = []
    authentication_classes = [LeadgenAPIAuthentication]

    @allowed_leadgen_partner
    def patch(self, request: Request, *args, **kwargs) -> Response:
        customer = request.user.customer
        payment_method_id = self.kwargs["payment_method_id"]
        is_exists = PaymentMethod.objects.filter(id=payment_method_id, customer=customer).exists()
        if not is_exists:
            message = "payment method {} tidak ditemukan".format(payment_method_id)
            return error_response(status=status.HTTP_404_NOT_FOUND, message=message)

        response = super().put(request, payment_method_id)
        if response.status_code == status.HTTP_400_BAD_REQUEST:
            message = "payment method {} tidak ditemukan".format(payment_method_id)
            return error_response(status=status.HTTP_404_NOT_FOUND, message=message)
        else:
            return success_response(status=status.HTTP_204_NO_CONTENT)


class LeadgenPaymentMethodList(PaymentMethodRetrieveView, LeadgenStandardAPIView):
    permission_classes = []
    authentication_classes = [LeadgenAPIAuthentication]

    @allowed_leadgen_partner
    def get(self, request: Request, *args, **kwargs) -> Response:
        try:
            if not hasattr(request.user, "customer"):
                return error_response(message="Customer tidak ditemukan")

            if not request.user.customer.account:
                return error_response(message="Account tidak ditemukan")

            response = super().get(request, request.user.customer.account.id)

            if isinstance(response, JsonResponse):
                res_content = json.loads(response.content.decode("utf-8"))
            else:
                res_content = response.data

            if res_content["success"]:
                bank_vas, retails, ewallets = list(), list(), list()

                payment_methods = res_content["data"]["payment_methods"]

                if not payment_methods:
                    return success_response(
                        status=status.HTTP_200_OK, data={}, is_display_data_field=True
                    )

                for pm in payment_methods:
                    if pm.get("type") == PaymentMethodTypes.BANK_VA:
                        bank_vas.append(
                            {
                                "id": pm.get("id"),
                                "name": pm.get("bank_virtual_name"),
                                "bankCode": pm.get("bank_code"),
                                "virtualAccount": pm.get("virtual_account"),
                                "logo": pm.get("image_logo_url"),
                            }
                        )
                    elif pm.get("type") == PaymentMethodTypes.RETAIL:
                        retails.append(
                            {
                                "id": pm.get("id"),
                                "name": pm.get("bank_virtual_name"),
                                "bankCode": pm.get("bank_code"),
                                "virtualAccount": pm.get("virtual_account"),
                                "logo": pm.get("image_logo_url"),
                            }
                        )
                    elif pm.get("type") == PaymentMethodTypes.E_WALLET:
                        ewallets.append(
                            {
                                "id": pm.get("id"),
                                "name": pm.get("bank_virtual_name"),
                                "bankCode": pm.get("bank_code"),
                                "virtualAccount": pm.get("virtual_account"),
                                "logo": pm.get("image_logo_url"),
                            }
                        )

                return success_response(
                    status=status.HTTP_200_OK,
                    data={"bankVAs": bank_vas, "retails": retails, "eWallets": ewallets},
                )
            else:
                return error_response(message=res_content["errors"][0])

        except Exception as e:
            return error_response(message=str(e))


class LeadgenLoanList(AccountLoansView, LeadgenStandardAPIView):
    permission_classes = []
    authentication_classes = [LeadgenAPIAuthentication]

    @allowed_leadgen_partner
    @make_request_mutable
    def get(self, request: Request, *args, **kwargs) -> Response:
        action = self.kwargs['action']

        if action == LeadgenLoanActionOptions.ACTIVE:
            request.GET['type'] = LeadgenLoanActionOptions.ACTIVE.upper()
        elif action == LeadgenLoanActionOptions.PAID_OFF:
            request.GET['type'] = LeadgenLoanActionOptions.IN_ACTIVE.upper()

        response = super().get(request)
        res_contents = response.data

        if isinstance(res_contents, dict) and 'data' in res_contents:
            data_list = res_contents['data']
        else:
            data_list = []

        data_response = [
            data
            for data in data_list
            if data.get('product_type') == TransactionMethodCode.SELF.code
        ]

        mapped_data_response = [
            {
                "xid": item["loan_xid"],
                "transactionDate": reformat_date(
                    item["loan_date"], DateFormatString.DATE_WITH_TIME
                ),
                "amount": item["loan_amount"],
                "bank": {
                    "name": item["bank_name_frontend"],
                    "accountName": item["bank_account_name"],
                    "accountNumber": item["bank_account_number"],
                },
            }
            for item in data_response
        ]

        mapped_data_response = sorted(
            mapped_data_response,
            key=lambda x: datetime.fromisoformat(x["transactionDate"]),
            reverse=True,
        )

        grouped_data = defaultdict(list)
        for item in mapped_data_response:
            transaction_date = datetime.fromisoformat(item["transactionDate"])

            year_month = reformat_date(transaction_date, DateFormatString.YEAR_MONTH)
            grouped_data[year_month].append(item)

        sorted_grouped_data = dict(sorted(grouped_data.items(), reverse=True))

        if mapped_data_response:
            return success_response(status=status.HTTP_200_OK, data=sorted_grouped_data)
        else:
            return success_response(is_display_data_field=True)


class LeadgenGetPrimaryPaymentMethod(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def get(self, request: Request, *args, **kwargs) -> Response:
        customer = request.user.customer
        primary_payment_method = PaymentMethod.objects.filter(
            customer=customer, is_primary=True
        ).first()

        if not primary_payment_method:
            permata_payment_method = PaymentMethod.objects.filter(
                customer=customer, payment_method_name=PaymentMethodName.PERMATA
            ).first()
            if permata_payment_method:
                permata_payment_method.is_primary = True
                permata_payment_method.save(update_fields=["is_primary"])
                primary_payment_method = permata_payment_method
            else:
                return success_response(is_display_data_field=True)

        bank_logo = ""
        method_lookup = PaymentMethodLookup.objects.filter(
            name=primary_payment_method.payment_method_name
        ).first()
        if method_lookup:
            bank_logo = method_lookup.image_logo_url

        response_data = {
            "id": primary_payment_method.id,
            "name": primary_payment_method.payment_method_name,
            "bankCode": primary_payment_method.bank_code,
            "virtualAccount": primary_payment_method.virtual_account,
            "logo": bank_logo,
        }

        return success_response(status=status.HTTP_200_OK, data=response_data)


class LeadgenRegisterDigisign(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def post(self, request: Request, *args, **kwargs) -> Response:
        customer = request.user.customer
        application = customer.account.get_active_application()

        # check registration status
        registration_status = partnership_get_registration_status(application)
        if not registration_status:
            # register digisign
            partnership_register_digisign_task.delay(application.id)
        if registration_status in RegistrationStatus.DONE_STATUS:
            return success_response(
                status=status.HTTP_200_OK,
                message="user already registered",
            )
        else:
            return Response(status=status.HTTP_204_NO_CONTENT)

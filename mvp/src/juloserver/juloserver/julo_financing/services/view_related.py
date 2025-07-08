from typing import Optional, List, Dict

from django.template import Template
from django.template import Context
from django.http import QueryDict
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from babel.dates import format_date
from django.template.loader import render_to_string

from juloserver.account.models import AccountLimit
from juloserver.customer_module.utils.utils_crm_v1 import get_phone_from_applications
from juloserver.julo.models import (
    Customer,
    Image,
    CreditMatrixRepeatLoan,
    Loan,
    AuthUser,
    PaymentMethod,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.utils import (
    display_rupiah_no_space,
    execute_after_transaction_safely,
    display_rupiah_skrtp,
)
from juloserver.julo_financing.constants import (
    JFinancingErrorMessage,
    JFinancingProductListConst,
    JFinancingFeatureNameConst,
    JFINANCING_LOAN_PURPOSE,
    JFinancingProductImageType,
    JFinancingStatus,
)
from juloserver.julo_financing.models import (
    JFinancingCheckout,
    JFinancingProduct,
    JFinancingVerification,
    JFinancingVerificationHistory,
    ProductTagData,
)
from juloserver.julo_financing.utils import get_invalid_product_image
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.loan.exceptions import (
    AccountLimitExceededException,
    LoanTransactionLimitExceeded,
)
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod
from juloserver.loan.services.credit_matrix_repeat import get_credit_matrix_repeat
from juloserver.loan.services.lender_related import julo_one_lender_auto_matchmaking
from juloserver.loan.services.loan_related import (
    calculate_loan_amount,
    generate_loan_payment_julo_one,
    get_loan_amount_by_transaction_type,
    is_product_lock_by_method,
    transaction_fdc_risky_check,
    compute_payment_installment_julo_one,
    transaction_method_limit_check,
)
from juloserver.julo_financing.tasks import upload_jfinancing_signature_image_task
from juloserver.julo_financing.exceptions import (
    CheckoutNotFound,
    InvalidVerificationStatus,
    ProductOutOfStock,
    UserNotAllowed,
    JFinancingProductLocked,
    ProductNotFound,
)
from juloserver.julo_financing.services.crm_services import JFinancingVerificationStatusService
from juloserver.followthemoney.models import LoanAgreementTemplate
from juloserver.julo_financing.services.core_services import (
    get_shipping_fee_from_province,
    is_province_supported,
)


def get_account_available_limit(customer: Customer) -> int:
    account_limit = AccountLimit.objects.filter(account=customer.account).last()
    if not account_limit:
        return 0

    return account_limit.available_limit


def get_j_financing_user_info(customer: Customer) -> Dict[str, str]:
    province_supported = is_province_supported(str(customer.address_provinsi))

    return {
        "full_name": customer.fullname,
        "phone_number": customer.phone
        or get_phone_from_applications(customer.application_set.all()),
        "address": customer.full_address if province_supported else "",
        "address_detail": customer.address_detail if province_supported else "",
        "available_limit": get_account_available_limit(customer=customer),
        "province_name": customer.address_provinsi if province_supported else "",
    }


def get_min_quantity_to_show_product_in_list():
    fs = FeatureSettingHelper(
        feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PRODUCT_CONFIGURATION
    )
    if not fs.is_active or not fs.params:
        return JFinancingProductListConst.MIN_PRODUCT_QUANTITY

    return fs.params.get(
        'min_quantity_to_show_product_in_list', JFinancingProductListConst.MIN_PRODUCT_QUANTITY
    )


def get_mapping_thumbnail_url_for_list_j_financing_product(
    product_ids: List[int],
) -> Dict[int, str]:
    images = Image.objects.filter(
        image_source__in=product_ids, image_type=JFinancingProductImageType.PRIMARY
    ).order_by('pk')
    # generate thumbnail url by calling api first,
    # will enhance this by using static bucket when implement image uploading
    return {image.image_source: image.thumbnail_url_api for image in images}


def get_list_j_financing_product(category_id: Optional[int]) -> List[dict]:
    products = (
        JFinancingProduct.objects.with_tags()
        .filter(
            quantity__gte=get_min_quantity_to_show_product_in_list(),
            is_active=True,
        )
        .order_by('-pk')
    )

    if category_id is not None:
        products = products.filter(j_financing_category_id=category_id)

    mapping_thumbnail_url = get_mapping_thumbnail_url_for_list_j_financing_product(
        product_ids=[product.id for product in products]
    )

    results = []

    for product in products:
        # set empty string if product does not have thumbnail url
        thumbnail_url = mapping_thumbnail_url.get(product.id, '')
        display_installment_price = display_rupiah_no_space(
            number=product.display_installment_price
        )

        # sale tags
        sorted_tags: List[ProductTagData] = sorted(product.tags, key=lambda tag: tag.tag_name)

        result = {
            "id": product.id,
            "name": product.name,
            "thumbnail_url": thumbnail_url,
            "display_installment_price": display_installment_price,
            "sale_tags": [tag.__dict__ for tag in sorted_tags],
            "price": product.price,
        }
        results.append(result)

    return results


def get_j_financing_product_images(product_id: int) -> List[str]:
    # prioritize to show primary image first
    images = Image.objects.filter(
        image_source=product_id, image_type__in=JFinancingProductImageType.list_image_types()
    ).order_by('-image_type', '-pk')

    # generate image url by calling api first,
    # will enhance this by using static bucket when implement image uploading
    return [image.image_url for image in images]


def get_j_financing_product_detail(product_id: int) -> Optional[Dict[str, str]]:
    product: JFinancingProduct = (
        JFinancingProduct.objects.with_tags()
        .filter(
            id=product_id,
            is_active=True,
        )
        .first()
    )

    if not product:
        raise ProductNotFound

    if product.quantity < get_min_quantity_to_show_product_in_list():
        raise ProductOutOfStock

    sorted_tags: List[ProductTagData] = sorted(product.tags, key=lambda tag: tag.tag_name)
    return {
        "sale_tags": [tag.__dict__ for tag in sorted_tags],
        "images": get_j_financing_product_images(product_id=product_id),
        "display_installment_price": display_rupiah_no_space(
            number=product.display_installment_price,
        ),
        "description": product.description,
        "price": product.price,
        "name": product.name,
        "id": product.id,
    }


def populate_request_data_loan_calculation(request_data: QueryDict) -> None:
    request_data.update(
        self_bank_account=False,
        transaction_type_code=TransactionMethodCode.JFINANCING.code,
        is_tax=True,
    )


def get_available_durations(loan_choice: dict) -> list:
    fs = FeatureSettingHelper(
        feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PRODUCT_CONFIGURATION
    )
    if not fs.is_active or not fs.params['allowed_durations']['is_active']:
        return loan_choice

    allowed_durations = fs.params['allowed_durations']['durations']
    return [
        loan_choice for loan_choice in loan_choice if loan_choice['duration'] in allowed_durations
    ]


def get_customer_jfinancing_transaction_history(customer_id: int) -> List[Dict]:
    """
    Get customer's verification/transactions
    To enhance: pagination
    """

    checkouts = (
        JFinancingCheckout.objects.filter(
            customer_id=customer_id,
        )
        .select_related('verification')
        .filter(
            verification__loan__isnull=False,
        )
        .exclude(
            verification__validation_status=JFinancingStatus.INITIAL,
        )
        .order_by('-id')
    )

    # ger thumbnails
    j_product_ids = [checkout.j_financing_product_id for checkout in checkouts]
    thumbnails = get_mapping_thumbnail_url_for_list_j_financing_product(
        product_ids=j_product_ids,
    )

    # data for each transaction item
    default_img_url = get_invalid_product_image()
    response_checkouts = []
    for checkout in checkouts:
        checkout_data = {
            "id": checkout.id,
            "display_price": display_rupiah_no_space(checkout.price),
            "display_loan_amount": display_rupiah_no_space(checkout.verification.loan.loan_amount),
            "product_name": checkout.j_financing_product.name,
            "thumbnail_url": thumbnails.get(checkout.j_financing_product_id, default_img_url),
            "status": checkout.verification.get_validation_status_display(),
            "transaction_date": timezone.localtime(checkout.cdate).strftime('%d %b %Y'),
        }
        response_checkouts.append(checkout_data)

    return {
        "checkouts": response_checkouts,
    }


class JFinancingSubmitViewService:
    """
    Service for /api/julo-financing/v1/submit/{{token}}
    """

    def __init__(self, customer: Customer, submit_data: Dict) -> None:
        self.customer = customer
        self.account = customer.account
        self.application = self.account.get_active_application()
        self.submit_data = submit_data
        self.product = self._get_product(submit_data['j_financing_product_id'])
        self.shipping_fee = self._get_shipping_fee()

    def _get_product(self, pk: int) -> JFinancingProduct:
        return JFinancingProduct.objects.get(pk=pk)

    def _get_shipping_fee(self) -> int:
        return get_shipping_fee_from_province(self.submit_data['province_name'])

    def _get_total_price(self) -> int:
        """
        Total price for the product, might have more than one item in the future
        """
        return self.product.price + self.shipping_fee

    def _get_loan_amount(self) -> int:
        """
        Total Price + (future) other fees
        """
        return self._get_total_price()

    def check_eligibility(self) -> None:
        """
        Check elibility to make loan before submitting
        """

        # available limit
        account_limit = AccountLimit.objects.filter(
            account=self.account,
        ).last()

        if self._get_loan_amount() > account_limit.available_limit:
            raise AccountLimitExceededException

        # transaction method limit
        jfinancing_method = TransactionMethod.objects.get(pk=TransactionMethodCode.JFINANCING.code)
        is_within_limit, error_message = transaction_method_limit_check(
            account=self.account,
            transaction_method=jfinancing_method,
            minimum_loan_status=LoanStatusCodes.INACTIVE,
        )
        if not is_within_limit:
            raise LoanTransactionLimitExceeded(error_message)

    def submit(self) -> Dict:
        """
        create x209 loan, checkout, initial verification
        """
        self.check_eligibility()

        with transaction.atomic():
            self.loan = self.create_x209_loan()
            self.checkout = self.create_checkout()

            self.create_verification(loan=self.loan, checkout=self.checkout)

        # success, update submit data before returning
        response_data = self.submit_data
        response_data['loan_amount'] = self.loan.loan_amount
        response_data['product_name'] = self.checkout.j_financing_product.name
        response_data['total_price'] = self._get_total_price()
        response_data['checkout_id'] = self.checkout.id

        return response_data

    def create_checkout(self) -> JFinancingCheckout:
        """
        Create checkout record
        """
        checkout = JFinancingCheckout.objects.create(
            customer_id=self.customer.id,
            price=self.product.price,
            shipping_fee=self.shipping_fee,
            j_financing_product_id=self.product.id,
            additional_info=self.submit_data['checkout_info'],
            loan_duration=self.submit_data['loan_duration'],
        )

        return checkout

    def create_verification(self, loan: Loan, checkout: JFinancingCheckout) -> None:
        JFinancingVerification.objects.create(
            j_financing_checkout_id=checkout.id,
            validation_status=JFinancingStatus.INITIAL,
            loan_id=loan.id,
        )

    def create_x209_loan(self) -> Loan:
        """
        Create draft loan
        """
        # data for loan creation
        is_payment_point = False
        self_bank_account = False
        requested_loan_amount = self._get_loan_amount()
        bank_account_destination = None
        loan_purpose = JFINANCING_LOAN_PURPOSE
        loan_duration = self.submit_data['loan_duration']

        # transaction method
        transaction_method_id = TransactionMethodCode.JFINANCING.code
        transaction_method = TransactionMethod.objects.get(pk=transaction_method_id)

        is_locked, _ = is_product_lock_by_method(
            account=self.account,
            method_code=transaction_method_id,
            application_direct=self.application,
        )
        if is_locked:
            raise JFinancingProductLocked

        adjusted_loan_amount, credit_matrix, credit_matrix_product_line = calculate_loan_amount(
            application=self.application,
            loan_amount_requested=requested_loan_amount,
            transaction_type=transaction_method.method,
            is_payment_point=is_payment_point,
            is_self_bank_account=self_bank_account,
        )
        credit_matrix_product = credit_matrix.product
        monthly_interest_rate = credit_matrix_product.monthly_interest_rate
        origination_fee_pct = credit_matrix_product.origination_fee_pct
        # check credit matrix repeat, and if exist change the provision fee and interest
        credit_matrix_repeat = get_credit_matrix_repeat(
            self.customer.id,
            credit_matrix_product_line.product.product_line_code,
            transaction_method_id,
        )
        if credit_matrix_repeat:
            origination_fee_pct = credit_matrix_repeat.provision
            monthly_interest_rate = credit_matrix_repeat.interest
            # recalculate amount since origination_fee_pct may be changed
            adjusted_loan_amount = get_loan_amount_by_transaction_type(
                requested_loan_amount, origination_fee_pct, self_bank_account
            )

        loan_requested = dict(
            is_loan_amount_adjusted=True,
            original_loan_amount_requested=requested_loan_amount,
            loan_amount=adjusted_loan_amount,
            loan_duration_request=loan_duration,
            interest_rate_monthly=monthly_interest_rate,
            product=credit_matrix_product,
            provision_fee=origination_fee_pct,
            is_withdraw_funds=self_bank_account,
            product_line_code=self.application.product_line_code,
            transaction_method_id=transaction_method_id,
        )

        loan = generate_loan_payment_julo_one(
            application=self.application,
            loan_requested=loan_requested,
            loan_purpose=loan_purpose,
            credit_matrix=credit_matrix,
            bank_account_destination=bank_account_destination,
            draft_loan=True,
        )
        if credit_matrix_repeat:
            CreditMatrixRepeatLoan.objects.create(
                credit_matrix_repeat=credit_matrix_repeat,
                loan=loan,
            )
            loan.set_disbursement_amount()

        transaction_fdc_risky_check(loan)
        loan_update_dict = {'transaction_method_id': transaction_method_id}

        # assign lender
        lender = julo_one_lender_auto_matchmaking(loan)

        if lender:
            loan_update_dict.update({'lender_id': lender.pk, 'partner_id': lender.user.partner.pk})

        loan.update_safely(**loan_update_dict)

        return loan


class JFinancingUploadSignatureService:
    def __init__(self, checkout_id: int, input_data: Dict, user: AuthUser):
        self.checkout = JFinancingCheckout.objects.get_or_none(pk=checkout_id)
        if not self.checkout:
            raise CheckoutNotFound

        if not self.checkout.customer.user_id == user.id:
            raise UserNotAllowed

        if self.checkout.verification.validation_status != JFinancingStatus.INITIAL:
            raise InvalidVerificationStatus

        self.input_data = input_data
        self.user = user

    def upload_signature(self) -> None:
        """
        Main logic for uploading signature
        """
        with transaction.atomic():

            self._lock_and_update_product_quantity()
            self._update_verification_status()

            # create & upload signature
            image_id = self._create_signature()
            self._upload_signature(image_id=image_id)

            # update checkout
            self._update_checkout(image_id=image_id)

            # send event notification
            verification_service = JFinancingVerificationStatusService(self.checkout.verification)
            verification_service.send_event_verification_status_change()

    def _create_signature(self) -> int:
        """
        Create the signature Image
        Return image id
        """
        signature_image = Image(
            image_source=self.checkout.verification.loan_id,
            image_type='signature',
        )
        signature_image.save()

        signature_image.image.save(
            name=self.input_data['data'],
            content=self.input_data['upload'],
        )
        return signature_image.id

    def _upload_signature(self, image_id: int) -> None:
        execute_after_transaction_safely(
            lambda: upload_jfinancing_signature_image_task.delay(
                image_id=image_id,
                customer_id=self.user.customer.id,
            )
        )

    def _lock_and_update_product_quantity(self) -> None:
        """
        Lock & Update product quantity
        """
        product = JFinancingProduct.objects.select_for_update().get(
            pk=self.checkout.j_financing_product_id,
        )
        new_quantity = product.quantity - 1
        if new_quantity < 0:
            raise ProductOutOfStock

        product.quantity = new_quantity
        product.save(update_fields=['quantity'])

    def _update_verification_status(self) -> None:
        """
        Update status to ON_REVIEW & create history
        """
        verification = self.checkout.verification

        old_value = verification.validation_status
        new_value = JFinancingStatus.ON_REVIEW

        verification.validation_status = new_value
        verification.save(update_fields=['validation_status'])

        JFinancingVerificationHistory.objects.create(
            j_financing_verification=verification,
            field_name='validation_status',
            old_value=old_value,
            new_value=new_value,
            change_reason='user signed signature',
        )

    def _update_checkout(self, image_id: int) -> None:
        self.checkout.signature_image_id = image_id
        self.checkout.save(update_fields=['signature_image'])


class JFinancingTransactionDetailViewService:
    def __init__(self, checkout_id: int, user: AuthUser) -> None:
        self.checkout = (
            JFinancingCheckout.objects.exclude(
                verification__validation_status=JFinancingStatus.INITIAL
            )
            .filter(
                pk=checkout_id,
            )
            .last()
        )
        if not self.checkout:
            raise CheckoutNotFound

        if not self.checkout.customer.user_id == user.id:
            raise UserNotAllowed
        self.loan = self.checkout.verification.loan

    def _get_shipping_fee(self) -> int:
        return self.checkout.shipping_fee

    def _get_total_price(self) -> int:
        return self.checkout.total_price

    def get_transaction_detail(self):

        response_data = {
            "logistics_info": self.logistics_info,
            "product_detail": self.product_detail,
            "checkout_info": self.checkout_info,
            "transaction_detail": self.transaction_detail,
            "loan_detail": self.loan_detail,
        }

        return response_data

    @property
    def logistics_info(self) -> Dict:
        if self.checkout.verification.validation_status != JFinancingStatus.ON_DELIVERY:
            return {}

        # get icon url
        fs = FeatureSettingHelper(
            feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PRODUCT_CONFIGURATION
        )
        default_img = get_invalid_product_image()
        couriers_info = fs.get('couriers_info', default={})
        courier = couriers_info.get(self.checkout.courier_name, {})
        icon_link = courier.get('image_link', default_img)

        data = {
            "courier": {
                "icon_link": icon_link,
                "name": self.checkout.courier_name,
            },
            "seri_number": self.checkout.courier_tracking_id,
        }

        return data

    @property
    def product_detail(self) -> Dict:
        thumbnails = get_mapping_thumbnail_url_for_list_j_financing_product(
            product_ids=[self.checkout.j_financing_product_id],
        )

        # data for each transaction item
        default_img_url = get_invalid_product_image()
        return {
            "display_price": display_rupiah_no_space(self.checkout.price),
            "name": self.checkout.j_financing_product.name,
            "display_loan_amount": display_rupiah_no_space(self.loan.loan_amount),
            "thumbnail_url": thumbnails.get(self.checkout.j_financing_product_id, default_img_url),
            "status": self.checkout.verification.get_validation_status_display(),
        }

    @property
    def checkout_info(self) -> Dict:
        return self.checkout.additional_info

    @property
    def transaction_detail(self) -> Dict:
        return {
            "transaction_date": timezone.localtime(self.checkout.cdate).strftime(
                '%d %b %Y, %H:%M %Z'
            ),
            "display_total_price": display_rupiah_no_space(self._get_total_price()),
            "display_shipping_fee": display_rupiah_no_space(self._get_shipping_fee()),
            "display_price": display_rupiah_no_space(self.checkout.price),
        }

    @property
    def loan_detail(self) -> Dict:
        return {
            "display_total_price": display_rupiah_no_space(self._get_total_price()),
            "display_loan_amount": display_rupiah_no_space(self.loan.loan_amount),
            "duration": "{} bulan".format(self.loan.loan_duration),
            "monthly_installment_amount": display_rupiah_no_space(self.loan.installment_amount),
        }


def get_j_financing_loan_agreement_template(
    checkout_id: int,
    user_id: int,
    agreement_type: str,
) -> Dict[bool, str]:
    checkout = JFinancingCheckout.objects.filter(
        pk=checkout_id,
        customer__user_id=user_id,
        verification__isnull=False,
        verification__loan__isnull=False,
        verification__loan__account__isnull=False,
    ).last()
    if not checkout:
        return False, JFinancingErrorMessage.SYSTEM_ISSUE

    loan = checkout.verification.loan
    account = loan.account
    application = account.get_active_application()
    account_limit = account.get_account_limit
    if not account_limit:
        return False, JFinancingErrorMessage.SYSTEM_ISSUE

    payments = loan.payment_set.exclude(is_restructured=True).order_by('id')
    loan_amount = display_rupiah_skrtp(loan.loan_amount)
    for payment in payments:
        payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
        payment.due_amount = display_rupiah_skrtp(payment.due_amount + payment.paid_amount)

    _, interest_fee_monthly, _ = compute_payment_installment_julo_one(
        loan.loan_amount, loan.loan_duration, loan.interest_rate_monthly
    )
    julo_bank_code = '-'
    payment_method_name = '-'
    payment_method = PaymentMethod.objects.filter(
        virtual_account=loan.julo_bank_account_number
    ).first()
    if payment_method:
        julo_bank_code = payment_method.bank_code
        payment_method_name = payment_method.payment_method_name
    context = {
        'loan_xid': loan.loan_xid,
        'payments': payments,
        'application': application,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'loan_amount': loan_amount,
        'late_fee_amount': display_rupiah_skrtp(loan.late_fee_amount),
        'max_total_late_fee_amount': display_rupiah_skrtp(loan.max_total_late_fee_amount),
        'provision_fee_amount': display_rupiah_skrtp(loan.provision_fee()),
        'loan_tax_amount': display_rupiah_skrtp(loan.get_loan_tax_fee()),
        'interest_fee_monthly': display_rupiah_skrtp(interest_fee_monthly),
        'disbursement_fee': display_rupiah_skrtp(loan.disbursement_fee),
        'julo_bank_name': loan.julo_bank_name,
        'julo_bank_code': julo_bank_code,
        'payment_method_name': payment_method_name,
        'julo_bank_account_number': loan.julo_bank_account_number,
        'date_today': format_date(
            timezone.localtime(loan.sphp_sent_ts), 'd MMMM yyyy', locale='id_ID'
        ),
        'available_limit': display_rupiah_skrtp(account_limit.set_limit),
        'company_name': '',
        'poc_name': '',
        'poc_position': '',
        'license_number': '',
        'lender_address': '',
        'lender_signature_name': '',
        'signature': '',
    }

    lender = loan.lender
    if lender:
        context.update(
            {
                'company_name': lender.company_name,
                'poc_name': lender.poc_name,
                'poc_position': lender.poc_position,
                'license_number': lender.license_number,
                'lender_address': lender.lender_address,
                'lender_signature_name': lender.poc_name,
            }
        )

    loan_agreement_type = "spf_{}".format(agreement_type)
    template = LoanAgreementTemplate.objects.filter(
        Q(lender=lender) | Q(lender__isnull=True)
    ).filter(
        is_active=True, agreement_type=loan_agreement_type
    ).order_by ('lender_id').first()

    if not template:
        return True, render_to_string(
            'loan_agreement/spf_{}.html'.format(agreement_type), context=context
        )

    return True, Template(template.body).render(Context(context))

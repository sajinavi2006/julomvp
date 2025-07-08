from hashids import Hashids

from django.db import transaction
from django.utils import timezone

from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.models import Partner, ProductLookup
from juloserver.julo.exceptions import JuloException
from juloserver.julo.statuses import LoanStatusCodes

from .models import RenteeDeviceList, PaymentDeposit
from .constants import PaymentDepositStatus


RENTEE_DEPOSIT_PERCENTAGE = 0.2
RENTEE_PROTECTION_FEE = 75000
RENTEE_RESIDUAL_PERCENTAGE = 0.65


def get_deposit_loan(customer):
    payment_deposit_data = PaymentDeposit.objects.filter(
        loan__customer=customer,
        loan__loan_status=LoanStatusCodes.INACTIVE,
        status__in=PaymentDepositStatus.waiting()).order_by('-id').last()
    if not payment_deposit_data:
        return None

    return payment_deposit_data.loan


def get_loan_purpose():
    return RenteeDeviceList.objects.filter(
        is_active=True).values('id', 'price', 'device_name').order_by('id')


def get_loan_purpose_by_code(code):
    return RenteeDeviceList.objects.filter(is_active=True, pk=code).last()


def get_deposit_status_by_loan(loan):
    deposit_obj = PaymentDeposit.objects.get(loan=loan)
    return {
        "julo_bank_name": loan.julo_bank_name,
        "julo_bank_account_number": loan.julo_bank_account_number,
        "deposit_amount": deposit_obj.deposit_amount,
        "total_deposit_amount": deposit_obj.total_deposit_amount,
        "admin_fee": deposit_obj.admin_fee,
        "protection_fee": deposit_obj.protection_fee,
        "status": deposit_obj.status,
        "paid_total_deposit_amount": deposit_obj.paid_total_deposit_amount,
        "is_verified_code": deposit_obj.is_verified_code,
        "is_expired": loan.status == LoanStatusCodes.SPHP_EXPIRED,
        "expired_date": loan.sphp_exp_date
    }


def generate_payment_deposit(loan, device_id):
    hashids = Hashids(min_length=7, salt='julo_rentee_loan')

    loan_detail = get_rentee_loan_detail(device_id)
    PaymentDeposit.objects.create(
        loan=loan,
        rentee_device_id=device_id,
        admin_fee=loan_detail["admin_fee"],
        protection_fee=loan_detail['protection_fee'],
        total_deposit_amount=loan_detail['total_deposit_amount'],
        deposit_amount=loan_detail['deposit_amount'],
        rentee_invoice='JULO-RENTEE-' + hashids.encode(loan.id)
    )


def get_payment_deposit_pending(account, latest=False):
    payment_deposit_data = PaymentDeposit.objects.filter(
        loan__loan_status=LoanStatusCodes.INACTIVE,
        loan__account=account,
        status__in=PaymentDepositStatus.waiting()).order_by('-id')

    if latest:
        payment_deposit_data = payment_deposit_data.last()

    return payment_deposit_data


def process_payment_deposit(payment_deposit, remaining_amount):
    with transaction.atomic():
        payment_deposit = payment_deposit.lock()
        # update paid amount
        if payment_deposit.due_amount >= remaining_amount:
            payment_deposit.paid_total_deposit_amount += remaining_amount
            payment_deposit.save()
            remaining_amount = 0
        else:
            remaining_amount -= payment_deposit.due_amount
            payment_deposit.paid_total_deposit_amount += payment_deposit.due_amount
            payment_deposit.save()
        # update status if done
        payment_deposit.paid_date = timezone.localtime(timezone.now())
        if payment_deposit.due_amount == 0:
            payment_deposit.status = PaymentDepositStatus.SUCCESS
            payment_deposit.new_verification_code()
            payment_deposit.save()
        else:
            payment_deposit.status = PaymentDepositStatus.PARTIAL
            payment_deposit.save()

    return remaining_amount


def check_verification_code(code_input, loan):
    payment_deposit = PaymentDeposit.objects.get(loan=loan)

    check_expiried = loan.status != LoanStatusCodes.SPHP_EXPIRED
    check_status = payment_deposit.status == PaymentDepositStatus.SUCCESS
    check_code = payment_deposit.verification_code == code_input

    return check_expiried and check_status and check_code


def update_verified_code(loan):
    payment_deposit = PaymentDeposit.objects.get(loan=loan)
    payment_deposit.is_verified_code = True
    payment_deposit.save()


def get_rentee_loan_detail(device_id):
    product = ProductLookup.objects.get(is_active=True,
                                        product_line=ProductLineCodes.RENTEE)

    available_duration = [product.product_line.max_duration]
    provision_fee = product.admin_fee + RENTEE_PROTECTION_FEE

    rentee_device = get_loan_purpose_by_code(device_id)
    if not rentee_device:
        raise JuloException("device tidak ditemukan")

    loan_amount_request = rentee_device.price
    loan_amount = loan_amount_request
    disbursement_amount = loan_amount
    deposit_amount = loan_amount_request * RENTEE_DEPOSIT_PERCENTAGE
    total_deposit_amount = deposit_amount + provision_fee
    installed_loan_amount = int(loan_amount * RENTEE_RESIDUAL_PERCENTAGE)
    residual_loan_amount = loan_amount - installed_loan_amount

    return {
        "provision_fee": provision_fee,
        "available_duration": available_duration,
        "loan_amount": loan_amount,
        "disbursement_amount": disbursement_amount,
        "device_name": rentee_device.device_name,
        "product": product,
        "total_deposit_amount": total_deposit_amount,
        "deposit_amount": deposit_amount,
        "loan_amount_request": loan_amount_request,
        "installed_loan_amount": installed_loan_amount,
        "residual_loan_amount": residual_loan_amount,
        "admin_fee": product.admin_fee,
        "protection_fee": RENTEE_PROTECTION_FEE
    }


def update_deposit_before_reverting(loan):
    if loan.status != LoanStatusCodes.CANCELLED_BY_CUSTOMER:
        return False

    payment_deposit = PaymentDeposit.objects.get(loan=loan)
    if payment_deposit.status not in PaymentDepositStatus.has_paid():
        return False

    payment_deposit.is_verified_code = False
    payment_deposit.save()

    return True


def get_active_loan_by_customer(customer):
    last_loan = customer.loan_set.last()
    if last_loan and hasattr(last_loan, 'paymentdeposit'):
        payment_deposit = last_loan.paymentdeposit
        check_active_loan = last_loan.status == LoanStatusCodes.INACTIVE
        check_reactive_loan = last_loan.status == LoanStatusCodes.CANCELLED_BY_CUSTOMER \
            and payment_deposit.status == PaymentDepositStatus.SUCCESS

        if check_active_loan or check_reactive_loan:
            return {
                'loan_xid': last_loan.loan_xid,
                'loan_status': last_loan.status
            }

    return None

from builtins import str
import logging
import functools

from celery import task
from datetime import timedelta
from babel.dates import format_date
from django.utils import timezone
from django.conf import settings
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User
from django.db.models.expressions import RawSQL
from juloserver.julo.models import (
    Loan,
    Customer,
    EmailHistory,
    PaymentMethod,
    FeatureSetting
)
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.exceptions import JuloException
from juloserver.julo.services2 import encrypt
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.constants import FeatureNameConst

from ..models import (
    LoanRefinancingRequest,
    WaiverRequest,
    LoanRefinancingRequestCampaign,
    LoanRefinancingApproval,
)
from ..constants import (
    Campaign,
    LoanRefinancingConst,
    CovidRefinancingConst
)
from ..services.customer_related import get_eligible_customers
from ..services.notification_related import (CovidLoanRefinancingEmail,
                                             CovidLoanRefinancingSMS,
                                             CovidLoanRefinancingPN,
                                             CovidLoanRefinancingRobocall)
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.julo.clients import get_julo_sms_client
from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.exceptions import SmsNotSent
from juloserver.monitors.notifications import get_slack_bot_client
from juloserver.minisquad.utils import collection_detokenize_sync_object_model
from juloserver.pii_vault.constants import (
    PiiSource,
    PiiVaultDataType,
)

logger = logging.getLogger(__name__)


@task(queue="collection_normal")
def notify_eligible_customers_for_loan_refinancing():
    is_feature_on = FeatureSetting.objects.filter(
        is_active=True,
        feature_name=FeatureNameConst.LOAN_REFINANCING).exists()

    if not is_feature_on:
        return

    eligible_customer_ids = get_eligible_customers()

    for customer_id in eligible_customer_ids:
        send_loan_refinancing_email.delay(customer_id)


@task(queue="collection_normal")
def send_loan_refinancing_email(customer_id):
    customer = Customer.objects.get_or_none(pk=customer_id)

    if customer is None:
        raise JuloException('Customer not found')

    julo_email_client = get_julo_email_client()
    application = customer.application_set.last()

    today = timezone.localtime(timezone.now()).date()
    encrypter = encrypt()
    encrypted_customer_data = '{}|{}'.format(str(application.id), str(today))
    encoded_customer_id = encrypter.encode_string(encrypted_customer_data)

    status, headers, subject, msg = julo_email_client.\
        email_loan_refinancing_eligibility(customer, encoded_customer_id)

    template_code = "loan_refinancing_eligibility_email"
    loan = Loan.objects.filter(customer=customer).last()
    oldest_payment = loan.payment_set.filter(
        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME)\
        .order_by('payment_number').first()

    EmailHistory.objects.create(
        customer=customer,
        sg_message_id=headers["X-Message-Id"],
        to_email=customer.email,
        subject=subject,
        application=application,
        message_content=msg,
        template_code=template_code,
        payment=oldest_payment
    )

    logger.info({
        "action": "send_loan_refinancing_email",
        "customer_id": customer.id,
        "template_code": template_code
    })


@task(queue="collection_normal")
def send_loan_refinancing_request_email(loan_id):
    from ..services.loan_related import (
        get_unpaid_payments,
        construct_tenure_probabilities,
        get_loan_refinancing_request_info,
    )
    from juloserver.loan_refinancing.services.refinancing_product_related import \
        get_covid_loan_refinancing_request

    loan = Loan.objects.get_or_none(pk=loan_id)
    loan_refinancing_request = get_loan_refinancing_request_info(loan)
    covid_loan_refinancing_request = get_covid_loan_refinancing_request(loan)
    if not loan_refinancing_request:
        logger.info({
            "action": "send_loan_refinancing_request_email",
            "loan_id": loan.id,
            "error": "loan refinancing request not found"
        })

        return

    ordered_unpaid_payments = get_unpaid_payments(
        loan, order_by='payment_number')
    tenure_extension = loan_refinancing_request.tenure_extension
    tenure_dict = construct_tenure_probabilities(
        ordered_unpaid_payments, tenure_extension, covid_loan_refinancing_request)
    new_payment_structures = tenure_dict[loan_refinancing_request.tenure_extension]
    julo_email_client = get_julo_email_client()
    customer = loan.customer
    application = loan.application
    payment_method = PaymentMethod.objects.filter(loan=loan, is_latest_payment_method=True).last()
    if not payment_method:
        payment_method = PaymentMethod.objects.filter(loan=loan, is_primary=True).last()
    payment_method_detokenized = collection_detokenize_sync_object_model(
        PiiSource.PAYMENT_METHOD,
        payment_method,
        None,
        ['virtual_account'],
        PiiVaultDataType.KEY_VALUE,
    )
    customer_info = {
        'customer': customer,
        'va_number': payment_method_detokenized.virtual_account,
        'bank_code': payment_method.bank_code,
        'bank_name': payment_method.payment_method_name
    }

    payment_info = {
        'new_payment_structures': new_payment_structures,
        'due_amount':
            new_payment_structures[LoanRefinancingConst.FIRST_LOAN_REFINANCING_INSTALLMENT][
                'due_amount'],
        'total_due_amount': functools.reduce(
            lambda x, y: x + y['due_amount'], new_payment_structures, 0),
        'late_fee_discount': loan_refinancing_request.total_latefee_discount,
        'chosen_tenure': loan_refinancing_request.tenure_extension
    }

    status, headers, subject, msg = julo_email_client.\
        email_loan_refinancing_request(customer_info, payment_info)

    template_code = "loan_refinancing_request"
    oldest_payment = loan.payment_set.filter(
        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME)\
        .order_by('payment_number').first()

    EmailHistory.objects.create(
        customer=customer,
        sg_message_id=headers["X-Message-Id"],
        to_email=customer.email,
        subject=subject,
        application=application,
        message_content=msg,
        template_code=template_code,
        payment=oldest_payment
    )

    logger.info({
        "action": "email_notify_loan_refinancing",
        "customer_id": customer.id,
        "template_code": template_code
    })


@task(queue="collection_normal")
def send_loan_refinancing_success_email(loan_id):
    from ..services.loan_related import (
        get_loan_refinancing_request_info
    )

    loan = Loan.objects.get_or_none(pk=loan_id)
    loan_refinancing_request = get_loan_refinancing_request_info(loan)

    if not loan_refinancing_request:
        logger.info({
            "action": "send_loan_refinancing_success_email",
            "loan_id": loan.id,
            "error": "loan refinancing request not found"
        })

        return

    customer = loan.customer
    application = loan.application
    julo_email_client = get_julo_email_client()
    status, headers, subject, msg = julo_email_client.\
        email_loan_refinancing_success(customer)

    template_code = "loan_refinancing_active"
    oldest_payment = loan.payment_set.filter(
        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME)\
        .order_by('payment_number').first()

    customer_detokenized = collection_detokenize_sync_object_model(
        PiiSource.CUSTOMER,
        customer,
        customer.customer_xid,
        ['email'],
    )

    EmailHistory.objects.create(
        customer=customer,
        sg_message_id=headers["X-Message-Id"],
        to_email=customer_detokenized.email,
        subject=subject,
        application=application,
        message_content=msg,
        template_code=template_code,
        payment=oldest_payment
    )

    logger.info({
        "action": "send_loan_refinancing_success_email",
        "customer_id": customer.id,
        "template_code": template_code
    })


@task(queue="collection_normal")
def send_email_multiple_payment_minus_expiry(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingEmail(loan_refinancing_request).send_multiple_payment_minus_expiry_email()


@task(queue="collection_normal")
def send_email_multiple_payment_expiry(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingEmail(loan_refinancing_request).send_multiple_payment_expiry_email()


@task(queue="collection_normal")
def send_email_multiple_payment_ptp(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingEmail(loan_refinancing_request).send_multiple_payment_ptp_email()


@task(queue="collection_normal")
def send_email_covid_refinancing_approved(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingEmail(loan_refinancing_request).send_approved_email()


@task(queue="collection_normal")
def send_sms_covid_refinancing_offer_selected(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingSMS(loan_refinancing_request).send_reminder_offer_selected_sms()


@task(queue="collection_normal")
def send_pn_covid_refinancing_offer_selected(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingPN(loan_refinancing_request).send_reminder_offer_pn()


@task(queue="collection_normal")
def send_pn_covid_refinancing_approved(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingPN(loan_refinancing_request).send_approved_pn()


@task(queue="collection_normal")
def send_sms_covid_refinancing_approved(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingSMS(loan_refinancing_request).send_approved_sms()


@task(queue="collection_normal")
def send_sms_covid_refinancing_activated(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingSMS(loan_refinancing_request).send_activated_sms()


@task(queue="collection_normal")
def send_pn_covid_refinancing_activated(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingPN(loan_refinancing_request).send_activated_pn()


@task(queue="collection_normal")
def send_sms_covid_refinancing_reminder_offer_selected_2(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingSMS(loan_refinancing_request).send_reminder_offer_selected_2_sms()


@task(queue="collection_normal")
def send_pn_covid_refinancing_reminder_offer_selected_2(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingPN(loan_refinancing_request).send_reminder_offer_selected_minus_2_pn()


@task(queue="collection_normal")
def send_email_covid_refinancing_reminder(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingEmail(loan_refinancing_request).send_reminder_email()


@task(queue="collection_normal")
def send_sms_covid_refinancing_reminder_offer_selected_1(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingSMS(loan_refinancing_request).send_reminder_offer_selected_1_sms()


@task(queue="collection_normal")
def send_pn_covid_refinancing_reminder_offer_selected_1(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingPN(loan_refinancing_request).send_reminder_offer_selected_minus_1_pn()


@task(queue="collection_normal")
def send_email_covid_refinancing_activated(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingEmail(loan_refinancing_request).send_activated_email()


@task(queue="collection_normal")
def send_email_sos_refinancing_activated(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingEmail(loan_refinancing_request).send_email_sos_refinancing_activated()


@task(queue="collection_normal")
def send_email_covid_refinancing_opt(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    not_opt_email_status = ['Form Viewed', 'Offer Generated']

    if loan_refinancing_request.status in not_opt_email_status:
        return

    CovidLoanRefinancingEmail(loan_refinancing_request).send_opt_email()


@task(queue="collection_normal")
def send_reminder_email_opt():
    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
        status=CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email
    )

    today = timezone.localtime(timezone.now()).date()
    for loan_refinancing_request in loan_refinancing_requests:
        loan = loan_refinancing_request.loan
        payment_unpaid = loan.payment_set.by_loan(loan).order_by(
            'payment_number').not_paid().first()
        if not payment_unpaid:
            continue
        dpd_when_upload_request = loan_refinancing_request.request_date - payment_unpaid.due_date
        day_after_request = today - loan_refinancing_request.request_date
        if dpd_when_upload_request.days < -7:
            if payment_unpaid.due_late_days in [-15, -10, -5, -2, 0, 2]:
                send_email_covid_refinancing_opt.delay(loan_refinancing_request.id)
        elif -7 < dpd_when_upload_request.days < 0:
            if day_after_request.days in [1] or \
                    payment_unpaid.due_late_days in [-5, -2, 0, 2]:
                send_email_covid_refinancing_opt.delay(loan_refinancing_request.id)
        elif dpd_when_upload_request.days >= 0:
            if day_after_request.days in [1, 3, 5]:
                send_email_covid_refinancing_opt.delay(loan_refinancing_request.id)


@task(queue="collection_normal")
def send_email_pending_covid_refinancing(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingEmail(loan_refinancing_request).send_pending_refinancing_email()


@task(queue="collection_normal")
def send_email_covid_refinancing_reminder_to_pay_minus_2(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    if loan_refinancing_request.status != CovidRefinancingConst.STATUSES.approved:
        return
    CovidLoanRefinancingEmail(loan_refinancing_request).send_expiration_minus_2_email()


@task(queue="collection_normal")
def send_email_covid_refinancing_reminder_to_pay_minus_1(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    if loan_refinancing_request.status != CovidRefinancingConst.STATUSES.approved:
        return

    CovidLoanRefinancingEmail(loan_refinancing_request).send_expiration_minus_1_email()


@task(queue="collection_normal")
def send_pn_covid_refinancing_reminder_to_pay_minus_2(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    if loan_refinancing_request.status != CovidRefinancingConst.STATUSES.approved:
        return
    CovidLoanRefinancingPN(loan_refinancing_request).send_expiration_minus_2_pn()


@task(queue="collection_normal")
def send_pn_covid_refinancing_reminder_to_pay_minus_1(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    if loan_refinancing_request.status != CovidRefinancingConst.STATUSES.approved:
        return
    CovidLoanRefinancingPN(loan_refinancing_request).send_expiration_minus_1_pn()


@task(queue="collection_normal")
def send_sms_covid_refinancing_reminder_to_pay_minus_2(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    if loan_refinancing_request.status != CovidRefinancingConst.STATUSES.approved:
        return
    CovidLoanRefinancingSMS(loan_refinancing_request).send_expiration_minus_2_sms()


@task(queue="collection_normal")
def send_sms_covid_refinancing_reminder_to_pay_minus_1(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    if loan_refinancing_request.status != CovidRefinancingConst.STATUSES.approved:
        return
    CovidLoanRefinancingSMS(loan_refinancing_request).send_expiration_minus_1_sms()


@task(queue="collection_normal")
def send_all_refinancing_request_reminder_to_pay_minus_1():
    from ..services.comms_channels import send_loan_refinancing_request_reminder_minus_1
    from django.db.models.expressions import RawSQL
    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
        is_multiple_ptp_payment=False,
        status='Approved', loanrefinancingoffer__is_accepted=True,
        loanrefinancingoffer__offer_accepted_ts__date=RawSQL(
            "CURRENT_DATE - (interval '1 day' * (expire_in_days - 1))", []))
    for loan_refinancing_request in loan_refinancing_requests:
        send_loan_refinancing_request_reminder_minus_1(loan_refinancing_request)


@task(queue="collection_normal")
def send_all_refinancing_request_reminder_to_pay_minus_2():
    from ..services.comms_channels import send_loan_refinancing_request_reminder_minus_2
    from django.db.models.expressions import RawSQL
    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
        is_multiple_ptp_payment=False,
        status=CovidRefinancingConst.STATUSES.approved, loanrefinancingoffer__is_accepted=True,
        loanrefinancingoffer__offer_accepted_ts__date=RawSQL(
            "CURRENT_DATE - (interval '1 day' * (expire_in_days - 2))", []))
    for loan_refinancing_request in loan_refinancing_requests:
        send_loan_refinancing_request_reminder_minus_2(loan_refinancing_request)


@task(queue="collection_normal")
def send_all_multiple_payment_ptp_minus_expiry():
    from ..services.comms_channels import send_loan_refinancing_request_multiple_payment_expiry_minus_notification
    from django.db.models.expressions import RawSQL
    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
        is_multiple_ptp_payment=False,
        status=CovidRefinancingConst.STATUSES.approved, loanrefinancingoffer__is_accepted=True,
        loanrefinancingoffer__offer_accepted_ts__date=RawSQL(
            "CURRENT_DATE - (interval '1 day' * (expire_in_days - 1))", []))
    for loan_refinancing_request in loan_refinancing_requests:
        send_loan_refinancing_request_multiple_payment_expiry_minus_notification(
            loan_refinancing_request)


@task(queue="collection_normal")
def send_all_multiple_payment_ptp_expiry():
    from ..services.comms_channels import send_loan_refinancing_request_multiple_payment_expiry_notification
    from django.db.models.expressions import RawSQL
    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
        is_multiple_ptp_payment=False,
        status=CovidRefinancingConst.STATUSES.approved, loanrefinancingoffer__is_accepted=True,
        loanrefinancingoffer__offer_accepted_ts__date=timezone.localtime(timezone.now()).date())
    for loan_refinancing_request in loan_refinancing_requests:
        send_loan_refinancing_request_multiple_payment_expiry_notification(loan_refinancing_request)


@task(queue="collection_normal")
def send_all_refinancing_request_reminder_offer_selected_2():
    from ..services.comms_channels import send_loan_refinancing_request_reminder_offer_selected_2
    from django.db.models.expressions import RawSQL
    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
        status=CovidRefinancingConst.STATUSES.offer_selected,
        loanrefinancingoffer__is_accepted=True,
        loanrefinancingoffer__offer_accepted_ts__date=RawSQL(
            "CURRENT_DATE - (interval '1 day' * (expire_in_days - 2))",
            []))
    for loan_refinancing_request in loan_refinancing_requests:
        send_loan_refinancing_request_reminder_offer_selected_2(loan_refinancing_request)


@task(queue="collection_normal")
def send_all_refinancing_request_reminder_offer_selected_1():
    from ..services.comms_channels import send_loan_refinancing_request_reminder_offer_selected_1
    from django.db.models.expressions import RawSQL
    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
        status=CovidRefinancingConst.STATUSES.offer_selected,
        loanrefinancingoffer__is_accepted=True,
        loanrefinancingoffer__offer_accepted_ts__date=RawSQL(
            "CURRENT_DATE - (interval '1 day' * (expire_in_days - 1))",
            []))
    for loan_refinancing_request in loan_refinancing_requests:
        send_loan_refinancing_request_reminder_offer_selected_1(loan_refinancing_request)


@task(queue="collection_normal")
def send_robocall_refinancing_request_reminder_offer_selected_3():
    from ..services.comms_channels import send_loan_refinancing_robocall_reminder_minus_3
    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
        status=CovidRefinancingConst.STATUSES.offer_selected,
        loanrefinancingoffer__is_accepted=True,
        loanrefinancingoffer__offer_accepted_ts__date=RawSQL(
            "CURRENT_DATE - (interval '3 day' * (expire_in_days - 1))",
            []))
    for loan_refinancing_request in loan_refinancing_requests:
        send_loan_refinancing_robocall_reminder_minus_3(loan_refinancing_request)


@task(queue="collection_normal")
def send_robocall_refinancing_request_approved_selected_3():
    from ..services.comms_channels import send_loan_refinancing_robocall_reminder_minus_3
    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
        status=CovidRefinancingConst.STATUSES.approved,
        loanrefinancingoffer__is_accepted=True,
        loanrefinancingoffer__offer_accepted_ts__date=RawSQL(
            "CURRENT_DATE - (interval '3 day' * (expire_in_days - 1))",
            []))
    for loan_refinancing_request in loan_refinancing_requests:
        send_loan_refinancing_robocall_reminder_minus_3(loan_refinancing_request)


@task(queue="collection_normal")
def send_sms_notification(customer_id, phone_number, text, template_code=None):
    mobile_number = format_e164_indo_phone_number(phone_number)
    get_julo_sms = get_julo_sms_client()
    txt_msg, response = get_julo_sms.prefix_change_notification(mobile_number, text)

    if response["status"] != "0":
        raise SmsNotSent(
            {
                "send_status": response["status"],
                "message_id": response.get("message-id"),
                "sms_client_method_name": "loan_refinancing_send_sms_notification",
                "error_text": response.get("error-text"),
            }
        )

    customer = Customer.objects.get(pk=customer_id)
    sms = create_sms_history(response=response,
                             customer=customer,
                             message_content=txt_msg,
                             to_mobile_phone=format_e164_indo_phone_number(response["to"]),
                             phone_number_type="mobile_phone_1",
                             template_code=template_code
                             )
    if sms:
        logger.info(
            {
                "status": "sms_created",
                "sms_history_id": sms.id,
                "message_id": sms.message_id,
            }
        )


@task(queue="collection_normal")
def send_all_proactive_refinancing_email_reminder_10am():
    send_proactive_email_send_reminder.delay("email", 2)
    send_proactive_email_open_reminder.delay("email", 4)


@task(queue="collection_normal")
def send_all_proactive_refinancing_email_reminder_8am():
    send_proactive_email_open_reminder.delay("email", 2)
    send_proactive_form_viewed_reminder.delay("email", 2)


@task(queue="collection_normal")
def send_all_proactive_refinancing_pn_reminder_8am():
    send_proactive_email_send_reminder.delay("pn", 1)
    send_proactive_email_open_reminder.delay("pn", 3)
    send_proactive_form_viewed_reminder.delay("pn", 4)


@task(queue="collection_normal")
def send_all_proactive_refinancing_pn_reminder_10am():
    send_proactive_email_open_reminder.delay("pn", 1)


@task(queue="collection_normal")
def send_all_proactive_refinancing_pn_reminder_12pm():
    send_proactive_email_send_reminder.delay("pn", 3)
    send_proactive_form_viewed_reminder.delay("pn", 1)


@task(queue="collection_normal")
def send_all_proactive_refinancing_robocall_reminder_8am():
    send_proactive_email_send_reminder.delay("robocall", 4)


@task(queue="collection_normal")
def send_all_proactive_refinancing_sms_reminder_10am():
    send_proactive_email_send_reminder.delay("sms", 6)
    send_proactive_email_open_reminder.delay("sms", 6)
    send_proactive_form_viewed_reminder.delay("sms", 6)


@task(queue="collection_normal")
def send_proactive_email_send_reminder(reminder_type, day):
    from ..services.comms_channels import send_proactive_refinancing_reminder
    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
        status=CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email,
        channel=CovidRefinancingConst.CHANNELS.proactive,
        request_date=RawSQL(
            "CURRENT_DATE - (interval '{} day')".format(day),
            []))
    for loan_refinancing_request in loan_refinancing_requests:
        send_proactive_refinancing_reminder(
            loan_refinancing_request, reminder_type, day, "email_send")


@task(queue="collection_normal")
def send_proactive_email_open_reminder(reminder_type, day):
    from ..services.comms_channels import send_proactive_refinancing_reminder
    from ..services.loan_related import get_unpaid_payments
    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
        status=CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email,
        request_date=RawSQL(
            "CURRENT_DATE - (interval '{} day')".format(day),
            []))
    today_minus_day = timezone.localtime(timezone.now()) - timedelta(days=day)
    range_start = today_minus_day.replace(hour=0, minute=0, second=0, microsecond=0)
    range_end = range_start + timedelta(days=1)
    for loan_refinancing_request in loan_refinancing_requests:
        ordered_unpaid_payments = get_unpaid_payments(
            loan_refinancing_request.loan, order_by='payment_number')
        email_history = EmailHistory.objects.filter(
            template_code__in=("email_notif_proactive_refinancing",
                               "emailsent_offer_first_email",
                               "emailsent_offer_first_email_b5"),
            payment=ordered_unpaid_payments[0],
            status__in=("open", "click",),
            udate__gte=range_start,
            udate__lt=range_end,
        ).last()
        if email_history:
            send_proactive_refinancing_reminder(
                loan_refinancing_request, reminder_type, day, "email_open")


@task(queue="collection_normal")
def send_proactive_form_viewed_reminder(reminder_type, day):
    from ..services.comms_channels import send_proactive_refinancing_reminder
    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
        status=CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit,
        form_viewed_ts__date=RawSQL(
            "CURRENT_DATE - (interval '{} day')".format(day),
            []))
    for loan_refinancing_request in loan_refinancing_requests:
        send_proactive_refinancing_reminder(loan_refinancing_request, reminder_type, day)


@task(queue="collection_normal")
def send_proactive_offer_generated_reminder(reminder_type, day):
    from ..services.comms_channels import send_proactive_refinancing_reminder
    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
        status=CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer,
        form_submitted_ts__date=RawSQL(
            "CURRENT_DATE - (interval '{} day')".format(day),
            []))
    for loan_refinancing_request in loan_refinancing_requests:
        send_proactive_refinancing_reminder(loan_refinancing_request, reminder_type, day)


@task(queue="collection_normal")
def send_proactive_email_reminder(loan_refinancing_req_id, new_status, day):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_req_id)
    CovidLoanRefinancingEmail(loan_refinancing_request).send_proactive_email(new_status, day)


@task(queue="collection_normal")
def send_proactive_pn_reminder(loan_refinancing_req_id, new_status, day):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_req_id)
    CovidLoanRefinancingPN(loan_refinancing_request).send_proactive_pn(new_status, day)


@task(queue="collection_normal")
def send_proactive_robocall_reminder(loan_refinancing_req_id, filter_data, limit):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_req_id)
    CovidLoanRefinancingRobocall(loan_refinancing_request).send_proactive_robocall(
        filter_data, limit)


@task(queue="collection_normal")
def send_proactive_sms_reminder(loan_refinancing_req_id, new_status):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_req_id)
    CovidLoanRefinancingSMS(loan_refinancing_request).send_proactive_sms(new_status)


@task(queue="collection_normal")
def send_email_refinancing_offer_selected(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingEmail(loan_refinancing_request).send_offer_selected_email()


@task(queue="collection_normal")
def send_email_refinancing_offer_selected_minus_1(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingEmail(loan_refinancing_request).send_offer_selected_minus_1_email_reminder()


@task(queue="collection_normal")
def send_email_refinancing_offer_selected_minus_2(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingEmail(loan_refinancing_request).send_offer_selected_minus_2_email_reminder()


@task(queue="collection_normal")
def send_robocall_refinancing_reminder_minus_3(loan_refinancing_request_id, filter_data, limit):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    CovidLoanRefinancingRobocall(loan_refinancing_request)\
        .send_reminder_refinancing_minus_3_robocall(filter_data, limit)


@task(queue="collection_low")
def send_slack_notification_for_waiver_approver(loan_id):
    today_date = timezone.localtime(timezone.now()).date()
    waiver_request = WaiverRequest.objects.filter(
        loan_id=loan_id, is_approved__isnull=True,
        is_automated=False, waiver_validity_date__gte=today_date
    ).order_by('cdate').last()
    if not waiver_request:
        return

    if not waiver_request.approver_group_name:
        return

    link = "{}{}?portal_type=approver_portal&loan_id={}".format(
        settings.NEW_CRM_BASE_URL, reverse('loan_refinancing:covid_refinancing_web_portal'),
        loan_id
    )
    message = "Waiver untuk {} menunggu approval Anda. Silakan klik {} untuk melakukan " \
        "pengecekan lebih lanjut. Mohon approve sebelum {}, jika terlambat, " \
        "program customer akan hangus.".format(loan_id, link, format_date(
        waiver_request.waiver_validity_date, 'd MMMM yyyy', locale='id_ID'))

    users = User.objects.filter(is_active=True, groups__name=waiver_request.approver_group_name)
    for user in users:
        if user.email:
            slack_user = get_slack_bot_client().api_call("users.lookupByEmail", email=user.email)
            if slack_user["ok"]:
                get_slack_bot_client().api_call(
                    "chat.postMessage", channel=slack_user['user']['id'], text=message)


@task(queue="collection_low")
def send_slack_notification_for_refinancing_approver(loan_refinancing_approval_id):
    loan_refinancing_approval = LoanRefinancingApproval.objects.filter(
        id=loan_refinancing_approval_id
    ).last()
    loan_refinancing_request = loan_refinancing_approval.loan_refinancing_request
    loan_refinancing_offer = loan_refinancing_request.loanrefinancingoffer_set.filter(
        is_accepted=True,
    ).last()

    link = "{}{}?portal_type=approver_portal&account_id={}".format(
        settings.NEW_CRM_BASE_URL,
        reverse('refinancing_collection_offer_j1'),
        loan_refinancing_request.account.id,
    )
    message = (
        "Refinancing untuk {} menunggu approval Anda. Silakan klik {} untuk melakukan "
        "pengecekan lebih lanjut. Mohon approve sebelum {}, jika terlambat, "
        "program customer akan hangus."
    ).format(
        loan_refinancing_request.account.id,
        link,
        format_date(
            (
                loan_refinancing_offer.offer_accepted_ts
                or loan_refinancing_request.cdate
                + timedelta(days=loan_refinancing_request.expire_in_days)
            ).date(),
            'd MMMM yyyy',
            locale='id_ID',
        ),
    )
    approver_group_name, _ = loan_refinancing_approval.approver_group_name()
    users = User.objects.filter(is_active=True, groups__name=approver_group_name)
    for user in users:
        if user.email:
            slack_user = get_slack_bot_client().api_call("users.lookupByEmail", email=user.email)
            if slack_user["ok"]:
                get_slack_bot_client().api_call(
                    "chat.postMessage", channel=slack_user['user']['id'], text=message
                )


@task(queue="collection_normal")
def send_all_refinancing_offer_reminder_for_requested_status_campaign_minus_2():
    from juloserver.loan_refinancing.services.comms_channels import send_loan_refinancing_requested_status_campaign_reminder_minus_2
    loan_refinancing_campaigns = LoanRefinancingRequestCampaign.objects.filter(
        loan_refinancing_request__status=CovidRefinancingConst.STATUSES.requested,
        campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
        loan_refinancing_request__request_date=RawSQL(
            "CURRENT_DATE - (interval '1 day' * (loan_refinancing_request.expire_in_days - 2))", []))
    for loan_refinancing_campaign in loan_refinancing_campaigns:
        send_loan_refinancing_requested_status_campaign_reminder_minus_2(
            loan_refinancing_campaign.loan_refinancing_request)


@task(queue="collection_normal")
def send_all_refinancing_offer_reminder_for_requested_status_campaign_minus_1():
    from juloserver.loan_refinancing.services.comms_channels import send_loan_refinancing_requested_status_campaign_reminder_minus_1
    loan_refinancing_campaigns = LoanRefinancingRequestCampaign.objects.filter(
        loan_refinancing_request__status=CovidRefinancingConst.STATUSES.requested,
        campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
        loan_refinancing_request__request_date=RawSQL(
            "CURRENT_DATE - (interval '1 day' * (loan_refinancing_request.expire_in_days - 1))", []))
    for loan_refinancing_campaign in loan_refinancing_campaigns:
        send_loan_refinancing_requested_status_campaign_reminder_minus_1(
            loan_refinancing_campaign.loan_refinancing_request)


@task(queue="collection_normal")
def send_email_requested_status_campaign_reminder_to_pay_minus_2(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    if loan_refinancing_request.status != CovidRefinancingConst.STATUSES.requested:
        return
    CovidLoanRefinancingEmail(loan_refinancing_request)._send_requested_status_campaign_expiration_minus_2_email()


@task(queue="collection_normal")
def send_email_requested_status_campaign_reminder_to_pay_minus_1(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    if loan_refinancing_request.status != CovidRefinancingConst.STATUSES.requested:
        return
    CovidLoanRefinancingEmail(loan_refinancing_request)._send_requested_status_campaign_expiration_minus_1_email()


@task(queue="collection_normal")
def send_pn_requested_status_campaign_reminder_to_pay_minus_2(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    if loan_refinancing_request.status != CovidRefinancingConst.STATUSES.requested:
        return
    CovidLoanRefinancingPN(loan_refinancing_request).send_requested_status_campaign_minus_2_pn()


@task(queue="collection_normal")
def send_pn_requested_status_campaign_reminder_to_pay_minus_1(loan_refinancing_request_id):
    loan_refinancing_request = LoanRefinancingRequest.objects.get(pk=loan_refinancing_request_id)
    if loan_refinancing_request.status != CovidRefinancingConst.STATUSES.requested:
        return
    CovidLoanRefinancingPN(loan_refinancing_request).send_requested_status_campaign_minus_1_pn()

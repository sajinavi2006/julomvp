import juloserver.pin.services as pin_services
from django.conf import settings
from juloserver.julo.models import (
    Customer,
    Application,
    OnboardingEligibilityChecking,
    EmailHistory,
    MobileFeatureSetting,
)
from juloserver.julo.constants import MobileFeatureNameConst
from django.utils import timezone
from django.template.loader import get_template
from juloserver.julovers.services.core_services import JuloverPageMapping
from juloserver.julovers.constants import JuloverPageConst
from juloserver.julo.clients import (
    get_julo_email_client,
    get_julo_sentry_client,
)
from juloserver.julo.exceptions import EmailNotSent
from juloserver.pin.services import CustomerPinChangeService
from juloserver.pin.tasks import send_reset_pin_sms
from juloserver.julo.utils import (
    generate_email_key,
    generate_phone_number_key,
)
from datetime import datetime, timedelta
from juloserver.apiv1.tasks import send_reset_password_email
from juloserver.julolog.julolog import JuloLog


logger = JuloLog()


def send_link_reset_pin_manual(cust_id, actor_id=None):
    result = "success"
    try:
        logger.info(
            {
                'action': 'send link reset pin',
                'id': cust_id,
                'actor_id': actor_id,
            }
        )
        result = _do_send_link_reset_pin_manual(cust_id)
    except Exception as e:
        result = str(e)
    return result


def _do_send_link_reset_pin_manual(cust_id):
    customer = Customer.objects.filter(pk=cust_id, is_active=True).last()
    if not customer:
        raise Exception("failed : customer not exists or not active")

    to_email = customer.email
    if not to_email:
        raise Exception("this customer doesn't have email")
    if not pin_services.does_user_have_pin(customer.user):
        raise Exception("failed : Customer has not set pin earlier")

    _custom_process_reset_pin_request(customer, to_email)

    is_oec = OnboardingEligibilityChecking.objects.filter(customer_id=cust_id).exists()
    additional_return = "This customer is rejected in jturbo first check"
    if not is_oec:
        additional_return = "This customer not yet select product picker"
    return f'success ask cust {cust_id} to open their email ({customer.email}). {additional_return}'


def _custom_process_reset_pin_request(
    customer, email=None, is_j1=True, is_mf=False, phone_number=None, new_julover=False
):

    password_type = 'pin' if is_j1 or is_mf else 'password'
    new_key_needed = False
    customer_pin_change_service = CustomerPinChangeService()

    if customer.reset_password_exp_date is None:
        new_key_needed = True
    else:
        if customer.has_resetkey_expired():
            new_key_needed = True
        elif (
            is_j1
            or is_mf
            and not customer_pin_change_service.check_key(customer.reset_password_key)
        ):
            new_key_needed = True

    if new_key_needed:
        if email:
            reset_pin_key = generate_email_key(email)
        else:
            reset_pin_key = generate_phone_number_key(phone_number)
        customer.reset_password_key = reset_pin_key
        if is_j1:
            mobile_feature_setting = MobileFeatureSetting.objects.get_or_none(
                feature_name=MobileFeatureNameConst.LUPA_PIN, is_active=True
            )
            if mobile_feature_setting:
                request_time = mobile_feature_setting.parameters.get(
                    'pin_users_link_exp_time', {'days': 0, 'hours': 24, 'minutes': 0}
                )
            else:
                request_time = {'days': 0, 'hours': 24, 'minutes': 0}
        else:
            request_time = {'days': 7, 'hours': 0, 'minutes': 0}

        reset_pin_exp_date = datetime.now() + timedelta(
            days=request_time.get('days'),
            hours=request_time.get('hours'),
            minutes=request_time.get('minutes'),
        )
        customer.reset_password_exp_date = reset_pin_exp_date
        customer.save()
        if is_j1 or is_mf:
            customer_pin = customer.user.pin
            customer_pin_change_service.init_customer_pin_change(
                email=email,
                phone_number=phone_number,
                expired_time=reset_pin_exp_date,
                customer_pin=customer_pin,
                change_source='Forget PIN',
                reset_key=reset_pin_key,
            )
        logger.info(
            {
                'status': 'just_generated_reset_%s' % password_type,
                'email': email,
                'phone_number': phone_number,
                'customer': customer,
                'reset_%s_key' % password_type: reset_pin_key,
                'reset_%s_exp_date' % password_type: reset_pin_exp_date,
            }
        )
    else:
        reset_pin_key = customer.reset_password_key
        logger.info(
            {
                'status': 'reset_%s_key_already_generated' % password_type,
                'email': email,
                'phone_number': phone_number,
                'customer': customer,
                'reset_%s_key' % password_type: reset_pin_key,
            }
        )
    if is_j1 or is_mf:
        if email:
            custom_send_reset_pin_email(
                email, reset_pin_key, new_julover=new_julover, customer=customer
            )
        else:
            send_reset_pin_sms(customer, phone_number, reset_pin_key)
    else:
        send_reset_password_email(email, reset_pin_key)


def custom_send_reset_pin_email(email, reset_pin_key, new_julover=False, customer=None):

    reset_pin_page_link = settings.RESET_PIN_JULO_ONE_LINK_HOST + reset_pin_key + '/'

    logger.info(
        {
            'status': 'reset_pin_page_link_created',
            'action': 'sending_email',
            'email': email,
            'reset_pin_page_link': reset_pin_page_link,
        }
    )

    time_now = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
    subject = "JULO: Reset PIN (%s) - %s" % (email, time_now)
    template = get_template('email/email_reset_pin.html')
    username = email.split("@")
    variable = {"link": reset_pin_page_link, "name": username[0]}
    html_content = template.render(variable)
    template_code = 'email_reset_pin'
    app = None
    message_id = None
    error_message = None
    status = 'error'

    if new_julover:
        template_code = None
        app = Application.objects.filter(email__iexact=email).last()
        subject, html_content = JuloverPageMapping.get_julover_page_content(
            title=JuloverPageConst.EMAIL_AT_190,
            application=app,
            reset_pin_key=reset_pin_key,
        )
    try:
        status, _, headers = get_julo_email_client().send_email(
            subject,
            html_content,
            email,
            settings.EMAIL_FROM,
        )
        if status == 202:
            status = 'sent_to_sendgrid'
            error_message = None
        message_id = headers['X-Message-Id']
    except Exception as e:
        error_message = str(e)
        if not isinstance(e, EmailNotSent):
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            logger.exception('reset_pin_send_email_failed, data={} | err={}'.format(customer, e))

    EmailHistory.objects.create(
        to_email=email,
        subject=subject,
        sg_message_id=message_id,
        template_code=template_code,
        application=app,
        customer=customer,
        status=str(status),
        error_message=error_message,
    )

    customer_pin_change_service = CustomerPinChangeService()
    customer_pin_change_service.update_email_status_to_sent(reset_pin_key)

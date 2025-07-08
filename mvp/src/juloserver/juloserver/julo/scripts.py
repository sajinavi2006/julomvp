from __future__ import print_function
from __future__ import division
from builtins import str
from time import sleep

from django.core.paginator import Paginator
from django.db.models import (
    signals,
    Prefetch,
)
from factory.django import mute_signals
from past.utils import old_div
from django.template.loader import render_to_string

from datetime import *
from juloserver.julo.models import *
from juloserver.minisquad.tasks import *
from juloserver.julo.formulas import *
from juloserver.julo.clients import get_julo_email_client
from juloserver.loan_refinancing.models import WaiverRequest
from juloserver.loan_refinancing.services.loan_related import get_unpaid_payments
from juloserver.apiv2.models import LoanRefinancingScore
from juloserver.account_payment.models import AccountPaymentNote
from juloserver.minisquad.models import SentToDialer
from juloserver.cootek.clients import get_julo_cootek_client
from juloserver.julo.models import CootekRobocall
from juloserver.pusdafil.tasks import task_report_new_user_registration, \
    task_report_new_borrower_registration, \
    task_report_new_application_registration, \
    task_report_new_loan_registration, \
    task_report_new_loan_approved, \
    task_report_new_loan_payment_creation
from juloserver.streamlined_communication.models import InAppNotificationHistory
from juloserver.collection_vendor.models import AgentAssignment
from juloserver.collection_vendor.models import CollectionVendorAssignment
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.formulas import determine_first_due_dates_by_payday
from juloserver.julo.constants import EmailDeliveryAddress


def retro_bca(loans):
    from juloserver.julo.utils import format_mobile_phone
    from juloserver.julo.services2.payment_method import get_application_primary_phone
    for loan in loans:
        mobile_phone_1 = get_application_primary_phone(loan.application)

        if not mobile_phone_1:
            print('Loan- {} does not have phone number'.format(loan.id))
            continue

        mobile_phone_1 = format_mobile_phone(mobile_phone_1)
        va_suffix = mobile_phone_1

        virtual_account = "".join([
                    '10994',
                    va_suffix
        ])

        PaymentMethod.objects.create(
            payment_method_code='10994',
            payment_method_name='Bank BCA',
            bank_code='014',
            customer=loan.customer,
            is_shown=True,
            is_primary=False,
            loan=loan,
            virtual_account=virtual_account
        )

        print('successfully create bca va for loan_id: {}'.format(loan.id))

def retro_maybank(loans):
    #add VA Maybank
    for loan in loans:
        virtual_account_suffix = VirtualAccountSuffix.objects.get(loan=loan)
        virtual_account = "".join([
            '782182',
            virtual_account_suffix.virtual_account_suffix
        ])
        exists = PaymentMethod.objects.filter(loan=loan, payment_method_name='Bank MAYBANK').first()
        if not exists:
            PaymentMethod.objects.create(
                payment_method_code='782182',
                payment_method_name='Bank MAYBANK',
                bank_code='016',
                loan=loan,
                virtual_account=virtual_account
                )
        loan.julo_bank_name = 'Bank MAYBANK'
        loan.julo_bank_account_number = virtual_account
        loan.save()


def retro_permata(loans):
    #add VA permata
    for loan in loans:
        virtual_account_suffix = VirtualAccountSuffix.objects.get(loan=loan)
        virtual_account = "".join([
            PaymentMethodCodes.PERMATA,
            virtual_account_suffix.virtual_account_suffix
        ])
        if not PaymentMethod.objects.filter(loan=loan, payment_method_name='Bank PERMATA').first():
            PaymentMethod.objects.create(
                payment_method_code=PaymentMethodCodes.PERMATA,
                payment_method_name='Bank PERMATA',
                bank_code='013',
                loan=loan,
                virtual_account=virtual_account
                )

def set_suffix_va(loan):
    #set virtual account suffix if loan can't add payment method Maybank or Permata
    with transaction.atomic():
        va_suffix_obj = VirtualAccountSuffix.objects.select_for_update().filter(
            loan=None, line_of_credit=None, account=None).order_by('id').first()
        if not va_suffix_obj:
            raise Exception('no va suffix available')
        va_suffix_obj.loan = loan
        va_suffix_obj.save()

def retro_bri(loan_ids):
    # add virtual account BRI
    from juloserver.julo.utils import format_mobile_phone
    from juloserver.julo.services2.payment_method import get_application_primary_phone
    for loan_id in loan_ids:
        loan = Loan.objects.get(pk=loan_id)
        mobile_phone_1 = get_application_primary_phone(loan.application)
        if not mobile_phone_1:
            print('Loan- {} does not have phone number'.format(loan.id))
            continue
        mobile_phone_1 = format_mobile_phone(mobile_phone_1)
        va_suffix = mobile_phone_1
        virtual_account = "".join([
                    '23454',
                    va_suffix
        ])
        PaymentMethod.objects.create(
            payment_method_code='234540',
            payment_method_name='Bank BRI',
            bank_code='002',
            customer=loan.customer,
            is_shown=True,
            is_primary=False,
            loan=loan,
            virtual_account=virtual_account
        )
        print('successfully create bri va for loan_id: {}'.format(loan.id))


def retro_cimb(loan_id):
    # add virtual account CIMB Niaga
    with transaction.atomic():
        loan = Loan.objects.get(pk=loan_id)
        PaymentMethod.objects.filter(loan_id = loan_id, is_primary = True).update(is_primary = False,is_affected=True)
        va = BankVirtualAccount.objects.filter(bank_code='022',loan_id=None).first()
        va.loan = loan
        va.save()
        PaymentMethod.objects.create(
                payment_method_code='50391',
                payment_method_name=va.bank_code.name,
                bank_code=va.bank_code_id,
                loan=loan,
                customer_id=loan.customer_id,
                virtual_account=va.virtual_account_number,
                is_primary=True,
                is_shown=True,
                is_affected=True
                )


def waive_principal(payment, waive_principal_amount, note):
    # to waive principal amount when requested by agent
    from juloserver.julo.services import process_received_payment, record_payment_transaction
    from juloserver.julo.utils import display_rupiah
    event_date = timezone.localtime(timezone.now()).date()
    due_amount_before = payment.due_amount
    payment_note = '[Add Event Waive Principal]\n\
                    amount: %s,\n\
                    date: %s,\n\
                    note: %s.' % (display_rupiah(waive_principal_amount),
                                  event_date.strftime('%d-%m-%Y'),
                                  note)
    try:
        with transaction.atomic():
            payment.due_amount -= waive_principal_amount
            payment.paid_amount += waive_principal_amount
            payment.paid_date = event_date
            payment.save(update_fields=['due_amount',
                                        'paid_amount',
                                        'udate',
                                        'paid_date'])
            payment_event = PaymentEvent.objects.create(payment=payment,
                                                        event_payment=waive_principal_amount,
                                                        event_due_amount=due_amount_before,
                                                        event_date=event_date,
                                                        event_type='waive_principal')
            PaymentNote.objects.create(
                note_text=payment_note,
                payment=payment)
            record_payment_transaction(
                payment, waive_principal_amount, due_amount_before, event_date,
                'borrower_bank')
            payment_event.update_safely(can_reverse=False)
            payment.refresh_from_db()
            if payment.due_amount == 0:  # change payment status to paid
                process_received_payment(payment)
    except JuloException as e:
        logger.info({
            'action': 'waive_principal_error',
            'payment_id': payment.id,
            'message': str(e)
        })
    message = "Payment event waive_principal success"
    return True, message


def cashback_adjustment(customer_id,amount):
    #To deduct cashback customer if they waive principal
    with transaction.atomic():
        event_date = timezone.localtime(timezone.now()).date()
        last_cashback = CustomerWalletHistory.objects.filter(customer_id=customer_id,latest_flag=True).last()
        CustomerWalletHistory.objects.filter(customer=customer_id).update(latest_flag=False)
        CustomerWalletHistory.objects.create(customer=last_cashback.customer,
                                                 application=last_cashback.application,
                                                 loan=last_cashback.loan,
                                                 wallet_balance_accruing=last_cashback.wallet_balance_accuring - amount,
                                                 wallet_balance_available=last_cashback.wallet_balance_available - amount,
                                                 wallet_balance_accruing_old=last_cashback.wallet_balance_accruing,
                                                 wallet_balance_available_old=last_cashback.wallet_balance_available,
                                                 change_reason='cashback_adjustment_waiver',
                                                 latest_flag=True,
                                                 event_date=event_date)


def send_data_to_centrix(is_assign_need = False):
    #Function to send data to centrix if at morning, no data on centrix campaign
    #is_assign_need is need only if not yet assigned.
    # from juloserver.collectionbucket.tasks import assign_collection_agent

    # if is_assign_need:
    #     assign_collection_agent()

    # upload_julo_t0_data_to_centerix.apply_async(countdown=5)
    # upload_julo_tminus1_data_to_centerix.apply_async(countdown=10)
    # upload_julo_tplus1_to_4_data_centerix.apply_async(countdown=15)
    # upload_julo_tplus5_to_10_data_centerix.apply_async(countdown=20)
    # upload_julo_b2_data_centerix.apply_async(countdown=25)
    # upload_julo_b2_s1_data_centerix.apply_async(countdown=30)
    # upload_julo_b2_s2_data_centerix.apply_async(countdown=35)
    # upload_julo_b3_data_centerix.apply_async(countdown=40)
    # upload_julo_b3_s1_data_centerix.apply_async(countdown=45)
    # upload_julo_b3_s2_data_centerix.apply_async(countdown=50)
    # upload_julo_b3_s3_data_centerix.apply_async(countdown=55)
    # upload_julo_b4_data_centerix.apply_async(countdown=60)
    # upload_julo_b4_s1_data_centerix.apply_async(countdown=65)
    # upload_ptp_agent_level_data_centerix.apply_async(countdown=70)
    # deprecated
    pass


def bypass_fdc(application_id):
    #to bypass application because of fdc when requested by ken
    from juloserver.julo.formulas.experiment import calculation_affordability
    from juloserver.julo.services import get_offer_recommendations
    application = Application.objects.get(pk=application_id)
    affordability,monthly_income = calculation_affordability(
        application.id, application.monthly_income, application.monthly_housing_cost,
        application.monthly_expenses, application.total_current_debt)
    recomendation_offers = get_offer_recommendations(
        application.product_line.product_line_code,
        application.loan_amount_request,
        application.loan_duration_request,
        affordability,
        application.payday,
        application.ktp,
        application.id,
    application.partner
    )
    if len(recomendation_offers['offers']) > 0:
        offer_data = recomendation_offers['offers'][0]
        product = ProductLookup.objects.get(pk=offer_data['product'])
        offer_data['product'] = product
        offer_data['application'] = application
        offer_data['is_approved'] = True
        # process change status 141-172 to create offer
        offer = Offer(**offer_data)
        # set default Skiptrace
        customer_phone = Skiptrace.objects.filter(customer_id=application.customer_id).order_by('id', '-effectiveness')
        for phone in customer_phone:
            phone.effectiveness = 0
            phone.save()
        with transaction.atomic():
            offer.save()
            process_application_status_change(application.id,
                ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                'fdc_pve_bypass_141')
            application.refresh_from_db()
            if application.application_status_id == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                status = process_application_status_change(application.id,
                    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
                    'fdc_pve_bypass_172')


def update_interest_amount(application_id, product_id):
    #script to change interest amount
    offer = Offer.objects.get(application_id=application_id)
    loan = offer.loan_set.first()
    product=ProductLookup.objects.get(pk=product_id)
    interest_rate = old_div(product.interest_rate,12)
    _,first_interest_amount,first_installment_amount = compute_adjusted_payment_installment(loan.loan_amount, loan.loan_duration, interest_rate, offer.cdate.date(), offer.first_payment_date)
    _,interest_amount,installment_amount = compute_payment_installment(loan.loan_amount, loan.loan_duration, interest_rate)
    offer.product_id=product_id
    offer.first_installment_amount=first_installment_amount
    offer.installment_amount_offer=installment_amount
    offer.save()
    loan.product_id=product_id
    loan.installment_amount=installment_amount
    loan.first_installment_amount=first_installment_amount
    loan.save()
    payments = loan.payment_set.all()
    payments.update(due_amount=installment_amount, installment_interest=interest_amount)
    payment = payments.first()
    payment.due_amount=first_installment_amount
    payment.installment_interest=first_interest_amount
    payment.save()


def delete_withdraw_transaction(withdraw_id, withdraw_amount):
    #script to delete lender withdrawal
    from juloserver.followthemoney.models import LenderBalanceCurrent
    from juloserver.followthemoney.models import LenderWithdrawal
    from juloserver.followthemoney.models import LenderTransactionMapping
    from django.db import transaction
    with transaction.atomic():
        lender_balance = LenderBalanceCurrent.objects.get(lender_id=1, pending_withdrawal__gte=withdraw_amount)
        lender_balance.pending_withdrawal -= withdraw_amount
        lender_balance.save()
        lender_mapping = LenderTransactionMapping.objects.get(lender_withdrawal_id=withdraw_id)
        lender_mapping.delete()
        withdrawal_request = LenderWithdrawal.objects.get(id=withdraw_id)
        withdrawal_request.delete()


def disbursement_step_1_initiated(application_id, new_status_code, change_reason, note):
    #to solve initiated disbursement on step 1
    from juloserver.julo.services import ApplicationHistoryUpdated
    from juloserver.julo.workflows2.handlers import execute_action
    from juloserver.julo.services import trigger_info_application_partner
    from juloserver.julo.models import Application
    from juloserver.julo.models import ApplicationNote
    app = Application.objects.get(pk=application_id)
    old_status_code = app.status
    new_status_code = new_status_code
    is_experiment=False
    workflow = app.workflow
    processed = execute_action(app, old_status_code, new_status_code, change_reason, note, workflow, 'pre')
    if processed:
        execute_action(app, old_status_code, new_status_code, change_reason, note, workflow, 'post')


def disbursement_stuck_step_1(disburse_id):
    #to solve only have step 1 completed
    from juloserver.disbursement.services import get_disbursement_process, get_disbursement_by_obj
    a = get_disbursement_process(disburse_id) ##use disburse_id
    a.disburse()


def bulk_retry_disburse(application_ids):
    #to application that stuck in 181
    from juloserver.disbursement.models import Disbursement as Db
    from juloserver.disbursement.models import BcaTransactionRecord as Btr
    from juloserver.julo.services import process_application_status_change
    apps = Application.objects.select_related('loan').filter(id__in=application_ids)
    app_170 = []
    app_181 = []
    app_180 = []
    btr_not_found = []
    for app in apps:
        print(app.id)
        if app.application_status_id != 181:
            print('app id %s not in 181 but in status %s' % (app.id, app.status))
            continue
        loan = app.loan
        db = Db.objects.get(pk=loan.disbursement_id)
        db.retry_times += 1
        db.save(update_fields=['retry_times', 'udate'])
        db.refresh_from_db()
        if db.method == 'Bca':
            btr = Btr.objects.filter(reference_id=db.external_id).last()
            if btr:
                btr.reference_id += str(db.retry_times)
                btr.save()
        process_application_status_change(app.id, 170, 'Legal agreement signed', 'bulk retry disburse from backend script')
        app.refresh_from_db()
        print(app.status)
        if app.application_status_id == 170:
            app_170.append(app.id)
        elif app.application_status_id == 181:
            app_181.append(app.id)
        elif app.application_status_id == 180:
            app_180.append(app.id)
    return app_170, app_181, app_180, btr_not_found


def delete_customer(app_id):
    #To delete customer if requested by ops agent
    with transaction.atomic():
        application = Application.objects.get(pk=app_id)
        isExist = application.customer.application_set.filter(application_status_id=180).exists()
        if isExist == False:
            user = User.objects.filter(username=application.ktp).last()
            if user:
                user.username = user.username[0:12] + '99' + user.username[-2:]
                user.save()
            new_ktp = application.ktp[0:12]+'99'+application.ktp[-2:]
            new_email= 'deleted.' + application.email
            new_phone= application.mobile_phone_1 + '54321' if application.mobile_phone_1 else ''
            new_bank_account= application.bank_account_number+'54321' if application.bank_account_number else ''
            new_name= 'deleted.' + application.fullname if application.fullname else ''
            customer = Customer.objects.get(pk=application.customer_id)
            customer.update_safely(email=new_email, nik=new_ktp, phone=new_phone, fullname=new_name)
            [application.update_safely(email=new_email, ktp=new_ktp, mobile_phone_1= new_phone ,bank_account_number = new_bank_account,
                fullname=new_name,application_status_id = 106) for application in customer.application_set.all()]
            [st.skiptracehistory_set.all().delete() for st in customer.skiptrace_set.all()]
            customer.skiptrace_set.all().delete()
            devices = customer.device_set.all()
            for device in devices:
                device.gcm_reg_id=device.gcm_reg_id.split(':')[0] + ':deleted'
                device.android_id = device.android_id + '54321'
                device.save()
            force_logout_action = CustomerAppAction.objects.get_or_none(customer=customer,action="force_logout",is_completed=False)
            if not force_logout_action:
                CustomerAppAction.objects.create(customer=customer, action='force_logout', is_completed=False)
        else:
            print('gagal menghapus {}'.format(app_id))


def delete_application(application_id):
    #to delete application
    with transaction.atomic():
        application = Application.objects.get(pk=application_id)
        application.customer_id = 1000203289
        application.save()
        application.refresh_from_db()
        new_ktp = application.ktp[0:12]+'99'+application.ktp[-2:]
        new_email= application.customer.email
        new_phone= application.mobile_phone_1 + '54321' if application.mobile_phone_1 else ''
        new_bank_account= application.bank_account_number+'54321' if application.bank_account_number else ''
        application.update_safely(email=new_email, ktp=new_ktp, mobile_phone_1=new_phone, bank_account_number = new_bank_account,application_status_id=106)


def change_nik(app_id, new_ktp):
    application = Application.objects.get(pk=app_id)
    print(("old:", application.ktp, " New KTP:", new_ktp))
    customer = application.customer
    customer.update_safely(nik=new_ktp)
    # update ktp of all application for customer
    customer.application_set.update(ktp=new_ktp)
    user_obj = customer.user
    if user_obj and user_obj.username.isnumeric():
        user_obj.username = new_ktp
        user_obj.save()


def change_email(app_id, email):
    with transaction.atomic():
        app = Application.objects.get(pk=app_id)
        print(("old:", app.email, " New email:", email))
        customer = app.customer
        customer.update_safely(email=email)
        # update email of all application for customer
        customer.application_set.update(email=email)
        if customer.user.email:
            customer.user.email = email
            customer.user.save()


def change_name(app_id, name):
    app = Application.objects.get(pk=app_id)
    print(("old:", app.fullname, " New :", name))
    app.fullname = name
    app.save()
    customer = app.customer
    customer.fullname = name
    customer.save()


def retroload_blank_bucket_name_for_special_cohort():
    blank_bucket_waiver_request = WaiverRequest.objects.filter(bucket_name__isnull=True)

    for waiver in blank_bucket_waiver_request:
        loan_refinancing_score = LoanRefinancingScore.objects.filter(loan=waiver.loan).last()

        if loan_refinancing_score:
            bucket_name = loan_refinancing_score.bucket
            waiver.bucket_name = bucket_name
            waiver.save()
            continue

        unpaid_payments = get_unpaid_payments(waiver.loan, order_by='payment_number')
        if unpaid_payments:
            payment = unpaid_payments.first()
            bucket_name = 'Bucket {}'.format(payment.bucket_number)
            waiver.bucket_name = bucket_name
            waiver.save()
            continue

        last_payment = Payment.objects.normal().filter(loan=waiver.loan).order_by('payment_number').last()
        if last_payment:
            bucket_name = 'Bucket {}'.format(last_payment.bucket_number)
            waiver.bucket_name = bucket_name
            waiver.save()


def retrofix_data_for_non_contacted_bucket():
    excluded_bucket_level_loan_ids = SkiptraceHistory.objects.filter(
        excluded_from_bucket=True
    ).order_by('loan', '-cdate').distinct('loan').values_list('loan', flat=True)

    for loan_id in excluded_bucket_level_loan_ids:
        excluded_bucket = SkiptraceHistory.objects.filter(
            loan_id=loan_id,
            excluded_from_bucket=True
        ).first()

        # update all payment for all bucket
        excluded_bucket_level_payment = SkiptraceHistory.objects.filter(
            loan_id=loan_id,
            cdate__gte=excluded_bucket.cdate,
            payment_id__isnull=False
        ).update(excluded_from_bucket=True)

        list_payment_ids = SkiptraceHistory.objects.filter(loan_id=loan_id).values_list('payment_id', flat=True)
        loan = Loan.objects.get(pk=loan_id)
        oldest_unpaid_payment = loan.get_oldest_unpaid_payment()

        if oldest_unpaid_payment:
            if oldest_unpaid_payment.id in list_payment_ids:
                continue

            latest_skiptrace_history = SkiptraceHistory.objects.filter(
                loan_id=loan_id,
                payment_id__isnull=False
            ).order_by('id').last()

            if latest_skiptrace_history:
                note = "retrofix data, changes oldest payment from {} to  {} ".format(
                    latest_skiptrace_history.payment_id,
                    oldest_unpaid_payment.id)

                latest_skiptrace_history.payment.id = oldest_unpaid_payment.id
                latest_skiptrace_history.note = note
                latest_skiptrace_history.save()


def retrofix_data_in_email_warning_letter(offset=0, limit=100, template_code="'warning_letter1.html'"):
    from django.db import connection

    query = """select email_history_id
               from ops.email_history eh
               where template_code = {template_code}
               and cdate::date >= '2020-01-01'
               and eh.payment_id is null
               order by eh.email_history_id asc
               limit {limit} offset {offset}""".format(limit=limit, offset=offset, template_code=template_code)

    with connection.cursor() as cursor:
        cursor.execute(query)
        retroload_data = cursor.fetchall()

    if retroload_data:

        if template_code == "'warning_letter1.html'":
                warning_number = 1
        elif template_code == "'warning_letter2.html'":
                warning_number = 2
        elif template_code == "'warning_letter3.html'":
                warning_number = 3

        for id in retroload_data:
            email_history = EmailHistory.objects.get(pk=('{}'.format(id[0])))

            warning_letter_history = WarningLetterHistory.objects.filter(
                customer=email_history.customer,
                warning_number=warning_number,
                cdate__date=email_history.cdate.date(),
            ).last()

            if warning_letter_history:
                payment_id = warning_letter_history.payment_id
                email_history.update_safely(payment_id=payment_id)
            else:
                loan = Loan.objects.filter(application=email_history.application).last()
                payment = Payment.objects.filter(
                    loan_id=loan.id,
                    due_date__lt=email_history.cdate.date()).last()

                if payment:
                    email_history.update_safely(payment_id=payment.id)


def retroload_account_payment_note():
    payment_notes_j1 = PaymentNote.objects.filter(
        account_payment__isnull=False,
        payment__isnull=True
    ).order_by('cdate')

    for payment_note in payment_notes_j1:
        cdate = payment_note.cdate.date()
        note = payment_note.note_text + ';' + str(cdate)
        AccountPaymentNote.objects.create(
            account_payment=payment_note.account_payment,
            note_text=note,
            added_by=payment_note.added_by
        )


def retroload_ptp_account_payment_j1():
    account_j1_ptps = PTP.objects.filter(
        loan__account_id__isnull=False,
        account_payment_id__isnull=True,
        payment__account_payment_id__isnull=False
    )

    for ptp in account_j1_ptps:
        account_payment = ptp.payment.account_payment
        account = ptp.loan.account
        if account_payment:
            existing_ptp = PTP.objects.filter(
                account_payment=account_payment
            )
            if existing_ptp:
                continue

        ptp.account_payment = account_payment
        ptp.account = account
        ptp.loan_id = None
        ptp.payment_id = None
        ptp.save()


def retroload_sent_to_dialer_j1_account():
    incorrectly_send_as_mtl = SentToDialer.objects.filter(
        loan__account_id__isnull=False,
        loan_id__isnull=False
    )

    for j1_data in incorrectly_send_as_mtl:
        loan = j1_data.loan
        account = loan.account
        payment = j1_data.payment
        account_payment = payment.account_payment
        cdate = j1_data.cdate
        if account_payment:
            existing_data = SentToDialer.objects.filter(
                account_payment=account_payment,
                cdate__date=cdate.date()
            )

            if existing_data:
                j1_data.delete()
                continue

            j1_data.payment_id = None
            j1_data.loan_id = None
            j1_data.account_payment = account_payment
            j1_data.account = account
            j1_data.save()

        if account and not account_payment:
            j1_data.delete()


def retroload_skiptrace_history():
    account_j1_skiptrace_history = SkiptraceHistory.objects.filter(
        loan_id__isnull=False,
        loan__account_id__isnull=False,
        payment_id__isnull=False
    )

    account_j1_skiptrace_history.delete()


def retroload_cancelled_cootek():
    cootek_datas = CootekRobocall.objects.filter(
        intention__in=['A', 'C', '--'],
        call_status='cancelled'
    )

    cootek_client = get_julo_cootek_client()

    for cootek in cootek_datas:
        if cootek.payment:
            task_details = cootek_client.get_task_details(cootek.task_id)
            task_details = task_details['detail']

            for detail in task_details:
                payment_id = int(detail['Comments'])
                call_status = detail['Status']
                if payment_id == cootek.payment_id:
                    cootek.call_status = call_status
                    cootek.save()

        if cootek.account_payment:
            task_details = cootek_client.get_task_details(cootek.task_id)
            task_details = task_details['detail']

            for detail in task_details:
                account_payment_id = int(detail['Comments'])
                call_status = detail['Status']
                if account_payment_id == cootek.account_payment_id:
                    cootek.call_status = call_status
                    cootek.save()

        if cootek.statement:
            task_details = cootek_client.get_task_details(cootek.task_id)
            task_details = task_details['detail']

            for detail in task_details:
                statement_id = int(detail['Comments'])
                call_status = detail['Status']
                if statement_id == cootek.statement_id:
                    cootek.call_status = call_status
                    cootek.save()


def retroload_data_that_should_send_to_pusdafil():

    if settings.ENVIRONMENT != 'prod':
        return

    # reg_pengguna
    user_ids = Application.objects.filter(
        fullname__isnull=False,
        application_status__gte=ApplicationStatusCodes.FORM_PARTIAL).distinct(
            'customer_id').values_list(
                'customer__user_id', flat=True).order_by('-customer_id', '-customer__user_id')

    for user_id in user_ids:
        task_report_new_user_registration.apply_async(
            (user_id,), queue='application_pusdafil', routing_key='application_pusdafil')

    # reg_borrower
    customer_ids = Application.objects.filter(
        ktp__isnull=False,
        fullname__isnull=False,
    ).values_list('customer_id', flat=True).order_by('-customer_id')

    for customer_id in customer_ids:
        task_report_new_borrower_registration.apply_async(
            (customer_id,), queue='application_pusdafil', routing_key='application_pusdafil')

    # pengajuan_pinjaman
    app_status = [ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                  ApplicationStatusCodes.LOC_APPROVED]
    application_ids = Application.objects.filter(
        application_status__in=app_status
    ).values_list('id', flat=True).order_by('-id')

    for application_id in application_ids:
        task_report_new_application_registration.apply_async(
            (application_id,), queue='application_pusdafil', routing_key='application_pusdafil')

    # pengajuan_pemberian_pinjaman
    # transaksi_pinjam_meminjam
    mtl_loan_ids = Loan.objects.filter(
        application__application_status_id__in=app_status,
        loan_status__gte=LoanStatusCodes.CURRENT
    ).values_list('id', flat=True).order_by('id')

    j1_loan_ids = Loan.objects.filter(
        account__application__application_status_id__in=app_status,
        loan_status__gte=LoanStatusCodes.CURRENT
    ).values_list('id', flat=True).order_by('id')

    loan_ids = []
    loan_ids.extend(mtl_loan_ids)
    loan_ids.extend(j1_loan_ids)

    for loan_id in loan_ids:
        task_report_new_loan_registration.apply_async(
            (application_id,), queue='application_pusdafil', routing_key='application_pusdafil')
        task_report_new_loan_approved.apply_async(
            (application_id,), queue='application_pusdafil', routing_key='application_pusdafil')

    # pembayaran_pinjaman
    payment_ids = PaymentEvent.objects.filter(
        event_type='payment'
    ).order_by('-cdate').values_list('payment_id', flat=True)

    for payment_id in payment_ids:
        task_report_new_loan_payment_creation.apply_async(
            (payment_id,), queue='application_pusdafil', routing_key='application_pusdafil')


def send_lebaran_2021_promo_email(customer_id, bucket, overdue_amount, total_due_amount,
                                  payment_id=None, account_payment_id=None):
    customer = Customer.objects.get(pk=customer_id)
    application = customer.application_set.last()

    context = {
        "overdue_amount": overdue_amount,
        "total_due_amount": total_due_amount
    }

    if bucket == 5:
        template_code = 'lebaran21_bucket5.html'
    elif bucket == 4:
        template_code = 'lebaran21_bucket4.html'
    elif bucket == 3:
        template_code = 'lebaran21_bucket3.html'
    elif bucket == 2:
        template_code = 'lebaran21_bucket2.html'
    elif bucket == 1:
        template_code = 'lebaran21_bucket1_template2.html'
    else:
        template_code = 'lebaran21_bucket1_template1.html'

    reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
    email_from = EmailDeliveryAddress.COLLECTIONS_JTF
    name_from = 'JULO'

    subject = 'Bayar Angsuran Anda Sekarang dan Dapatkan Diskon Besar-besaran!'
    email_client = get_julo_email_client()
    message = render_to_string(template_code, context=context)
    status, body, headers = email_client.send_email(
        subject=subject,
        content=message,
        email_to=application.email,
        email_from=email_from,
        email_cc=None,
        name_from=name_from,
        reply_to=reply_to,
    )

    EmailHistory.objects.create(
        application=application,
        customer=customer,
        sg_message_id=headers['X-Message-Id'],
        status=str(status),
        to_email=application.email,
        subject=subject,
        message_content=message,
        template_code=template_code,
        payment_id=payment_id,
        account_payment_id=account_payment_id
    )


def retrofix_inapp_notification_history_moengage():
    InAppNotificationHistory.objects.filter(
        template_code='MKT_Inapp_Fraud Caution rev<::>0<::>1'
    ).update(template_code='MKT_Inapp_Fraud Caution rev')

    InAppNotificationHistory.objects.filter(
        template_code='J1x190_InApp<::>0<::>1'
    ).update(template_code='J1x190_InApp')

    InAppNotificationHistory.objects.filter(
        template_code='MKT_Inapp_Data Privacy<::>0<::>1'
    ).update(template_code='MKT_Inapp_Data Privacy')

    InAppNotificationHistory.objects.filter(
        template_code='Duplicate - Promo190<::>0<::>1'
    ).update(template_code='Duplicate - Promo190')

    InAppNotificationHistory.objects.filter(
        template_code='MKT_InApp_Retarget AvaiLimit Pulsa_16 Mar 2021 rev2<::>0<::>1'
    ).update(template_code='MKT_InApp_Retarget AvaiLimit Pulsa_16 Mar 2021 rev2')



def retrofix_double_vendor_assigment():
    active_vendor_assignments_for_non_j1 = CollectionVendorAssignment.objects.filter(
        payment__isnull=False
    ).values('payment_id', 'is_active_assignment').annotate(count_active=Count('payment_id')).filter(
        count_active__gt=1,
        is_active_assignment=True,
    )

    for data in active_vendor_assignments_for_non_j1:
        payment_id = data['payment_id']
        collection_vendor = CollectionVendorAssignment.objects.filter(
            payment_id=payment_id,
            is_active_assignment=True
        )
        duplicate_vendor_assigment = \
        collection_vendor.values('vendor_id').annotate(count_vendor=Count('vendor_id')).filter(
            count_vendor__gt=1
        )

        # same vendor
        if duplicate_vendor_assigment:
            collection_vendor.first().delete()
            continue

        # different_vendor
        collection_vendor.exclude(
            is_transferred_from_other=True
        ).update(is_active_assignment=False)

    active_vendor_assignments_for_j1 = CollectionVendorAssignment.objects.filter(
        account_payment__isnull=False
    ).values('account_payment_id', 'is_active_assignment').annotate(count_active=Count('account_payment_id')).filter(
        count_active__gt=1,
        is_active_assignment=True,
    )

    for data in active_vendor_assignments_for_j1:
        account_payment_id = data['account_payment_id']
        collection_vendor = CollectionVendorAssignment.objects.filter(
            account_payment_id=account_payment_id,
            is_active_assignment=True
        )
        duplicate_vendor_assigment = \
        collection_vendor.values('vendor_id').annotate(count_vendor=Count('vendor_id')).filter(
            count_vendor__gt=1
        )

        # same vendor
        if duplicate_vendor_assigment:
            collection_vendor.first().delete()
            continue

        # different_vendor
        collection_vendor.exclude(
            is_transferred_from_other=True
        ).update(is_active_assignment=False)


def retrofix_double_agent_assigment():
    active_agent_assigment_for_non_j1 = AgentAssignment.objects.filter(
        payment__isnull=False
    ).values('payment_id', 'is_active_assignment').annotate(count_active=Count('payment_id')).filter(
        count_active__gt=1,
        is_active_assignment=True,
    )

    for data in active_agent_assigment_for_non_j1:
        payment_id = data['payment_id']
        agent_assignment = AgentAssignment.objects.filter(
            payment_id=payment_id,
            is_active_assignment=True
        )

        last_agent_assignment = agent_assignment.last()
        agent_assignment.exclude(id__in=[last_agent_assignment.id]).delete()

    active_agent_assigment_for_j1 = AgentAssignment.objects.filter(
        account_payment__isnull=False
    ).values('account_payment_id', 'is_active_assignment').annotate(count_active=Count('account_payment_id')).filter(
        count_active__gt=1,
        is_active_assignment=True,
    )

    for data in active_agent_assigment_for_j1:
        account_payment_id = data['account_payment_id']
        agent_assignment = AgentAssignment.objects.filter(
            account_payment_id=account_payment_id,
            is_active_assignment=True
        )

        last_agent_assignment = agent_assignment.last()
        agent_assignment.exclude(id__in=[last_agent_assignment.id]).delete()


def retro_fix_due_date(application):
    account = application.account
    if not account:
        return
    loans = account.loan_set.filter(loan_status_id__gte=220).order_by('fund_transfer_ts')
    first_due_date = determine_first_due_dates_by_payday(
            application.payday, account.cdate, application.product_line_code,)
    cycle_day = first_due_date.day
    first_loan = loans.first()
    account.update_safely(cycle_day=cycle_day)
    payment_first_due_date = first_loan.payment_set.first().due_date
    account_payments = account.accountpayment_set.order_by('id')
    with transaction.atomic():
        for index, account_payment in enumerate(account_payments):
            acp_due_date = payment_first_due_date + relativedelta(months=index, day=cycle_day)
            account_payment.update_safely(
                due_amount=0,
                principal_amount=0,
                interest_amount=0,
                late_fee_amount=0,
                late_fee_applied=0,
                paid_interest=0,
                paid_principal=0,
                paid_late_fee=0,
                status_id=330,
                due_date=acp_due_date)
        account_payments = AccountPayment.objects.filter(account_id=account.id).order_by('due_date')
        for loan in loans:
            first_payment_date = determine_first_due_dates_by_payday(application.payday,
                                                                     loan.fund_transfer_ts.date(),
                                                                     application.product_line_code)
            first_payment_date = first_payment_date + relativedelta(day=cycle_day)
            if (first_payment_date - loan.fund_transfer_ts.date()).days < 15:
                first_payment_date = first_payment_date + relativedelta(months=1)
            for idx, payment in enumerate(loan.payment_set.all().order_by("id")):
                real_due_date = first_payment_date + relativedelta(months=idx)
                account_payment = account_payments.filter(due_date__month=real_due_date.month).first()
                if not account_payment:
                    account_payment = AccountPayment.objects.create(
                        account=loan.account,
                        late_fee_amount=0,
                        due_date=real_due_date,
                        status_id=330,
                    )
                account_payment.update_safely(
                    due_amount=account_payment.due_amount + payment.due_amount,
                    principal_amount=account_payment.principal_amount + payment.installment_principal,
                    interest_amount=account_payment.interest_amount + payment.installment_interest,
                    late_fee_amount=account_payment.late_fee_amount + payment.late_fee_amount,
                    late_fee_applied=payment.late_fee_applied,
                    paid_interest=account_payment.paid_interest + payment.paid_interest,
                    paid_principal=account_payment.paid_principal + payment.paid_principal,
                    paid_late_fee=account_payment.paid_late_fee + payment.paid_late_fee)
                if account_payment.due_amount > 0:
                    account_payment.change_status(310)
                    account_payment.save()
                if payment.payment_status_id < 330:
                    payment.due_date=account_payment.due_date
                payment.account_payment = account_payment
                payment.save()


def retrofix_intelix_call_result(intelix_call_result):
    dialer_task = DialerTask.objects.create(
            type=DialerTaskStatus.INITIATED
    )

    create_history_dialer_task_event(param=dict(dialer_task=dialer_task))

    create_history_dialer_task_event(
            param=dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.DOWNLOADED,
                data_count=1
            )
    )
    skiptrace_result_choices = SkiptraceResultChoice.objects.all().values_list('id', 'name')

    store_call_result(intelix_call_result, dialer_task.id, skiptrace_result_choices)

    create_history_dialer_task_event(
            param=dict(dialer_task=dialer_task, status=DialerTaskStatus.SUCCESS,
                       data_count=1)
    )


def store_call_result(call_result, dialer_task_id, skiptrace_result_choices):
    dialer_task = DialerTask.objects.get(pk=dialer_task_id)
    loan_id = call_result.get('LOAN_ID')
    account_id = call_result.get('ACCOUNT_ID')
    start_ts = datetime.strptime(call_result.get('START_TS'), '%Y-%m-%d %H:%M:%S')
    end_ts = datetime.strptime(call_result.get('END_TS'), '%Y-%m-%d %H:%M:%S')
    call_status = call_result.get('CALL_STATUS')
    loan_status_id = None
    payment_status_id = None
    account_payment_status_id = None
    payment_id = None
    account_payment_id = None

    # loan_id is primary key for non J1 customers
    if loan_id:
        loan = Loan.objects.select_related('application', 'loan_status').get(pk=loan_id)
        is_julo_one = False

        if not loan:
            create_failed_call_results.delay(
                dict(
                    dialer_task=dialer_task,
                    error='loan id : {} is not found on database'.format(call_result.get('LOAN_ID')),
                    call_result=json.dumps(call_result)
                )
            )
            return

        application = loan.application
        loan_status_id = loan.loan_status.status_code
        payment = loan.payment_set.get_or_none(id=call_result.get('PAYMENT_ID'))

        call_result_exists = SkiptraceHistory.objects.filter(
            loan=loan,
            start_ts=start_ts
        )

        if call_result_exists:
            return

        if not payment:
            create_failed_call_results.delay(
                dict(
                    dialer_task=dialer_task,
                    error='payment id : {} is not found on database with loan id : '
                          '{}'.format(call_result.get('PAYMENT_ID'), loan.id),
                    call_result=json.dumps(call_result)
                )
            )
            return

        payment_status_id = payment.payment_status.status_code
        payment_id = payment.id

    # account_id is primary key for J1 customer
    if account_id:
        account = Account.objects.get_or_none(pk=account_id)
        is_julo_one = True
        if not account:
            create_failed_call_results.delay(
                dict(
                    dialer_task=dialer_task,
                    error='account id : {} is not found on database'.format(call_result.get(
                        'ACCOUNT_ID')),
                    call_result=json.dumps(call_result)
                )
            )
            return

        application = account.customer.application_set.last()
        account_payment = account.accountpayment_set.get_or_none(id=call_result.get(
            'ACCOUNT_PAYMENT_ID'))

        call_result_exists = SkiptraceHistory.objects.filter(
            account=account,
            start_ts=start_ts
        )

        if call_result_exists:
            return

        if not account_payment:
            create_failed_call_results.delay(
                dict(
                    dialer_task=dialer_task,
                    error='account payment id : {} is not found on database with account id : '
                          '{}'.format(call_result.get('ACCOUNT_PAYMENT_ID'), account.id),
                    call_result=json.dumps(call_result)
                )
            )
            return

        account_payment_status_id = account_payment.status_id
        account_payment_id = account_payment.id

    mapping_key = call_status.lower()
    if mapping_key not in IntelixResultChoiceMapping.MAPPING_STATUS:
        julo_skiptrace_result_choice = None
    else:
        julo_skiptrace_result_choice = IntelixResultChoiceMapping.MAPPING_STATUS[mapping_key]

    skip_result_choice_id = None
    status_group = None
    status = None
    for id, name in skiptrace_result_choices:
        if julo_skiptrace_result_choice == name:
            skip_result_choice_id = id
            status_group, status = construct_status_and_status_group(julo_skiptrace_result_choice)

    if not skip_result_choice_id:
        create_failed_call_results.delay(
            dict(
                dialer_task=dialer_task,
                error='Invalid skip_result_choice with value {}'.format(call_status),
                call_result=json.dumps(call_result)
            )
        )
        return

    agent_user = User.objects.filter(username=call_result.get('AGENT_NAME').lower()).last()
    agent_name = None

    if agent_user:
        agent_name = agent_user.username

    ptp_amount = call_result.get('PTP_AMOUNT')
    ptp_date = call_result.get('PTP_DATE')
    phone = call_result.get('PHONE_NUMBER')
    skiptrace = Skiptrace.objects.filter(
        phone_number=format_e164_indo_phone_number(phone),
        customer=application.customer).last()
    notes = call_result.get('NOTES')

    with transaction.atomic():
        if not skiptrace:
            skiptrace = Skiptrace.objects.create(
                phone_number=format_e164_indo_phone_number(phone),
                customer=application.customer,
                application=application)

        ptp_notes = ''
        if ptp_amount and ptp_date:
            if agent_user:
                ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
                if not is_julo_one:
                    payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
                    ptp_create(payment, ptp_date, ptp_amount, agent_user, is_julo_one)
                else:
                    account_payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
                    ptp_create(account_payment, ptp_date, ptp_amount, agent_user, is_julo_one)
            else:
                create_failed_call_results.delay(
                    dict(
                        dialer_task=dialer_task,
                        error="invalid because not found agent name {} for this "
                              "PTP".format(call_result.get('AGENT_NAME')),
                        call_result=json.dumps(call_result)
                    )
                )
                return

        if notes or ptp_notes:
            if not is_julo_one:
                PaymentNote.objects.create(
                    note_text='{};{}'.format(ptp_notes, notes),
                    payment=payment,
                    added_by=agent_user
                )
            else:
                AccountPaymentNote.objects.create(
                    note_text='{};{}'.format(ptp_notes, notes),
                    account_payment=account_payment,
                    added_by=agent_user
                )

        skiptrace_history = SkiptraceHistory.objects.create(
            start_ts=start_ts,
            end_ts=end_ts,
            application_id=application.id,
            application_status=application.status,
            skiptrace_id=skiptrace.id,
            call_result_id=skip_result_choice_id,
            spoke_with=call_result.get('SPOKE_WITH'),
            non_payment_reason=call_result.get('NON_PAYMENT_REASON'),
            callback_time=call_result.get('CALLBACK_TIME'),
            agent=agent_user,
            agent_name=agent_name,
            notes=notes,
            status_group=status_group,
            status=status,
            caller_id=call_result.get('CALLER_ID'),
            dialer_task_id=dialer_task.id,
            source='CRM'
            )

        if skiptrace_history:
            if not is_julo_one:
                skiptrace_history.loan_id = loan_id
                skiptrace_history.loan_status = loan_status_id
                skiptrace_history.payment_id = payment_id
                skiptrace_history.payment_status = payment_status_id
            else:
                skiptrace_history.account_payment_id = account_payment_id
                skiptrace_history.account_payment_status_id = account_payment_status_id
                skiptrace_history.account_id = account_id

            skiptrace_history.save()


def retrofix_customer_that_did_not_have_primary_payment_method():
    primary_payment_method = PaymentMethod.objects.filter(
        is_primary=True,
        customer_id__isnull=False).distinct('customer_id')

    primary_customer_ids = primary_payment_method.values_list('customer_id', flat=True)

    payment_methods = PaymentMethod.objects.filter(
        customer_id__isnull=False).exclude(customer_id__in=primary_customer_ids).distinct('customer_id')

    for payment_method in payment_methods.iterator():
        customer = payment_method.customer
        application = customer.application_set.last()
        bca_payment_method = None
        permata_payment_method = None

        if application and application.bank_name == 'BANK CENTRAL ASIA, Tbk (BCA)':
            bca_payment_method = PaymentMethod.objects.filter(
                customer=customer,
                bank_code=BankCodes.BCA,
                is_shown=True
            ).last()

            if bca_payment_method:
                bca_payment_method.update_safely(is_primary=True)
                continue

        permata_payment_method = PaymentMethod.objects.filter(
            customer=customer,
            payment_method_code='851598'
        ).last()

        if permata_payment_method:
            permata_payment_method.update_safely(
                is_primary=True,
                is_shown=True)
            continue

        latest_payment_method = PaymentMethod.objects.filter(
            customer=customer,
            is_shown=True
        ).last()

        if latest_payment_method:
            latest_payment_method.update_safely(is_primary=True)

    primary_payment_method.update(is_shown=True)


def delete_customer_qc(app_id, batch):
    # delete customer for internal QC, please filled batch using string
    with transaction.atomic():
        application = Application.objects.get(pk=app_id)
        isExist = application.customer.application_set.filter(application_status_id=180).exists()
        if not isExist:
            user = User.objects.filter(username=application.ktp).last()
            if user:
                user.username = batch + application.ktp[-14:]
                user.save()
            new_ktp = batch + application.ktp[-14:]
            new_email = 'qc' + batch + application.email
            new_phone = '081317782065'
            new_bank_account = '5425202917'
            new_bank = 'BANK CENTRAL ASIA, Tbk (BCA)'
            new_bank_name = 'JULO'
            customer = Customer.objects.get(pk=application.customer_id)
            customer.update_safely(email=new_email, nik=new_ktp, phone=new_phone)
            [application.update_safely(email=new_email, ktp=new_ktp, mobile_phone_1=new_phone,
                                       bank_account_number=new_bank_account,
                                       application_status_id=106, mobile_phone_2=new_phone,
                                       spouse_mobile_phone=new_phone, kin_mobile_phone=new_phone,
                                       company_phone_number=new_phone,
                                       close_kin_mobile_phone=new_phone, name_in_bank=new_bank_name) for application in
             customer.application_set.all()]
            [st.skiptracehistory_set.all().delete() for st in customer.skiptrace_set.all()]
            customer.skiptrace_set.all().delete()
            devices = customer.device_set.all()
            for device in devices:
                device.gcm_reg_id = 'Julo Testing - Internal QC'
                device.android_id = 'Julo Testing - Internal QC'
                device.save()
            force_logout_action = CustomerAppAction.objects.get_or_none(customer=customer, action="force_logout",
                                                                        is_completed=False)
            if not force_logout_action:
                CustomerAppAction.objects.create(customer=customer, action='force_logout', is_completed=False)
        else:
            print('gagal menghapus {}'.format(app_id))


@mute_signals(signals.post_save, signals.pre_save, signals.post_init)
def hotfix_skiptrace_empty_customer_fullname(
    application_id=None, is_force=False, per_page=200, relative_from=relativedelta(months=3)
):
    """
    set `is_force` to `True` to update the existing data in skiptrace if exists.
    """
    now = timezone.localtime(timezone.now())
    query = Application.objects.get_queryset()

    if application_id:
        query = query.filter(id=application_id)
    else:
        query = query.filter(
            Q(customer__fullname__isnull=True) | Q(customer__fullname=''),
            Q(mobile_phone_1__isnull=False) & ~Q(mobile_phone_1=''),
            Q(cdate__lte=now),
        ).exclude(
            Q(fullname__isnull=True),
            Q(fullname=''),
        ).order_by('-cdate')

    if relative_from:
        from_datetime = now - relative_from
        query = query.filter(cdate__gt=from_datetime)

    skiptrace_sources = (
        'mobile_phone_1',
        'mobile_phone_2'
    )

    paginator = Paginator(query, per_page)
    total_data = paginator.count
    process_idx = 0
    print('Total {} applications'.format(total_data))
    for page in paginator.page_range:
        applications = paginator.page(page).object_list
        for application in applications:
            print('Processing {}/{}:'.format(process_idx, total_data), end=' ')
            customer = application.customer

            skiptraces = customer.skiptrace_set.filter(
                contact_source__in=skiptrace_sources
            )
            skiptrace_dict = {
                'mobile_phone_1': None,
                'mobile_phone_2': None,
            }

            for skiptrace in skiptraces.all():
                if skiptrace.contact_source in skiptrace_dict:
                    skiptrace_dict[skiptrace.contact_source] = skiptrace

            processed_sources = []
            for contact_source in skiptrace_dict:
                phone_number = getattr(application, contact_source)
                if not phone_number:
                    continue

                if not skiptrace_dict[contact_source]:
                    processed_sources.append(contact_source)
                    Skiptrace.objects.create(
                        customer=application.customer,
                        application=application,
                        contact_source=contact_source,
                        phone_number=format_e164_indo_phone_number(phone_number),
                        contact_name=application.fullname,
                    )
                elif is_force:
                    processed_sources.append(contact_source)
                    skiptrace_dict[contact_source].update_safely(
                        customer=application.customer,
                        application=application,
                        contact_source=contact_source,
                        phone_number=format_e164_indo_phone_number(phone_number),
                        contact_name=application.fullname,
                    )

            process_idx += 1
            print('Processed ', application.id, customer.id, processed_sources)
            sleep(0.1)

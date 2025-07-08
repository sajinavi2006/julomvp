from builtins import str

from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.streamlined_communication.constant import CardProperty
from juloserver.streamlined_communication.models import StreamlinedCommunication
from django.utils import timezone
from django.db.models import Q

from juloserver.streamlined_communication.utils import add_thousand_separator, format_date_indo

from juloserver.julo.services2.high_score import feature_high_score_full_bypass
from juloserver.sdk.services import is_customer_has_good_payment_histories
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform
)
from juloserver.streamlined_communication.services import format_info_card_for_android, \
    is_already_have_transaction, is_info_card_expired
from juloserver.streamlined_communication.services import checking_rating_shown
from juloserver.application_flow.services import JuloOneService
from juloserver.apiv2.services import get_eta_time_for_c_score_delay
from juloserver.julo_privyid.services.privy_services import get_info_cards_privy


def construct_web_infocards(customer, application):
    should_rating_shown = checking_rating_shown(application)
    data = {
        'shouldRatingShown': should_rating_shown
    }
    is_document_submission = False
    card_due_date = '-'
    card_due_amount = '-'
    card_cashback_amount = '-'
    card_cashback_multiplier = '-'
    card_dpd = '-'
    loan = None if not hasattr(application, 'loan') else application.loan
    if application.is_julo_one():
        if application.account:
            loan = application.account.loan_set.last()
            if loan and loan.account:
                oldest_payment = loan.account.accountpayment_set.not_paid_active() \
                    .order_by('due_date') \
                    .first()
                if oldest_payment:
                    card_due_date = format_date_indo(oldest_payment.due_date)
                    card_due_amount = add_thousand_separator(str(oldest_payment.due_amount))
                    card_cashback_amount = oldest_payment.payment_set.last().cashback_earned
                    card_cashback_multiplier = oldest_payment.cashback_multiplier
                    card_dpd = oldest_payment.dpd

    available_context = {
        'card_title': application.bpk_ibu,
        'card_full_name': application.full_name_only,
        'card_first_name': application.first_name_only,
        'card_due_date': card_due_date,
        'card_due_amount': card_due_amount,
        'card_cashback_amount': card_cashback_amount,
        'card_cashback_multiplier': str(card_cashback_multiplier) + 'x',
        'card_dpd': card_dpd
    }

    web_infocards_queryset = StreamlinedCommunication.objects.filter(
        Q(partner__isnull=True) | Q(partner=application.partner), show_in_web=True
    )

    info_cards = []
    if application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL:
        if not hasattr(application, 'creditscore'):
            info_cards = list(web_infocards_queryset.filter(
                communication_platform=CommunicationPlatform.INFO_CARD,
                status_code_id=application.application_status_id,
                extra_conditions=CardProperty.CUSTOMER_WAITING_SCORE,
                is_active=True
            ).order_by('message__info_card_property__card_order_number'))
        else:
            customer_high_score = feature_high_score_full_bypass(application)
            customer_with_high_c_score = JuloOneService.is_high_c_score(application)
            is_c_score = JuloOneService.is_c_score(application)
            if is_c_score:
                eta_time = get_eta_time_for_c_score_delay(application)
                now = timezone.localtime(timezone.now())
                if now > eta_time:
                    info_cards = list(web_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions=CardProperty.CUSTOMER_HAVE_LOW_SCORE_OR_C,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                else:
                    info_cards = list(web_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions=CardProperty.CUSTOMER_HAVE_LOW_SCORE_OR_C_WITH_DElAY,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
            elif customer_high_score:
                info_cards = list(web_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    status_code_id=application.application_status_id,
                    extra_conditions=CardProperty.CUSTOMER_HAVE_HIGH_SCORE,
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))
            elif customer_with_high_c_score:
                is_document_submission = True
                info_cards = list(web_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    status_code_id=application.application_status_id,
                    extra_conditions=CardProperty.CUSTOMER_HAVE_HIGH_C_SCORE,
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))
            elif not is_c_score:
                # Medium because not meet customer high score and not meet
                # high c score also not meet c
                is_document_submission = True
                info_cards = list(web_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    status_code_id=application.application_status_id,
                    extra_conditions=CardProperty.CUSTOMER_HAVE_MEDIUM_SCORE,
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))
    elif application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED:
        negative_payment_history = not is_customer_has_good_payment_histories(
            customer, is_for_julo_one=True)
        if negative_payment_history:
            extra_condition = CardProperty.MOVE_TO_106_WITH_REASON_NEGATIVE_PAYMENT_HISTORY
        else:
            extra_condition = CardProperty.ALL_106_EXPECT_PREVIOUS_EXPIRY_REASON
        info_cards = list(web_infocards_queryset.filter(
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=application.application_status_id,
            extra_conditions=extra_condition,
            is_active=True
        ).order_by('message__info_card_property__card_order_number'))

    elif application.application_status_id == ApplicationStatusCodes.DIGISIGN_FACE_FAILED:
        info_cards = get_info_cards_privy(application.id)

    elif application.application_status_id == ApplicationStatusCodes.APPLICATION_DENIED:
        if customer.can_reapply:
            info_cards = list(web_infocards_queryset.filter(
                communication_platform=CommunicationPlatform.INFO_CARD,
                status_code_id=application.application_status_id,
                extra_conditions=CardProperty.ALREADY_ELIGIBLE_TO_REAPPLY,
                is_active=True
            ).order_by('message__info_card_property__card_order_number'))
    elif application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
        if not is_already_have_transaction(customer):
            info_cards = list(web_infocards_queryset.filter(
                communication_platform=CommunicationPlatform.INFO_CARD,
                status_code_id=application.application_status_id,
                extra_conditions=CardProperty.MSG_TO_STAY_UNTIL_1ST_TRANSACTION,
                is_active=True
            ).order_by('message__info_card_property__card_order_number'))

    if len(info_cards) == 0:
        info_cards = list(web_infocards_queryset.filter(
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=application.application_status_id,
            extra_conditions__isnull=True,
            is_active=True
        ).order_by('message__info_card_property__card_order_number'))

    if application.application_status_id == \
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
        is_document_submission = True

    data['is_document_submission'] = is_document_submission

    if application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
        if application.is_julo_one():
            loan = application.account.loan_set.last()
            if loan:
                loan_cards_qs = web_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    status_code_id=loan.status,
                    is_active=True)

                account_limit = application.account.get_account_limit
                account_property = application.account.accountproperty_set.last()
                if account_limit and account_property.concurrency and \
                    loan.status == LoanStatusCodes.CURRENT and \
                        account_limit.available_limit >= CardProperty.EXTRA_220_LIMIT_THRESHOLD:

                    loan_cards_qs = loan_cards_qs.filter(
                        extra_conditions=CardProperty.LIMIT_GTE_500)
                else:
                    loan_cards_qs = loan_cards_qs.filter(extra_conditions__isnull=True)

                loan_cards = list(
                    loan_cards_qs.order_by('message__info_card_property__card_order_number'))
                info_cards = loan_cards + info_cards
                oldest_payment = loan.account.accountpayment_set.not_paid_active() \
                    .order_by('due_date') \
                    .first()
                if oldest_payment:
                    dpd = oldest_payment.dpd
                    payment_cards = list(web_infocards_queryset.filter(
                        Q(dpd=dpd) |
                        (Q(dpd_lower__lte=dpd) & Q(dpd_upper__gte=dpd)) |
                        (Q(dpd_lower__lte=dpd) & Q(until_paid=True))).filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions__isnull=True,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                    info_cards = payment_cards + info_cards

    processed_info_cards = []
    for info_card in info_cards:
        is_expired = False
        if info_card.expiration_option and info_card.expiration_option != "No Expiration Time":
            is_expired = is_info_card_expired(info_card, application, loan)
        if not is_expired:
            processed_info_cards.append(
                format_info_card_for_android(info_card, available_context)
            )
    data['cards'] = processed_info_cards
    return data

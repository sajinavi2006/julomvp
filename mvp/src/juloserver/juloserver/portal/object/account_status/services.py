from juloserver.julo.statuses import PaymentStatusCodes


def check_account_payment_first_installment_btn_active(account_payment):
    oldest_unpaid_payment = account_payment.account.get_oldest_unpaid_account_payment()
    if (
        not account_payment.is_paid
        and oldest_unpaid_payment
        and oldest_unpaid_payment.status_id
        in [
            PaymentStatusCodes.PAYMENT_NOT_DUE,
            PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
            PaymentStatusCodes.PAYMENT_DUE_TODAY,
            PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
        ]
    ):
        return True
    return False


def find_phone_number_from_application_table(qs, phone_number):

    data = {}
    list_of_id = []
    fields = [
        'additional_contact_1_number',
        'additional_contact_2_number',
        'company_phone_number',
        'close_kin_mobile_phone',
        'kin_mobile_phone',
        'mobile_phone_2',
        'landlord_mobile_phone',
        'new_mobile_phone',
        'spouse_mobile_phone',
    ]

    data['additional_contact_1_number'] = qs.filter(
        account__application__additional_contact_1_number=phone_number
    )
    data['additional_contact_2_number'] = qs.filter(
        account__application__additional_contact_2_number=phone_number
    )
    data['company_phone_number'] = qs.filter(
        account__application__company_phone_number=phone_number
    )

    data['close_kin_mobile_phone'] = qs.filter(
        account__application__close_kin_mobile_phone=phone_number
    )
    data['kin_mobile_phone'] = qs.filter(account__application__kin_mobile_phone=phone_number)
    data['mobile_phone_2'] = qs.filter(account__application__mobile_phone_2=phone_number)

    data['landlord_mobile_phone'] = qs.filter(
        account__application__landlord_mobile_phone=phone_number
    )
    data['new_mobile_phone'] = qs.filter(account__application__new_mobile_phone=phone_number)
    data['spouse_mobile_phone'] = qs.filter(account__application__spouse_mobile_phone=phone_number)

    # remove duplicate id
    for field in fields:
        for values in data[field]:
            list_of_id.append(values.id)
    list_of_id = list(dict.fromkeys(list_of_id))
    list_of_id.sort()
    result = qs.filter(id__in=list_of_id)

    return result

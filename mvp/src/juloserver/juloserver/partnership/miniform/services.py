from typing import Union

from django.db.models import Q

from django.contrib.auth.models import User
from juloserver.julo.models import Customer, Partner, Application
from juloserver.julo.utils import format_mobile_phone
from juloserver.partnership.constants import PartnershipTokenType
from juloserver.partnership.crm.services import pre_check_create_user_data
from juloserver.partnership.jwt_manager import JWTManager
from juloserver.partnership.models import PartnershipCustomerData


def save_pii_and_phone_offer(data):
    phone = format_mobile_phone(data["phone"])
    email = data['email']
    nik = data['nik']
    name = data['name']
    partner_name = data['partner_name']
    other_phone = data.get('other_phone')

    return_data = {
        "message": None,
        "content": {
            "parameters": {
                "partner_name": partner_name,
                "name": name,
                "phone_number": phone,
                "other_phone_number": other_phone,
                "email": email,
                "nik": nik,
            }
        },
        "error": None,
    }

    partner = Partner.objects.filter(name=partner_name).last()

    partnership_customer_data_set = PartnershipCustomerData.objects.filter(
        Q(phone_number=phone) | Q(email=email) | Q(nik=nik), partner=partner
    )

    application_data_set = Application.objects.filter(
        Q(mobile_phone_1=phone) | Q(email=email) | Q(ktp=nik)
    )

    customer_data_set = Customer.objects.filter(
        Q(phone=phone) | Q(email=email) | Q(nik=nik)
    )

    user_data_set = User.objects.filter(
        Q(email=email) | Q(username=nik)
    )

    if (partnership_customer_data_set.exists()
            or application_data_set.exists()
            or customer_data_set.exists()
            or user_data_set.exists()):
        message = "NIK/Email/Nomor HP kamu sudah terdaftar di JULO atau tidak valid"
        error = message
        return_data['error'] = error
    else:
        pre_check_create_user_data(
            partner=partner,
            nik=nik,
            name=name,
            email=email,
            phone=phone,
            loan_purpose="Membeli elektronik",
            re_apply=False,
            register_from_portal=True,
            other_phone_number=other_phone,
        )
        message = "Data Berhasil Disimpan"

    return_data['message'] = message

    return return_data


# This function is for script to generate lifetime token
def jwt_token_generator(partner_name) -> Union[str, None]:
    if partner_name:
        partner = Partner.objects.filter(name=partner_name).last()
        if partner:
            user = partner.user
            jwt_token = JWTManager(user=user, partner_name=partner.name)
            access_token = jwt_token.create_or_update_token(
                token_type=PartnershipTokenType.LIFETIME
            )
        else:
            return None
    else:
        return None

    return access_token.token

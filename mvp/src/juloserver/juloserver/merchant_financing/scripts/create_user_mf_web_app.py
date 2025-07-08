import random
import secrets
import string
from juloserver.julo.models import AuthUser as User
from django.db import transaction

from juloserver.julo.models import Agent, Partner, FeatureSetting
from juloserver.merchant_financing.constants import MFStandardRole, MFFeatureSetting
from juloserver.partnership.models import PartnershipUser
from juloserver.partnership.jwt_manager import JWTManager
from juloserver.partnership.constants import PartnershipProductCategory
from juloserver.partnership.utils import generate_pii_filter_query_partnership


def generate_random_username(prefix='mf_agent', length=8):
    characters = string.ascii_letters + string.digits
    while True:
        random_suffix = ''.join(random.choice(characters) for _ in range(length))
        random_username = f"{prefix}_{random_suffix}"
        if not User.objects.filter(username=random_username).exists():
            return random_username


def generate_strong_password(length=12):
    characters = string.ascii_letters + string.digits + '#$%&?@'
    password = ''.join(secrets.choice(characters) for _ in range(length))
    return password


def generate_random_email(partner: str, prefix='mf', domain='julo.co.id', length=4):
    characters = string.ascii_letters + string.digits

    # Remove spaces from partner name
    partner_name = partner.replace(' ', '_')

    while True:
        random_string = ''.join(secrets.choice(characters) for _ in range(length))
        random_email = f"{prefix.strip()}_{partner_name.strip()}_{random_string}@{domain.strip()}"
        pii_user_filter_dict = generate_pii_filter_query_partnership(User, {'email': random_email})
        if not User.objects.filter(**pii_user_filter_dict).exists():
            return random_email


def deactivated_user(username: str):
    """
    this function to deactivated user
    Sample command to running the function:
    from juloserver.merchant_financing.scripts.create_user_mf_web_app import *
    deactivated_user(username='<username>')
    """
    user = User.objects.filter(username=username).last()
    if not user:
        print('user not found')
        return

    user.is_active = False
    user.save()
    try:
        # process inactivate JWT token
        with transaction.atomic():
            jwt_token = user.partnershipjsonwebtoken_set.values_list('token', flat=True).last()
            if not jwt_token:
                print('token not found, user already inactive')
                return
            jwt_manager = JWTManager(product_category=PartnershipProductCategory.MERCHANT_FINANCING)
            decoded_token = jwt_manager.decode_token(jwt_token)
            if not decoded_token:
                print('user already inactive')
                return
            partner_name = decoded_token.get('partner')
            jwt_manager = JWTManager(
                partner_name=partner_name,
                product_category=PartnershipProductCategory.MERCHANT_FINANCING,
            )
            partner_name = decoded_token.get('partner')
            jwt_manager.inactivate_token(jwt_token)
            print('User successfully deactivated.')
    except Exception as error:
        print('failed deactivated user token, because: {}'.format(str(error)))


def create_mf_user_agent_role(
    partner_user_role: str,
    partner_name: str = None,
    email: str = None,
    username: str = None,
    password: str = None,
) -> dict:
    """
    This function create:
    - User
    - if username is blank we will generate random username
    - if password is blank we will generate random password
    - if email is blank we will generate random email
    - Create Partnership User
    Sample command to running the function:
    from juloserver.merchant_financing.scripts.create_user_mf_web_app import *
    create agent role:
    1. random username, email, password
    create_mf_user_agent_role(partner_user_role='agent')
    2. define username, email, password
    create_mf_user_agent_role(
        partner_user_role='agent'
        email='sample.email@julo.co.id'
        username='sample.email@julo.co.id'
        password='sample.email@julo.co.id'
    )
    //
    create partner_agent role:
    1.random username, email, password
    create_mf_user_agent_role(partner_user_role='partner_agent', partner_name='partner_name')
    2. define username, email, password
    create_mf_user_agent_role(
        partner_user_role='partner_agent'
        partner_name='partner_name'
        email='sample.email@julo.co.id'
        username='sample.email@julo.co.id'
        password='sample.email@julo.co.id'
    )
    """

    data_user = {
        'username': username,
        'email': email,
        'success_result': False,
    }

    if not partner_user_role:
        data_user['error_message'] = 'please fill in partner_user_role'
        return data_user

    partner = None
    if partner_user_role == MFStandardRole.PARTNER_AGENT:
        if not partner_name:
            data_user['error_message'] = 'partner name is required'
            return data_user

        partner = Partner.objects.filter(
            name=partner_name,
            is_active=True,
        ).last()

        if not partner:
            data_user['error_message'] = 'Partner not found'
            return data_user

        feature_setting = FeatureSetting.objects.filter(
            feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL,
            is_active=True,
        ).last()
        if feature_setting and feature_setting.parameters:
            allowed_partners = feature_setting.parameters.get('api_v2')
            if allowed_partners and partner_name not in allowed_partners:
                data_user[
                    'error_message'
                ] = 'partner are not allowed mf standard product v2 please check feature setting {}'.format(
                    MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL
                )
                return data_user
    else:
        partner_name = 'julo'

    if partner_user_role not in {
        MFStandardRole.PARTNER_AGENT,
        MFStandardRole.AGENT,
    }:
        data_user['error_message'] = 'User role not in allowed list'
        return data_user

    # If Username blank we will generate random username
    if not username:
        username = generate_random_username(
            'mf_{}'.format(
                partner_name.replace(' ', '_'),
            )
        )

    # If email blank we will generate random email
    if not email:
        email = generate_random_email(partner_name)

    # If password blank we will generate random password
    if not password:
        password = generate_strong_password()

    with transaction.atomic():
        user, created = User.objects.get_or_create(username=username, is_active=True)
        if created:
            user.email = email
            user.set_password(password)
            user.save()

        partnership_user, _ = PartnershipUser.objects.get_or_create(user=user)
        if partnership_user and partnership_user.role:
            data_user[
                'error_message'
            ] = 'username already registered on different partner please create with new username'
            return data_user

        partnership_user.update_safely(role=partner_user_role)

        if not partnership_user.partner and partner_user_role == MFStandardRole.PARTNER_AGENT:
            partnership_user.update_safely(partner=partner)

        if partner_user_role == MFStandardRole.PARTNER_AGENT:
            data_user['partner'] = partner.name

        Agent.objects.get_or_create(user=user)
        data_user['username'] = username
        data_user['password'] = password
        data_user['role'] = partner_user_role
        data_user['success_result'] = True

    return data_user

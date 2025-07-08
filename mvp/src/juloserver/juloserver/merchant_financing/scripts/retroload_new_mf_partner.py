from juloserver.julo.product_lines import ProductLineCodes
from juloserver.merchant_financing.constants import MFFeatureSetting
from juloserver.merchant_financing.scripts.create_user_mf_web_app import generate_strong_password
from juloserver.portal.object.bulk_upload.constants import MerchantFinancingCSVUploadPartner
from juloserver.julo.models import Partner, ProductLine, Customer, FeatureSetting
from django.contrib.auth.models import Group, User
from django.conf import settings


def retroload_new_mf_partner(
    partner_name,
    default_user_email='',
    default_ops_email='',
    app_190_email_recipients='',
    disburse_email_recipients=None,
    due_date_type=None,
    partner_bank_account_number=None,
    partner_bank_account_name=None,
    partner_bank_name=None,
    poc_name=None,
    company_name=None,
    company_address=None,
    poc_phone=None,
):
    # please define the partner name on MerchantFinancingCSVUploadPartner
    merchant_financing_csv_upload_partners = []
    for attribute_name in dir(MerchantFinancingCSVUploadPartner):
        if not attribute_name.startswith("__"):
            attribute_value = getattr(MerchantFinancingCSVUploadPartner, attribute_name)
            merchant_financing_csv_upload_partners.append(attribute_value)

    if partner_name not in merchant_financing_csv_upload_partners:
        return 'please define the constant first on MerchantFinancingCSVUploadPartner'

    group = Group.objects.get(name="julo_partners")

    user, created = User.objects.get_or_create(
        username=partner_name,
        defaults={'email': default_user_email, 'password': generate_strong_password()},
    )
    user.groups.add(group)

    if settings.ENVIRONMENT != 'prod':
        app_190_email_recipients = 'albert.christian@julofinance.com'
        disburse_email_recipients = 'albert.christian@julofinance.com'

    merchant_financing_standard_product = ProductLine.objects.filter(
        product_line_code=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
    ).last()

    partner, created = Partner.objects.get_or_create(
        user=user,
        defaults={
            'poc_email': default_user_email,
            'poc_phone': poc_phone,
            'poc_name': poc_name,
            'name': partner_name,
            'phone': '+628111111111',
            'email': default_user_email,
            'company_name': company_name,
            'company_address': company_address,
            'is_active': True,
            'is_csv_upload_applicable': True,
            'partner_bank_account_number': partner_bank_account_number,
            'partner_bank_account_name': partner_bank_account_name,
            'partner_bank_name': partner_bank_name,
            'is_disbursement_to_partner_bank_account': True,
            'recipients_email_address_for_190_application': app_190_email_recipients,
            'recipients_email_address_for_bulk_disbursement': disburse_email_recipients,
            'sender_email_address_for_190_application': default_ops_email,
            'sender_email_address_for_bulk_disbursement': default_ops_email,
            'due_date_type': due_date_type,
            'product_line': merchant_financing_standard_product,
        },
    )

    if not created:
        partner.poc_email = default_user_email
        partner.poc_phone = poc_phone
        partner.poc_name = poc_name
        partner.name = partner_name
        partner.phone = '+628111111111'
        partner.email = default_user_email
        partner.company_name = company_name
        partner.company_address = company_address
        partner.is_active = True
        partner.is_csv_upload_applicable = True
        partner.partner_bank_account_number = partner_bank_account_number
        partner.partner_bank_account_name = partner_bank_account_name
        partner.partner_bank_name = partner_bank_name
        partner.is_disbursement_to_partner_bank_account = True
        partner.recipients_email_address_for_190_application = app_190_email_recipients
        partner.recipients_email_address_for_bulk_disbursement = disburse_email_recipients
        partner.sender_email_address_for_190_application = default_ops_email
        partner.sender_email_address_for_bulk_disbursement = default_ops_email
        partner.due_date_type = due_date_type
        partner.save()

    Customer.objects.create(user=user, email=default_user_email, phone=partner.phone)

    feature_setting = FeatureSetting.objects.filter(
        feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL
    ).last()
    if feature_setting:
        list_partners = feature_setting.parameters.get('api_v2', [])
        list_partners.append(partner_name)
        feature_setting.update_safely(parameters=feature_setting.parameters)

    return 'successful'

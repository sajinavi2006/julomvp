from typing import Optional

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q, Prefetch

from juloserver.customer_module.models import BankAccountDestination
from juloserver.julo.constants import WorkflowConst, XidIdentifier
from juloserver.julo.models import (
    Partner,
    Workflow,
    ProductLine,
    Customer,
    Application,
    Loan,
    ApplicationNote,
    CreditScore,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.merchant_financing.web_app.constants import (
    PARTNERSHIP_PREFIX_IDENTIFIER,
    PARTNERSHIP_SUFFIX_EMAIL,
)
from juloserver.partnership.constants import (
    PartnershipXIDGenerationMethod,
    PartnershipImageProductType,
)
from juloserver.partnership.models import (
    PartnershipCustomerData,
    PartnershipApplicationData,
    PartnershipImage,
)
from juloserver.partnership.services.services import partnership_generate_xid
from juloserver.partnership.utils import generate_pii_filter_query_partnership
from juloserver.portal.object.bulk_upload.constants import MerchantFinancingCSVUploadPartner

MF_STANDARD_PRODUCT_PARTNERS = {
    MerchantFinancingCSVUploadPartner.GAJIGESA,
    MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_REGULER,
    MerchantFinancingCSVUploadPartner.EFISHERY_JAWARA,
    MerchantFinancingCSVUploadPartner.EFISHERY_INTI_PLASMA,
    MerchantFinancingCSVUploadPartner.AGRARI,
    MerchantFinancingCSVUploadPartner.KARGO,
    MerchantFinancingCSVUploadPartner.RABANDO,
    MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_LITE,
    MerchantFinancingCSVUploadPartner.FISHLOG,
    MerchantFinancingCSVUploadPartner.DAGANGAN,
    MerchantFinancingCSVUploadPartner.EFISHERY,
}

PARTNER_PRODUCT_LINE_CODE = {
    MerchantFinancingCSVUploadPartner.GAJIGESA: ProductLineCodes.GAJIGESA,
    MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_REGULER: ProductLineCodes.EFISHERY_KABAYAN_REGULER,
    MerchantFinancingCSVUploadPartner.EFISHERY_JAWARA: ProductLineCodes.EFISHERY_JAWARA,
    MerchantFinancingCSVUploadPartner.EFISHERY_INTI_PLASMA: ProductLineCodes.EFISHERY_INTI_PLASMA,
    MerchantFinancingCSVUploadPartner.AGRARI: ProductLineCodes.AGRARI,
    MerchantFinancingCSVUploadPartner.KARGO: ProductLineCodes.KARGO,
    MerchantFinancingCSVUploadPartner.RABANDO: ProductLineCodes.RABANDO,
    MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_LITE: ProductLineCodes.EFISHERY_KABAYAN_LITE,
    MerchantFinancingCSVUploadPartner.FISHLOG: ProductLineCodes.FISHLOG,
    MerchantFinancingCSVUploadPartner.DAGANGAN: ProductLineCodes.DAGANGAN,
    MerchantFinancingCSVUploadPartner.EFISHERY: ProductLineCodes.EFISHERY,
}


def mf_standard_register_merchant(
    merchant_data: dict, partner: Partner, workflow: Workflow, product_line: ProductLine
) -> Optional[PartnershipApplicationData]:
    """Function to create merchant:
    - User (masked email, nik)
    - Customer (masked email, nik, fullname)
    - Application (masked email, nik, fullname)
    - Create Partnership Customer Data
    - Create Partnership Application Data
    - Create Application Note
    - Run Happy Path Flow 100
    - Run Happy Path Flow 105
    - Run Happy Path Flow 130
    """
    # temporary nik user, email and phone
    prefix = PARTNERSHIP_PREFIX_IDENTIFIER
    product_code = ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT

    temp_nik = '{}{}{}'.format(prefix, product_code, merchant_data.get("ktp"))
    user_email = '{}_{}{}'.format(merchant_data.get("ktp"), partner.name, PARTNERSHIP_SUFFIX_EMAIL)
    masked_phone = '{}{}'.format(product_code, merchant_data['mobile_phone_1'])
    web_version = "0.2.0"

    # Check if email/phone exists on partnership customer data
    pii_filter_partnership_customer_data_dict = generate_pii_filter_query_partnership(
        PartnershipCustomerData,
        {
            'phone_number': merchant_data.get('mobile_phone_1'),
            'nik': merchant_data.get('ktp'),
            'email': merchant_data.get('email'),
        },
    )
    existing_partnership_customer = PartnershipCustomerData.objects.filter(
        Q(partner__name=partner.name)
        & (
            Q(email=pii_filter_partnership_customer_data_dict.get('email'))
            | Q(nik=pii_filter_partnership_customer_data_dict.get('ktp'))
            | Q(phone_number=pii_filter_partnership_customer_data_dict.get('mobile_phone_1'))
        )
    ).exists()
    if existing_partnership_customer:
        print("No KTP/Alamat email/No HP Borrower sudah terdaftar")
        return None

    try:
        partnership_application_data = None
        with transaction.atomic():
            # create user
            user = User(username=temp_nik, email=user_email)
            password = User.objects.make_random_password()
            user.set_password(password)
            user.save()

            # create customer
            customer = Customer.objects.create(
                user=user,
                email=user_email,
                appsflyer_device_id=None,
                advertising_id=None,
                mother_maiden_name=None,
                phone=masked_phone,
                dob=merchant_data.get('dob'),
                fullname=merchant_data.get('fullname'),
                gender=merchant_data.get('gender'),
            )

            # create application
            application_xid_generated = partnership_generate_xid(
                table_source=XidIdentifier.APPLICATION.value,
                method=PartnershipXIDGenerationMethod.DATETIME.value,
            )

            application = Application.objects.create(
                application_xid=application_xid_generated,
                customer=customer,
                email=user_email,
                partner=partner,
                workflow=workflow,
                product_line=product_line,
                web_version=web_version,
                fullname=merchant_data.get('fullname'),
                mobile_phone_1=masked_phone,
                birth_place=merchant_data.get('birth_place'),
                dob=merchant_data.get('dob'),
                gender=merchant_data.get('gender'),
                last_education=merchant_data.get('last_education'),
                home_status=merchant_data.get('home_status'),
                address_street_num=merchant_data.get('address_street_num'),
                address_provinsi=merchant_data.get('address_provinsi'),
                address_kabupaten=merchant_data.get('address_kabupaten'),
                address_kelurahan=merchant_data.get('address_kelurahan'),
                address_kecamatan=merchant_data.get('address_kecamatan'),
                address_kodepos=merchant_data.get('address_kodepos'),
                marital_status=merchant_data.get('marital_status'),
                spouse_name=merchant_data.get('spouse_name'),
                spouse_mobile_phone=merchant_data.get('spouse_mobile_phone'),
                kin_name=merchant_data.get('kin_name'),
                kin_mobile_phone=merchant_data.get('kin_mobile_phone'),
                bank_name=merchant_data.get('bank_name'),
                bank_account_number=merchant_data.get('bank_account_number'),
                monthly_income=merchant_data.get('monthly_income'),
                monthly_expenses=merchant_data.get('monthly_expenses'),
                job_type='Pengusaha',
                loan_purpose=merchant_data.get('loan_purpose'),
                number_of_employees=merchant_data.get('pegawai'),
            )

            # User NIK
            user_nik = '{}{}{}'.format(prefix, product_code, application.id)

            # Update user, customer, application nik
            user.username = user_nik
            user.save(update_fields=['username'])

            customer.nik = user_nik
            customer.save(update_fields=['nik'])

            application.ktp = user_nik
            application.save(update_fields=['ktp'])

            # Get old customer id
            old_customer_id = None
            old_application = (
                Application.objects.filter(
                    ktp=merchant_data.get('ktp'),
                    partner=partner,
                )
                .distinct('customer_id')
                .values('customer_id', 'ktp')
            )
            if old_application.exists():
                old_customer_id = old_application[0].get('customer_id')

            # create partnership customer data
            partnership_customer_data = PartnershipCustomerData.objects.create(
                nik=merchant_data.get('ktp'),
                email=merchant_data.get('email'),
                partner=partner,
                phone_number=merchant_data.get('mobile_phone_1'),
                customer=customer,
                application=application,
                npwp=merchant_data.get('npwp'),
                certificate_number=merchant_data.get('certificate_number'),
                certificate_date=merchant_data.get('certificate_date'),
                user_type=merchant_data.get('user_type', 'perorangan'),
                customer_id_old=old_customer_id,
            )

            # create partnership application data
            partnership_application_data = PartnershipApplicationData.objects.create(
                partnership_customer_data=partnership_customer_data,
                application=application,
                email=merchant_data.get('email'),
                web_version=web_version,
                fullname=merchant_data.get('fullname'),
                mobile_phone_1=merchant_data.get('mobile_phone_1'),
                birth_place=merchant_data.get('birth_place'),
                dob=merchant_data.get('dob'),
                gender=merchant_data.get('gender'),
                last_education=merchant_data.get('last_education'),
                home_status=merchant_data.get('home_status'),
                address_street_num=merchant_data.get('address_street_num'),
                address_provinsi=merchant_data.get('address_provinsi'),
                address_kabupaten=merchant_data.get('address_kabupaten'),
                address_kelurahan=merchant_data.get('address_kelurahan'),
                address_kecamatan=merchant_data.get('address_kecamatan'),
                address_kodepos=merchant_data.get('address_kodepos'),
                marital_status=merchant_data.get('marital_status'),
                spouse_name=merchant_data.get('spouse_name'),
                spouse_mobile_phone=merchant_data.get('spouse_mobile_phone'),
                kin_name=merchant_data.get('kin_name'),
                kin_mobile_phone=merchant_data.get('kin_mobile_phone'),
                job_type='Pengusaha',
                monthly_income=merchant_data.get('monthly_income'),
                monthly_expenses=merchant_data.get('monthly_expenses'),
                business_type=merchant_data.get('business_type'),
                loan_purpose=merchant_data.get('loan_purpose'),
                bank_name=merchant_data.get('bank_name'),
                bank_account_number=merchant_data.get('bank_account_number'),
                proposed_limit=merchant_data.get('proposed_limit'),
                product_line=product_line,
                reject_reason={},
                business_entity=merchant_data.get('business_entity'),
            )

            ApplicationNote.objects.create(
                application_id=application.id,
                note_text="migrate from merchant financing csv upload CRM to merchant financing standard product",
            )

            # Set application STATUS to 100
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.FORM_CREATED,
                change_reason='system_triggered',
            )

            # Set application STATUS to 105
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.FORM_PARTIAL,
                change_reason='system_triggered',
            )

            # Set application STATUS to 130
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                change_reason='system_triggered',
            )

        print("Success register merchant application")
        return partnership_application_data

    except Exception as e:
        print(str(e))
        return None


def duplicate_existing_mf_users(limit: Optional[int], partner_name: str) -> None:
    """Duplicate existing MF users to MFSP
    - has application status x190
    - has no loan record or has loan record but the status is not between >= 220 and < 250
    - user data then will be duplicated to MFSP. should be only the user data, not their loan / payment
    """

    if partner_name not in MF_STANDARD_PRODUCT_PARTNERS:
        print('Not merchant financing partner')
        return

    partner = Partner.objects.filter(name=partner_name).last()
    if not partner:
        print('Partner not found')
        return

    j1_workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)
    mf_standard_workflow = Workflow.objects.get(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)
    partnership_product_line = ProductLine.objects.get(
        product_line_code=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
    )

    applications = (
        Application.objects.filter(
            partner_id=partner.id,
            application_status=ApplicationStatusCodes.LOC_APPROVED,
            workflow=j1_workflow,
            product_line__product_line_code=PARTNER_PRODUCT_LINE_CODE[partner_name],
        )
        .prefetch_related('account__accountlimit_set')
        .order_by('-cdate')
    )

    if limit:
        applications = applications[:limit]

    for application in applications:
        application_id = application.id

        print('Process application {}'.format(application_id))

        account = application.account
        customer = application.customer
        if not account:
            account_limit = 0
        else:
            account_limit = account.accountlimit_set.all()[0].set_limit

        merchant_data = {
            "proposed_limit": account_limit,
            "distributor_code": None,
            "fullname": customer.fullname,
            "mobile_phone_1": application.mobile_phone_1,
            "marital_status": application.marital_status,
            "gender": application.gender,
            "birth_place": application.birth_place,
            "dob": application.dob,
            "home_status": application.home_status,
            "spouse_name": application.spouse_name,
            "spouse_mobile_phone": application.spouse_mobile_phone,
            "kin_name": application.kin_name,
            "kin_mobile_phone": application.kin_mobile_phone,
            "address_provinsi": application.address_provinsi,
            "address_kabupaten": application.address_kabupaten,
            "address_kelurahan": application.address_kelurahan,
            "address_kecamatan": application.address_kecamatan,
            "address_kodepos": application.address_kodepos,
            "address_street_num": application.address_street_num,
            "bank_name": application.bank_name,
            "bank_account_number": application.bank_account_number,
            "loan_purpose": application.loan_purpose,
            "monthly_income": application.monthly_income,
            "monthly_expenses": application.monthly_expenses,
            "pegawai": None,
            "business_type": None,
            "ktp": customer.nik,
            "last_education": application.last_education,
            "npwp": None,
            "email": customer.email,
        }

        partnership_application_data = mf_standard_register_merchant(
            merchant_data=merchant_data,
            partner=partner,
            workflow=mf_standard_workflow,
            product_line=partnership_product_line,
        )

        if partnership_application_data:
            new_application = partnership_application_data.application

            # Migrate application image
            images = PartnershipImage.objects.filter(application_image_source=application_id)

            for image in images:
                try:
                    image.application_image_source = new_application.id
                    image.product_type = PartnershipImageProductType.MF_API
                    image.save(update_fields=['application_image_source', 'product_type'])
                except Exception as e:
                    print('Failed migrate image {} with error {}'.format(image.id, str(e)))

            # Migrate bank account destination
            old_bank_account_destination = BankAccountDestination.objects.filter(
                customer=customer
            ).last()
            if old_bank_account_destination:
                BankAccountDestination.objects.create(
                    bank_account_category=old_bank_account_destination.bank_account_category,
                    customer=new_application.customer,
                    bank=old_bank_account_destination.bank,
                    name_bank_validation=old_bank_account_destination.name_bank_validation,
                    account_number=old_bank_account_destination.account_number,
                    is_deleted=old_bank_account_destination.is_deleted,
                    description=old_bank_account_destination.description,
                )

                new_application.name_bank_validation = (
                    old_bank_account_destination.name_bank_validation
                )
                new_application.save(update_fields=['name_bank_validation'])
                print('Success create new bank account destination')

            # Migrate credit score
            old_credit_score = CreditScore.objects.filter(application=application).last()
            if old_credit_score:
                CreditScore.objects.create(
                    application_id=new_application.id,
                    score=old_credit_score.score,
                    message=old_credit_score.message,
                    products_str=old_credit_score.products_str,
                    income_prediction_score=old_credit_score.income_prediction_score,
                    thin_file_score=old_credit_score.thin_file_score,
                    inside_premium_area=old_credit_score.inside_premium_area,
                    score_tag=old_credit_score.score_tag,
                    credit_limit=old_credit_score.credit_limit,
                    failed_checks=old_credit_score.failed_checks,
                    model_version=old_credit_score.model_version,
                    credit_matrix_version=old_credit_score.credit_matrix_version,
                    fdc_inquiry_check=old_credit_score.fdc_inquiry_check,
                    credit_matrix_id=old_credit_score.credit_matrix_id,
                )
                print('Success create new credit score')

            # Create note for old application
            application_note = (
                "migrated to new application with id {}. migrate application image".format(
                    new_application.id
                )
            )
            ApplicationNote.objects.create(
                application_id=application.id,
                note_text=application_note,
            )

        print('=' * 10)

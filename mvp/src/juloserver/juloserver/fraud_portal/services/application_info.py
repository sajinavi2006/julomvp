from typing import Tuple

import pytz

from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.bpjs.services.bpjs_direct import get_range_salary
from juloserver.fraud_portal.models.models import FraudApplicationInfo
from juloserver.julo.models import Application, Device, Image
from juloserver.pii_vault.constants import PiiSource

jakarta_tz = pytz.timezone('Asia/Jakarta')


def get_application_info(application_ids: list) -> list:
    application_info_list = []
    for application_id in application_ids:
        application = Application.objects.get(id=application_id)
        # documents here means image, just following the Frontend
        documents = list(
            Image.objects.filter(
                image_source=application.id,
                image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ, Image.DELETED],
            ).only("image_type", "url", "image_status")
        )
        application_info = constuct_application_info(application, documents)
        application_info_list.append(application_info.to_dict())

    return application_info_list


def constuct_application_info(application: Application, documents: list) -> FraudApplicationInfo:
    detokenized_application = detokenize_pii_antifraud_data(PiiSource.APPLICATION, [application])[0]
    spouse_or_kin_mobile_phone, spouse_or_kin_name = get_spouse_or_kin_info(application)
    documents_info = get_documents(documents)
    other_documents = get_documents(documents, Image.DELETED)
    device_info_list = get_device_info_list(application)

    return FraudApplicationInfo(
        application_id=application.id,
        application_full_name=detokenized_application.fullname,
        application_status_code=application.status,
        application_status=application.code_status,
        cdate=str(application.cdate.astimezone(jakarta_tz)),
        ktp=detokenized_application.ktp,
        email=detokenized_application.email,
        dob=application.dob,
        birth_place=application.birth_place,
        mobile_phone_1=detokenized_application.mobile_phone_1,
        marital_status=application.marital_status,
        spouse_or_kin_mobile_phone=spouse_or_kin_mobile_phone,
        spouse_or_kin_name=spouse_or_kin_name,
        address_detail=application.address_street_num,
        address_provinsi=application.address_provinsi,
        address_kabupaten=application.address_kabupaten,
        address_kecamatan=application.address_kecamatan,
        address_kelurahan=application.address_kelurahan,
        bank_name=application.bank_name,
        name_in_bank=application.name_in_bank,
        bank_account_number=application.bank_account_number,
        documents=documents_info,
        other_documents=other_documents,
        gender=application.gender,
        range_upah=get_range_salary(application.monthly_income),
        blth_upah=application.last_month_salary,
        employment_status=application.employment_status,
        bpjs_package='JHT,JKK,JKM,JPN',
        device_info_list=device_info_list,
    )


def get_spouse_or_kin_info(application: Application) -> Tuple[str, str]:
    spouse_or_kin_mobile_phone = application.spouse_mobile_phone
    spouse_or_kin_name = application.spouse_name
    if not spouse_or_kin_mobile_phone or not spouse_or_kin_name:
        spouse_or_kin_mobile_phone = application.kin_mobile_phone
        spouse_or_kin_name = application.kin_name

    return spouse_or_kin_mobile_phone, spouse_or_kin_name


def get_device_info_list(application: Application) -> list:
    customer = application.customer
    if not customer:
        device_info_list = Device.objects.filter(id=application.device_id).values(
            "device_model_name", "android_id", "ios_id"
        )
        return device_info_list
    device_info_list = (
        Device.objects.filter(customer=customer)
        .values("device_model_name", "android_id", "ios_id")
        .distinct()
    )
    return device_info_list


# documents here means images
def get_documents(documents: list, imageStatus: int = None) -> list:
    if imageStatus is None:
        status = {Image.CURRENT, Image.RESUBMISSION_REQ}
    else:
        status = {imageStatus}

    return [
        {
            "document_type": doc.image_type,
            "document_url": doc.image_url,
        }
        for doc in documents
        if doc.image_status in status
    ]


def get_applications_by_device(android_id: str, ios_id: str) -> list:
    if android_id:
        devices_qs = Device.objects.filter(android_id=android_id)
    else:
        devices_qs = Device.objects.filter(ios_id=ios_id)

    # Build a list (or subquery) of the matching customer_ids
    customer_ids = devices_qs.values_list('customer_id', flat=True)

    # Retrieve all application_ids in a single query
    application_ids = (
        Application.objects.filter(customer_id__in=customer_ids)
        .values_list('id', flat=True)
        .order_by('cdate')
    )

    return application_ids

from django.contrib.auth.models import User
from django.utils import timezone

from juloserver.dana.models import DanaCustomerData
from juloserver.followthemoney.models import LenderCurrent
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import Application
from juloserver.pusdafil.clients import get_pusdafil_client
from juloserver.pusdafil.constants import (
    PUSDAFIL_ORGANIZER_ID,
    ApplicationConstant,
    EducationConstant,
    GenderConstant,
    UserConstant,
    cities,
    job_industries,
    jobs,
    provinces,
)
from juloserver.pusdafil.models import PusdafilUpload
from juloserver.pusdafil.services import PusdafilService
from juloserver.pusdafil.utils import CommonUtils


def do_resend_existing_user_registration_to_pusdafil(user_id):
    existing_pusdafil_upload = PusdafilUpload.objects.filter(
        name=PusdafilService.REPORT_NEW_USER_REGISTRATION,
        status=PusdafilUpload.STATUS_SUCCESS,
        identifier=user_id,
    )

    if len(existing_pusdafil_upload) == 1:
        try:
            user = User.objects.get(pk=user_id)

            customer = user.customer
            lender = LenderCurrent.objects.filter(user=user).first()
            application = Application.objects.filter(customer=customer).order_by("cdate").last()

            if lender or application.fullname:
                # Initiating log
                pusdafil_upload = PusdafilUpload.objects.create(
                    name=PusdafilService.REPORT_NEW_USER_REGISTRATION,
                    identifier=user_id,
                    retry_count=0,
                    status=PusdafilUpload.STATUS_INITIATED,
                )

                # identity number
                identity_number = ''

                if user.id in ApplicationConstant.LEGAL_ENTITY_USER_IDS:
                    identity_number = ApplicationConstant.LEGAL_ENTITY_IDENTITY_NUMBER
                elif customer:
                    if application.is_dana_flow():
                        identity_number = application.dana_customer_data.nik
                    else:
                        identity_number = application.ktp

                # npwp
                npwp = ''

                if user.id in ApplicationConstant.LEGAL_ENTITY_USER_IDS:
                    npwp = ApplicationConstant.LEGAL_ENTITY_IDENTITY_NUMBER
                elif customer:
                    npwp = None

                # gender
                gender = GenderConstant.GENDER_MALE

                if lender:
                    gender = GenderConstant.GENDER_LENDER
                elif application and application.gender == 'Pria':
                    gender = GenderConstant.GENDER_MALE
                elif application and application.gender == 'Wanita':
                    gender = GenderConstant.GENDER_FEMALE

                address = ApplicationConstant.ADDRESS_DEFAULT_VALUE
                city_id = ApplicationConstant.CITY_DEFAULT_ID
                province_id = ApplicationConstant.PROVINCE_DEFAULT_ID
                postal_code = ''

                if application:
                    if application.address_street_num and len(application.address_street_num) > 1:
                        address = application.address_street_num
                    if (
                        application.address_kabupaten
                        and application.address_kabupaten.upper() in cities
                    ):
                        city_id = cities[application.address_kabupaten.upper()]
                    if (
                        application.address_provinsi
                        and application.address_provinsi.upper() in provinces
                    ):
                        province_id = provinces[application.address_provinsi.upper()]
                    postal_code = application.address_kodepos

                # marital status id
                marital_status = ApplicationConstant.MARITAL_STATUS_NO_DATA

                if application and application.marital_status in [
                    'Cerai',
                    'Janda / duda',
                    'Menikah',
                ]:
                    marital_status = ApplicationConstant.MARITAL_STATUS_MARRIED
                elif application and application.marital_status in ['Lajang']:
                    marital_status = ApplicationConstant.MARITAL_STATUS_NOT_MARRIED
                elif lender:
                    marital_status = ApplicationConstant.MARITAL_STATUS_LEGAL_ENTITY

                # job id
                job_id = ApplicationConstant.JOB_NO_DATA

                if application and application.job_type in jobs:
                    job_id = jobs[application.job_type]
                elif lender:
                    job_id = ApplicationConstant.JOB_LEGAL_ENTITY

                # job industry id
                job_industry_id = ApplicationConstant.JOB_INDUSTRY_DEFAULT_ID

                if application:
                    if application.job_type in job_industries:
                        job_industry_id = job_industries[application.job_type]
                    elif application.job_industry in job_industries:
                        job_industry_id = job_industries[application.job_industry]

                # monthly income id
                monthly_income_id = ApplicationConstant.MONTHLY_INCOME_FIRST_TIER

                if application and application.monthly_income:
                    if application.monthly_income < 12500000:
                        monthly_income_id = ApplicationConstant.MONTHLY_INCOME_FIRST_TIER
                    elif application.monthly_income <= 50000000:
                        monthly_income_id = ApplicationConstant.MONTHLY_INCOME_SECOND_TIER
                    elif application.monthly_income <= 500000000:
                        monthly_income_id = ApplicationConstant.MONTHLY_INCOME_THIRD_TIER
                    elif application.monthly_income <= 50000000000:
                        monthly_income_id = ApplicationConstant.MONTHLY_INCOME_FOURTH_TIER
                    else:
                        monthly_income_id = ApplicationConstant.MONTHLY_INCOME_FIFTH_TIER

                # work experience
                work_experience = ApplicationConstant.WORK_EXPERIENCE_NO_DATA

                if application:
                    if application.job_type in ['Mahasiswa']:
                        work_experience = ApplicationConstant.WORK_EXPERIENCE_NO_EXPERIENCE
                    elif application.job_start:
                        delta_result = (
                            timezone.localtime(timezone.now()).date() - application.job_start
                        )

                        if delta_result.days < 360:
                            work_experience = ApplicationConstant.WORK_EXPERIENCE_LESS_THAN_ONE_YEAR
                        elif 360 <= delta_result.days <= 720:
                            work_experience = 2
                        elif 720 <= delta_result.days <= 1080:
                            work_experience = (
                                ApplicationConstant.WORK_EXPERIENCE_TWO_YEAR_TO_THREE_YEAR
                            )
                        elif delta_result.days >= 1080:
                            work_experience = (
                                ApplicationConstant.WORK_EXPERIENCE_MORE_THAN_THREE_YEAR
                            )
                elif lender:
                    work_experience = ApplicationConstant.WORK_EXPERIENCE_LEGAL_ENTITY

                # education id
                education_id = EducationConstant.EDUCATION_DEFAULT

                if application:
                    if application.last_education == "SD":
                        education_id = EducationConstant.EDUCATION_ELEMENTARY_SCHOOL
                    elif application.last_education == "SLTP":
                        education_id = EducationConstant.EDUCATION_JUNIOR_SCHOOL
                    elif application.last_education == "SLTA":
                        education_id = EducationConstant.EDUCATION_HIGH_SCHOOL
                    elif application.last_education == "Diploma":
                        education_id = EducationConstant.EDUCATION_DIPLOMA
                    elif application.last_education == "S1":
                        education_id = EducationConstant.EDUCATION_S1
                    elif application.last_education == "S2":
                        education_id = EducationConstant.EDUCATION_S2
                    elif application.last_education == "S3":
                        education_id = EducationConstant.EDUCATION_S3
                elif lender:
                    education_id = EducationConstant.EDUCATION_LENDER

                # representative name
                representative = None

                if lender:
                    representative = lender.poc_name

                # representative number
                representative_number = ''

                if user.id in ApplicationConstant.LEGAL_ENTITY_USER_IDS:
                    representative_number = ApplicationConstant.LEGAL_ENTITY_IDENTITY_NUMBER
                elif customer:
                    representative_number = None

                request = dict(
                    id_penyelenggara=str(PUSDAFIL_ORGANIZER_ID),
                    id_pengguna=str(user.id),
                    jenis_pengguna=UserConstant.LENDER_USER_ID
                    if lender
                    else UserConstant.REGULAR_USER_ID,
                    tgl_registrasi=user.date_joined.strftime("%Y-%m-%d"),
                    nama_pengguna=lender.lender_name if lender else customer.fullname,
                    jenis_identitas=UserConstant.LENDER_IDENTITY_TYPE
                    if lender
                    else UserConstant.USER_IDENTITY_TYPE,
                    no_identitas=identity_number,
                    no_npwp=npwp,
                    id_jenis_badan_hukum=UserConstant.LENDER_LEGAL_ENTITY_TYPE
                    if lender
                    else UserConstant.REGULAR_USER_LEGAL_ENTITY_TYPE,
                    tempat_lahir=application.birth_place[:50]
                    if customer and application.birth_place
                    else None,
                    tgl_lahir=application.dob.strftime("%Y-%m-%d") if customer else None,
                    id_jenis_kelamin=gender,
                    alamat=address,
                    id_kota=city_id,
                    id_provinsi=province_id,
                    kode_pos=postal_code,
                    id_agama=UserConstant.LENDER_RELIGION_ID
                    if lender
                    else UserConstant.OTHER_RELIGION_ID,
                    id_status_perkawinan=marital_status,
                    id_pekerjaan=job_id,
                    id_bidang_pekerjaan=job_industry_id,
                    id_pekerjaan_online=ApplicationConstant.JOB_ONLINE_ID,
                    pendapatan=monthly_income_id,
                    pengalaman_kerja=work_experience,
                    id_pendidikan=education_id,
                    nama_perwakilan=representative,
                    no_identitas_perwakilan=representative_number,
                )

                # Updating log
                pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED, upload_data=request
                )
                print("Hit ")
                status_code, response = send_to_pusdafil_with_retry_script(
                    PusdafilService.REPORT_NEW_USER_REGISTRATION, request, pusdafil_upload
                )

                return status_code, request, response

            else:
                raise Exception("This user is not eligible to be sent to pusdafil")
        except Exception as e:
            if pusdafil_upload:
                pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED_ERROR,
                    error={"name": "Exception", "message": str(e)},
                )

            return e
    else:
        return 200, None, "Already sent succces smore than once"


def send_to_pusdafil_with_retry_script(request_name, request, pusdafil_upload, max_retry_count=3):
    import json
    import time

    from requests.exceptions import (
        ConnectionError,
        ConnectTimeout,
        ReadTimeout,
        RequestException,
        Timeout,
    )

    from juloserver.pusdafil.exceptions import JuloClientTimeout

    client = get_pusdafil_client()
    retry_count = 1

    while retry_count <= max_retry_count:
        try:
            status_code, response = client.send(request_name, request)

            # Updating log
            if status_code == 200:
                error_message = None
                for data in response["data"]:
                    if data["error"]:
                        error_message = CommonUtils.get_error_message(data['message'])
                        break
                if not error_message:
                    pusdafil_upload.update_safely(
                        status=PusdafilUpload.STATUS_SUCCESS, retry_count=retry_count
                    )
                else:
                    pusdafil_upload.update_safely(
                        status=PusdafilUpload.STATUS_FAILED,
                        error={"name": "PusdafilUploadError", "message": error_message},
                        retry_count=retry_count,
                    )
            else:
                message = response
                if type(response) is dict:
                    message = json.dumps(response)

                pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_FAILED,
                    error={"name": "PusdafilAPIError", "message": message},
                    retry_count=retry_count,
                )

            return status_code, response
        except (ConnectionError, ConnectTimeout, ReadTimeout, Timeout, RequestException) as e:
            error = str(e)

            # Updating log
            pusdafil_upload.update_safely(
                status=PusdafilUpload.STATUS_ERROR,
                error={"name": type(e).__name__, "message": error},
                retry_count=retry_count,
            )

            retry_seconds = pow(3, retry_count)

            time.sleep(retry_seconds)

            retry_count += 1
        except Exception as e:
            raise JuloException(str(e))

    if retry_count > max_retry_count:
        raise JuloClientTimeout("Exceeding max retry attempts")


def resend_existing_user_registration_to_pusdafil() -> None:

    dana_customer_list = (
        DanaCustomerData.objects.filter(
            customer__application__marital_status__isnull=False,
            customer__application__address_provinsi__isnull=False,
            customer__application__address_kabupaten__isnull=False,
            customer__application__address_kodepos__isnull=False,
            customer__application__gender__isnull=False,
            customer__application__job_type__isnull=False,
            customer__application__job_industry__isnull=False,
            customer__application__monthly_income__isnull=False,
        )
        .select_related(
            'customer', 'customer__application'
        )
        .values_list(
            'customer__user__id',
        )
    )

    counter = 0

    for dana_customer_tuple in dana_customer_list.iterator():
        (user_id, ) = dana_customer_tuple

        do_resend_existing_user_registration_to_pusdafil(user_id)

        print("{} - User {} successfuly resent to pusdafil".format(counter, user_id))

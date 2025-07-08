import json
import time
import logging
import re
from builtins import object, str

from django.contrib.auth.models import User
from django.db.models import Sum
from django.utils import timezone
from requests.exceptions import (
    ConnectionError,
    ConnectTimeout,
    ReadTimeout,
    RequestException,
    Timeout,
)

from juloserver.followthemoney.models import LenderBankAccount, LenderCurrent
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Application,
    ApplicationHistory,
    CreditScore,
    Customer,
    FeatureSetting,
    Loan,
    LoanHistory,
    Payment,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.pusdafil.clients import get_pusdafil_client
from juloserver.pusdafil.constants import (
    PUSDAFIL_ORGANIZER_ID,
    ApplicationConstant,
    EducationConstant,
    GenderConstant,
    LoanConstant,
    RequestDataConstant,
    UserConstant,
    cities,
    home_statuses,
    job_industries,
    jobs,
    provinces,
    marital_statuses,
    genders,
)
from juloserver.pusdafil.exceptions import JuloClientTimeout
from juloserver.pusdafil.models import PusdafilUpload
from juloserver.pusdafil.utils import CommonUtils

logger = logging.getLogger(__name__)


class PusdafilService(object):
    REPORT_NEW_USER_REGISTRATION = "reg_pengguna"
    REPORT_NEW_LENDER_REGISTRATION = "reg_lender"
    REPORT_NEW_BORROWER_REGISTRATION = "reg_borrower"
    REPORT_NEW_APPLICATION_REGISTRATION = "pengajuan_pinjaman"
    REPORT_NEW_LOAN_REGISTRATION = "pengajuan_pemberian_pinjaman"
    REPORT_NEW_LOAN_APPROVED = "transaksi_pinjam_meminjam"
    REPORT_NEW_LOAN_PAYMENT_CREATION = "pembayaran_pinjaman"

    def __init__(self, organizer_id, client):
        self.organizer_id = organizer_id
        self.client = client

        self.pusdafil_upload = None

    def report_new_user_registration(self, user_id, force=False):
        if not force:
            existing_pusdafil_upload = PusdafilUpload.objects.filter(
                name=PusdafilService.REPORT_NEW_USER_REGISTRATION,
                status=PusdafilUpload.STATUS_SUCCESS,
                identifier=user_id,
            )

            if existing_pusdafil_upload:
                return 200, None, None

        try:
            user = User.objects.get(pk=user_id)

            customer = Customer.objects.filter(user=user).first()
            lender = LenderCurrent.objects.filter(user=user).first()
            application = Application.objects.filter(customer=customer).order_by("cdate").last()

            if lender or application.fullname:
                # Initiating log
                self.initiate_pusdafil_upload_object(
                    PusdafilService.REPORT_NEW_USER_REGISTRATION, user_id
                )

                # identity number
                identity_number = ''

                if user.id in ApplicationConstant.LEGAL_ENTITY_USER_IDS:
                    identity_number = ApplicationConstant.LEGAL_ENTITY_IDENTITY_NUMBER
                elif customer is not None:
                    if application.is_dana_flow():
                        identity_number = application.dana_customer_data.nik
                    elif (
                        application.product_line_code
                        and application.product_line_code == ProductLineCodes.AXIATA_WEB
                        and hasattr(application, 'partnership_customer_data')
                        and application.partnership_customer_data.nik
                    ):
                        # Only For Axiata Compliance Web App that have product line code 305
                        identity_number = application.partnership_customer_data.nik
                    else:
                        identity_number = application.ktp

                # npwp
                npwp = ''

                if user.id in ApplicationConstant.LEGAL_ENTITY_USER_IDS:
                    npwp = ApplicationConstant.LEGAL_ENTITY_IDENTITY_NUMBER
                elif customer is not None:
                    npwp = None

                # gender
                gender = GenderConstant.GENDER_MALE

                if lender:
                    gender = GenderConstant.GENDER_LENDER
                elif application and application.gender in genders:
                    gender = genders.get(application.gender)

                address = ApplicationConstant.ADDRESS_DEFAULT_VALUE
                city_id = ApplicationConstant.CITY_DEFAULT_ID
                province_id = ApplicationConstant.PROVINCE_DEFAULT_ID
                postal_code = ''

                if application:
                    address_street_num = application.address_street_num
                    if application.is_dana_flow() and hasattr(
                        application.customer, 'dana_customer_data'
                    ):
                        address_street_num = application.customer.dana_customer_data.address

                    if address_street_num and len(address_street_num) > 1:
                        address = address_street_num
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

                if application and application.marital_status in marital_statuses:
                    marital_status = marital_statuses.get(application.marital_status)
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
                            work_experience = (
                                ApplicationConstant.WORK_EXPERIENCE_ONE_YEAR_TO_LESS_THAN_TWO_YEAR
                            )
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
                    id_penyelenggara=str(self.organizer_id),
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
                self.pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED, upload_data=request
                )

                status_code, response = self.send_to_pusdafil_with_retry(
                    PusdafilService.REPORT_NEW_USER_REGISTRATION, request
                )

                return status_code, request, response
            else:
                raise Exception("This user is not eligible to be sent to pusdafil")
        except Exception as e:
            if self.pusdafil_upload:
                self.pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED_ERROR,
                    error={"name": "Exception", "message": str(e)},
                )
            return should_raise_error(e)

    def report_new_lender_registration(self, lender_id):
        existing_pusdafil_upload = PusdafilUpload.objects.filter(
            name=PusdafilService.REPORT_NEW_LENDER_REGISTRATION,
            status=PusdafilUpload.STATUS_SUCCESS,
            identifier=lender_id,
        )

        if existing_pusdafil_upload:
            return 200, None, None

        try:
            # Initiating log
            self.initiate_pusdafil_upload_object(
                PusdafilService.REPORT_NEW_LENDER_REGISTRATION, lender_id
            )

            lender = LenderCurrent.objects.get(pk=lender_id)

            request = dict(
                id_penyelenggara=str(self.organizer_id),
                id_pengguna=str(lender.user.id),
                id_lender=str(lender.id),
                id_negara_domisili=RequestDataConstant.DOMICILE_COUNTRY_INDONESIA,
                id_kewarganegaraan=None,
                sumber_dana=RequestDataConstant.SOURCE_OF_FUND_OTHERS,
            )

            # Updating log
            self.pusdafil_upload.update_safely(
                status=PusdafilUpload.STATUS_QUERIED, upload_data=request
            )

            status_code, response = self.send_to_pusdafil_with_retry(
                PusdafilService.REPORT_NEW_LENDER_REGISTRATION, request
            )

            return status_code, request, response
        except Exception as e:
            if self.pusdafil_upload:
                self.pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED_ERROR,
                    error={"name": "Exception", "message": str(e)},
                )
            return should_raise_error(e)

    def report_new_borrower_registration(self, borrower_id, force=False):
        if force:
            existing_pusdafil_upload = PusdafilUpload.objects.filter(
                name=PusdafilService.REPORT_NEW_BORROWER_REGISTRATION,
                status=PusdafilUpload.STATUS_SUCCESS,
                identifier=borrower_id,
            )

            if existing_pusdafil_upload:
                return 200, None, None

        try:
            customer = Customer.objects.get(pk=borrower_id)

            application = (
                Application.objects.filter(customer_id=customer.id).order_by("cdate").last()
            )

            # check if application is eligible to be sent to pusdafil
            if (
                application.ktp
                and len(application.ktp) > 1
                and application.fullname
                and len(application.fullname) > 1
            ):

                # Initiating log
                self.initiate_pusdafil_upload_object(
                    PusdafilService.REPORT_NEW_BORROWER_REGISTRATION, borrower_id
                )

                request = dict(
                    id_penyelenggara=str(self.organizer_id),
                    id_pengguna=str(customer.user.id),
                    id_borrower=str(customer.id),
                    total_aset=RequestDataConstant.DEFAULT_TOTAL_ASSET,
                    status_kepemilikan_rumah=RequestDataConstant.OWN_HOUSE
                    if application.home_status in home_statuses
                    else RequestDataConstant.NOT_OWN_HOUSE,
                )

                # Updating log
                self.pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED, upload_data=request
                )

                status_code, response = self.send_to_pusdafil_with_retry(
                    PusdafilService.REPORT_NEW_BORROWER_REGISTRATION, request
                )

                return status_code, request, response
            else:
                raise Exception("This borrower is not eligible to be sent to pusdafil")
        except Exception as e:
            if self.pusdafil_upload:
                self.pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED_ERROR,
                    error={"name": "Exception", "message": str(e)},
                )
            return should_raise_error(e)

    def report_new_application_registration(self, application_id, force=False):
        application = Application.objects.get_or_none(id=application_id)

        loan = Loan.objects.filter(application=application).order_by("cdate").last()

        if not loan:
            loan = Loan.objects.filter(account=application.account).order_by("cdate").last()

        if not loan:
            raise Exception("There is no loan associated with this application")
        if not force:
            existing_pusdafil_upload = PusdafilUpload.objects.filter(
                name=PusdafilService.REPORT_NEW_APPLICATION_REGISTRATION,
                status=PusdafilUpload.STATUS_SUCCESS,
                identifier=loan.id,
            )

            if existing_pusdafil_upload:
                return 200, None, None

        try:
            application_history = ApplicationHistory.objects.filter(
                application=application,
                status_new__in=[
                    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                    ApplicationStatusCodes.FORM_GENERATED,
                    ApplicationStatusCodes.LOC_APPROVED,
                    ApplicationStatusCodes.FORM_PARTIAL,
                ],
            ).first()

            loan_history = (
                LoanHistory.objects.filter(
                    loan=loan, status_new__in=[LoanStatusCodes.LENDER_APPROVAL]
                )
                .order_by("cdate")
                .last()
            )

            if application_history:
                publication_plan = loan.fund_transfer_ts.date() - application_history.cdate.date()
                publication_realization = (
                    loan.fund_transfer_ts.date() - application_history.cdate.date()
                )
            elif loan_history:
                publication_plan = loan.fund_transfer_ts.date() - loan_history.cdate.date()
                publication_realization = loan.fund_transfer_ts.date() - loan_history.cdate.date()
            else:
                raise Exception(
                    "There is no expected application_history "
                    "or loan_history for this application"
                )

            app_am_du_exist = application.loan_amount_request and application.loan_duration_request
            loan_am_du_exist = loan.loan_amount and loan.loan_duration

            address_street_num = application.address_street_num
            if application.is_dana_flow() and hasattr(application.customer, 'dana_customer_data'):
                address_street_num = application.customer.dana_customer_data.address

            # check if application is eligible to be sent to pusdafil
            if (
                application.status
                in [
                    ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                    ApplicationStatusCodes.LOC_APPROVED,
                ]
                and application.ktp
                and len(application.ktp) > 1
                and application.fullname
                and len(application.fullname) > 1
                and address_street_num
                and len(address_street_num) > 1
                and (app_am_du_exist or loan_am_du_exist)
                and (application_history or loan_history)
                and publication_plan.days is not None
                and publication_realization.days is not None
            ):

                # Initiating log
                self.initiate_pusdafil_upload_object(
                    PusdafilService.REPORT_NEW_APPLICATION_REGISTRATION, loan.id
                )

                credit_score = (
                    CreditScore.objects.filter(application=application).order_by("cdate").last()
                )

                application_status = 0

                if application.status in (
                    ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                    ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
                    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
                ):
                    application_status = 1
                elif application.status in (
                    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    ApplicationStatusCodes.APPLICATION_DENIED,
                ):
                    application_status = 2
                elif application.status in (
                    ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                    ApplicationStatusCodes.LOC_APPROVED,
                ):
                    application_status = 3
                elif application.status in (
                    ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                ):
                    application_status = 6

                start_publication_date = None

                if application_history:
                    start_publication_date = application_history.cdate.strftime("%Y-%m-%d")
                elif loan_history:
                    start_publication_date = loan_history.cdate.strftime("%Y-%m-%d")

                account = application.account

                account_max_limit = account.get_account_limit.max_limit if account else None
                loan_count = account.loan_set.count() if account else LoanConstant.COUNT_DEFAULT

                trx_method = loan.transaction_method

                request = dict(
                    id_penyelenggara=str(self.organizer_id),
                    id_pinjaman=str(application.application_xid),
                    id_borrower=str(application.customer.id),
                    id_syariah=LoanConstant.LENDING_TYPE,
                    id_status_pengajuan_pinjaman=application_status,
                    nama_pinjaman=trx_method.fe_display_name if trx_method else 'Tarik Dana',
                    tgl_pengajuan_pinjaman=application.cdate.strftime("%Y-%m-%d"),
                    nilai_permohonan_pinjaman=application.loan_amount_request
                    if application.loan_amount_request
                    else loan.loan_amount,
                    jangka_waktu_pinjaman=application.loan_duration_request
                    if application.loan_duration_request
                    else loan.loan_duration,
                    satuan_jangka_waktu_pinjaman=LoanConstant.TENURE_RATE_UNIT,
                    penggunaan_pinjaman=LoanConstant.LOAN_PURPOSE_DEFAULT,
                    agunan=LoanConstant.COLLATERAL,
                    jenis_agunan=LoanConstant.COLLATERAL_DEFAULT,
                    rasio_pinjaman_nilai_agunan=LoanConstant.COLLATERAL_RATIO,
                    permintaan_jaminan='',
                    rasio_pinjaman_aset=LoanConstant.ASSET_RATIO,
                    cicilan_bulan=application.total_current_debt or None,
                    rating_pengajuan_pinjaman=credit_score.score if credit_score else 'B-',
                    nilai_plafond=account_max_limit,
                    nilai_pengajuan_pinjaman=loan.loan_amount,
                    suku_bunga_pinjaman=loan.product.interest_rate,
                    satuan_suku_bunga_pinjaman=LoanConstant.INTEREST_RATE_UNIT,
                    jenis_bunga=LoanConstant.INTEREST_TYPE,
                    tgl_mulai_publikasi_pinjaman=start_publication_date,
                    rencana_jangka_waktu_publikasi=LoanConstant.WAITING_DAY_DEFAULT,
                    realisasi_jangka_waktu_publikasi=int(publication_realization.days) or 1,
                    tgl_mulai_pendanaan=loan.fund_transfer_ts.strftime("%Y-%m-%d")
                    if loan.fund_transfer_ts
                    else None,
                    frekuensi_pinjaman=loan_count,
                )

                # Updating log
                self.pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED, upload_data=request
                )

                status_code, response = self.send_to_pusdafil_with_retry(
                    PusdafilService.REPORT_NEW_APPLICATION_REGISTRATION, request
                )

                return status_code, request, response
            else:
                raise Exception("This application is not eligible to be reported to pusdafil.")
        except Exception as e:
            if self.pusdafil_upload:
                self.pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED_ERROR,
                    error={"name": "Exception", "message": str(e)},
                )
            return should_raise_error(e)

    def report_new_loan_registration(self, loan_id, force=False):
        if not force:
            existing_pusdafil_upload = PusdafilUpload.objects.filter(
                name=PusdafilService.REPORT_NEW_LOAN_REGISTRATION,
                status=PusdafilUpload.STATUS_SUCCESS,
                identifier=loan_id,
            )

            if existing_pusdafil_upload:
                return 200, None, None

        try:
            loan = Loan.objects.get(pk=loan_id)
            application = Application.objects.filter(loan=loan).order_by("cdate").last()

            if not application:
                application = (
                    Application.objects.filter(account=loan.account).order_by("cdate").last()
                )

            address_street_num = application.address_street_num
            if application.is_dana_flow() and hasattr(application.customer, 'dana_customer_data'):
                address_street_num = application.customer.dana_customer_data.address

            # check if loan is eligible to be sent to pusdafil
            if (
                application
                and application.status
                in [
                    ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                    ApplicationStatusCodes.LOC_APPROVED,
                ]
                and application.ktp
                and len(application.ktp) > 1
                and application.fullname
                and len(application.fullname) > 1
                and address_street_num
                and len(address_street_num) > 1
            ):

                # Initiating log
                self.initiate_pusdafil_upload_object(
                    PusdafilService.REPORT_NEW_LOAN_REGISTRATION, loan_id
                )

                lender = LenderCurrent.objects.get(lender_name='jtp')
                lender_bank_account = LenderBankAccount.objects.filter(
                    lender=lender, bank_account_type='repayment_va'
                ).first()

                request = dict(
                    id_penyelenggara=str(self.organizer_id),
                    id_pinjaman=str(application.application_xid),
                    id_borrower=str(application.customer_id),
                    # id_lender=str(lender.id),
                    id_lender='1',
                    no_perjanjian_lender=str(lender.pks_number),
                    tgl_perjanjian_lender=loan.cdate.strftime("%Y-%m-%d"),
                    tgl_penawaran_pemberian_pinjaman=loan.cdate.strftime("%Y-%m-%d"),
                    nilai_penawaran_pinjaman=loan.loan_amount,
                    nilai_penawaran_disetujui=loan.loan_amount,
                    no_va_lender=str(lender_bank_account.account_number),
                )

                # Updating log
                self.pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED, upload_data=request
                )

                status_code, response = self.send_to_pusdafil_with_retry(
                    PusdafilService.REPORT_NEW_LOAN_REGISTRATION, request
                )

                return status_code, request, response
            else:
                raise Exception("This new loan is not eligible to be sent to pusdafil")
        except Exception as e:
            if self.pusdafil_upload:
                self.pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED_ERROR,
                    error={"name": "Exception", "message": str(e)},
                )
            return should_raise_error(e)

    def report_new_loan_approved(self, loan_id, force=False):
        if not force:
            existing_pusdafil_upload = PusdafilUpload.objects.filter(
                name=PusdafilService.REPORT_NEW_LOAN_APPROVED,
                status=PusdafilUpload.STATUS_SUCCESS,
                identifier=loan_id,
            )

            if existing_pusdafil_upload:
                return 200, None, None

        try:
            loan = Loan.objects.get(pk=loan_id)
            application = Application.objects.filter(loan=loan).order_by("cdate").last()

            if not application:
                application = (
                    Application.objects.filter(account=loan.account).order_by("cdate").last()
                )

            # Getting application history as in legacy query
            application_history = (
                ApplicationHistory.objects.filter(
                    application=application,
                    status_new__in=[
                        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                        ApplicationStatusCodes.FORM_GENERATED,
                    ],
                )
                .order_by("cdate")
                .last()
            )

            # Getting loan history as in legacy query
            loan_history = (
                LoanHistory.objects.filter(
                    loan=loan, status_new__in=[LoanStatusCodes.LENDER_APPROVAL]
                )
                .order_by("cdate")
                .last()
            )

            address_street_num = application.address_street_num
            if application.is_dana_flow() and hasattr(application.customer, 'dana_customer_data'):
                address_street_num = application.customer.dana_customer_data.address

            # check if loan approval is eligible to be sent to pusdafil
            if (
                application
                and application.status
                in [
                    ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                    ApplicationStatusCodes.LOC_APPROVED,
                ]
                and application.ktp
                and len(application.ktp) > 1
                and application.fullname
                and len(application.fullname) > 1
                and address_street_num
                and len(address_street_num) > 1
                and (application_history or loan_history)
            ):

                # Initiating log
                self.initiate_pusdafil_upload_object(
                    PusdafilService.REPORT_NEW_LOAN_APPROVED, loan_id
                )

                lender = LenderCurrent.objects.get(lender_name='jtp')
                lender_bank_account = LenderBankAccount.objects.filter(
                    lender=lender, bank_account_type='repayment_va'
                ).first()
                payment = Payment.objects.filter(loan=loan).order_by('cdate').first()

                payment_kind_id = 2

                if application.product_line_code in [ProductLineCodes.MTL1, ProductLineCodes.MTL2]:
                    payment_kind_id = 1

                request = dict(
                    id_penyelenggara=str(self.organizer_id),
                    id_pinjaman=str(application.application_xid),
                    id_borrower=str(application.customer.id),
                    id_lender=str(lender.id),
                    id_transaksi=str(application.application_xid),
                    no_perjanjian_borrower=str(application.application_xid),
                    tgl_perjanjian_borrower=loan.sphp_accepted_ts.strftime("%Y-%m-%d")
                    if loan.sphp_accepted_ts
                    else None,
                    nilai_pendanaan=loan.loan_amount,
                    suku_bunga_pinjaman=loan.product.interest_rate,
                    satuan_suku_bunga_pinjaman=LoanConstant.INTEREST_RATE_UNIT,
                    id_jenis_pembayaran=payment_kind_id,
                    id_frekuensi_pembayaran=LoanConstant.INSTALMENT_FREQUENCY,
                    nilai_angsuran=loan.installment_amount,
                    objek_jaminan=None,
                    jangka_waktu_pinjaman=loan.loan_duration,
                    satuan_jangka_waktu_pinjaman=LoanConstant.TENURE_RATE_UNIT,
                    tgl_jatuh_tempo=payment.due_date.strftime("%Y-%m-%d")
                    if payment.due_date
                    else None,
                    tgl_pendanaan=loan.fund_transfer_ts.strftime("%Y-%m-%d")
                    if loan.fund_transfer_ts
                    else None,
                    tgl_penyaluran_dana=loan.fund_transfer_ts.strftime("%Y-%m-%d")
                    if loan.fund_transfer_ts
                    else None,
                    no_ea_transaksi=lender_bank_account.account_number,
                    frekuensi_pendanaan=application.application_number
                    if application.application_number
                    else 0,
                )

                # Updating log
                self.pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED, upload_data=request
                )

                status_code, response = self.send_to_pusdafil_with_retry(
                    PusdafilService.REPORT_NEW_LOAN_APPROVED, request
                )

                return status_code, request, response
            else:
                raise Exception("This loan approval is not eligible to be sent to pusdafil")
        except Exception as e:
            if self.pusdafil_upload:
                self.pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED_ERROR,
                    error={"name": "Exception", "message": str(e)},
                )
            return should_raise_error(e)

    def report_new_loan_payment_creation(self, payment_id):
        if self.check_existing_upload_object(
            PusdafilService.REPORT_NEW_LOAN_PAYMENT_CREATION, payment_id
        ):
            logger.warning(
                {
                    'action': 'report_new_loan_payment_creation',
                    'name': 'PusdafilService.REPORT_NEW_LOAN_PAYMENT_CREATION',
                    'identifier': payment_id,
                    'status': 'sent_success exist',
                }
            )
            return None, None, None

        try:
            payment = Payment.objects.get(pk=payment_id)
            if payment.payment_status_id not in PaymentStatusCodes.paid_status_codes():
                logger.info(
                    {
                        'action': 'report_new_loan_payment_creation',
                        'message': 'skip report_new_loan_payment_creation',
                        'payment_id': payment_id,
                        'payment_status_code': payment.payment_status_id,
                        'payment_udate': str(payment.udate),
                    }
                )
                return None, None, None

            loan = payment.loan
            application = Application.objects.filter(loan=loan).order_by("cdate").last()

            if not application:
                application = (
                    Application.objects.filter(account=loan.account).order_by("cdate").last()
                )

            address_street_num = application.address_street_num
            if application.is_dana_flow() and hasattr(application.customer, 'dana_customer_data'):
                address_street_num = application.customer.dana_customer_data.address

            # check if payment creation is eligible to be sent to pusdafil
            if (
                application
                and application.status
                in [
                    ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                    ApplicationStatusCodes.LOC_APPROVED,
                ]
                and application.ktp
                and len(application.ktp) > 1
                and application.fullname
                and len(application.fullname) > 1
                and address_street_num
                and len(address_street_num) > 1
                and payment.paid_amount != 0
                and payment.paid_date
            ):

                # Initiating log
                self.initiate_pusdafil_upload_object(
                    PusdafilService.REPORT_NEW_LOAN_PAYMENT_CREATION, payment_id
                )

                lender = LenderCurrent.objects.get(lender_name='jtp')

                if loan.status in (
                    LoanStatusCodes.INACTIVE,
                    LoanStatusCodes.LOAN_90DPD,
                    LoanStatusCodes.LOAN_120DPD,
                    LoanStatusCodes.LOAN_150DPD,
                    LoanStatusCodes.LOAN_180DPD,
                    LoanStatusCodes.RENEGOTIATED,
                    LoanStatusCodes.SELL_OFF,
                ):
                    remaining_due_amount = 0
                else:
                    total_paid_principal = (
                        loan.payment_set.paid().aggregate(total=Sum('paid_principal')).get('total')
                        or 0
                    )
                    remaining_due_amount = loan.loan_amount - total_paid_principal

                loan_status_id = 1

                if loan.status in (
                    LoanStatusCodes.CURRENT,
                    LoanStatusCodes.LOAN_1DPD,
                    LoanStatusCodes.LOAN_5DPD,
                    LoanStatusCodes.PAID_OFF,
                ):
                    loan_status_id = 1
                elif loan.status in (
                    LoanStatusCodes.LOAN_30DPD,
                    LoanStatusCodes.LOAN_60DPD,
                ):
                    loan_status_id = 2
                elif loan.status in (
                    LoanStatusCodes.INACTIVE,
                    LoanStatusCodes.LOAN_90DPD,
                    LoanStatusCodes.LOAN_120DPD,
                    LoanStatusCodes.LOAN_150DPD,
                    LoanStatusCodes.LOAN_180DPD,
                    LoanStatusCodes.RENEGOTIATED,
                    LoanStatusCodes.SELL_OFF,
                ):
                    loan_status_id = 3

                next_payment = payment.get_next_payment()

                request = dict(
                    id_penyelenggara=str(self.organizer_id),
                    id_pinjaman=str(application.application_xid),
                    id_borrower=str(application.customer.id),
                    id_lender=str(lender.id),
                    id_transaksi=str(application.application_xid),
                    id_pembayaran=str(payment.id),
                    tgl_jatuh_tempo=payment.due_date.strftime("%Y-%m-%d"),
                    tgl_jatuh_tempo_selanjutnya=next_payment.due_date.strftime("%Y-%m-%d")
                    if next_payment
                    else payment.due_date.strftime("%Y-%m-%d"),
                    tgl_pembayaran_borrower=payment.paid_date.strftime("%Y-%m-%d")
                    if payment.paid_date
                    else None,
                    tgl_pembayaran_penyelenggara=payment.paid_date.strftime("%Y-%m-%d")
                    if payment.paid_date
                    else None,
                    sisa_pinjaman_berjalan=remaining_due_amount if remaining_due_amount >= 0 else 0,
                    id_status_pinjaman=loan_status_id,
                    tgl_pelunasan_borrower=payment.paid_date.strftime("%Y-%m-%d")
                    if payment.paid_date
                    else None,
                    tgl_pelunasan_penyelenggara=payment.paid_date.strftime("%Y-%m-%d")
                    if payment.paid_date
                    else None,
                    denda=payment.late_fee_amount if payment.late_fee_amount >= 0 else 0,
                    nilai_pembayaran=payment.paid_amount if payment.paid_amount >= 0 else 0,
                )

                # Updating log
                self.pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED, upload_data=request
                )

                status_code, response = self.send_to_pusdafil_with_retry(
                    PusdafilService.REPORT_NEW_LOAN_PAYMENT_CREATION, request
                )

                return status_code, request, response
            else:
                raise Exception("Payment is not eligible to be reported to pusdafil")
        except Exception as e:
            if self.pusdafil_upload:
                self.pusdafil_upload.update_safely(
                    status=PusdafilUpload.STATUS_QUERIED_ERROR,
                    error={"name": "Exception", "message": str(e)},
                )
            return should_raise_error(e)

    def initiate_pusdafil_upload_object(self, name, identifier):
        self.pusdafil_upload = PusdafilUpload.objects.create(
            name=name, identifier=identifier, retry_count=0, status=PusdafilUpload.STATUS_INITIATED
        )

    def send_to_pusdafil_with_retry(self, request_name, request, max_retry_count=3):
        retry_count = 1

        while retry_count <= max_retry_count:
            try:
                status_code, response = self.client.send(request_name, request)

                # Updating log
                if status_code == 200:
                    error_message = None
                    for data in response["data"]:
                        if data["error"]:
                            error_message = CommonUtils.get_error_message(data['message'])
                            break
                    if not error_message:
                        self.pusdafil_upload.update_safely(
                            status=PusdafilUpload.STATUS_SUCCESS, retry_count=retry_count
                        )
                    else:
                        self.pusdafil_upload.update_safely(
                            status=PusdafilUpload.STATUS_FAILED,
                            error={"name": "PusdafilUploadError", "message": error_message},
                            retry_count=retry_count,
                        )
                else:
                    message = response
                    if type(response) is dict:
                        message = json.dumps(response)

                    self.pusdafil_upload.update_safely(
                        status=PusdafilUpload.STATUS_FAILED,
                        error={"name": "PusdafilAPIError", "message": message},
                        retry_count=retry_count,
                    )

                return status_code, response
            except (ConnectionError, ConnectTimeout, ReadTimeout, Timeout, RequestException) as e:
                error = str(e)

                # Updating log
                self.pusdafil_upload.update_safely(
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

    def check_existing_upload_object(self, name, identifier):
        return PusdafilUpload.objects.filter(
            name=name, identifier=identifier, status=PusdafilUpload.STATUS_SUCCESS
        ).exists()


def get_pusdafil_service():
    pusdafil_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name='pusdafil', is_active=True
    )
    if not pusdafil_feature_setting:
        return

    return PusdafilService(PUSDAFIL_ORGANIZER_ID, get_pusdafil_client())


def should_raise_error(error):
    pusdafil_raise_error_sett = FeatureSetting.objects.get_or_none(
        feature_name='pusdafil_raise_error', is_active=True
    )
    if pusdafil_raise_error_sett:
        raise error

    return 500, None, None


def validate_pusdafil_customer_data(applications):
    """
    Make sure This field are exist and can be mapped properly,
    with proper validation
    1. application.gender
    2. application.address_kabupaten
    3. application.address_provinsi
    4. application.address_kodepos
    5. application.marital_status
    6. application.job_type
    7. application.job_industry
    8. application.monthly_income
    """
    validated_application = []
    errors = []
    for application in applications:
        error = []
        # gender
        if not application.gender or not genders.get(application.gender):
            error.append("gender not found or cannot be mapped")

        # address_kabupaten
        if not application.address_kabupaten or not cities.get(
            application.address_kabupaten.upper()
        ):
            error.append("address_kabupaten not found or cannot be mapped")

        # address_provinsi
        if not application.address_provinsi or not provinces.get(
            application.address_provinsi.upper()
        ):
            error.append("address_provinsi not found or cannot be mapped")

        # address_kodepos
        # make sure only 5 digit numeric
        pattern = r'^\d{5}$'
        if not re.match(pattern, str(application.address_kodepos)):
            error.append("address_kodepos not found or is not 5 digit numeric")

        # matrial_status
        if not application.marital_status or not marital_statuses.get(application.marital_status):
            error.append("marital_status not found or cannot be mapped")

        # job_type
        if not application.job_type or not jobs.get(application.job_type):
            error.append("job_type not found or cannot be mapped")

        # job_industry
        if not application.job_industry or not job_industries.get(application.job_industry):
            error.append("job_industry not found or cannot be mapped")

        # monthly_income
        if not application.monthly_income:
            error.append("monthly_income not found")

        if not error:
            validated_application.append(application)
        else:
            errors.append(
                {
                    'application': application.id,
                    'error': error,
                }
            )

    if errors:
        logger.info(
            {
                'action': 'validate_pusdafil_customer_data',
                'message': 'application data not complete, data not sent to pusdafil',
                'error': errors,
            }
        )

    return validated_application

import json
from builtins import str
from datetime import date, datetime

import mock
import pytest
import pytz
import six
from django.conf import settings
from django.test.testcases import TestCase
from requests.exceptions import ConnectionError

from juloserver.core.utils import ObjectMock
from juloserver.followthemoney.factories import (
    LenderBankAccountFactory,
    LenderCurrentFactory,
)
from juloserver.followthemoney.models import LenderCurrent
from juloserver.julo.models import Application, ApplicationHistory, Customer, Loan
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationHistoryFactory,
    AuthUserFactory,
    CreditScoreFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
    PartnerFactory,
    PaymentFactory,
    ProductLineFactory,
    ProductLookupFactory,
    StatusLookupFactory,
)
from juloserver.pusdafil.constants import (
    PUSDAFIL_ORGANIZER_ID,
    cities,
    home_statuses,
    job_industries,
    jobs,
    provinces,
)
from juloserver.pusdafil.services import get_pusdafil_service


@pytest.mark.django_db
class TestObjectPusdafilServices(TestCase):
    def setUp(self):
        self.organizer_id = PUSDAFIL_ORGANIZER_ID
        self.mocked_client_response = (
            200,
            dict(
                request_status=200,
                data=[
                    dict(request_status=200, error=False),
                    dict(request_status=200, error=False),
                    dict(request_status=200, error=False),
                    dict(request_status=200, error=False),
                    dict(request_status=200, error=False),
                    dict(request_status=200, error=False),
                    dict(request_status=200, error=False),
                ],
            ),
        )

        self.data = dict(
            id_negara_domisili=0,
            id_pengguna='514133',
            id_lender='1',
            sumber_dana='Lain-lain',
            id_kewarganegaraan=None,
            id_penyelenggara=PUSDAFIL_ORGANIZER_ID,
        )

        self.mocked_response = ObjectMock(
            status_code=200,
            content=json.dumps(
                dict(
                    request_status=200,
                    data=[
                        dict(request_status=200, error=False),
                        dict(request_status=200, error=False),
                    ],
                )
            ),
        )

    @mock.patch("juloserver.pusdafil.services.PusdafilService.send_to_pusdafil_with_retry")
    def test_task_report_new_user_customer_registration(self, mocked_pusdafil_client):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        pusdafil_service = get_pusdafil_service()

        mocked_pusdafil_client.return_value = self.mocked_client_response

        # user type customer
        user = AuthUserFactory()
        customer = CustomerFactory(user=user, gender='Pria')

        ApplicationFactory(
            customer=customer,
            home_status='Milik sendiri, lunas',
            ktp="2763516253412344",
            fullname="Brad Pitt",
            marital_status='Menikah',
            job_industry='Media',
            last_education='SD',
            address_street_num="Omah sweet home",
        )

        application = Application.objects.filter(customer=customer).order_by("cdate").last()

        status_code, request, response = pusdafil_service.report_new_user_registration(
            user_id=user.id
        )

        self.assertEqual(status_code, 200)

        lender = LenderCurrent.objects.filter(user=user).first()

        # identity number
        identity_number = ''

        if user.id == 514133:
            identity_number = '802965566015000'
        elif customer is not None:
            identity_number = application.ktp

        # npwp
        npwp = ''

        if user.id == 514133:
            npwp = '802965566015000'
        elif customer is not None:
            npwp = None

        # gender
        gender = 1

        if lender:
            gender = 3
        elif customer and customer.gender == 'Pria':
            gender = 1
        elif customer and customer.gender == 'Wanita':
            gender = 2

        # address
        address = 'alamat kosong'

        if application and len(application.address_street_num) > 1:
            address = application.address_street_num

        # city id
        city_id = 'e999'

        if application and application.address_kabupaten in cities:
            city_id = cities[application.address_kabupaten]

        # province id
        province_id = '99'

        if application and application.address_provinsi in provinces:
            province_id = provinces[application.address_provinsi]

        # postal code
        postal_code = ''

        if application:
            postal_code = application.address_kodepos

        # marital status id
        marital_status = 4

        if application and application.marital_status in ['Cerai', 'Janda / duda', 'Menikah']:
            marital_status = 1
        elif application and application.marital_status in ['Lajang']:
            marital_status = 2
        elif lender:
            marital_status = 3

        # job id
        job_id = 10

        if application and application.job_type in jobs:
            job_id = jobs[application.job_type]
        elif lender:
            job_id = 9

        # job industry id
        job_industry_id = 'e99'

        if application and application.job_industry in job_industries:
            job_industry_id = job_industries[application.job_industry]

        # monthly income id
        monthly_income_id = 'p7'

        if application and application.monthly_income < 12500000:
            monthly_income_id = '1'
        elif application and 12000001 <= application.monthly_income <= 50000000:
            monthly_income_id = '2'
        elif application and 50000001 <= application.monthly_income <= 500000000:
            monthly_income_id = '3'
        elif application and 500000001 <= application.monthly_income <= 50000000000:
            monthly_income_id = '4'
        elif application and application.monthly_income > 50000000000:
            monthly_income_id = '5'

        # work experience
        work_experience = 6

        if application:
            delta_result = date.today() - application.job_start

            if delta_result.days < 360:
                work_experience = 1
            elif 360 <= delta_result.days <= 720:
                work_experience = 2
            elif 720 <= delta_result.days <= 1080:
                work_experience = 3
            elif delta_result.days >= 1080:
                work_experience = 4
        elif lender:
            work_experience = 5

        # education id
        education_id = 9

        if application:
            if application.last_education == 'SD':
                education_id = 1
            elif application.last_education == 'SLTP':
                education_id = 2
            elif application.last_education == 'SLTA':
                education_id = 3
            elif application.last_education == 'Diploma':
                education_id = 4
            elif application.last_education == 'S1':
                education_id = 5
            elif application.last_education == 'S2':
                education_id = 6
            elif application.last_education == 'S3':
                education_id = 7
        elif lender:
            education_id = 8

        # representative name
        representative = None

        if lender:
            representative = lender.poc_name

        # representative number
        representative_number = ''

        if user.id == 514133:
            representative_number = '802965566015000'
        elif customer:
            representative_number = None

        six.assertCountEqual(
            self,
            request,
            dict(
                id_penyelenggara=str(self.organizer_id),
                id_pengguna=str(user.id),
                jenis_pengguna=2 if lender else 1,
                tgl_registrasi=user.date_joined.strftime("%Y-%m-%d"),
                nama_pengguna=lender.lender_name if lender else customer.fullname,
                jenis_identitas=3 if lender else 1,
                no_identitas=identity_number,
                no_npwp=npwp,
                id_jenis_badan_hukum=1 if lender else 6,
                tempat_lahir=application.birth_place if customer else None,
                tgl_lahir=application.dob if customer else None,
                id_jenis_kelamin=gender,
                alamat=address,
                id_kota=city_id,
                id_provinsi=province_id,
                kode_pos=postal_code,
                id_agama=7,
                id_status_perkawinan=marital_status,
                id_pekerjaan=job_id,
                id_bidang_pekerjaan=job_industry_id,
                id_pekerjaan_online=3,
                pendapatan=monthly_income_id,
                pengalaman_kerja=work_experience,
                id_pendidikan=education_id,
                nama_perwakilan=representative,
                no_identitas_perwakilan=representative_number,
            ),
        )

        self.assertEqual(response["request_status"], 200)
        self.assertEqual(response["data"][0]["error"], False)

        status_code, request, response = pusdafil_service.report_new_user_registration(
            user_id=user.id
        )

        self.assertEqual(response["request_status"], 200)
        self.assertEqual(response["data"][0]["error"], False)

    @mock.patch("juloserver.pusdafil.services.PusdafilService.send_to_pusdafil_with_retry")
    def test_task_report_new_user_lender_registration(self, mocked_pusdafil_client):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        pusdafil_service = get_pusdafil_service()

        mocked_pusdafil_client.return_value = self.mocked_client_response

        # user type lender
        user = AuthUserFactory()
        lender = LenderCurrentFactory(user=user)

        status_code, request, response = pusdafil_service.report_new_user_registration(
            user_id=user.id
        )

        self.assertEqual(status_code, 200)

        customer = Customer.objects.filter(user=user).first()
        application = Application.objects.filter(customer=customer).order_by("cdate").last()

        # identity number
        identity_number = ''

        if user.id == 514133:
            identity_number = '802965566015000'
        elif customer is not None:
            identity_number = application.ktp

        # npwp
        npwp = ''

        if user.id == 514133:
            npwp = '802965566015000'
        elif customer is not None:
            npwp = None

        # gender
        gender = 1

        if lender:
            gender = 3
        elif customer and customer.gender == 'Pria':
            gender = 1
        elif customer and customer.gender == 'Wanita':
            gender = 2

        # address
        address = 'alamat kosong'

        if application and len(application.address_street_num) > 1:
            address = application.address_street_num

        # city id
        city_id = 'e999'

        if application and application.address_kabupaten in cities:
            city_id = cities[application.address_kabupaten]

        # province id
        province_id = '99'

        if application and application.address_provinsi in provinces:
            province_id = provinces[application.address_provinsi]

        # postal code
        postal_code = ''

        if application:
            postal_code = application.address_kodepos

        # marital status id
        marital_status = 4

        if application and application.marital_status in ['Cerai', 'Janda / duda', 'Menikah']:
            marital_status = 1
        elif application and application.marital_status in ['Lajang']:
            marital_status = 2
        elif lender:
            marital_status = 3

        # job id
        job_id = 10

        if application is not None and application.job_type in jobs:
            job_id = jobs[application.job_type]
        elif lender:
            job_id = 9

        # job industry id
        job_industry_id = 'e99'

        if application and application.job_industry in job_industries:
            job_industry_id = job_industries[application.job_industry]

        # monthly income id
        monthly_income_id = 'p7'

        if application and application.monthly_income < 12500000:
            monthly_income_id = '1'
        elif application and 12000001 <= application.monthly_income <= 50000000:
            monthly_income_id = '2'
        elif application and 50000001 <= application.monthly_income <= 500000000:
            monthly_income_id = '3'
        elif application and 500000001 <= application.monthly_income <= 50000000000:
            monthly_income_id = '4'
        elif application and application.monthly_income > 50000000000:
            monthly_income_id = '5'

        # work experience
        work_experience = 6

        if application:
            delta_result = date.today() - application.job_start

            if delta_result.days < 360:
                work_experience = 1
            elif 360 <= delta_result.days <= 720:
                work_experience = 2
            elif 720 <= delta_result.days <= 1080:
                work_experience = 3
            elif delta_result.days >= 1080:
                work_experience = 4
        elif lender:
            work_experience = 5

        # education id
        education_id = 9

        if application:
            if application.last_education == 'SD':
                education_id = 1
            elif application.last_education == 'SLTP':
                education_id = 2
            elif application.last_education == 'SLTA':
                education_id = 3
            elif application.last_education == 'Diploma':
                education_id = 4
            elif application.last_education == 'S1':
                education_id = 5
            elif application.last_education == 'S2':
                education_id = 6
            elif application.last_education == 'S3':
                education_id = 7
        elif lender:
            education_id = 8

        # representative name
        representative = None

        if lender:
            representative = lender.poc_name

        # representative number
        representative_number = ''

        if user.id == 514133:
            representative_number = '802965566015000'
        elif customer:
            representative_number = None

        six.assertCountEqual(
            self,
            request,
            dict(
                id_penyelenggara=str(self.organizer_id),
                id_pengguna=str(user.id),
                jenis_pengguna=2 if lender else 1,
                tgl_registrasi=user.date_joined.strftime("%Y-%m-%d"),
                nama_pengguna=lender.lender_name if lender else customer.fullname,
                jenis_identitas=3 if lender else 1,
                no_identitas=identity_number,
                no_npwp=npwp,
                id_jenis_badan_hukum=1 if lender else 6,
                tempat_lahir=application.birth_place if customer else None,
                tgl_lahir=application.dob if customer else None,
                id_jenis_kelamin=gender,
                alamat=address,
                id_kota=city_id,
                id_provinsi=province_id,
                kode_pos=postal_code,
                id_agama=8,
                id_status_perkawinan=marital_status,
                id_pekerjaan=job_id,
                id_bidang_pekerjaan=job_industry_id,
                id_pekerjaan_online=3,
                pendapatan=monthly_income_id,
                pengalaman_kerja=work_experience,
                id_pendidikan=education_id,
                nama_perwakilan=representative,
                no_identitas_perwakilan=representative_number,
            ),
        )

        self.assertEqual(response["request_status"], 200)
        self.assertEqual(response["data"][0]["error"], False)

    @mock.patch("juloserver.pusdafil.services.PusdafilService.send_to_pusdafil_with_retry")
    def test_task_report_new_lender_registration(self, mocked_pusdafil_client):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        pusdafil_service = get_pusdafil_service()

        mocked_pusdafil_client.return_value = self.mocked_client_response

        user = AuthUserFactory()
        lender = LenderCurrentFactory(user=user)

        status_code, request, response = pusdafil_service.report_new_lender_registration(
            lender_id=lender.id
        )

        self.assertEqual(status_code, 200)

        six.assertCountEqual(
            self,
            request,
            dict(
                id_penyelenggara=str(self.organizer_id),
                id_pengguna=str(lender.user.id),
                id_lender=str(lender.id),
                id_negara_domisili=0,
                id_kewarganegaraan=None,
                sumber_dana='Lain-Lain',
            ),
        )

        self.assertEqual(response["request_status"], 200)
        self.assertEqual(response["data"][1]["error"], False)

    @mock.patch("juloserver.pusdafil.services.PusdafilService.send_to_pusdafil_with_retry")
    def test_task_report_new_borrower_registration(self, mocked_pusdafil_client):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        pusdafil_service = get_pusdafil_service()

        mocked_pusdafil_client.return_value = self.mocked_client_response

        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        application = ApplicationFactory(
            customer=customer,
            home_status='Milik sendiri, lunas',
            ktp="2763516253412344",
            fullname="Brad Pitt",
            address_street_num="Omah sweet home",
        )

        application.application_status_id = 190
        application.save()

        status_code, request, response = pusdafil_service.report_new_borrower_registration(
            borrower_id=customer.id
        )

        self.assertEqual(status_code, 200)

        six.assertCountEqual(
            self,
            request,
            dict(
                id_penyelenggara=str(self.organizer_id),
                id_pengguna=str(customer.user.id),
                id_borrower=str(customer.id),
                total_aset=0,
                status_kepemilikan_rumah=1 if application.home_status in home_statuses else 2,
            ),
        )

        self.assertEqual(response["request_status"], 200)
        self.assertEqual(response["data"][2]["error"], False)

    @mock.patch("juloserver.pusdafil.services.PusdafilService.send_to_pusdafil_with_retry")
    def test_task_report_new_application_registration(self, mocked_pusdafil_client):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        pusdafil_service = get_pusdafil_service()

        mocked_pusdafil_client.return_value = self.mocked_client_response

        customer = CustomerFactory()
        product_line = ProductLineFactory()
        application = ApplicationFactory(
            customer=customer,
            product_line=product_line,
            ktp="2763516253412344",
            fullname="Brad Pitt",
            address_street_num="Omah sweet home",
        )

        application.application_status_id = 190
        application.save()

        ApplicationHistoryFactory(application_id=application.id, status_new=160)
        application_history = ApplicationHistory.objects.filter(application=application).last()

        credit_score = CreditScoreFactory(application_id=application.id)
        product = ProductLookupFactory()

        LoanFactory(application=application, product=product)
        loan = Loan.objects.filter(application=application).last()

        status_code, request, response = pusdafil_service.report_new_application_registration(
            application_id=application.id
        )

        self.assertEqual(status_code, 200)

        application_status = 0

        if application.application_status.status_code in (141, 163, 172):
            application_status = 1
        elif application.application_status.status_code in (133, 134, 135):
            application_status = 2
        elif application.application_status.status_code == 180:
            application_status = 3
        elif application.application_status.status_code in (137, 139):
            application_status = 6

        publication_plan = loan.fund_transfer_ts.date() - application_history.cdate.date()
        publication_realization = loan.fund_transfer_ts.date() - application_history.cdate.date()

        six.assertCountEqual(
            self,
            request,
            dict(
                id_penyelenggara=str(self.organizer_id),
                id_pinjaman=str(application.application_xid),
                id_borrower=str(application.customer.id),
                id_syariah=2,
                id_status_pengajuan_pinjaman=application_status,
                nama_pinjaman=application.product_line.product_line_type[1:],
                tgl_pengajuan_pinjaman=application.cdate.strftime("%Y-%m-%d"),
                nilai_permohonan_pinjaman=application.loan_amount_request,
                jangka_waktu_pinjaman=application.loan_duration_request,
                satuan_jangka_waktu_pinjaman=3,
                penggunaan_pinjaman='e0',
                agunan=2,
                jenis_agunan=8,
                rasio_pinjaman_nilai_agunan=0,
                permintaan_jaminan='',
                rasio_pinjaman_aset=0,
                cicilan_bulan=application.total_current_debt,
                rating_pengajuan_pinjaman=credit_score.score if credit_score else 'B-',
                nilai_plafond=0,
                nilai_pengajuan_pinjaman=application.loan_amount_request,
                suku_bunga_pinjaman=loan.product.interest_rate,
                satuan_suku_bunga_pinjaman=4,
                jenis_bunga=1,
                tgl_mulai_publikasi_pinjaman=application_history.cdate.strftime("%Y-%m-%d"),
                rencana_jangka_waktu_publikasi=publication_plan.days,
                realisasi_jangka_waktu_publikasi=publication_realization.days,
                tgl_mulai_pendanaan=loan.fund_transfer_ts.strftime("%Y-%m-%d"),
                frekuensi_pinjaman=application.application_number
                if application.application_number
                else 1,
            ),
        )

        self.assertEqual(response["request_status"], 200)
        self.assertEqual(response["data"][3]["error"], False)

    @mock.patch("juloserver.pusdafil.services.PusdafilService.send_to_pusdafil_with_retry")
    def test_task_report_new_loan_registration(self, mocked_pusdafil_client):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )

        pusdafil_service = get_pusdafil_service()

        mocked_pusdafil_client.return_value = self.mocked_client_response

        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        application = ApplicationFactory(
            customer=customer,
            ktp="2763516253412344",
            fullname="Brad Pitt",
            address_street_num="Omah sweet home",
        )

        application.application_status_id = 190
        application.save()

        loan = LoanFactory(customer=customer, application=application)
        partner = PartnerFactory(user=user)
        lender = LenderCurrentFactory(id=1, user=partner.user, lender_name='jtp')
        lender_bank_account = LenderBankAccountFactory(
            lender=lender, bank_account_type='repayment_va'
        )

        status_code, request, response = pusdafil_service.report_new_loan_registration(
            loan_id=loan.id
        )

        self.assertEqual(status_code, 200)

        six.assertCountEqual(
            self,
            request,
            dict(
                id_penyelenggara=str(self.organizer_id),
                id_pinjaman=str(application.application_xid),
                id_borrower=str(application.customer_id),
                id_lender=str(lender.id),
                no_perjanjian_lender=str(lender.pks_number),
                tgl_perjanjian_lender=loan.cdate.strftime("%Y-%m-%d"),
                tgl_penawaran_pemberian_pinjaman=loan.cdate.strftime("%Y-%m-%d"),
                nilai_penawaran_pinjaman=loan.loan_amount,
                nilai_penawaran_disetujui=loan.loan_amount,
                no_va_lender=str(lender_bank_account.account_number),
            ),
        )

        self.assertEqual(response["request_status"], 200)
        self.assertEqual(response["data"][4]["error"], False)

    @mock.patch("juloserver.pusdafil.services.PusdafilService.send_to_pusdafil_with_retry")
    def test_task_report_new_loan_approved(self, mocked_pusdafil_client):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        pusdafil_service = get_pusdafil_service()

        mocked_pusdafil_client.return_value = self.mocked_client_response

        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        application = ApplicationFactory(
            customer=customer,
            ktp="2763516253412344",
            fullname="Brad Pitt",
            address_street_num="Omah sweet home",
        )

        application.application_status_id = 190
        application.save()

        ApplicationHistoryFactory(application_id=application.id, status_old=141, status_new=160)

        loan = LoanFactory(
            customer=customer,
            application=application,
            sphp_accepted_ts=datetime.now(tz=pytz.timezone(settings.TIME_ZONE)),
            fund_transfer_ts=datetime.now(tz=pytz.timezone(settings.TIME_ZONE)),
        )
        partner = PartnerFactory(user=user)
        lender = LenderCurrentFactory(id=1, user=partner.user, lender_name='jtp')
        lender_bank_account = LenderBankAccountFactory(
            lender=lender, bank_account_type='repayment_va'
        )
        payment = PaymentFactory(loan=loan, due_date=date.today())

        status_code, request, response = pusdafil_service.report_new_loan_approved(loan_id=loan.id)

        self.assertEqual(status_code, 200)

        payment_kind_id = 2

        if application.product_line_code in (10, 11):
            payment_kind_id = 1

        six.assertCountEqual(
            self,
            request,
            dict(
                id_penyelenggara=str(self.organizer_id),
                id_pinjaman=str(application.application_xid),
                id_borrower=str(application.customer.id),
                id_lender=str(lender.id),
                id_transaksi=str(application.application_xid),
                no_perjanjian_borrower=str(application.application_xid),
                tgl_perjanjian_borrower=loan.sphp_accepted_ts.strftime("%Y-%m-%d"),
                nilai_pendanaan=loan.loan_amount,
                suku_bunga_pinjaman=loan.product.interest_rate,
                satuan_suku_bunga_pinjaman=4,
                id_jenis_pembayaran=payment_kind_id,
                id_frekuensi_pembayaran=3,
                nilai_angsuran=loan.installment_amount,
                objek_jaminan=None,
                jangka_waktu_pinjaman=loan.loan_duration,
                satuan_jangka_waktu_pinjaman=3,
                tgl_jatuh_tempo=payment.due_date.strftime("%Y-%m-%d"),
                tgl_pendanaan=loan.fund_transfer_ts.strftime("%Y-%m-%d"),
                tgl_penyaluran_dana=loan.fund_transfer_ts.strftime("%Y-%m-%d"),
                no_ea_transaksi=lender_bank_account.account_number,
                frekuensi_pendanaan=application.application_number
                if application.application_number
                else 0,
            ),
        )

        self.assertEqual(response["request_status"], 200)
        self.assertEqual(response["data"][5]["error"], False)

    @mock.patch("juloserver.pusdafil.services.PusdafilService.send_to_pusdafil_with_retry")
    def test_task_report_new_loan_payment_creation(self, mocked_pusdafil_client):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        pusdafil_service = get_pusdafil_service()

        mocked_pusdafil_client.return_value = self.mocked_client_response

        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        application = ApplicationFactory(
            customer=customer,
            ktp="3284840102038888",
            fullname="Brad Pitt",
            address_street_num="Omah sweet home",
        )

        application.application_status_id = 190
        application.save()

        status_lookup = StatusLookupFactory(status_code=220)
        loan = LoanFactory(
            customer=customer,
            application=application,
            sphp_accepted_ts=datetime.now(tz=pytz.timezone(settings.TIME_ZONE)),
            fund_transfer_ts=datetime.now(tz=pytz.timezone(settings.TIME_ZONE)),
            loan_status=status_lookup,
        )
        partner = PartnerFactory(user=user)
        lender = LenderCurrentFactory(id=1, user=partner.user, lender_name='jtp')
        payment = PaymentFactory(loan=loan, payment_number=1, due_date=date.today())

        payment.paid_date = date.today()
        payment.paid_amount = 3000000
        payment.payment_status_id = 330
        payment.due_amount = 0
        payment.save()

        next_payment = PaymentFactory(loan=loan, payment_number=2, due_date=date.today())

        next_payment.paid_date = date.today()
        next_payment.paid_amount = 3000000
        payment.save()

        status_code, request, response = pusdafil_service.report_new_loan_payment_creation(
            payment_id=payment.id
        )

        self.assertEqual(status_code, 200)

        remaining_loan_count = ''

        if (
            payment.paid_amount >= payment.installment_principal
            or payment.loan.loan_status.status_code in (210, 234, 235, 236, 237, 240, 260)
        ):
            remaining_loan_count = 0
        if payment.paid_amount < payment.installment_principal:
            remaining_loan_count = payment.installment_principal - payment.paid_amount

        loan_status_id = ''

        if payment.loan.loan_status.status_code in (220, 230, 231, 250):
            loan_status_id = 1
        elif payment.loan.loan_status.status_code in (232, 233):
            loan_status_id = 2
        elif payment.loan.loan_status.status_code in (210, 234, 235, 236, 237, 240, 260):
            loan_status_id = 3

        six.assertCountEqual(
            self,
            request,
            dict(
                id_penyelenggara=str(self.organizer_id),
                id_pinjaman=str(application.application_xid),
                id_borrower=str(application.customer.id),
                id_lender=str(lender.id),
                id_transaksi=str(application.application_xid),
                id_pembayaran=str(payment.id),
                tgl_jatuh_tempo=payment.due_date,
                tgl_jatuh_tempo_selanjutnya=next_payment.due_date,
                tgl_pembayaran_borrower=payment.paid_date,
                tgl_pembayaran_penyelenggara=payment.paid_date,
                sisa_pinjaman_berjalan=remaining_loan_count,
                id_status_pinjaman=loan_status_id,
                tgl_pelunasan_borrower=payment.paid_date,
                tgl_pelunasan_penyelenggara=payment.paid_date,
                denda=payment.late_fee_amount,
                nilai_pembayaran=payment.paid_amount,
            ),
        )

        self.assertEqual(response["request_status"], 200)
        self.assertEqual(response["data"][6]["error"], False)

    @mock.patch("juloserver.pusdafil.clients.requests.post")
    def test_success_send(self, mocked_pusdafil_client):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )

        pusdafil_service = get_pusdafil_service()

        mocked_pusdafil_client.return_value = self.mocked_response

        pusdafil_service.initiate_pusdafil_upload_object("reg_lender", 1)
        status_code, response_body = pusdafil_service.send_to_pusdafil_with_retry(
            "reg_lender", self.data
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(response_body["request_status"], 200)
        self.assertEqual(response_body["data"][1]["error"], False)

    @mock.patch("juloserver.pusdafil.clients.requests.post")
    def test_not_retrying_exception_send(self, mocked_pusdafil_client):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        pusdafil_service = get_pusdafil_service()

        mocked_pusdafil_client.return_value = self.mocked_response
        mocked_pusdafil_client.side_effect = Exception("Not on retry exception")

        with self.assertRaises(Exception) as context:
            pusdafil_service.send_to_pusdafil_with_retry("reg_lender", self.data)

        self.assertTrue('Not on retry exception' in str(context.exception))

    @mock.patch("juloserver.pusdafil.clients.requests.post")
    def test_max_retry_send(self, mocked_pusdafil_client):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        pusdafil_service = get_pusdafil_service()

        error_message = "Exceeding max retry attempts"

        mocked_pusdafil_client.return_value = self.mocked_response
        mocked_pusdafil_client.side_effect = [
            ConnectionError(error_message),
            ConnectionError(error_message),
        ]

        with self.assertRaises(Exception) as context:
            pusdafil_service.initiate_pusdafil_upload_object("reg_lender", 1)
            pusdafil_service.send_to_pusdafil_with_retry("reg_lender", self.data, max_retry_count=1)

        self.assertTrue(error_message in str(context.exception))

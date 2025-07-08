from rest_framework.test import APIClient
from rest_framework.test import APITestCase

from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    CustomerFactory,
    AuthUserFactory,
    StatusLookupFactory,
    WorkflowFactory,
    FeatureSettingFactory,
    ApplicationFactory,
    CustomerWalletHistoryFactory,
    CashbackTransferTransactionFactory,
    BankFactory,
    MobileFeatureSettingFactory,
    ProductLineFactory,
    ImageFactory,
    ExperimentSettingFactory,
    ExperimentFactory,
    ExperimentTestGroupFactory,
)
from juloserver.julo_savings.tests.factories import (
    JuloSavingsWhitelistApplicationFactory,
    JuloSavingsMobileContentSettingFactory,
)
from juloserver.julo_savings.constants import ContentNameConst, DescriptionConst


class TestJuloSavingsAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.whitelist_application = JuloSavingsWhitelistApplicationFactory(
            application=self.application
        )
        json_content = {
            "header": {
                "title": "Yuk, Buka Tabungan JULO Sekarang!",
                "subtitle": "Nabungnya mudah, untungnya berlimpah!",
                "banner_image": "https://statics.julo.co.id/julo_savings/header-saving.png",
            },
            "benefits": {
                "title": "Keuntungan Memiliki Tabungan JULO",
                "benefits_data": [
                    {
                        "title": "Double Credit Limit",
                        "icon": "https://statics.julo.co.id/julo_savings/saving-easy-payment.png",
                        "subtitle": "Bonus kredit limit 2 kali saldo tabungan",
                        "description_image": '',
                    },
                    {
                        "title": "Double Interest Rate",
                        "icon": "https://statics.julo.co.id/julo_savings/saving-easy-registration.png",
                        "subtitle": "Bunga tabungan 2 kali lebih besar",
                        "description_image": '',
                    },
                    {
                        "title": "Double Cashback Repayment",
                        "icon": "https://statics.julo.co.id/julo_savings/saving-in-app-saving.png",
                        "subtitle": "Cashback 2 kali lipat untuk pelunasan lebih awal",
                        "description_image": '',
                    },
                ],
            },
            "footer": {
                "icon": "https://statics.julo.co.id/julo_savings/blu_logo.png",
                "title": "Melanjutkan ke tahap berikutnya berarti Anda menyetujui semua Syarat & Ketentuan serta Kebijakan Privasi kami",
            },
        }
        self.mobile_content_json = JuloSavingsMobileContentSettingFactory(
            content_name=ContentNameConst.BENEFIT_SCREEN,
            description=DescriptionConst.JSON_CONTENT,
            parameters=json_content,
            content=None,
            is_active=True,
        )
        self.mobile_content_html = JuloSavingsMobileContentSettingFactory(
            content_name=ContentNameConst.BENEFIT_SCREEN,
            description=DescriptionConst.DOUBLE_CREDIT_LIMIT,
            content="""<p><strong>Double Credit Limit&nbsp;</strong></p>
                <ul>
                <li style="font-weight: 400;"><span style="font-weight: 400;">Pengguna Tabungan JULO harus mendapat status terverifikasi di aplikasi JULO untuk mengaktifkan manfaat Credit Limit Tambahan</span></li>
                <li style="font-weight: 400;"><span style="font-weight: 400;">Pengguna Tabungan JULO menyimpan dana tabungan di wallet bluAccount, bluSavings, dan bluDeposit, dengan nominal setidaknya Rp. 250.000,- di salah satu wallet</span></li>
                <li style="font-weight: 400;"><span style="font-weight: 400;">Pengguna Tabungan JULO menabung selama 3 bulan sejak dana tabungan pertama masuk</span></li>
                <li style="font-weight: 400;"><span style="font-weight: 400;">Pengguna Tabungan JULO mendapat manfaat Credit Limit Tambahan di Pinjaman JULO sebesar 2 kali lipat dari total saldo terendah Tabungan JULO di wallet bluAccount, bluSavings, dan bluDeposit selama 3 bulan sejak dana tabungan pertama masuk.</span><span style="font-weight: 400;"><br /></span><span style="font-weight: 400;">Contoh: Jika total saldo terendah selama 3 bulan terakhir adalah Rp.1.500.000,-, maka manfaat Credit Limit Tambahan yang pengguna dapatkan yaitu sebesar Rp. 3.000.000,-</span></li>
                <li style="font-weight: 400;"><span style="font-weight: 400;">Manfaat Credit Limit Tambahan akan diperbaharui setiap 3 bulan sejak aktivasi sebelumnya dengan nilai manfaat sesuai dengan total saldo terendah bluAccount, bluSavings, dan bluDeposit</span></li>
                </ul>""",
            parameters=None,
            is_active=True,
        )
        self.mobile_content_html_1 = JuloSavingsMobileContentSettingFactory(
            content_name=ContentNameConst.BENEFIT_SCREEN,
            description=DescriptionConst.DOUBLE_INTEREST_RATE,
            content="""<p>Double Interest Bonus&nbsp;</p><ul>
                    <li>
                        <p>Total bunga yang didapat dari wallet bluAccount dan bluSavings selama 6 bulan pertama sejak aktivasi akun akan terhitung sebagai bonus Cashback</p>
                    </li>
                    <li>
                        <p>Bonus Cashback akan dikirimkan ke wallet Cashback JULO dalam xx hari sejak Pengguna Tabungan JULO dinyatakan mendapat bonus tersebut</p>
                    </li>
                </ul>""",
            parameters=None,
            is_active=True,
        )
        self.mobile_content_html_2 = JuloSavingsMobileContentSettingFactory(
            content_name=ContentNameConst.BENEFIT_SCREEN,
            description=DescriptionConst.DOUBLE_CASHBACK_REPAYMENT,
            content="""<p>Double Cashback&nbsp;</p>
                <ul>
                    <li>
                        <p>Pengguna Tabungan JULO berhak mendapat Cashback dengan nominal 2 kali lipat dari nominal seharusnya untuk 6 kali pembayaran kembali Pinjaman JULO yang tepat waktu atau lebih awal dari tenggat waktu</p>
                    </li>
                    <li>
                        <p>Detail lebih rinci terkait skema Cashback untuk pembayaran kembali Pinjaman JULO dapat dilihat di xx</p>
                    </li>
                </ul>""",
            parameters=None,
            is_active=True,
        )

    def test_true_get_whitelist_status(self):
        response = self.client.get(
            '/api/julo-savings/v1/whitelist-status/{}'.format(self.application.id)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], {'whitelist_status': True})
        self.assertEqual(response.json()['success'], True)

    def test_false_get_whitelist_status(self):
        response = self.client.get('/api/julo-savings/v1/whitelist-status/{}'.format(39))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], {'whitelist_status': False})
        self.assertEqual(response.json()['success'], True)

    def test_success_get_benefit_page(self):
        self.maxDiff = None
        response = self.client.get('/api/julo-savings/v1/blu/welcome')
        benefits_data = [
            {
                "title": "Double Credit Limit",
                "icon": "https://statics.julo.co.id/julo_savings/saving-easy-payment.png",
                "subtitle": "Bonus kredit limit 2 kali saldo tabungan",
                "description": self.mobile_content_html.content,
                "description_image": '',
            },
            {
                "title": "Double Interest Rate",
                "icon": "https://statics.julo.co.id/julo_savings/saving-easy-registration.png",
                "subtitle": "Bunga tabungan 2 kali lebih besar",
                "description": self.mobile_content_html_1.content,
                "description_image": '',
            },
            {
                "title": "Double Cashback Repayment",
                "icon": "https://statics.julo.co.id/julo_savings/saving-in-app-saving.png",
                "subtitle": "Cashback 2 kali lipat untuk pelunasan lebih awal",
                "description": self.mobile_content_html_2.content,
                "description_image": '',
            },
        ]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['benefits']['benefits_data'], benefits_data)
        self.assertEqual(response.json()['success'], True)

    def test_failed_get_benefit_page(self):
        self.mobile_content_json.content_name = ''
        self.mobile_content_json.save()
        self.mobile_content_html.content_name = ''
        self.mobile_content_html.save()
        self.mobile_content_html_1.content_name = ''
        self.mobile_content_html_1.save()
        self.mobile_content_html_2.content_name = ''
        self.mobile_content_html_2.save()
        response = self.client.get('/api/julo-savings/v1/blu/welcome')
        self.assertEqual(response.status_code, 404)

    def test_multiple_html_content(self):
        self.mobile_content_html_3 = JuloSavingsMobileContentSettingFactory(
            content_name=ContentNameConst.BENEFIT_SCREEN,
            description=DescriptionConst.DOUBLE_CASHBACK_REPAYMENT,
            content="""<p>just some test, this is the new one</p>""",
            parameters=None,
            is_active=True,
        )
        response = self.client.get('/api/julo-savings/v1/blu/welcome')
        self.assertEqual(
            response.json()['data']['benefits']['benefits_data'][2]['description'],
            self.mobile_content_html_3.content,
        )
        self.assertEqual(response.json()['success'], True)

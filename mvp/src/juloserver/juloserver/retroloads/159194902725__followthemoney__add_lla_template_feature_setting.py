# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def get_html():
    return '<html>\
            <title>SURAT PERJANJIAN {{agreement_letter_number}} - {{application_xid}}</title>\
            <style>\
                @page {size: A4; padding: 70px 100px;}\
            </style>\
            <body>\
                <center>\
                    <strong>\
                        PERJANJIAN PELAKSANAAN<br/>\
                        PINJAMAN ANTARA<br/>\
                        PT JULO TEKNOLOGI FINANSIAL<br/>\
                        &<br/>\
                        {{company_name}}<br/>\
                        {{agreement_letter_number}}<br/>\
                    </strong>\
                </center>\
                \
                <div>\
                    <p>Perjanjian ini dibuat dan disetujui pada hari ini, tanggal {{date_today}} oleh dan antara:</p>\
                    <ol style="padding-inline-start: 16px;">\
                        <li>PT JULO TEKNOLOGI FINANSIAL (selanjutnya disebut "<strong>JULO</strong>") sebagai penyelenggara layanan Pinjam Menimjam Uang Berbasis Teknologi Informasi, sesuai dengan Peraturan OJK No.77/POJK.01/2016;</li>\
                        <li>{{company_name}}, suatu perusahaan yang didirikan berdasarkan hukum negara Republik Indonesia, beralamat di {{company_address}}, Indonesia, (selanjutnya disebut "<strong>PEMBERI PINJAMAN</strong>").</li>\
                    </ol>\
                    \
                    <p>Pemberi Pinjaman menyatakan setuju untuk mengikatkan diri kepada JULO atas ketentuan-ketentuan sebagai berikut:</p>\
                    <ol style="padding-inline-start: 16px;">\
                        <li>Bahwa JULO sebagai platform yang bertindak mewakili Pemberi Pinjaman sesuai dengan surat Perjanjian Kerjasama {{agreement_letter_number}}, diberikan kuasa untuk menerima informasi Penerima Pinjaman. Tujuan menggunakan informasi tersebut adalah untuk melakukan verifikasi dan/atau tinjau kelayakan sesuai dengan kriteria yang telah ditetapkan, menginformasikan hasil pengajuan, dan memberikan reminder pembayaran/ penagihan atas jumlah terhutang, baik dilakukan oleh pihak JULO sendiri maupun melalui Pihak Ketiga JULO. Kuasa berlaku sepanjang jangka waktu Perjanjian Kerjasama ataupun selama durasi Pinjaman berjalan, mana yang lebih lama.</li>\
                        <li>Bahwa Pemberi Pinjaman menyetujui pinjaman kepada Penerima Pinjaman melalui JULO dengan nomor perjanjian {{application_xid}}. Adapun pinjaman berbentuk uang tunai sebesar {{loan_amount}} ("Pinjaman"), dengan biaya provisi sebesar {{provision_fee_amount}} dan suku bunga {{interest_rate}}.</li>\
                        <li>Bahwa pembayaran angsuran Pinjaman akan dilakukan setiap bulan pada tanggal {{cycle_day}} selama {{duration_month}} bulan sebesar Rp {{installment_amount}} dimulai dari tanggal {{due_date_1}}. Keterlambatan akan dikenakan biaya sebesar {{late_fee_amount}} per bulan, untuk setiap angsuran yang terlambat, sampai dengan satu tahun.</li>\
                        <li>Bahwa biaya komisi seperti yang ditetapkan dan disetujui di surat Perjanjian Kerjasama, beserta biaya provisi dan biaya keterlambatan (jika ada) adalah hak bagi pihak JULO.</li>\
                    </ol>\
                    \
                    <p>Pemberi Pinjaman dan JULO mengerti bahwa masing-masing pihak dapat menunjuk Pihak ketiga terkait penggunaan segala data/informasi Penerima Pinjaman hanya terbatas pada kesepakatan pinjam meminjam saja, yang mana detail pihak ketiga akan disebutkan di dalam Syarat dan Ketentuan. Dalam hal penggunaan segala informasi/data Penerima Pinjaman hanya berlaku sampai dengan kewajiban dari Penerima Pinjaman yang tertuang dalam perjanjian pinjam meminjam dengan Pemberi Pinjaman/JULO telah berakhir. Pemberi Pinjaman dan JULO mengerti atas hak dan kewajiban masing-masing pihak, sesuai dengan yang tertuang pada Perjanjian Kerjasama pasal 4 & 5, dan senantiasa mematuhi ketentuan hukum yang berlaku dalam melaksanakan Perjanjian ini.</p>\
                    \
                    <p>Apabila JULO sebagai Penyelenggara Layanan Pinjam Meminjam Uang Berbasis Teknologi Informasi tidak dapat melanjutkan kegiatan operasionalnya, JULO akan tetap menjalankan segala kewajibannya terkait dengan penyelesaian Pinjaman ini, termasuk namun tidak terbatas pada kegiatan reminder pembayaran/ penagihan, penyediaan informasi pelunasan, penyediaan sarana Virtual Account, seperti yang tertuang di Surat Penjanjian Hutang Piutang dan di Syarat & Ketentuan.</p>\
                    \
                    <p>Sengketa yang mungkin timbul dari penafsiran dan/atau pelaksanaan Perjanjian ini akan diselesaikan melalui musyawarah untuk mencapai mufakat antara kedua belah pihak, atau melalui jalur hukum yuridiksi Pengadilan Negeri Jakarta Selatan Republik Indonesia atau pengadilan manapun di setiap yuridiksi yang kompeten.</p>\
                    \
                    <p>Perjanjian ini adalah sah dan mengikat sesuai dengan ketentuan peraturan perundang-undangan yang berlaku, dan Pemberi Pinjaman menandatangani secara sadar dan tanpa paksaan dari pihak manapun.</p>\
                </div>\
                \
                <div>\
                    <table border="0" style="width: 100%; text-align: center;">\
                        <tr style="vertical-align: bottom;">\
                            <td><img src="{{company_logo}}" style="width: 200px" /></td>\
                            <td><img src="{{julo_logo}}" style="width: 200px" /></td>\
                        </tr>\
                        <tr>\
                            <td><br/><br/><br/><br/></td>\
                            <td><br/><br/><br/><br/></td>\
                        </tr>\
                        <tr>\
                            <td>{{company_name}}</td>\
                            <td>PT JULO TEKNOLOGI FINANSIAL</td>\
                        </tr>\
                    </table>\
                </div>\
            </body>\
        </html>'

def ftm_config_feature_setting(apps, _schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=True,
        feature_name=FeatureNameConst.LLA_TEMPLATE,
        category="followthemoney",
        parameters= {"template": get_html()},
        description="Default Lender Loan Agreement Template")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(ftm_config_feature_setting, migrations.RunPython.noop)
    ]
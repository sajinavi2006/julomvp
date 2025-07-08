import os
import csv
import tempfile
import pdfkit
from juloserver.julo.models import Application, CreditScore, Loan, Document
from django.utils import timezone
from juloserver.julo.exceptions import JuloException
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tasks import upload_document
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.utils import display_rupiah
from babel.dates import format_date
from django.conf import settings
from juloserver.loan.services.views_related import get_manual_signature_url_grab
from django.template import Context
from django.template import Template
from juloserver.followthemoney.services import get_lender_and_director_julo, get_list_loans, get_detail_loans
from juloserver.followthemoney.models import LoanAgreementTemplate, LenderBucket
from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.grab.tasks import (
    generate_julo_one_loan_agreement_grab_script,
    julo_one_generate_auto_lender_agreement_document_grab_script
)
from bulk_update.helper import bulk_update
template_body = """
<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <link href="https://statics.julo.co.id/montserrat/montserrat-v14-cyrillic-ext_vietnamese_latin-ext_cyrillic_latin.css" rel="stylesheet">

    <style>
        body {
            font-family: Montserrat;
            font-size: 12px;
            color: #5e5e5e;
            margin: 5px;
            padding: 0px;
            text-align: justify;
            counter-reset: item;
        }

        .container {
            padding: 50px 100px;
            width: 1200px;
            height: 2040px;
            font-size: 22px;
        }

        .titleSphp {
            font-size: 36px;
            font-weight: bold;
            padding-top: 10px;
            text-align: center;
            padding-bottom: 30px;
        }

        .titleSkrtp {
            font-size: 20px;
            font-weight: bold;
            text-align: center;
        }

        ol {
            margin: 1em;
            padding-inline-start: 50px;
        }

        ol.section2 {
            counter-reset: section;
            padding-inline-start: 50px;
            padding-left: 0;
            padding-top: 15px;
            display:block;
            margin-left:0;
        }

        li {
            padding-left: 30px;
            padding-top: 15px;
        }

        ol.section2>li {
            counter-increment: section;
            position: relative;
            padding-left: 0;
            margin-bottom: 0.5em;
            line-height: 1.5;
            display:block;
            margin-left:0;
        }

        ol.section2>li::before {
            content: counters(section, ".") " ";
            counter-increment: item
            position: absolute;
            left: 0;
            height: 100%;
            margin-right: 1em;
        }

        .divContent {
            padding-top: 15px;
        }

        .logo {
            width: 180px;
            height: 75px;
        }

        .footer {
            font-size: 20px;
            text-align: right;
        }

        .footerTop {
            margin-top: 25px;
        }

        .dateText {
            text-align: right;
        }

        .bold {
            font-weight: bold;
        }

        .divRight {
            float: right;
        }

        .divLeft {
            float: left;
        }

        .spaceSign {
            height: 120px;
        }

        .enter {
            margin-top: 13px;
        }

        .contentPadding{
            padding-bottom: 10px;
        }

        .firstT3TR {
            font-weight: bold;
            border-top: 2px solid rgb(46, 46, 46);
            font-size: 24px;
        }

        .secondT3TR {
            border-top: 2px solid rgb(46, 46, 46);
        }

        table {
            padding-left: 10px;
            width: 100%;
        }

        table.t2 td {
            padding-top: 10px;
        }

        table.t3 {
            border-collapse: collapse;
            width: 100%;
        }

        table.t3 tr {
            font-size: 24px;
            vertical-align: middle;
            text-align: center;
        }

        table.t3 th,
        table.t3 td {
            padding: 10px;
            border-top: 1px solid #ddd;
        }

        table.t3 td {
            height: 10px;
        }
       .table-same{
            list-style-type: lower-latin;
       }
       .table-same li {
           padding : 0;
           margin-bottom: 5px;
       }
       .table-same li span {
            display: inline-block;
            position: relative;
            vertical-align: top;
            word-wrap: break-word;
       }
       .table-same li>span:first-child {
            width: 30%;
            padding-right: 5px;
       }
       .table-same li>span:nth-child(2) {
            width: 65%;
            padding-right: 5px;
       }
       .table-same li>span:first-child {
            display: inline-block;
            position: relative;
            padding-right: 5px;
            vertical-align: top;
            text-align: left;
       }
       .table-same li>span:first-child:after{
            content: ":";
            position : absolute;
            right:  0;
            top : 0;
            bottom : 0;
       }
    </style>

</head>

<body>
    <div class="container">
        <div>
            <img src="{{ julo_image }}" class="logo"/>
        </div>
        <p>Diperbaharui sejak tanggal : {{ today_date_bahasa }}
        <div class="titleSphp">
            <div>PERJANJIAN PEMBERIAN PENDANAAN
            </div>
            <div>No. Perjanjian : {{ loan.loan_xid }}</div>
        </div>
        <div class="Content">
        <div>
            Sebagai persyaratan awal sebelum Anda menandatangani Perjanjian Pemberian Pendanaan
            ini (selanjutnya disebut <b>“Perjanjian Pendanaan”</b>), Anda wajib membaca, memeriksa,
            memahami Perjanjian Pendanaan ini dengan memindahkan bilah gulir (<i>scroll bar</i>) atau
            menekan tombol persetujuan (<i>approval button</i>) yang tersedia pada Perjanjian Pendanaan
            ini, dengan penuh cermat dan kehati-hatian. <b>Tidak ada tuntutan/gugatan apapun oleh
            Anda kepada Pemberi Dana dan/atau JULO dari segala tanggung jawab terhadap kerugian
            yang terjadi disebabkan dari kealpaan atau kelalaian Anda dengan tidak membaca,
            memeriksa atau memahami isi seluruh perjanjian Pendanaan ini.</b>
        </div>
        <br>
        <div>
            Perjanjian Pendanaan ini disepakati dan ditandatangani pada tanggal {{date_today}}
            (selanjutnya disebut <b>“Tanggal Penandatanganan”</b>), oleh dan antara :
        </div>
        <ol class="section1">
            <li>
                <div><b>Penerima Dana</b>, yang memiliki identitas sebagai berikut: </div>
                <ol class="table-same">
                    <li>
                        <span>Nama</span> <span>{{ application.fullname }}</span>
                    </li>
                    <li>
                        <span>Tgl. Lahir</span> <span>{{ dob }}</span>
                    </li>
                    <li>
                        <span>No. KTP</span> <span>{{ application.ktp }}</span>
                    </li>
                    <li>
                        <span>No. Telpon</span> <span>{{ application.mobile_phone_1 }}</span>
                    </li>
                    <li>
                        <span>Alamat</span> <span>{{ full_address }}</span>
                    </li>
                </ol>
            </li>
            <br>
            <li>
                <div><b>Pemberi Dana</b> yaitu perusahaan atau orang perseorangan dengan detail identitas legalitas sebagai berikut:
                </div>
                    <ol class="table-same">
                        <li>
                            <span>Nama/Perusahaan</span> <span>{{ lender_company_name }}</span>
                        </li>
                        <li>
                            <span>Nama Perwakilan Perusahaan</span> <span>{{ lender_director }}</span>
                        </li>
                        <li>
                            <span>Nomor Izin Perusahaan Terkait</span> <span>{{ lender_license_number }}</span>
                        </li>
                        <li>
                            <span>Alamat Terdaftar	</span> <span>{{ lender_full_address }}</span>
                        </li>
                    </ol>
                </li>
            <br>
        </ol>
        <div class="contentPadding">
            <div>
                Untuk selanjutnya, Penerima Dana dan Pemberi Dana secara bersama-sama disebut juga
                <b>“Para Pihak”</b> dan masing-masing disebut <b>“Pihak”</b>.
            </div>
            <br>
            <div>
                Anda juga diwajibkan membaca <b>Lampiran 1.  Syarat dan Ketentuan Penggunaan </b>yang disediakan
                oleh JULO dan/atau Mitra Bisnis. Dengan Anda menekan fitur persetujuan (<i>consent</i>) yang akan
                muncul pada halaman Aplikasi Anda pada saat pengajuan Pendanaan, maka berarti Anda juga telah
                menyetujui Syarat dan Ketentuan Penggunaan sebagaimana laman website diatas. Syarat dan Ketentuan
                Penggunaan ini merupakan bagian yang tidak terpisahkan dengan Perjanjian Pendanaan serta Syarat
                dan Ketentuan Penggunaan ini dapat berubah dari waktu ke waktu sesuai kebijakan Pemberi Dana
                dan/atau Mitra Bisnis dan tanpa memerlukan persetujuan Para Pihak.
            </div>
            <br>
            <div>
                Perjanjian Pendanaan mencakup hal-hal sebagai berikut:
            </div>
        </div>
        <div>
            <ol class="section2">
                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                    <div>
                    <b>KETENTUAN UMUM</b>
                    <ol class="section2">
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                            <b>Definisi</b>
                            <ol type="a" style="list-style:lower-alpha;">
                                <li>
                                    <b>Akun</b> adalah rekening Pendanaan pendanaan yang terdaftar berisi data
                                    tentang Anda dan dapat diakses melalui aplikasi JULO dan/atau Mitra
                                    Bisnis yang Anda unduh serta ditujukan untuk membantu Anda dalam mengakses
                                    kredit secara digital, melalui Aplikasi JULO dan/atau Aplikasi Mitra Bisnis.
                                </li>
                                <li>
                                    <b>Aplikasi</b> adalah perangkat lunak dan/atau sistem elektronik yang dimiliki
                                    oleh PT. Julo Teknologi Finansial.
                                </li>
                                <li>
                                    <b>Aplikasi Mitra Bisnis</b> adalah perangkat lunak yang Sistem Elektroniknya
                                    dimiliki oleh Mitra Bisnis yang bekerjasama baik secara eksklusif maupun
                                    inklusif dengan JULO.
                                </li>
                                <li>
                                    <b>Dokumen-Dokumen Elektronik</b> adalah setiap Informasi elektronik yang dibuat,
                                    diteruskan, dikirimkan, diterima, atau disimpan, dapat dilihat, ditampilkan,
                                    dan/atau didengar  melalui Sistem Elektronik JULO termasuk antara lain
                                    Perjanjian Pendanaan beserta segala Lampiran-Lampirannya, syarat dan
                                    ketentuan JULO lainnya, kebijakan-kebijakan JULO lainnya,  form-form di
                                    dalam aplikasi, dan/atau informasi elektronik lainnya yang tidak tertuang
                                    dalam Perjanjian Pendanaan ini tetapi masuk dalam Sistem Elektronik yang
                                    dimiliki oleh JULO.
                                </li>
                                <li>
                                    <b>Pendanaan</b> adalah sebagaimana didefinisikan dalam pasal 1 ayat 1.4
                                    huruf a Perjanjian Pendanaan ini.
                                </li>
                                <li>
                                    <b>Fitur JULO</b> adalah sebagaimana yang didefinisikan dalam pasal 9.3.,
                                    Perjanjian Pendanaan ini.
                                </li>
                                <li>
                                    <b>JULO</b> adalah platform dengan merek dagang resmi yang terdaftar dan Sistem
                                    Elektronik yang dimiliki oleh PT. Julo Teknologi Finansial sebagai Pihak
                                    Penyelenggara yang terdaftar dan berizin di Otoritas Jasa Keuangan sebagai
                                    Penyelenggara Layanan Pendanaan Bersama Teknologi Informasi (LPBBTI), yang
                                    dalam Perjanjian ini dipilih oleh Pemberi Dana sebagai mitra penyedia
                                    aplikasi yang menyediakan LPBBTI.
                                </li>
                                <li>
                                    <b>Kode PIN</b> adalah sejumlah kode unik atau nomor digit tertentu yang
                                    digunakan Penerima Dana untuk kepentingan sebagai sarana verifikasi untuk
                                    mendukung fungsi autentikasi Dokumen-Dokumen Elektronik.
                                </li>
                                <li>
                                    <b>Layanan JULO</b> adalah LPBBTI, yang mana pada pokoknya mempertemukan Pemberi
                                    Dana dengan Penerima Dana dalam melakukan pendanaan konvensional secara
                                    langsung melalui Sistem Elektronik yang dimiliki dan dikelola mutlak
                                    oleh JULO.
                                </li>
                                <li>
                                    <b>Merchant</b> adalah pihak ketiga yang bekerjasama dengan JULO sebagai penjual
                                    barang dan/atau jasa yang memiliki <i>physical store</i> atau bentuk usaha toko
                                    fisik maupun toko online.
                                </li>
                                <li>
                                    <b>Mitra Bisnis</b> adalah pihak ketiga yang bekerjasama dengan JULO dengan pola
                                    <i>partnership</i>/ kemitraan untuk menunjang bisnis JULO dalam
                                    memberikan Layanan JULO.
                                </li>
                                <li>
                                    <b>OJK</b> adalah Otoritas Jasa Keuangan, yang merupakan Lembaga yang mengatur
                                    serta mengawasi perusahaan penyelenggaraan LPBBTI.
                                </li>
                                <li>
                                    <b>Pemegang Akun</b> berarti sebagaimana yang didefinisikan pada Pasal 1.2
                                    huruf a Perjanjian Pendanaan ini.
                                </li>
                                <li>
                                    <b>Penerima Dana</b> adalah perorangan atau badan hukum yang menerima Pendanaan
                                    melalui Layanan JULO.
                                </li>
                                <li>
                                    <b>Pemberi Dana</b> adalah perorangan atau badan hukum yang memberikan Pendanaan
                                    melalui Layanan JULO.
                                </li>
                                <li>
                                    <b>Permohonan Pengajuan Pendanaan</b> adalah Permohonan yang dilakukan oleh
                                    Penerima Dana untuk mendapatkan persetujuan dari Pemberi Dana  atas sebesar
                                    Pendanaan tertentu  yang tersedia bagi Penerima Dana.
                                </li>
                                <li>
                                    <b>Permohonan Penggunaan Pendanaan</b> adalah Permohonan yang dilakukan oleh
                                    Penerima Dana untuk penggunaan/pencairan Pendanaan.
                                </li>
                                <li>
                                    <b>Pokok Pendanaan</b> adalah sejumlah pendanaan yang diperoleh dari Fasilitas
                                    Pendanaan yang diperoleh Penerima Dana, yang besarannya sama setiap angsuran
                                    per bulannya.
                                </li>
                                <li>
                                    <b>Sistem Elektronik</b> adalah serangkaian perangkat dan prosedur elektronik
                                    yang berfungsi mempersiapkan, mengumpulkan, mengolah, menganalisis,
                                    menyimpan, menampilkan, mengumumkan, mengirimkan, dan/atau menyebarkan
                                    Informasi Elektronik.
                                </li>
                                <li>
                                    <b>Surat Kuasa</b> adalah surat yang berisi tentang  pernyataan pemberian kuasa,
                                    yang diberikan oleh Pemberi Dana kepada JULO sebagai penerima kuasa untuk
                                    penandatanganan Perjanjian Pendanaan ini. Tidak ada interpretasi lain dalam
                                    Surat Kuasa selain hanya sebagai penerima kuasa untuk menandatangani
                                    Perjanjian Pendanaan.
                                </li>
                                <li>
                                    <b>Surat Keterangan Lunas</b> adalah surat yang diberikan oleh setiap
                                    Pemberi Dana kepada Penerima Dana melalui JULO yang menyatakan bahwa
                                    Penerima Dana tidak ada lagi kewajiban pembayaran yang tertunggak
                                    berdasarkan Perjanjian Pendanaan ini.
                                </li>
                                <li>
                                    <b>SKRTP</b> adalah sebagaimana yang didefinisikan di dalam pasal 2.1.7.,
                                    Perjanjian Pendanaan ini.
                                </li>
                                <li>
                                    <b>Tanda Tangan Elektronik</b> adalah sebagaimana yang didefinisikan di dalam
                                    pasal 9.4 huruf a, Perjanjian Pendanaan ini.
                                </li>
                                <li>
                                    <b>Total Pendanaan</b> adalah jumlah yang harus dilunasi atau dibayarkan kembali
                                    oleh Penerima Dana kepada Pemberi Dana dengan rincian Pokok Pendanaan
                                    setelah dikurangi Biaya Provisi dan ditambah dengan Bunga Pendanaan.
                                </li>
                                <li>
                                    <b>Transaksi Pendanaan</b> adalah setiap transaksi yang dilakukan oleh
                                    Penerima Dana melalui Aplikasi.
                                </li>
                            </ol>
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                            <b>Penerbitan dan Penggunaan Akun atau Layanan JULO</b>
                            <ol type="a" style="list-style:lower-alpha;">
                                <li>
                                    Penerima Dana adalah Pemegang Akun yang mana artinya Pemegang Akun
                                    dimungkinkan untuk memiliki akun JULO dan/atau Mitra Bisnis secara
                                    bersamaan atau salah satu dari keduanya. Pemegang Akun tidak akan
                                    mengizinkan orang lain untuk menggunakan Akunnya dan akan selalu menjaga
                                    Akun dan nomor identifikasi pemilik Akun yang diterbitkan, dan menjaga
                                    kerahasiaan data lain termasuk namun tidak terbatas email dan
                                    password milik pemegang Akun.
                                </li>
                                <li>
                                    Penerima Dana bertanggung jawab atas Pendanaan yang diberikan Pemberi
                                    Dana sehubungan dengan Akun dan untuk semua biaya terkait yang timbul
                                    dari Perjanjian Pendanaan ini.
                                </li>
                                <li>
                                    Penerima Dana juga wajib mematuhi seluruh ketentuan penggunaan Akun
                                    sebagaimana <b>Lampiran 1.  Syarat dan Ketentuan Penggunaan</b>, serta
                                    segala resiko yang timbul akibat penggunaan Akun.
                                </li>
                                <li>
                                    Penerima Dana harus memberitahukan kepada Mitra Bisnis atau JULO
                                    sesegera mungkin setiap perubahan Akun termasuk namun tidak terbatas
                                    pekerjaan, alamat kantor, alamat rumah, nomor telepon Penerima Dana,
                                    dan juga dapat menyampaikan keluhan atau pengaduan terkait tentang
                                    Pendanaan, dengan cara sebagai berikut :
                                    <ol type="i" style="list-style:lower-roman;">
                                        <li>
                                            Kantor Mitra Bisnis :
                                            <ol>
                                                <li>
                                                    dapat mengirimkan pesan melalui
                                                    email : support.id@grabtaxi.com atau
                                                </li>
                                                <li>
                                                    dapat menggunakan Live Chat pada Aplikasi atau
                                                </li>
                                                <li>
                                                    cara lain yang dapat dilihat di Aplikasi atau
                                                    laman website JULO.
                                                </li>
                                            </ol>
                                        </li>
                                        <li>
                                            Kantor JULO :
                                            <ol>
                                                <li>
                                                    dapat mengirimkan pesan melalui email :cs@julo.co.id atau
                                                </li>
                                                <li>
                                                    dapat menggunakan Live Chat pada Aplikasi atau
                                                </li>
                                                <li>
                                                    cara lain yang dapat dilihat di Aplikasi atau laman
                                                    website JULO.
                                                </li>
                                            </ol>
                                        </li>
                                    </ol>
                                </li>
                                <li>
                                    Untuk mengaktifkan Akun Mitra Bisnis dan/atau Akun JULO yang Anda miliki,
                                    Anda wajib mengisi informasi berupa termasuk namun tidak terbatas data diri
                                    Anda untuk serangkaian proses uji tuntas nasabah (<i>customer due diligence</i>)
                                    seperti proses identifikasi, verifikasi dan pemantauan yang dilakukan
                                    Mitra Bisnis dan/atau JULO. Setelah itu, Permohonan Pengajuan Pendanaan
                                    Anda  akan diproses dan dinilai terlebih dahulu oleh Mitra Bisnis dan/atau
                                    JULO sebelum disetujui oleh Pemberi Dana. Untuk mengaktifkan layanan,
                                    Anda dapat melakukan transaksi melalui Aplikasi dan mendapatkan Surat
                                    Konfirmasi Rincian Transaksi Pendanaan (selanjutnya disebut “<b>SKRTP”</b>)
                                    yang mana berfungsi sebagai ringkasan informasi untuk setiap Permohonan
                                    Penggunaan Pendanaan.
                                </li>
                                <li>
                                    Persetujuan atas Permohonan Penggunaan Pendanaan dan pencairan dana akan
                                    dinyatakan berhasil dengan ditandai berhasilnya pemrosesan pembayaran
                                    transaksi Anda dan bersamaan dengan diterbitkannya Perjanjian Pendanaan
                                    ini dan SKRTP yang telah ditandatangani Pemberi Dana.
                                </li>
                                <li>
                                    Setiap detail transaksi atas Pendanaanyang tertuang dalam SKRTP, yang mana
                                    dalam jumlah berapapun yang Anda gunakan dan dinyatakan berhasil ini
                                    menunjukan bahwa Anda telah sepakat, membaca, dan memahami seluruh
                                    ketentuan dalam Perjanjian Pendanaan ini maupun setiap SKRTP yang Anda
                                    terima, dengan teliti, penuh kesadaran, dan tanpa pengaruh dari pihak
                                    mana pun.
                                </li>
                                <li>
                                    SKTRP yang dimaksud sebagaimana huruf e pada ayat ini adalah SKRTP yang
                                    telah Anda setujui dengan mengklik fitur persetujuan yang akan muncul
                                    di dalam Aplikasi Anda atau memasukan Kode PIN yang Anda miliki pada
                                    saat melakukan transaksi ataupun cara lain sesuai kesepakatan Para Pihak.
                                </li>
                            </ol>
                            </div>
                        </li>

                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                <b>Sumber Pendanaan</b>
                                <p>
                                    Sumber Pendanaan yang disalurkan kepada Anda untuk melakukan transaksi
                                    Pendanaan adalah sepenuhnya berasal dari dan dimiliki oleh Pemberi Dana yang
                                    terdaftar dan bekerjasama pada JULO. JULO hanya memfasilitasi penyaluran dana
                                    dari Pemberi Dana dengan cara meneruskan dana Pendanaan tersebut kepada Anda
                                    secara langsung maupun kepada Anda secara tidak langsung melalui Mitra Bisnis.
                                    Oleh karena itu, segala risiko yang timbul dari Pendanaan sepenuhnya ditanggung
                                    oleh Anda dan Pemberi Dana.
                                </p>
                            </div>
                        </li>

                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                            <b>Pendanaan</b>
                            <ol type="a" style="list-style:lower-alpha;">
                                <li>
                                    Setiap jenis transaksi yang Anda lakukan (baik Transaksi Pertama atau
                                    Transaksi setelahnya) akan dianggap sebagai dan merupakan Permohonan
                                    Penggunaan Pendanaan, dan dalam hal ini disetujui berdasarkan penilaian
                                    oleh Mitra Bisnis dan/atau JULO yang mana kriteria terhadap penilaian
                                    tersebut sudah ditetapkan berdasarkan kriteria yang diberikan oleh Pemberi
                                    Dana (selanjutnya disebut <b>“Pendanaan”</b>).
                                </li>
                                <li>
                                    Jenis transaksi sebagaimana yang dimaksud dapat dilakukan termasuk namun
                                    tidak terbatas penarikan atau transfer tunai, pembelian barang dan jasa
                                    melalui Merchant yang berkerjasama dengan Mitra Bisnis dan/atau JULO
                                    (jika ada) dan transaksi lain yang dibenarkan Undang-Undang sesuai dengan
                                    izin yang dimiliki Mitra Bisnis dan/atau JULO, melalui berbagai cara atau
                                    metode penggunaan yaitu antara lain melalui Transaksi Pendanaan atau pun
                                    cara lain yang akan difasilitasi oleh Pemberi Dana kepada Penerima Dana.
                                </li>
                            </ol>
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                            <b>Keberlakuan Perjanjian Pendanaan</b>
                            <ol type="a" style="list-style:lower-alpha;">
                                <li>
                                    Perjanjian Pendanaan ini merupakan perjanjian yang sah dan mengikat
                                    bagi Anda dan berlaku juga sebagai perjanjian antara Anda dengan
                                    Pemberi Dana.
                                </li>
                                <li>
                                    Dokumen-Dokumen Elektronik merupakan satu-kesatuan dan bagian yang
                                    tidak terpisahkan satu sama lain, termasuk namun tidak terbatas
                                    Perjanjian Pendanaan ini beserta segala addendumnya.
                                </li>
                                <li>
                                    Jika terdapat perbedaan makna atau penafsiran tentang segala ketentuan
                                    yang berkaitan dengan pemberian Pendanaan, yang terdapat pada Perjanjian
                                    Pendanaan, Syarat dan Ketentuan Penggunaan dan Kebijakan Privasi, maka
                                    yang berlaku adalah Perjanjian Pendanaan.
                                </li>
                                <li>
                                    Jika terdapat perbedaan makna atau penafsiran tentang segala ketentuan
                                    yang berkaitan aturan penggunaan umum, yang terdapat pada Perjanjian
                                    Pendanaan, Syarat dan Ketentuan Penggunaan dan Kebijakan Privasi, maka
                                    yang berlaku adalah Syarat dan Ketentuan Penggunaan.
                                </li>
                                <li>
                                    Jika terdapat perbedaan makna tentang segala ketentuan yang berkaitan
                                    aturan perlindungan penggunaan data pribadi, yang terdapat pada
                                    Perjanjian Pendanaan, Syarat dan Ketentuan Penggunaan dan Kebijakan
                                    Privasi, maka yang berlaku adalah Kebijakan Privasi.
                                </li>
                            </ol>
                            </div>
                        </li>
                    </ol>
                    </div>
                </li>
                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                    <div>
                    <b>KETENTUAN POKOK</b>
                    <ol class="section2" type="1">
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                <b>Rincian Pendanaan</b>
                                <p>
                                    Pendanaan yang disetujui Pemberi Dana adalah sebesar jumlah Pendanaan
                                    yang dapat berubah dari waktu ke waktu berdasarkan penilaian JULO dan
                                    atas persetujuan Penerima Dana.
                                </p>
                                <p>
                                    Jika Anda setuju menggunakan Pendanaan tersebut, dengan memilih,
                                    menerima, mengaktifkan dan/atau menggunakan Pendanaan yang muncul pada
                                    Aplikasi, maka Anda wajib mengetahui ketentuan rincian Pendanaan
                                    sebagai berikut :
                                </p>

                            <ol class="section2">
                                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                                    <div>
                                    <b>Pendanaan</b>
                                    <ol type="a" style="list-style:lower-alpha;">
                                        <li>
                                            Setiap persetujuan Pendanaan, Pemberi Dana memiliki wewenang
                                            menetapkan jumlah Pendanaan yang akan disalurkan kepada Anda,
                                            berdasarkan penilaian kelayakan kredit oleh JULO.
                                        </li>
                                        <li>
                                            Tanpa mengurangi ketentuan tersebut di atas dari pasal ini dan
                                            pasal lain terkait yang diatur dalam Perjanjian Pendanaan ini,
                                            Pemberi Dana, atas kebijakannya sendiri dan dari waktu ke waktu,
                                            menaikkan atau mengurangi jumlah Pendanaanyang ditetapkan,
                                            sebagai hasil dari penilaian yang wajar oleh JULO atas Akun
                                            dan/ atau informasi mengenai Penerima Dana yang relevan yang
                                            tersedia bagi JULO. Kenaikan atau pengurangan jumlah
                                            Pendanaan tersebut akan diberitahukan oleh JULO kepada Penerima
                                            Dana dari waktu ke waktu.
                                        </li>
                                        <li>
                                            Apabila jumlah Pendanaan tidak mencukupi maka persetujuan yang
                                            dimaksud pada  pasal 1.1.2 huruf f secara otomatis tidak akan
                                            berlaku dan transaksi tidak dapat dilakukan dengan menggunakan
                                            Pendanaan dari Aplikasi.
                                        </li>
                                        <li>
                                            Bahwa, Pendanaan akan dapat digunakan jika setiap pembayaran
                                            kembali dilakukan oleh Penerima Dana atau saldo pada Pendanaan
                                            tersedia kembali/mencukupi untuk digunakan dalam bertransaksi.
                                        </li>
                                    </ol>
                                    </div>
                                </li>
                                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                                    <div>
                                    <b>Manfaat Ekonomi Pendanaan</b>
                                    <p>Atas Pendanaan yang Anda terima, Anda akan dikenakan biaya
                                        Manfaat Ekonomi Pendanaan yang terdiri dari:</p>
                                    <ol type="a" style="list-style:lower-alpha;">
                                        <li>
                                            <b>Biaya Provisi</b>. Atas penggunaan Pendanaan, Anda akan dikenakan
                                            Biaya Provisi yang mana merupakan biaya layanan yang ditetapkan
                                            JULO setiap kali Anda menggunakan Layanan JULO atau melakukan
                                            Permohonan Penggunaan Pendanaan, sesuai tercantum pada halaman Akun
                                            atau di setiap SKRTP yang Anda miliki.
                                        </li>
                                        <li>
                                            <b>Bunga Pendanaan</b>. Atas penggunaan Pendanaan, Anda akan dikenakan
                                            Bunga Pendanaan sesuai Bunga Pendanaan yang tercantum pada halaman
                                            Akun yang Anda miliki atau setiap SKRTP, pada Aplikasi atau Aplikasi
                                            Mitra Bisnis.
                                        </li>
                                    </ol>
                                    <p>Dalam hal total biaya Manfaat Ekonomi Pendanaan melebihi 0,3% per hari dari Pokok Pendanaan,
                                        JULO akan melakukan pengembalian dana (<i>refund</i>) atas kelebihan tersebut ke Penerima Dana melalui
                                        namun tidak terbatas pada OVO (sebagaimana didefinisikan pada SKRTP) dan/atau rekening bank
                                        terdaftar paling lambat 45 (empat puluh lima) hari kalender atau 30 (tiga puluh) hari kerja
                                        sejak cicilan atau angsuran pertama Anda.
                                    </p>
                                    </div>
                                </li>
                                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                                    <div>
                                    <b>Nilai Angsuran</b>
                                    <p>Nilai Angsuran berarti besarnya nilai
                                        angsuran tergantung pada :</p>
                                    <ol type="a" style="list-style:lower-alpha;">
                                        <li>
                                            Total Pendanaan yang didanai;
                                        </li>
                                        <li>
                                            Jangka waktu pembayaran angsuran yang Anda pilih;
                                        </li>
                                        <li>
                                            Bunga Pendanaan yang berlaku  sesuai dengan jangka waktu angsuran
                                            yang Anda pilih; Nilai Angsuran yang Anda bayarkan untuk setiap
                                            jangka waktu pembayaran angsuran tercantum pada SKRTP di Aplikasi
                                            atau Aplikasi Mitra Bisnis;
                                        </li>
                                        <li>
                                            Rincian besaran angsuran terhadap Pendanaan yang telah disetujui
                                            akan dicantumkan dalam SKRTP.
                                        </li>
                                    </ol>
                                    </div>
                                </li>
                                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                                    <div>
                                        <b>Jangka Waktu Pembayaran Angsuran</b>
                                        <p>
                                            Jangka waktu pembayaran angsuran dapat merujuk pada setiap
                                            SKRTP yang Anda terima.
                                        </p>
                                    </div>
                                </li>
                                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                                    <div>
                                        <b>Denda Keterlambatan</b>
                                        <p>
                                            Anda dapat dikenakan Denda Keterlambatan apabila Anda lalai membayar jumlah
                                            Tagihan yang telah jatuh tempo pada Tanggal Jatuh Tempo pembayaran. Denda
                                            Keterlambatan tersebut dimulai setelah lewat Masa Tenggang dan akan
                                            diakumulasikan untuk masing-masing penggunaan Pendanaan sesuai dengan
                                            Denda yang akan tercantum (jika ada) pada halaman transaksi di Aplikasi
                                            atau Aplikasi Mitra Bisnis.
                                        </p>
                                    </div>
                                </li>
                                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                                    <div>
                                        <b>Riwayat Transaksi (History Transaction)</b>
                                        <p>
                                            Anda dapat mengetahui seluruh riwayat transaksi penggunaan Pendanaan
                                            yang Anda miliki dengan membaca dan memahami seluruh dokumen SKRTP yang
                                            dapat diakses pada halaman Akun Anda ataupun dengan media lain yang akan
                                            disediakan oleh JULO dan/atau Mitra Bisnis sesuai kebijakan yang berlaku
                                            di JULO dan/atau Mitra Bisnis.
                                        </p>
                                    </div>
                                </li>
                                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                                    <div>
                                        <b>Surat Konfirmasi Rincian Transaksi Pendanaan (SKRTP)</b>
                                        <ol>
                                            <li>
                                                SKRTP merupakan Dokumen elektronik yang Anda akan terima pada saat
                                                Anda melakukan setiap transaksi apapun  dengan menggunakan
                                                Pendanaan yang tersedia pada Aplikasi atau Aplikasi Mitra Bisnis
                                                (format SKRTP tercantum dalam <b>Lampiran 3. Contoh Surat Konfirmasi
                                                Transaksi Pendanaan (SKRTP).</b> SKRTP ini merupakan bagian yang tidak
                                                terpisahkan dengan Perjanjian Pendanaan dan kebijakan JULO yang
                                                dapat berubah dari waktu ke waktu sesuai kesepakatan Para Pihak.
                                            </li>
                                            <li>
                                                Seluruh dokumen SKRTP yang Anda miliki saat ini akan tetap berlaku
                                                dan mengikat sebagai bukti Permohonan Penggunaan Pendanaan Anda,
                                                sepanjang Penerima Dana masih terdapat kewajiban yang tertagih
                                                dan jangka waktu pembayarannya masih aktif.
                                            </li>
                                        </ol>
                                    </div>
                                </li>
                                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                                    <div>
                                        <b>Masa Tenggang</b>
                                        <p>
                                            Masa tenggang adalah 4 hari kalender dari tanggal jatuh tempo pembayaran
                                            bulan pertama atau tanggal jatuh tempo bulan berikutnya atau sesuai kebijakan
                                            dari JULO sebagaimana diberitahukan kepada Anda dari waktu ke waktu.
                                        </p>
                                    </div>
                                </li>
                                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                                    <div>
                                        <b>Pembayaran Kembali</b>
                                        <p>
                                            Setiap penggunaan Pendanaan dari Permohonan Penggunaan Pendanaan Anda beserta
                                            biaya-biaya sebagaimana pasal 2.1.2, denda keterlambatan (jika ada) atau
                                            dengan kata lain setiap Angsuran Anda akan ditagihkan kepada Anda dan Anda
                                            wajib melakukan pembayaran kembali pada sebelum atau sesuai tanggal jatuh
                                            tempo sebagaimana yang dirincikan pada setiap SKRTP yang Anda miliki.
                                        </p>
                                    </div>
                                </li>
                                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                                    <div>
                                        <b>Pembayaran Dipercepat</b>
                                        <p>
                                            Untuk pembayaran kembali, Anda dapat melakukan pembayaran kembali lebih
                                            cepat dari tanggal jatuh tempo sebagaimana yang dirincikan pada setiap
                                            SKRTP yang Anda miliki, tanpa dikenakan biaya tambahan apapun dari JULO
                                            (kecuali ditentukan sebaliknya oleh JULO di kemudian hari dengan
                                            pemberitahuan kepada Anda).
                                        </p>
                                    </div>
                                </li>
                                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                                    <div>
                                        <b>Jaminan</b>
                                        <p>
                                            Untuk menjamin kepastian Pembayaran Kembali dengan tertib dan sebagaimana
                                            mestinya, maka Penerima Dana dan/atau pihak ketiga yang ditunjuk Penerima
                                            Dana dapat memberikan jaminan, selama dalam pelaksanaan pendanaan ini
                                            dipersyaratkan atas  jaminan yang ditentukan oleh Pemberi Dana yang dalam
                                            hal ini juga menjadi pihak penerima jaminan oleh karenanya Penerima Dana
                                            setuju bahwa Pemberi Dana dan/atau Pihak Ketiga yang ditunjuk Pemberi Dana
                                            dapat melakukan eksekusi atas jaminan sebagaimana yang diperlukan
                                            berdasarkan perjanjian ini apabila. Penjaminan disini yaitu termasuk namun
                                            tidak terbatas penanggungan yang dilakukan baik dari perorangan maupun
                                            badan hukum dan/atau jaminan kebendaan yang diatur berdasarkan peraturan
                                            perundang-undangan meliputi gadai, fidusia, hak tanggungan, hipotek kapal
                                            dan resi gudang, yang mana beberapa atau keseluruhan penjaminan tersebut
                                            dapat menjadikan Perjanjian Pendanaan menjadi dasar penjaminan dan
                                            eksekusi jaminan, atau sebaliknya jika diperlukan ketentuan lebih lanjut
                                            Para Pihak dapat mengaturnya melalui perjanjian jaminan yang terpisah
                                            dari Perjanjian Pendanaan ini.
                                        </p>
                                    </div>
                                </li>
                            </ol>
                            </div>
                        </li>
                    </ol>
                    </div>
                </li>
                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                    <div>
                    <b>HAK DAN KEWAJIBAN</b>
                    <ol class="section2">
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                            <b>Hak dan Kewajiban Pemberi Dana</b>
                            <p>
                                Dengan tidak mengesampingkan hak-hak dan kewajiban-kewajiban lain yang diatur
                                dalam Perjanjian Pendanaan ini, hak dan kewajiban Pemberi Dana, adalah sebagai
                                berikut:
                            </p>
                            <ol type="a" style="list-style:lower-alpha;">
                                <li>
                                    Wajib menyediakan Pendanaan dan mencairkan  Pendanaan kepada Anda
                                    sesuai Perjanjian Pendanaan ini.
                                </li>
                                <li>
                                    Wajib melaksanakan  seluruh ketentuan-ketentuan dalam Perjanjian
                                    Pendanaan ini.
                                </li>
                                <li>
                                    Berhak menolak atau memberikan persetujuan pemberian Pendanaan
                                    berdasarkan penilaiannya dan/atau penilaian skor kredit yang
                                    disediakan JULO.
                                </li>
                                <li>
                                    Berhak menerima pembayaran secara penuh atas seluruh kewajiban
                                    pembayaran tagihan Anda termasuk namun tidak terbatas, pembayaran
                                    kembali Pendanaan, Biaya Provisi, Bunga Pendanaan, Denda Keterlambatan
                                    (Jika Ada), serta biaya-biaya lain berdasarkan Perjanjian Pendanaan
                                    ini (Jika Ada).
                                </li>
                                <li>
                                    Berhak melaksanakan segala proses penagihan atas seluruh kewajiban
                                    pembayaran Anda termasuk namun tidak terbatas penagihan  melalui
                                    JULO atau dengan menunjuk pihak ketiga lainnya yang ditunjuk JULO
                                    atau Pemberi Dana, serta memberikan peringatan secara tertulis dalam
                                    hal Penerima Dana mengalami keterlambatan pembayaran, Penerima Dana
                                    setuju bahwa proses penagihan dapat dilakukan melalui tata cara
                                    sebagai berikut :
                                    <ol type="i" style="list-style:lower-roman;">
                                        <li>
                                            <i>Desk Collection</i>, yaitu penagihan melalui sarana komunikasi
                                            elektronik, seperti telepon, SMS, surat elektronik, dan/atau
                                            media komunikasi elektronik lainnya ke nomor telepon atau email
                                            yang terdaftar pada Aplikasi JULO;
                                        </li>
                                        <li>
                                            <i>Field Collection</i>, yaitu penagihan melalui kunjungan lapangan ke
                                            alamat Penerima Dana yang terdaftar pada Aplikasi JULO;
                                        </li>
                                        <li>
                                            Tata cara lain yang disyaratkan dan diperbolehkan oleh Asosiasi,
                                            OJK atau pemerintah yang berwenang lainnya.
                                        </li>
                                    </ol>
                                </li>
                                <li>
                                    Berhak mengambil tindakan yang diperlukan dalam hal Penerima Dana tidak
                                    menjalankan atau melakukan pelanggaran atas pelaksanaan hak dan kewajiban
                                    berdasarkan Perjanjian Pendanaan ini, termasuk namun tidak terbatas
                                    melaporkan kepada OJK ke dalam Daftar
                                </li>
                                <li>
                                    Berhak untuk memindahkan dan mengalihkan Pendanaan dan Tagihan sesuai
                                    dengan Perjanjian Pendanaan ini.
                                </li>
                            </ol>
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                            <b>Hak dan Kewajiban Penerima Dana</b>
                            <p>
                                Dengan tidak mengesampingkan hak-hak dan kewajiban-kewajiban lain yang
                                diatur dalam Perjanjian Pendanaan ini, hak dan kewajiban Anda sebagai Penerima
                                Dana adalah sebagai berikut :
                            </p>
                            <ol type="a" style="list-style:lower-alpha;">
                                <li>
                                    Wajib membayar secara penuh kewajiban pembayaran atas Pendanaan yang
                                    diberikan pada tanggal jatuh tempo pembayaran, termasuk namun tidak
                                    terbatas untuk membayar Bunga Pendanaan dan Denda Keterlambatan
                                    (apabila ada) dan biaya-biaya relevan sebagaimana relevan berdasarkan
                                    Perjanjian Pendanaan ini.
                                </li>
                                <li>
                                    Wajib memberitahukan Pemberi Dana dan/atau JULO atas setiap terjadinya
                                    perubahan data atau informasi dari Penerima Dana.
                                </li>
                                <li>
                                    Wajib melaksanakan seluruh ketentuan-ketentuan dalam Perjanjian Pendanaan
                                    ini dan Hukum yang berlaku dengan itikad baik dan penuh tanggung jawab.
                                </li>
                                <li>
                                    Berhak menerima Pendanaan dan menerima pencairan dana berdasarkan
                                    Perjanjian Pendanaan ini.
                                </li>
                                <li>
                                    Berhak melakukan pembayaran dipercepat.
                                </li>
                                <li>
                                    Berhak untuk mendapatkan informasi atau akses informasi mengenai status
                                    pendanaan yang diterima dengan benar, akurat dan tidak menyesatkan.
                                </li>
                                <li>
                                    Berhak mengajukan permohonan bukti atas  seluruh kewajiban pembayaran
                                    secara penuh, yang telah dilakukan oleh Penerima Dana kepada Pemberi
                                    Dana. Permohonan bukti pembayaran ini akan diberikan dalam bentuk
                                    Surat Keterangan Lunas yang akan disampaikan secara elektronik melalui
                                    aplikasi JULO dan sesuai dengan Standar Oerasional pemberian Surat
                                    Keterangan Lunas dari JULO.
                                </li>
                            </ol>
                            </div>
                        </li>
                    </ol>
                    </div>
                </li>
                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                    <div>
                    <b>PENGALIHAN</b>
                    <ol class="section2">
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Anda dapat mengakui dan menyetujui bahwa Pemberi Dana dapat memindahkan atau
                                mengalihkan setiap dana yang masih terutang dan Tagihan kepada pihak lain
                                termasuk namun tidak terbatas pada bank, Lembaga keuangan bukan bank atau
                                institusi keuangan lainnya dengan tunduk hukum yang berlaku, dan setiap
                                pengalihan tersebut akan diberitahukan kepada Anda melalui Aplikasi atau
                                melalui media komunikasi  atau sarana lainnya sebagaimana yang ditentukan
                                JULO dari waktu ke waktu.
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Penerima Dana tidak dapat mengalihkan, baik sebagian maupun seluruh hak dan
                                kewajiban yang timbul dari atau terkait dengan Pendanaan berdasarkan Perjanjian
                                Pendanaan ini kepada pihak manapun, tanpa persetujuan dari Pemberi Dana atau
                                JULO (untuk dan atas nama Pemberi Dana).
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Penerima Dana menyetujui dan mengakui keabsahan pengalihan yang dilakukan
                                setiap Pemberi Dana berdasarkan ayat 4.1 pada pasal ini, dan tidak akan
                                mengajukan keberatan atas pengalihan yang dilakukan demikian.
                            </div>
                        </li>
                    </ol>
                    </div>
                </li>
                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                    <div>
                    <b>PAJAK, BEA MATERAI DAN BIAYA-BIAYA LAIN</b>
                        <ol class="section2">
                            <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                                <div>
                                    Para Pihak setuju bahwa segala kewajiban perpajakan, biaya bea materai
                                    dan/atau biaya-biaya lain (Jika Ada) yang dikenakan pemerintah saat ini
                                    atau yang akan datang dalam bentuk apapun yang dikenakan, dipungut atau
                                    dipungut oleh atau atas nama otoritas pemerintahan, yang timbul berdasarkan
                                    Perjanjian Pendanaan ini akan menjadi beban masing-masing Pihak atau salah
                                    satu Pihak sesuai dengan ketentuan perpajakan yang berlaku di negara Republik
                                    Indonesia dan/atau kesepakatan Para Pihak.
                                </div>
                            </li>
                        </ol>
                    </div>
                </li>
                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                    <div>
                    <b>PENGGUNAAN DATA PRIBADI</b>
                    <ol class="section2">
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Dengan menyetujui Perjanjian Pendanaan ini, Anda menyatakan bahwa Anda
                                telah membaca dan menyetujui Kebijakan Data Pribadi, yang dapat diakses
                                pada website Kami atau sebagaimana yang tercantum dalam <b>Lampiran 2.
                                Kebijakan Data Pribadi.</b> Oleh karenanya, Anda wajib membaca, memahami
                                dan mengerti kebijakan Data Pribadi JULO dan/atau Mitra Bisnis. Kebijakan
                                Data Pribadi ini merupakan bagian yang tidak terpisahkan dengan Perjanjian
                                Pendanaan dan kebijakan JULO dan/atau Mitra Bisnis ini dapat berubah dari
                                waktu ke waktu tanpa memerlukan persetujuan Para Pihak.
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Dengan Anda menekan fitur  persetujuan (<i>consent</i>) yang akan muncul pada
                                halaman Aplikasi Anda pada saat pengajuan Pendanaan, maka Anda juga telah
                                menyetujui Kebijakan Data Pribadi JULO dan/atau Mitra Bisnis
                                sebagaimana laman website diatas.
                            </div>
                        </li>
                    </ol>
                    </div>
                </li>
                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                    <div>
                    <b>MEKANISME PENYELESAIAN SENGKETA</b>
                    <ol class="section2">
                       <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                           <div>
                               Penafsiran dan pelaksanaan Perjanjian Pendanaan ini dan segala akibatnya
                               diatur dan ditafsirkan menurut hukum Republik Indonesia.
                           </div>
                       </li>
                       <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                           <div>
                               Apabila terjadi perselisihan atau sengketa antara Para Pihak yang timbul
                               berdasarkan Perjanjian Pendanaan ini, Para Pihak sepakat untuk
                               menyelesaikannya terlebih dahulu dengan cara musyawarah untuk mencapai
                               mufakat. Apabila sengketa tersebut tidak dapat diselesaikan dengan cara
                               musyawarah, Para Pihak sepakat untuk menyerahkan kepada dan diselesaikan
                               di tingkat akhir arbitrase di Indonesia yang diselenggarakan oleh Lembaga
                               Alternatif Penyelesaian Sengketa Sektor Jasa Keuangan (“<b>LAPS SJK</b>”),
                               sesuai ketentuan LAPS SJK yang berlaku pada saat itu. Arbitrase akan
                               dilangsungkan dengan 1 (Satu) orang arbiter dan Bahasa yang digunakan
                               dalam arbitrase adalah Indonesia.
                           </div>
                       </li>
                    </ol>
                    </div>
                </li>
                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                    <div>
                    <b>PERNYATAAN DAN JAMINAN</b>
                    <ol class="section2">
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                            Penerima Dana dengan ini menyatakan dan menjamin Pemberi Dana bahwa :
                            <ol type="a" style="list-style:lower-alpha;">
                                <li>
                                    Penerima Dana adalah Warga Negara Indonesia dan tunduk secara sah
                                    pada hukum Republik Indonesia, yang merupakan orang perorangan yang
                                    cakap hukum untuk mengadakan dan melaksanakan Perjanjian Pendanaan
                                    ini, sesuai ketentuan perundang-undangan yang berlaku, dan telah
                                    mendapatkan seluruh persetujuan dan perizinan yang dibutuhkan
                                    (termasuk namun tidak terbatas kepada persetujuan pasangan) untuk
                                    menandatangani Perjanjian Pendanaan ini.
                                </li>
                                <li>
                                    Penerima Dana telah membaca dan memahami dan telah mendapatkan saran
                                    yang diperlukan mengenai keberlakuan dari Perjanjian Pendanaan ini.
                                </li>
                                <li>
                                    Seluruh fakta, data, informasi, dokumen dan keterangan yang Anda
                                    berikan untuk mendapatkan Pendanaan  adalah benar, jelas, jujur,
                                    terbaru, akurat dan lengkap.
                                </li>
                            </ol>
                            </div>
                        </li>
                    </ol>
                    </div>
                </li>
                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                    <div>
                    <b>LAIN-LAIN</b>
                    <ol class="section2">
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Setiap komunikasi dan pemberitahuan yang diisyaratkan atau diperbolehkan untuk
                                diberikan kepada Para Pihak dibuat secara tertulis melalui pengumuman, surat
                                elektronik, surat tercatat, Aplikasi, Platform Penyelenggara, nomor telepon
                                resmi JULO, atau melalui media komunikasi lainnya.
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Apabila satu atau lebih ketentuan dalam Perjanjian Pendanaan ini menjadi tidak
                                berlaku, tidak sah atau tidak dapat dilaksanakan dalam cara apapun menurut Hukum
                                yang berlaku, hal tersebut tidak mempengaruhi keabsahan, keberlakuan, dan dapat
                                dilaksanakannya ketentuan-ketentuan lain dalam Perjanjian Pendanaan ini.
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                            <b>Fitur JULO</b>, sebagaimana dijelaskan di bawah ini :
                            <ol type="a" style="list-style:lower-alpha;">
                                <li>
                                    ialah fungsi/karakteristik dalam hal teknologi, yang dimiliki dan/atau
                                    disediakan pada Aplikasi JULO dengan tujuan membantu memudahkan Penerima
                                    Dana dalam melakukan transaksi dengan Aplikasi JULO.
                                </li>
                                <li>
                                    Setiap fitur yang disediakan oleh JULO kepada Anda dan Fitur lainnya yang
                                    dimiliki JULO dan/atau Fitur yang diperoleh dari kerjasama dengan Mitra
                                    Bisnis, yang mana  akan terus diperbaharui, ditambahkan, dihapus, diganti,
                                    dan/atau dirilis ulang, dan hal ini merupakan sepenuhnya kebijakan
                                    dan kewenangan JULO.
                                </li>
                                <li>
                                    Tanpa mengurangi maksud pasal 9.4, Setiap atau beberapa penggunaan Fitur
                                    JULO oleh Anda sebagaimana yang diperlukan dalam Dokumen-Dokumen Elektronik,
                                    JULO berhak membutuhkan tindakan persetujuan tertentu di luar Perjanjian
                                    Pendanaan ini, yang menginstruksikan dan/atau mengizinkan JULO mengakses
                                    dan memproses data-data yang Anda berikan untuk tujuan penggunaan fitur
                                    tersebut, seperti termasuk namun tidak terbatas pernyataan dan persetujuan
                                    Anda, yang diperoleh secara elektronik pada Aplikasi JULO dan cara lain
                                    yang akan disepakati Para Pihak. Persetujuan ini merupakan bagian dari
                                    pernyataan tambahan yang merupakan satu-kesatuan yang tidak terpisahkan
                                    dan sebagai bentuk pelaksanaan dari Perjanjian Pendanaan ini, yang sama
                                    mengikatnya dan sah secara hukum.
                                </li>
                            </ol>
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                            <b>Tanda Tangan Elektronik.</b>
                            <ol type="a" style="list-style:lower-alpha;">
                                <li>
                                    Tanda Tangan Elektronik adalah tanda tangan yang berupa informasi
                                    elektronik yang dilekatkan, terasosiasi atau terkait informasi elektroniknya
                                    yang digunakan sebagai alat verifikasi dan autentikasi.
                                </li>
                                <li>
                                    Penggunaan tanda tangan elektronik oleh Penerima Dana pada Dokumen-Dokumen
                                    Elektronik, yang mana merupakan satu-kesatuan dari padanya adalah sah,
                                    benar dan mengikat secara hukum yang sama kuatnya dengan tanda tangan
                                    fisik.
                                </li>
                                <li>
                                    Para Pihak dapat menggunakan tanda tangan elektronik untuk satu atau
                                    beberapa dokumen dari Dokumen-Dokumen Elektronik dengan klasifikasi
                                    tertentu, baik dengan, maupun tanpa menggunakan sertifikat elektronik
                                    yang dibuat oleh penyelenggara sertifikat elektronik Indonesia yang
                                    terdaftar di instansi terkait, sepanjang memenuhi persyaratan yang
                                    diatur dalam Undang-Undang mengenai informasi dan transaksi elektronik
                                    atau sejenisnya. Pengklasifikasian tersebut diatur sesuai standar
                                    operasional prosedur yang berlaku di JULO dan/atau Mitra Bisnis.
                                </li>
                                <li>
                                    Dalam hal proses autentikasi tambahan, jika diperlukan, Penerima Dana
                                    dengan ini memberikan kuasa kepada Pemberi Dana untuk menyematkan tanda
                                    tangan elektronik pada setiap Perjanjian Pendanaan dan SKRTP atau
                                    Dokumen-Dokumen Elektronik lainnya, dengan tata cara yang diinstruksikan
                                    oleh JULO dan/atau Mitra Bisnis sesuai peraturan yang berlaku terkait
                                    tanda tangan elektronik, termasuk namun tidak terbatas dengan cara
                                    menekan fitur persetujuan (<i>consent</i>) yang akan muncul pada setiap SKRTP
                                    dan/atau Dokumen-Dokumen Elektronik lainnya, atau memasukan Kode PIN
                                    yang Anda miliki  ataupun cara lain yang sah sesuai kesepakatan Para
                                    Pihak.
                                </li>
                                <li>
                                    Para Pihak mengetahui dan sepakat bahwa Tanda Tangan Elektronik yang
                                    disematkan sebagaimana huruf d ayat ini adalah Tanda Tangan elektronik
                                    yang keabsahannya diatur dan distandarisasi oleh standar operasional
                                    prosedur yang berlaku di JULO dan/atau Mitra Bisnis.
                                </li>
                            </ol>
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Pemberi Dana dan/atau JULO telah menyusun Perjanjian Pendanaan ini dengan maksud
                                menyeragamkan atau menstandarisasikan isi dan bentuk Perjanjian Pendanaan ini
                                secara elektronik, terkait bentuk kegiatan, skema dan/atau model pendanaan yang
                                dilakukan antara Pemberi Dana dan Penerima Dana. Apabila terdapat segala bentuk
                                Perjanjian Pendanaan lainnya yang berbeda dari isi dan bentuk Perjanjian Pendanaan
                                ini akan segera disesuaikan dengan standar Perjanjian Pendanaan ini di
                                kemudian hari.
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Pemberi Dana dan/atau JULO dan/atau Mitra Bisnis dapat memberikan akses kepada
                                Penerima Dana untuk dapat mencetak Perjanjian Pendanaan ini. Dalam hal ini,
                                Perjanjian Pendanaan bersifat elektronik, sehingga memungkinkan Penerima Dana
                                tidak dapat mencetak keseluruhan lampiran berupa tautan sehingga memerlukan
                                tindakan tambahan untuk mengakses terlebih dahulu lampiran-lampiran bertautan
                                tersebut.
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Perjanjian ini telah disesuaikan dengan ketentuan peraturan perundang-undangan
                                termasuk ketentuan Peraturan Otoritas Jasa Keuangan.
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Menyimpang dari hal-hal yang bertentangan, ketentuan Perjanjian Pendanaan ini
                                dapat sewaktu-waktu diubah atau diubah secara tertulis dengan persetujuan
                                bersama Para Pihak dan tidak ada modifikasi atau tambahan pada bagian manapun
                                dari Perjanjian Pendanaan ini kecuali dibuat dengan Adendum/Amandemen tertulis
                                yang ditandatangani oleh perwakilan resmi Para Pihak.
                            </div>
                        </li>
                    </ol>
                    </div>
                </li>
                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                    <div>
                    <b>MEKANISME PENYELESAIAN HAK dan KEWAJIBAN SESUAI JIKA JULO TIDAK DAPAT
                        MELANJUTKAN KEGIATAN OPERASIONALNYA.</b>
                    <ol class="section2">
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Pemberi Dana melalui JULO akan menginformasikan kepada Penerima Dana
                                mengenai rencana penghentian Layanan JULO dalam jangka waktu tertentu
                                yang akan diinformasikan beserta alasan dan rencana penyelesaian hak
                                dan kewajiban baik antara JULO dengan Penerima Dana maupun Pemberi Dana
                                melalui Sistem Elektronik milik JULO dan/atau media lain yang relevan,
                                sebelum rencana tersebut dilakukan.
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                            Penyelesaian hak dan kewajiban JULO kepada seluruh pengguna baik
                            Penerima Dana maupun Pemberi Dana dapat dilakukan melalui :
                            <ol type="a" style="list-style:lower-alpha;">
                                <li>
                                    posisi akhir pengalihan porfolio Pendanaan yang tertunggak
                                    dari Penerima Dana;
                                </li>
                                <li>
                                    tata cara atau mekanisme lain yang akan disepakati Para
                                    Pihak dalam Perjanjian Pendanaan ini.
                                </li>
                            </ol>
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Tanpa mengurangi maksud pasal 10.1 dan pasal 10.2 Perjanjian Pendanaan ini,
                                penyelesaian hak dan kewajiban wajib diselesaikan sejak persetujuan yang
                                akan disampaikan ke OJK kepada JULO.
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Mekanisme dan jangka waktu penyelesaian seluruh kewajiban yang timbul dalam
                                penyelenggaraan LPBBTI ditetapkan oleh OJK dengan memperhatikan rencana
                                tindak lanjut yang disampaikan oleh JULO.
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Pemberi Dana dapat melakukan mekanisme apapun yang disebutkan pada pasal 10.2,
                                dengan kesepakatan terlebih dahulu dengan Penerima Dana.
                            </div>
                        </li>
                    </ol>
                    </div>
                </li>
                <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                    <div>
                    <b>FORCE MAJEURE</b>
                    <ol class="section2">
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                Pengertian Force Majeure adalah suatu keadaan tanpa kesalahan atau kelalaian
                                yang disebabkan oleh salah satu Pihak yang terjadi di luar kendali Pihak
                                tersebut, dimana Pihak tersebut secara wajar tidak dapat mencegah atau
                                mengatasinya, termasuk namun tidak terbatas pada bencana alam, wabah penyakit,
                                perang (dinyatakan atau tidak), invasi, konflik bersenjata, kerusuhan, demonstrasi,
                                revolusi atau kudeta, tindakan terorisme, sabotase atau kerusakan karena
                                kriminalisme, ledakan nuklir, kontaminasi radioaktif atau kimia atau radiasi
                                ionisasi, gelombang tekanan yang disebabkan oleh pesawat terbang atau lainnya
                                benda terbang yang melaju dengan kecepatan suara atau di atas kecepatan suara,
                                gangguan listrik, gangguan sistem atau jaringan pihak ketiga lainnya atau
                                perubahan peraturan perundang-undangan atau kebijakan pemerintah yang dapat
                                mempengaruhi kemampuan salah satu Pihak atau Para Pihak. Dalam keadaan force
                                majeure, Penerima Dana tetap bertanggung jawab atas kewajibannya berdasarkan
                                Perjanjian Pendanaan ini.
                            </div>
                        </li>
                        <li style="display:flex;display:-webkit-box;-webkit-box-pack:center;justify-content:center;">
                            <div>
                                JULO dan/atau Mitra Bisnis atas permintaan Pemberi Dana atau berdasarkan
                                kuasa Pemberi Dana, dapat menghentikan layanan Pendanaan kepada Anda atau
                                mengambil tindakan atau langkah-langkah yang dipandang perlu oleh JULO, setiap
                                saat jika terjadi Force Majeure sebagaimana yang disebutkan pada pasal 11.1 ini.
                            </div>
                        </li>
                    </ol>
                    </div>
                </li>
            </ol>
            <br>
    </div>
        <br><br>
        <div style="margin-top:100px">
            <h3 style="text-align:center;">
                Lampiran 1
            </h3>
            <h4 style="text-align:center;">
                SYARAT DAN KETENTUAN PENGGUNAAN
            </h4>
            <div>
                <ol type="a" style="list-style:lower-alpha;">
                    <li>
                        Syarat dan Ketentuan JULO <a href="https://www.julo.co.id/terms-and-conditions"
                                                     target="_blank">
                        (dalam bentuk tautan)</a>
                    </li>

                </ol>
            </div>
        </div>
        <div>
            <h3 style="text-align:center;">
                Lampiran 2
            </h3>
            <h4 style="text-align:center;">
                KEBIJAKAN DATA PRIBADI
            </h4>
            <div>
                <ol type="a" style="list-style:lower-alpha;">
                    <li>
                        Kebijakan Privasi JULO <a href="https://www.julo.co.id/privacy-policy"
                                                  target="_blank">
                        (dalam bentuk tautan)</a>
                    </li>
                    <li>
                        Kebijakan Privasi Mitra Bisnis <a
                            href="https://www.grab.com/id/terms-policies/privacy-notice/"
                            target="_blank">
                        (dalam bentuk tautan)</a>
                    </li>
                </ol>
            </div>
        </div>
        <div>
            <h3 style="text-align:center;">
                Lampiran 3
            </h3>
            <div class="titleSkrtp">
                <div><b>SURAT KONFIRMASI RINCIAN TRANSAKSI PENDANAAN</b>
                </div>
            </div>

        <div>
        <div class="divContent">
            <div>
                Surat Konfirmasi Rincian Transaksi Pendanaan (selanjutnya disebut <b>“SKRTP”</b>) ini
                dibuat dan disetujui pada tanggal {{ signature_date }}, oleh dan antara :
            </div>
            <ol>
                <li>
                    <div><b>Pemberi Dana</b> yaitu perusahaan atau orang perseorangan dengan
                        detail identitas legalitas sebagai berikut :</div>
                    <ol class="table-same">
                        <li>
                            <span>Nama/Perusahaan</span> <span>{{ lender_company_name }}</span>
                        </li>
                        <li>
                            <span>Nama Perwakilan Perusahaan</span> <span>{{ lender_director }}</span>
                        </li>
                        <li>
                            <span>Nomor Izin Perusahaan Terkait</span> <span>{{ lender_license_number }}</span>
                        </li>
                        <li>
                            <span>Alamat Terdaftar	</span> <span>{{ lender_full_address }}</span>
                        </li>
                    </ol>
                </li>
                <br>
                <li>
                    <div><b>Penerima Dana</b>, yang memiliki identitas sebagai berikut: </div>
                    <ol class="table-same">
                        <li>
                            <span>Nama</span> <span>{{ application.fullname }}</span>
                        </li>
                        <li>
                            <span>Tgl. Lahir</span> <span>{{ dob }}</span>
                        </li>
                        <li>
                            <span>No. KTP</span> <span>{{ application.ktp }}</span>
                        </li>
                        <li>
                            <span>No. Telpon</span> <span>{{ application.mobile_phone_1 }}</span>
                        </li>
                        <li>
                            <span>Alamat</span> <span>{{ full_address }}</span>
                        </li>
                    </ol>
                </li>
                <br>
            </ol>
        </div>

        <div class="divContent">
            <div>
                Untuk selanjutnya, Penerima Dana dan Pemberi Dana secara bersama-sama
                disebut juga <b>“Para Pihak”</b> dan masing-masing disebut <b>“Pihak”</b>.
            </div>
            <br>
            <div>
                Penerima Dana menyatakan setuju untuk mengikatkan diri kepada Pemberi
                Dana atas ketentuan-ketentuan sebagai berikut:
            </div>
            <ol>
                <li>
                    Bahwa Penerima Dana mengajukan permohonan Pendanaan kepada Pemberi Dana
                    dengan nomor Perjanjian Pendanaan {{ loan.loan_xid }} melalui
                    JULO, dan telah disetujui dalam bentuk GrabModal dengan Pokok
                    Pendanaan sebesar {{ loan_amount }}, dengan biaya provisi sebesar
                    {{ provision_fee_amount }} dan Bunga Pendanaan sebesar {{ interest_rate }}
                    per bulan (Total Pendanaan)

                </li>
                <li>
                    Jika telah terjadi pembayaran atas Total Pendanaan sebagaimana butir 1, maka sisa
                    pembayaran yang harus dibayarkan oleh Penerima Dana adalah
                    {{ loan_amount }}, sebaliknya sisa pembayaran akan otomatis tertera
                    sebesar {{ loan_amount }}, jika belum terdapat pembayaran apapun.

                </li>

                <li>
                    Bahwa Penerima Dana berjanji untuk melunasi Pendanaan dengan melakukan
                    pembayaran sesuai dengan jadwal berikut ini:
                    <ol type="a" style="list-style:lower-alpha;">
                        <li>
                            Cicilan harian sebesar {{ installment_amount }} selama
                            {{ loan_duration }} hari.
                        </li>
                    </ol>
                </li>

                <li>
                    Bahwa Penerima Dana akan melakukan pembayaran setiap hari sebelum tanggal jatuh tempo.
                    Keterlambatan akan dikenakan biaya denda sebesar {{late_fee_amount}} per hari, untuk
                    setiap angsuran yang terlambat, dengan total kumulatif tidak melebihi
                    {{max_total_late_fee_amount}}.
                </li>
                <li>
                    Sehubungan dengan status Penerima Dana selaku mitra pengemudi terdaftar dan aktif pada
                    Aplikasi Grab (<b>“Mitra Pengemudi”</b>) yang dikelola oleh PT Grab Teknologi Indonesia
                    dan afiliasinya (<b>“Grab”</b>), pada saat penandatanganan Perjanjian Pendanaan ini, maka
                    Penerima Dana, selama terdaftar sebagai Mitra Pengemudi, dengan ini sepakat untuk:

                    <ol type="a" style="list-style:lower-alpha;">
                        <li>
                            wajib mengisi ulang dan menjaga total saldo pada dompet elektronik Mitra
                            Pengemudi dalam Aplikasi Grab, baik credit wallet maupun cash wallet-nya yang
                            terdaftar atas nama Penerima Dana (“Dompet Mitra Pengemudi”), sekurang-kurangnya
                            sebesar total cicilan terutang yang telah jatuh tempo pada hari pembayaran;
                        </li>
                        <li>
                            Selama aktif menjadi Mitra Pengemudi, Penerima Dana dengan ini:
                            <ol type="i" style="list-style:lower-roman;">
                                <li>
                                    Setuju untuk memberikan kuasa kepada Pemberi Dana untuk
                                    mengungkapkan data pribadi yang relevan (yaitu: nama lengkap
                                    sesuai KTP, Nomor KTP), serta total cicilan terutang yang telah
                                    jatuh tempo kepada Grab untuk kepentingan pemotongan atas saldo
                                    Dompet Mitra Pengemudi;
                                </li>
                                <li>
                                    memberikan kuasa dengan hak substitusi kepada Pemberi Dana yang
                                    selanjutnya Pemberi Dana akan menguasakan kembali kepada kepada
                                    Grab, selaku pengelola Aplikasi Grab di Indonesia, untuk melakukan
                                    pemotongan atas saldo Dompet Mitra Pengemudi, sejumlah cicilan
                                    terutang Penerima Dana sebagaimana diberitahukan oleh Pemberi
                                    Dana melalui JULO kepada Grab dari waktu ke waktu dan telah
                                    disetujui secara tegas oleh Penerima Dana. Jika saldo Dompet
                                    Mitra Pengemudi tidak mencukupi untuk memenuhi jumlah cicilan
                                    yang terhutang, Penerima Dana setuju bahwa beberapa upaya
                                    pemotongan atas saldo akan dilakukan setiap hari sampai
                                    jumlah penuh yang tersisa untuk jumlah cicilan yang relevan diterima;
                                </li>
                                <li>
                                    memberikan persetujuan bagi JULO, melalui kanal komunikasi yang
                                    dimiliki atau dikelola oleh Grab, untuk memberikan pemberitahuan
                                    serta peringatan kewajiban membayar cicilan terutang dari waktu ke
                                    waktu selama Perjanjian ini belum berakhir dan Penerima Dana masih
                                    memiliki kewajiban terutang terhadap JULO dan Pemberi Dana;
                                </li>
                                <li>
                                    setuju bahwa selama Penerima Dana tetap sebagai Mitra Pengemudi
                                    dan memiliki pembayaran Pendanaan yang terutang berdasarkan
                                    Perjanjian ini, Penerima Dana tidak akan mengajukan Pendanaan
                                    jenis lainnya melalui JULO dan setuju bahwa JULO memiliki hak
                                    untuk menolak aplikasi Pendanaan dalam hal tersebut;
                                </li>
                                <li>
                                    setuju untuk tidak menjual, menghibahkan, atau mengalihkan dalam
                                    bentuk apapun atas akun/Aplikasi Grab yang dimilikinya semata-mata
                                    untuk mengalihkan kewajibannya dalam pembayaran Pendanaan yang
                                    terutang, terkecuali Aplikasi Grab yang dimiliki dinonaktifkan
                                    sementara oleh Grab Indonesia untuk menghindari penyalahgunaan akun;
                                </li>
                                <li>
                                    setuju untuk tetap bertanggung jawab atas segala pembayaran
                                    Pendanaan berikut bunga, dan denda keterlambatan (jika ada)
                                    apabila layanan Penerima sebagai Mitra Pengemudi diakhiri atau
                                    ditangguhkan atas alasan apapun;
                                </li>
                            </ol>
                        </li>
                        <li>
                            Penerima Dana dengan ini membebaskan Grab, Pemberi Dana, dan JULO dari
                            segala tuntutan, akibat hukum, dan/atau kerugian yang ditimbulkan bagi
                            Penerima Dana sehubungan dengan Perjanjian ini, termasuk namun tidak
                            terbatas pada pemotongan saldo Dompet Mitra Pengemudi oleh Grab yang
                            dilakukan sesuai dengan kuasa yang diberikan secara khusus di luar
                            Perjanjian ini, sepanjang Grab dapat membuktikan bahwa pemotongan
                            tersebut sesuai dengan cicilan terutang Penerima Dana sebagaimana
                            diberitahukan oleh JULO kepada Grab dari waktu ke waktu;
                        </li>
                        <li>
                            Dalam hal Penerima Dana tidak lagi terdaftar sebagai Mitra Pengemudi
                            dengan alasan apapun, maka Penerima Dana wajib untuk memberitahukan hal
                            tersebut kepada JULO selambat-lambatnya 7 hari sejak tanggal
                            efektif deregistrasi tersebut melalui :
                            <ol type="i" style="list-style:lower-roman;">
                                <li>
                                    Email: cs@julo.co.id;
                                </li>
                                <li>
                                    Call Center :021 5091 9034 / 021 5091 9036 (senin-minggu pukul
                                    08.00-17.00);
                                </li>
                                <li>
                                    Whatsapp : 0811 1778 2070 / 0813 1778 2065 (chat only).
                                </li>
                            </ol>
                        </li>
                        <li>
                            Kewajiban Penerima Dana untuk melakukan pembayaran Pendanaan akan terus
                            berlanjut meskipun ada penangguhan atau penghentian Penerima Dana sebagai
                            Mitra Pengemudi selama tenor Pendanaan.
                        </li>
                    </ol>
                </li>
                <li>
                    Bahwa jika terjadi keterlambatan sebagaimana pasal 3 di atas, maka Penerima Dana
                    bersedia, setuju, dan memberikan izin kepada Pejabat JULO atau pihak yang ditunjuk
                    JULO untuk melakukan penagihan dan/atau kunjungan sesuai dengan peraturan di Indonesia.
                </li>
                <li>
                    Pernyataan Persetujuan
                    <ol style="list-style-type: lower-alpha;">
                        <li>
                            Penerima Dana dan Pemberi Dana mengerti atas hak dan kewajiban masing-masing pihak,
                            sesuai dengan yang tertuang pada Perjanjian Pendanaan sesuai No.
                            {{ loan.loan_xid }} dan akan senantiasa mematuhi ketentuan
                            hukum yang berlaku dalam melaksanakan SKRTP ini.
                        </li>
                        <li>
                            Hal yang belum dituangkan dalam SKRTP ini akan diatur di kemudian hari melalui
                            Perubahan SKRTP (Addendum), yang merupakan persetujuan lebih lanjut antara
                            Pemberi Dana dan Penerima Dana, dan bagian yang tidak terpisahkan dari
                            SKRTP ini, serta tidak memerlukan tanda tangan ulang.
                        </li>
                    </ol>

                </li>
            </ol>
            <br>
            <div>
                <b>DEMIKIAN</b>, Perjanjian Pendanaan beserta Lampiran-Lampirannya , yang man ini
                disetujui atau ditandatangani secara elektronik (termasuk menggunakan tanda tangan
                elektronik) sesuai dengan ketentuan dalam Undang-Undang Republik Indonesia No. 11
                Tahun 2008 tanggal 21 April 2008 tentang informasi dan Transaksi Elektronik berikut
                dengan segala perubahan/amandemennya dan peraturan pelaksananya beserta segala
                perubahan/amandemennya, dari waktu ke waktu oleh Para Pihak atau perwakilannya yang
                sah dan mempunyai kekuatan yang sama dengan perjanjian yang dibuat dan ditandatangani
                secara fisik.
            </div>
            <br>
            <br>

        </div>
        <div class="spaceSign"></div>
        <div class="divContent">
            <div class="divLeft">
                <div class="bold" style="text-alight:left;">Penerima Dana</div>
                <br>
                {% if signature %}
                    <img height="auto" src="{{signature}}" style="border:0;display:block;outline:none;text-decoration:none;height:auto;float:left;max-height:50px"/>
                {% endif %}
                <br>
                <br>
                <div class="enter enter-left" style="text-alight:left;">{{ application.fullname }}</div>
            </div>
            <div class="divRight">
                <div class="bold dateText">Pemberi Dana</div>
                <br>
                {% if signature %}
                {% if display_lender_signature %}
                <img height="auto" src="https://julofiles-staging.oss-ap-southeast-5.aliyuncs.com/signatures/ska.png" style="border:0;display:block;outline:none;text-decoration:none;height:auto;float:right;max-height:50px"/>
                <br>
                <br>
                {% endif %}
                <div class="divRight enter enter-right" style="white-space: nowrap;text-alight:right;">{{ lender_director }}</div>
                <br>
                <br>
                <div class="divRight enter enter-right" style="white-space: nowrap;text-alight:right;">{% if display_lender_signature %}Direktur{% endif %}</div>
                <br>
                <div class="divRight enter enter-right" style="white-space: nowrap;text-alight:right;"><b>{{ lender_company_name }}</b></div>
                {% endif %}
            <br>
            <br>
            <div class="divLeft"></div>
        </div>
        <div class="divRight"></div>
        </div>

    </div>
        </div>

    </div>
    </div>
</body>
</html>
"""


def get_sphp_template_grab_script(loan_id, type="document"):
    loan = Loan.objects.get_or_none(pk=loan_id)
    display_lender_signature = True
    if not loan:
        return None
    template = None
    sphp_date = loan.sphp_sent_ts
    payments = loan.payment_set.order_by('due_date')
    if not payments:
        return None
    start_date = payments.first().due_date
    end_date = payments.last().due_date
    today_date = timezone.localtime(timezone.now()).date()
    application = loan.account.application_set.last()
    provision_fee_amount = loan.provision_fee() + loan.product.admin_fee
    interest_rate = loan.product.interest_rate * 100
    maximum_late_fee_amount = loan.loan_amount if loan.late_fee_amount else 0
    total_due_amount = loan.installment_amount * loan.loan_duration
    disbursement_amount = loan.loan_amount - provision_fee_amount
    context = {
        'loan': loan, 'application': application,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.full_address,
        'loan_amount': display_rupiah(loan.loan_amount),
        'late_fee_amount': display_rupiah(loan.late_fee_amount),
        'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
        'background_image': settings.SPHP_STATIC_FILE_PATH + 'julo-a-4@3x.png',
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'start_date': format_date(start_date, 'dd-MM-yyyy', locale='id_ID'),
        'end_date': format_date(end_date, 'dd-MM-yyyy', locale='id_ID'),
        'total_number_of_payments': payments.count(),
        'max_total_late_fee_amount': display_rupiah(loan.late_fee_amount),
        'provision_fee_amount': display_rupiah(provision_fee_amount),
        'interest_rate': '{}%'.format(interest_rate),
        'installment_amount': display_rupiah(loan.installment_amount),
        'maximum_late_fee_amount': display_rupiah(maximum_late_fee_amount),
        'total_due_amount': display_rupiah(total_due_amount),
        'loan_duration': loan.loan_duration,
        'disbursement_amount': display_rupiah(disbursement_amount),
        'monthly_late_fee': 0,
        'max_monthly_late_fee': 0,
        'lender_director': "Aris Pondaag",
        'lender_company_name': "PT Sentral Kalita Abadi",
        'lender_license_number': "9120300152955",
        'lender_full_address': "Gedung Millennium Centennial Center, Jl. Jenderal "
                               "Sudirman, Kuningan, Setiabudi, Jakarta Selatan",
        'display_lender_signature': display_lender_signature,

    }
    signature_url = get_manual_signature_url_grab(loan)
    if signature_url:
        context['signature'] = signature_url
    else:
        context['signature'] = ''
        context['lender_director'] = ''
        context['lender_company_name'] = ''
        context['lender_license_number'] = ''
        context['lender_full_address'] = ''
        context['display_lender_signature'] = False

    if loan.loan_status_id in {
        LoanStatusCodes.LENDER_REJECT,
        LoanStatusCodes.GRAB_AUTH_FAILED
    }:
        context['lender_director'] = ''
        context['lender_company_name'] = ''
        context['lender_license_number'] = ''
        context['lender_full_address'] = ''
        context['display_lender_signature'] = False

    context['today_date_bahasa'] = format_date(sphp_date, 'd MMMM yyyy', locale='id_ID')
    signature_date = loan.sphp_accepted_ts if loan.sphp_accepted_ts else today_date
    context['signature_date'] = format_date(signature_date, 'dd-MM-yyyy', locale='id_ID')

    template_main = Template(template_body)
    template = template_main.render(Context(context))
    return template


def get_julo_loan_agreement_template_grab_script(loan_id, type="document"):

    def _template_return(
        template, agreement_type='sphp'
    ):
        return template, agreement_type, None, None

    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return None, None

    account = loan.account
    if not account:
        raise JuloException("ACCOUNT NOT FOUND")

    if account.is_grab_account():
        return _template_return(
            get_sphp_template_grab_script(loan_id, type),
        )
    else:
        raise JuloException("NOT GRAB ACCOUNT")


def get_summary_loan_agreement_template_grab_script(lender_bucket, lender, use_fund_transfer=False):
    template = LoanAgreementTemplate.objects.get_or_none(
        lender=lender, is_active=True, agreement_type=LoanAgreementType.SUMMARY)
    lender_info, director_info = get_lender_and_director_julo(lender.lender_name)
    if lender.lender_name in {'ska', 'ska2'}:
        lender_info['poc_name'] = 'Aris Pondaag'
        lender_info['signature'] = 'https://julofiles-staging.oss-ap-southeast-5.aliyuncs.com/signatures/ska.png'
    if not template or not director_info:
        return None

    today = timezone.localtime(timezone.now())
    if use_fund_transfer:
        today = timezone.localtime(lender_bucket.action_time)
    if lender_bucket.application_ids and lender_bucket.application_ids['approved']:
        approved = lender_bucket.application_ids['approved']
    else:
        approved = lender_bucket.loan_ids['approved']

    detail_loans = get_detail_loans(approved)
    loans = get_list_loans(detail_loans)

    context = {
        'lender': lender,
        'today_date': today.strftime("%d-%m-%Y"),
        'today_datetime': today.strftime("%d-%m-%Y %H:%M:%S"),
        'lender_poc_name': lender_info.get('poc_name', lender.poc_name),
        'no_SKP3': lender_bucket.lender_bucket_xid,
        'lender_poc_position': lender_info.get('poc_position', lender.poc_name),
        'loans': loans,
        'lender_signature': lender_info.get('signature', '#'),
        'director_poc_name': director_info.get('poc_name'),
        'director_poc_position': director_info.get('poc_position'),
        'director_signature': director_info.get('signature','#'),
        'full_lender_company_name': 'full_lender_company_name',
        'lender_license_no': lender_info.get('license_no'),
        'lender_address': lender_info.get('address'),
        'lender_company_name': lender_info.get(
            'lender_company_name', ''),
    }

    template = Template(template.body)
    return template.render(Context(context))


def generate_summary_lender_loan_agreement_grab_script(lender_bucket_id, use_fund_transfer=False):
    lender_bucket = LenderBucket.objects.get_or_none(pk=lender_bucket_id)
    if not lender_bucket:
        raise JuloException("LENDER BUCKET NOT FOUND")

    try:
        document = Document.objects.get_or_none(document_source=lender_bucket_id,
                                                document_type="summary_lender_sphp")
        if document:
            raise JuloException("DOCUMENT NOT FOUND")

        user = lender_bucket.partner.user
        lender = user.lendercurrent
        body = get_summary_loan_agreement_template_grab_script(lender_bucket, lender, use_fund_transfer)

        if not body:
            raise JuloException("BODY CANNOT BE EMPTY")
        filename = 'rangkuman_perjanjian_pinjaman-{}.pdf'.format(
            lender_bucket.lender_bucket_xid)
        file_path = os.path.join(tempfile.gettempdir(), filename )

        try:
            pdfkit.from_string(body, file_path)
        except Exception as e:
            print("EXCEPTION RAISED", print(e))
            return

        summary_lla = Document.objects.create(
            document_source=lender_bucket_id,
            document_type='summary_lender_sphp',
            filename=filename,
        )
        upload_document(summary_lla.id, file_path, is_bucket=True)

    except Exception as e:
        print("RAISE EXCEPTION")
        raise JuloException(e)


def run_main():
    loan_ids = []
    failed_loans = []
    successful_loans = []
    for loan_id in loan_ids:
        try:
            generate_julo_one_loan_agreement_grab_script.delay(loan_id)
            julo_one_generate_auto_lender_agreement_document_grab_script.delay(loan_id)
            successful_loans.append(loan_id)
        except JuloException as je:
            print(je, loan_id)
            failed_loans.append(loan_id)
            continue


def create_or_update_grab_cscore(limiter: int = 100, score: str = 'B-', update: bool = False):
    """
    create or update a record for table credit_score for grab applications

    params:
        - limiter (int) = max limit for each bulk_create inside of loop
        - score (str) = score needed to recorded
        - update (bool) = if true the script will also update the existing, if false then skip existing.
    """
    application_qs = Application.objects.filter(
        product_line__product_line_code__in=ProductLineCodes.grab(),
        application_status=ApplicationStatusCodes.LOC_APPROVED
    )
    list_application_ids = application_qs.values_list('id', flat=True)
    existing_cs_by_app_id_qs = CreditScore.objects.filter(application_id__in=list_application_ids)
    existing_app_id_in_cs = existing_cs_by_app_id_qs.values_list('application_id', flat=True)

    list_of_cs_obj_to_be_created = []
    list_of_cs_obj_to_be_updated = []

    if update:
        for cs_obj in existing_cs_by_app_id_qs.iterator():
            cs_obj.score = score
            list_of_cs_obj_to_be_updated.append(cs_obj)
            if len(list_of_cs_obj_to_be_updated) == limiter:
                bulk_update(list_of_cs_obj_to_be_updated,
                            update_fields=['score'], batch_size=limiter)
                list_of_cs_obj_to_be_updated = []
                print("success update existing 100 credit score")
        try:
            bulk_update(list_of_cs_obj_to_be_updated)
            print("---------finish update existing credit score---------")
        except Exception as err:
            print("error when bulk_update with error {}".format(str(err)))

    for app_id in list_application_ids:
        # skip the existing id that already have credit score data
        if app_id in existing_app_id_in_cs:
            continue

        cs_obj = CreditScore(
            application_id=app_id,
            score=score,
        )
        list_of_cs_obj_to_be_created.append(cs_obj)
        if len(list_of_cs_obj_to_be_created) == limiter:
            CreditScore.objects.bulk_create(list_of_cs_obj_to_be_created)
            print("success create new 100 credit score")
            list_of_cs_obj_to_be_created = []
    try:
        CreditScore.objects.bulk_create(list_of_cs_obj_to_be_created)
        print("---------finish create all new credit score---------")
    except Exception as err:
        print("error when bulk_create with error {}".format(str(err)))

    return "success"


def generate_belum_bisa_melanjukan_aplikasi_info_card():
    from juloserver.streamlined_communication.models import (
        InfoCardProperty,
        StreamlinedCommunication,
        StreamlinedMessage,
        CardProperty
    )
    from juloserver.streamlined_communication.constant import CommunicationPlatform
    from juloserver.julo.models import Image, StatusLookup

    class ImageNames(object):
        DESIGNS_REAL = 'info-card/data_bg.png'


    def create_image(image_source_id, image_type, image_url):
        image = Image()
        image.image_source = image_source_id
        image.image_type = image_type
        image.url = image_url
        image.save()

    data = {
        'status': ApplicationStatusCodes.LOC_APPROVED,
        'additional_condition': CardProperty.GRAB_BELUM_BISA_MELANJUTKAN_APLIKASI,
        'title': 'Kamu Belum Bisa Melanjutkan Aplikasi',
        'content': 'Coba Ajukan Pinjaman Lagi 1x24 jam ya. '
                   'Pastikan kamu sudah melunasi seluruh tagihan yang belum terbayar.',
        'button': [],
        'button_name': [],
        'click_to': [],
        'template_type': '2',
        'card_number': 1,
        'text_colour': '#ffffff',
        'title_colour': '#ffffff',
        'background_url': ImageNames.DESIGNS_REAL,
        'additional_images': [],
        'button_url': [],
    }

    button_2_properties = {
        'card_type': '2',
        'title': data['title'],
        'title_color': data['title_colour'],
        'text_color': data['text_colour'],
        'card_order_number': data['card_number']
    }

    info_card = InfoCardProperty.objects.create(**button_2_properties)
    data_streamlined_message = {
        'message_content': data['content'],
        'info_card_property': info_card
    }
    message = StreamlinedMessage.objects.create(**data_streamlined_message)
    status = StatusLookup.objects.filter(status_code=data['status']).last()
    data_for_streamlined_comms = {
        'status_code': status,
        'status': data['status'],
        'communication_platform': CommunicationPlatform.INFO_CARD,
        'message': message,
        'description': 'retroloaded grab card move auth information',
        'is_active': True,
        'extra_conditions': data['additional_condition']
    }

    StreamlinedCommunication.objects.create(**data_for_streamlined_comms)

    # create image for background
    if data['background_url']:
        create_image(
            info_card.id,
            CardProperty.IMAGE_TYPE.card_background_image,
            data['background_url']
        )


def read_data_backated_data(file_path, chunk_size=100):
    result = {}
    with open(file_path, "r") as f:
        reader = csv.reader(f)
        for counter, line in enumerate(reader):
            if counter == 0:
                continue

            if len(line) < 2:
                continue

            loan_xid = int(line[0])
            restructure_date = line[1]
            if len(result) < chunk_size:
                result[loan_xid] = {"loan_xid": loan_xid, "restructure_date": restructure_date}
            else:
                yield result
                result = {loan_xid: {"loan_xid": loan_xid, "restructure_date": restructure_date}}

    if result:
        yield result


def fill_backdate_data_restructure_history_log(file_path: str, chunk_size=100):
    from juloserver.grab.services.services import GrabRestructureHistoryLogService
    service = GrabRestructureHistoryLogService()

    for loans_data in read_data_backated_data(file_path, chunk_size):
        loans_data = service.fetch_loan_id_by_xid(loans_data)
        n_data, n_inserted = service.create_restructure_history_entry_bulk(
            loans_data.values(),
            is_restructured=True
        )
        not_inserted = [
            loan_data.get('loan_xid') for loan_data in loans_data.values()
            if not loan_data.get('loan_id')
        ]
        for loan_xid in not_inserted:
            print("loan_xid {} not exists".format(loan_xid))

        print("inserted: {}/{}".format(n_inserted, n_data))

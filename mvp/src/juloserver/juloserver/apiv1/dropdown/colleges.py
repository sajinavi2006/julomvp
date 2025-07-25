from __future__ import unicode_literals

from .base import DropDownBase


class CollegeDropDown(DropDownBase):
    dropdown = "colleges"
    version = 1
    file_name = "colleges.json"

    # Please Always Upgrade Version if there is changes on data
    DATA = [
        "Aceh,Politeknik Negeri Lhokseumawe (PNL) - Aceh",
        "Aceh,Universitas Islam Negeri Ar-Raniry (UIN Ar Raniry) - Aceh",
        "Aceh,Universitas Malikussaleh (UNIMAL) - Aceh",
        "Aceh,Universitas Samudera (UNSAM) - Aceh",
        "Aceh,Universitas Syiah Kuala (UNSYIAH) - Aceh",
        "Aceh,Universitas Teuku Umar (UTU) - Aceh",
        "Aceh,Lainnya - Aceh",
        "Bali,Institute Seni Indonesia Denpasar (ISI-DPS) - Bali",
        "Bali,Politeknik Negeri Bali (PNB) - Bali",
        "Bali,Stenden University Bali (SUB) - Bali",
        "Bali,Universitas Pendidikan Ganesha (UNDIKSHA) - Bali",
        "Bali,Universitas Pendidikan Nasional (UNDIKNAS) - Bali",
        "Bali,Universitas Udayana (UNUD) - Bali",
        "Bali,Universitas Warmadewa (UNWAR) - Bali",
        "Bali,Lainnya - Bali",
        "Bangka-Belitung,Politeknik Manufaktur Bangka Belitung (POLMAN-Babel) - Bangka-Belitung",
        (
            "Bangka-Belitung,Sekolah Tinggi Agama Islam Negeri Sungailiat (STAIN Sungailiat) "
            "- Bangka-Belitung"
        ),
        (
            "Bangka-Belitung,Sekolah Tinggi Agama Islam Negeri Syaikh Abdurrahman Siddik "
            "(STAIN SAS Babel) - Bangka-Belitung"
        ),
        "Bangka-Belitung,Universitas Bangka Belitung (UBB) - Bangka-Belitung",
        "Bangka-Belitung,Lainnya - Bangka-Belitung",
        "Banten,Institut Teknologi Indonesia (ITI) - Banten",
        "Banten,Perguruan Tinggi Raharja Tangerang (RAHARJA) - Banten",
        "Banten,Sekolah Bisnis Prasetiya Mulya (PMBS-Prasmul-PMSBE) - Banten",
        "Banten,Swiss German University (SGU) - Banten",
        "Banten,Universitas Islam Syekh Yusuf Tangerang (UNIS) - Banten",
        "Banten,Universitas Media Nusantara (UNIMEDIA) - Banten",
        "Banten,Universitas Pamulang (UNPAM) - Banten",
        "Banten,Universitas Pelita Harapan (UPH) - Banten",
        "Banten,Universitas Sultan Ageng Tirtayasa (UNTIRTA) - Banten",
        "Banten,Universitas Surya (SU) - Banten",
        "Banten,Universitas Terbuka (UT) - Banten",
        "Banten,Lainnya - Banten",
        "Bengkulu,Institut Agama Islam Negeri Bengkulu (IAIN Bengkulu) - Bengkulu",
        "Bengkulu,Universitas Bengkulu (UNIB) - Bengkulu",
        "Bengkulu,Universitas Muhammadiyah Bengkulu (UMB) - Bengkulu",
        "Bengkulu,Lainnya - Bengkulu",
        "Gorontalo,Universitas Negeri Gorontalo (UNG) - Gorontalo",
        "Gorontalo,Lainnya - Gorontalo",
        "Jakarta,Akademi Telkom Jakarta - Jakarta",
        "Jakarta,Institut Bisnis Nusantara (IBN) - Jakarta",
        "Jakarta,Institut Kesenian Jakarta (IKJ) - Jakarta",
        "Jakarta,Pendidikan dan Pembinaan Manajemen (PPM) - Jakarta",
        "Jakarta,Politeknik Negeri Jakarta (PNJ) - Jakarta",
        "Jakarta,Politeknik Negeri Media Kreatif (POLIMEDIA) - Jakarta",
        "Jakarta,Raffles Institute of Higher Education (Raffles@Citywalk) - Jakarta",
        "Jakarta,Sekolah Tinggi Manajemen Informatika dan Komputer Jakarta (STMIK) - Jakarta",
        "Jakarta,STIE Perbanas (ABFI-PERBANAS) - Jakarta",
        "Jakarta,Universitas Al-Azhar Indonesia (UAI) - Jakarta",
        "Jakarta,Universitas Bakrie (UB) - Jakarta",
        "Jakarta,Universitas Bina Nusantara (Binus University) - Jakarta",
        "Jakarta,Universitas Borobudur - Jakarta",
        "Jakarta,Universitas Budi Luhur (UBL) - Jakarta",
        "Jakarta,Universitas Bunda Mulia (UBM) - Jakarta",
        "Jakarta,Universitas Darma Persada (UNSADA) - Jakarta",
        "Jakarta,Universitas Esa Unggul (UEU) - Jakarta",
        "Jakarta,Universitas Indonesia (UI) - Jakarta",
        "Jakarta,Universitas Indraprasta PGRI (UNINDRA) - Jakarta",
        (
            "Jakarta,Universitas Islam Negeri Syarif Hidayatullah Jakarta "
            "(UIN Syarif Hidayatullah) - Jakarta"
        ),
        "Jakarta,Universitas Katolik Atma Jaya (STMIK Jakarta STI&K) - Jakarta",
        "Jakarta,Universitas Kristen Indonesia (UKI) - Jakarta",
        "Jakarta,Universitas Kristen Krida Wacana (UKRIDA) - Jakarta",
        "Jakarta,Universitas Mercubuana (UMB) - Jakarta",
        "Jakarta,Universitas Muhammadiyah Jakarta (UMJ) - Jakarta",
        "Jakarta,Universitas Muhammadiyah Prof. Dr. HAMKA (UHAMKA) - Jakarta",
        "Jakarta,Universitas Nasional (UNAS) - Jakarta",
        "Jakarta,Universitas Negeri Jakarta (UNJ) - Jakarta",
        "Jakarta,Universitas Pancasila (UP) - Jakarta",
        "Jakarta,Universitas Paramadina (UPM/PARMAD) - Jakarta",
        "Jakarta,Universitas Pembangunan Nasional Veteran (UPN Veteran) - Jakarta",
        (
            "Jakarta,Universitas Persada Indonesia Yayasan Administrasi Indonesia (UPI Y.A.I) "
            "- Jakarta"
        ),
        "Jakarta,Universitas Prof. Moestopo (Beragama) - Jakarta",
        "Jakarta,Universitas Respati Indonesia (URINDO) - Jakarta",
        "Jakarta,Universitas Sahid (USAHID) - Jakarta",
        "Jakarta,Universitas Tarumanagara (UNTAR) - Jakarta",
        "Jakarta,Universitas Trisakti (USAKTI) - Jakarta",
        "Jakarta,Universitas Yayasan Rumah Sakit Islam Indonesia (YARSI) (YARSI) - Jakarta",
        "Jakarta,Lainnya - Jakarta",
        "Jambi,Sekolah Tinggi Agama Islam Negeri Jambi (STAIN Jambi) - Jambi",
        "Jambi,Universitas Jambi (UNJA) - Jambi",
        "Jambi,Lainnya - Jambi",
        "Jawa Barat,Institut Pertanian Bogor (IPB) - Jawa Barat",
        "Jawa Barat,Institut Teknologi Bandung (ITB) - Jawa Barat",
        "Jawa Barat,Institut Teknologi Harapan Bangsa (ITHB) - Jawa Barat",
        "Jawa Barat,Institut Teknologi Nasional (ITENAS) - Jawa Barat",
        "Jawa Barat,Politeknik Manufaktur Bandung (POLMAN-Bandung) - Jawa Barat",
        "Jawa Barat,Politeknik Negeri Bandung (POLBAN) - Jawa Barat",
        "Jawa Barat,Sekolah Tinggi Pariwisata Bandung (STPB) - Jawa Barat",
        "Jawa Barat,Sekolah Tinggi Seni Indonesia Bandung (STSI-BDG) - Jawa Barat",
        "Jawa Barat,Sekolah Tinggi Teknologi Garut (STTG) - Jawa Barat",
        "Jawa Barat,Telkom University (Tel-U) - Jawa Barat",
        "Jawa Barat,Universitas Djuanda (UNIDA) - Jawa Barat",
        "Jawa Barat,Universitas Gunadarma (GUNDAR) - Jawa Barat",
        "Jawa Barat,Universitas Islam 45 Bekasi (UNISMA) - Jawa Barat",
        "Jawa Barat,Universitas Islam Bandung (UNISBA) - Jawa Barat",
        "Jawa Barat,Universitas Islam Negeri Sunan Gunung Djati (UIN-SGD) - Jawa Barat",
        "Jawa Barat,Universitas Islam Nusantara (UNINUS) - Jawa Barat",
        "Jawa Barat,Universitas Jayabaya (UJ) - Jawa Barat",
        "Jawa Barat,Universitas Jenderal Achmad Yani (UNJANI) - Jawa Barat",
        "Jawa Barat,Universitas Katolik Parahyangan (UNPAR) - Jawa Barat",
        "Jawa Barat,Universitas Komputer Indonesia (UNIKOM) - Jawa Barat",
        "Jawa Barat,Universitas Kristen Maranatha (UKM) - Jawa Barat",
        "Jawa Barat,Universitas Kuningan (UNIKU) - Jawa Barat",
        "Jawa Barat,Universitas Langlangbuana (UNLA) - Jawa Barat",
        "Jawa Barat,Universitas Padjajaran (UNPAD) - Jawa Barat",
        "Jawa Barat,Universitas Pakuan (UNPAK) - Jawa Barat",
        "Jawa Barat,Universitas Pasundan (UNPAS) - Jawa Barat",
        "Jawa Barat,Universitas Pendidikan Indonesia (UPI) - Jawa Barat",
        "Jawa Barat,Universitas Presiden (PresUniv) - Jawa Barat",
        "Jawa Barat,Universitas Siliwangi (UNSIL) - Jawa Barat",
        "Jawa Barat,Universitas Singaperbangsa (UNSIKA) - Jawa Barat",
        "Jawa Barat,Universitas Widyatama (Widyatama) - Jawa Barat",
        "Jawa Barat,Lainnya - Jawa Barat",
        "Jawa Tengah,Institut Agama Islam Negeri Salatiga (IAIN-Salatiga) - Jawa Tengah",
        "Jawa Tengah,Institut Seni Indonesia Surakarta (ISI-SKA) - Jawa Tengah",
        "Jawa Tengah,Politeknik Negeri Semarang (POLINES) - Jawa Tengah",
        "Jawa Tengah,Sekolah Tinggi Agama Islam Negeri Kudus (STAIN-Kudus) - Jawa Tengah",
        "Jawa Tengah,Sekolah Tinggi Agama Islam Negeri Purwokerto (STAIN-Purwokerto) - Jawa Tengah",
        "Jawa Tengah,Universitas Dian Nuswantoro (UDINUS) - Jawa Tengah",
        "Jawa Tengah,Universitas Diponegoro (UNDIP) - Jawa Tengah",
        "Jawa Tengah,Universitas Islam Negeri Walisongo (UIN) - Jawa Tengah",
        "Jawa Tengah,Universitas Jenderal Soedirman (UNSOED) - Jawa Tengah",
        "Jawa Tengah,Universitas Katolik Soegijapranata - Jawa Tengah",
        "Jawa Tengah,Universitas Kristen Satya Wacana (UKSW) - Jawa Tengah",
        "Jawa Tengah,Universitas Muhammadiyah Magelang (UMMGL) - Jawa Tengah",
        "Jawa Tengah,Universitas Muhammadiyah Purwoketo (UMP) - Jawa Tengah",
        "Jawa Tengah,Universitas Muhammadiyah Purworejo (UMP) - Jawa Tengah",
        "Jawa Tengah,Universitas Muhammadiyah Semarang (UNIMUS) - Jawa Tengah",
        "Jawa Tengah,Universitas Muhammadiyah Surakarta (UMS) - Jawa Tengah",
        "Jawa Tengah,Universitas Muria Kudus (UMK) - Jawa Tengah",
        "Jawa Tengah,Universitas Negeri Semarang (UNNES) - Jawa Tengah",
        "Jawa Tengah,Universitas Sebelas Maret (UNS) - Jawa Tengah",
        "Jawa Tengah,Lainnya - Jawa Tengah",
        "Jawa Timur,Institut Ilmu Kesehatan (IIK) - Jawa Timur",
        "Jawa Timur,Institut Teknologi Sepuluh Nopember (ITS) - Jawa Timur",
        "Jawa Timur,Politeknik Elektronika Negeri Surabaya (PENS) - Jawa Timur",
        "Jawa Timur,Politeknik Negeri Banyuwangi (POLIWANGI) - Jawa Timur",
        "Jawa Timur,Politeknik Negeri Jember (POLIJE) - Jawa Timur",
        "Jawa Timur,Politeknik Negeri Madiun (PNM) - Jawa Timur",
        "Jawa Timur,Politeknik Negeri Madura (POLTERA) - Jawa Timur",
        "Jawa Timur,Politeknik Negeri Malang (POLINEMA) - Jawa Timur",
        "Jawa Timur,Politeknik Perkapalan Negeri Surabaya (PPNS) - Jawa Timur",
        "Jawa Timur,Sekolah Tinggi Ilmu ekonomi Kertanegara Malang (STIEKMA) - Jawa Timur",
        "Jawa Timur,Universitas Airlangga (UNAIR) - Jawa Timur",
        "Jawa Timur,Universitas Brawijaya (UB) - Jawa Timur",
        "Jawa Timur,Universitas Ciputra (UC) - Jawa Timur",
        (
            "Jawa Timur,Universitas Islam Negeri Maulana Malik Ibrahim Malang (UIN-Malang) "
            "- Jawa Timur"
        ),
        "Jawa Timur,Universitas Islam Negeri Sunan Ampel (UIN Sunan Ampel) - Jawa Timur",
        "Jawa Timur,Universitas Jember (UNEJ) - Jawa Timur",
        "Jawa Timur,Universitas Katolik Widya Mandala Surabaya (UKWMS) - Jawa Timur",
        "Jawa Timur,Universitas Kristen Petra (UKP) - Jawa Timur",
        "Jawa Timur,Universitas Muhammadiyah Gresik (UMG) - Jawa Timur",
        "Jawa Timur,Universitas Muhammadiyah Jember (Unmuh Jember) - Jawa Timur",
        "Jawa Timur,Universitas Muhammadiyah Malang (UMM) - Jawa Timur",
        "Jawa Timur,Universitas Muhammadiyah Sidoarjo (UMSIDA) - Jawa Timur",
        "Jawa Timur,Universitas Muhammadiyah Surabaya (Unmuh Surabaya) - Jawa Timur",
        "Jawa Timur,Universitas Negeri Malang (UM) - Jawa Timur",
        "Jawa Timur,Universitas Negeri Surabaya (UNESA) - Jawa Timur",
        (
            "Jawa Timur,Universitas Pembangunan Nasional Veteran Jawa Timur (UPN Veteran Jatim) "
            "- Jawa Timur"
        ),
        (
            "Jawa Timur,Universitas Pembangunan Nasional 'Veteran' Jawa Timur (UPNVJT / UPN Jatim) "
            "- Jawa Timur"
        ),
        "Jawa Timur,Universitas Surabaya (UBAYA) - Jawa Timur",
        "Jawa Timur,Universitas Trunojoyo (UTM) - Jawa Timur",
        "Jawa Timur,Widya Mandala Catholic University (UKWMS) - Jawa Timur",
        "Jawa Timur,Lainnya - Jawa Timur",
        "Kalimantan Barat,Politeknik Negeri Pontianak (POLNEP) - Kalimantan Barat",
        "Kalimantan Barat,Universitas Tanjungpura (UNTAN) - Kalimantan Barat",
        "Kalimantan Barat,Lainnya - Kalimantan Barat",
        "Kalimantan Selatan,Politeknik Negeri Banjarmasin (POLIBAN) - Kalimantan Selatan",
        "Kalimantan Selatan,Politeknik Negeri Tanah Laut (POLITALA) - Kalimantan Selatan",
        "Kalimantan Selatan,Universitas Lambung Mangkurat (UNLAM) - Kalimantan Selatan",
        "Kalimantan Selatan,Lainnya - Kalimantan Selatan",
        "Kalimantan Tengah,Universitas Palangkaraya (UPR) - Kalimantan Tengah",
        "Kalimantan Tengah,Lainnya - Kalimantan Tengah",
        "Kalimantan Timur,Institut Teknologi Kalimantan (ITK) - Kalimantan Timur",
        "Kalimantan Timur,Politeknik Negeri Balikpapan (POLTEKBA) - Kalimantan Timur",
        "Kalimantan Timur,Politeknik Negeri Samarinda (POLNES) - Kalimantan Timur",
        "Kalimantan Timur,Politeknik Pertanian Negeri Samarinda (POLTANESA) - Kalimantan Timur",
        "Kalimantan Timur,Universitas Mulawarman (UNMUL) - Kalimantan Timur",
        "Kalimantan Timur,Lainnya - Kalimantan Timur",
        "Kalimantan Utara,Universitas Borneo Tarakan - Kalimantan Utara",
        "Kalimantan Utara,Lainnya - Kalimantan Utara",
        "Kepulauan Riau,Politeknik Negeri Batam (Polibatam) - Kepulauan Riau",
        (
            "Kepulauan Riau,Sekolah Tinggi Agama Islam Negeri Tanjung Pinang "
            "(STAIN Tanjung Pinang) - Kepulauan Riau"
        ),
        "Kepulauan Riau,Universitas Maritim Raja Ali Haji (UMRAH) - Kepulauan Riau",
        "Kepulauan Riau,Lainnya - Kepulauan Riau",
        "Lampung,Institut Teknologi Sumatera (ITERA) - Lampung",
        "Lampung,Politeknik Negeri Lampung (POLINELA) - Lampung",
        "Lampung,Sekolah Tinggi Agama Islam Negeri Bandar Lampung (STAIN Bandar Lampung) - Lampung",
        "Lampung,Sekolah Tinggi Agama Islam Negeri Lampung (STAIN Lampung) - Lampung",
        "Lampung,Universitas Lampung (UNILA) - Lampung",
        "Lampung,Universitas Muhammadiyah Metro (UM Metro) - Lampung",
        "Lampung,Lainnya - Lampung",
        "Maluku Utara,Universitas Khairun (UNKHAIR) - Maluku Utara",
        "Maluku Utara,Lainnya - Maluku Utara",
        "Maluku,Politeknik Negeri Ambon (POLNAM) - Maluku",
        "Maluku,Politeknik Perikanan Negeri Tual - Maluku",
        "Maluku,Universitas Pattimura (UNPATTI) - Maluku",
        "Maluku,Lainnya - Maluku",
        "Nusa Tenggara Barat,Universitas Mataram (UNRAM) - Nusa Tenggara Barat",
        "Nusa Tenggara Barat,Lainnya - Nusa Tenggara Barat",
        "Nusa Tenggara Timur,Politeknik Negeri Kupang - Nusa Tenggara Timur",
        "Nusa Tenggara Timur,Politeknik Pertanian Negeri Kupang (PERTI) - Nusa Tenggara Timur",
        "Nusa Tenggara Timur,Universitas Kristen Artha Wacana (UKAW) - Nusa Tenggara Timur",
        "Nusa Tenggara Timur,Universitas Nusa Cendana (UNDANA) - Nusa Tenggara Timur",
        "Nusa Tenggara Timur,Universitas Timor (UNIMOR) - Nusa Tenggara Timur",
        "Nusa Tenggara Timur,Lainnya - Nusa Tenggara Timur",
        "Papua Barat,STKIP Muhammadiyah Sorong (STKIP Muh Sorong) - Papua Barat",
        "Papua Barat,Universitas Negeri Papua (UNIPA) - Papua Barat",
        "Papua Barat,Lainnya - Papua Barat",
        "Papua,Universitas Cenderawasih (UNCEN) - Papua",
        "Papua,Universitas Musamus Merauke (UNMUS) - Papua",
        "Papua,Lainnya - Papua",
        "Riau,Universitas Islam Negeri Sultan Syarif Kasim II (UIN Suska II) - Riau",
        "Riau,Universitas Riau (UNRI) - Riau",
        "Riau,Lainnya - Riau",
        "Sulawesi Selatan,Politeknik Negeri Ujung Pandang (POLIUPG/PNUP) - Sulawesi Selatan",
        "Sulawesi Selatan,Politeknik Pertanian Negeri Pangkep (POLTEKPANGKEP) - Sulawesi Selatan",
        (
            "Sulawesi Selatan,Sekolah Tinggi Ilmu Manajemen Lembaga Pendidikan Indonesia "
            "(STIM LPI) - Sulawesi Selatan"
        ),
        "Sulawesi Selatan,Universitas Hasanudin (UNHAS) - Sulawesi Selatan",
        "Sulawesi Selatan,Universitas Indonesia Timur (UIT) - Sulawesi Selatan",
        "Sulawesi Selatan,Universitas Islam Negeri Alauddin (UIN Alauddin) - Sulawesi Selatan",
        "Sulawesi Selatan,Universitas Muhammadiyah Makassar (UMM) - Sulawesi Selatan",
        "Sulawesi Selatan,Universitas Muslim Indonesia Makassar (UMI) - Sulawesi Selatan",
        "Sulawesi Selatan,Universitas Negeri Makassar (UNM) - Sulawesi Selatan",
        "Sulawesi Selatan,Universitas Veteran Republik Indonesia (UVRI) - Sulawesi Selatan",
        "Sulawesi Selatan,Lainnya - Sulawesi Selatan",
        "Sulawesi Tengah,Universitas Tadulako (UNTAD) - Sulawesi Tengah",
        "Sulawesi Tengah,Lainnya - Sulawesi Tengah",
        "Sulawesi Tenggara,Universitas Haluoleo (UHO) - Sulawesi Tenggara",
        "Sulawesi Tenggara,Lainnya - Sulawesi Tenggara",
        "Sulawesi Utara,Politeknik Negeri Manado (POLIMDO) - Sulawesi Utara",
        "Sulawesi Utara,Universitas Katolik De La Salle Manado - Sulawesi Utara",
        "Sulawesi Utara,Universitas Negeri Manado (UNIMA) - Sulawesi Utara",
        "Sulawesi Utara,Universitas Sam Ratulangi (UNSRAT) - Sulawesi Utara",
        "Sulawesi Utara,Lainnya - Sulawesi Utara",
        "Sumatra Barat,Institut Agama Islam Negeri Imam Bonjol (IAIN Imam Bonjol) - Sumatra Barat",
        "Sumatra Barat,Institut Seni Indonesia Padang Panjang (ISI) - Sumatra Barat",
        "Sumatra Barat,Politeknik Negeri Padang (POLINPDG) - Sumatra Barat",
        "Sumatra Barat,Politeknik Pertanian Negeri Payakumbuh (POLIPYK) - Sumatra Barat",
        (
            "Sumatra Barat,Sekolah Tinggi Agama Islam Negeri Padang Panjang (STAIN Padang Panjang) "
            "- Sumatra Barat"
        ),
        (
            "Sumatra Barat,Sekolah Tinggi Agama Islam Negeri Payakumbuh (STAIN Payakumbuh) "
            "- Sumatra Barat"
        ),
        "Sumatra Barat,Universitas Andalas (UNAND) - Sumatra Barat",
        "Sumatra Barat,Universitas Negeri Padang (UNP) - Sumatra Barat",
        "Sumatra Barat,Lainnya - Sumatra Barat",
        "Sumatra Selatan,Politeknik Negeri Sriwijaya (POLSRIWIJAYA) - Sumatra Selatan",
        (
            "Sumatra Selatan,Sekolah Tinggi Agama Islam Negeri Palembang (STAIN Palembang) "
            "- Sumatra Selatan"
        ),
        "Sumatra Selatan,Universitas Bina Darma (UBD) - Sumatra Selatan",
        "Sumatra Selatan,Universitas Muhammadiyah Palembang (UMP) - Sumatra Selatan",
        "Sumatra Selatan,Universitas Sriwijaya (UNSRI) - Sumatra Selatan",
        "Sumatra Selatan,Lainnya - Sumatra Selatan",
        "Sumatra Utara,Politeknik Negeri Medan (POLMED) - Sumatra Utara",
        "Sumatra Utara,Universitas HKBP Nommensen - Sumatra Utara",
        "Sumatra Utara,Universitas Islam Negeri Sumatera Utara (UINSU) - Sumatra Utara",
        "Sumatra Utara,Universitas Islam Sumatera Utara (UISU) - Sumatra Utara",
        "Sumatra Utara,Universitas Methodist Indonesia (UMI) - Sumatra Utara",
        "Sumatra Utara,Universitas Negeri Medan (UNIMED) - Sumatra Utara",
        "Sumatra Utara,Universitas Sumatera Utara (USU) - Sumatra Utara",
        "Sumatra Utara,Lainnya - Sumatra Utara",
        "Yogyakarta,Institut Sains dan Teknologi AKPRIND (IST AKPRIND) - Yogyakarta",
        "Yogyakarta,Institut Seni Indonesia (ISI) - Yogyakarta",
        "Yogyakarta,STMIK AMIKOM Yogyakarta (AMIKOM) - Yogyakarta",
        "Yogyakarta,Universitas Ahmad Dahlan (UAD) - Yogyakarta",
        "Yogyakarta,Universitas Atmajaya Yogyakarta - Yogyakarta",
        "Yogyakarta,Universitas Gadjah Mada (UGM) - Yogyakarta",
        "Yogyakarta,Universitas Islam Indonesia (UII) - Yogyakarta",
        (
            "Yogyakarta,Universitas Islam Negeri Sunan Kalijaga Yogyakarta (UIN Sunan Kalijaga) "
            "- Yogyakarta"
        ),
        "Yogyakarta,Universitas Kristen Duta Wacana (UKDW) - Yogyakarta",
        "Yogyakarta,Universitas Mercubuana Yogyakarta (UMY) - Yogyakarta",
        "Yogyakarta,Universitas Muhammadiyah Yogyakarta (UMY) - Yogyakarta",
        "Yogyakarta,Universitas Negeri Yogyakarta (UNY) - Yogyakarta",
        (
            "Yogyakarta,Universitas Pembangunan Nasional Veteran Yogyakarta "
            "(UPN Veteran Yogyakarta) - Yogyakarta"
        ),
        "Yogyakarta,Universitas Sanata Dharma (USD) - Yogyakarta",
    ]

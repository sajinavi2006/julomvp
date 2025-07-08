from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes

credit_score_rules = {
    # Partner None which means Julo
    None: {
        'checks': {
            'application_date_of_birth': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena '
                'belum memenuhi kriteria umur yang di tentukan.',
            },
            'job_not_black_listed': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'form_partial_location': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Produk pinjaman lain belum tersedia di daerah Anda.',
            },
            'form_partial_income': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria pinjaman yang ada. Silakan coba kembali 6 bulan mendatang.',
            },
            'saving_margin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria pinjaman yang ada. Silakan coba kembali 6 bulan mendatang.',
            },
            'fraud_form_partial_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan HP yang '
                'sudah terdaftar. Silahkan login kembali menggunakan HP pribadi Anda.',
            },
            'fraud_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan HP yang '
                'sudah terdaftar. Silahkan login kembali menggunakan HP pribadi Anda.',
            },
            'fraud_form_partial_hp_own': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan nomor '
                'HP yang sudah terdaftar. Silahkan coba kembali menggunakan nomor HP pribadi '
                'Anda atau login menggunakan akun yang sudah terdaftar.',
            },
            'fraud_form_partial_hp_kin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'fraud_hp_spouse': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'email_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'sms_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
        },
        'scores': [
            {
                'probability_min': 0.9,
                'probability_max': 1.0,
                'score': 'A-',
                'product_lines': [ProductLineCodes.MTL1, ProductLineCodes.STL1],
                'message': 'Poin kredit Anda sangat bagus. Peluang pengajuan Anda di-ACC besar! '
                'Silakan pilih salah satu produk pinjaman di bawah ini & selesaikan '
                'pengajuannya. Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.75,
                'probability_max': 0.9,
                'score': 'B+',
                'product_lines': [ProductLineCodes.MTL1, ProductLineCodes.STL1],
                'message': 'Poin kredit Anda bagus. Peluang pengajuan Anda di-ACC cukup besar! '
                'Silakan pilih salah satu produk pinjaman di bawah ini & selesaikan '
                'pengajuannya. Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.65,
                'probability_max': 0.75,
                'score': 'B-',
                'product_lines': [ProductLineCodes.STL1],
                'message': 'Peluang pengajuan Anda di-ACC cukup besar! Silakan pilih salah '
                'satu produk pinjaman di bawah ini & selesaikan pengajuannya. '
                'Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.0,
                'probability_max': 0.65,
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
        ],
        'bypass_checks': [],
    },
    PartnerConstant.TOKOPEDIA_PARTNER: {
        'checks': {
            'application_date_of_birth': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria umur yang di tentukan.',
            },
            'job_not_black_listed': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'form_partial_location': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Produk pinjaman lain belum tersedia di daerah Anda.',
            },
            'form_partial_income': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria pinjaman yang ada. Silakan coba kembali 6 bulan mendatang.',
            },
            'saving_margin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria pinjaman yang ada. Silakan coba kembali 6 bulan mendatang.',
            },
            'fraud_form_partial_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan HP '
                'yang sudah terdaftar. Silahkan login kembali menggunakan HP pribadi Anda.',
            },
            'fraud_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan HP '
                'yang sudah terdaftar. Silahkan login kembali menggunakan HP pribadi Anda.',
            },
            'fraud_form_partial_hp_own': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan nomor '
                'HP yang sudah terdaftar. Silahkan coba kembali menggunakan '
                'nomor HP pribadi Anda atau login menggunakan akun yang sudah terdaftar.',
            },
            'fraud_form_partial_hp_kin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'fraud_hp_spouse': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'email_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'sms_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
        },
        'scores': [
            {
                'probability_min': 0.9,
                'probability_max': 1.0,
                'score': 'A-',
                'product_lines': [ProductLineCodes.MTL1, ProductLineCodes.STL1],
                'message': 'Poin kredit Anda sangat bagus. Peluang pengajuan Anda di-ACC besar! '
                'Silakan pilih salah satu produk pinjaman di bawah ini & selesaikan pengajuannya. '
                'Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.75,
                'probability_max': 0.9,
                'score': 'B+',
                'product_lines': [ProductLineCodes.MTL1, ProductLineCodes.STL1],
                'message': 'Poin kredit Anda bagus. Peluang pengajuan Anda di-ACC cukup besar! '
                'Silakan pilih salah satu produk pinjaman di bawah ini & selesaikan '
                'pengajuannya. Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.65,
                'probability_max': 0.75,
                'score': 'B-',
                'product_lines': [ProductLineCodes.STL1],
                'message': 'Peluang pengajuan Anda di-ACC cukup besar! Silakan pilih salah '
                'satu produk pinjaman di bawah ini & selesaikan pengajuannya. '
                'Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.0,
                'probability_max': 0.65,
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
        ],
        'bypass_checks': [],
    },
    PartnerConstant.DOKU_PARTNER: {
        'checks': {
            'application_date_of_birth': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria umur yang di tentukan.',
            },
            'job_not_black_listed': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'form_partial_location': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Produk pinjaman lain belum tersedia di daerah Anda.',
            },
            'form_partial_income': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena '
                'belum memenuhi kriteria pinjaman yang ada. Silakan coba kembali '
                '6 bulan mendatang.',
            },
            'saving_margin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena '
                'belum memenuhi kriteria pinjaman yang ada. Silakan coba kembali '
                '6 bulan mendatang.',
            },
            'fraud_form_partial_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan HP '
                'yang sudah terdaftar. Silahkan login kembali menggunakan HP '
                'pribadi Anda.',
            },
            'fraud_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan HP '
                'yang sudah terdaftar. Silahkan login kembali menggunakan HP '
                'pribadi Anda.',
            },
            'fraud_form_partial_hp_own': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan nomor '
                'HP yang sudah terdaftar. Silahkan coba kembali menggunakan nomor '
                'HP pribadi Anda atau login menggunakan akun yang sudah terdaftar.',
            },
            'fraud_form_partial_hp_kin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'fraud_hp_spouse': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'email_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'sms_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
        },
        'scores': [
            {
                'probability_min': 0.9,
                'probability_max': 1.0,
                'score': 'A-',
                'product_lines': [ProductLineCodes.MTL1, ProductLineCodes.STL1],
                'message': 'Poin kredit Anda sangat bagus. Peluang pengajuan Anda di-ACC besar! '
                'Silakan pilih salah satu produk pinjaman di bawah ini & selesaikan '
                'pengajuannya. Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.75,
                'probability_max': 0.9,
                'score': 'B+',
                'product_lines': [ProductLineCodes.MTL1, ProductLineCodes.STL1],
                'message': 'Poin kredit Anda bagus. Peluang pengajuan Anda di-ACC cukup besar! '
                'Silakan pilih salah satu produk pinjaman di bawah ini & selesaikan '
                'pengajuannya. Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.65,
                'probability_max': 0.75,
                'score': 'B-',
                'product_lines': [ProductLineCodes.STL1],
                'message': 'Peluang pengajuan Anda di-ACC cukup besar! Silakan pilih salah '
                'satu produk pinjaman di bawah ini & selesaikan pengajuannya. '
                'Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.0,
                'probability_max': 0.65,
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
        ],
        'bypass_checks': [],
    },
    PartnerConstant.GRAB_PARTNER: {
        'checks': {
            'application_date_of_birth': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria umur yang di tentukan.',
            },
            'job_not_black_listed': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'form_partial_location': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Produk pinjaman lain belum tersedia di daerah Anda.',
            },
            'form_partial_income': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena '
                'belum memenuhi kriteria pinjaman yang ada. Silahkan coba kembali '
                '6 bulan mendatang.',
            },
            'saving_margin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena '
                'belum memenuhi kriteria pinjaman yang ada. Silahkan coba kembali '
                '6 bulan mendatang.',
            },
            'fraud_form_partial_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan '
                'HP yang sudah terdaftar. Silahkan login kembali menggunakan '
                'HP pribadi Anda.',
            },
            'fraud_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan '
                'HP yang sudah terdaftar. Silahkan login kembali menggunakan HP '
                'pribadi Anda.',
            },
            'fraud_form_partial_hp_own': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan nomor '
                'HP yang sudah terdaftar. Silahkan coba kembali menggunakan nomor '
                'HP pribadi Anda atau login menggunakan akun yang sudah terdaftar.',
            },
            'fraud_form_partial_hp_kin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan nomor '
                'HP yang sudah terdaftar. Silahkan coba kembali menggunakan nomor '
                'HP pribadi Anda atau login menggunakan akun yang sudah terdaftar.',
            },
            'fraud_hp_spouse': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan nomor '
                'HP yang sudah terdaftar. Silahkan coba kembali menggunakan nomor '
                'HP pribadi Anda atau login menggunakan akun yang sudah terdaftar.',
            },
            'email_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'sms_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
        },
        'scores': [
            {
                'probability_min': 0.9,
                'probability_max': 1.0,
                'score': 'A-',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': 'Pilih produk pinjaman Grab di bawah ini & selesaikan pengajuannya. '
                'Pasti CAIR!',
            },
            {
                'probability_min': 0.75,
                'probability_max': 0.9,
                'score': 'B+',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': 'Pilih produk pinjaman Grab di bawah ini & selesaikan pengajuannya. '
                'Pasti CAIR!',
            },
            {
                'probability_min': 0.65,
                'probability_max': 0.75,
                'score': 'B-',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': 'Pilih produk pinjaman Grab di bawah ini & selesaikan pengajuannya. '
                'Pasti CAIR!',
            },
            {
                'probability_min': 0.0,
                'probability_max': 0.65,
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': 'Pilih produk pinjaman Grab di bawah ini & selesaikan pengajuannya. '
                'Pasti CAIR!',
            },
        ],
        'bypass_checks': ['application_date_of_birth', 'form_partial_location'],
    },
    PartnerConstant.GRAB_FOOD_PARTNER: {
        'checks': {
            'application_date_of_birth': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria umur yang di tentukan.',
            },
            'job_not_black_listed': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'form_partial_location': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Produk pinjaman lain belum tersedia di daerah Anda.',
            },
            'form_partial_income': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRABF1],
                'message': 'Pilih produk pinjaman Grab & selesaikan pengajuan!',
            },
            'saving_margin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRABF1],
                'message': 'Pilih produk pinjaman Grab & selesaikan pengajuan!',
            },
            'fraud_form_partial_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRABF1],
                'message': 'Pilih produk pinjaman Grab & selesaikan pengajuan!',
            },
            'fraud_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRABF1],
                'message': 'Pilih produk pinjaman Grab & selesaikan pengajuan!',
            },
            'fraud_form_partial_hp_own': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRABF1],
                'message': 'Pilih produk pinjaman Grab & selesaikan pengajuan!',
            },
            'fraud_form_partial_hp_kin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRABF1],
                'message': 'Pilih produk pinjaman Grab & selesaikan pengajuan!',
            },
            'fraud_hp_spouse': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRABF1],
                'message': 'Pilih produk pinjaman Grab & selesaikan pengajuan!',
            },
            'email_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRABF1],
                'message': 'Pilih produk pinjaman Grab & selesaikan pengajuan!',
            },
            'sms_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRABF1],
                'message': 'Pilih produk pinjaman Grab & selesaikan pengajuan!',
            },
        },
        'scores': [
            {
                'probability_min': 0.9,
                'probability_max': 1.0,
                'score': 'A-',
                'product_lines': [ProductLineCodes.GRABF1],
                'message': 'Pilih produk pinjaman Grab & selesaikan pengajuan. Pasti CAIR!',
            },
            {
                'probability_min': 0.75,
                'probability_max': 0.9,
                'score': 'B+',
                'product_lines': [ProductLineCodes.GRABF1],
                'message': 'Pilih produk pinjaman Grab & selesaikan pengajuan. Pasti CAIR!',
            },
            {
                'probability_min': 0.65,
                'probability_max': 0.75,
                'score': 'B-',
                'product_lines': [ProductLineCodes.GRABF1],
                'message': 'Pilih produk pinjaman Grab & selesaikan pengajuan. Pasti CAIR!',
            },
            {
                'probability_min': 0.0,
                'probability_max': 0.65,
                'score': 'C',
                'product_lines': [ProductLineCodes.GRABF1],
                'message': 'Pilih produk pinjaman Grab & selesaikan pengajuan. Pasti CAIR!',
            },
        ],
        'bypass_checks': [
            'application_date_of_birth',
            'form_partial_location',
            'job_not_black_listed',
        ],
    },
    PartnerConstant.BRI_PARTNER: {
        'checks': {
            'application_date_of_birth': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria umur yang di tentukan.',
            },
            'job_not_black_listed': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'form_partial_location': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Produk pinjaman lain belum tersedia di daerah Anda.',
            },
            'form_partial_income': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria pinjaman yang ada. Silakan coba kembali 6 bulan mendatang.',
            },
            'saving_margin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria pinjaman yang ada. Silakan coba kembali 6 bulan mendatang.',
            },
            'fraud_form_partial_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan HP yang '
                'sudah terdaftar. Silahkan login kembali menggunakan HP pribadi Anda.',
            },
            'fraud_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan HP yang '
                'sudah terdaftar. Silahkan login kembali menggunakan HP pribadi Anda.',
            },
            'fraud_form_partial_hp_own': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan nomor HP '
                'yang sudah terdaftar. Silahkan coba kembali menggunakan nomor HP pribadi Anda '
                'atau login menggunakan akun yang sudah terdaftar.',
            },
            'fraud_form_partial_hp_kin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'fraud_hp_spouse': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'email_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'sms_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
        },
        'scores': [
            {
                'probability_min': 0.9,
                'probability_max': 1.0,
                'score': 'A-',
                'product_lines': [ProductLineCodes.MTL1, ProductLineCodes.STL1],
                'message': 'Poin kredit Anda sangat bagus. Peluang pengajuan Anda di-ACC besar! '
                'Silakan pilih salah satu produk pinjaman di bawah ini & selesaikan pengajuannya. '
                'Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.75,
                'probability_max': 0.9,
                'score': 'B+',
                'product_lines': [ProductLineCodes.MTL1, ProductLineCodes.STL1],
                'message': 'Poin kredit Anda bagus. Peluang pengajuan Anda di-ACC cukup besar! '
                'Silakan pilih salah satu produk pinjaman di bawah ini & selesaikan pengajuannya. '
                'Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.65,
                'probability_max': 0.75,
                'score': 'B-',
                'product_lines': [ProductLineCodes.STL1],
                'message': 'Peluang pengajuan Anda di-ACC cukup besar! Silakan pilih salah '
                'satu produk pinjaman di bawah ini & selesaikan pengajuannya. '
                'Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.0,
                'probability_max': 0.65,
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
        ],
        'bypass_checks': [],
    },
    PartnerConstant.ATURDUIT_PARTNER: {
        'checks': {
            'application_date_of_birth': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria umur yang di tentukan.',
            },
            'job_not_black_listed': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'form_partial_location': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Produk pinjaman lain belum tersedia di daerah Anda.',
            },
            'form_partial_income': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria pinjaman yang ada. Silakan coba kembali 6 bulan mendatang.',
            },
            'saving_margin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum '
                'memenuhi kriteria pinjaman yang ada. Silakan coba kembali 6 bulan mendatang.',
            },
            'fraud_form_partial_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan HP yang '
                'sudah terdaftar. Silahkan login kembali menggunakan HP pribadi Anda.',
            },
            'fraud_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan HP yang '
                'sudah terdaftar. Silahkan login kembali menggunakan HP pribadi Anda.',
            },
            'fraud_form_partial_hp_own': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan nomor HP '
                'yang sudah terdaftar. Silahkan coba kembali menggunakan nomor HP pribadi Anda '
                'atau login menggunakan akun yang sudah terdaftar.',
            },
            'fraud_form_partial_hp_kin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'fraud_hp_spouse': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'email_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
            'sms_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
        },
        'scores': [
            {
                'probability_min': 0.9,
                'probability_max': 1.0,
                'score': 'A-',
                'product_lines': [ProductLineCodes.MTL1, ProductLineCodes.STL1],
                'message': 'Poin kredit Anda sangat bagus. Peluang pengajuan Anda di-ACC besar! '
                'Silakan pilih salah satu produk pinjaman di bawah ini & selesaikan pengajuannya. '
                'Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.75,
                'probability_max': 0.9,
                'score': 'B+',
                'product_lines': [ProductLineCodes.MTL1, ProductLineCodes.STL1],
                'message': 'Poin kredit Anda bagus. Peluang pengajuan Anda di-ACC cukup besar! '
                'Silakan pilih salah satu produk pinjaman di bawah ini & selesaikan pengajuannya. '
                'Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.65,
                'probability_max': 0.75,
                'score': 'B-',
                'product_lines': [ProductLineCodes.STL1],
                'message': 'Peluang pengajuan Anda di-ACC cukup besar! Silakan pilih salah satu '
                'produk pinjaman di bawah ini & selesaikan pengajuannya. Tinggal sedikit lagi!',
            },
            {
                'probability_min': 0.0,
                'probability_max': 0.65,
                'score': 'C',
                'product_lines': [ProductLineCodes.CTL1],
                'message': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                'memenuhi kriteria pinjaman yang ada.',
            },
        ],
        'bypass_checks': [],
    },
}

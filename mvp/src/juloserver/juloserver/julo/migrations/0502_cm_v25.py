# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models
from juloserver.julo.product_lines import ProductLineCodes


def credit_matrix2_v25(apps, _schema_editor):
    CreditMatrix = apps.get_model("julo", "CreditMatrix")
    CreditMatrixProductLine = apps.get_model("julo", "CreditMatrixProductLine")
    ProductLine = apps.get_model("julo", "ProductLine")

    CreditMatrixProductLine.objects.all().delete()
    CreditMatrix.objects.all().delete()

    ctl = ProductLine.objects.filter(pk=ProductLineCodes.CTL1).first()
    stl = ProductLine.objects.filter(pk=ProductLineCodes.STL1).first()
    mtl = ProductLine.objects.filter(pk=ProductLineCodes.MTL1).first()

    ctl2 = ProductLine.objects.filter(pk=ProductLineCodes.CTL2).first()
    stl2 = ProductLine.objects.filter(pk=ProductLineCodes.STL2).first()
    mtl2 = ProductLine.objects.filter(pk=ProductLineCodes.MTL2).first()

    # Inside Premium Area
    # Default Credit Matrix C
    cm_c = CreditMatrix.objects.create(
        score="C",
        min_threshold=0.00,
        max_threshold=0.69,
        score_tag='c_low_credit_score',
        message="{}{}".format("Anda belum dapat mengajukan pinjaman tanpa agunan ",
            "karena belum memenuhi kriteria pinjaman yang ada."),
        is_premium_area=True,
        credit_matrix_type="julo")

    cm_c_ctl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=0,
        max_loan_amount=0,
        max_duration=0,
        product=ctl,
        credit_matrix=cm_c
        )

    cm_c_ctl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=0,
        max_loan_amount=0,
        max_duration=0,
        product=ctl2,
        credit_matrix=cm_c
        )

    # Default Credit Matrix B- Low
    cm_bml = CreditMatrix.objects.create(
        score="B-",
        min_threshold=0.69,
        max_threshold=0.79,
        score_tag="B- low",
        message="{}{}{}".format("Peluang pengajuan Anda di-ACC cukup besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=True,
        credit_matrix_type="julo")

    cm_bml_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=500000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_bml
        )

    cm_bml_stl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=500000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_bml
        )

    cm_bml_mtl = CreditMatrixProductLine.objects.create(
        interest=0.06,
        min_loan_amount=2000000,
        max_loan_amount=4000000,
        max_duration=4,
        product=mtl,
        credit_matrix=cm_bml
        )

    cm_bml_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.06,
        min_loan_amount=2000000,
        max_loan_amount=4000000,
        max_duration=4,
        product=mtl2,
        credit_matrix=cm_bml
        )

    # Default Credit Matrix B- High
    cm_bmh = CreditMatrix.objects.create(
        score="B-",
        min_threshold=0.79,
        max_threshold=0.88,
        score_tag="B- high",
        message="{}{}{}".format("Peluang pengajuan Anda di-ACC cukup besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=True,
        credit_matrix_type="julo")

    cm_bmh_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_bmh
        )

    cm_bmh_stl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_bmh
        )

    cm_bmh_mtl = CreditMatrixProductLine.objects.create(
        interest=0.06,
        min_loan_amount=2000000,
        max_loan_amount=5000000,
        max_duration=4,
        product=mtl,
        credit_matrix=cm_bmh
        )

    cm_bmh_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.06,
        min_loan_amount=2000000,
        max_loan_amount=5000000,
        max_duration=4,
        product=mtl2,
        credit_matrix=cm_bmh
        )

    # Default Credit Matrix B+
    cm_bp = CreditMatrix.objects.create(
        score="B+",
        min_threshold=0.88,
        max_threshold=0.93,
        score_tag=None,
        message="{}{}{}{}".format("Poin kredit Anda bagus. ",
            "Peluang pengajuan Anda di-ACC cukup besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=True,
        credit_matrix_type="julo")

    cm_bp_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_bp
        )

    cm_bp_stl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_bp
        )

    cm_bp_mtl = CreditMatrixProductLine.objects.create(
        interest=0.05,
        min_loan_amount=2000000,
        max_loan_amount=7000000,
        max_duration=6,
        product=mtl,
        credit_matrix=cm_bp
        )

    cm_bp_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.05,
        min_loan_amount=2000000,
        max_loan_amount=7000000,
        max_duration=6,
        product=mtl2,
        credit_matrix=cm_bp
        )

    # Default Credit Matrix A+
    cm_ap = CreditMatrix.objects.create(
        score="A-",
        min_threshold=0.93,
        max_threshold=1.00,
        score_tag=None,
        message="{}{}{}{}".format("Poin kredit Anda sangat bagus. ",
            "Peluang pengajuan Anda di-ACC besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=True,
        credit_matrix_type="julo")

    cm_ap_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_ap
        )

    cm_ap_stl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_ap
        )

    cm_ap_mtl = CreditMatrixProductLine.objects.create(
        interest=0.04,
        min_loan_amount=2000000,
        max_loan_amount=8000000,
        max_duration=6,
        product=mtl,
        credit_matrix=cm_ap
        )

    cm_ap_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.04,
        min_loan_amount=2000000,
        max_loan_amount=8000000,
        max_duration=6,
        product=mtl2,
        credit_matrix=cm_ap
        )

    # Outside Premium Area
    # Default Credit Matrix C
    cm_c = CreditMatrix.objects.create(
        score="C",
        min_threshold=0.00,
        max_threshold=0.69,
        score_tag='c_low_credit_score',
        message="{}{}".format("Anda belum dapat mengajukan pinjaman tanpa agunan ",
            "karena belum memenuhi kriteria pinjaman yang ada."),
        is_premium_area=False,
        credit_matrix_type="julo")

    cm_c_ctl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=0,
        max_loan_amount=0,
        max_duration=0,
        product=ctl,
        credit_matrix=cm_c
        )

    cm_c_ctl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=0,
        max_loan_amount=0,
        max_duration=0,
        product=ctl2,
        credit_matrix=cm_c
        )

    # Default Credit Matrix B- Low
    cm_bml = CreditMatrix.objects.create(
        score="B-",
        min_threshold=0.69,
        max_threshold=0.79,
        score_tag="B- low",
        message="{}{}{}".format("Peluang pengajuan Anda di-ACC cukup besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=False,
        credit_matrix_type="julo")

    cm_bml_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=500000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_bml
        )

    cm_bml_stl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=500000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_bml
        )

    cm_bml_mtl = CreditMatrixProductLine.objects.create(
        interest=0.06,
        min_loan_amount=2000000,
        max_loan_amount=4000000,
        max_duration=4,
        product=mtl,
        credit_matrix=cm_bml
        )

    cm_bml_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.06,
        min_loan_amount=2000000,
        max_loan_amount=4000000,
        max_duration=4,
        product=mtl2,
        credit_matrix=cm_bml
        )

    # Default Credit Matrix B- High
    cm_bmh = CreditMatrix.objects.create(
        score="B-",
        min_threshold=0.79,
        max_threshold=0.88,
        score_tag="B- high",
        message="{}{}{}".format("Peluang pengajuan Anda di-ACC cukup besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=False,
        credit_matrix_type="julo")

    cm_bmh_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_bmh
        )

    cm_bmh_stl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_bmh
        )

    cm_bmh_mtl = CreditMatrixProductLine.objects.create(
        interest=0.06,
        min_loan_amount=2000000,
        max_loan_amount=4000000,
        max_duration=4,
        product=mtl,
        credit_matrix=cm_bmh
        )

    cm_bmh_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.06,
        min_loan_amount=2000000,
        max_loan_amount=4000000,
        max_duration=4,
        product=mtl2,
        credit_matrix=cm_bmh
        )

    # Default Credit Matrix B+
    cm_bp = CreditMatrix.objects.create(
        score="B+",
        min_threshold=0.88,
        max_threshold=0.93,
        score_tag=None,
        message="{}{}{}{}".format("Poin kredit Anda bagus. ",
            "Peluang pengajuan Anda di-ACC cukup besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=False,
        credit_matrix_type="julo")

    cm_bp_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_bp
        )

    cm_bp_stl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_bp
        )

    cm_bp_mtl = CreditMatrixProductLine.objects.create(
        interest=0.05,
        min_loan_amount=2000000,
        max_loan_amount=5000000,
        max_duration=5,
        product=mtl,
        credit_matrix=cm_bp
        )

    cm_bp_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.05,
        min_loan_amount=2000000,
        max_loan_amount=5000000,
        max_duration=5,
        product=mtl2,
        credit_matrix=cm_bp
        )

    # Default Credit Matrix A+
    cm_ap = CreditMatrix.objects.create(
        score="A-",
        min_threshold=0.93,
        max_threshold=1.00,
        score_tag=None,
        message="{}{}{}{}".format("Poin kredit Anda sangat bagus. ",
            "Peluang pengajuan Anda di-ACC besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=False,
        credit_matrix_type="julo")

    cm_ap_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_ap
        )

    cm_ap_stl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_ap
        )

    cm_ap_mtl = CreditMatrixProductLine.objects.create(
        interest=0.04,
        min_loan_amount=2000000,
        max_loan_amount=6000000,
        max_duration=6,
        product=mtl,
        credit_matrix=cm_ap
        )

    cm_ap_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.04,
        min_loan_amount=2000000,
        max_loan_amount=6000000,
        max_duration=6,
        product=mtl2,
        credit_matrix=cm_ap
        )

    # Webapp inside premium area
    # Default Credit Matrix C
    cm_c = CreditMatrix.objects.create(
        score="C",
        min_threshold=0.00,
        max_threshold=0.79,
        score_tag='c_low_credit_score',
        message="{}{}".format("Anda belum dapat mengajukan pinjaman tanpa agunan ",
            "karena belum memenuhi kriteria pinjaman yang ada."),
        is_premium_area=True,
        credit_matrix_type="webapp")

    cm_c_ctl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=0,
        max_loan_amount=0,
        max_duration=0,
        product=ctl,
        credit_matrix=cm_c
        )

    cm_c_ctl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=0,
        max_loan_amount=0,
        max_duration=0,
        product=ctl2,
        credit_matrix=cm_c
        )

    # Default Credit Matrix B-
    cm_bm = CreditMatrix.objects.create(
        score="B-",
        min_threshold=0.79,
        max_threshold=0.88,
        score_tag=None,
        message="{}{}{}".format("Peluang pengajuan Anda di-ACC cukup besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=True,
        credit_matrix_type="webapp")

    cm_bm_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=500000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_bm
        )

    cm_bm_stl2= CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=500000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_bm
        )

    cm_bm_mtl = CreditMatrixProductLine.objects.create(
        interest=0.06,
        min_loan_amount=3000000,
        max_loan_amount=3000000,
        max_duration=4,
        product=mtl,
        credit_matrix=cm_bm
        )

    cm_bm_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.06,
        min_loan_amount=3000000,
        max_loan_amount=3000000,
        max_duration=4,
        product=mtl2,
        credit_matrix=cm_bm
        )

    # Default Credit Matrix B+
    cm_bp = CreditMatrix.objects.create(
        score="B+",
        min_threshold=0.88,
        max_threshold=0.94,
        score_tag=None,
        message="{}{}{}{}".format("Poin kredit Anda bagus. ",
            "Peluang pengajuan Anda di-ACC cukup besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=True,
        credit_matrix_type="webapp")

    cm_bp_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=500000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_bp
        )

    cm_bp_stl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=500000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_bp
        )

    cm_bp_mtl = CreditMatrixProductLine.objects.create(
        interest=0.05,
        min_loan_amount=3000000,
        max_loan_amount=4000000,
        max_duration=5,
        product=mtl,
        credit_matrix=cm_bp
        )

    cm_bp_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.05,
        min_loan_amount=3000000,
        max_loan_amount=4000000,
        max_duration=5,
        product=mtl2,
        credit_matrix=cm_bp
        )

    # Default Credit Matrix A-
    cm_am = CreditMatrix.objects.create(
        score="A-",
        min_threshold=0.94,
        max_threshold=1.00,
        score_tag=None,
        message="{}{}{}{}".format("Poin kredit Anda sangat bagus. ",
            "Peluang pengajuan Anda di-ACC besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=True,
        credit_matrix_type="webapp")

    cm_am_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_am
        )

    cm_am_stl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_am
        )

    cm_am_mtl = CreditMatrixProductLine.objects.create(
        interest=0.04,
        min_loan_amount=3000000,
        max_loan_amount=5000000,
        max_duration=6,
        product=mtl,
        credit_matrix=cm_am
        )

    cm_am_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.04,
        min_loan_amount=3000000,
        max_loan_amount=5000000,
        max_duration=6,
        product=mtl2,
        credit_matrix=cm_am
        )

    # Webapp outside premium area
    # Default Credit Matrix C
    cm_c = CreditMatrix.objects.create(
        score="C",
        min_threshold=0.00,
        max_threshold=0.79,
        score_tag='c_low_credit_score',
        message="{}{}".format("Anda belum dapat mengajukan pinjaman tanpa agunan ",
            "karena belum memenuhi kriteria pinjaman yang ada."),
        is_premium_area=False,
        credit_matrix_type="webapp")

    cm_c_ctl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=0,
        max_loan_amount=0,
        max_duration=0,
        product=ctl,
        credit_matrix=cm_c
        )

    cm_c_ctl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=0,
        max_loan_amount=0,
        max_duration=0,
        product=ctl2,
        credit_matrix=cm_c
        )

    # Default Credit Matrix B-
    cm_bm = CreditMatrix.objects.create(
        score="B-",
        min_threshold=0.79,
        max_threshold=0.88,
        score_tag=None,
        message="{}{}{}".format("Peluang pengajuan Anda di-ACC cukup besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=False,
        credit_matrix_type="webapp")

    cm_bm_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=500000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_bm
        )

    cm_bm_stl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=500000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_bm
        )

    cm_bm_mtl = CreditMatrixProductLine.objects.create(
        interest=0.06,
        min_loan_amount=3000000,
        max_loan_amount=3000000,
        max_duration=4,
        product=mtl,
        credit_matrix=cm_bm
        )

    cm_bm_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.06,
        min_loan_amount=3000000,
        max_loan_amount=3000000,
        max_duration=4,
        product=mtl2,
        credit_matrix=cm_bm
        )

    # Default Credit Matrix B+
    cm_bp = CreditMatrix.objects.create(
        score="B+",
        min_threshold=0.88,
        max_threshold=0.94,
        score_tag=None,
        message="{}{}{}{}".format("Poin kredit Anda bagus. ",
            "Peluang pengajuan Anda di-ACC cukup besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=False,
        credit_matrix_type="webapp")

    cm_bp_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=500000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_bp
        )

    cm_bp_stl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=500000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_bp
        )

    cm_bp_mtl = CreditMatrixProductLine.objects.create(
        interest=0.05,
        min_loan_amount=3000000,
        max_loan_amount=4000000,
        max_duration=5,
        product=mtl,
        credit_matrix=cm_bp
        )

    cm_bp_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.05,
        min_loan_amount=3000000,
        max_loan_amount=4000000,
        max_duration=5,
        product=mtl2,
        credit_matrix=cm_bp
        )

    # Default Credit Matrix A-
    cm_am = CreditMatrix.objects.create(
        score="A-",
        min_threshold=0.94,
        max_threshold=1.00,
        score_tag=None,
        message="{}{}{}{}".format("Poin kredit Anda sangat bagus. ",
            "Peluang pengajuan Anda di-ACC besar! ",
            "Silakan pilih salah satu produk pinjaman di bawah ini ",
            "& selesaikan pengajuannya. Tinggal sedikit lagi!"),
        is_premium_area=False,
        credit_matrix_type="webapp")

    cm_am_stl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl,
        credit_matrix=cm_am
        )

    cm_am_stl2 = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=500000,
        max_loan_amount=1000000,
        max_duration=0,
        product=stl2,
        credit_matrix=cm_am
        )

    cm_am_mtl = CreditMatrixProductLine.objects.create(
        interest=0.04,
        min_loan_amount=3000000,
        max_loan_amount=5000000,
        max_duration=6,
        product=mtl,
        credit_matrix=cm_am
        )

    cm_am_mtl2 = CreditMatrixProductLine.objects.create(
        interest=0.04,
        min_loan_amount=3000000,
        max_loan_amount=5000000,
        max_duration=6,
        product=mtl2,
        credit_matrix=cm_am
        )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0502_add_skiptrace_callback_time'),
    ]

    operations = [
        migrations.RunPython(credit_matrix2_v25, migrations.RunPython.noop),
    ]
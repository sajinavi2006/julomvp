# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models
from juloserver.julo.product_lines import ProductLineCodes


def credit_matrix2_extend(apps, _schema_editor):
    CreditMatrix = apps.get_model("julo", "CreditMatrix")
    CreditMatrixProductLine = apps.get_model("julo", "CreditMatrixProductLine")
    ProductLine = apps.get_model("julo", "ProductLine")

    ctl = ProductLine.objects.filter(pk=ProductLineCodes.CTL2).first()
    stl = ProductLine.objects.filter(pk=ProductLineCodes.STL2).first()
    mtl = ProductLine.objects.filter(pk=ProductLineCodes.MTL2).first()

    # Inside Premium Area
    # Default Credit Matrix C
    cm_c = CreditMatrix.objects.filter(
        score="C",
        is_premium_area=True,
        credit_matrix_type="julo").first()
    if cm_c:
        cm_c_ctl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=0,
        max_loan_amount=0,
        max_duration=0,
        product=ctl,
        credit_matrix=cm_c
        )

    # Default Credit Matrix B- Low
    cm_bml = CreditMatrix.objects.filter(
        score="B-",
        score_tag="B- low",
        is_premium_area=True,
        credit_matrix_type="julo").first()
    if cm_bml:
        cm_bml_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=500000,
            max_duration=0,
            product=stl,
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

    # Default Credit Matrix B- High
    cm_bmh = CreditMatrix.objects.filter(
        score="B-",
        score_tag="B- high",
        is_premium_area=True,
        credit_matrix_type="julo").first()
    if cm_bmh:
        cm_bmh_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=1000000,
            max_duration=0,
            product=stl,
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

    # Default Credit Matrix B+
    cm_bp = CreditMatrix.objects.filter(
        score="B+",
        is_premium_area=True,
        credit_matrix_type="julo").first()
    if cm_bp:
        cm_bp_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=1000000,
            max_duration=0,
            product=stl,
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

    # Default Credit Matrix A+
    cm_ap = CreditMatrix.objects.filter(
        score="A-",
        is_premium_area=True,
        credit_matrix_type="julo").first()
    if cm_ap:
        cm_ap_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=1000000,
            max_duration=0,
            product=stl,
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

    # Outside Premium Area
    # Default Credit Matrix C
    cm_c = CreditMatrix.objects.filter(
        score="C",
        is_premium_area=False,
        credit_matrix_type="julo").first()
    if cm_c:
        cm_c_ctl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=0,
        max_loan_amount=0,
        max_duration=0,
        product=ctl,
        credit_matrix=cm_c
        )

    # Default Credit Matrix B- Low
    cm_bml = CreditMatrix.objects.filter(
        score="B-",
        score_tag="B- low",
        is_premium_area=False,
        credit_matrix_type="julo").first()
    if cm_bml:
        cm_bml_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=500000,
            max_duration=0,
            product=stl,
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

    # Default Credit Matrix B- High
    cm_bmh = CreditMatrix.objects.filter(
        score="B-",
        score_tag="B- high",
        is_premium_area=False,
        credit_matrix_type="julo").first()
    if cm_bmh:
        cm_bmh_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=1000000,
            max_duration=0,
            product=stl,
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

    # Default Credit Matrix B+
    cm_bp = CreditMatrix.objects.filter(
        score="B+",
        is_premium_area=False,
        credit_matrix_type="julo").first()
    if cm_bp:
        cm_bp_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=1000000,
            max_duration=0,
            product=stl,
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

    # Default Credit Matrix A+
    cm_ap = CreditMatrix.objects.filter(
        score="A-",
        is_premium_area=False,
        credit_matrix_type="julo").first()
    if cm_ap:
        cm_ap_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=1000000,
            max_duration=0,
            product=stl,
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

    # Webapp outside premium area
    # Default Credit Matrix C
    cm_c = CreditMatrix.objects.filter(
        score="C",
        is_premium_area=False,
        credit_matrix_type="webapp").first()
    if cm_c:
        cm_c_ctl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=0,
        max_loan_amount=0,
        max_duration=0,
        product=ctl,
        credit_matrix=cm_c
        )

    # Default Credit Matrix B-
    cm_bm = CreditMatrix.objects.filter(
        score="B-",
        is_premium_area=False,
        credit_matrix_type="webapp").first()
    if cm_bm:
        cm_bm_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=500000,
            max_duration=0,
            product=stl,
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

    # Default Credit Matrix B+
    cm_bp = CreditMatrix.objects.filter(
        score="B+",
        is_premium_area=False,
        credit_matrix_type="webapp").first()
    if cm_bp:
        cm_bp_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=500000,
            max_duration=0,
            product=stl,
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

    # Default Credit Matrix A-
    cm_am = CreditMatrix.objects.filter(
        score="A-",
        is_premium_area=False,
        credit_matrix_type="webapp").first()
    if cm_am:
        cm_am_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=1000000,
            max_duration=0,
            product=stl,
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

    # Webapp inside premium area
    # Default Credit Matrix C
    cm_c = CreditMatrix.objects.filter(
        score="C",
        is_premium_area=True,
        credit_matrix_type="webapp").first()
    if cm_c:
        cm_c_ctl = CreditMatrixProductLine.objects.create(
        interest=0,
        min_loan_amount=0,
        max_loan_amount=0,
        max_duration=0,
        product=ctl,
        credit_matrix=cm_c
        )

    # Default Credit Matrix B-
    cm_bm = CreditMatrix.objects.filter(
        score="B-",
        is_premium_area=True,
        credit_matrix_type="webapp").first()
    if cm_bm:
        cm_bm_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=500000,
            max_duration=0,
            product=stl,
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

    # Default Credit Matrix B+
    cm_bp = CreditMatrix.objects.filter(
        score="B+",
        is_premium_area=True,
        credit_matrix_type="webapp").first()
    if cm_bp:
        cm_bp_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=500000,
            max_duration=0,
            product=stl,
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

    # Default Credit Matrix A-
    cm_am = CreditMatrix.objects.filter(
        score="A-",
        is_premium_area=True,
        credit_matrix_type="webapp").first()
    if cm_am:
        cm_am_stl = CreditMatrixProductLine.objects.create(
            interest=0,
            min_loan_amount=500000,
            max_loan_amount=1000000,
            max_duration=0,
            product=stl,
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

def non_premium_area_amount(apps, _schema_editor):
    ProductLine = apps.get_model("julo", "ProductLine")

    ProductLine.objects.filter(
        product_line_code__in=ProductLineCodes.mtl()
        ).update(
        non_premium_area_min_amount=2000000,
        non_premium_area_max_amount=6000000
        )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0501_add_field_appsflyer_log'),
    ]

    operations = [
        migrations.RunPython(credit_matrix2_extend, migrations.RunPython.noop),
    ]
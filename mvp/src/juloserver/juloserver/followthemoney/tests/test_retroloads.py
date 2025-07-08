from importlib import import_module

from django.test import TestCase

from juloserver.followthemoney.factories import LenderCurrentFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import ProductLineFactory


class TestRetroloadBypassLenderMatchMakingByProductLine(TestCase):
    retroload = import_module('.164707291831__followthemoney__feature_setting_bypass_by_product_line',
                              package='juloserver.retroloads')

    def test_retroload_bypass_lender_match_making_by_product_line(self):
        jtp_lender = LenderCurrentFactory(lender_name='jtp')
        julover_product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)

        self.retroload.create_feature_setting_bypass_by_product_line(None, None)

        feature_setting = FeatureSetting.objects.get(
            feature_name=FeatureNameConst.BYPASS_LENDER_MATCHMAKING_PROCESS_BY_PRODUCT_LINE
        )
        expected_parameters = {
            str(julover_product_line.product_line_code): jtp_lender.id
        }
        self.assertTrue(feature_setting.is_active)
        self.assertEquals(expected_parameters, feature_setting.parameters)
        self.assertEquals('followthemoney', feature_setting.category)

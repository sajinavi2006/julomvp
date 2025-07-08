import csv
import json

from django.core.management.base import BaseCommand

from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


class Command(BaseCommand):
    help = 'Retroload for Feature Setting Instruction Verification Docs'

    def create_feature_setting(self):
        default_json_dir = 'misc_files/json/default_instruction_verification_docs.json'
        with open(default_json_dir, 'r') as f:
            parameters = json.load(f)

        setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.INSTRUCTION_VERIFICATION_DOCS
        ).exists()
        if setting:
            self.stdout.write(self.style.ERROR('Feature Setting already exist.'))
            return False

        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.INSTRUCTION_VERIFICATION_DOCS,
            category='upload document',
            description='Content for Instruction Page Upload Document Verification',
            is_active=True,
            parameters=parameters,
        )
        return True

    def handle(self, *args, **options):

        self.stdout.write(self.style.SUCCESS('start executing...'))
        self.create_feature_setting()
        self.stdout.write(self.style.SUCCESS('Done executed.'))

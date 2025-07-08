from __future__ import print_function

import logging

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Creating initial for user roles using django auth group'

    # def add_arguments(self, parser):
    #     parser.add_argument('roles', nargs='+', type=str)

    def handle(self, *args, **options):
        logging.basicConfig(level=logging.DEBUG, format="%(message)s")
        logging.info("-" * 72)
        user_roles = [
            'admin_full',
            'admin_read_only',
            'bo_full',
            'bo_read_only',
            'bo_data_verifier',
            'bo_credit_analyst',
            'bo_outbound_caller',
            'bo_finance',
            'bo_general_cs',
            'partner_full',
            'partner_read_only',
            'collection_recovery',
            'freelance',
        ]
        for roles in user_roles:
            new_group, created = Group.objects.get_or_create(name=roles)

        logging.info("creating user roles is quitting.")
        print("Creating User Roles Successfully")

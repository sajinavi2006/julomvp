from __future__ import absolute_import
import pytest
import datetime
import mock
from mock import patch

from django.test.testcases import TestCase
from .factories import CollectionAgentTaskFactory
from juloserver.collectionbucket.models import CollectionAgentTask
from juloserver.collectionbucket.management.commands import retroload_collection_agent_task_data


class TestRetroloadCollectionAgentTask(TestCase):
    def setUp(self):
        self.collection_agent_task = CollectionAgentTaskFactory(type='dpd71_dpd100')

    def test_retroload_collection_agent_task_data(self):
        retroload_collection_agent_task_data.Command().handle()
        collection_agent_task = CollectionAgentTask.objects.last()
        self.assertEqual(collection_agent_task.type, 'dpd71_dpd90')


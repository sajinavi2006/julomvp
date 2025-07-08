from builtins import object
import datetime
from juloserver.julo.models import Agent, DashboardBuckets, Customer, Payment, Loan, ProductLookup, EmailAttachments, \
    EmailHistory
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

class UserSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = get_user_model()
        fields = ( 'username', 'email', 'first_name', 'id')



class GroupSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Group
        fields = ( 'name','id')

class AgentSerializer(serializers.ModelSerializer):
    user = UserSerializer(required=False)
    created_by = UserSerializer(required=False)
    roles = serializers.SerializerMethodField()
    class Meta(object):
        model = Agent
        fields = ('user', 'created_by', 'roles', 'id','user_extension','cdate')
        read_only_fields = ('created_by',)

    def get_roles(self, agent):
        return agent.user.groups.values_list('name',flat=True)

    def custome_validation(self, data):
        if not data.get('user'):
            raise serializers.ValidationError("Incorrect username")
        if not data.get('role'):
            raise serializers.ValidationError("Incorrect role")
        if not data.get('password') and len(data.get('password')) < 5:
            raise serializers.ValidationError("Incorrect password ")
        
        return True


class BucketSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = DashboardBuckets


class PaymentSerializer(serializers.ModelSerializer):
    dpd = serializers.SerializerMethodField()

    class Meta(object):
        model = Payment
        fields = ('id', 'due_amount', 'dpd', 'status')

    def get_dpd(self, payment):
        today = datetime.datetime.now().date()
        diff_day = payment.due_date - today
        return diff_day.days


class LoanSerializer(serializers.ModelSerializer):
    payment = PaymentSerializer(source='payment_set', many=True)
    product = serializers.SerializerMethodField()
    class Meta(object):
        model = Loan
        fields = ('id', 'payment', 'product')

    def get_product(self, loan):
        data = {
            "code": loan.product.product_line.product_line_code,
            "id": loan.product.product_line.pk,
            "type": loan.product.product_line.product_line_type
        }
        return data


class CustomerSerializer(serializers.ModelSerializer):
    loan = LoanSerializer(source='loan_set', many=True)
    class Meta(object):
        fields = ('id', 'fullname', 'loan', 'email', 'phone', 'email', 'country', 'cdate')
        model = Customer


class EmailAttachmentSerializer(serializers.ModelSerializer):
    class Meta(object):
        fields = ('id', 'cdate', 'attachment')
        model = EmailAttachments


class EmailSerializer(serializers.ModelSerializer):
    email = EmailAttachmentSerializer(source='emailattachments_set', many=True)

    class Meta(object):
        fields = ('id', 'message_content', 'to_email', 'cc_email', 'subject', 'email', 'customer')
        read_only_fields = ('email',)
        model = EmailHistory

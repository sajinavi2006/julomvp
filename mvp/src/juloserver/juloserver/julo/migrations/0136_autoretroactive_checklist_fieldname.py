
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0135_add_field_application'),
    ]

    operations = [
        migrations.RunSQL(
            "UPDATE application_check_list SET field_name='hrd_name' WHERE field_name='nama_hrd';"),
        migrations.RunSQL(
            "UPDATE application_check_list SET field_name='company_address' WHERE field_name='alamat_kantor_penempatan';"),
        migrations.RunSQL(
            "UPDATE application_check_list SET field_name='number_of_employees' WHERE field_name='jumlah_karyawan';"),
        migrations.RunSQL(
            "UPDATE application_check_list SET field_name='position_employees' WHERE field_name='posisi_karyawan';"),
        migrations.RunSQL(
            "UPDATE application_check_list SET field_name='employment_status' WHERE field_name='status_kepegawaian';"),
        migrations.RunSQL(
            "UPDATE application_check_list SET field_name='billing_office' WHERE field_name='tunggakan_di_kantor';"),
        migrations.RunSQL(
            "UPDATE application_check_list SET field_name='mutation' WHERE field_name='mutasi';"),
        migrations.RunSQL(
            "UPDATE application_check_list_comment SET field_name='hrd_name' WHERE field_name='nama_hrd';"),
        migrations.RunSQL(
            "UPDATE application_check_list_comment SET field_name='company_address' WHERE field_name='alamat_kantor_penempatan';"),
        migrations.RunSQL(
            "UPDATE application_check_list_comment SET field_name='number_of_employees' WHERE field_name='jumlah_karyawan';"),
        migrations.RunSQL(
            "UPDATE application_check_list_comment SET field_name='position_employees' WHERE field_name='posisi_karyawan';"),
        migrations.RunSQL(
            "UPDATE application_check_list_comment SET field_name='employment_status' WHERE field_name='status_kepegawaian';"),
        migrations.RunSQL(
            "UPDATE application_check_list_comment SET field_name='billing_office' WHERE field_name='tunggakan_di_kantor';"),
        migrations.RunSQL(
            "UPDATE application_check_list_comment SET field_name='mutation' WHERE field_name='mutasi';"),
    ]

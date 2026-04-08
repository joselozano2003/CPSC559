from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_file_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='chunk',
            name='expected_hash',
            field=models.CharField(max_length=64, null=True, blank=True),
        ),
    ]

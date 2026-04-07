from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_pendingdelete'),
    ]

    operations = [
        migrations.AddField(
            model_name='file',
            name='status',
            field=models.CharField(
                choices=[('pending', 'Pending'), ('complete', 'Complete'), ('failed', 'Failed')],
                default='complete',
                max_length=16,
            ),
        ),
    ]

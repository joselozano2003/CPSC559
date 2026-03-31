import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_remove_chunk_storage_node_chunkreplica'),
    ]

    operations = [
        migrations.CreateModel(
            name='PendingDelete',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chunk_id', models.CharField(max_length=255)),
                ('retry_count', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('storage_node', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pending_deletes', to='core.storagenode')),
            ],
            options={
                'unique_together': {('storage_node', 'chunk_id')},
            },
        ),
    ]

import os
from django.db import migrations


def seed_storage_node(apps, schema_editor):
    StorageNode = apps.get_model('core', 'StorageNode')
    StorageNode.objects.get_or_create(
        name='storage-node-1',
        defaults={
            'address': os.environ.get('STORAGE_NODE_URL', 'http://storage-node:6000'),
            'is_active': True,
        }
    )


def unseed_storage_node(apps, schema_editor):
    StorageNode = apps.get_model('core', 'StorageNode')
    StorageNode.objects.filter(name='storage-node-1').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_storagenode_alter_chunk_storage_node'),
    ]

    operations = [
        migrations.RunPython(seed_storage_node, unseed_storage_node),
    ]
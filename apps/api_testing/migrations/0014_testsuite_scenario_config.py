from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api_testing', '0013_alter_apipromptconfig_prompt_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='testsuite',
            name='scenario_config',
            field=models.JSONField(blank=True, default=dict, verbose_name='可视化场景配置'),
        ),
    ]

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("rules", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="Group",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.AlterModelOptions(
            name="rule",
            options={"ordering": ["group__name", "domain"]},
        ),
        migrations.AlterField(
            model_name="rule",
            name="domain",
            field=models.CharField(max_length=253),
        ),
        # The table is empty at this point in the project's life, so the
        # default binds to no row and preserve_default drops it again.
        migrations.AddField(
            model_name="rule",
            name="group",
            field=models.ForeignKey(
                default=1,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rules",
                to="rules.group",
            ),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name="rule",
            constraint=models.UniqueConstraint(
                fields=("group", "domain"), name="one_rule_per_domain_per_group"
            ),
        ),
    ]

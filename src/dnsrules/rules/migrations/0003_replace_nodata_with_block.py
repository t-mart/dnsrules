from django.db import migrations, models


def replace_nodata(apps, schema_editor) -> None:
    Rule = apps.get_model("rules", "Rule")
    Rule.objects.filter(action="block_nodata").update(action="block")


class Migration(migrations.Migration):
    dependencies = [("rules", "0002_remove_group_zone")]

    operations = [
        migrations.RunPython(replace_nodata, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="rule",
            name="action",
            field=models.CharField(
                choices=[
                    ("block", "Block, answer NXDOMAIN"),
                    ("allow", "Allow, skip the blocklist"),
                ],
                default="block",
                max_length=16,
            ),
        ),
    ]

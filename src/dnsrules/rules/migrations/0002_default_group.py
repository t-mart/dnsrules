"""Give a fresh install one group, so a rule has somewhere to go.

The name picks the URL that unbound fetches, at `/rpz/home.zone`. The zone is
what `unbound.conf` calls it. Both are data, so change them here or in the
admin rather than in code.
"""

from django.db import migrations

NAME = "home"
ZONE = "runtime_rules"


def add(apps, schema_editor) -> None:
    Group = apps.get_model("rules", "Group")
    Group.objects.get_or_create(name=NAME, defaults={"zone": ZONE})


def remove(apps, schema_editor) -> None:
    Group = apps.get_model("rules", "Group")
    Group.objects.filter(name=NAME, rules__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("rules", "0001_initial")]

    operations = [migrations.RunPython(add, remove)]

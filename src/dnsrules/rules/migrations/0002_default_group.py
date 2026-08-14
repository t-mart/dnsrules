"""Create the rules zone, so a rule has somewhere to go.

`RPZ_NAME` picks the URL that unbound fetches, at `/rpz/<name>.zone`. `RPZ_ZONE`
is the name unbound.conf gives that zone. Both default to `dnsrules`.

The settings seed the row and nothing more. Change the row to rename the zone
on a database that exists already.
"""

from django.conf import settings
from django.db import migrations


def add(apps, schema_editor) -> None:
    Group = apps.get_model("rules", "Group")
    Group.objects.get_or_create(
        name=settings.RPZ_NAME, defaults={"zone": settings.RPZ_ZONE}
    )


def remove(apps, schema_editor) -> None:
    Group = apps.get_model("rules", "Group")
    Group.objects.filter(name=settings.RPZ_NAME, rules__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("rules", "0001_initial")]

    operations = [migrations.RunPython(add, remove)]

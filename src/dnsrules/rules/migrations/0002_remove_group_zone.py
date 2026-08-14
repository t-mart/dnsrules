"""One name for a zone, not two.

`name` picked the URL and `zone` named it inside unbound. They had no reason to
differ, and two names for one thing is the drift that `reconcile` had to learn
to catch. `name` survives, because it is the one a URL already carries.

A row is seeded from `DNSRULES_RPZ_ZONES` after each migrate. See
`rules/apps.py`.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("rules", "0001_initial")]

    operations = [migrations.RemoveField(model_name="group", name="zone")]

"""Record that an answer was blocked, and stop recording what blocked it.

`blocked_by` held `rule` or `feed`. The `feed` half read the RA bit off the
answer. The `rule` half matched the query name against the rules table, which
cannot see a wildcard, cannot tell that a client carries no tag, and cannot
know which zone reaches which client. The boolean keeps the half that works.

The index goes too. Two values give the planner nothing that the BRIN on `at`
does not already give it.
"""

from django.db import migrations, models


def fill(apps, schema_editor) -> None:
    Query = apps.get_model("queries", "Query")
    Query.objects.exclude(blocked_by="").update(blocked=True)


def empty(apps, schema_editor) -> None:
    Query = apps.get_model("queries", "Query")
    Query.objects.filter(blocked=True).update(blocked_by="feed")


class Migration(migrations.Migration):
    dependencies = [("queries", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="query",
            name="blocked",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(fill, empty),
        migrations.RemoveIndex(model_name="query", name="queries_query_blocked_by"),
        migrations.RemoveField(model_name="query", name="blocked_by"),
    ]

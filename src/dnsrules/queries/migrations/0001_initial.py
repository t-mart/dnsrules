"""Create the query log as a partitioned table, and the archive beside it.

Django writes `CREATE TABLE`, and it has no way to add `PARTITION BY`. So the
SQL is written here and `state_operations` tells Django what it produced. The
model and this file must stay in step, or `makemigrations --check` fails.

The DEFAULT partition is a safety net. Without one, an insert for a day that
has no partition raises and the ingest loses rows. With one, the row lands and
nothing is lost. The cost: a later `CREATE ... PARTITION OF` for that same day
fails while those rows sit there. The retention job runs days ahead of time so
that case stays theoretical.
"""

from django.db import migrations, models

TABLE = "queries_query"

CREATE = f"""
CREATE TABLE {TABLE} (
    id bigserial NOT NULL,
    at timestamptz NOT NULL,
    client inet NOT NULL,
    qname varchar(253) NOT NULL,
    qtype varchar(16) NOT NULL,
    rcode varchar(16) NOT NULL,
    reply_ms double precision NULL,
    blocked boolean NOT NULL,
    PRIMARY KEY (at, id)
) PARTITION BY RANGE (at);

-- The rows arrive in time order, so a block range summary is enough. It costs
-- a fraction of the space a btree would take over 7 million rows.
CREATE INDEX {TABLE}_at_brin ON {TABLE} USING brin (at);

-- The log table filters on these two.
CREATE INDEX {TABLE}_qname ON {TABLE} (qname varchar_pattern_ops);
CREATE INDEX {TABLE}_client ON {TABLE} (client);

CREATE TABLE {TABLE}_default PARTITION OF {TABLE} DEFAULT;
"""

DROP = f"DROP TABLE {TABLE} CASCADE;"


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.RunSQL(
            sql=CREATE,
            reverse_sql=DROP,
            state_operations=[
                migrations.CreateModel(
                    name="Query",
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
                        ("at", models.DateTimeField()),
                        ("client", models.GenericIPAddressField()),
                        ("qname", models.CharField(max_length=253)),
                        ("qtype", models.CharField(max_length=16)),
                        ("rcode", models.CharField(blank=True, max_length=16)),
                        ("reply_ms", models.FloatField(blank=True, null=True)),
                        ("blocked", models.BooleanField(default=False)),
                    ],
                    options={"ordering": ["-at"], "verbose_name_plural": "queries"},
                ),
            ],
        ),
        migrations.CreateModel(
            name="Hour",
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
                ("at", models.DateTimeField()),
                ("client", models.GenericIPAddressField()),
                ("blocked", models.BooleanField()),
                ("count", models.PositiveIntegerField()),
            ],
            options={
                "ordering": ["-at"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("at", "client", "blocked"),
                        name="one_row_per_client_per_hour",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Top",
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
                ("at", models.DateField()),
                ("qname", models.CharField(max_length=253)),
                ("blocked", models.BooleanField()),
                ("count", models.PositiveIntegerField()),
            ],
            options={
                "ordering": ["-at", "-count"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("at", "qname", "blocked"),
                        name="one_row_per_name_per_day",
                    )
                ],
            },
        ),
    ]

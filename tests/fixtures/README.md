# Fixtures

Captured bytes from a live resolver. `dnstap.fstrm` is not committed, because it
holds every DNS query the network made during the capture window.

The tests that need it skip when it is absent. See "Fixtures" in
[DEVELOPMENT.md](../../DEVELOPMENT.md) for the capture recipe.

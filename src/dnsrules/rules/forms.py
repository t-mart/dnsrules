from datetime import timedelta

from django import forms
from django.utils import timezone

from dnsrules.rules.models import Rule

# Seconds, or empty for permanent. The form asks for a duration and never for a
# date, because the case that started this project is "let me reach this site
# for the next hour".
DURATIONS = [
    ("", "Permanent"),
    ("900", "15 minutes"),
    ("3600", "1 hour"),
    ("28800", "8 hours"),
    ("86400", "1 day"),
    ("604800", "1 week"),
]

KEEP = "keep"


class RuleForm(forms.ModelForm):
    duration = forms.ChoiceField(choices=DURATIONS, required=False, label="Expires")

    class Meta:
        model = Rule
        fields = ["group", "domain", "action", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(["group", "domain", "action", "duration", "note"])
        if self.instance.pk:
            self.fields["duration"].choices = [(KEEP, "No change"), *DURATIONS]
            self.fields["duration"].initial = KEEP

    def save(self, commit: bool = True) -> Rule:
        rule = super().save(commit=False)
        seconds = self.cleaned_data["duration"]
        if seconds != KEEP:
            rule.expires_at = (
                timezone.now() + timedelta(seconds=int(seconds)) if seconds else None
            )
        if commit:
            rule.save()
        return rule

from datetime import timedelta
from decimal import Decimal

from django import forms
from django.utils import timezone

from .models import Need
from .services import MAX_TAGS, BidError, clean_tags

# value = minutes. The 5-minute option is only SHOWN with ?demo=1 but always accepted.
DURATION_CHOICES = (
    ("30", "30 min"),
    ("120", "2 h"),
    ("1440", "24 h"),
    ("4320", "3 jours"),
)
DEMO_DURATION = ("5", "5 min (démo)")


class NeedForm(forms.ModelForm):
    tags = forms.CharField(
        label="Compétences",
        required=False,
        help_text=f"Jusqu’à {MAX_TAGS} mots-clés, séparés par des virgules (ex. django, stellar, ui).",
        widget=forms.TextInput(attrs={"class": "ui-input", "placeholder": "django, stellar, ui", "autocomplete": "off"}),
    )
    delay_max_days = forms.IntegerField(
        label="Délai max",
        min_value=1,
        max_value=365,
        widget=forms.NumberInput(attrs={"class": "ui-input", "inputmode": "numeric", "placeholder": "10"}),
    )
    duration = forms.ChoiceField(
        label="Durée des enchères",
        choices=DURATION_CHOICES,
        initial="120",
        widget=forms.Select(attrs={"class": "ui-select"}),
    )

    class Meta:
        model = Need
        fields = ["title", "description", "budget_max", "delay_max_days"]
        labels = {
            "title": "Titre",
            "description": "Description",
            "budget_max": "Budget max",
            "delay_max_days": "Délai max",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "ui-input", "placeholder": "Landing page Django + Stellar", "maxlength": 120}),
            "description": forms.Textarea(
                attrs={"class": "ui-textarea", "rows": 5, "placeholder": "Ce que vous attendez, les livrables, le contexte…"}
            ),
            "budget_max": forms.NumberInput(attrs={"class": "ui-input", "inputmode": "decimal", "step": "0.01", "min": "0.01", "placeholder": "500"}),
        }

    def __init__(self, *args, demo: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.demo = demo
        # The field always ACCEPTS the demo value; the template only SHOWS it with ?demo=1.
        self.fields["duration"].choices = (DEMO_DURATION, *DURATION_CHOICES)
        if demo:
            self.fields["duration"].initial = DEMO_DURATION[0]

    @property
    def visible_durations(self):
        return self.fields["duration"].choices if self.demo else DURATION_CHOICES

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if len(title) < 4:
            raise forms.ValidationError("Le titre est trop court.")
        return title

    def clean_budget_max(self):
        budget = self.cleaned_data["budget_max"]
        if budget is None or budget <= 0:
            raise forms.ValidationError("Le budget doit être strictement positif.")
        if budget != budget.quantize(Decimal("0.0000001")):
            raise forms.ValidationError("Au plus 7 décimales (précision USDC).")
        return budget

    def clean_tags(self):
        try:
            return clean_tags(self.cleaned_data.get("tags", ""))
        except BidError as e:
            raise forms.ValidationError(e.message) from None

    def save(self, client, commit: bool = True) -> Need:
        need: Need = super().save(commit=False)
        need.client = client
        need.tags = self.cleaned_data["tags"]
        need.bidding_ends_at = timezone.now() + timedelta(minutes=int(self.cleaned_data["duration"]))
        if commit:
            need.save()
        return need

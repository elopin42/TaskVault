from django import forms

from .models import Project
from .services import TITLE_MIN


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["title", "description"]
        labels = {"title": "Titre du projet", "description": "Description"}
        widgets = {
            "title": forms.TextInput(
                attrs={"class": "ui-input", "placeholder": "Site vitrine + paiement Stellar", "maxlength": 120, "autofocus": True}
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "ui-textarea",
                    "rows": 6,
                    "placeholder": "Le contexte, l’objectif, ce que vous attendez au final. Vous découperez ensuite en tâches à prix fixe.",
                }
            ),
        }

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if len(title) < TITLE_MIN:
            raise forms.ValidationError("Le titre est trop court.")
        return title

    def clean_description(self):
        description = self.cleaned_data["description"].strip()
        if not description:
            raise forms.ValidationError("Décrivez le projet en quelques lignes.")
        return description

    def save(self, company, commit: bool = True) -> Project:
        project: Project = super().save(commit=False)
        project.company = company
        if commit:
            project.save()
        return project

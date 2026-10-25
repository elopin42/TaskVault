from django import forms

from .models import Project
from .services import TITLE_MIN, initial_published_at


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["title", "description"]
        labels = {"title": "Project title", "description": "Description"}
        widgets = {
            "title": forms.TextInput(
                attrs={"class": "ui-input", "placeholder": "Showcase website + Stellar payment", "maxlength": 120, "autofocus": True}
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "ui-textarea",
                    "rows": 6,
                    "placeholder": "The context, the goal, what you expect in the end. You will then split it into fixed-price tasks.",
                }
            ),
        }

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if len(title) < TITLE_MIN:
            raise forms.ValidationError("The title is too short.")
        return title

    def clean_description(self):
        description = self.cleaned_data["description"].strip()
        if not description:
            raise forms.ValidationError("Describe the project in a few lines.")
        return description

    def save(self, company, commit: bool = True) -> Project:
        project: Project = super().save(commit=False)
        project.company = company
        if project.pk is None:
            project.published_at = initial_published_at()
        if commit:
            project.save()
        return project

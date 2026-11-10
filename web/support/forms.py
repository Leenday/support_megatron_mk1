from django import forms
from django.utils.translation import gettext_lazy as _

from support.models import Department, Ticket


class RequestForm(forms.Form):
    text = forms.CharField(
        label=_("Describe the problem in your own words"),
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 8, "autofocus": True}),
        help_text=_("Russian or English. Who, where, when and what happened, if you know."),
    )
    contact = forms.CharField(
        label=_("How to reach you"),
        max_length=200,
        help_text=_("E-mail, phone or messenger."),
    )


class TagsField(forms.CharField):
    """Tags as one comma-separated line."""

    def prepare_value(self, value):
        return ", ".join(value) if isinstance(value, list) else value

    def to_python(self, value):
        text = super().to_python(value) or ""
        return list(dict.fromkeys(t.strip() for t in text.split(",") if t.strip()))


class DeskFilterForm(forms.Form):
    """Filters of the dashboard lists (story 21); every field is optional."""

    status = forms.ChoiceField(
        label=_("Status"),
        required=False,
        choices=[("", _("Any"))] + Ticket.Status.choices,
    )
    tag = forms.CharField(label=_("Tag"), required=False, max_length=50)
    since = forms.DateField(
        label=_("From"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    until = forms.DateField(
        label=_("To"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )


class TicketEditForm(forms.Form):
    who = forms.CharField(label=_("Who"), required=False, max_length=500)
    where = forms.CharField(label=_("Where"), required=False, max_length=500)
    when = forms.CharField(label=_("When"), required=False, max_length=500)
    what = forms.CharField(label=_("What"), max_length=1000)
    summary = forms.CharField(label=_("Summary"), max_length=300)
    tags = TagsField(label=_("Tags"), required=False, help_text=_("Separated by commas."))

    def clean(self):
        super().clean()
        data = self.cleaned_data
        # An empty optional field means "unknown", stored as null like the model's answer.
        for field in ("who", "where", "when"):
            if field in data and not data[field]:
                data[field] = None
        return data


class ReturnForm(forms.Form):
    reason = forms.CharField(
        label=_("Why it is not for this department"),
        max_length=500,
        widget=forms.TextInput(),
    )


class DepartmentField(forms.ModelChoiceField):
    """Departments named in the interface language."""

    language = "ru"

    def label_from_instance(self, obj: Department) -> str:
        return obj.name(self.language)


class CloseForm(forms.Form):
    correct = forms.ChoiceField(
        label=_("Was the department right?"),
        choices=[("yes", _("Yes")), ("no", _("No, it should have gone to:"))],
        widget=forms.RadioSelect,
        initial="yes",
    )
    department = DepartmentField(
        label=_("Department"),
        empty_label=_("Choose a department"),
        queryset=Department.objects.filter(active=True),
        required=False,
    )

    def __init__(self, *args, language: str = "ru", exclude: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["department"]
        assert isinstance(field, DepartmentField)
        field.queryset = Department.objects.filter(active=True).exclude(pk=exclude)
        field.language = language

    def clean(self):
        super().clean()
        data = self.cleaned_data
        if data.get("correct") == "no" and not data.get("department"):
            self.add_error("department", _("Choose the department that should have got it."))
        return data

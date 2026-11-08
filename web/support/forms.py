from django import forms
from django.utils.translation import gettext_lazy as _


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

"""Django forms for the cms app."""

from __future__ import annotations

from django import forms

from cms.homepage_forms import config_from_form, get_section_config_form
from cms.models import HomepageSection


class HomepageSectionAdminForm(forms.ModelForm):
    """
    Model form with structured per-type config fields (not raw JSON).

    Mirrors Phase 5 gifting pattern: one form class per section_type in a registry.
    """

    class Meta:
        model = HomepageSection
        fields = ("section_type", "title", "display_order", "is_active")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        section_type = (
            self.data.get("section_type")
            if self.data
            else (
                self.initial.get("section_type")
                if (self.initial and self.initial.get("section_type"))
                else (self.instance.section_type if (self.instance and self.instance.pk) else "")
            )
        )

        from cms.models import HomepageSectionType
        from core.services import get_site_settings

        site_settings = get_site_settings()
        if not getattr(site_settings, "enable_brands", True):
            if not (
                self.instance
                and self.instance.pk
                and self.instance.section_type == HomepageSectionType.FEATURED_BRANDS
            ):
                self.fields["section_type"].choices = [
                    choice
                    for choice in self.fields["section_type"].choices
                    if choice[0] != HomepageSectionType.FEATURED_BRANDS
                ]
        if not getattr(site_settings, "enable_newsletter", True):
            if not (
                self.instance
                and self.instance.pk
                and self.instance.section_type == HomepageSectionType.NEWSLETTER
            ):
                self.fields["section_type"].choices = [
                    choice
                    for choice in self.fields["section_type"].choices
                    if choice[0] != HomepageSectionType.NEWSLETTER
                ]

        initial_config = self.instance.config if self.instance.pk else {}
        self.config_form = get_section_config_form(
            section_type=section_type,
            initial=initial_config,
        )
        prefix = "config_"


        if self.data or (hasattr(self, "files") and self.files):
            config_data = {
                key[len(prefix) :]: value
                for key, value in self.data.items()
                if key.startswith(prefix)
            }
            config_files = {
                key[len(prefix) :]: value
                for key, value in self.files.items()
                if key.startswith(prefix)
            }
            form_class = type(self.config_form)
            self.config_form = form_class(
                data=config_data,
                files=config_files,
                initial=self.config_form.initial,
            )
        for name, field in self.config_form.fields.items():
            self.fields[f"config_{name}"] = field
            val = self.config_form.initial.get(name)
            self.fields[f"config_{name}"].initial = val
            self.initial[f"config_{name}"] = val

    def clean(self) -> dict:
        cleaned = super().clean()
        section_type = cleaned.get("section_type", "")

        from cms.models import HomepageSectionType
        from core.services import get_site_settings

        if section_type == HomepageSectionType.FEATURED_BRANDS:
            site_settings = get_site_settings()
            if not getattr(site_settings, "enable_brands", True):
                if not (
                    self.instance
                    and self.instance.pk
                    and self.instance.section_type == HomepageSectionType.FEATURED_BRANDS
                ):
                    self.add_error("section_type", "Brands are currently disabled in site settings.")
        elif section_type == HomepageSectionType.NEWSLETTER:
            site_settings = get_site_settings()
            if not getattr(site_settings, "enable_newsletter", True):
                if not (
                    self.instance
                    and self.instance.pk
                    and self.instance.section_type == HomepageSectionType.NEWSLETTER
                ):
                    self.add_error("section_type", "Newsletter is currently disabled in site settings.")

        prefix = "config_"
        config_data = {}
        for key in self.fields:
            if key.startswith(prefix):
                config_data[key[len(prefix) :]] = cleaned.get(key)

        config_files = {}
        if hasattr(self, "files") and self.files:
            config_files = {
                key[len(prefix) :]: value
                for key, value in self.files.items()
                if key.startswith(prefix)
            }
        initial_config = self.instance.config if (self.instance and self.instance.pk) else {}
        base_form = get_section_config_form(
            section_type=section_type,
            initial=initial_config,
        )
        form_class = type(base_form)
        self.config_form = form_class(
            data=config_data,
            files=config_files,
            initial=base_form.initial,
        )
        if not self.config_form.is_valid():
            raise forms.ValidationError(self.config_form.errors)
        cleaned["config"] = config_from_form(section_type=section_type, form=self.config_form)
        return cleaned


    def save(self, commit: bool = True) -> HomepageSection:
        instance = super().save(commit=False)
        if "config" in self.cleaned_data:
            instance.config = self.cleaned_data["config"]
        if commit:
            instance.save()
        return instance

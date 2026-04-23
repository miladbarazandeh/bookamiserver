from django.views.generic import TemplateView


class LandingView(TemplateView):
    template_name = "index.html"


class TermsView(TemplateView):
    template_name = "terms.html"


class PrivacyView(TemplateView):
    template_name = "privacy.html"

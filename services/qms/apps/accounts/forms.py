from django import forms


class ProfileForm(forms.Form):
    """Личные данные - половина в User, половина в UserProfile.

    Одна форма на две модели, а не две формы рядом: для человека это одна
    карточка «кто я», и разделять её по границе таблиц не за чем.
    """

    first_name = forms.CharField(label="Имя", max_length=150, required=False)
    last_name = forms.CharField(label="Фамилия", max_length=150, required=False)
    email = forms.EmailField(label="Почта", required=False)
    phone = forms.CharField(label="Телефон", max_length=64, required=False)

    @classmethod
    def for_user(cls, user, data=None):
        profile = getattr(user, "profile", None)
        initial = {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "phone": getattr(profile, "phone", ""),
        }
        return cls(data=data, initial=initial)

    def save(self, user):
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        user.save(update_fields=["first_name", "last_name", "email"])
        profile = getattr(user, "profile", None)
        if profile is not None:
            profile.phone = self.cleaned_data["phone"]
            profile.save(update_fields=["phone"])
        return user

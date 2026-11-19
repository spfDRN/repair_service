from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator

from .models import (
    Client,
    Device,
    Diagnosis,
    Part,
    RepairJob,
    RepairRequest,
    RequestPhoto,
    PHOTO_EXTENSIONS,
    validate_photo_size,
)


def photo_field(required=True):
    return forms.ImageField(
        label="Фото неисправности", required=required,
        validators=[FileExtensionValidator(PHOTO_EXTENSIONS), validate_photo_size],
        help_text="JPG или PNG, не более 5 МБ",
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png"}),
    )


def check_photo_format(image):
    if image is not None and getattr(image, "image", None) is not None:
        if image.image.format not in ("JPEG", "PNG"):
            raise forms.ValidationError("Допустимы только файлы JPG и PNG")
    return image


class PhotoForm(forms.Form):
    image = photo_field()

    def clean_image(self):
        return check_photo_format(self.cleaned_data["image"])


class RegisterForm(UserCreationForm):
    full_name = forms.CharField(label="ФИО", max_length=150)
    email = forms.EmailField(label="Email")
    phone = forms.CharField(label="Телефон", max_length=20)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "full_name", "email", "phone")

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Пользователь с таким email уже зарегистрирован")
        return email

    def clean_phone(self):
        phone = self.cleaned_data["phone"]
        if Client.objects.filter(phone=phone).exists():
            raise forms.ValidationError("Клиент с таким телефоном уже зарегистрирован")
        return phone

    def save(self, commit=True):
        user = super().save(commit=False)
        name_parts = self.cleaned_data["full_name"].split()
        user.last_name = name_parts[0] if name_parts else ""
        user.first_name = " ".join(name_parts[1:])
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
            Client.objects.create(
                user=user,
                full_name=self.cleaned_data["full_name"],
                phone=self.cleaned_data["phone"],
            )
        return user


class NewOrderForm(forms.Form):
    device = forms.ModelChoiceField(
        label="Устройство", queryset=Device.objects.none(), required=False,
        empty_label="— новое устройство —",
    )
    device_type = forms.ChoiceField(
        label="Тип устройства", choices=Device.DeviceType.choices, required=False,
    )
    brand = forms.CharField(label="Производитель", max_length=100, required=False)
    model = forms.CharField(label="Модель", max_length=100, required=False)
    serial_number = forms.CharField(label="Серийный номер", max_length=100, required=False)
    problem_description = forms.CharField(
        label="Описание неисправности", widget=forms.Textarea(attrs={"rows": 4}),
    )
    image = photo_field(required=False)

    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = client
        if client:
            self.fields["device"].queryset = client.devices.all()

    def clean_problem_description(self):
        value = (self.cleaned_data.get("problem_description") or "").strip()
        if not value:
            raise forms.ValidationError("Опишите неисправность")
        return value

    def clean_image(self):
        return check_photo_format(self.cleaned_data.get("image"))

    def clean(self):
        data = super().clean()
        if data.get("device"):
            return data
        if not (data.get("device_type") and data.get("brand") and data.get("model")):
            raise forms.ValidationError(
                "Выберите устройство из списка или заполните тип, производителя и модель"
            )
        return data

    def save(self, receptionist):
        data = self.cleaned_data
        device = data["device"]
        if not device:
            device = Device.objects.create(
                client=self.client,
                device_type=data["device_type"],
                brand=data["brand"],
                model=data["model"],
                serial_number=data["serial_number"] or None,
            )
        last = (
            RepairRequest.objects.order_by("-id").values_list("number", flat=True).first()
        )
        next_index = 1
        if last and last.startswith("РЗ-"):
            try:
                next_index = int(last.split("-")[-1]) + 1
            except ValueError:
                next_index = RepairRequest.objects.count() + 1
        number = f"РЗ-{next_index:07d}"
        repair_request = RepairRequest.objects.create(
            number=number,
            device=device,
            status=form_status(),
            receptionist=receptionist,
            problem_description=data["problem_description"],
        )
        if data.get("image"):
            RequestPhoto.objects.create(
                request=repair_request, image=data["image"],
                uploaded_by=self.client.user,
            )
        return repair_request


def form_status():
    from .models import RequestStatus

    return RequestStatus.objects.get(order_index=1)


class ProfileForm(forms.Form):
    full_name = forms.CharField(label="ФИО", max_length=150)
    phone = forms.CharField(label="Телефон", max_length=20)
    email = forms.EmailField(label="Email")

    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = client
        if client:
            self.fields["full_name"].initial = client.full_name
            self.fields["phone"].initial = client.phone
            self.fields["email"].initial = client.user.email

    def clean_phone(self):
        phone = self.cleaned_data["phone"]
        other = Client.objects.filter(phone=phone).exclude(pk=self.client.pk)
        if other.exists():
            raise forms.ValidationError("Клиент с таким телефоном уже зарегистрирован")
        return phone

    def save(self):
        self.client.full_name = self.cleaned_data["full_name"]
        self.client.phone = self.cleaned_data["phone"]
        self.client.save(update_fields=["full_name", "phone"])
        user = self.client.user
        user.email = self.cleaned_data["email"]
        user.save(update_fields=["email"])
        return self.client


class DiagnosisForm(forms.ModelForm):
    class Meta:
        model = Diagnosis
        fields = ("findings", "estimated_hours")
        widgets = {"findings": forms.Textarea(attrs={"rows": 4})}


class JobForm(forms.ModelForm):
    class Meta:
        model = RepairJob
        fields = ("name", "price", "hours")


class PartWriteOffForm(forms.Form):
    part = forms.ModelChoiceField(label="Запчасть", queryset=Part.objects.all())
    quantity = forms.IntegerField(label="Количество", min_value=1)

    def clean(self):
        data = super().clean()
        part = data.get("part")
        quantity = data.get("quantity")
        if part and quantity and part.stock_quantity < quantity:
            raise forms.ValidationError(
                f"На складе только {part.stock_quantity} шт. «{part.name}»"
            )
        return data


class AssignForm(forms.Form):
    master = forms.ModelChoiceField(
        label="Мастер",
        queryset=None,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Employee

        self.fields["master"].queryset = Employee.objects.filter(
            role=Employee.Role.MASTER
        ).select_related("user")


class TrackForm(forms.Form):
    number = forms.CharField(label="Номер заявки", max_length=20)

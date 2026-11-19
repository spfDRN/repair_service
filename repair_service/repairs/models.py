import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Employee(models.Model):

    class Role(models.TextChoices):
        MASTER = "master", "Мастер"
        RECEPTIONIST = "receptionist", "Приёмщик"
        ADMIN = "admin", "Администратор"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="пользователь",
        related_name="employee_profile",
        on_delete=models.CASCADE,
    )
    role = models.CharField(
        "роль", max_length=20, choices=Role.choices, db_index=True
    )
    specialization = models.CharField(
        "специализация", max_length=150, blank=True,
        help_text="Например: ремонт ноутбуков, пайка плат",
    )
    phone = models.CharField("телефон", max_length=20, blank=True)

    class Meta:
        verbose_name = "сотрудник"
        verbose_name_plural = "сотрудники"
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.get_role_display()})"


class Client(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="пользователь",
        related_name="client_profile",
        on_delete=models.CASCADE,
    )
    full_name = models.CharField("ФИО", max_length=150)
    phone = models.CharField("телефон", max_length=20, unique=True)
    created_at = models.DateTimeField("дата регистрации", auto_now_add=True)

    class Meta:
        verbose_name = "клиент"
        verbose_name_plural = "клиенты"
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class Device(models.Model):
    class DeviceType(models.TextChoices):
        SMARTPHONE = "smartphone", "Смартфон"
        LAPTOP = "laptop", "Ноутбук"
        TABLET = "tablet", "Планшет"
        APPLIANCE = "appliance", "Бытовая техника"
        OTHER = "other", "Другое"

    client = models.ForeignKey(
        Client, verbose_name="клиент", related_name="devices",
        on_delete=models.CASCADE,
    )
    device_type = models.CharField(
        "тип устройства", max_length=20, choices=DeviceType.choices,
    )
    brand = models.CharField("производитель", max_length=100)
    model = models.CharField("модель", max_length=100)
    serial_number = models.CharField(
        "серийный номер", max_length=100, blank=True, null=True,
    )
    description = models.TextField("особые приметы", blank=True)
    created_at = models.DateTimeField("добавлено", auto_now_add=True)

    class Meta:
        verbose_name = "устройство"
        verbose_name_plural = "устройства"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "model", "serial_number"],
                name="uniq_device_brand_model_serial",
                condition=models.Q(serial_number__isnull=False),
            ),
        ]

    def __str__(self):
        return f"{self.brand} {self.model} ({self.client.full_name})"


class RequestStatus(models.Model):
    name = models.CharField("название", max_length=50, unique=True)
    order_index = models.PositiveSmallIntegerField(
        "порядок этапа", unique=True,
        help_text="Определяет последовательность статусов в процессе",
    )
    is_final = models.BooleanField("финальный статус", default=False)

    class Meta:
        verbose_name = "статус заявки"
        verbose_name_plural = "статусы заявок"
        ordering = ["order_index"]

    def __str__(self):
        return self.name


class RepairRequest(models.Model):
    number = models.CharField("номер заявки", max_length=20, unique=True)
    device = models.ForeignKey(
        Device, verbose_name="устройство", related_name="requests",
        on_delete=models.PROTECT,
    )
    status = models.ForeignKey(
        RequestStatus, verbose_name="статус", related_name="requests",
        on_delete=models.PROTECT,
    )
    receptionist = models.ForeignKey(
        Employee, verbose_name="приёмщик", related_name="accepted_requests",
        on_delete=models.PROTECT,
        limit_choices_to={"role": Employee.Role.RECEPTIONIST},
    )
    master = models.ForeignKey(
        Employee, verbose_name="мастер", related_name="assigned_requests",
        on_delete=models.PROTECT, null=True, blank=True,
        limit_choices_to={"role": Employee.Role.MASTER},
    )
    problem_description = models.TextField("жалоба клиента")
    estimate_total = models.DecimalField(
        "итоговая смета, руб.", max_digits=10, decimal_places=2,
        null=True, blank=True,
        validators=[MinValueValidator(0)],
    )
    client_confirmed = models.BooleanField("смета подтверждена клиентом", default=False)
    client_confirmed_at = models.DateTimeField(
        "дата подтверждения сметы", null=True, blank=True,
    )
    created_at = models.DateTimeField("дата приёма", auto_now_add=True)
    closed_at = models.DateTimeField("дата выдачи", null=True, blank=True)

    class Meta:
        verbose_name = "заявка на ремонт"
        verbose_name_plural = "заявки на ремонт"
        ordering = ["-created_at"]

    def __str__(self):
        return self.number

    def recalc_estimate(self):
        jobs_total = self.jobs.aggregate(s=models.Sum("price"))["s"] or 0
        parts_total = (
            PartUsage.objects.filter(job__request=self).aggregate(
                s=models.Sum(
                    models.F("quantity") * models.F("price_at_write_off"),
                    output_field=models.DecimalField(max_digits=10, decimal_places=2),
                )
            )["s"]
            or 0
        )
        self.estimate_total = jobs_total + parts_total
        self.save(update_fields=["estimate_total"])
        return self.estimate_total


class Diagnosis(models.Model):

    request = models.OneToOneField(
        RepairRequest, verbose_name="заявка", related_name="diagnosis",
        on_delete=models.CASCADE,
    )
    master = models.ForeignKey(
        Employee, verbose_name="мастер", related_name="diagnoses",
        on_delete=models.PROTECT,
        limit_choices_to={"role": Employee.Role.MASTER},
    )
    findings = models.TextField("выявленная неисправность")
    estimated_hours = models.DecimalField(
        "ориентировочная трудоёмкость, ч", max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    created_at = models.DateTimeField("дата диагностики", auto_now_add=True)

    class Meta:
        verbose_name = "диагностика"
        verbose_name_plural = "диагностики"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Диагностика по {self.request.number}"


class RepairJob(models.Model):

    request = models.ForeignKey(
        RepairRequest, verbose_name="заявка", related_name="jobs",
        on_delete=models.CASCADE,
    )
    master = models.ForeignKey(
        Employee, verbose_name="мастер", related_name="performed_jobs",
        on_delete=models.PROTECT,
        limit_choices_to={"role": Employee.Role.MASTER},
    )
    name = models.CharField("наименование работы", max_length=150)
    price = models.DecimalField(
        "стоимость работы, руб.", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    hours = models.DecimalField(
        "затраченное время, ч", max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    parts = models.ManyToManyField(
        "Part", verbose_name="запчасти", through="PartUsage",
        related_name="jobs", blank=True,
    )
    performed_at = models.DateTimeField("дата выполнения", null=True, blank=True)

    class Meta:
        verbose_name = "выполненная работа"
        verbose_name_plural = "выполненные работы"
        ordering = ["-performed_at"]

    def __str__(self):
        return f"{self.name} ({self.request.number})"


class Part(models.Model):

    name = models.CharField("наименование", max_length=150)
    sku = models.CharField("артикул", max_length=50, unique=True)
    unit_price = models.DecimalField(
        "цена за единицу, руб.", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    stock_quantity = models.PositiveIntegerField("остаток на складе", default=0)

    class Meta:
        verbose_name = "запчасть"
        verbose_name_plural = "запчасти"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.sku})"


class PartUsage(models.Model):
    job = models.ForeignKey(
        RepairJob, verbose_name="работа", related_name="part_usages",
        on_delete=models.CASCADE,
    )
    part = models.ForeignKey(
        Part, verbose_name="запчасть", related_name="usages",
        on_delete=models.PROTECT,
    )
    quantity = models.PositiveIntegerField(
        "количество", validators=[MinValueValidator(1)],
    )
    price_at_write_off = models.DecimalField(
        "цена на момент списания, руб.", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        verbose_name = "расход запчасти"
        verbose_name_plural = "расход запчастей"
        constraints = [
            models.UniqueConstraint(
                fields=["job", "part"], name="uniq_job_part",
            ),
        ]

    def __str__(self):
        return f"{self.part.name} x{self.quantity} ({self.job.name})"


class WarrantyCard(models.Model):
    request = models.OneToOneField(
        RepairRequest, verbose_name="заявка", related_name="warranty_card",
        on_delete=models.CASCADE,
    )
    number = models.CharField("номер талона", max_length=30, unique=True)
    issued_at = models.DateField("дата выдачи", default=timezone.now)
    valid_months = models.PositiveSmallIntegerField("срок гарантии, мес.", default=3)
    terms = models.TextField("условия гарантии", blank=True)

    class Meta:
        verbose_name = "гарантийный талон"
        verbose_name_plural = "гарантийные талоны"
        ordering = ["-issued_at"]

    def __str__(self):
        return self.number


MAX_PHOTO_SIZE = 5 * 1024 * 1024
PHOTO_EXTENSIONS = ["jpg", "jpeg", "png"]


def validate_photo_size(file):
    if file.size > MAX_PHOTO_SIZE:
        raise ValidationError("Размер фото не должен превышать 5 МБ")


def photo_upload_to(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"request_photos/{instance.request_id}/{uuid.uuid4().hex}{extension}"


class RequestPhoto(models.Model):
    request = models.ForeignKey(
        RepairRequest, verbose_name="заявка", related_name="photos",
        on_delete=models.CASCADE,
    )
    image = models.ImageField(
        "фото", upload_to=photo_upload_to,
        validators=[FileExtensionValidator(PHOTO_EXTENSIONS), validate_photo_size],
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="загрузил",
        related_name="request_photos", on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    uploaded_at = models.DateTimeField("дата загрузки", auto_now_add=True)

    class Meta:
        verbose_name = "фото заявки"
        verbose_name_plural = "фото заявок"
        ordering = ["uploaded_at"]

    def __str__(self):
        return f"Фото {self.request.number}"
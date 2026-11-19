from django.contrib import admin

from .models import (
    Client,
    Device,
    Diagnosis,
    Employee,
    Part,
    PartUsage,
    RepairJob,
    RepairRequest,
    RequestPhoto,
    RequestStatus,
    WarrantyCard,
)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "created_at")
    search_fields = ("full_name", "phone")


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("brand", "model", "client", "device_type", "created_at")
    list_filter = ("device_type",)
    search_fields = ("brand", "model", "serial_number")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "specialization", "phone")
    list_filter = ("role",)


@admin.register(RequestStatus)
class RequestStatusAdmin(admin.ModelAdmin):
    list_display = ("name", "order_index", "is_final")


class PartUsageInline(admin.TabularInline):
    model = PartUsage
    extra = 0


@admin.register(RepairJob)
class RepairJobAdmin(admin.ModelAdmin):
    list_display = ("name", "request", "master", "price", "hours", "performed_at")
    inlines = [PartUsageInline]


class RepairJobInline(admin.TabularInline):
    model = RepairJob
    extra = 0


class RequestPhotoInline(admin.TabularInline):
    model = RequestPhoto
    extra = 0


@admin.register(RepairRequest)
class RepairRequestAdmin(admin.ModelAdmin):
    list_display = (
        "number", "device", "status", "receptionist", "master",
        "estimate_total", "client_confirmed", "created_at",
    )
    list_filter = ("status", "client_confirmed")
    search_fields = ("number",)
    inlines = [RepairJobInline, RequestPhotoInline]


@admin.register(Diagnosis)
class DiagnosisAdmin(admin.ModelAdmin):
    list_display = ("request", "master", "estimated_hours", "created_at")


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "unit_price", "stock_quantity")
    search_fields = ("name", "sku")


@admin.register(PartUsage)
class PartUsageAdmin(admin.ModelAdmin):
    list_display = ("job", "part", "quantity", "price_at_write_off")


@admin.register(WarrantyCard)
class WarrantyCardAdmin(admin.ModelAdmin):
    list_display = ("number", "request", "issued_at", "valid_months")
import csv
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, DecimalField, F, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services as services_module
from .forms import (
    AssignForm,
    DiagnosisForm,
    JobForm,
    NewOrderForm,
    PhotoForm,
    PartWriteOffForm,
    ProfileForm,
    RegisterForm,
    TrackForm,
)
from .models import (
    Client,
    Device,
    Diagnosis,
    Employee,
    Part,
    RepairJob,
    RepairRequest,
    RequestPhoto,
    RequestStatus,
    WarrantyCard,
)


def client_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not hasattr(request.user, "client_profile"):
            raise PermissionDenied("Раздел доступен только клиентам")
        return view(request, *args, **kwargs)

    return wrapper


def staff_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            employee = getattr(request.user, "employee_profile", None)
            if employee is None or (roles and employee.role not in roles):
                raise PermissionDenied("Недостаточно прав для этого раздела")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def master_can_edit(request, repair_request):
    employee = request.user.employee_profile
    return employee.role == Employee.Role.ADMIN or repair_request.master_id == employee.pk


def home(request):
    return render(request, "home.html")


def services_page(request):
    return render(request, "services.html")


def about(request):
    return render(request, "about.html")


def contacts(request):
    return render(request, "contacts.html")


def track(request):
    form = TrackForm(request.GET or None)
    found = None
    if form.is_valid():
        found = RepairRequest.objects.filter(
            number__iexact=form.cleaned_data["number"].strip()
        ).first()
        if found is None:
            messages.error(request, "Заявка с таким номером не найдена")
    return render(request, "track.html", {"form": form, "found": found})


def track_detail(request, number):
    repair_request = get_object_or_404(
        RepairRequest.objects.select_related("status", "device", "master__user"),
        number__iexact=number,
    )
    return render(request, "track_detail.html", {"request_obj": repair_request})


def register(request):
    if request.user.is_authenticated:
        return redirect("after_login")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Регистрация завершена. Добро пожаловать!")
        return redirect("cabinet")
    return render(request, "registration/register.html", {"form": form})


def after_login(request):
    if not request.user.is_authenticated:
        return redirect("login")
    if hasattr(request.user, "employee_profile"):
        return redirect("staff_orders")
    return redirect("cabinet")


@client_required
def dashboard(request):
    client = request.user.client_profile
    orders = RepairRequest.objects.filter(device__client=client).select_related(
        "status", "device"
    )
    return render(
        request,
        "cabinet/dashboard.html",
        {
            "orders": orders[:5],
            "orders_count": orders.count(),
            "devices_count": client.devices.count(),
            "warranty_count": WarrantyCard.objects.filter(
                request__device__client=client
            ).count(),
        },
    )


@client_required
def order_list(request):
    client = request.user.client_profile
    orders = RepairRequest.objects.filter(device__client=client).select_related(
        "status", "device", "master__user"
    )
    return render(request, "cabinet/orders.html", {"orders": orders})


@client_required
def order_new(request):
    client = request.user.client_profile
    receptionist = (
        Employee.objects.filter(role=Employee.Role.RECEPTIONIST).first()
        or Employee.objects.filter(role=Employee.Role.ADMIN).first()
    )
    form = NewOrderForm(request.POST or None, request.FILES or None, client=client)
    if request.method == "POST" and form.is_valid():
        if receptionist is None:
            messages.error(request, "В сервисе пока нет приёмщика, обратитесь по телефону")
        else:
            repair_request = form.save(receptionist)
            messages.success(request, f"Заявка {repair_request.number} создана")
            return redirect("cabinet_order", pk=repair_request.pk)
    return render(request, "cabinet/order_form.html", {"form": form})


@client_required
def order_detail(request, pk):
    client = request.user.client_profile
    repair_request = get_object_or_404(
        RepairRequest.objects.select_related("status", "device", "master__user"),
        pk=pk,
    )
    if repair_request.device.client_id != client.pk:
        raise PermissionDenied("Заявка принадлежит другому клиенту")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "photo":
            try:
                _save_photo(request, repair_request)
            except ValueError as error:
                messages.error(request, str(error))
            else:
                messages.success(request, "Фото загружено")
            return redirect("cabinet_order", pk=pk)
        if action in {"confirm", "reject"}:
            try:
                services_module.confirm_estimate(
                    repair_request, confirmed=action == "confirm"
                )
            except ValueError as error:
                messages.error(request, str(error))
            else:
                messages.success(
                    request,
                    "Смета подтверждена, ремонт начинается"
                    if action == "confirm"
                    else "Смета отклонена",
                )
            return redirect("cabinet_order", pk=pk)

    usages = (
        repair_request.jobs.prefetch_related("part_usages__part")
        .select_related("master__user")
    )
    return render(
        request,
        "cabinet/order_detail.html",
        {
            "request_obj": repair_request,
            "jobs": usages,
            "photos": repair_request.photos.all(),
            "photo_form": PhotoForm(),
            "warranty": getattr(repair_request, "warranty_card", None),
        },
    )


@client_required
def devices(request):
    client = request.user.client_profile
    return render(request, "cabinet/devices.html", {"devices": client.devices.all()})


@client_required
def warranty(request):
    client = request.user.client_profile
    cards = WarrantyCard.objects.filter(
        request__device__client=client
    ).select_related("request__device")
    return render(request, "cabinet/warranty.html", {"cards": cards})


@client_required
def profile(request):
    client = request.user.client_profile
    form = ProfileForm(request.POST or None, client=client)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Профиль сохранён")
        return redirect("cabinet_profile")
    return render(request, "cabinet/profile.html", {"form": form})


class CabinetPasswordChangeView(PasswordChangeView):
    template_name = "cabinet/password_change.html"
    success_url = reverse_lazy("cabinet_profile")

    def form_valid(self, form):
        messages.success(self.request, "Пароль изменён")
        return super().form_valid(form)


@staff_required(Employee.Role.MASTER, Employee.Role.RECEPTIONIST, Employee.Role.ADMIN)
def staff_orders(request):
    employee = request.user.employee_profile
    orders = RepairRequest.objects.select_related(
        "status", "device__client", "master__user", "receptionist__user"
    )

    if employee.role == Employee.Role.MASTER:
        orders = orders.filter(master=employee)

    query = (request.GET.get("q") or "").strip()
    if query:
        orders = orders.filter(
            Q(number__icontains=query)
            | Q(device__brand__icontains=query)
            | Q(device__model__icontains=query)
            | Q(device__client__full_name__icontains=query)
            | Q(device__client__phone__icontains=query)
        )

    status_id = request.GET.get("status")
    if status_id:
        orders = orders.filter(status_id=status_id)

    device_type = request.GET.get("device_type")
    if device_type:
        orders = orders.filter(device__device_type=device_type)

    master_id = request.GET.get("master")
    if master_id:
        orders = orders.filter(master_id=master_id)

    sort = request.GET.get("sort", "-created_at")
    allowed_sorts = {
        "-created_at": "-created_at",
        "created_at": "created_at",
        "number": "number",
        "-number": "-number",
        "estimate_total": "estimate_total",
        "-estimate_total": "-estimate_total",
    }
    orders = orders.order_by(allowed_sorts.get(sort, "-created_at"))

    page_obj = _paginate(request, orders, 20)

    query_params = request.GET.copy()
    query_params.pop("page", None)

    return render(
        request,
        "staff/orders.html",
        {
            "page_obj": page_obj,
            "statuses": RequestStatus.objects.all(),
            "device_types": Device.DeviceType.choices,
            "masters": Employee.objects.filter(role=Employee.Role.MASTER).select_related("user"),
            "query": query,
            "selected_status": status_id or "",
            "selected_device_type": device_type or "",
            "selected_master": master_id or "",
            "sort": sort,
            "querystring": query_params.urlencode(),
        },
    )


def _paginate(request, queryset, per_page):
    from django.core.paginator import Paginator

    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


@staff_required(Employee.Role.RECEPTIONIST, Employee.Role.ADMIN)
def staff_export(request):
    orders = RepairRequest.objects.select_related(
        "status", "device__client", "master__user"
    ).order_by("-created_at")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="requests.csv"'
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(
        ["Номер", "Клиент", "Телефон", "Устройство", "Статус", "Мастер", "Смета", "Создана"]
    )
    for order in orders:
        writer.writerow(
            [
                order.number,
                order.device.client.full_name,
                order.device.client.phone,
                f"{order.device.brand} {order.device.model}",
                order.status.name,
                order.master.user.get_full_name() if order.master else "",
                order.estimate_total or 0,
                order.created_at.strftime("%d.%m.%Y"),
            ]
        )
    return response


@staff_required(Employee.Role.MASTER, Employee.Role.RECEPTIONIST, Employee.Role.ADMIN)
def staff_order(request, pk):
    repair_request = get_object_or_404(
        RepairRequest.objects.select_related(
            "status", "device__client", "master__user", "receptionist__user"
        ),
        pk=pk,
    )
    employee = request.user.employee_profile
    if employee.role == Employee.Role.MASTER and repair_request.master_id != employee.pk:
        raise PermissionDenied("Заявка назначена другому мастеру")

    diagnosis_form = DiagnosisForm(
        instance=getattr(repair_request, "diagnosis", None)
    )
    job_form = JobForm()
    part_form = PartWriteOffForm()

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "diagnosis":
                _save_diagnosis(request, repair_request, employee)
            elif action == "job":
                _add_job(request, repair_request, employee)
            elif action == "part":
                _write_off(request, repair_request)
            elif action == "estimate":
                if repair_request.status.order_index < 2:
                    raise ValueError("Сначала проведите диагностику")
                if not repair_request.jobs.exists():
                    raise ValueError("Добавьте хотя бы одну работу")
                repair_request.recalc_estimate()
                services_module.change_status(repair_request, 3)
                messages.success(request, "Смета отправлена клиенту")
            elif action == "ready":
                if not repair_request.client_confirmed:
                    raise ValueError("Клиент ещё не подтвердил смету")
                services_module.change_status(repair_request, 5)
                messages.success(request, "Заявка готова к выдаче")
            elif action == "issue":
                card = services_module.issue_device(repair_request)
                messages.success(request, f"Устройство выдано, гарантийный талон {card.number}")
            elif action == "photo":
                _save_photo(request, repair_request)
                messages.success(request, "Фото загружено")
            elif action == "start":
                services_module.change_status(repair_request, 2)
                messages.success(request, "Диагностика начата")
            else:
                raise ValueError("Неизвестное действие")
        except ValueError as error:
            messages.error(request, str(error))
        return redirect("staff_order", pk=pk)

    return render(
        request,
        "staff/order_detail.html",
        {
            "request_obj": repair_request,
            "diagnosis_form": diagnosis_form,
            "job_form": job_form,
            "part_form": part_form,
            "jobs": repair_request.jobs.select_related("master__user").prefetch_related(
                "part_usages__part"
            ),
            "parts": Part.objects.all(),
            "photos": repair_request.photos.all(),
            "photo_form": PhotoForm(),
            "warranty": getattr(repair_request, "warranty_card", None),
            "can_edit": master_can_edit(request, repair_request),
            "is_receptionist": employee.role
            in {Employee.Role.RECEPTIONIST, Employee.Role.ADMIN},
        },
    )


def _save_photo(request, repair_request):
    form = PhotoForm(request.POST, request.FILES)
    if not form.is_valid():
        raise ValueError("; ".join(form.errors["image"]))
    RequestPhoto.objects.create(
        request=repair_request,
        image=form.cleaned_data["image"],
        uploaded_by=request.user,
    )


def _save_diagnosis(request, repair_request, employee):
    if employee.role == Employee.Role.RECEPTIONIST:
        raise ValueError("Диагностику заполняет мастер")
    form = DiagnosisForm(request.POST, instance=getattr(repair_request, "diagnosis", None))
    if not form.is_valid():
        raise ValueError("Проверьте поля диагностики")
    diagnosis = form.save(commit=False)
    diagnosis.request = repair_request
    diagnosis.master = employee
    diagnosis.save()
    if repair_request.status.order_index == 1:
        services_module.change_status(repair_request, 2)
    messages.success(request, "Диагностика сохранена")


def _add_job(request, repair_request, employee):
    if employee.role == Employee.Role.RECEPTIONIST:
        raise ValueError("Работы добавляет мастер")
    form = JobForm(request.POST)
    if not form.is_valid():
        raise ValueError("Проверьте поля работы")
    job = form.save(commit=False)
    job.request = repair_request
    job.master = employee
    job.performed_at = timezone.now()
    job.save()
    repair_request.recalc_estimate()
    messages.success(request, "Работа добавлена")


def _write_off(request, repair_request):
    form = PartWriteOffForm(request.POST)
    if not form.is_valid():
        raise ValueError("Выберите запчасть и количество")
    job_id = request.POST.get("job")
    job = get_object_or_404(RepairJob, pk=job_id, request=repair_request)
    services_module.write_off_part(job, form.cleaned_data["part"], form.cleaned_data["quantity"])
    messages.success(request, "Запчасть списана со склада")


@staff_required(Employee.Role.RECEPTIONIST, Employee.Role.ADMIN)
def staff_assign(request, pk):
    repair_request = get_object_or_404(RepairRequest, pk=pk)
    form = AssignForm(request.POST or None, initial={"master": repair_request.master})
    if request.method == "POST" and form.is_valid():
        repair_request.master = form.cleaned_data["master"]
        repair_request.save(update_fields=["master"])
        messages.success(request, "Мастер назначен")
        return redirect("staff_order", pk=pk)
    return render(
        request,
        "staff/assign.html",
        {"form": form, "request_obj": repair_request},
    )


@staff_required(Employee.Role.ADMIN)
def staff_dashboard(request):
    orders = RepairRequest.objects.all()
    total = orders.count()
    revenue = orders.filter(status__order_index=6).aggregate(
        total=Coalesce(
            Sum("estimate_total"),
            0,
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
    )["total"]
    average = orders.filter(status__order_index=6).aggregate(
        value=Coalesce(
            Avg("estimate_total"),
            0,
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
    )["value"]
    warranty_count = WarrantyCard.objects.count()
    by_status = (
        RequestStatus.objects.annotate(requests_count=Count("requests"))
        .order_by("order_index")
    )
    max_count = max([row.requests_count for row in by_status] or [1]) or 1
    chart = [
        {
            "name": row.name,
            "count": row.requests_count,
            "width": round(row.requests_count * 100 / max_count),
        }
        for row in by_status
    ]
    warranty_share = round(warranty_count * 100 / total) if total else 0
    return render(
        request,
        "staff/dashboard.html",
        {
            "total": total,
            "revenue": revenue,
            "average": average,
            "warranty_count": warranty_count,
            "warranty_share": warranty_share,
            "chart": chart,
        },
    )


@login_required
def status_json(request, pk):
    repair_request = get_object_or_404(RepairRequest.objects.select_related("status"), pk=pk)
    if not request.user.is_authenticated:
        raise PermissionDenied("Требуется вход")
    employee = getattr(request.user, "employee_profile", None)
    if employee is None:
        client = getattr(request.user, "client_profile", None)
        if client is None or repair_request.device.client_id != client.pk:
            raise PermissionDenied("Заявка принадлежит другому клиенту")
    elif employee.role == Employee.Role.MASTER and repair_request.master_id != employee.pk:
        raise PermissionDenied("Заявка назначена другому мастеру")
    return JsonResponse(
        {
            "number": repair_request.number,
            "status": repair_request.status.name,
            "order_index": repair_request.status.order_index,
            "estimate_total": str(repair_request.estimate_total or 0),
            "client_confirmed": repair_request.client_confirmed,
        }
    )

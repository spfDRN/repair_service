from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import Part, PartUsage, RepairRequest, RequestStatus, WarrantyCard


def notify_status_change(request: RepairRequest):
    email = request.device.client.user.email
    if not email:
        return
    subject = f"Статус заявки {request.number}"
    message = (
        f"Здравствуйте, {request.device.client.full_name}!\n\n"
        f"Статус вашей заявки {request.number} изменён: {request.status.name}.\n"
        f"Устройство: {request.device.brand} {request.device.model}.\n\n"
        "С уважением, сервисный центр РемТех."
    )
    send_mail(subject, message, None, [email], fail_silently=True)


@transaction.atomic
def write_off_part(job, part: Part, quantity: int):
    part = Part.objects.select_for_update().get(pk=part.pk)
    if part.stock_quantity < quantity:
        raise ValueError("Недостаточно запчастей на складе")

    PartUsage.objects.create(
        job=job, part=part, quantity=quantity, price_at_write_off=part.unit_price,
    )
    part.stock_quantity -= quantity
    part.save(update_fields=["stock_quantity"])

    job.request.recalc_estimate()


@transaction.atomic
def confirm_estimate(request: RepairRequest, confirmed: bool):
    request = RepairRequest.objects.select_for_update().get(pk=request.pk)
    if request.status.order_index != 3:
        raise ValueError("Смета не ожидает подтверждения клиентом")

    request.client_confirmed = confirmed
    request.client_confirmed_at = timezone.now()
    request.status = RequestStatus.objects.get(
        order_index=4 if confirmed else 7  # «В работе» / «Отклонена клиентом»
    )
    request.save(update_fields=["client_confirmed", "client_confirmed_at", "status"])
    notify_status_change(request)
    return request


@transaction.atomic
def change_status(request: RepairRequest, order_index: int, **extra_fields):
    request = RepairRequest.objects.select_for_update().get(pk=request.pk)
    request.status = RequestStatus.objects.get(order_index=order_index)
    for field, value in extra_fields.items():
        setattr(request, field, value)
    request.save(update_fields=["status", *extra_fields.keys()])
    notify_status_change(request)
    return request


@transaction.atomic
def issue_device(request: RepairRequest):
    request = RepairRequest.objects.select_for_update().get(pk=request.pk)
    if request.status.order_index != 5:
        raise ValueError("Выдать можно только готовую к выдаче заявку")
    if not request.client_confirmed:
        raise ValueError("Смета не подтверждена клиентом")

    has_jobs = request.jobs.exists()
    card, created = WarrantyCard.objects.get_or_create(
        request=request,
        defaults={
            "number": f"ГТ-{request.number.split("-")[-1]}",
            "valid_months": 12 if has_jobs else 3,
        },
    )
    request.status = RequestStatus.objects.get(order_index=6)
    request.closed_at = timezone.now()
    request.save(update_fields=["status", "closed_at"])
    notify_status_change(request)
    return card

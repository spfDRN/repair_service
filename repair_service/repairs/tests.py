from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from . import services
from .models import (
    Client, Device, Employee, Part, RepairJob, RepairRequest, RequestStatus,
)


class BaseCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        names = ["Новая", "Диагностика", "Ожидает подтверждения сметы", "В работе",
                 "Готова к выдаче", "Выдана", "Отклонена клиентом"]
        cls.statuses = {
            index: RequestStatus.objects.create(
                name=name, order_index=index, is_final=index in (6, 7)
            )
            for index, name in enumerate(names, start=1)
        }
        cls.users = {}
        for key in ("c1", "c2", "m1", "m2", "r"):
            cls.users[key] = User.objects.create_user(key, f"{key}@x.ru", "pass12345")
        cls.client1 = Client.objects.create(user=cls.users["c1"], full_name="К1", phone="+70000000001")
        cls.client2 = Client.objects.create(user=cls.users["c2"], full_name="К2", phone="+70000000002")
        cls.master1 = Employee.objects.create(user=cls.users["m1"], role="master")
        cls.master2 = Employee.objects.create(user=cls.users["m2"], role="master")
        cls.recept = Employee.objects.create(user=cls.users["r"], role="receptionist")
        cls.device = Device.objects.create(client=cls.client1, device_type="laptop", brand="A", model="B")
        cls.part = Part.objects.create(name="Экран", sku="S1", unit_price=Decimal("100"), stock_quantity=5)

    def make_request(self, status=1, number="РЗ-2026-001", master=None):
        return RepairRequest.objects.create(
            number=number, device=self.device, status=self.statuses[status],
            receptionist=self.recept, master=master or self.master1,
            problem_description="не включается",
        )

    def make_job(self, request):
        return RepairJob.objects.create(
            request=request, master=self.master1, name="Замена", price=Decimal("500"), hours=1,
        )


class ServicesTests(BaseCase):
    def test_write_off_reduces_stock_and_recalculates(self):
        request = self.make_request(4)
        job = self.make_job(request)
        services.write_off_part(job, self.part, 2)
        self.part.refresh_from_db()
        request.refresh_from_db()
        self.assertEqual(self.part.stock_quantity, 3)
        self.assertEqual(request.estimate_total, Decimal("700"))

    def test_write_off_insufficient_stock(self):
        job = self.make_job(self.make_request(4))
        with self.assertRaises(ValueError):
            services.write_off_part(job, self.part, 10)
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_quantity, 5)

    def test_confirm_estimate_wrong_status(self):
        with self.assertRaises(ValueError):
            services.confirm_estimate(self.make_request(2), True)

    def test_confirm_estimate_moves_to_work_or_rejected(self):
        accepted = services.confirm_estimate(self.make_request(3), True)
        self.assertEqual(accepted.status.order_index, 4)
        rejected = services.confirm_estimate(self.make_request(3, "РЗ-2026-002"), False)
        self.assertEqual(rejected.status.order_index, 7)

    def test_issue_requires_confirmation(self):
        request = self.make_request(5)
        with self.assertRaises(ValueError):
            services.issue_device(request)

    def test_issue_creates_warranty(self):
        request = self.make_request(5)
        request.client_confirmed = True
        request.save()
        card = services.issue_device(request)
        request.refresh_from_db()
        self.assertEqual(request.status.order_index, 6)
        self.assertEqual(card.request, request)


class AccessTests(BaseCase):
    def test_foreign_client_gets_403(self):
        request = self.make_request(1)
        self.client.login(username="c2", password="pass12345")
        response = self.client.get(reverse("cabinet_order", args=[request.pk]))
        self.assertEqual(response.status_code, 403)

    def test_owner_client_gets_200(self):
        request = self.make_request(1)
        self.client.login(username="c1", password="pass12345")
        response = self.client.get(reverse("cabinet_order", args=[request.pk]))
        self.assertEqual(response.status_code, 200)

    def test_foreign_master_gets_403(self):
        request = self.make_request(2)
        self.client.login(username="m2", password="pass12345")
        response = self.client.get(reverse("staff_order", args=[request.pk]))
        self.assertEqual(response.status_code, 403)

import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from .models import RequestPhoto

PHOTO_MEDIA = tempfile.mkdtemp()


def make_image(fmt="PNG", name="a.png", size=(10, 10)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, fmt)
    return SimpleUploadedFile(name, buffer.getvalue())


@override_settings(MEDIA_ROOT=PHOTO_MEDIA)
class PhotoTests(BaseCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PHOTO_MEDIA, ignore_errors=True)

    def upload(self, user, request, image):
        self.client.login(username=user, password="pass12345")
        url = reverse("cabinet_order", args=[request.pk])
        return self.client.post(url, {"action": "photo", "image": image})

    def test_valid_png_saved(self):
        request = self.make_request()
        self.upload("c1", request, make_image())
        self.assertEqual(RequestPhoto.objects.filter(request=request).count(), 1)

    def test_valid_jpg_saved(self):
        request = self.make_request()
        self.upload("c1", request, make_image("JPEG", "a.jpg"))
        self.assertEqual(RequestPhoto.objects.count(), 1)

    def test_too_large_rejected(self):
        request = self.make_request()
        big = SimpleUploadedFile("a.png", make_image().read() + b"0" * (5 * 1024 * 1024 + 1))
        self.upload("c1", request, big)
        self.assertEqual(RequestPhoto.objects.count(), 0)

    def test_bad_extension_rejected(self):
        request = self.make_request()
        self.upload("c1", request, SimpleUploadedFile("a.txt", b"hello"))
        self.assertEqual(RequestPhoto.objects.count(), 0)

    def test_foreign_request_forbidden(self):
        request = self.make_request()
        response = self.upload("c2", request, make_image())
        self.assertIn(response.status_code, (403, 404))
        self.assertEqual(RequestPhoto.objects.count(), 0)

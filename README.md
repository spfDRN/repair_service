# Сервис ремонта техники (вариант 12)

Django + SQLite, приложение `repairs`. Демо-данные уже находятся в `repair_service\db.sqlite3`.

## Запуск
```
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
cd repair_service
..\.venv\Scripts\python manage.py migrate
..\.venv\Scripts\python manage.py set_demo_passwords
..\.venv\Scripts\python manage.py runserver
```
Тесты: `python manage.py test repairs`

## Демо-логины (пароль `demo12345`)
- клиент: `ivanov.p`
- мастера: `sidorov.m`, `gavrilova.i`, `romanov.v`
- приёмщик: `pavlova.y`
- администратор: `egorov.s`

## Структура
- `repairs/models.py`, `services.py` (списание запчастей, смена статусов, выдача), `views.py`, `forms.py`, `urls.py`
- `templates/`, `static/css/style.css`

## Примечания
- `DEBUG=True` для локальной демонстрации; для продакшена выключить.
- Фото поломки (FR-19): модель `RequestPhoto`, загрузка из кабинета и карточки заявки для персонала, ограничения — JPG/PNG до 5 МБ. Файлы сохраняются в `media/`. Требуется `Pillow` (в `requirements.txt`).
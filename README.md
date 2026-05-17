# 🏗️ Telegram-бот для заказа бетона

## Структура файлов

```
concrete_bot/
├── bot.py           — основной код бота
├── config.py        — настройки (токен, ключ API, цены, тарифы)
└── requirements.txt — зависимости
```

## Как работает расчёт логистики

1. Клиент вводит адрес доставки в свободной форме
1. Бот отправляет адрес в **Yandex Geocoder API** → получает координаты (lat, lon)
1. Расстояние считается по формуле Гаверсинуса (прямое) × коэффициент 1.3 (дорожное)
1. Итоговая цена: `BASE_DELIVERY_PRICE + PRICE_PER_KM × расстояние`

## Установка и запуск

### 1. Получите токен бота

Напишите @BotFather → `/newbot` → получите токен вида `7123456789:AAF...`

### 2. Получите ключ Yandex Geocoder API

1. Перейдите на https://developer.tech.yandex.ru/
1. Создайте аккаунт и новый проект
1. Подключите **«Геокодер HTTP API»** (бесплатно до 1 000 запросов/день)
1. Скопируйте API-ключ

### 3. Узнайте координаты вашего завода

Откройте https://maps.yandex.ru/ → найдите завод → в адресной строке будут координаты:
`https://yandex.ru/maps/?ll=37.617635%2C55.755814` → lon=37.617, lat=55.755

### 4. Узнайте ваш Telegram ID

Напишите @userinfobot — он покажет ваш числовой ID.

### 5. Заполните config.py

```python
BOT_TOKEN = "7123456789:AAF..."
MANAGER_CHAT_ID = 123456789
YANDEX_GEOCODER_API_KEY = "ваш-ключ"
PLANT_ADDRESS = "г. Москва, ул. Заводская, д. 1"
PLANT_LAT = 55.7558
PLANT_LON = 37.6173
BASE_DELIVERY_PRICE = 3000   # ₽
PRICE_PER_KM = 80            # ₽/км
```

### 6. Установите зависимости и запустите

```bash
pip install -r requirements.txt
python bot.py
```

## Пример расчёта

Заказ: **М300, 10 м³**, завод в Москве, доставка в Подольск (~45 км по дороге)

```
Бетон:    5 300 ₽/м³ × 10 м³       = 53 000 ₽
Доставка: 3 000 + 80 × 45 км       =  6 600 ₽
─────────────────────────────────────────────
ИТОГО:                               59 600 ₽
```

## Запуск на сервере (для постоянной работы)

```bash
# systemd (Linux)
sudo nano /etc/systemd/system/concrete_bot.service
```

```ini
[Unit]
Description=Concrete Order Bot
After=network.target

[Service]
WorkingDirectory=/opt/concrete_bot
ExecStart=/usr/bin/python3 bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable concrete_bot && sudo systemctl start concrete_bot
```
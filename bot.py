"""
Telegram-бот для заказа бетона
Логистика: автоматический расчёт расстояния через Yandex Geocoder API
"""

import logging
import math
import os
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
import asyncio

try:
    from config import (
        BOT_TOKEN, MANAGER_CHAT_ID, PLANT_ADDRESS,
        PLANT_LAT, PLANT_LON, PRICE_PER_KM, BASE_DELIVERY_PRICE,
        CONCRETE_PRICES, YANDEX_GEOCODER_API_KEY
    )
except ImportError:
    BOT_TOKEN = os.environ["BOT_TOKEN"]
    MANAGER_CHAT_ID = int(os.environ["MANAGER_CHAT_ID"])
    YANDEX_GEOCODER_API_KEY = os.environ["YANDEX_GEOCODER_API_KEY"]
    PLANT_LAT = float(os.environ["PLANT_LAT"])
    PLANT_LON = float(os.environ["PLANT_LON"])
    BASE_DELIVERY_PRICE = float(os.environ.get("BASE_DELIVERY_PRICE", 300))
    PRICE_PER_KM = float(os.environ.get("PRICE_PER_KM", 30))
    PLANT_ADDRESS = os.environ.get("PLANT_ADDRESS", "Шушары, Паровозная дорога д.28")
    CONCRETE_PRICES = {
        "М100 (В7.5)":  3800,
        "М150 (В12.5)": 4100,
        "М200 (В15)":   4500,
        "М250 (В20)":   4900,
        "М300 (В22.5)": 5300,
        "М350 (В25)":   5700,
        "М400 (В30)":   6200,
        "М450 (В35)":   6800,
        "М500 (В40)":   7500,
    }

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


class OrderForm(StatesGroup):
    choosing_concrete = State()
    entering_volume   = State()
    entering_address  = State()
    entering_date     = State()
    entering_phone    = State()
    confirming        = State()


async def get_coords(address: str):
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": address,
        "format": "json",
        "limit": 1,
        "countrycodes": "ru",
    }
    try:
        headers = {"User-Agent": "BetoncoinBot/1.0"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not data:
                    return None
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        logger.error(f"Geocoder error: {e}")
        return None



def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return round(R * c * 1.3, 1)


def calculate_cost(mark, volume, distance):
    price = CONCRETE_PRICES.get(mark, 0)
    concrete_total = price * volume

    # Минимальный объём для расчёта доставки — 8 м³
    billing_volume = max(volume, 8.0)

    # Цена доставки за 1 м³ = 30₽/км × расстояние + 200₽ выезд
    delivery_per_m3 = PRICE_PER_KM * distance + BASE_DELIVERY_PRICE
    delivery_cost = delivery_per_m3 * billing_volume

    return {
        "concrete_price_per_m3": price,
        "concrete_total": concrete_total,
        "delivery_per_m3": delivery_per_m3,
        "billing_volume": billing_volume,
        "delivery_cost": delivery_cost,
        "total": concrete_total + delivery_cost,
    }


def format_order_summary(data, costs):
    billing_note = ""
    if costs['billing_volume'] > data['volume']:
        billing_note = f" (мин. 8 м³ для расчёта доставки)"
    return (
        f"📦 <b>Сводка заказа</b>\n\n"
        f"🔹 Марка бетона: <b>{data['concrete_mark']}</b>\n"
        f"🔹 Объём: <b>{data['volume']} м³</b>\n"
        f"🔹 Адрес доставки: <b>{data['address']}</b>\n"
        f"🔹 Расстояние от завода: <b>{data['distance']} км</b>\n"
        f"🔹 Дата и время: <b>{data['datetime']}</b>\n"
        f"🔹 Телефон: <b>{data['phone']}</b>\n\n"
        f"💰 <b>Расчёт стоимости:</b>\n"
        f"   • Бетон: {costs['concrete_price_per_m3']:,.0f} ₽/м³ × {data['volume']} м³ = <b>{costs['concrete_total']:,.0f} ₽</b>\n"
        f"   • Доставка: (30₽ × {data['distance']} км + 200₽) × {costs['billing_volume']:.0f} м³{billing_note} = <b>{costs['delivery_cost']:,.0f} ₽</b>\n"
        f"   • <b>ИТОГО: {costs['total']:,.0f} ₽</b>\n\n"
        f"📍 Отгрузка с завода: {PLANT_ADDRESS}"
    )


def main_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Оформить заказ")],
        [KeyboardButton(text="🧮 Рассчитать стоимость")],
        [KeyboardButton(text="📞 Связаться с менеджером")],
        [KeyboardButton(text="ℹ️ О компании")],
    ], resize_keyboard=True)


def concrete_keyboard():
    kb = [[KeyboardButton(text=m)] for m in CONCRETE_PRICES]
    kb.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def confirm_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="✅ Подтвердить заказ")],
        [KeyboardButton(text="✏️ Изменить данные")],
        [KeyboardButton(text="❌ Отменить")],
    ], resize_keyboard=True)


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"👋 Добро пожаловать в сервис заказа бетона!\n\n"
        f"🏭 Завод: {PLANT_ADDRESS}\n\n"
        f"Выберите действие:",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML"
    )


@dp.message(F.text.in_({"🔙 Назад", "❌ Отменить"}))
async def go_back(message: types.Message, state: FSMContext):
    await state.clear()
    text = "Заказ отменён. " if message.text == "❌ Отменить" else ""
    await message.answer(text + "Главное меню:", reply_markup=main_menu_keyboard())


@dp.message(F.text == "🔙 В главное меню")
async def back_to_main(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню:", reply_markup=main_menu_keyboard())


@dp.message(F.text == "ℹ️ О компании")
async def about_company(message: types.Message):
    await message.answer(
        f"🏭 <b>О нашей компании</b>\n\n"
        f"📍 Адрес завода: {PLANT_ADDRESS}\n"
        f"🕐 Режим работы: Пн-Сб 07:00–19:00\n\n"
        f"Стоимость доставки: {BASE_DELIVERY_PRICE:,.0f} ₽ (базовая) + {PRICE_PER_KM} ₽/км",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML"
    )


@dp.message(F.text == "📞 Связаться с менеджером")
async def contact_manager(message: types.Message):
    await message.answer(
        "📞 <b>Связь с менеджером</b>\n\n"
        "• Telegram: @cashmoney_j\n"
        "• Режим работы: Пн-Сб 07:00–19:00",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML"
    )


@dp.message(F.text.in_({"📋 Оформить заказ", "🧮 Рассчитать стоимость"}))
async def order_start(message: types.Message, state: FSMContext):
    mode = "order" if message.text == "📋 Оформить заказ" else "calc"
    await state.set_state(OrderForm.choosing_concrete)
    await state.update_data(mode=mode)
    header = "📋 <b>Оформление заказа</b>\n\nШаг 1/4:" if mode == "order" else "🧮 <b>Расчёт стоимости</b>\n\nШаг 1/3:"
    await message.answer(f"{header} Выберите марку бетона:", reply_markup=concrete_keyboard(), parse_mode="HTML")


@dp.message(OrderForm.choosing_concrete)
async def process_concrete(message: types.Message, state: FSMContext):
    if message.text not in CONCRETE_PRICES:
        await message.answer("Пожалуйста, выберите марку из списка.")
        return
    await state.update_data(concrete_mark=message.text)
    data = await state.get_data()
    step = "Шаг 2/4" if data["mode"] == "order" else "Шаг 2/3"
    await state.set_state(OrderForm.entering_volume)
    await message.answer(
        f"✅ Марка: <b>{message.text}</b>\n\n{step}: Введите объём бетона в м³\n<i>Например: 10 или 7.5</i>",
        reply_markup=ReplyKeyboardRemove(), parse_mode="HTML"
    )


@dp.message(OrderForm.entering_volume)
async def process_volume(message: types.Message, state: FSMContext):
    try:
    if not message.text:
        await message.answer("Введите корректный объём (например: 10 или 7.5).")
        return
    volume = float(message.text.replace(",", "."))
    if not (0 < volume <= 500):
        raise ValueError
except ValueError:
    await message.answer("Введите корректный объём (например: 10 или 7.5).")
    return

    await state.update_data(volume=volume)
    data = await state.get_data()
    step = "Шаг 3/4" if data["mode"] == "order" else "Шаг 3/3"
    await state.set_state(OrderForm.entering_address)
    await message.answer(
        f"✅ Объём: <b>{volume} м³</b>\n\n{step}: Введите адрес доставки\n"
        f"<i>Пример: Санкт-Петербург, Смольный пр.1</i>\n\n📍 Завод: {PLANT_ADDRESS}",
        parse_mode="HTML"
    )


@dp.message(OrderForm.entering_address)
async def process_address(message: types.Message, state: FSMContext):
    address = message.text.strip()
    if len(address) < 5:
        await message.answer("Введите полный адрес доставки.")
        return

    wait_msg = await message.answer("🔍 Определяю адрес и считаю расстояние...")
    coords = await get_coords(address)

    if coords is None:
        await wait_msg.delete()
        await message.answer(
            "⚠️ Не удалось определить адрес по Яндекс Картам.\n"
            "Уточните: укажите город, улицу и номер дома.\n"
            "<i>Пример: Санкт-Петербург, Смольный пр.1</i>",
            parse_mode="HTML"
        )
        return

    client_lat, client_lon = coords
    distance = haversine_distance(PLANT_LAT, PLANT_LON, client_lat, client_lon)
    await state.update_data(address=address, distance=distance)
    data = await state.get_data()
    costs = calculate_cost(data["concrete_mark"], data["volume"], distance)
    await wait_msg.delete()

    cost_text = (
        f"\n\n📏 Расстояние от завода: <b>{distance} км</b>\n\n"
        f"💰 <b>Предварительный расчёт:</b>\n"
        f"   • Бетон: {costs['concrete_total']:,.0f} ₽\n"
        f"   • Доставка: {costs['delivery_cost']:,.0f} ₽\n"
        f"   • <b>ИТОГО: {costs['total']:,.0f} ₽</b>"
    )

    if data["mode"] == "calc":
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="📋 Оформить заказ")],
            [KeyboardButton(text="🔙 В главное меню")],
        ], resize_keyboard=True)
        await state.clear()
        await message.answer(
            f"🧮 <b>Расчёт стоимости</b>\nМарка: {data['concrete_mark']}, объём: {data['volume']} м³\nАдрес: {address}" + cost_text,
            reply_markup=kb, parse_mode="HTML"
        )
    else:
        await state.set_state(OrderForm.entering_date)
        await message.answer(
            f"✅ Адрес принят." + cost_text +
            f"\n\nШаг 4/4: Введите желаемую дату и время доставки\n<i>Например: 20.05.2026 в 09:00</i>",
            parse_mode="HTML"
        )


@dp.message(OrderForm.entering_date)
async def process_date(message: types.Message, state: FSMContext):
    if len(message.text.strip()) < 3:
        await message.answer("Укажите дату и время доставки.")
        return
    await state.update_data(datetime=message.text.strip())
    await state.set_state(OrderForm.entering_phone)
    await message.answer(
        f"✅ Дата: <b>{message.text.strip()}</b>\n\nВведите контактный номер телефона\n<i>Например: +79991234567</i>",
        parse_mode="HTML"
    )


@dp.message(OrderForm.entering_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if len(phone) < 7:
        await message.answer("Введите корректный номер телефона.")
        return
    await state.update_data(phone=phone)
    data = await state.get_data()
    costs = calculate_cost(data["concrete_mark"], data["volume"], data["distance"])
    await state.set_state(OrderForm.confirming)
    await message.answer(
        format_order_summary(data, costs) + "\n\n❓ Всё верно? Подтвердите заказ:",
        reply_markup=confirm_keyboard(), parse_mode="HTML"
    )


@dp.message(OrderForm.confirming, F.text == "✅ Подтвердить заказ")
async def confirm_order(message: types.Message, state: FSMContext):
    data = await state.get_data()
    costs = calculate_cost(data["concrete_mark"], data["volume"], data["distance"])
    manager_text = (
        f"🚨 <b>НОВАЯ ЗАЯВКА НА БЕТОН</b>\n\n"
        f"👤 Клиент: @{message.from_user.username or '—'} (ID: {message.from_user.id})\n"
        f"👤 Имя: {message.from_user.full_name}\n\n"
        + format_order_summary(data, costs)
    )
    try:
        await bot.send_message(MANAGER_CHAT_ID, manager_text, parse_mode="HTML")
        notified = True
    except Exception as e:
        logger.error(f"Ошибка отправки менеджеру: {e}")
        notified = False
    await state.clear()
    if notified:
        await message.answer(
            "✅ <b>Заявка принята!</b>\n\nВаш заказ передан менеджеру. Мы свяжемся с вами в ближайшее время. 🏗️",
            reply_markup=main_menu_keyboard(), parse_mode="HTML"
        )
    else:
        await message.answer(
            "✅ Заявка оформлена, но возникла техническая проблема. Позвоните нам напрямую.",
            reply_markup=main_menu_keyboard()
        )


@dp.message(OrderForm.confirming, F.text == "✏️ Изменить данные")
async def edit_order(message: types.Message, state: FSMContext):
    await state.update_data(mode="order")
    await state.set_state(OrderForm.choosing_concrete)
    await message.answer("Начнём заново. Выберите марку бетона:", reply_markup=concrete_keyboard())


async def main():
    logger.info("Бот запущен...")
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)
    await dp.start_polling(bot)



if __name__ == "__main__":
    asyncio.run(main())

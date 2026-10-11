import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from motor.motor_asyncio import AsyncIOMotorClient

# --- НАСТРОЙКИ (в Railway вставь это как переменные окружения) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# --- БАЗА ДАННЫХ ---
client = AsyncIOMotorClient(MONGO_URI)
db = client["reputation_bot"]
users_col = db["users"]

# --- СОСТОЯНИЯ (FSM) ---
class RepForm(StatesGroup):
    waiting_for_username = State()   # Ждем юзернейм для отзыва
    waiting_for_type = State()       # Ждем +реп или -реп
    waiting_for_search = State()     # Ждем юзернейм для поиска

# --- РОУТЕР ---
router = Router()

# --- КЛАВИАТУРА ---
def main_kb():
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✍️ Написать отзыв"), KeyboardButton(text="🔍 Поиск")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )
    return kb

# --- ХЕЛПЕР: БАЗА ---
async def get_user(telegram_id: int):
    user = await users_col.find_one({"telegram_id": telegram_id})
    if not user:
        user = {"telegram_id": telegram_id, "username": None, "rep_pos": 0, "rep_neg": 0}
        await users_col.insert_one(user)
    return user

# --- ХЕНДЛЕРЫ ---

@router.message(CommandStart())
async def start(message: Message):
    await get_user(message.from_user.id)
    await message.answer(
        "Привет! Я бот для репутации.\nВыбери действие на клавиатуре:",
        reply_markup=main_kb()
    )

# --- НАПИСАТЬ ОТЗЫВ ---
@router.message(F.text == "✍️ Написать отзыв")
async def start_review(message: Message, state: FSMContext):
    await message.answer("Введи юзернейм пользователя (например, @username):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(RepForm.waiting_for_username)

@router.message(RepForm.waiting_for_username)
async def process_username(message: Message, state: FSMContext):
    target_username = message.text.strip().replace("@", "")
    
    # Проверка: не себя ли
    if target_username.lower() == (message.from_user.username or "").lower():
        await message.answer("Нельзя ставить репутацию самому себе!")
        return
    
    # Ищем пользователя в базе по username
    target_user = await users_col.find_one({"username": target_username})
    
    # Если не нашли — сохраняем в состоянии и просим выбрать тип
    await state.update_data(target_username=target_username)
    await message.answer(
        f"Пользователь @{target_username} найден!\n"
        "Напиши `+реп` или `-реп`:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="+реп"), KeyboardButton(text="-реп")]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )
    await state.set_state(RepForm.waiting_for_type)

@router.message(RepForm.waiting_for_type, F.text.in_({"+реп", "-реп"}))
async def process_rep_type(message: Message, state: FSMContext):
    data = await state.get_data()
    target_username = data["target_username"]
    rep_type = message.text
    
    # Обновляем репутацию в базе
    if rep_type == "+реп":
        await users_col.update_one({"username": target_username}, {"$inc": {"rep_pos": 1}}, upsert=True)
        await message.answer(f"✅ Ты повысил репутацию @{target_username}!", reply_markup=main_kb())
    else:
        await users_col.update_one({"username": target_username}, {"$inc": {"rep_neg": 1}}, upsert=True)
        await message.answer(f"❌ Ты понизил репутацию @{target_username}!", reply_markup=main_kb())
    
    await state.clear()

# --- ПОИСК ---
@router.message(F.text == "🔍 Поиск")
async def start_search(message: Message, state: FSMContext):
    await message.answer("Введи юзернейм для поиска (например, @username):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(RepForm.waiting_for_search)

@router.message(RepForm.waiting_for_search)
async def process_search(message: Message, state: FSMContext):
    target_username = message.text.strip().replace("@", "")
    user = await users_col.find_one({"username": target_username})
    
    if user:
        rep_pos = user.get("rep_pos", 0)
        rep_neg = user.get("rep_neg", 0)
        await message.answer(
            f"📊 Репутация @{target_username}:\n"
            f"👍 Хорошая: {rep_pos}\n"
            f"👎 Плохая: {rep_neg}",
            reply_markup=main_kb()
        )
    else:
        await message.answer(f"Пользователь @{target_username} не найден в базе.", reply_markup=main_kb())
    
    await state.clear()

# --- ЗАПУСК ---
async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

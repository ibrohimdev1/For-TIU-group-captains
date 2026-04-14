# pip install python-telegram-bot==20.7
"""
Telegram bot for TIU group captains to manage rosters and take attendance.
Stores each user's language and student list in a local JSON file.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

LANG_SELECT, MAIN_MENU, ADD_STUDENT, DELETE_STUDENT, ATTENDANCE_GROUP, ATTENDANCE_PARA, ATTENDANCE_SELECT = range(7)

DEFAULT_LANG = "uz"
SUPPORTED_LANGS = ("uz", "ru", "en")
DATA_FILE = Path(__file__).resolve().with_name("students_data.json")
ENV_FILE = Path(__file__).resolve().with_name(".env")
GROUP_CODE_PATTERN = re.compile(r"^[A-Za-z]{1,5}-\d{1,2}-\d{2,4}$")
DATA_LOCK = RLock()

LANG_CALLBACK_PREFIX = "lang:"
DELETE_CALLBACK_PREFIX = "delete:"
PARA_CALLBACK_PREFIX = "para:"
TOGGLE_CALLBACK_PREFIX = "toggle:"
DONE_CALLBACK = "attendance:done"
CANCEL_CALLBACK = "action:cancel"

CTX_ATTENDANCE_GROUP = "attendance_group"
CTX_ATTENDANCE_PARA = "attendance_para"
CTX_ATTENDANCE_PRESENT = "attendance_present"
CTX_ATTENDANCE_STUDENTS = "attendance_students"
CTX_ACTIVE_INLINE_MESSAGE_ID = "active_inline_message_id"

DataStore = dict[str, dict[str, Any]]
ATTENDANCE_HISTORY_LIMIT = 50

TEXTS: dict[str, dict[str, str]] = {
    "uz": {
        "language_prompt": "Tilni tanlang:",
        "language_changed": "Til saqlandi.",
        "language_button_uz": "🇺🇿 O'zbek",
        "language_button_ru": "🇷🇺 Русский",
        "language_button_en": "🇬🇧 English",
        "main_menu_prompt": "Kerakli bo'limni tanlang:",
        "menu_start": "/start",
        "menu_add": "➕ Talaba qo'shish",
        "menu_view": "📋 Ro'yxatni ko'rish",
        "menu_remove": "🗑 Talabani o'chirish",
        "menu_attendance": "📊 Davomat",
        "menu_history": "🕘 Eski davomat",
        "menu_unknown": "Iltimos, menyudagi tugmalardan birini tanlang.",
        "cancel_button": "❌ Bekor qilish",
        "cancelled": "Amal bekor qilindi.",
        "ask_student_name": "Talabaning to'liq ism-familiyasini yuboring.",
        "student_empty": "Bo'sh matn yuborib bo'lmaydi. To'liq ism-familiyani kiriting.",
        "student_duplicate": "Bu talaba allaqachon ro'yxatda: {name}",
        "student_added": "✅ Talaba qo'shildi: {name}",
        "roster_empty": "Ro'yxat hozircha bo'sh. Avval talabalarni qo'shing.",
        "roster_template": "📋 Talabalar ro'yxati\n\nJami: {count} ta talaba\n\n{students}",
        "delete_prompt": "🗑 O'chirish uchun talabani tanlang:",
        "student_removed": "🗑 Talaba o'chirildi: {name}",
        "delete_missing": "Tanlangan talaba topilmadi. Qaytadan urinib ko'ring.",
        "attendance_no_students": "Davomat olishdan oldin kamida bitta talaba qo'shing.",
        "attendance_group_prompt": "Guruh kodini yuboring.\nNamuna: DI-1-25",
        "attendance_group_invalid": "Guruh kodi noto'g'ri.\nNamuna: DI-1-25\nFormat: HARFLAR-RAQAM-RAQAM",
        "attendance_para_prompt": "Parani tanlang:",
        "para_1": "1-para",
        "para_2": "2-para",
        "para_3": "3-para",
        "para_4": "4-para",
        "attendance_select_prompt": "Darsga kelgan talabalarni belgilang. Belgilanmaganlar kelmaganlar ro'yxatiga tushadi. Tugatgach \"{done_button}\" tugmasini bosing.",
        "done_button": "✅ Yakunlash",
        "attendance_report": "{group} {period}:\n{body}",
        "attendance_report_absent": "{students}",
        "attendance_report_all_present": "Barcha talabalar keldi.",
        "history_empty": "Hozircha eski davomatlar yo'q.",
        "history_latest": "Oxirgi davomat: {date}\n{group} {period}:\n{body}",
        "history_title": "🕘 Eski davomatlar",
        "history_entry_template": "🕘 #{index}\n🏫 Guruh  : {group}\n⏰ Para   : {period}\n📅 Sana   : {date}\n✅ Kelganlar: {present_count} ta\n❌ Kelmaganlar: {absent_count} ta\n{absent_section}",
        "history_absent_list": "Kelmaganlar ro'yxati:\n{students}",
        "history_more_records": "... va yana {count} ta eski davomat bor.",
        "use_inline_buttons": "Iltimos, quyidagi tugmalardan foydalaning.",
        "stale_action": "Bu tugma endi faol emas. Asosiy menyudan qayta boshlang.",
        "generic_error": "Kutilmagan xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
        "delete_button_text": "🗑 {index}. {name}",
        "attendance_button_unselected": "{index}. {name}",
        "attendance_button_present": "✅ {index}. {name}",
    },
    "ru": {
        "language_prompt": "Выберите язык:",
        "language_changed": "Язык сохранен.",
        "language_button_uz": "🇺🇿 O'zbek",
        "language_button_ru": "🇷🇺 Русский",
        "language_button_en": "🇬🇧 English",
        "main_menu_prompt": "Выберите действие:",
        "menu_start": "/start",
        "menu_add": "➕ Добавить студента",
        "menu_view": "📋 Посмотреть список",
        "menu_remove": "🗑 Удалить студента",
        "menu_attendance": "📊 Посещаемость",
        "menu_history": "🕘 Старая посещаемость",
        "menu_unknown": "Пожалуйста, используйте кнопки меню.",
        "cancel_button": "❌ Отмена",
        "cancelled": "Действие отменено.",
        "ask_student_name": "Отправьте полное имя студента.",
        "student_empty": "Пустое имя отправить нельзя. Введите полное имя.",
        "student_duplicate": "Этот студент уже есть в списке: {name}",
        "student_added": "✅ Студент добавлен: {name}",
        "roster_empty": "Список пока пуст. Сначала добавьте студентов.",
        "roster_template": "📋 Список студентов\n\nВсего: {count} студентов\n\n{students}",
        "delete_prompt": "🗑 Выберите студента для удаления:",
        "student_removed": "🗑 Студент удален: {name}",
        "delete_missing": "Выбранный студент не найден. Попробуйте еще раз.",
        "attendance_no_students": "Перед отмечанием посещаемости добавьте хотя бы одного студента.",
        "attendance_group_prompt": "Отправьте код группы.\nПример: DI-1-25",
        "attendance_group_invalid": "Неверный код группы.\nПример: DI-1-25\nФормат: БУКВЫ-ЧИСЛО-ЧИСЛО",
        "attendance_para_prompt": "Выберите пару:",
        "para_1": "1-пара",
        "para_2": "2-пара",
        "para_3": "3-пара",
        "para_4": "4-пара",
        "attendance_select_prompt": "Отметьте пришедших студентов. Невыбранные попадут в список отсутствующих. Когда закончите, нажмите \"{done_button}\".",
        "done_button": "✅ Готово",
        "attendance_report": "{group} {period}:\n{body}",
        "attendance_report_absent": "{students}",
        "attendance_report_all_present": "Все студенты пришли.",
        "history_empty": "Старых записей посещаемости пока нет.",
        "history_latest": "Последняя посещаемость: {date}\n{group} {period}:\n{body}",
        "history_title": "🕘 Старая посещаемость",
        "history_entry_template": "🕘 #{index}\n🏫 Группа : {group}\n⏰ Пара   : {period}\n📅 Дата   : {date}\n✅ Присутствуют: {present_count}\n❌ Отсутствуют: {absent_count}\n{absent_section}",
        "history_absent_list": "Список отсутствующих:\n{students}",
        "history_more_records": "... и еще {count} старых записей посещаемости.",
        "use_inline_buttons": "Пожалуйста, используйте кнопки ниже.",
        "stale_action": "Эта кнопка уже неактуальна. Начните заново из главного меню.",
        "generic_error": "Произошла непредвиденная ошибка. Попробуйте еще раз.",
        "delete_button_text": "🗑 {index}. {name}",
        "attendance_button_unselected": "{index}. {name}",
        "attendance_button_present": "✅ {index}. {name}",
    },
    "en": {
        "language_prompt": "Select a language:",
        "language_changed": "Language saved.",
        "language_button_uz": "🇺🇿 O'zbek",
        "language_button_ru": "🇷🇺 Русский",
        "language_button_en": "🇬🇧 English",
        "main_menu_prompt": "Choose an action:",
        "menu_start": "/start",
        "menu_add": "➕ Add student",
        "menu_view": "📋 View roster",
        "menu_remove": "🗑 Remove student",
        "menu_attendance": "📊 Attendance",
        "menu_history": "🕘 Old attendance",
        "menu_unknown": "Please use the menu buttons below.",
        "cancel_button": "❌ Cancel",
        "cancelled": "Action cancelled.",
        "ask_student_name": "Send the student's full name.",
        "student_empty": "Empty input is not allowed. Please send a full name.",
        "student_duplicate": "This student is already in your roster: {name}",
        "student_added": "✅ Student added: {name}",
        "roster_empty": "Your roster is empty right now. Add students first.",
        "roster_template": "📋 Roster\n\nTotal: {count} students\n\n{students}",
        "delete_prompt": "🗑 Select a student to remove:",
        "student_removed": "🗑 Student removed: {name}",
        "delete_missing": "That student could not be found. Please try again.",
        "attendance_no_students": "Add at least one student before taking attendance.",
        "attendance_group_prompt": "Send the group code.\nExample: DI-1-25",
        "attendance_group_invalid": "Invalid group code.\nExample: DI-1-25\nFormat: LETTERS-NUMBER-NUMBER",
        "attendance_para_prompt": "Select the lecture period:",
        "para_1": "1st period",
        "para_2": "2nd period",
        "para_3": "3rd period",
        "para_4": "4th period",
        "attendance_select_prompt": "Mark the students who are present. Unmarked students will be added to the absent list. When you finish, press \"{done_button}\".",
        "done_button": "✅ Done",
        "attendance_report": "{group} {period}:\n{body}",
        "attendance_report_absent": "{students}",
        "attendance_report_all_present": "All students are present.",
        "history_empty": "There are no previous attendance records yet.",
        "history_latest": "Latest attendance: {date}\n{group} {period}:\n{body}",
        "history_title": "🕘 Old attendance",
        "history_entry_template": "🕘 #{index}\n🏫 Group  : {group}\n⏰ Period : {period}\n📅 Date   : {date}\n✅ Present: {present_count}\n❌ Absent : {absent_count}\n{absent_section}",
        "history_absent_list": "Absent list:\n{students}",
        "history_more_records": "... and {count} more previous attendance records.",
        "use_inline_buttons": "Please use the buttons below.",
        "stale_action": "This button is no longer active. Please start again from the main menu.",
        "generic_error": "An unexpected error occurred. Please try again.",
        "delete_button_text": "🗑 {index}. {name}",
        "attendance_button_unselected": "{index}. {name}",
        "attendance_button_present": "✅ {index}. {name}",
    },
}


def load_local_env() -> None:
    """Load variables from a local .env file without extra dependencies."""
    if not ENV_FILE.exists():
        return

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        clean_key = key.strip()
        clean_value = value.strip().strip('"').strip("'")

        if clean_key:
            os.environ.setdefault(clean_key, clean_value)


def normalize_student_name(name: str) -> str:
    """Normalize whitespace in a student name."""
    return " ".join(name.split())


def _default_record() -> dict[str, Any]:
    """Return the default JSON record for a user."""
    return {"lang": DEFAULT_LANG, "students": [], "attendance_history": []}


def _sanitize_students(raw_students: Any) -> list[str]:
    """Normalize and validate the students list from JSON."""
    if not isinstance(raw_students, list):
        return []

    students: list[str] = []
    for item in raw_students:
        if isinstance(item, str):
            clean_name = normalize_student_name(item)
            if clean_name:
                students.append(clean_name)
    return students


def _sanitize_attendance_history(raw_history: Any) -> list[dict[str, Any]]:
    """Normalize the attendance history records loaded from JSON."""
    if not isinstance(raw_history, list):
        return []

    history: list[dict[str, Any]] = []
    for item in raw_history:
        if not isinstance(item, dict):
            continue

        group = item.get("group")
        date = item.get("date")
        raw_period = item.get("period")
        present_students = _sanitize_students(item.get("present_students", []))
        absent_students = _sanitize_students(item.get("absent_students", []))

        period: int | None
        if isinstance(raw_period, int):
            period = raw_period
        elif isinstance(raw_period, str) and raw_period.isdigit():
            period = int(raw_period)
        else:
            period = None

        if not isinstance(group, str) or not group.strip():
            continue
        if not isinstance(date, str) or not date.strip():
            continue
        if period not in {1, 2, 3, 4}:
            continue

        history.append(
            {
                "group": group.strip().upper(),
                "period": period,
                "date": date.strip(),
                "present_students": present_students,
                "absent_students": absent_students,
            }
        )

    return history[-ATTENDANCE_HISTORY_LIMIT:]


def _load_data_unlocked() -> DataStore:
    """Read and sanitize the JSON storage without acquiring the outer lock."""
    if not DATA_FILE.exists():
        _save_data_unlocked({})
        return {}

    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON detected in %s. Resetting storage.", DATA_FILE)
        _save_data_unlocked({})
        return {}
    except OSError:
        logger.exception("Failed to read %s.", DATA_FILE)
        return {}

    if not isinstance(raw_data, dict):
        logger.warning("Unexpected JSON structure in %s. Resetting storage.", DATA_FILE)
        _save_data_unlocked({})
        return {}

    data: DataStore = {}
    for raw_user_id, raw_record in raw_data.items():
        if not isinstance(raw_record, dict):
            continue

        lang = raw_record.get("lang", DEFAULT_LANG)
        students = _sanitize_students(raw_record.get("students", []))
        attendance_history = _sanitize_attendance_history(raw_record.get("attendance_history", []))

        data[str(raw_user_id)] = {
            "lang": lang if lang in SUPPORTED_LANGS else DEFAULT_LANG,
            "students": students,
            "attendance_history": attendance_history,
        }

    return data


def _save_data_unlocked(data: DataStore) -> None:
    """Write the JSON storage atomically without acquiring the outer lock."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = DATA_FILE.with_name(f"{DATA_FILE.name}.tmp")

    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    os.replace(temp_file, DATA_FILE)


def load_data() -> DataStore:
    """Load the JSON storage under a process lock."""
    with DATA_LOCK:
        return _load_data_unlocked()


def save_data(data: DataStore) -> None:
    """Save the JSON storage under a process lock."""
    with DATA_LOCK:
        _save_data_unlocked(data)


def ensure_user_record(user_id: int) -> None:
    """Create a default record for a user if it does not exist yet."""
    with DATA_LOCK:
        data = _load_data_unlocked()
        user_key = str(user_id)
        if user_key not in data:
            data[user_key] = _default_record()
            _save_data_unlocked(data)


def get_user_language(user_id: int) -> str:
    """Return the user's selected language or the default one."""
    data = load_data()
    record = data.get(str(user_id), {})
    lang = record.get("lang", DEFAULT_LANG)
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def translate(lang: str, key: str, **kwargs: Any) -> str:
    """Translate a text key using a known language code."""
    template = TEXTS.get(lang, TEXTS[DEFAULT_LANG]).get(key, TEXTS[DEFAULT_LANG][key])
    return template.format(**kwargs)


def t(user_id: int, key: str, **kwargs: Any) -> str:
    """Translate a text key for the current user."""
    return translate(get_user_language(user_id), key, **kwargs)


def set_user_language(user_id: int, lang: str) -> None:
    """Persist the selected language for a user."""
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG

    with DATA_LOCK:
        data = _load_data_unlocked()
        user_key = str(user_id)
        record = data.get(user_key, _default_record())
        record["lang"] = lang
        record["students"] = _sanitize_students(record.get("students", []))
        record["attendance_history"] = _sanitize_attendance_history(record.get("attendance_history", []))
        data[user_key] = record
        _save_data_unlocked(data)


def get_students(user_id: int) -> list[str]:
    """Return a copy of the user's current roster."""
    data = load_data()
    record = data.get(str(user_id), _default_record())
    return list(record.get("students", []))


def get_attendance_history(user_id: int) -> list[dict[str, Any]]:
    """Return a copy of the user's saved attendance history."""
    data = load_data()
    record = data.get(str(user_id), _default_record())
    history = _sanitize_attendance_history(record.get("attendance_history", []))
    return [dict(item) for item in history]


def add_student_to_roster(user_id: int, raw_name: str) -> tuple[str, str]:
    """Add a student if valid and unique. Returns a status and the normalized name."""
    clean_name = normalize_student_name(raw_name)
    if not clean_name:
        return "empty", ""

    with DATA_LOCK:
        data = _load_data_unlocked()
        user_key = str(user_id)
        record = data.get(user_key, _default_record())
        students = list(record.get("students", []))

        if any(existing.casefold() == clean_name.casefold() for existing in students):
            return "duplicate", clean_name

        students.append(clean_name)
        record["students"] = students
        data[user_key] = record
        _save_data_unlocked(data)

    return "added", clean_name


def remove_student_from_roster(user_id: int, index: int) -> str | None:
    """Delete a student by index and return the removed name."""
    with DATA_LOCK:
        data = _load_data_unlocked()
        user_key = str(user_id)
        record = data.get(user_key, _default_record())
        students = list(record.get("students", []))

        if index < 0 or index >= len(students):
            return None

        removed_name = students.pop(index)
        record["students"] = students
        data[user_key] = record
        _save_data_unlocked(data)

    return removed_name


def save_attendance_record(
    user_id: int,
    group_code: str,
    para_number: int,
    date_text: str,
    present_students: list[str],
    absent_students: list[str],
) -> None:
    """Save a completed attendance session into the user's history."""
    entry = {
        "group": group_code,
        "period": para_number,
        "date": date_text,
        "present_students": list(present_students),
        "absent_students": list(absent_students),
    }

    with DATA_LOCK:
        data = _load_data_unlocked()
        user_key = str(user_id)
        record = data.get(user_key, _default_record())
        history = _sanitize_attendance_history(record.get("attendance_history", []))
        history.append(entry)
        record["attendance_history"] = history[-ATTENDANCE_HISTORY_LIMIT:]
        record["students"] = _sanitize_students(record.get("students", []))
        data[user_key] = record
        _save_data_unlocked(data)


def resolve_menu_action(text: str) -> str | None:
    """Resolve a pressed main-menu button into an internal action name."""
    clean_text = text.strip()
    menu_map = {
        "menu_start": "start",
        "menu_add": "add",
        "menu_view": "view",
        "menu_remove": "remove",
        "menu_attendance": "attendance",
        "menu_history": "history",
    }

    for lang in SUPPORTED_LANGS:
        for key, action in menu_map.items():
            if clean_text == TEXTS[lang][key]:
                return action

    return None


def is_cancel_text(text: str) -> bool:
    """Check whether a message matches any localized cancel label."""
    clean_text = text.strip()
    return any(clean_text == TEXTS[lang]["cancel_button"] for lang in SUPPORTED_LANGS)


def build_language_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Build the inline language-selection keyboard."""
    lang = get_user_language(user_id)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(translate(lang, "language_button_uz"), callback_data=f"{LANG_CALLBACK_PREFIX}uz"),
                InlineKeyboardButton(translate(lang, "language_button_ru"), callback_data=f"{LANG_CALLBACK_PREFIX}ru"),
                InlineKeyboardButton(translate(lang, "language_button_en"), callback_data=f"{LANG_CALLBACK_PREFIX}en"),
            ]
        ]
    )


def build_main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Build the localized main menu keyboard."""
    return ReplyKeyboardMarkup(
        [
            [t(user_id, "menu_start")],
            [t(user_id, "menu_add"), t(user_id, "menu_view")],
            [t(user_id, "menu_remove"), t(user_id, "menu_attendance")],
            [t(user_id, "menu_history")],
        ],
        resize_keyboard=True,
    )


def build_cancel_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Build the localized single-button cancel keyboard."""
    return ReplyKeyboardMarkup([[t(user_id, "cancel_button")]], resize_keyboard=True)


def build_delete_keyboard(user_id: int, students: list[str]) -> InlineKeyboardMarkup:
    """Build the inline delete keyboard for the current roster."""
    rows = [
        [InlineKeyboardButton(t(user_id, "delete_button_text", index=index, name=name), callback_data=f"{DELETE_CALLBACK_PREFIX}{index - 1}")]
        for index, name in enumerate(students, start=1)
    ]
    rows.append([InlineKeyboardButton(t(user_id, "cancel_button"), callback_data=CANCEL_CALLBACK)])
    return InlineKeyboardMarkup(rows)


def build_para_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Build the inline keyboard for lecture period selection."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t(user_id, "para_1"), callback_data=f"{PARA_CALLBACK_PREFIX}1"),
                InlineKeyboardButton(t(user_id, "para_2"), callback_data=f"{PARA_CALLBACK_PREFIX}2"),
            ],
            [
                InlineKeyboardButton(t(user_id, "para_3"), callback_data=f"{PARA_CALLBACK_PREFIX}3"),
                InlineKeyboardButton(t(user_id, "para_4"), callback_data=f"{PARA_CALLBACK_PREFIX}4"),
            ],
            [InlineKeyboardButton(t(user_id, "cancel_button"), callback_data=CANCEL_CALLBACK)],
        ]
    )


def build_attendance_keyboard(user_id: int, students: list[str], present_indices: set[int]) -> InlineKeyboardMarkup:
    """Build the toggleable inline keyboard for attendance selection."""
    rows = []
    for index, name in enumerate(students, start=1):
        key = "attendance_button_present" if index - 1 in present_indices else "attendance_button_unselected"
        rows.append(
            [
                InlineKeyboardButton(
                    t(user_id, key, index=index, name=name),
                    callback_data=f"{TOGGLE_CALLBACK_PREFIX}{index - 1}",
                )
            ]
        )

    rows.append([InlineKeyboardButton(t(user_id, "done_button"), callback_data=DONE_CALLBACK)])
    rows.append([InlineKeyboardButton(t(user_id, "cancel_button"), callback_data=CANCEL_CALLBACK)])
    return InlineKeyboardMarkup(rows)


def format_numbered_list(items: list[str]) -> str:
    """Format a list into numbered lines."""
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def format_plain_list(items: list[str]) -> str:
    """Format a list into plain line-by-line text."""
    return "\n".join(items)


def format_roster_message(user_id: int, students: list[str]) -> str:
    """Format the full roster message."""
    return t(user_id, "roster_template", count=len(students), students=format_numbered_list(students))


def format_attendance_report(
    user_id: int,
    group_code: str,
    para_number: int,
    absent_students: list[str],
    date_text: str,
) -> str:
    """Format the final attendance report message."""
    if absent_students:
        body = t(
            user_id,
            "attendance_report_absent",
            count=len(absent_students),
            students=format_plain_list(absent_students),
        )
    else:
        body = t(user_id, "attendance_report_all_present")

    return t(
        user_id,
        "attendance_report",
        group=group_code,
        period=t(user_id, f"para_{para_number}"),
        date=date_text,
        body=body,
    )


def format_attendance_history_message(user_id: int, history: list[dict[str, Any]]) -> str:
    """Format the saved attendance history into a localized message."""
    if not history:
        return t(user_id, "history_empty")

    latest = history[-1]
    absent_students = list(latest.get("absent_students", []))
    body = format_plain_list(absent_students) if absent_students else t(user_id, "attendance_report_all_present")

    return t(
        user_id,
        "history_latest",
        date=latest["date"],
        group=latest["group"],
        period=t(user_id, f"para_{latest['period']}"),
        body=body,
    )


def clear_flow_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear all transient conversation data for the current user."""
    for key in (
        CTX_ATTENDANCE_GROUP,
        CTX_ATTENDANCE_PARA,
        CTX_ATTENDANCE_PRESENT,
        CTX_ATTENDANCE_STUDENTS,
        CTX_ACTIVE_INLINE_MESSAGE_ID,
    ):
        context.user_data.pop(key, None)


async def send_bot_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup: object | None = None,
) -> None:
    """Send a message to the current chat."""
    chat = update.effective_chat
    if chat is None:
        return

    await context.bot.send_message(chat_id=chat.id, text=text, reply_markup=reply_markup)


async def safe_remove_markup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove inline buttons from the currently tracked inline message."""
    message_id = context.user_data.get(CTX_ACTIVE_INLINE_MESSAGE_ID)
    chat = update.effective_chat
    if message_id is None or chat is None:
        context.user_data.pop(CTX_ACTIVE_INLINE_MESSAGE_ID, None)
        return

    try:
        await context.bot.edit_message_reply_markup(chat_id=chat.id, message_id=message_id, reply_markup=None)
    except BadRequest:
        pass

    context.user_data.pop(CTX_ACTIVE_INLINE_MESSAGE_ID, None)


async def open_language_selector(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show the language selector and move the conversation into the language state."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return LANG_SELECT

    ensure_user_record(user.id)
    await safe_remove_markup(update, context)
    clear_flow_context(context)
    await message.reply_text(t(user.id, "language_prompt"), reply_markup=build_language_keyboard(user.id))
    return LANG_SELECT


async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str) -> int:
    """Send a message with the main menu keyboard and return to the main menu state."""
    await send_bot_message(update, context, text, reply_markup=build_main_menu_keyboard(user_id))
    return MAIN_MENU


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the bot by opening the language selector."""
    return await open_language_selector(update, context)


async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Re-open the language selector from any point in the conversation."""
    return await open_language_selector(update, context)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current flow and return to the main menu."""
    user = update.effective_user
    if user is None:
        return MAIN_MENU

    await safe_remove_markup(update, context)
    clear_flow_context(context)
    return await return_to_main_menu(update, context, user.id, t(user.id, "cancelled"))


async def handle_language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the selected language and show the main menu."""
    user = update.effective_user
    query = update.callback_query
    if user is None or query is None or not query.data:
        return LANG_SELECT

    selected_lang = query.data.replace(LANG_CALLBACK_PREFIX, "", 1)
    if selected_lang not in SUPPORTED_LANGS:
        await query.answer()
        return LANG_SELECT

    set_user_language(user.id, selected_lang)
    await safe_remove_markup(update, context)
    clear_flow_context(context)
    await query.answer()

    try:
        await query.edit_message_text(translate(selected_lang, "language_changed"))
    except BadRequest:
        pass

    return await return_to_main_menu(update, context, user.id, translate(selected_lang, "main_menu_prompt"))


async def remind_language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Remind the user to choose a language using the inline buttons."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return LANG_SELECT

    await message.reply_text(t(user.id, "language_prompt"), reply_markup=build_language_keyboard(user.id))
    return LANG_SELECT


async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Route the pressed main-menu button to the requested feature."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or message.text is None:
        return MAIN_MENU

    ensure_user_record(user.id)
    action = resolve_menu_action(message.text)

    if action is not None:
        await safe_remove_markup(update, context)
        clear_flow_context(context)

    if action == "start":
        return await start_command(update, context)

    if action == "add":
        await message.reply_text(t(user.id, "ask_student_name"), reply_markup=build_cancel_keyboard(user.id))
        return ADD_STUDENT

    if action == "view":
        students = get_students(user.id)
        response_text = t(user.id, "roster_empty") if not students else format_roster_message(user.id, students)
        await message.reply_text(response_text, reply_markup=build_main_menu_keyboard(user.id))
        return MAIN_MENU

    if action == "remove":
        students = get_students(user.id)
        if not students:
            await message.reply_text(t(user.id, "roster_empty"), reply_markup=build_main_menu_keyboard(user.id))
            return MAIN_MENU

        prompt_message = await message.reply_text(t(user.id, "delete_prompt"), reply_markup=build_delete_keyboard(user.id, students))
        context.user_data[CTX_ACTIVE_INLINE_MESSAGE_ID] = prompt_message.message_id
        return DELETE_STUDENT

    if action == "attendance":
        students = get_students(user.id)
        if not students:
            await message.reply_text(t(user.id, "attendance_no_students"), reply_markup=build_main_menu_keyboard(user.id))
            return MAIN_MENU

        context.user_data[CTX_ATTENDANCE_STUDENTS] = students
        await message.reply_text(t(user.id, "attendance_group_prompt"), reply_markup=build_cancel_keyboard(user.id))
        return ATTENDANCE_GROUP

    if action == "history":
        history = get_attendance_history(user.id)
        await message.reply_text(
            format_attendance_history_message(user.id, history),
            reply_markup=build_main_menu_keyboard(user.id),
        )
        return MAIN_MENU

    await message.reply_text(t(user.id, "menu_unknown"), reply_markup=build_main_menu_keyboard(user.id))
    return MAIN_MENU


async def handle_add_student(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate and save a student name entered during the add-student flow."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or message.text is None:
        return ADD_STUDENT

    if is_cancel_text(message.text):
        clear_flow_context(context)
        return await return_to_main_menu(update, context, user.id, t(user.id, "cancelled"))

    status, clean_name = add_student_to_roster(user.id, message.text)
    if status == "empty":
        await message.reply_text(t(user.id, "student_empty"), reply_markup=build_cancel_keyboard(user.id))
        return ADD_STUDENT

    if status == "duplicate":
        await message.reply_text(
            t(user.id, "student_duplicate", name=clean_name),
            reply_markup=build_cancel_keyboard(user.id),
        )
        return ADD_STUDENT

    clear_flow_context(context)
    return await return_to_main_menu(update, context, user.id, t(user.id, "student_added", name=clean_name))


async def handle_delete_student(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle delete selection callbacks and remove the chosen student."""
    user = update.effective_user
    query = update.callback_query
    if user is None or query is None or not query.data:
        return DELETE_STUDENT

    await query.answer()

    if query.data == CANCEL_CALLBACK:
        await safe_remove_markup(update, context)
        clear_flow_context(context)
        return await return_to_main_menu(update, context, user.id, t(user.id, "cancelled"))

    index_text = query.data.replace(DELETE_CALLBACK_PREFIX, "", 1)
    if not index_text.isdigit():
        return DELETE_STUDENT

    removed_name = remove_student_from_roster(user.id, int(index_text))
    await safe_remove_markup(update, context)
    clear_flow_context(context)

    if removed_name is None:
        return await return_to_main_menu(update, context, user.id, t(user.id, "delete_missing"))

    return await return_to_main_menu(update, context, user.id, t(user.id, "student_removed", name=removed_name))


async def handle_delete_student_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text messages while the delete inline keyboard is active."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or message.text is None:
        return DELETE_STUDENT

    if is_cancel_text(message.text):
        await safe_remove_markup(update, context)
        clear_flow_context(context)
        return await return_to_main_menu(update, context, user.id, t(user.id, "cancelled"))

    action = resolve_menu_action(message.text)
    if action is not None:
        await safe_remove_markup(update, context)
        return await handle_main_menu(update, context)

    await message.reply_text(t(user.id, "use_inline_buttons"), reply_markup=build_main_menu_keyboard(user.id))
    return DELETE_STUDENT


async def handle_attendance_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate the group code before moving to lecture-period selection."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or message.text is None:
        return ATTENDANCE_GROUP

    if is_cancel_text(message.text):
        clear_flow_context(context)
        return await return_to_main_menu(update, context, user.id, t(user.id, "cancelled"))

    group_code = message.text.strip().upper()
    if not GROUP_CODE_PATTERN.fullmatch(group_code):
        await message.reply_text(t(user.id, "attendance_group_invalid"), reply_markup=build_cancel_keyboard(user.id))
        return ATTENDANCE_GROUP

    students = context.user_data.get(CTX_ATTENDANCE_STUDENTS)
    if not isinstance(students, list) or not students:
        clear_flow_context(context)
        return await return_to_main_menu(update, context, user.id, t(user.id, "attendance_no_students"))

    context.user_data[CTX_ATTENDANCE_GROUP] = group_code
    prompt_message = await message.reply_text(t(user.id, "attendance_para_prompt"), reply_markup=build_para_keyboard(user.id))
    context.user_data[CTX_ACTIVE_INLINE_MESSAGE_ID] = prompt_message.message_id
    return ATTENDANCE_PARA


async def handle_attendance_para(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the selected lecture period and open the attendance toggle list."""
    user = update.effective_user
    query = update.callback_query
    if user is None or query is None or not query.data:
        return ATTENDANCE_PARA

    await query.answer()

    if query.data == CANCEL_CALLBACK:
        await safe_remove_markup(update, context)
        clear_flow_context(context)
        return await return_to_main_menu(update, context, user.id, t(user.id, "cancelled"))

    para_text = query.data.replace(PARA_CALLBACK_PREFIX, "", 1)
    if not para_text.isdigit():
        return ATTENDANCE_PARA

    students = context.user_data.get(CTX_ATTENDANCE_STUDENTS)
    if not isinstance(students, list) or not students:
        await safe_remove_markup(update, context)
        clear_flow_context(context)
        return await return_to_main_menu(update, context, user.id, t(user.id, "attendance_no_students"))

    context.user_data[CTX_ATTENDANCE_PARA] = int(para_text)
    context.user_data[CTX_ATTENDANCE_PRESENT] = set()

    await query.edit_message_text(
        t(user.id, "attendance_select_prompt", done_button=t(user.id, "done_button")),
        reply_markup=build_attendance_keyboard(user.id, students, set()),
    )
    return ATTENDANCE_SELECT


async def handle_attendance_para_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text input while waiting for inline lecture-period selection."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or message.text is None:
        return ATTENDANCE_PARA

    if is_cancel_text(message.text):
        await safe_remove_markup(update, context)
        clear_flow_context(context)
        return await return_to_main_menu(update, context, user.id, t(user.id, "cancelled"))

    await message.reply_text(t(user.id, "use_inline_buttons"), reply_markup=build_cancel_keyboard(user.id))
    return ATTENDANCE_PARA


async def handle_attendance_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Toggle present students and finalize the attendance report when done."""
    user = update.effective_user
    query = update.callback_query
    if user is None or query is None or not query.data:
        return ATTENDANCE_SELECT

    await query.answer()

    if query.data == CANCEL_CALLBACK:
        await safe_remove_markup(update, context)
        clear_flow_context(context)
        return await return_to_main_menu(update, context, user.id, t(user.id, "cancelled"))

    students = context.user_data.get(CTX_ATTENDANCE_STUDENTS)
    if not isinstance(students, list) or not students:
        await safe_remove_markup(update, context)
        clear_flow_context(context)
        return await return_to_main_menu(update, context, user.id, t(user.id, "attendance_no_students"))

    raw_present = context.user_data.get(CTX_ATTENDANCE_PRESENT, set())
    present_indices = set(raw_present) if isinstance(raw_present, (set, list, tuple)) else set()

    if query.data == DONE_CALLBACK:
        group_code = context.user_data.get(CTX_ATTENDANCE_GROUP)
        para_number = context.user_data.get(CTX_ATTENDANCE_PARA)
        if not isinstance(group_code, str) or not isinstance(para_number, int):
            await safe_remove_markup(update, context)
            clear_flow_context(context)
            return await return_to_main_menu(update, context, user.id, t(user.id, "stale_action"))

        present_students = [students[index] for index in sorted(present_indices) if 0 <= index < len(students)]
        absent_students = [name for index, name in enumerate(students) if index not in present_indices]
        date_text = datetime.now().strftime("%d.%m.%Y %H:%M")
        save_attendance_record(user.id, group_code, para_number, date_text, present_students, absent_students)
        report = format_attendance_report(user.id, group_code, para_number, absent_students, date_text)
        await safe_remove_markup(update, context)
        clear_flow_context(context)
        return await return_to_main_menu(update, context, user.id, report)

    index_text = query.data.replace(TOGGLE_CALLBACK_PREFIX, "", 1)
    if not index_text.isdigit():
        return ATTENDANCE_SELECT

    index = int(index_text)
    if index < 0 or index >= len(students):
        return ATTENDANCE_SELECT

    if index in present_indices:
        present_indices.remove(index)
    else:
        present_indices.add(index)

    context.user_data[CTX_ATTENDANCE_PRESENT] = present_indices

    try:
        await query.edit_message_reply_markup(reply_markup=build_attendance_keyboard(user.id, students, present_indices))
    except BadRequest:
        logger.info("Attendance keyboard update skipped because the markup did not change.")

    return ATTENDANCE_SELECT


async def handle_attendance_select_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text input while waiting for attendance toggle callbacks."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or message.text is None:
        return ATTENDANCE_SELECT

    if is_cancel_text(message.text):
        await safe_remove_markup(update, context)
        clear_flow_context(context)
        return await return_to_main_menu(update, context, user.id, t(user.id, "cancelled"))

    await message.reply_text(t(user.id, "use_inline_buttons"), reply_markup=build_cancel_keyboard(user.id))
    return ATTENDANCE_SELECT


async def handle_stale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Handle stale inline buttons and old language selectors that remain in chat history."""
    user = update.effective_user
    query = update.callback_query
    if user is None or query is None or not query.data:
        return None

    if query.data.startswith(LANG_CALLBACK_PREFIX):
        return await handle_language_selection(update, context)

    await query.answer(t(user.id, "stale_action"))
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except BadRequest:
        pass

    return None


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unexpected errors and send a localized recovery message when possible."""
    logger.error("Unhandled exception while processing an update: %s", context.error)

    if not isinstance(update, Update):
        return

    user = update.effective_user
    if user is None or update.effective_chat is None:
        return

    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t(user.id, "generic_error"),
            reply_markup=build_main_menu_keyboard(user.id),
        )
    except BadRequest:
        logger.exception("Failed to send an error message to the user.")


def build_conversation_handler() -> ConversationHandler:
    """Create the main conversation handler for the bot."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            CommandHandler("lang", lang_command),
        ],
        states={
            LANG_SELECT: [
                CallbackQueryHandler(handle_language_selection, pattern=r"^lang:(uz|ru|en)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, remind_language_selection),
            ],
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu),
            ],
            ADD_STUDENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_student),
            ],
            DELETE_STUDENT: [
                CallbackQueryHandler(handle_delete_student, pattern=r"^(delete:\d+|action:cancel)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_delete_student_text),
            ],
            ATTENDANCE_GROUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_attendance_group),
            ],
            ATTENDANCE_PARA: [
                CallbackQueryHandler(handle_attendance_para, pattern=r"^(para:[1-4]|action:cancel)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_attendance_para_text),
            ],
            ATTENDANCE_SELECT: [
                CallbackQueryHandler(
                    handle_attendance_select,
                    pattern=r"^(toggle:\d+|attendance:done|action:cancel)$",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_attendance_select_text),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CallbackQueryHandler(handle_stale_callback),
        ],
        allow_reentry=True,
    )


def main() -> None:
    """Run the Telegram bot."""
    load_local_env()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")

    application = Application.builder().token(token).concurrent_updates(False).build()
    application.add_handler(build_conversation_handler())
    application.add_error_handler(error_handler)

    logger.info("Bot is starting.")
    application.run_polling()


if __name__ == "__main__":
    main()


import os
import time
import hmac
import hashlib
import logging

import psycopg
import telebot
from flask import Flask, request, abort
from telebot import types

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("formiq")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

PUBLIC_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    "https://formiq-bot.onrender.com"
).rstrip("/")

WEBHOOK_SECRET = hashlib.sha256(
    TOKEN.encode()
).hexdigest()

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

# =========================
# АНКЕТА
# =========================

QUESTIONS = [
    ("goal", "Какая твоя цель?", [
        ("Похудеть", "loss"),
        ("Набрать мышцы", "muscle"),
        ("Выносливость", "endurance"),
        ("Поддерживать форму", "general"),
    ]),
    ("level", "Какой у тебя опыт?", [
        ("Новичок", "beginner"),
        ("Иногда тренируюсь", "some"),
        ("Регулярно тренируюсь", "experienced"),
    ]),
    ("days", "Сколько тренировок в неделю?", [
        ("2 дня", "2"),
        ("3 дня", "3"),
        ("4 дня", "4"),
        ("5 дней", "5"),
    ]),
    ("equipment", "Где хочешь тренироваться?", [
        ("Дома без инвентаря", "home"),
        ("Дома с инвентарём", "homegear"),
        ("В зале", "gym"),
    ]),
    ("age_group", "Тебе уже исполнилось 18 лет?", [
        ("Да, 18+", "adult"),
        ("Нет", "minor"),
    ]),
    ("minutes", "Сколько минут на тренировку?", [
        ("20 минут", "20"),
        ("30 минут", "30"),
        ("45 минут", "45"),
        ("60 минут", "60"),
    ]),
    (
        "clearance",
        "Есть боль, травмы или сомнения "
        "в безопасности нагрузки?",
        [
            ("Нет известных ограничений", "none"),
            ("Да, есть", "yes"),
            ("Не уверен(а)", "unsure"),
        ]
    ),
]

FIELDS = [q[0] for q in QUESTIONS]

LABELS = {
    (field, value): name
    for field, _, options in QUESTIONS
    for name, value in options
}

TITLES = [
    "Цель",
    "Опыт",
    "Дней в неделю",
    "Формат",
    "Возраст",
    "Время",
    "Ограничения"
]


# =========================
# БАЗА ДАННЫХ
# =========================

def db():
    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                chat_id BIGINT PRIMARY KEY,
                goal TEXT,
                level TEXT,
                days TEXT,
                equipment TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        for field in (
            "age_group",
            "minutes",
            "clearance"
        ):
            conn.execute(
                f"ALTER TABLE profiles "
                f"ADD COLUMN IF NOT EXISTS {field} TEXT"
            )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS workouts (
                id BIGSERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                plan_day TEXT NOT NULL,
                started_at TIMESTAMPTZ
                    NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ,
                difficulty TEXT,
                status TEXT NOT NULL DEFAULT 'active'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS workout_items (
                workout_id BIGINT NOT NULL
                    REFERENCES workouts(id)
                    ON DELETE CASCADE,
                position INT NOT NULL,
                exercise TEXT NOT NULL,
                target TEXT NOT NULL,
                done BOOLEAN NOT NULL DEFAULT FALSE,
                PRIMARY KEY (workout_id, position)
            )
        """)

        conn.execute("""
            ALTER TABLE workout_items
            ADD COLUMN IF NOT EXISTS skipped
            BOOLEAN NOT NULL DEFAULT FALSE
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS workouts_chat_idx
            ON workouts(chat_id, started_at DESC)
        """)


# =========================
# КНОПКИ И ГЛАВНОЕ МЕНЮ
# =========================

def menu(*buttons):
    markup = types.InlineKeyboardMarkup(row_width=1)

    for label, data in buttons:
        markup.add(
            types.InlineKeyboardButton(
                label,
                callback_data=data
            )
        )

    return markup


def main_menu(chat_id, greeting=True):
    if greeting:
        text = (
            "💪 FORMIQ 7.0 — твой тренировочный "
            "помощник\n\n"
            "Анкета, тренировки и дневник "
            "в одном месте.\n"
            "Пока тестируем: это не "
            "медицинское назначение."
        )
    else:
        text = "🏠 Главное меню FORMIQ"

    bot.send_message(
        chat_id,
        text,
        reply_markup=menu(
            ("👤 Мой профиль", "profile"),
            ("📝 Анкета", "restart"),
            ("🏋️ Мой план", "plan"),
            ("▶️ Текущая тренировка", "current"),
            ("📊 Статистика", "stats"),
            ("📖 История", "history"),
        )
    )


# =========================
# ПРОФИЛЬ
# =========================

def get_profile(chat_id):
    with db() as conn:
        row = conn.execute("""
            SELECT
                goal,
                level,
                days,
                equipment,
                age_group,
                minutes,
                clearance
            FROM profiles
            WHERE chat_id=%s
        """, (chat_id,)).fetchone()

    return dict(zip(FIELDS, row)) if row else {}


def reset_profile(chat_id):
    with db() as conn:
        conn.execute("""
            INSERT INTO profiles(chat_id)
            VALUES (%s)
            ON CONFLICT(chat_id)
            DO UPDATE SET
                goal=NULL,
                level=NULL,
                days=NULL,
                equipment=NULL,
                age_group=NULL,
                minutes=NULL,
                clearance=NULL,
                updated_at=NOW()
        """, (chat_id,))


def save_answer(chat_id, field, value):
    if field not in FIELDS:
        return

    with db() as conn:
        conn.execute("""
            INSERT INTO profiles(chat_id)
            VALUES (%s)
            ON CONFLICT(chat_id) DO NOTHING
        """, (chat_id,))

        conn.execute(
            f"UPDATE profiles "
            f"SET {field}=%s, updated_at=NOW() "
            f"WHERE chat_id=%s",
            (value, chat_id)
        )


def ask(chat_id, index):
    if index >= len(QUESTIONS):
        show_profile(chat_id)
        return

    _, question, options = QUESTIONS[index]

    buttons = [
        (name, f"answer:{index}:{value}")
        for name, value in options
    ]

    bot.send_message(
        chat_id,
        f"📝 Вопрос {index + 1}/{len(QUESTIONS)}"
        f"\n\n{question}",
        reply_markup=menu(*buttons)
    )


def show_profile(chat_id):
    p = get_profile(chat_id)

    if not p or not any(p.values()):
        bot.send_message(
            chat_id,
            "Пока нет анкеты. "
            "Открой /start и нажми «Анкета»."
        )
        return

    lines = [
        f"• {title}: "
        f"{LABELS.get((field, p.get(field)), '—')}"
        for field, title in zip(FIELDS, TITLES)
    ]

    bot.send_message(
        chat_id,
        "👤 Твой профиль FORMIQ\n\n"
        + "\n".join(lines),
        reply_markup=menu(
            ("🏋️ Мой план", "plan"),
            ("🔄 Изменить анкету", "restart"),
            ("🏠 В меню", "menu"),
        )
    )


# =========================
# ПРОГРАММЫ ТРЕНИРОВОК
# =========================

def plan_data(profile, suggestion="normal"):
    if any(
        not profile.get(field)
        for field in FIELDS
    ):
        return None, (
            "Для плана сначала заполни "
            "анкету: /start."
        )

    if profile["age_group"] != "adult":
        return None, (
            "Тестовая версия FORMIQ "
            "рассчитана на взрослых 18+."
        )

    if profile["clearance"] != "none":
        return None, (
            "При боли, травмах или сомнениях "
            "в безопасности нагрузку не назначаю. "
            "Уточни допустимую активность "
            "у специалиста."
        )

    minutes = int(profile["minutes"])
    beginner = profile["level"] == "beginner"

    sets = 2 if beginner or minutes == 20 else 3

    if suggestion == "lighter":
        sets = max(1, sets - 1)

    target = (
        "10–12"
        if suggestion == "slightly_more"
        else "8–12"
    )

    if profile["equipment"] == "gym":
        a = [
            "Жим ногами с лёгким весом",
            "Тяга верхнего блока",
            "Жим от груди в тренажёре",
            "Ягодичный мост",
        ]

        b = [
            "Степ-ап на низкую платформу",
            "Горизонтальная тяга",
            "Жим гантелей с лёгким весом",
            "Птица-собака",
        ]

    else:
        a = [
            "Приседания к стулу",
            "Отжимания от стены",
            "Ягодичный мост",
            "Птица-собака",
        ]

        b = [
            "Подъём на невысокую ступень",
            "Отжимания от опоры",
            "Подъём на носки",
            "Планка у стены",
        ]

    count = 3 if minutes == 20 else 4

    result = {}

    for name, items in (
        ("A", a),
        ("B", b)
    ):
        result[name] = [
            (
                ex,
                f"{sets} × "
                + (
                    "15–30 сек"
                    if "Планка" in ex
                    else target
                )
            )
            for ex in items[:count]
        ]

    return result, None


# =========================
# АДАПТАЦИЯ НАГРУЗОК
# =========================

def last_workouts(chat_id):
    with db() as conn:
        return conn.execute("""
            SELECT
                w.plan_day,
                w.difficulty,
                count(i.position) AS total,
                count(i.position)
                    FILTER (WHERE i.done) AS done
            FROM workouts w
            LEFT JOIN workout_items i
                ON i.workout_id=w.id
            WHERE w.chat_id=%s
                AND w.status='finished'
            GROUP BY w.id
            ORDER BY
                w.finished_at DESC,
                w.id DESC
            LIMIT 2
        """, (chat_id,)).fetchall()


def next_day(chat_id):
    rows = last_workouts(chat_id)

    return (
        "B"
        if rows and rows[0][0] == "A"
        else "A"
    )


def adaptation(chat_id):
    rows = last_workouts(chat_id)

    if not rows:
        return (
            "normal",
            "Первое занятие: не торопись "
            "и следи за техникой."
        )

    if rows[0][1] == "hard":
        return (
            "lighter",
            "В прошлый раз было тяжело: "
            "уменьшаем число подходов."
        )

    if len(rows) == 2 and all(
        row[1] == "easy"
        and row[2] > 0
        and row[2] == row[3]
        for row in rows
    ):
        return (
            "slightly_more",
            "Два полных занятия были лёгкими: "
            "пробуем немного больше повторений."
        )

    return (
        "normal",
        "Сохраняем комфортную нагрузку "
        "и технику."
    )


# =========================
# АКТИВНАЯ ТРЕНИРОВКА
# =========================

def active_workout(chat_id):
    with db() as conn:
        return conn.execute("""
            SELECT id
            FROM workouts
            WHERE chat_id=%s
                AND status='active'
            ORDER BY id DESC
            LIMIT 1
        """, (chat_id,)).fetchone()


def show_plan(chat_id):
    p = get_profile(chat_id)

    change, note = adaptation(chat_id)
    plans, error = plan_data(p, change)

    if error:
        bot.send_message(chat_id, error)
        return

    day = next_day(chat_id)

    days = min(
        int(p["days"]),
        3 if p["level"] == "beginner" else 4
    )

    lines = [
        f"🏋️ FORMIQ · {days} занятий "
        f"в неделю по {p['minutes']} мин",
        f"Следующая тренировка: {day}",
        note,
        "Разминка 3–5 мин, заминка 2–3 мин. "
        "Отдых 45–75 сек.",
    ]

    for name, exercises in plans.items():
        lines.append(f"\nДень {name}:")

        lines.extend(
            f"• {ex} — {target}"
            for ex, target in exercises
        )

    lines.append(
        "\nМежду силовыми оставляй день "
        "восстановления. При боли, "
        "головокружении или необычной одышке "
        "остановись. Это базовый шаблон, "
        "не медицинское назначение."
    )

    ongoing = active_workout(chat_id)

    if ongoing:
        buttons = [
            (
                "▶️ Продолжить тренировку",
                "current"
            )
        ]
    else:
        buttons = [
            (
                f"▶️ Начать тренировку {day}",
                "begin:next"
            )
        ]

    buttons += [
        ("📊 Статистика", "stats"),
        ("🏠 В меню", "menu"),
    ]

    bot.send_message(
        chat_id,
        "\n".join(lines),
        reply_markup=menu(*buttons)
    )


def next_day_in_transaction(conn, chat_id):
    row = conn.execute("""
        SELECT plan_day
        FROM workouts
        WHERE chat_id=%s
            AND status='finished'
        ORDER BY finished_at DESC, id DESC
        LIMIT 1
    """, (chat_id,)).fetchone()

    return (
        "B"
        if row and row[0] == "A"
        else "A"
    )


def start_workout(chat_id):
    p = get_profile(chat_id)
    change, _ = adaptation(chat_id)

    plans, error = plan_data(p, change)

    if error:
        bot.send_message(chat_id, error)
        return

    with db() as conn:
        # Защита от двух одновременных запусков
        conn.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (chat_id,)
        )

        row = conn.execute("""
            SELECT id
            FROM workouts
            WHERE chat_id=%s AND status='active'
            LIMIT 1
        """, (chat_id,)).fetchone()

        if row:
            wid = row[0]

        else:
            day = next_day_in_transaction(
                conn,
                chat_id
            )

            wid = conn.execute("""
                INSERT INTO workouts(
                    chat_id,
                    plan_day
                )
                VALUES (%s, %s)
                RETURNING id
            """, (chat_id, day)).fetchone()[0]

            for index, (exercise, target) in enumerate(
                plans[day]
            ):
                conn.execute("""
                    INSERT INTO workout_items(
                        workout_id,
                        position,
                        exercise,
                        target
                    )
                    VALUES (%s, %s, %s, %s)
                """, (
                    wid,
                    index,
                    exercise,
                    target
                ))

    show_workout(chat_id, wid)


def show_workout(chat_id, wid):
    with db() as conn:
        workout = conn.execute("""
            SELECT plan_day, status
            FROM workouts
            WHERE id=%s AND chat_id=%s
        """, (wid, chat_id)).fetchone()

        if not workout:
            bot.send_message(
                chat_id,
                "Тренировка не найдена."
            )
            return

        items = conn.execute("""
            SELECT
                position,
                exercise,
                target,
                done,
                skipped
            FROM workout_items
            WHERE workout_id=%s
            ORDER BY position
        """, (wid,)).fetchall()

    day, status = workout

    state = (
        "идёт"
        if status == "active"
        else "завершена"
    )

    lines = [
        f"🏋️ Тренировка {day} · {state}"
    ]

    buttons = []

    for pos, exercise, target, done, skipped in items:
        mark = (
            "✅" if done
            else "⏭" if skipped
            else "⬜"
        )

        lines.append(
            f"{mark} {exercise} — {target}"
        )

        if (
            status == "active"
            and not done
            and not skipped
        ):
            buttons.extend([
                (
                    f"✅ {exercise[:28]}",
                    f"done:{wid}:{pos}"
                ),
                (
                    f"⏭ Пропустить {exercise[:24]}",
                    f"skip:{wid}:{pos}"
                ),
            ])

    if status == "active":
        buttons.extend([
            (
                "🏁 Завершить",
                f"finish:{wid}"
            ),
            (
                "❌ Отменить",
                f"cancel:{wid}"
            ),
        ])

    buttons.append(
        ("🏠 В меню", "menu")
    )

    bot.send_message(
        chat_id,
        "\n".join(lines),
        reply_markup=menu(*buttons)
    )


def mark_item(chat_id, wid, pos, skip=False):
    with db() as conn:
        changed = conn.execute("""
            UPDATE workout_items i
            SET done=%s, skipped=%s
            WHERE i.workout_id=%s
                AND i.position=%s
                AND NOT i.done
                AND NOT i.skipped
                AND EXISTS (
                    SELECT 1
                    FROM workouts w
                    WHERE w.id=i.workout_id
                        AND w.chat_id=%s
                        AND w.status='active'
                )
            RETURNING i.position
        """, (
            not skip,
            skip,
            wid,
            pos,
            chat_id
        )).fetchone()

    if changed:
        show_workout(chat_id, wid)
    else:
        bot.send_message(
            chat_id,
            "Этот пункт уже обработан "
            "или кнопка устарела. /workout"
        )


def finish_workout(chat_id, wid):
    with db() as conn:
        changed = conn.execute("""
            UPDATE workouts
            SET
                status='finished',
                finished_at=NOW()
            WHERE id=%s
                AND chat_id=%s
                AND status='active'
            RETURNING id
        """, (wid, chat_id)).fetchone()

    if not changed:
        bot.send_message(
            chat_id,
            "Тренировка уже завершена "
            "или отменена."
        )
        return

    bot.send_message(
        chat_id,
        "🏁 Занятие сохранено! "
        "Как прошла нагрузка?",
        reply_markup=menu(
            ("🙂 Легко", f"rate:{wid}:easy"),
            ("💪 Нормально", f"rate:{wid}:ok"),
            ("😮‍💨 Тяжело", f"rate:{wid}:hard"),
        )
    )


def rate_workout(chat_id, wid, rating):
    if rating not in ("easy", "ok", "hard"):
        return

    with db() as conn:
        changed = conn.execute("""
            UPDATE workouts
            SET difficulty=%s
            WHERE id=%s
                AND chat_id=%s
                AND status='finished'
                AND difficulty IS NULL
            RETURNING id
        """, (
            rating,
            wid,
            chat_id
        )).fetchone()

    if changed:
        text = "✅ Оценка записана. /stats"
    else:
        text = (
            "Оценка уже сохранена "
            "или кнопка устарела."
        )

    bot.send_message(chat_id, text)


# =========================
# ПОДТВЕРЖДЕНИЕ ДЕЙСТВИЙ
# =========================

def action_signature(
    kind,
    chat_id,
    wid,
    expires
):
    content = (
        f"{kind}:{chat_id}:{wid}:{expires}"
    ).encode()

    return hmac.new(
        TOKEN.encode(),
        content,
        hashlib.sha256
    ).hexdigest()[:12]


def valid_signature(
    kind,
    chat_id,
    wid,
    expires,
    signature
):
    return (
        int(time.time()) <= expires
        and hmac.compare_digest(
            signature,
            action_signature(
                kind,
                chat_id,
                wid,
                expires
            )
        )
    )


def confirm_cancel(chat_id, wid):
    expires = int(time.time()) + 600

    signature = action_signature(
        "cancel",
        chat_id,
        wid,
        expires
    )

    bot.send_message(
        chat_id,
        "Отменить занятие? "
        "Оно не попадёт в статистику.",
        reply_markup=menu(
            (
                "❌ Да, отменить",
                f"cancel_yes:{wid}:{expires}:{signature}"
            ),
            (
                "↩️ Нет, продолжить",
                "current"
            ),
        )
    )


def cancel_workout(chat_id, wid):
    with db() as conn:
        deleted = conn.execute("""
            DELETE FROM workouts
            WHERE id=%s
                AND chat_id=%s
                AND status='active'
            RETURNING id
        """, (wid, chat_id)).fetchone()

    if deleted:
        text = "Тренировка отменена."
    else:
        text = (
            "Тренировка уже завершена "
            "или отменена."
        )

    bot.send_message(chat_id, text)


# =========================
# ИСТОРИЯ
# =========================

def show_history(chat_id):
    with db() as conn:
        rows = conn.execute("""
            SELECT
                w.plan_day,
                w.started_at,
                w.difficulty,
                count(i.position),
                count(i.position)
                    FILTER (WHERE i.done)
            FROM workouts w
            LEFT JOIN workout_items i
                ON i.workout_id=w.id
            WHERE w.chat_id=%s
                AND w.status='finished'
            GROUP BY w.id
            ORDER BY
                w.finished_at DESC,
                w.id DESC
            LIMIT 10
        """, (chat_id,)).fetchall()

    if not rows:
        bot.send_message(
            chat_id,
            "В дневнике пока нет "
            "завершённых тренировок."
        )
        return

    labels = {
        "easy": "легко",
        "ok": "нормально",
        "hard": "тяжело"
    }

    lines = ["📖 История тренировок:"]

    for (
        day,
        started,
        rating,
        total,
        done
    ) in rows:
        lines.append(
            f"• {started:%d.%m} · {day} · "
            f"{done}/{total} · "
            f"{labels.get(rating, 'без оценки')}"
        )

    bot.send_message(
        chat_id,
        "\n".join(lines)
    )


# =========================
# СТАТИСТИКА
# =========================

def show_stats(chat_id):
    with db() as conn:
        counts = conn.execute("""
            SELECT
                count(*) FILTER (
                    WHERE finished_at >=
                    NOW()-INTERVAL '7 days'
                ),
                count(*) FILTER (
                    WHERE finished_at >=
                    NOW()-INTERVAL '30 days'
                ),
                count(*)
            FROM workouts
            WHERE chat_id=%s
                AND status='finished'
        """, (chat_id,)).fetchone()

        items = conn.execute("""
            SELECT
                count(*) FILTER (WHERE i.done),
                count(*) FILTER (WHERE i.skipped)
            FROM workout_items i
            JOIN workouts w
                ON w.id=i.workout_id
            WHERE w.chat_id=%s
                AND w.status='finished'
        """, (chat_id,)).fetchone()

    p = get_profile(chat_id)

    if p.get("days") in (
        "2", "3", "4", "5"
    ):
        goal = min(
            int(p["days"]),
            3 if p.get("level") == "beginner" else 4
        )
    else:
        goal = 0

    weekly = (
        f"{counts[0]}/{goal}"
        if goal
        else str(counts[0])
    )

    _, note = adaptation(chat_id)

    bot.send_message(
        chat_id,
        "📊 Статистика FORMIQ\n"
        f"За 7 дней: {weekly}\n"
        f"За 30 дней: {counts[1]}\n"
        f"Всего завершено: {counts[2]}\n"
        f"Упражнений сделано: {items[0]}\n"
        f"Пропущено: {items[1]}\n\n"
        + note,
        reply_markup=menu(
            ("🏋️ Мой план", "plan"),
            ("🏠 В меню", "menu"),
        )
    )


# =========================
# УДАЛЕНИЕ ПРОФИЛЯ
# =========================

def confirm_delete(chat_id):
    expires = int(time.time()) + 600

    signature = action_signature(
        "delete",
        chat_id,
        0,
        expires
    )

    bot.send_message(
        chat_id,
        "Удалить профиль и весь "
        "дневник FORMIQ?",
        reply_markup=menu(
            (
                "🗑 Да, удалить всё",
                f"delete_yes:{expires}:{signature}"
            ),
            (
                "↩️ Не удалять",
                "menu"
            ),
        )
    )


def delete_all(chat_id):
    with db() as conn:
        conn.execute(
            "DELETE FROM workouts WHERE chat_id=%s",
            (chat_id,)
        )

        conn.execute(
            "DELETE FROM profiles WHERE chat_id=%s",
            (chat_id,)
        )

    bot.send_message(
        chat_id,
        "Профиль и дневник удалены "
        "из базы FORMIQ. "
        "Сообщения Telegram и внешние "
        "копии не затронуты."
    )


# =========================
# КОМАНДЫ TELEGRAM
# =========================

def private_chat(chat_id, chat_type):
    if chat_type != "private":
        bot.send_message(
            chat_id,
            "Пожалуйста, используй "
            "FORMIQ в личном чате."
        )
        return False

    return True


@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    if private_chat(
        message.chat.id,
        message.chat.type
    ):
        main_menu(message.chat.id)


@bot.message_handler(commands=["profile"])
def cmd_profile(message):
    if private_chat(
        message.chat.id,
        message.chat.type
    ):
        show_profile(message.chat.id)


@bot.message_handler(commands=["plan"])
def cmd_plan(message):
    if private_chat(
        message.chat.id,
        message.chat.type
    ):
        show_plan(message.chat.id)


@bot.message_handler(commands=["workout"])
def cmd_workout(message):
    if not private_chat(
        message.chat.id,
        message.chat.type
    ):
        return

    row = active_workout(message.chat.id)

    if row:
        show_workout(
            message.chat.id,
            row[0]
        )
    else:
        bot.send_message(
            message.chat.id,
            "Активной тренировки нет. "
            "Открой /plan."
        )


@bot.message_handler(
    commands=["progress", "history"]
)
def cmd_history(message):
    if private_chat(
        message.chat.id,
        message.chat.type
    ):
        show_history(message.chat.id)


@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    if private_chat(
        message.chat.id,
        message.chat.type
    ):
        show_stats(message.chat.id)


@bot.message_handler(commands=["delete_me"])
def cmd_delete(message):
    if private_chat(
        message.chat.id,
        message.chat.type
    ):
        confirm_delete(message.chat.id)


@bot.message_handler(
    commands=["nutrition", "coach"]
)
def cmd_soon(message):
    if private_chat(
        message.chat.id,
        message.chat.type
    ):
        bot.send_message(
            message.chat.id,
            "Функция ещё в разработке. "
            "Пока доступны /plan и /stats."
        )


# =========================
# ОБРАБОТКА КНОПОК
# =========================

@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    chat_id = call.message.chat.id
    data = call.data or ""

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if (
        call.message.chat.type != "private"
        or call.from_user.id != chat_id
    ):
        return

    # Убираем кнопки старого сообщения
    try:
        bot.edit_message_reply_markup(
            chat_id,
            call.message.message_id,
            reply_markup=None
        )
    except Exception:
        pass

    if data == "menu":
        main_menu(
            chat_id,
            greeting=False
        )

    elif data == "profile":
        show_profile(chat_id)

    elif data == "restart":
        bot.send_message(
            chat_id,
            "Начать анкету заново? "
            "История тренировок сохранится.",
            reply_markup=menu(
                ("✅ Да, начать", "restart_yes"),
                ("↩️ Нет", "menu")
            )
        )

    elif data == "restart_yes":
        reset_profile(chat_id)
        ask(chat_id, 0)

    elif data == "plan":
        show_plan(chat_id)

    elif data == "current":
        row = active_workout(chat_id)

        if row:
            show_workout(chat_id, row[0])
        else:
            bot.send_message(
                chat_id,
                "Активной тренировки нет. /plan"
            )

    elif data == "stats":
        show_stats(chat_id)

    elif data == "history":
        show_history(chat_id)

    elif data.startswith("answer:"):
        try:
            _, number, value = data.split(":", 2)
            index = int(number)
            field, _, options = QUESTIONS[index]
        except (ValueError, IndexError):
            return

        if value not in {
            option for _, option in options
        }:
            return

        p = get_profile(chat_id)

        expected = next(
            (
                i
                for i, f in enumerate(FIELDS)
                if not p.get(f)
            ),
            len(FIELDS)
        )

        if index != expected:
            bot.send_message(
                chat_id,
                "Эта кнопка анкеты устарела. "
                "Используй /start."
            )
            return

        save_answer(
            chat_id,
            field,
            value
        )

        ask(chat_id, index + 1)

    elif data == "begin:next":
        start_workout(chat_id)

    elif (
        data.startswith("done:")
        or data.startswith("skip:")
    ):
        try:
            action, wid, pos = data.split(":", 2)

            mark_item(
                chat_id,
                int(wid),
                int(pos),
                action == "skip"
            )
        except ValueError:
            pass

    elif data.startswith("finish:"):
        try:
            finish_workout(
                chat_id,
                int(data.split(":")[1])
            )
        except ValueError:
            pass

    elif data.startswith("rate:"):
        try:
            _, wid, rating = data.split(":", 2)

            rate_workout(
                chat_id,
                int(wid),
                rating
            )
        except ValueError:
            pass

    elif data.startswith("cancel:"):
        try:
            confirm_cancel(
                chat_id,
                int(data.split(":")[1])
            )
        except ValueError:
            pass

    elif data.startswith("cancel_yes:"):
        try:
            _, wid, expiry, signature = data.split(
                ":",
                3
            )

            wid = int(wid)
            expiry = int(expiry)

            if valid_signature(
                "cancel",
                chat_id,
                wid,
                expiry,
                signature
            ):
                cancel_workout(chat_id, wid)
            else:
                bot.send_message(
                    chat_id,
                    "Подтверждение устарело. "
                    "/workout"
                )
        except ValueError:
            pass

    elif data.startswith("delete_yes:"):
        try:
            _, expiry, signature = data.split(
                ":",
                2
            )

            expiry = int(expiry)

            if valid_signature(
                "delete",
                chat_id,
                0,
                expiry,
                signature
            ):
                delete_all(chat_id)
            else:
                bot.send_message(
                    chat_id,
                    "Подтверждение устарело. "
                    "/delete_me"
                )
        except ValueError:
            pass

    else:
        bot.send_message(
            chat_id,
            "Эта кнопка из старой версии. "
            "Открой /start."
        )


# =========================
# WEBHOOK И ЗАПУСК
# =========================

@app.get("/")
def health():
    return "FORMIQ 7.0 online", 200


@app.post("/telegram-webhook")
def webhook():
    candidate = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token",
        ""
    )

    if not hmac.compare_digest(
        candidate,
        WEBHOOK_SECRET
    ):
        abort(403)

    if not request.is_json:
        abort(415)

    update = types.Update.de_json(
        request.get_data(as_text=True)
    )

    bot.process_new_updates([update])

    return "OK", 200


if __name__ == "__main__":
    init_db()

    bot.set_webhook(
        url=PUBLIC_URL + "/telegram-webhook",
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=False
    )

    log.info("FORMIQ 7.0 webhook ready")

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False
    )

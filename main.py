
import os
import hmac
import hashlib
import logging
import time

import psycopg
import telebot
from flask import Flask, request, abort
from telebot import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("formiq")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DB_URL = os.environ["DATABASE_URL"]
PUBLIC_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    "https://formiq-bot.onrender.com"
).rstrip("/")
SECRET = hashlib.sha256(TOKEN.encode()).hexdigest()

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

QUESTIONS = [
    ("goal", "Какая твоя цель?", [
        ("Похудеть", "loss"),
        ("Набрать мышцы", "muscle"),
        ("Выносливость", "endurance"),
        ("Поддерживать форму", "general")
    ]),
    ("level", "Какой у тебя опыт?", [
        ("Новичок", "beginner"),
        ("Иногда тренируюсь", "some"),
        ("Регулярно тренируюсь", "experienced")
    ]),
    ("days", "Сколько тренировок в неделю?", [
        ("2 дня", "2"),
        ("3 дня", "3"),
        ("4 дня", "4"),
        ("5 дней", "5")
    ]),
    ("equipment", "Где хочешь тренироваться?", [
        ("Дома без инвентаря", "home"),
        ("Дома с инвентарём", "homegear"),
        ("В зале", "gym")
    ]),
    ("age_group", "Тебе уже исполнилось 18 лет?", [
        ("Да, 18+", "adult"),
        ("Нет", "minor")
    ]),
    ("minutes", "Сколько минут на тренировку?", [
        ("20 минут", "20"),
        ("30 минут", "30"),
        ("45 минут", "45"),
        ("60 минут", "60")
    ]),
    ("clearance",
     "Есть боль, травмы или сомнения "
     "в безопасности нагрузки?", [
        ("Нет известных ограничений", "none"),
        ("Да, есть", "yes"),
        ("Не уверен(а)", "unsure")
    ])
]

FIELDS = [q[0] for q in QUESTIONS]

LABELS = {
    (field, val): text
    for field, _, choices in QUESTIONS
    for text, val in choices
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

# Название, техника, частая ошибка
EXERCISES = {
    "squat": (
        "Приседания к стулу",
        "Стой устойчиво, садись назад до касания "
        "стула, вставай без рывка.",
        "Не заваливай колени внутрь и не падай на стул."
    ),
    "wall_push": (
        "Отжимания от стены",
        "Ладони на уровне груди, тело прямое, "
        "плавно согни и разогни руки.",
        "Не прогибай поясницу и не поднимай плечи."
    ),
    "bridge": (
        "Ягодичный мост",
        "Лёжа согни колени, подними таз "
        "за счёт ягодиц, опусти плавно.",
        "Не переразгибай поясницу."
    ),
    "bird": (
        "Птица-собака",
        "На четвереньках вытягивай противоположные "
        "руку и ногу, сохраняй ровный корпус.",
        "Не вращай таз и не тяни ногу слишком высоко."
    ),
    "step": (
        "Подъём на невысокую ступень",
        "Поднимайся на устойчивую низкую "
        "платформу и опускайся медленно.",
        "Не используй шаткую опору и не прыгай вниз."
    ),
    "incline_push": (
        "Отжимания от высокой опоры",
        "Упрись в устойчивый стол или стойку, "
        "держи корпус ровным.",
        "Не используй скользящую опору."
    ),
    "calf": (
        "Подъём на носки",
        "Держись за опору, поднимай пятки, "
        "опускай плавно.",
        "Не раскачивайся и не делай рывков."
    ),
    "wall_plank": (
        "Планка у стены",
        "Упрись предплечьями в стену, "
        "держи корпус ровно и дыши.",
        "Не задерживай дыхание и не проваливай поясницу."
    ),
    "leg_press": (
        "Жим ногами с лёгким весом",
        "Настрой тренажёр, двигай платформу "
        "плавно в комфортной амплитуде.",
        "Не отрывай таз и не блокируй колени."
    ),
    "lat_pull": (
        "Тяга верхнего блока",
        "Тяни рукоять к верхней части груди, "
        "опускай плечи и контролируй возврат.",
        "Не тяни за голову и не раскачивай корпус."
    ),
    "chest_press": (
        "Жим от груди в тренажёре",
        "Отрегулируй сиденье, жми плавно, "
        "не зажимай плечи.",
        "Не используй вес, при котором теряется контроль."
    ),
    "seated_row": (
        "Горизонтальная тяга",
        "Сиди устойчиво, тяни рукоять к корпусу, "
        "своди лопатки.",
        "Не округляй спину и не дёргай вес."
    ),
    "light_press": (
        "Жим гантелей с лёгким весом",
        "Сядь с опорой спины, плавно поднимай "
        "лёгкие гантели без боли.",
        "Не переразгибай поясницу."
    )
}


# ==================================
# БАЗА ДАННЫХ
# ==================================

def connect():
    return psycopg.connect(
        DB_URL,
        connect_timeout=10
    )


def init_db():
    with connect() as conn:
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

        for col in ("age_group", "minutes", "clearance"):
            conn.execute(
                f"ALTER TABLE profiles "
                f"ADD COLUMN IF NOT EXISTS {col} TEXT"
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
                    REFERENCES workouts(id) ON DELETE CASCADE,
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
            CREATE TABLE IF NOT EXISTS workout_sets (
                workout_id BIGINT NOT NULL,
                position INT NOT NULL,
                set_no INT NOT NULL,
                target_min INT NOT NULL,
                target_max INT NOT NULL,
                unit TEXT NOT NULL,
                actual_value INT,
                state TEXT NOT NULL DEFAULT 'pending',
                completed_at TIMESTAMPTZ,
                PRIMARY KEY (workout_id, position, set_no),
                FOREIGN KEY (workout_id, position)
                    REFERENCES workout_items(workout_id, position)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_inputs (
                chat_id BIGINT PRIMARY KEY,
                workout_id BIGINT NOT NULL,
                position INT NOT NULL,
                set_no INT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS workouts_chat_idx
            ON workouts(chat_id, started_at DESC)
        """)


# ==================================
# ИНТЕРФЕЙС
# ==================================

def kb(*items):
    markup = types.InlineKeyboardMarkup(row_width=1)

    for title, data in items:
        markup.add(
            types.InlineKeyboardButton(
                title,
                callback_data=data
            )
        )

    return markup


def respond(chat_id, text, items=(), edit_id=None):
    markup = kb(*items) if items else None

    if edit_id:
        try:
            bot.edit_message_text(
                text,
                chat_id,
                edit_id,
                reply_markup=markup
            )
            return
        except Exception:
            pass

    bot.send_message(
        chat_id,
        text,
        reply_markup=markup
    )


def main_menu(chat_id, edit_id=None):
    respond(
        chat_id,
        "💪 FORMIQ 8.0\n\n"
        "Тренировки, подходы и прогресс "
        "в одном месте.",
        [
            ("🏋️ Мой план", "plan"),
            ("▶️ Продолжить тренировку", "current"),
            ("📊 Статистика", "stats"),
            ("📖 История", "history"),
            ("👤 Профиль", "profile"),
            ("📝 Анкета", "restart")
        ],
        edit_id
    )


# ==================================
# АНКЕТА
# ==================================

def profile(chat_id):
    with connect() as conn:
        row = conn.execute("""
            SELECT goal, level, days, equipment,
                   age_group, minutes, clearance
            FROM profiles
            WHERE chat_id=%s
        """, (chat_id,)).fetchone()

    return dict(zip(FIELDS, row)) if row else {}


def show_profile(chat_id, edit_id=None):
    p = profile(chat_id)

    if not p or not any(p.values()):
        respond(
            chat_id,
            "Анкеты пока нет. Открой «Анкета».",
            [("📝 Анкета", "restart")],
            edit_id
        )
        return

    lines = [
        f"• {name}: "
        f"{LABELS.get((field, p.get(field)), '—')}"
        for field, name in zip(FIELDS, TITLES)
    ]

    respond(
        chat_id,
        "👤 Профиль FORMIQ\n\n" + "\n".join(lines),
        [
            ("🏋️ План", "plan"),
            ("🔄 Изменить анкету", "restart"),
            ("🏠 Меню", "menu")
        ],
        edit_id
    )


def reset_profile(chat_id):
    with connect() as conn:
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

    with connect() as conn:
        conn.execute("""
            INSERT INTO profiles(chat_id)
            VALUES (%s)
            ON CONFLICT DO NOTHING
        """, (chat_id,))

        conn.execute(
            f"UPDATE profiles "
            f"SET {field}=%s, updated_at=NOW() "
            f"WHERE chat_id=%s",
            (value, chat_id)
        )


def ask(chat_id, index, edit_id=None):
    if index >= len(QUESTIONS):
        show_profile(chat_id, edit_id)
        return

    _, question, choices = QUESTIONS[index]

    respond(
        chat_id,
        f"📝 Вопрос {index + 1}/{len(QUESTIONS)}"
        f"\n\n{question}",
        [
            (title, f"answer:{index}:{value}")
            for title, value in choices
        ],
        edit_id
    )


# ==================================
# ПЕРСОНАЛЬНЫЕ ПРОГРАММЫ
# ==================================

def last_day(chat_id):
    with connect() as conn:
        row = conn.execute("""
            SELECT plan_day
            FROM workouts
            WHERE chat_id=%s AND status='finished'
            ORDER BY finished_at DESC, id DESC
            LIMIT 1
        """, (chat_id,)).fetchone()

    return "B" if row and row[0] == "A" else "A"


def adjustment(chat_id, day):
    with connect() as conn:
        rows = conn.execute("""
            SELECT id, difficulty
            FROM workouts
            WHERE chat_id=%s
              AND plan_day=%s
              AND status='finished'
            ORDER BY finished_at DESC, id DESC
            LIMIT 2
        """, (chat_id, day)).fetchall()

        if rows and rows[0][1] == "hard":
            return (
                "lighter",
                "В прошлый раз было тяжело: "
                "на один подход меньше."
            )

        if len(rows) < 2 or any(
            row[1] != "easy" for row in rows
        ):
            return (
                "normal",
                "Работаем в комфортном темпе, без боли."
            )

        for wid, _ in rows:
            total, strong = conn.execute("""
                SELECT
                    COUNT(*),
                    COUNT(*) FILTER (
                        WHERE state='done'
                        AND actual_value >= target_max
                    )
                FROM workout_sets
                WHERE workout_id=%s
            """, (wid,)).fetchone()

            if not total or total != strong:
                return (
                    "normal",
                    "Пока сохраняем текущую нагрузку."
                )

    return (
        "more",
        "Два лёгких полных занятия: "
        "добавим по одному повторению."
    )


def plan_data(p, mode="normal"):
    if any(not p.get(field) for field in FIELDS):
        return None, "Заполни все 7 вопросов анкеты."

    if p["age_group"] != "adult":
        return None, "Тестовые планы доступны только для 18+."

    if p["clearance"] != "none":
        return None, (
            "При боли, травмах или сомнениях "
            "в безопасности нагрузки план пока "
            "не составляю. Уточни допустимую "
            "активность со специалистом."
        )

    minutes = int(p["minutes"])

    sets = (
        2 if p["level"] == "beginner"
        or minutes == 20
        else 3
    )

    if mode == "lighter":
        sets = max(1, sets - 1)

    low, high = (
        (9, 13) if mode == "more"
        else (8, 12)
    )

    if p["equipment"] == "gym":
        routines = {
            "A": [
                "leg_press",
                "lat_pull",
                "chest_press",
                "bridge"
            ],
            "B": [
                "step",
                "seated_row",
                "light_press",
                "bird"
            ]
        }
    else:
        routines = {
            "A": [
                "squat",
                "wall_push",
                "bridge",
                "bird"
            ],
            "B": [
                "step",
                "incline_push",
                "calf",
                "wall_plank"
            ]
        }

    count = 3 if minutes == 20 else 4

    result = {}

    for day, keys in routines.items():
        result[day] = []

        for key in keys[:count]:
            unit = (
                "sec" if key == "wall_plank"
                else "reps"
            )

            result[day].append((
                key,
                sets,
                15 if unit == "sec" else low,
                30 if unit == "sec" else high,
                unit
            ))

    return result, None


def show_plan(chat_id, edit_id=None):
    p = profile(chat_id)
    day = last_day(chat_id)
    mode, tip = adjustment(chat_id, day)
    plans, error = plan_data(p, mode)

    if error:
        respond(
            chat_id,
            error,
            [
                ("📝 Анкета", "restart"),
                ("🏠 Меню", "menu")
            ],
            edit_id
        )
        return

    days = min(
        int(p["days"]),
        3 if p["level"] == "beginner"
        else 4
    )

    lines = [
        f"🏋️ FORMIQ · {days} занятия/неделю "
        f"· {p['minutes']} мин",
        f"Следующая: {day}. {tip}",
        "Разминка 3–5 мин, заминка 2–3 мин, "
        "отдых 60–90 сек."
    ]

    for label, routine in plans.items():
        lines.append(f"\nДень {label}:")

        for key, sets, lo, hi, unit in routine:
            measure = (
                "сек" if unit == "sec"
                else "повт."
            )

            lines.append(
                f"• {EXERCISES[key][0]} — "
                f"{sets} × {lo}–{hi} {measure}"
            )

    lines.append(
        "\nМежду силовыми — день отдыха. "
        "При боли, головокружении или необычной "
        "одышке остановись. Это стартовый шаблон, "
        "не медицинское назначение."
    )

    respond(
        chat_id,
        "\n".join(lines),
        [
            (
                f"▶️ Начать следующую ({day})",
                "begin"
            ),
            ("📊 Статистика", "stats"),
            ("🏠 Меню", "menu")
        ],
        edit_id
    )


# ==================================
# ТРЕНИРОВКИ
# ==================================

def active_workout(chat_id):
    with connect() as conn:
        return conn.execute("""
            SELECT id
            FROM workouts
            WHERE chat_id=%s AND status='active'
            ORDER BY id DESC LIMIT 1
        """, (chat_id,)).fetchone()


def start_workout(chat_id, edit_id=None):
    p = profile(chat_id)
    day = last_day(chat_id)
    mode, _ = adjustment(chat_id, day)
    plans, error = plan_data(p, mode)

    if error:
        respond(chat_id, error, edit_id=edit_id)
        return

    with connect() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (chat_id,)
        )

        existing = conn.execute("""
            SELECT id
            FROM workouts
            WHERE chat_id=%s AND status='active'
            ORDER BY id DESC LIMIT 1
        """, (chat_id,)).fetchone()

        if existing:
            wid = existing[0]

        else:
            previous = conn.execute("""
                SELECT plan_day
                FROM workouts
                WHERE chat_id=%s AND status='finished'
                ORDER BY finished_at DESC, id DESC
                LIMIT 1
            """, (chat_id,)).fetchone()

            day = (
                "B" if previous and previous[0] == "A"
                else "A"
            )

            wid = conn.execute("""
                INSERT INTO workouts(chat_id, plan_day)
                VALUES (%s, %s)
                RETURNING id
            """, (chat_id, day)).fetchone()[0]

            for pos, item in enumerate(plans[day]):
                key, sets, low, high, unit = item
                title = EXERCISES[key][0]

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
                    pos,
                    title,
                    f"{sets} × {low}–{high}"
                ))

                for set_no in range(1, sets + 1):
                    conn.execute("""
                        INSERT INTO workout_sets(
                            workout_id,
                            position,
                            set_no,
                            target_min,
                            target_max,
                            unit
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        wid,
                        pos,
                        set_no,
                        low,
                        high,
                        unit
                    ))

    show_workout(chat_id, wid, edit_id)


def workout_summary(conn, wid, chat_id):
    return conn.execute("""
        SELECT plan_day, status
        FROM workouts
        WHERE id=%s AND chat_id=%s
    """, (wid, chat_id)).fetchone()


def show_workout(chat_id, wid, edit_id=None, note=""):
    with connect() as conn:
        workout = workout_summary(
            conn,
            wid,
            chat_id
        )

        if not workout:
            respond(
                chat_id,
                "Тренировка не найдена.",
                edit_id=edit_id
            )
            return

        day, status = workout

        sets = conn.execute("""
            SELECT
                s.position,
                s.set_no,
                s.target_min,
                s.target_max,
                s.unit,
                s.actual_value,
                s.state,
                i.exercise
            FROM workout_sets s
            JOIN workout_items i
                ON i.workout_id=s.workout_id
                AND i.position=s.position
            WHERE s.workout_id=%s
            ORDER BY s.position, s.set_no
        """, (wid,)).fetchall()

        legacy = not sets
        old_items = []

        if legacy:
            old_items = conn.execute("""
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

    if status != "active":
        respond(
            chat_id,
            "Эта тренировка уже завершена "
            "или отменена.",
            [("🏠 Меню", "menu")],
            edit_id
        )
        return

    if legacy:
        lines = [
            f"🏋️ Тренировка {day} (старая версия)"
        ]

        choices = []

        for pos, name, target, done, skipped in old_items:
            mark = (
                "✅" if done
                else "⏭" if skipped
                else "⬜"
            )

            lines.append(
                f"{mark} {name} · {target}"
            )

            if not done and not skipped:
                choices.extend([
                    (
                        f"✅ {name[:22]}",
                        f"legacy_done:{wid}:{pos}"
                    ),
                    (
                        f"⏭ {name[:22]}",
                        f"legacy_skip:{wid}:{pos}"
                    )
                ])

        choices.extend([
            ("🏁 Завершить", f"finish:{wid}"),
            ("❌ Отменить", f"cancel:{wid}")
        ])

        respond(
            chat_id,
            "\n".join(lines),
            choices,
            edit_id
        )
        return

    total = len(sets)

    done_count = sum(
        row[6] == "done"
        for row in sets
    )

    skipped_count = sum(
        row[6] == "skipped"
        for row in sets
    )

    pending = next(
        (row for row in sets if row[6] == "pending"),
        None
    )

    prefix = (
        note + "\n\n" if note
        else ""
    )

    lines = [
        f"🏋️ День {day} · выполнено "
        f"{done_count}/{total} подходов",
        f"Пропущено: {skipped_count}"
    ]

    if pending:
        pos, set_no, low, high, unit, _, _, title = pending

        tip = next(
            (
                x for x in EXERCISES.values()
                if x[0] == title
            ),
            None
        )

        unit_text = (
            "секунд" if unit == "sec"
            else "повторений"
        )

        lines.extend([
            f"\n🎯 {title}",
            f"Подход {set_no}: "
            f"цель {low}–{high} {unit_text}"
        ])

        if tip:
            lines.extend([
                f"✅ Техника: {tip[1]}",
                f"⚠️ Ошибка: {tip[2]}"
            ])

        choices = [
            (
                "📝 Записать результат подхода",
                f"set:{wid}:{pos}:{set_no}"
            ),
            (
                "⏭ Пропустить упражнение",
                f"skip_ex:{wid}:{pos}"
            ),
            (
                "🏁 Завершить досрочно",
                f"finish:{wid}"
            ),
            (
                "❌ Отменить тренировку",
                f"cancel:{wid}"
            )
        ]

    else:
        lines.append(
            "\n✅ Все подходы отмечены. "
            "Заверши тренировку и оцени нагрузку."
        )

        choices = [
            (
                "🏁 Завершить тренировку",
                f"finish:{wid}"
            ),
            ("❌ Отменить", f"cancel:{wid}")
        ]

    respond(
        chat_id,
        prefix + "\n".join(lines),
        choices,
        edit_id
    )


# ==================================
# ЗАПИСЬ ПОДХОДОВ
# ==================================

def record_prompt(
    chat_id,
    wid,
    pos,
    set_no,
    edit_id=None
):
    with connect() as conn:
        row = conn.execute("""
            SELECT
                s.target_min,
                s.target_max,
                s.unit,
                s.state,
                i.exercise
            FROM workout_sets s
            JOIN workout_items i
                ON i.workout_id=s.workout_id
                AND i.position=s.position
            JOIN workouts w
                ON w.id=s.workout_id
            WHERE s.workout_id=%s
              AND s.position=%s
              AND s.set_no=%s
              AND w.chat_id=%s
              AND w.status='active'
        """, (
            wid,
            pos,
            set_no,
            chat_id
        )).fetchone()

    if not row or row[3] != "pending":
        respond(
            chat_id,
            "Этот подход уже закрыт. "
            "Открой /workout.",
            edit_id=edit_id
        )
        return

    low, high, unit, _, title = row

    options = (
        [15, 20, 25, 30]
        if unit == "sec"
        else [6, 8, 10, 12, 15]
    )

    choices = [
        (
            str(n),
            f"value:{wid}:{pos}:{set_no}:{n}"
        )
        for n in options
    ]

    choices.extend([
        (
            "✍️ Ввести точное число",
            f"custom:{wid}:{pos}:{set_no}"
        ),
        (
            "↩️ К тренировке",
            "current"
        )
    ])

    respond(
        chat_id,
        f"📝 {title}\n"
        f"Подход {set_no}: "
        f"цель {low}–{high} "
        f"{'сек' if unit == 'sec' else 'повт.'}"
        "\n\nСколько получилось на самом деле?",
        choices,
        edit_id
    )


def refresh_item(conn, wid, pos):
    count, pending, skipped = conn.execute("""
        SELECT
            COUNT(*),
            COUNT(*) FILTER (WHERE state='pending'),
            COUNT(*) FILTER (WHERE state='skipped')
        FROM workout_sets
        WHERE workout_id=%s AND position=%s
    """, (wid, pos)).fetchone()

    if count:
        conn.execute("""
            UPDATE workout_items
            SET done=%s, skipped=%s
            WHERE workout_id=%s AND position=%s
        """, (
            pending == 0 and skipped == 0,
            pending == 0 and skipped > 0,
            wid,
            pos
        ))


def record_set(
    chat_id,
    wid,
    pos,
    set_no,
    actual,
    edit_id=None
):
    if (
        not isinstance(actual, int)
        or not 1 <= actual <= 120
    ):
        respond(
            chat_id,
            "Введи целое положительное "
            "число до 120.",
            edit_id=edit_id
        )
        return

    with connect() as conn:
        changed = conn.execute("""
            UPDATE workout_sets s
            SET
                actual_value=%s,
                state='done',
                completed_at=NOW()
            WHERE s.workout_id=%s
              AND s.position=%s
              AND s.set_no=%s
              AND s.state='pending'
              AND EXISTS (
                  SELECT 1
                  FROM workouts w
                  WHERE w.id=s.workout_id
                    AND w.chat_id=%s
                    AND w.status='active'
              )
            RETURNING s.unit
        """, (
            actual,
            wid,
            pos,
            set_no,
            chat_id
        )).fetchone()

        if changed:
            refresh_item(conn, wid, pos)

            conn.execute(
                "DELETE FROM pending_inputs "
                "WHERE chat_id=%s",
                (chat_id,)
            )

    if not changed:
        respond(
            chat_id,
            "Подход уже записан или тренировка "
            "закрыта. /workout",
            edit_id=edit_id
        )
        return

    measure = (
        "сек" if changed[0] == "sec"
        else "повт."
    )

    show_workout(
        chat_id,
        wid,
        edit_id,
        f"✅ Записано: {actual} {measure}. "
        "Отдохни 60–90 секунд."
    )


def skip_exercise(
    chat_id,
    wid,
    pos,
    edit_id=None
):
    with connect() as conn:
        changed = conn.execute("""
            UPDATE workout_sets s
            SET
                state='skipped',
                completed_at=NOW()
            WHERE s.workout_id=%s
              AND s.position=%s
              AND s.state='pending'
              AND EXISTS (
                  SELECT 1
                  FROM workouts w
                  WHERE w.id=s.workout_id
                    AND w.chat_id=%s
                    AND w.status='active'
              )
            RETURNING set_no
        """, (
            wid,
            pos,
            chat_id
        )).fetchall()

        if changed:
            refresh_item(conn, wid, pos)

    show_workout(
        chat_id,
        wid,
        edit_id,
        "⏭ Оставшиеся подходы "
        "упражнения пропущены."
    )


def mark_legacy(
    chat_id,
    wid,
    pos,
    skip,
    edit_id=None
):
    with connect() as conn:
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
            RETURNING position
        """, (
            not skip,
            skip,
            wid,
            pos,
            chat_id
        )).fetchone()

    show_workout(
        chat_id,
        wid,
        edit_id,
        "✅ Записано." if changed
        else "Уже отмечено."
    )


def finish(chat_id, wid, edit_id=None):
    with connect() as conn:
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

        if changed:
            positions = conn.execute("""
                UPDATE workout_sets
                SET
                    state='skipped',
                    completed_at=NOW()
                WHERE workout_id=%s
                  AND state='pending'
                RETURNING position
            """, (wid,)).fetchall()

            for pos in set(
                row[0] for row in positions
            ):
                refresh_item(conn, wid, pos)

            conn.execute(
                "DELETE FROM pending_inputs "
                "WHERE chat_id=%s",
                (chat_id,)
            )

    if not changed:
        respond(
            chat_id,
            "Тренировка уже закрыта.",
            edit_id=edit_id
        )
        return

    respond(
        chat_id,
        "🏁 Тренировка сохранена. "
        "Как ощущалась нагрузка?",
        [
            ("🙂 Легко", f"rate:{wid}:easy"),
            ("💪 Нормально", f"rate:{wid}:ok"),
            ("😮‍💨 Тяжело", f"rate:{wid}:hard")
        ],
        edit_id
    )


def rate(
    chat_id,
    wid,
    difficulty,
    edit_id=None
):
    if difficulty not in ("easy", "ok", "hard"):
        return

    with connect() as conn:
        changed = conn.execute("""
            UPDATE workouts
            SET difficulty=%s
            WHERE id=%s
              AND chat_id=%s
              AND status='finished'
              AND difficulty IS NULL
            RETURNING id
        """, (
            difficulty,
            wid,
            chat_id
        )).fetchone()

    respond(
        chat_id,
        "✅ Оценка записана."
        if changed
        else "Оценка уже сохранена.",
        [
            ("📊 Статистика", "stats"),
            ("🏠 Меню", "menu")
        ],
        edit_id
    )


# ==================================
# БЕЗОПАСНОСТЬ ПОДТВЕРЖДЕНИЙ
# ==================================

def signed(kind, chat_id, wid, until):
    msg = (
        f"{kind}:{chat_id}:{wid}:{until}"
    ).encode()

    return hmac.new(
        TOKEN.encode(),
        msg,
        hashlib.sha256
    ).hexdigest()[:12]


def check_sign(
    kind,
    chat_id,
    wid,
    until,
    signature
):
    return (
        time.time() <= until
        and hmac.compare_digest(
            signed(kind, chat_id, wid, until),
            signature
        )
    )


def ask_cancel(chat_id, wid, edit_id=None):
    until = int(time.time()) + 600
    token = signed(
        "cancel",
        chat_id,
        wid,
        until
    )

    respond(
        chat_id,
        "Точно отменить тренировку? "
        "Она не попадёт в статистику.",
        [
            (
                "❌ Да, отменить",
                f"cancel_yes:{wid}:{until}:{token}"
            ),
            (
                "↩️ Продолжить",
                "current"
            )
        ],
        edit_id
    )


def cancel(chat_id, wid, edit_id=None):
    with connect() as conn:
        deleted = conn.execute("""
            DELETE FROM workouts
            WHERE id=%s
              AND chat_id=%s
              AND status='active'
            RETURNING id
        """, (wid, chat_id)).fetchone()

        conn.execute(
            "DELETE FROM pending_inputs "
            "WHERE chat_id=%s",
            (chat_id,)
        )

    respond(
        chat_id,
        "Тренировка отменена."
        if deleted
        else "Она уже закрыта.",
        [("🏠 Меню", "menu")],
        edit_id
    )


# ==================================
# СТАТИСТИКА И ИСТОРИЯ
# ==================================

def stats(chat_id, edit_id=None):
    with connect() as conn:
        numbers = conn.execute("""
            SELECT
                COUNT(*) FILTER (
                    WHERE finished_at >=
                    NOW()-INTERVAL '7 days'
                ),
                COUNT(*) FILTER (
                    WHERE finished_at >=
                    NOW()-INTERVAL '30 days'
                ),
                COUNT(*)
            FROM workouts
            WHERE chat_id=%s
              AND status='finished'
        """, (chat_id,)).fetchone()

        legacy = conn.execute("""
            SELECT
                COUNT(*) FILTER (WHERE i.done),
                COUNT(*) FILTER (WHERE i.skipped)
            FROM workout_items i
            JOIN workouts w ON w.id=i.workout_id
            WHERE w.chat_id=%s
              AND w.status='finished'
              AND NOT EXISTS (
                  SELECT 1
                  FROM workout_sets s
                  WHERE s.workout_id=w.id
              )
        """, (chat_id,)).fetchone()

        modern = conn.execute("""
            SELECT
                COUNT(*) FILTER (
                    WHERE s.state='done'
                ),
                COUNT(*) FILTER (
                    WHERE s.state='skipped'
                )
            FROM workout_sets s
            JOIN workouts w ON w.id=s.workout_id
            WHERE w.chat_id=%s
              AND w.status='finished'
        """, (chat_id,)).fetchone()

    p = profile(chat_id)

    if p.get("days") in (
        "2", "3", "4", "5"
    ):
        target = min(
            int(p["days"]),
            3 if p.get("level") == "beginner"
            else 4
        )
    else:
        target = 0

    weekly = (
        f"{numbers[0]}/{target}"
        if target
        else str(numbers[0])
    )

    respond(
        chat_id,
        "📊 FORMIQ · Прогресс\n\n"
        f"За 7 дней: {weekly} тренировок\n"
        f"За 30 дней: {numbers[1]}\n"
        f"Всего завершено: {numbers[2]}\n"
        f"Подходов записано: {modern[0]}\n"
        f"Подходов пропущено: {modern[1]}\n"
        f"Старых упражнений выполнено: {legacy[0]}\n"
        f"Старых пропущено: {legacy[1]}",
        [
            ("📖 История", "history"),
            ("🏠 Меню", "menu")
        ],
        edit_id
    )


def history(chat_id, edit_id=None):
    with connect() as conn:
        rows = conn.execute("""
            SELECT
                w.id,
                w.plan_day,
                w.started_at,
                w.difficulty,
                (
                    SELECT COUNT(*)
                    FROM workout_sets s
                    WHERE s.workout_id=w.id
                      AND s.state='done'
                ),
                (
                    SELECT COUNT(*)
                    FROM workout_sets s
                    WHERE s.workout_id=w.id
                )
            FROM workouts w
            WHERE w.chat_id=%s
              AND w.status='finished'
            ORDER BY w.finished_at DESC, w.id DESC
            LIMIT 10
        """, (chat_id,)).fetchall()

    if not rows:
        respond(
            chat_id,
            "Пока нет завершённых тренировок.",
            [("🏠 Меню", "menu")],
            edit_id
        )
        return

    labels = {
        "easy": "легко",
        "ok": "нормально",
        "hard": "тяжело"
    }

    lines = ["📖 Последние занятия:"]

    for (
        wid,
        day,
        started,
        difficulty,
        done,
        total
    ) in rows:
        progress = (
            f"{done}/{total} подходов"
            if total
            else "старая версия"
        )

        lines.append(
            f"• {started:%d.%m} · {day} · "
            f"{progress} · "
            f"{labels.get(difficulty, 'без оценки')}"
        )

    respond(
        chat_id,
        "\n".join(lines),
        [("🏠 Меню", "menu")],
        edit_id
    )


# ==================================
# УДАЛЕНИЕ ПРОФИЛЯ
# ==================================

def confirm_delete(chat_id, edit_id=None):
    until = int(time.time()) + 600

    token = signed(
        "delete",
        chat_id,
        0,
        until
    )

    respond(
        chat_id,
        "Удалить анкету и историю FORMIQ "
        "без возможности восстановления?",
        [
            (
                "🗑 Подтвердить удаление",
                f"delete_yes:{until}:{token}"
            ),
            (
                "↩️ Не удалять",
                "menu"
            )
        ],
        edit_id
    )


def delete_all(chat_id, edit_id=None):
    with connect() as conn:
        conn.execute(
            "DELETE FROM workouts "
            "WHERE chat_id=%s",
            (chat_id,)
        )

        conn.execute(
            "DELETE FROM profiles "
            "WHERE chat_id=%s",
            (chat_id,)
        )

        conn.execute(
            "DELETE FROM pending_inputs "
            "WHERE chat_id=%s",
            (chat_id,)
        )

    respond(
        chat_id,
        "Профиль и дневник удалены из базы "
        "FORMIQ. Переписка в Telegram и внешние "
        "резервные копии не удаляются.",
        [("🏠 Меню", "menu")],
        edit_id
    )


# ==================================
# КОМАНДЫ TELEGRAM
# ==================================

@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    if message.chat.type == "private":
        main_menu(message.chat.id)


@bot.message_handler(
    commands=[
        "plan", "profile", "workout",
        "stats", "progress", "history",
        "delete_me"
    ]
)
def cmd_routes(message):
    if message.chat.type != "private":
        return

    chat_id = message.chat.id
    command = message.text.split()[0].split("@")[0]

    if command == "/plan":
        show_plan(chat_id)

    elif command == "/profile":
        show_profile(chat_id)

    elif command == "/workout":
        active = active_workout(chat_id)

        if active:
            show_workout(chat_id, active[0])
        else:
            respond(
                chat_id,
                "Нет активной тренировки. /plan"
            )

    elif command == "/stats":
        stats(chat_id)

    elif command in ("/progress", "/history"):
        history(chat_id)

    elif command == "/delete_me":
        confirm_delete(chat_id)


@bot.message_handler(commands=["coach", "nutrition"])
def cmd_soon(message):
    if message.chat.type == "private":
        bot.send_message(
            message.chat.id,
            "ИИ и питание пока в разработке. "
            "Основные функции: /start"
        )


# Точное число повторений текстом
@bot.message_handler(
    content_types=["text"],
    func=lambda m: True
)
def numeric_result(message):
    if message.chat.type != "private":
        return

    chat_id = message.chat.id

    with connect() as conn:
        pending = conn.execute("""
            SELECT
                workout_id,
                position,
                set_no
            FROM pending_inputs
            WHERE chat_id=%s
        """, (chat_id,)).fetchone()

    if not pending:
        main_menu(chat_id)
        return

    try:
        value = int(message.text.strip())
    except ValueError:
        bot.send_message(
            chat_id,
            "Напиши число, например 9, "
            "или открой /workout."
        )
        return

    if not 1 <= value <= 120:
        bot.send_message(
            chat_id,
            "Укажи число от 1 до 120."
        )
        return

    record_set(
        chat_id,
        *pending,
        value
    )


# ==================================
# CALLBACK-КНОПКИ
# ==================================

@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    chat_id = call.message.chat.id

    if (
        call.message.chat.type != "private"
        or call.from_user.id != chat_id
    ):
        bot.answer_callback_query(
            call.id,
            "Только личный чат."
        )
        return

    bot.answer_callback_query(call.id)

    data = call.data or ""
    edit_id = call.message.message_id

    try:
        if data == "menu":
            main_menu(chat_id, edit_id)

        elif data == "profile":
            show_profile(chat_id, edit_id)

        elif data == "restart":
            respond(
                chat_id,
                "Начать анкету заново? "
                "История тренировок сохранится.",
                [
                    ("Да, начать", "restart_yes"),
                    ("Нет", "menu")
                ],
                edit_id
            )

        elif data == "restart_yes":
            reset_profile(chat_id)
            ask(chat_id, 0, edit_id)

        elif data == "plan":
            show_plan(chat_id, edit_id)

        elif data == "current":
            active = active_workout(chat_id)

            if active:
                show_workout(
                    chat_id,
                    active[0],
                    edit_id
                )
            else:
                respond(
                    chat_id,
                    "Нет активной тренировки.",
                    [("🏋️ План", "plan")],
                    edit_id
                )

        elif (
            data == "begin"
            or data.startswith("begin:")
        ):
            start_workout(chat_id, edit_id)

        elif data == "stats":
            stats(chat_id, edit_id)

        elif data == "history":
            history(chat_id, edit_id)

        elif data.startswith("answer:"):
            _, number, value = data.split(":", 2)
            index = int(number)

            field, _, choices = QUESTIONS[index]

            if value not in {
                v for _, v in choices
            }:
                return

            p = profile(chat_id)

            expected = next(
                (
                    i
                    for i, key in enumerate(FIELDS)
                    if not p.get(key)
                ),
                len(FIELDS)
            )

            if index != expected:
                respond(
                    chat_id,
                    "Этот шаг устарел. "
                    "Начни заново.",
                    [("📝 Анкета", "restart")],
                    edit_id
                )
                return

            save_answer(chat_id, field, value)

            ask(
                chat_id,
                index + 1,
                edit_id
            )

        elif data.startswith("set:"):
            _, wid, pos, set_no = data.split(":")

            record_prompt(
                chat_id,
                int(wid),
                int(pos),
                int(set_no),
                edit_id
            )

        elif data.startswith("value:"):
            _, wid, pos, set_no, value = data.split(":")

            record_set(
                chat_id,
                int(wid),
                int(pos),
                int(set_no),
                int(value),
                edit_id
            )

        elif data.startswith("custom:"):
            _, wid, pos, set_no = data.split(":")

            wid = int(wid)
            pos = int(pos)
            set_no = int(set_no)

            with connect() as conn:
                permitted = conn.execute("""
                    SELECT 1
                    FROM workout_sets s
                    JOIN workouts w
                        ON w.id=s.workout_id
                    WHERE s.workout_id=%s
                      AND s.position=%s
                      AND s.set_no=%s
                      AND s.state='pending'
                      AND w.chat_id=%s
                      AND w.status='active'
                """, (
                    wid,
                    pos,
                    set_no,
                    chat_id
                )).fetchone()

                if permitted:
                    conn.execute("""
                        INSERT INTO pending_inputs(
                            chat_id,
                            workout_id,
                            position,
                            set_no
                        )
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT(chat_id)
                        DO UPDATE SET
                            workout_id=EXCLUDED.workout_id,
                            position=EXCLUDED.position,
                            set_no=EXCLUDED.set_no,
                            created_at=NOW()
                    """, (
                        chat_id,
                        wid,
                        pos,
                        set_no
                    ))

            if not permitted:
                respond(
                    chat_id,
                    "Подход уже закрыт. "
                    "Открой /workout.",
                    edit_id=edit_id
                )
            else:
                respond(
                    chat_id,
                    "Напиши точное число повторений "
                    "или секунд одним сообщением, "
                    "от 1 до 120. Чтобы вернуться, "
                    "нажми /workout.",
                    [("↩️ Назад", "current")],
                    edit_id
                )

        elif data.startswith("skip_ex:"):
            _, wid, pos = data.split(":")

            skip_exercise(
                chat_id,
                int(wid),
                int(pos),
                edit_id
            )

        elif (
            data.startswith("legacy_done:")
            or data.startswith("legacy_skip:")
        ):
            action, wid, pos = data.split(":")

            mark_legacy(
                chat_id,
                int(wid),
                int(pos),
                action == "legacy_skip",
                edit_id
            )

        elif (
            data.startswith("done:")
            or data.startswith("skip:")
        ):
            action, wid, pos = data.split(":")

            mark_legacy(
                chat_id,
                int(wid),
                int(pos),
                action == "skip",
                edit_id
            )

        elif data.startswith("finish:"):
            finish(
                chat_id,
                int(data.split(":")[1]),
                edit_id
            )

        elif data.startswith("rate:"):
            _, wid, rating_value = data.split(":", 2)

            rate(
                chat_id,
                int(wid),
                rating_value,
                edit_id
            )

        elif data.startswith("cancel:"):
            ask_cancel(
                chat_id,
                int(data.split(":")[1]),
                edit_id
            )

        elif data.startswith("cancel_yes:"):
            _, wid, until, sig = data.split(":", 3)

            if check_sign(
                "cancel",
                chat_id,
                int(wid),
                int(until),
                sig
            ):
                cancel(
                    chat_id,
                    int(wid),
                    edit_id
                )
            else:
                respond(
                    chat_id,
                    "Подтверждение устарело.",
                    edit_id=edit_id
                )

        elif data.startswith("delete_yes:"):
            _, until, sig = data.split(":", 2)

            if check_sign(
                "delete",
                chat_id,
                0,
                int(until),
                sig
            ):
                delete_all(chat_id, edit_id)
            else:
                respond(
                    chat_id,
                    "Подтверждение устарело.",
                    edit_id=edit_id
                )

        else:
            respond(
                chat_id,
                "Старая кнопка. Открой /start.",
                edit_id=edit_id
            )

    except (ValueError, IndexError):
        respond(
            chat_id,
            "Кнопка устарела. Открой /start.",
            edit_id=edit_id
        )


# ==================================
# WEBHOOK И ЗАПУСК
# ==================================

@app.get("/")
def health():
    return "FORMIQ 8.0 online", 200


@app.post("/telegram-webhook")
def webhook():
    received = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token",
        ""
    )

    if not hmac.compare_digest(
        received,
        SECRET
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
        secret_token=SECRET,
        drop_pending_updates=False
    )

    logger.info("FORMIQ 8.0 online")

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False
    )

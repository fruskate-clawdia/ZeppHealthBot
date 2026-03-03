#!/usr/bin/env python3
"""
🏥 ZeppHealthBot — AI Health Assistant for Amazfit/Zepp watches
Connects your Amazfit watch data with Telegram + Claude AI

GitHub: https://github.com/fruskate-clawdia/ZeppHealthBot
"""

import json
import sqlite3
import os
import re
import base64
import tempfile
import logging
from datetime import datetime, time
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import anthropic

# === Config (from .env or environment variables) ===
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
HEALTH_DATA_FILE = os.environ.get("HEALTH_DATA_FILE", "/data/health_data.json")
DB_FILE = os.environ.get("DB_FILE", "/data/health.db")
ALLOWED_USER = int(os.environ["TELEGRAM_USER_ID"])

# User profile (customize in .env)
USER_NAME = os.environ.get("USER_NAME", "Friend")
USER_WEIGHT = int(os.environ.get("USER_WEIGHT", "80"))
USER_AGE = int(os.environ.get("USER_AGE", "35"))
USER_GOAL_WEIGHT = int(os.environ.get("USER_GOAL_WEIGHT", "70"))
DAILY_CALORIES = int(os.environ.get("DAILY_CALORIES", "2000"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

SYSTEM_PROMPT = f"""You are a personal AI health assistant for {USER_NAME} ({USER_AGE} years old, {USER_WEIGHT}kg, goal: {USER_GOAL_WEIGHT}kg).

Data comes from their Amazfit/Zepp smartwatch via webhook.
Be concise, friendly, and motivating. Use emojis for structure instead of markdown.
Write in the same language the user uses.

WATCH DATA FIELDS EXPLAINED:
- sleep.info.score — Sleep quality score 0-100. Good: 75+, Great: 80+
- sleep.info.totalTime — Total sleep in minutes
- sleep.info.deepTime — Deep sleep minutes (target: 90-120 min)
- heart_rate.last — Latest heart rate reading
- heart_rate.resting — Resting heart rate (target: 60-70 bpm)
- heart_rate.summary.maximum.hr_value — Max heart rate today
- stress.current.value — Stress level 0-100 (from HRV). <40 normal, 40-60 moderate, 60+ high
- steps.current / steps.target — Steps taken vs daily goal
- calorie.current — CALORIES BURNED through activity today (NOT consumed!) target: {DAILY_CALORIES}
- calorie.target — Daily calorie burn target
- distance.current — Distance traveled in meters
- blood_oxygen.current.value — SpO2 % (normal: 95-100%)
- workout.status.vo2Max — VO2 max fitness score
- pai.week — Weekly PAI score (target: 100+)
- battery.current — Watch battery %
- body_temperature.current.value — Body temp in 1/100 degrees (3650 = 36.5°C)

USER GOALS:
- Lose weight from {USER_WEIGHT}kg to {USER_GOAL_WEIGHT}kg
- Daily calorie intake limit for weight loss: {DAILY_CALORIES} kcal
- Improve VO2 max and PAI weekly score

IMPORTANT: No markdown formatting. Use emojis for structure instead."""


def init_db():
    Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS food_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT,
            calories INTEGER,
            protein REAL,
            fat REAL,
            carbs REAL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT,
            content TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()
    conn.close()


def load_health_data() -> dict:
    try:
        with open(HEALTH_DATA_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def format_health_summary(d: dict) -> str:
    if not d:
        return "No data from watch yet."

    lines = []
    received = d.get("_received_at", "")[:16].replace("T", " ")
    lines.append(f"📊 Data as of {received}\n")

    if "sleep" in d:
        s = d["sleep"].get("info", {})
        score = s.get("score", "?")
        total = s.get("totalTime", 0)
        deep = s.get("deepTime", 0)
        h, m = divmod(total, 60)
        lines.append(f"😴 Sleep: {h}h {m}min | score {score}/100 | deep {deep} min")

    if "heart_rate" in d:
        hr = d["heart_rate"]
        last = hr.get("last", "?")
        rest = hr.get("resting", "?")
        mx = hr.get("summary", {}).get("maximum", {}).get("hr_value", 0)
        line = f"❤️ Heart rate: {last} bpm | resting {rest}"
        if mx > 0:
            line += f" | max {mx}"
        lines.append(line)

    if "stress" in d:
        sv = d["stress"].get("current", {})
        val = sv.get("value", "?") if isinstance(sv, dict) else sv
        lines.append(f"🧠 Stress: {val}/100")

    if "steps" in d:
        s = d["steps"]
        lines.append(f"👟 Steps: {s.get('current', 0)} / {s.get('target', 10000)}")

    if "calorie" in d:
        c = d["calorie"]
        lines.append(f"🔥 Calories burned: {c.get('current', 0)} / {c.get('target', 0)}")

    if "blood_oxygen" in d:
        bo = d["blood_oxygen"].get("current", {})
        val = bo.get("value", 0) if isinstance(bo, dict) else 0
        if val > 0:
            lines.append(f"🩸 SpO2: {val}%")

    if "workout" in d:
        vo2 = d["workout"].get("status", {}).get("vo2Max", 0)
        pai = d.get("pai", {}).get("week", 0)
        if vo2:
            lines.append(f"🏃 VO2 max: {vo2} | Weekly PAI: {pai}/100")

    if "battery" in d:
        b = d["battery"].get("current", "?")
        emoji = "🔋" if isinstance(b, int) and b > 30 else "🪫"
        lines.append(f"{emoji} Battery: {b}%")

    return "\n".join(lines)


def ask_claude(user_message: str, health_data: dict) -> str:
    health_summary = format_health_summary(health_data)
    response = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Current watch data:\n{health_summary}\n\n{user_message}"
        }]
    )
    return response.content[0].text


async def check_allowed(update: Update) -> bool:
    if update.effective_user.id != ALLOWED_USER:
        await update.message.reply_text("This bot is private 🔒")
        return False
    return True


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    await update.message.reply_text(
        f"👋 Hello, {USER_NAME}!\n\n"
        "I'm your personal HealthBot 🏥\n"
        f"Tracking your Amazfit watch data.\n"
        f"Goal: {USER_WEIGHT}kg → {USER_GOAL_WEIGHT}kg 💪\n\n"
        "Commands:\n"
        "/status — current watch data\n"
        "/sleep — sleep analysis\n"
        "/workout — workout analysis\n"
        "/week — weekly summary\n"
        "/advice — today's recommendation\n"
        "/food_log — today's food diary\n\n"
        "📸 Send a food photo — I'll count calories!\n"
        "💬 Or just ask me anything"
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    data = load_health_data()
    await update.message.reply_text(format_health_summary(data) if data else "No watch data yet 😔")


async def cmd_sleep(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    data = load_health_data()
    if not data:
        await update.message.reply_text("No watch data yet 😔")
        return
    await update.message.chat.send_action("typing")
    reply = ask_claude("Analyze my sleep in detail. How does it affect health and weight loss? What should I improve?", data)
    await update.message.reply_text(reply)


async def cmd_workout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    data = load_health_data()
    history = data.get("workout", {}).get("history", [])
    if not history:
        await update.message.reply_text("No workout data yet 😔")
        return
    await update.message.chat.send_action("typing")
    recent = []
    for w in history[:5]:
        ts = w["startTime"] // 1000
        dt = datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
        mins = w["duration"] // 1000 // 60
        recent.append(f"• {dt} — {mins} min")
    workouts_text = "\n".join(recent)
    reply = ask_claude(
        f"Last 5 workouts:\n{workouts_text}\n\nAnalyze my activity. Is it enough for weight loss? What should I add?",
        data
    )
    await update.message.reply_text(reply)


async def cmd_advice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    data = load_health_data()
    if not data:
        await update.message.reply_text("No watch data yet 😔")
        return
    await update.message.chat.send_action("typing")
    reply = ask_claude("Give me a specific recommendation for today — what to do for health and weight loss. Short, 3-5 points.", data)
    await update.message.reply_text(reply)


async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    data = load_health_data()
    await update.message.chat.send_action("typing")
    stress_week = data.get("stress", {}).get("last_week", [])
    pai_week = data.get("pai", {}).get("last_week", [])
    reply = ask_claude(
        f"Weekly data:\nStress by day: {stress_week}\nPAI by day: {pai_week}\n\nGive me a weekly summary. Trends, what's good, what needs improvement.",
        data
    )
    await update.message.reply_text(reply)


async def cmd_food_log(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute(
        "SELECT created_at, description, calories, protein, fat, carbs FROM food_entries WHERE date(created_at)=date('now','localtime') ORDER BY created_at"
    ).fetchall()
    totals = conn.execute(
        "SELECT COALESCE(SUM(calories),0), COALESCE(SUM(protein),0), COALESCE(SUM(fat),0), COALESCE(SUM(carbs),0) FROM food_entries WHERE date(created_at)=date('now','localtime')"
    ).fetchone()
    conn.close()

    if not rows:
        await update.message.reply_text("No food logged today 🍽️\nSend a photo of your meal!")
        return

    text = "🍽️ Food diary today:\n\n"
    for row in rows:
        time = row[0][11:16]
        kcal = row[2]
        text += f"🕐 {time} — {kcal} kcal\n"

    cal, prot, fat, carb = totals
    remaining = DAILY_CALORIES - cal
    text += f"\nTotal: {cal} / {DAILY_CALORIES} kcal"
    text += f" ({'%d left' % remaining if remaining > 0 else '⚠️ over by %d' % abs(remaining)})"
    text += f"\nMacros: P {prot:.0f}g / F {fat:.0f}g / C {carb:.0f}g"
    await update.message.reply_text(text)


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    await update.message.chat.send_action("typing")

    photo = update.message.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    await file.download_to_drive(tmp_path)

    with open(tmp_path, "rb") as f:
        img_data = base64.standard_b64encode(f.read()).decode("utf-8")
    os.unlink(tmp_path)

    caption = update.message.caption or "What food is this? Calculate calories and macros."

    conn = sqlite3.connect(DB_FILE)
    today_total = conn.execute(
        "SELECT COALESCE(SUM(calories),0) FROM food_entries WHERE date(created_at)=date('now','localtime')"
    ).fetchone()[0]
    conn.close()

    food_system = SYSTEM_PROMPT + f"""

You are tracking food intake. Today already consumed: {today_total} kcal of {DAILY_CALORIES} kcal limit.
Remaining: {DAILY_CALORIES - today_total} kcal.

IMPORTANT: At the end of your response add exactly this line:
CALORIES:number|PROTEIN:number|FAT:number|CARBS:number
Example: CALORIES:450|PROTEIN:35|FAT:12|CARBS:40
Integers only, no units."""

    response = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=700,
        system=food_system,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_data}},
                {"type": "text", "text": caption}
            ]
        }]
    )
    full_reply = response.content[0].text

    calories, protein, fat, carbs = 0, 0.0, 0.0, 0.0
    match = re.search(r'CALORIES:(\d+)\|PROTEIN:(\d+)\|FAT:(\d+)\|CARBS:(\d+)', full_reply)
    if match:
        calories = int(match.group(1))
        protein = float(match.group(2))
        fat = float(match.group(3))
        carbs = float(match.group(4))

    reply = re.sub(r'\nCALORIES:\d+\|PROTEIN:\d+\|FAT:\d+\|CARBS:\d+', '', full_reply).strip()
    new_total = today_total + calories
    reply += f"\n\n📊 Today total: {new_total} / {DAILY_CALORIES} kcal"
    reply += f" ({'%d left' % (DAILY_CALORIES - new_total) if new_total <= DAILY_CALORIES else '⚠️ over by %d' % (new_total - DAILY_CALORIES)})"

    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT INTO food_entries (description, calories, protein, fat, carbs) VALUES (?, ?, ?, ?, ?)",
        (reply[:300], calories, protein, fat, carbs)
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(reply)


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    data = load_health_data()
    await update.message.chat.send_action("typing")
    reply = ask_claude(update.message.text, data)
    await update.message.reply_text(reply)


def main():
    init_db()
    log.info("🏥 ZeppHealthBot started")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("sleep", cmd_sleep))
    app.add_handler(CommandHandler("workout", cmd_workout))
    app.add_handler(CommandHandler("advice", cmd_advice))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("food_log", cmd_food_log))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Morning report at 08:00 local time (set MORNING_REPORT_UTC_HOUR env var, default 2 = UTC+6 08:00)
    report_hour = int(os.environ.get("MORNING_REPORT_UTC_HOUR", "2"))
    app.job_queue.run_daily(
        morning_report_job,
        time=time(hour=report_hour, minute=0),
        name="morning_report"
    )
    log.info(f"✅ Morning report scheduled at UTC {report_hour:02d}:00")

    app.run_polling(drop_pending_updates=True)


async def send_morning_report(app):
    """Send morning health summary"""
    data = load_health_data()
    if not data:
        return
    summary = format_health_summary(data)
    advice = ask_claude(
        "Morning summary. Briefly: how was the night, what's important today, one tip.",
        data
    )
    text = f"🌅 Good morning!\n\n{summary}\n\n💡 {advice}"
    await app.bot.send_message(chat_id=ALLOWED_USER, text=text)


async def morning_report_job(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue wrapper for morning report"""
    await send_morning_report(context.application)


if __name__ == "__main__":
    main()

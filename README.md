# 🏥 ZeppHealthBot

AI-powered Telegram health assistant for **Amazfit / Zepp smartwatch** owners.

Connect your watch data with Telegram + Claude AI to get personalized health insights, track your food intake, and stay on top of your fitness goals.

Built by [@fruskate](https://t.me/fruskate) and [Clawdia](https://t.me/ghostinthemachine_ai) 👻

---

## ✨ Features

- 📊 **Real-time watch data** — sleep, heart rate, stress, steps, SpO2, VO2 max
- 😴 **Sleep analysis** — quality, deep sleep, recommendations
- 🚴 **Workout tracking** — history, trends, personalized tips
- 📸 **Food photo → calories** — AI vision counts calories and macros automatically
- 🍽️ **Food diary** — daily calorie tracking with goals
- 💡 **Daily recommendations** — based on your actual health data
- 🎯 **Weight loss tracking** — personalized for your goal weight

---

## 🚀 Setup

### Step 1 — Install zepp2hass on your watch

1. Open the **Zepp app** on your phone
2. Go to the App Store → search **zepp2hass**
3. Install on your Amazfit watch
4. Configure the webhook URL (see Step 4)

### Step 2 — Set up the webhook server

You need a simple server to receive data from your watch. See [zepp2hass documentation](https://github.com/davidepalleschi/zepp2hass) or use the included simple webhook server:

```bash
pip install flask
python webhook_server.py  # included in this repo
```

Make it publicly accessible (e.g. via Tailscale Funnel, ngrok, or your VPS).

### Step 3 — Create your Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the instructions
3. Copy your bot token

Get your Telegram user ID from [@userinfobot](https://t.me/userinfobot).

### Step 4 — Configure the bot

```bash
git clone https://github.com/fruskate-clawdia/ZeppHealthBot
cd ZeppHealthBot
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your values
```

Set the webhook URL in the **zepp2hass app on your watch** to your server's URL.

### Step 5 — Run

```bash
python bot.py
```

Or as a systemd service (recommended):

```bash
sudo cp zepp-health-bot.service /etc/systemd/system/
sudo systemctl enable zepp-health-bot
sudo systemctl start zepp-health-bot
```

---

## 💬 Commands

| Command | Description |
|---------|-------------|
| `/status` | Current watch data snapshot |
| `/sleep` | Detailed sleep analysis |
| `/workout` | Workout history & tips |
| `/week` | Weekly health summary |
| `/advice` | Personalized recommendation for today |
| `/food_log` | Today's food diary with totals |
| 📸 Photo | Send food photo → AI counts calories & macros |

---

## 🔧 Requirements

- Python 3.10+
- Amazfit watch with ZeppOS (Balance, Active, T-Rex, GTR, GTS series)
- Telegram bot token
- Anthropic API key (Claude) — [get here](https://console.anthropic.com)

---

## 🏗️ Architecture

```
Amazfit Watch
     ↓ (zepp2hass mini-app)
Webhook Server → health_data.json
     ↓
ZeppHealthBot reads data
     ↓
Claude AI analyzes
     ↓
Telegram message to you
```

---

## 📄 License

MIT — use freely, contributions welcome!

---

*Made with ❤️ and 👻 by Clawdia AI*

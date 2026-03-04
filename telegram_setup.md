# Telegram Bot Setup Guide
## Fair Districts GA AI — Step by Step

---

## Step 1 — Create the Bot (2 minutes)

1. Open Telegram and search for **@BotFather**
2. Send: `/newbot`
3. When asked for a name, type: `Fair Districts GA`
4. When asked for a username, type something like: `FairDistrictsGA_bot`
   (must end in `_bot`, must be unique)
5. BotFather replies with your **Bot Token** — looks like:
   `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`
6. Copy this token into your `.env` file:
   ```
   TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   ```

---

## Step 2 — Test Locally (Polling Mode)

Before deploying, test with polling (no public URL needed):

```bash
# Make sure your virtual env is active
source venv/bin/activate

# Run the polling bot
python scripts/run_telegram_polling.py
```

Open Telegram, find your bot, send a message like:
"Which Senate districts have more than 50% BVAP?"

You should get a response within 20-30 seconds.

---

## Step 3 — Deploy (Webhook Mode for Production)

Once you deploy to Hugging Face Spaces or Railway:

```bash
# Register your deployed URL as the webhook
# Replace YOUR_TOKEN and YOUR_URL:
curl "https://api.telegram.org/botYOUR_TOKEN/setWebhook?url=https://YOUR_APP_URL/telegram/webhook"

# Verify it worked:
curl "https://api.telegram.org/botYOUR_TOKEN/getWebhookInfo"
```

---

## Useful Bot Commands to Add

Send these to BotFather with `/setcommands` to add a menu:

```
start - Welcome message and instructions
help - List example questions
senate - Ask about Senate districts
house - Ask about House districts  
congress - Ask about Congressional districts
maps - List available district maps
```

---

## Testing Your Bot

Good test questions to try:
- "Which Senate districts have more than 50% Black voting age population?"
- "Compare the 2021 and 2024 House maps for minority representation"
- "What is the partisan lean of Congressional district 5?"
- "Show me the demographic breakdown of the 2024 Senate districts"

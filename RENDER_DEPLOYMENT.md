# Render Deployment Guide for Vera-Next Bot

## Prerequisites
- GitHub account (✓ Already done)
- Render account (free: https://render.com)
- Anthropic API key

## Step 1: Connect Render to GitHub

1. Go to https://render.com
2. Sign up / Login with GitHub
3. Click **"New +"** → **"Web Service"**
4. Select **"Deploy an existing repository"**
5. Search for: `yaswanth-reddy14/magicpin`
6. Click **"Connect"**

## Step 2: Configure Render Service

| Setting | Value |
|---------|-------|
| **Name** | vera-bot (or any name) |
| **Environment** | Python 3 |
| **Region** | Choose nearest (e.g., Oregon, Frankfurt) |
| **Branch** | main |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python bot.py` |
| **Instance Type** | Free (for testing) or Starter ($7/mo) |

## Step 3: Add Environment Variables

In Render dashboard:
1. Under **"Environment"** section
2. Click **"Add Environment Variable"**
3. Add:
   - **Key**: `ANTHROPIC_API_KEY`
   - **Value**: `sk-ant-api03-YOUR_ACTUAL_KEY_HERE`

⚠️ **Important**: Replace with your actual Anthropic API key from `.env`

## Step 4: Deploy

1. Click **"Create Web Service"**
2. Render will automatically:
   - Build Docker image
   - Install dependencies
   - Start the bot
3. Wait for deployment (2-5 minutes)
4. You'll get a URL like: `https://vera-bot.onrender.com`

## Step 5: Test Deployment

```bash
# Test health endpoint
curl https://vera-bot.onrender.com/v1/healthz

# Expected response:
{
  "status": "ok",
  "uptime_seconds": 123,
  "contexts_loaded": {...}
}
```

## Step 6: Update Bot Submission

Once deployed on Render:
1. Go back to the magicpin challenge portal
2. Update your bot URL to: `https://vera-bot.onrender.com`
3. Resubmit

## Troubleshooting

### Build fails
- Check `requirements.txt` has all dependencies
- Verify Python version (3.8+)

### Bot crashes on startup
- Check logs: Click service → **"Logs"** tab
- Verify `ANTHROPIC_API_KEY` is set
- Ensure `Procfile` is correct

### Timeout on /v1/tick
- Increase Render instance to **Starter** plan
- Free tier has 15-min request timeout

## Keep Bot Running (Free Tier)

Free Render services spin down after 15 min of inactivity. To keep it running:

Option A: Add to cron job (e.g., Pingdom, UptimeRobot)
```
https://vera-bot.onrender.com/v1/healthz every 5 minutes
```

Option B: Upgrade to **Starter Plan** ($7/mo) for always-on

## Next Steps

After deployment, you can:
1. Monitor logs in Render dashboard
2. Track performance metrics
3. Update code via git push (auto-deploys)
4. Scale if needed

---

**Need Help?**
- Render Docs: https://render.com/docs
- Anthropic API: https://console.anthropic.com

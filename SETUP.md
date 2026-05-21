# SETUP.md — Google Cloud API Setup Guide

> **Digital Health Monitor** requires a Google Cloud API key for GBP (Places API)
> checks and optionally for PageSpeed Insights. This guide walks you through
> getting one from scratch.

---

## 📋 Prerequisites

- A Google account (any Gmail / Workspace account)
- A web browser
- ~10 minutes

---

## Step 1: Open Google Cloud Console

1. Go to **[https://console.cloud.google.com/](https://console.cloud.google.com/)**
2. Sign in with your Google account
3. If this is your first time, accept the Terms of Service

> [!TIP]
> Google gives every new account **$300 in free credits** for the first 90 days,
> plus a permanent **$200/month free tier** for Maps/Places APIs.

---

## Step 2: Create a New Project

1. Click the **project dropdown** at the top-left of the console (next to "Google Cloud")
2. Click **"New Project"** in the modal that appears
3. Enter a project name, e.g., `Digital Health Monitor`
4. Click **"Create"**
5. Wait a few seconds, then select the new project from the dropdown

> [!NOTE]
> If you already have a project you'd like to use, select it instead of
> creating a new one. Just make sure the required APIs are enabled.

---

## Step 3: Enable Required APIs

You need to enable **two** APIs:

### 3a. PageSpeed Insights API

1. Go to **[APIs & Services → Library](https://console.cloud.google.com/apis/library)**
2. Search for **"PageSpeed Insights API"**
3. Click on the result
4. Click **"Enable"**
5. Wait for the confirmation

> [!NOTE]
> PageSpeed Insights actually works without an API key (limited to ~25,000
> queries/day), but having a key removes rate limits and gives better
> reliability for batch audits.

### 3b. Places API (New)

1. Go back to the **[API Library](https://console.cloud.google.com/apis/library)**
2. Search for **"Places API (New)"**
   - ⚠️ Make sure you select **"Places API (New)"**, not the legacy "Places API"
3. Click on the result
4. Click **"Enable"**

> [!IMPORTANT]
> The tool uses the **new** Places API (`places.googleapis.com`), not the
> legacy one. The new API has different endpoints, pricing, and field masks.
> Make sure you enable the correct one.

---

## Step 4: Create an API Key

1. Go to **[APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)**
2. Click **"+ CREATE CREDENTIALS"** at the top
3. Select **"API key"**
4. Your new API key will be displayed — **copy it now!**
5. Click **"Close"**

> [!WARNING]
> Never commit your API key to version control! Always use a `.env` file and
> make sure `.env` is in your `.gitignore`.

---

## Step 5: (Recommended) Restrict the API Key

For security, restrict your key to only the APIs you need:

1. Click on your newly created API key in the Credentials list
2. Under **"API restrictions"**, select **"Restrict key"**
3. Check these APIs:
   - ✅ PageSpeed Insights API
   - ✅ Places API (New)
4. Click **"Save"**

You can also add **application restrictions** (HTTP referrers, IP addresses)
for additional security, but for local development this isn't necessary.

---

## Step 6: Set Up Your `.env` File

1. In the project root, copy the example file:

   ```bash
   cp .env.example .env
   ```

2. Open `.env` in your editor and paste your API key:

   ```env
   # Google Cloud API Key (required for GBP checks, optional for PageSpeed)
   GOOGLE_API_KEY=AIzaSyB1234567890abcdefghijklmnop
   ```

3. Save the file

> [!CAUTION]
> The `.env` file contains secrets! Make sure it's listed in `.gitignore`:
> ```
> # .gitignore
> .env
> ```

---

## 💰 Expected Costs

| API                    | Free Tier                              | Cost After Free Tier          |
|------------------------|----------------------------------------|-------------------------------|
| PageSpeed Insights API | **Free** — ~25,000 queries/day         | Free (no paid tier)           |
| Places API (New)       | **$200/month free credit** (~11k Text Searches/month) | ~$17 per 1,000 Text Searches |

### Realistic usage:

- **50 franchise sites, monthly audit** = ~50 Places API calls = well within free tier
- **200 franchise sites, weekly** = ~800 calls/month = still within free tier
- **1,000+ sites** = may start incurring costs, budget ~$17–35/month

> [!TIP]
> Set up a **budget alert** in Google Cloud to notify you if spend exceeds
> $10/month: [Billing → Budgets & alerts](https://console.cloud.google.com/billing/budgets)

---

## 🔧 Troubleshooting

### "API key not valid" error

- Double-check you copied the full key (it starts with `AIza...`)
- Ensure the key isn't restricted to wrong APIs
- Try creating a new unrestricted key to test

### "This API is not enabled" error

- Go to [APIs & Services → Enabled APIs](https://console.cloud.google.com/apis/dashboard)
- Verify both **PageSpeed Insights API** and **Places API (New)** show as enabled
- Make sure you're in the correct project

### "Request had insufficient authentication scopes"

- This usually means you're using an OAuth token instead of an API key
- The tool uses API keys, not OAuth — make sure `GOOGLE_API_KEY` is set

### "RESOURCE_EXHAUSTED" / 429 Too Many Requests

- You've hit rate limits — reduce `--workers` and increase `--delay`
- For batch audits, start with `--workers 2 --delay 1.0`

### Places API returns no results

- Try a more specific `--business` name with `--city`
- Use `--place-id` if you know the exact Place ID
- Search for the business on [Google Maps](https://maps.google.com) and extract
  the Place ID from the URL

### PageSpeed times out

- PSI can be slow for large sites — the tool uses a 60-second timeout
- Try running with `--no-pagespeed` first to verify other checkers work
- If running a batch, increase `--delay` to avoid overwhelming the API

---

## ✅ Verification

After setup, test with a quick single-site audit:

```bash
python main.py --url https://forkschemdry.com --business "Forks Chem-Dry" --city "Grand Forks" --output ./test_results
```

You should see:
1. Website SEO checks running (no API key needed)
2. PageSpeed checks running
3. GBP checks running (requires valid API key)
4. Score and grade output
5. Report files in `./test_results/`

If GBP checks fail with an API key error, double-check your `.env` file.

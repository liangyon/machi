# Machi — Deployment Guide

Production stack: **Vercel** (frontend) + **Railway** (backend) + **Neon** (PostgreSQL).

---

## Prerequisites

- GitHub repo: `liangyon/machi` (already set up)
- Accounts: [Neon](https://neon.tech), [Railway](https://railway.app), [Vercel](https://vercel.com)
- API keys: OpenAI, MAL Client ID (optional: Google/Discord OAuth)

---

## Step 1: Database — Neon (PostgreSQL)

> **Time: ~5 minutes**

1. Go to [neon.tech](https://neon.tech) → Sign up / Sign in
2. Click **"New Project"**
   - Name: `machi`
   - Region: pick the closest to your users (e.g., `us-east-2`)
   - Click **Create Project**
3. Copy the **connection string** from the dashboard:
   ```
   postgresql://neondb_owner:abc123@ep-cool-name-12345.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
4. In the **SQL Editor**, run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
   (This enables pgvector for future vector store migration)

**Save the connection string — you'll need it in Step 2.**

---

## Step 2: Backend — Railway

> **Time: ~10 minutes**

### 2a. Create the Service

1. Go to [railway.app](https://railway.app) → Sign in with GitHub
2. Click **"New Project"** → **"Deploy from GitHub Repo"**
3. Select the `liangyon/machi` repository
4. Railway will create a service. Click on it to configure:

### 2b. Configure Build Settings

1. Go to **Settings** tab:
   - **Root Directory**: `backend`
   - **Builder**: `Dockerfile`
   - **Health Check Path**: `/api/health`
   - **Restart Policy**: `On Failure`

### 2c. Add a Persistent Volume

1. In the service, go to **Volumes** → **Add Volume**
   - **Mount Path**: `/data`
   - This persists ChromaDB data across deploys

### 2d. Set Environment Variables

Go to **Variables** tab and add each:

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `DEBUG` | `false` |
| `DATABASE_URL` | `postgresql://...` (from Step 1) |
| `SECRET_KEY` | Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `OPENAI_API_KEY` | Your OpenAI API key |
| `MAL_CLIENT_ID` | Your MAL Client ID |
| `CORS_ORIGINS` | `["https://machi.vercel.app"]` (update after Step 3) |
| `FRONTEND_URL` | `https://machi.vercel.app` (update after Step 3) |
| `CHROMA_PERSIST_DIR` | `/data/chroma` |
| `CHROMA_COLLECTION_NAME` | `anime_catalog` |

Optional (OAuth):
| Variable | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | Your Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Your Google OAuth client secret |
| `DISCORD_CLIENT_ID` | Your Discord OAuth client ID |
| `DISCORD_CLIENT_SECRET` | Your Discord OAuth client secret |

### 2e. Deploy

Railway will auto-deploy. Wait for the build to complete and the health check to pass.

Note your Railway URL (e.g., `machi-backend-production.up.railway.app`).

### 2f. Run Database Migrations

In Railway dashboard → your service → click **"Shell"** (or use Railway CLI):

```bash
uv run alembic upgrade head
```

### 2g. Seed the Anime Catalog

Still in the Railway shell:

```bash
# Quick seed (~500-700 anime, takes ~2-3 min)
uv run python -m app.cli ingest-anime --pages 10 --seasons 4

# Or full catalog (~27,000 anime, takes ~15-20 min, ~$0.50-1.00 OpenAI cost)
uv run python -m app.cli ingest-anime --all
```

---

## Step 3: Frontend — Vercel

> **Time: ~5 minutes**

1. Go to [vercel.com](https://vercel.com) → Sign in with GitHub
2. Click **"Add New Project"** → Import `liangyon/machi`
3. Configure:
   - **Framework Preset**: Next.js (auto-detected)
   - **Root Directory**: `frontend`
4. Add **Environment Variable**:
   | Name | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | `https://machi-backend-production.up.railway.app` (your Railway URL from Step 2e) |
5. Click **Deploy**

Note your Vercel URL (e.g., `machi.vercel.app`).

### 3a. Update Backend CORS

Go back to Railway → Variables and update:
- `CORS_ORIGINS` → `["https://machi.vercel.app"]` (your actual Vercel URL)
- `FRONTEND_URL` → `https://machi.vercel.app`

Railway will auto-redeploy with the new variables.

---

## Step 4: CI/CD Setup (GitHub Actions)

> **Time: ~10 minutes**

### 4a. CI (Automatic)

The CI pipeline (`.github/workflows/ci.yml`) runs automatically on every push and PR:
- ✅ Backend tests (pytest)
- ✅ Frontend lint + build
- ✅ Docker build check

No setup needed — it works out of the box.

### 4b. Auto-Deploy via Railway GitHub Integration (Recommended)

Railway's built-in GitHub integration already auto-deploys on push to `main`. This is the simplest option and is already configured from Step 2.

**That's it!** Every push to `main` will:
1. Run CI checks (GitHub Actions)
2. Auto-deploy frontend (Vercel)
3. Auto-deploy backend (Railway)

### 4c. (Optional) Deploy via GitHub Actions

If you prefer deploying through GitHub Actions instead of Railway's built-in integration:

1. Install Railway CLI locally:
   ```bash
   npm i -g @railway/cli
   ```

2. Login and link:
   ```bash
   railway login
   railway link
   ```

3. Create a deploy token:
   ```bash
   railway tokens create
   ```

4. Add secrets to GitHub repo (Settings → Secrets and variables → Actions):
   | Secret | Value |
   |---|---|
   | `RAILWAY_TOKEN` | The token from step 3 |
   | `RAILWAY_SERVICE_ID` | Find in Railway → Service → Settings → Service ID |

5. The workflow at `.github/workflows/deploy-backend.yml` will now deploy on push to `main` when backend files change.

---

## Step 5: Verify Everything Works

1. **Health check**: Visit `https://your-backend.up.railway.app/api/health`
   - Should return `{"status": "ok"}`

2. **API docs**: Visit `https://your-backend.up.railway.app/api/docs`
   - Should show the Swagger UI

3. **Frontend**: Visit `https://machi.vercel.app`
   - Should load the app
   - Try registering an account and importing a MAL profile

---

## CI/CD Flow Diagram

```
Developer pushes code
        │
        ├── Push to feature branch (PR)
        │     └── GitHub Actions CI
        │           ├── Backend: pytest ✓/✗
        │           ├── Frontend: lint + build ✓/✗
        │           └── Docker build check ✓/✗
        │
        └── Merge to main
              ├── GitHub Actions CI (same checks)
              ├── Vercel auto-deploys frontend
              └── Railway auto-deploys backend
                    └── Health check passes → live
```

---

## Troubleshooting

### Backend won't start
- Check Railway logs (Dashboard → Service → Logs)
- Verify all required env vars are set (especially `DATABASE_URL`, `SECRET_KEY`, `OPENAI_API_KEY`)
- Ensure `ENVIRONMENT=production` and `SECRET_KEY` is ≥32 chars

### Database connection fails
- Verify the Neon connection string includes `?sslmode=require`
- Check that the Neon project is active (free tier pauses after inactivity)

### CORS errors in browser
- Verify `CORS_ORIGINS` in Railway matches your exact Vercel URL (including `https://`)
- Make sure it's a JSON array: `["https://machi.vercel.app"]`

### Frontend can't reach backend
- Verify `NEXT_PUBLIC_API_URL` in Vercel matches your Railway URL
- No trailing slash on the URL
- Redeploy frontend after changing env vars (Vercel → Deployments → Redeploy)

### ChromaDB data lost after deploy
- Ensure the Railway volume is mounted at `/data`
- `CHROMA_PERSIST_DIR` must be `/data/chroma`

---

## Cost Summary

| Service | Free Tier | Paid |
|---|---|---|
| **Vercel** | 100GB bandwidth, unlimited deploys | — |
| **Railway** | $5 credit/month (Hobby plan: $5/mo) | ~$5-7/mo |
| **Neon** | 0.5 GB storage, 190 compute hours | — |
| **OpenAI** | — | ~$2-10/mo depending on usage |
| **Total** | ~$5/mo | ~$10-15/mo |

---

## Optional: Custom Domain

### Vercel
1. Vercel Dashboard → Project → Settings → Domains
2. Add your domain (e.g., `machi.app`)
3. Update DNS records as instructed

### Railway
1. Railway Dashboard → Service → Settings → Domains
2. Add custom domain (e.g., `api.machi.app`)
3. Update DNS records as instructed
4. Update `CORS_ORIGINS` and `FRONTEND_URL` accordingly

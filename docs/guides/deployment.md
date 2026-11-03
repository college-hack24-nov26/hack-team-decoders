# Deploy MediKiosk — Render + Supabase + Vercel / Render Static Site

Step-by-step. Total deployment time: ~20-30 minutes.

```
Browser ──▶ Frontend (Vercel or Render Static Site)
                │
                ▼  VITE_API_BASE_URL
            Render (FastAPI backend Web Service)
                ├── Supabase Postgres (DB + pgvector)
                └── Supabase Storage (document uploads)
```

---

## Step 1 — Supabase (Database + File Storage)

1. Go to [supabase.com](https://supabase.com) → **New Project**
2. Name: `medikiosk`, set a DB password, region: **South Asia (Mumbai)** (or closest)
3. Wait for the project to spin up (~2 min)

### Get your credentials

| What | Where in Supabase dashboard |
|------|---------------------------|
| `DATABASE_URL` | Top bar **🔌 Connect** button → **Pooler (Supavisor)** tab → **Session mode** (port 5432) |
| `SUPABASE_URL` | **Settings (gear icon) → API → Project URL** (e.g. `https://abcdefg.supabase.co`) |
| `SUPABASE_SERVICE_KEY` | **Settings (gear icon) → API → service_role** key (the secret one, **not** anon) |

### Fix the DATABASE_URL format

Supabase gives you:
`postgresql://postgres.xxxxx:PASSWORD@aws-0-ap-south-1.pooler.supabase.com:5432/postgres`

Add `+psycopg2` after `postgresql` so SQLAlchemy uses the right driver:
```
postgresql+psycopg2://postgres.xxxxx:PASSWORD@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
```

> **Important:**
> 1. Use **Pooler in Session mode (port 5432)**, NOT direct connection (direct uses IPv6 which Render can't reach).
> 2. If your password has `@` in it, URL-encode it as `%40`.

### Enable pgvector

In Supabase left sidebar → **SQL Editor** → run:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Create storage bucket

1. Left sidebar → **Storage** → **New Bucket**
2. Name: `medikiosk-uploads`
3. Toggle **Public bucket** = OFF (backend uses service key)
4. Click **Create**

---

## Step 2 — Deploy Backend on Render (Web Service)

1. Go to [render.com](https://render.com) → **New + → Web Service**
2. Connect your GitHub repository (`college-hack24-nov26/hack-team-decoders`)
3. Configure:

| Setting | Value |
|---------|-------|
| **Name** | `medikiosk-api` |
| **Root Directory** | `backend` |
| **Environment** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| **Plan** | Free (or Starter $7/mo to avoid 30s cold starts) |

### Set environment variables

In Render → **Environment** tab, add these:

```env
# Database (from Supabase Step 1 — with +psycopg2)
DATABASE_URL=postgresql+psycopg2://postgres.xxxxx:PASSWORD@aws-0-ap-south-1.pooler.supabase.com:5432/postgres

# Auth
JWT_SECRET_KEY=generate_a_random_32_char_secret_here
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60

# File Storage
FILE_STORAGE_BACKEND=supabase
SUPABASE_URL=https://abcdefg.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGci...your_service_role_key
SUPABASE_BUCKET=medikiosk-uploads

# CORS (will update in Step 4 once frontend URL is ready)
CORS_ORIGINS=http://localhost:5173

# Optional AI services (summaries use deterministic fallback if blank)
MAIN_LLM_API_KEY=
MAIN_LLM_MODEL=gpt-4o-mini
TTS_PROVIDER=none
SARVAM_API_KEY=
PURGE_AFTER_PUSH=true
```

4. Click **Create Web Service** → wait for build & deployment (~3 min).
5. Copy your backend URL: e.g. `https://medikiosk-api.onrender.com`
6. Verify by opening `https://medikiosk-api.onrender.com/health` (should return `{"status":"ok"}`).

---

## Step 3 — Deploy Frontend (Choose Option A or Option B)

Your frontend is a Vite + React Single Page App (SPA). It compiles to static files (`HTML/JS/CSS`) that run in the user's browser. Both options below are **100% Free**.

---

### Option 3A — Render Static Site (Recommended for Private Org Repos)
*Best if your GitHub repo is private inside an organization, keeping everything on Render.*

1. In [render.com](https://render.com) dashboard → click **New + → Static Site**
2. Connect your repo (`college-hack24-nov26/hack-team-decoders`)
3. Settings:
   - **Name**: `medikiosk-ui`
   - **Root Directory**: `frontend`
   - **Build Command**: `npm run build`
   - **Publish Directory**: `dist`
4. Add Environment Variable:
   - `VITE_API_BASE_URL` = `https://medikiosk-api.onrender.com` *(your Render backend URL from Step 2)*
5. Configure SPA Routing Rewrite (prevents 404 on refresh):
   - In your new Static Site's settings → go to **Redirects/Rewrites**
   - Click **Add Rule**
   - **Type**: `Rewrite`
   - **Source**: `/*`
   - **Destination**: `/index.html`
6. Click **Create Static Site** (or Save).
7. Copy your frontend URL: e.g. `https://medikiosk-ui.onrender.com`

---

### Option 3B — Vercel
*Best if you make your GitHub repository Public or if it's on a personal GitHub account.*

> **Note:** Vercel free Hobby tier requires the repo to either be Public or under a personal GitHub account. If it's a private org repo, go to GitHub repo **Settings → Danger Zone → Change visibility → Make Public** first.

1. Go to [vercel.com](https://vercel.com) → **Add New → Project**
2. Import your GitHub repo
3. Configure:
   - **Framework Preset**: `Vite`
   - **Root Directory**: `frontend`
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`
4. Add Environment Variable:
   - `VITE_API_BASE_URL` = `https://medikiosk-api.onrender.com` *(your backend URL)*
5. Click **Deploy**
6. Copy your frontend URL: e.g. `https://medikiosk-xxx.vercel.app`

---

## Step 4 — Connect CORS on Backend

Now that your frontend has a live URL, allow it to talk to the backend:

1. Go to your **Render Backend Web Service** (`medikiosk-api`)
2. Go to the **Environment** tab
3. Update `CORS_ORIGINS` to include your frontend URL (comma-separated, no trailing slashes):
   ```env
   CORS_ORIGINS=http://localhost:5173,https://medikiosk-ui.onrender.com,https://medikiosk-xxx.vercel.app
   ```
4. Click **Save Changes** (Render will automatically redeploy in ~30 seconds).

---

## Step 5 — Test Full Journey

Open your live frontend URL in your browser and test:

1. ✅ **Language select**: Pick English or Hindi
2. ✅ **Patient login**: Enter any 14-digit number (mock ABHA)
3. ✅ **Consent**: Check boxes and submit
4. ✅ **Interview**: Answer questions (voice or touch)
5. ✅ **Documents**: Upload a prescription/lab report photo
6. ✅ **Visit Complete**: Finish session
7. **Physician login**: Use the physician account provisioned for this environment. Demo seed credentials are for local demonstrations only.
8. ✅ **Queue & Review**: Verify patient appears in doctor queue, review summary, and download clinical report

---

## Troubleshooting

### 1. Backend error: `psycopg2.OperationalError: Network is unreachable`
- You are using the Direct DB host (`db.xxx.supabase.co`) which is IPv6-only.
- **Fix:** Switch to Supabase **Connection Pooler in Session mode (port 5432)** (`aws-0-xxx.pooler.supabase.com`).

### 2. Frontend shows "Network Error" or "Failed to fetch"
- Check browser console (F12). If it's a CORS error, ensure `CORS_ORIGINS` in Render backend environment has your exact frontend URL (including `https://` with no trailing `/`).
- Ensure `VITE_API_BASE_URL` was set when building the frontend.

### 3. Page refresh gives 404 on Render Static Site
- In Render Static Site dashboard → **Redirects/Rewrites**, add a rewrite rule:
  `/*` → `/index.html` (Action: `Rewrite`).

### 4. Render free tier cold starts (~30s delay)
- Free Web Services spin down after 15 minutes of inactivity.
- **Tip for demo day:** Ping the backend `/health` endpoint 1 minute before your presentation, or upgrade to Render Starter ($7/mo) for always-on compute.

## Security note for hosted deployments

The bundled Docker Compose configuration and seeded demo accounts are intended
for local development and demonstrations only.

Before any shared or public deployment:
- Set unique, strong authentication secrets and account passwords.
- Set DEBUG=false.
- Replace development database credentials and placeholder signing secrets.
- Configure restricted CORS and private document storage.
- Never commit actual .env files.
- Do not use MEDIKIOSK_BOOTSTRAP=reset on a database containing real patient data.


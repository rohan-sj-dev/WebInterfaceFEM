# 🚀 Deployment Guide: Netlify + Render

This guide will help you deploy your OCR FEM application to production.

## Architecture

- **Frontend**: Netlify (React)
- **Backend**: Render (Flask)
- **Database**: SQLite (local file storage)

---

## Part 1: Deploy Backend to Render

### Step 1: Prepare Your Repository

1. Commit all changes:
```bash
cd modern-ocr-app
git add .
git commit -m "Prepare for deployment"
git push origin main
```

### Step 2: Create Render Account

1. Go to https://render.com
2. Sign up with your GitHub account
3. Authorize Render to access your repository

### Step 3: Deploy Backend

1. Click **"New +"** → **"Web Service"**
2. Connect your GitHub repository: `WebInterfaceFEM`
3. Configure the service:
   - **Name**: `ocr-fem-backend` (or your choice)
   - **Region**: Oregon (US West) or closest to you
   - **Branch**: `main`
   - **Root Directory**: `backend`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn --bind 0.0.0.0:$PORT --timeout 300 app:app`
   - **Instance Type**: `Free`

4. **Add Environment Variables** (click "Advanced" → "Add Environment Variable"):
   ```
   JWT_SECRET_KEY = (generate random string)
   FLASK_ENV = production
   ALLOWED_ORIGINS = https://your-app.netlify.app,http://localhost:3000
   OPENAI_API_KEY = your-openai-key
   GLM_API_KEY = your-glm-key
   UNSTRACT_API_KEY = your-unstract-key (optional)
   LLMWHISPERER_API_KEY = your-llmwhisperer-key (optional)
   AWS_ACCESS_KEY_ID = your-aws-key (optional)
   AWS_SECRET_ACCESS_KEY = your-aws-secret (optional)
   ```

5. Click **"Create Web Service"**

6. Wait for deployment (5-10 minutes)

7. **Copy your backend URL**: `https://your-backend-app.onrender.com`

### Step 4: Install Poppler on Render

Render needs Poppler for pdf2image. Add this to your backend:

Create `render-build.sh` in backend folder:
```bash
#!/usr/bin/env bash
# Install poppler-utils for pdf2image
apt-get update
apt-get install -y poppler-utils

# Install Python dependencies
pip install -r requirements.txt
```

Update Render Build Command to: `./render-build.sh`

---

## Part 2: Deploy Frontend to Netlify

### Step 1: Update Frontend Configuration

1. Update `frontend/netlify.toml`:
```toml
[build.environment]
  REACT_APP_API_URL = "https://your-backend-app.onrender.com/api"
```

Replace `your-backend-app.onrender.com` with your actual Render URL.

2. Commit changes:
```bash
git add frontend/netlify.toml
git commit -m "Update API URL for production"
git push origin main
```

### Step 2: Create Netlify Account

1. Go to https://www.netlify.com
2. Sign up with your GitHub account

### Step 3: Deploy Frontend

1. Click **"Add new site"** → **"Import an existing project"**
2. Choose **"GitHub"**
3. Select your repository: `WebInterfaceFEM`
4. Configure build settings:
   - **Base directory**: `frontend`
   - **Build command**: `npm run build`
   - **Publish directory**: `frontend/build`
   
5. **Add Environment Variables**:
   - Click "Site settings" → "Build & deploy" → "Environment"
   - Add: `REACT_APP_API_URL` = `https://your-backend-app.onrender.com/api`

6. Click **"Deploy site"**

7. Wait for deployment (2-5 minutes)

8. **Get your site URL**: `https://your-app.netlify.app`

### Step 4: Update Backend CORS

1. Go back to Render dashboard
2. Click on your backend service
3. Go to "Environment" tab
4. Update `ALLOWED_ORIGINS`:
   ```
   ALLOWED_ORIGINS=https://your-app.netlify.app,http://localhost:3000
   ```
5. Save changes (service will redeploy automatically)

---

## Part 3: Testing

### Test Your Deployment

1. Visit your Netlify URL: `https://your-app.netlify.app`
2. Register a new account
3. Try uploading a PDF
4. Test GLM table extraction
5. Test ABAQUS file generation

### Common Issues

**Issue**: CORS errors
- **Fix**: Make sure `ALLOWED_ORIGINS` in Render includes your Netlify URL

**Issue**: API calls fail
- **Fix**: Check `REACT_APP_API_URL` in Netlify environment variables

**Issue**: 502 Bad Gateway
- **Fix**: Backend is starting up (cold start). Wait 30 seconds and refresh.

**Issue**: PDF processing fails
- **Fix**: Make sure Poppler is installed (check render-build.sh)

---

## Part 4: Custom Domain (Optional)

### Netlify Custom Domain

1. Go to Netlify → Site settings → Domain management
2. Click "Add custom domain"
3. Follow DNS configuration instructions

### Render Custom Domain

1. Go to Render → Settings → Custom Domains
2. Add your domain
3. Update DNS records

---

## Free Tier Limitations

### Render Free Tier:
- ✅ 750 hours/month (24/7 for 1 app)
- ⚠️ **Spins down after 15 min inactivity**
- ⚠️ **Cold start: 10-20 seconds**
- ✅ 512MB RAM
- ✅ Automatic SSL

### Netlify Free Tier:
- ✅ 100GB bandwidth/month
- ✅ 300 build minutes/month
- ✅ Always on (no cold starts)
- ✅ Global CDN
- ✅ Automatic SSL

---

## Upgrade Path

When you outgrow the free tier:

**Render**: $7/month for always-on (no cold starts)
**Netlify**: Free tier is usually sufficient for frontend

---

## Monitoring

### Backend Logs (Render):
1. Go to Render dashboard
2. Click on your service
3. Click "Logs" tab

### Frontend Logs (Netlify):
1. Go to Netlify dashboard
2. Click "Deploys"
3. Click on latest deploy → "Deploy log"

---

## Local Development

Keep using:
```bash
# Backend
cd backend
python app.py

# Frontend
cd frontend
npm start
```

The `.env` file will use `http://localhost:5001/api` automatically.

---

## Support

**Render Issues**: https://render.com/docs
**Netlify Issues**: https://docs.netlify.com

🎉 **Your app is now live!**

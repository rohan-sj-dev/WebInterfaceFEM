# 🚀 Quick Deployment Checklist

## ✅ Files Created/Modified:

### Backend:
- ✅ `backend/render.yaml` - Render configuration
- ✅ `backend/render-build.sh` - Build script with Poppler
- ✅ `backend/requirements.txt` - Added gunicorn, zhipuai
- ✅ `backend/app.py` - Environment variable support for CORS
- ✅ `backend/.gitignore` - Ignore outputs, .env files

### Frontend:
- ✅ `frontend/netlify.toml` - Netlify configuration
- ✅ `frontend/.env` - Local development
- ✅ `frontend/.env.production` - Production template
- ✅ `frontend/.env.example` - Example file
- ✅ `frontend/src/services/authService.js` - Environment variable for API URL
- ✅ `frontend/.gitignore` - Ignore node_modules, build

### Documentation:
- ✅ `DEPLOYMENT_GUIDE.md` - Complete step-by-step guide

---

## 🎯 Next Steps:

### 1. Commit Changes
```bash
cd modern-ocr-app
git add .
git commit -m "Add deployment configuration for Netlify and Render"
git push origin main
```

### 2. Deploy Backend (Render)
1. Go to https://render.com
2. Sign up with GitHub
3. New → Web Service
4. Select repository: `WebInterfaceFEM`
5. Root Directory: `backend`
6. Build Command: `chmod +x render-build.sh && ./render-build.sh`
7. Start Command: `gunicorn --bind 0.0.0.0:$PORT --timeout 300 app:app`
8. Add environment variables (see DEPLOYMENT_GUIDE.md)
9. Deploy!

### 3. Deploy Frontend (Netlify)
1. Go to https://netlify.com
2. Sign up with GitHub
3. New site from Git
4. Select repository: `WebInterfaceFEM`
5. Base directory: `frontend`
6. Build command: `npm run build`
7. Publish directory: `frontend/build`
8. Add: `REACT_APP_API_URL` = `https://your-backend.onrender.com/api`
9. Deploy!

### 4. Update CORS
Go back to Render → Environment → Update:
```
ALLOWED_ORIGINS=https://your-app.netlify.app
```

---

## 🔑 Required Environment Variables:

### Backend (Render):
```
JWT_SECRET_KEY = (random string - auto-generate)
FLASK_ENV = production
ALLOWED_ORIGINS = https://your-app.netlify.app
OPENAI_API_KEY = sk-...
GLM_API_KEY = ...
```

### Frontend (Netlify):
```
REACT_APP_API_URL = https://your-backend.onrender.com/api
```

---

## ⚠️ Important Notes:

1. **Render Free Tier**: Service spins down after 15 min inactivity (10-20s cold start)
2. **First Request**: May take 20-30 seconds to wake up
3. **Poppler**: Installed via render-build.sh for pdf2image
4. **ABAQUS**: Not available on server - users download .inp files
5. **Database**: SQLite (local file, resets on redeploy)

---

## 📊 Estimated Costs:

- Backend (Render Free): $0/month (with cold starts)
- Frontend (Netlify Free): $0/month
- **Total**: FREE! 🎉

Upgrade to Render paid ($7/mo) for no cold starts when you have users.

---

## 📖 Full Guide:

See `DEPLOYMENT_GUIDE.md` for detailed instructions!

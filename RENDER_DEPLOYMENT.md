# 🚀 Render Deployment - Quick Guide

## **Simpler Approach: Keep SQLite for Now**

For initial deployment, we'll use SQLite (simpler, works on Render free tier).
Later you can migrate to PostgreSQL.

---

## **Deploy Backend on Render**

### **Step 1: Create Render Account**

1. Go to https://render.com
2. Click "Get Started"
3. Sign up with GitHub
4. Authorize Render

### **Step 2: Create Web Service**

1. Click "New +" → "Web Service"
2. Click "Connect repository" → Select `WebInterfaceFEM`
3. Configure:

```
Name: ocr-fem-backend
Region: Oregon (US West) or closest
Branch: main
Root Directory: backend
Runtime: Python 3
Build Command: chmod +x render-build.sh && ./render-build.sh
Start Command: gunicorn --bind 0.0.0.0:$PORT --timeout 300 app:app
```

4. **Instance Type**: Select "Free"

### **Step 3: Add Environment Variables**

Click "Advanced" → Add these one by one:

```
JWT_SECRET_KEY = (click Auto-Generate button)
FLASK_ENV = production
ALLOWED_ORIGINS = https://webinterfacefem.netlify.app
OPENAI_API_KEY = your-openai-key-here
GLM_API_KEY = your-glm-key-here
```

**Optional (if you're using them):**
```
UNSTRACT_API_KEY = your-key
LLMWHISPERER_API_KEY = your-key
AWS_ACCESS_KEY_ID = your-key
AWS_SECRET_ACCESS_KEY = your-secret
```

### **Step 4: Deploy**

1. Click "Create Web Service"
2. Wait 5-10 minutes for first deploy
3. **Copy your backend URL**: `https://ocr-fem-backend.onrender.com`

---

## **Step 5: Update Frontend**

1. Go to Netlify dashboard
2. Site settings → Build & deploy → Environment
3. Edit `REACT_APP_API_URL`:
   ```
   REACT_APP_API_URL=https://ocr-fem-backend.onrender.com/api
   ```
4. Click "Save"
5. Deploys → "Trigger deploy" → "Deploy site"

---

## **Step 6: Update Backend CORS**

1. Go back to Render dashboard
2. Click on your service
3. Environment → Edit `ALLOWED_ORIGINS`
4. Update with your Netlify URL:
   ```
   ALLOWED_ORIGINS=https://webinterfacefem.netlify.app
   ```
5. Save (auto-redeploys)

---

## **Testing**

1. Visit your Netlify site
2. Register a new account
3. Upload a PDF
4. Test extraction

**Note**: First request after 15min of inactivity takes 20-30 seconds (cold start on free tier)

---

## **Database: SQLite vs PostgreSQL**

### **Current (SQLite - Simple)**
- ✅ Works on Render
- ✅ No extra setup
- ⚠️ Data resets on redeploy
- ⚠️ Not for production with real users

### **Future (PostgreSQL - Production)**
When you have real users:
1. Render → New → PostgreSQL Database
2. Add `DATABASE_URL` environment variable
3. Migrate with the `database.py` module we created

---

## **Costs**

**Free Tier:**
- Backend: Free (with cold starts)
- Frontend: Free
- PostgreSQL: Free for 90 days, then $7/month

**Paid Tier:**
- Backend (no cold starts): $7/month
- PostgreSQL: $7/month

---

## **Troubleshooting**

**Build fails**: Check Render logs for error
**CORS errors**: Verify `ALLOWED_ORIGINS` matches Netlify URL
**502 errors**: Service is waking up (cold start), wait 30s

---

🎉 **You're ready to deploy!**

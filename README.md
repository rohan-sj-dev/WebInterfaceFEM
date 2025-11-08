# Modern OCR Application

A full-stack PDF OCR and data extraction application with React frontend and Flask backend, integrated with Unstract AI for advanced document processing.

## 🚀 Features

- **PDF OCR Processing** - Convert scanned PDFs to searchable documents
- **AI-Powered Extraction** - Unstract Cloud API integration for intelligent data extraction
- **Dual Extraction Methods**:
  - Local OCR (Tesseract-based)
  - Unstract Cloud API (GPT-4 Turbo / Azure GPT-4o)
- **Custom Query Support** - Ask specific questions about your documents
- **Table Detection & Extraction** - Automatic table recognition and CSV export
- **ABAQUS Integration** - Launch FEM simulations directly from extracted data
- **User Authentication** - JWT-based secure authentication
- **Real-time Processing** - Live status updates with progress tracking

## 📋 Prerequisites

### Backend Requirements
- Python 3.8+
- Tesseract OCR
- Poppler (for PDF processing)

### Frontend Requirements
- Node.js 16+
- npm or yarn

## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone <repository-url>
cd modern-ocr-app
```

### 2. Backend Setup
```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env and add your API keys (see ENV_SETUP.md for details)

# Run the backend
python app.py
```

Backend will start on `http://localhost:5001`

**Important:** See `backend/ENV_SETUP.md` for detailed configuration guide.

### 3. Frontend Setup
```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm start
```

Frontend will start on `http://localhost:3000`

## 🔧 Configuration

### Environment Variables

All API keys and configuration are stored in `backend/.env` file:

1. Copy the example file:
   ```bash
   cd backend
   cp .env.example .env
   ```

2. Edit `.env` and add your API keys:
   - `UNSTRACT_API_KEY` - Get from https://unstract.com
   - `LLMWHISPERER_API_KEY` - Get from Unstract dashboard
   - `AWS_ACCESS_KEY_ID` & `AWS_SECRET_ACCESS_KEY` - For AWS Textract (optional)

3. See `backend/ENV_SETUP.md` for detailed setup instructions

**Never commit `.env` to Git!** Use `.env.example` for sharing configuration structure.

### ABAQUS Configuration

The application searches for ABAQUS in common installation paths:
- `C:\SIMULIA\Commands\abaqus.bat`
- `C:\Program Files\Dassault Systemes\SimulationServices\...`
- System PATH

## 📖 Usage

### Basic OCR Processing
1. Login or create an account
2. Upload a PDF file
3. Choose processing options:
   - Local OCR extraction
   - Unstract AI extraction
4. Wait for processing to complete
5. Download results

### Custom Query Extraction
1. Upload a PDF
2. Select "Extract data via Unstract API"
3. Choose AI model (GPT-4 Turbo / Azure GPT-4o)
4. Enter custom prompts in the text area:
   - "What is the Si content of A61146?"
   - "Extract only chemical composition data"
   - "List all heat numbers"
5. Process and view results

### ABAQUS Integration
1. After extracting CSV data
2. Click "Run ABAQUS Simulation" button
3. ABAQUS CAE will launch automatically

## 🏗️ Project Structure

```
modern-ocr-app/
├── backend/
│   ├── app.py                 # Main Flask application
│   ├── requirements.txt       # Python dependencies
│   ├── uploads/              # Uploaded files (gitignored)
│   └── outputs/              # Processed files (gitignored)
├── frontend/
│   ├── src/
│   │   ├── components/       # React components
│   │   ├── context/          # Auth context
│   │   ├── pages/            # Dashboard, Login, Register
│   │   └── services/         # API services
│   ├── public/
│   └── package.json
├── .gitignore
└── README.md
```

## 🔐 Security Notes

- JWT tokens expire after 24 hours
- Passwords are hashed using bcrypt
- CORS is configured for localhost development
- **DO NOT commit** `.env` files, API keys, or database files
- **DO NOT commit** uploaded PDFs or output files

## 📊 Performance

- **Local OCR**: 10-30 seconds (depends on file size)
- **Unstract API**: 25-35 seconds
  - File upload: ~5 seconds
  - AI processing: ~20 seconds
  - Network overhead: ~5 seconds

See `PERFORMANCE_TIMING_ANALYSIS.md` for detailed breakdown.

## 🐛 Troubleshooting

### SSL/TLS Errors
The application includes automatic retry logic with SSL fallback. If issues persist:
- Check firewall settings
- Verify network connectivity
- Update SSL certificates

### ABAQUS Not Found
- Install ABAQUS or add to system PATH
- Verify installation paths in `app.py`

### Frontend Not Loading
- Clear browser cache
- Check console for errors
- Verify backend is running on port 5001

## 📝 API Documentation

### Authentication Endpoints
- `POST /api/register` - Create new user
- `POST /api/login` - User login
- `GET /api/profile` - Get user profile (requires JWT)

### OCR Endpoints
- `POST /api/upload` - Upload PDF for local OCR
- `POST /api/upload_unstract` - Upload PDF for Unstract extraction
- `GET /api/status/<task_id>` - Get processing status

### Download Endpoints
- `GET /api/download/<task_id>` - Download processed PDF
- `GET /api/download_all/<task_id>` - Download all results as ZIP

### ABAQUS Endpoint
- `POST /api/launch_abaqus` - Launch ABAQUS with CSV data

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License.

## 🙏 Acknowledgments

- [Unstract](https://unstract.com/) - AI-powered document extraction
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
- [React](https://reactjs.org/)
- [Flask](https://flask.palletsprojects.com/)
- [Tailwind CSS](https://tailwindcss.com/)

## 📞 Support

For issues, questions, or contributions, please open an issue on GitHub.

---

**Note:** This application requires active Unstract Cloud API credentials for AI-powered extraction features.

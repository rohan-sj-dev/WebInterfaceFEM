# Backend Cleanup Status

## ✅ COMPLETED
1. **Configuration removed** (lines 31-47):
   - Unstract config
   - AWS Textract config
   - LLMWhisperer config
   - OpenAI config
   
2. **Import removed**:
   - `from openai import OpenAI`

3. **Functions removed**:
   - `process_pdf_with_unstract()` - 337 lines ✅

## ⏳ TO DO - Remove These Functions

Find and remove these complete functions from app.py:

### 1. process_pdf_with_textract (AWS Textract)
- Starts around line 341 (after Unstract removal)
- Remove entire function until next `def process_` 

### 2. process_pdf_with_direct_llm (AWS Textract custom queries)
- Find: `def process_pdf_with_direct_llm`
- Remove entire function

### 3. process_pdf_with_llmwhisperer  
- Find: `def process_pdf_with_llmwhisperer`
- Remove entire function

### 4. process_pdf_with_gpt4o_hybrid
- Find: `def process_pdf_with_gpt4o_hybrid`
- Remove entire function

### 5. process_pdf_with_gpt4o_vision
- Find: `def process_pdf_with_gpt4o_vision`
- Remove entire function

## ⏳ TO DO - Remove These Endpoints

Find and remove these @app.route decorators and their handler functions:

### 1. /api/upload_llmwhisperer
- Find: `@app.route('/api/upload_llmwhisperer'`
- Remove decorator + entire `def upload_file_llmwhisperer()` function

### 2. /api/upload_direct_llm
- Find: `@app.route('/api/upload_direct_llm'`
- Remove decorator + entire function

### 3. /api/upload_gpt4o_vision
- Find: `@app.route('/api/upload_gpt4o_vision'`
- Remove decorator + entire function

### 4. /api/upload_gpt4o_hybrid
- Find: `@app.route('/api/upload_gpt4o_hybrid'`
- Remove decorator + entire function

### 5. /api/upload_unstract
- Find: `@app.route('/api/upload_unstract'`  
- Remove decorator + entire function

## 🔍 KEEP THESE (DO NOT REMOVE)
- `process_pdf_with_ocr_and_camelot` - Basic OCR
- `process_pdf_with_glm_custom_query` - GLM custom query ✅
- `process_pdf_extract_serial_numbers` - Serial number extraction
- `convert_pdf_to_searchable_ocrmypdf` - OCRmyPDF conversion ✅
- `convert_pdf_to_searchable_convertapi` - ConvertAPI conversion ✅
- `/api/upload` - Basic upload
- `/api/upload_ocrmypdf` - OCRmyPDF endpoint ✅
- `/api/upload_convertapi_ocr` - ConvertAPI endpoint ✅
- `/api/upload_glm_custom_query` - GLM custom query endpoint ✅
- `/api/upload_glm_table_extraction` - GLM table extraction ✅

---

## Frontend Cleanup (Next Step)

### authService.js - Remove these methods:
- `uploadFileUnstract()`
- `uploadFileLLMWhisperer()`  
- `uploadFileDirectLLM()`
- `uploadFileGPT4oVision()`
- `uploadFileGPT4oHybrid()`

### Dashboard.js - Remove these radio options:
- "Unstract API"
- "LLMWhisperer"
- "AWS Textract (Custom Queries)"
- "Create Searchable PDF (AWS Textract)"
- "GPT-4o Vision"
- "GPT-4o Hybrid"

### Dashboard.js - Remove these handlers:
- `uploadFileUnstract()`
- `uploadFileLLMWhisperer()`
- `uploadFileDirectLLM()`
- `uploadFileGPT4oVision()`
- `uploadFileGPT4oHybrid()`

### Dashboard.js - Remove results display components for deleted methods

---

**Current Progress:** Backend 20% complete (config + 1 function removed)
**Estimated Lines to Remove:** ~2500 lines total across backend + frontend

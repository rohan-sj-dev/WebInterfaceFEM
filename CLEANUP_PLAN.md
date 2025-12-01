# Cleanup Plan - Remove Unnecessary Extraction Methods

## Keep Only These Features:
1. ✅ GLM Table Extraction
2. ✅ GLM Custom Query Extraction  
3. ✅ Serial Number Extraction
4. ✅ Convert to Searchable PDF (OCRmyPDF)
5. ✅ Convert to Searchable PDF (ConvertAPI)

## Remove These Features:
1. ❌ Local OCR / Basic Text Extraction
2. ❌ Unstract API
3. ❌ LLMWhisperer
4. ❌ AWS Textract (Custom Queries / Direct LLM)
5. ❌ AWS Textract (Create Searchable PDF)
6. ❌ GPT-4o Vision
7. ❌ GPT-4o Hybrid

---

## Backend Changes (app.py)

### Remove Configuration (lines 31-47):
```python
# UNSTRACT CONFIGURATION
UNSTRACT_DEFAULT_URL = ...
UNSTRACT_DEFAULT_API_KEY = ...
UNSTRACT_QA_URL = ...

# LLMWHISPERER CONFIGURATION  
LLMWHISPERER_API_URL = ...
LLMWHISPERER_API_KEY = ...

# OPENAI CONFIGURATION
OPENAI_API_KEY = ...
```

### Remove Functions:
- `process_pdf_with_unstract()` (line ~359)
- `process_pdf_with_llmwhisperer()` (line ~600-800)
- `process_pdf_textract_custom_queries()` (line ~900-1100)
- `process_pdf_textract_searchable()` (line ~1200-1400)
- `process_pdf_with_gpt4o_vision()` (line ~1500-1700)
- `process_pdf_with_gpt4o_hybrid()` (line ~1800-2000)
- `process_pdf_local_ocr()` (if exists)

### Remove Endpoints:
- `/api/upload_unstract` (line ~3358)
- `/api/upload_llmwhisperer` (line ~2585)
- `/api/upload_direct_llm` (line ~2642)
- `/api/upload_gpt4o_vision` (line ~3232)
- `/api/upload_gpt4o_hybrid` (line ~3295)
- `/api/upload_local_ocr` (if exists)
- `/api/upload_textract_searchable` (if exists)

---

## Frontend Changes

### authService.js - Remove Methods:
- `uploadFileUnstract()`
- `uploadFileLLMWhisperer()`
- `uploadFileDirectLLM()`
- `uploadFileGPT4oVision()`
- `uploadFileGPT4oHybrid()`
- `uploadFileLocalOCR()` (if exists)

### Dashboard.js - Remove Radio Options:
- "Local OCR - Basic text extraction"
- "Unstract API - Cloud-based Table Extraction"
- "LLMWhisperer - Text extraction with layout"
- "AWS Textract (Custom Queries)"
- "Create Searchable PDF (AWS Textract)"
- "GPT-4o Vision"
- "GPT-4o Hybrid"

### Dashboard.js - Remove Upload Handlers:
- `uploadFileUnstract()`
- `uploadFileLLMWhisperer()`
- `uploadFileDirectLLM()`
- `uploadFileGPT4oVision()`
- `uploadFileGPT4oHybrid()`

### Dashboard.js - Remove Results Display:
- Unstract results component
- LLMWhisperer results component
- AWS Textract results component
- GPT-4o results components

---

## Imports to Remove from app.py:
```python
from openai import OpenAI  # If only used for GPT-4o
# Remove AWS imports if AWS Textract completely removed
```

---

## Testing After Cleanup:
1. Test GLM Table Extraction
2. Test GLM Custom Query
3. Test Serial Number Extraction
4. Test OCRmyPDF searchable conversion
5. Test ConvertAPI searchable conversion

---

## Execution Steps:
Due to the extensive nature of these changes (removing ~2000+ lines across multiple files), it's recommended to:

1. **Backup current code** first
2. **Remove backend code** (app.py)
3. **Remove frontend code** (Dashboard.js, authService.js)
4. **Test each remaining feature**
5. **Commit changes**

Would you like me to proceed with the automated cleanup?

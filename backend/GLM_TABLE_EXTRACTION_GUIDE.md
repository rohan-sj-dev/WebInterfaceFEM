# GLM-4.5V Table Extraction Integration

Complete! GLM-4.5V table extraction has been integrated into the backend.

## Setup

1. **Get GLM API Key:**
   - Visit: https://z.ai/manage-apikey/apikey-list
   - Create an account and generate an API key
   - Add to `.env` file:
     ```
     GLM_API_KEY=your-api-key-here
     ```

2. **Install Dependencies:**
   ```powershell
   pip install requests PyMuPDF pillow
   ```

## API Endpoint

### `/api/upload_glm_table_extraction`

**Method:** POST  
**Authentication:** JWT Required  
**Content-Type:** multipart/form-data

**Parameters:**
- `file` (required): PDF file to extract tables from
- `custom_prompt` (optional): Custom extraction prompt

**Response:**
```json
{
  "task_id": "uuid",
  "message": "GLM table extraction started",
  "status": "processing"
}
```

**Status Polling:** Use `/api/status/<task_id>` to check progress

**Completed Response:**
```json
{
  "status": "completed",
  "output_file": "path/to/tables.csv",
  "output_filename": "tables_20251127_123456.csv",
  "extracted_content": "CSV data...",
  "model_used": "glm-4.5v",
  "tokens_used": 1234,
  "pages_processed": 3
}
```

## Frontend Integration

### Service Function (authService.js)

```javascript
uploadFileGLMTableExtraction: async (file, customPrompt = '') => {
  const formData = new FormData();
  formData.append('file', file);
  if (customPrompt) {
    formData.append('custom_prompt', customPrompt);
  }

  return await api.post('/upload_glm_table_extraction', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
},
```

### Dashboard UI (Dashboard.js)

Add new extraction method option:

```javascript
<label className="flex items-start cursor-pointer">
  <input
    type="radio"
    name="extractionMethod"
    value="glm_table_extraction"
    checked={extractionMethod === 'glm_table_extraction'}
    onChange={(e) => setExtractionMethod(e.target.value)}
    className="h-4 w-4 mt-0.5 text-primary-600 border-gray-300 focus:ring-primary-500"
  />
  <div className="ml-3">
    <span className="text-sm font-medium text-gray-900">GLM-4.5V Table Extraction</span>
    <p className="text-xs text-gray-500">AI-powered table extraction using GLM vision model</p>
  </div>
</label>
```

Add custom prompt input (conditional):

```javascript
{extractionMethod === 'glm_table_extraction' && (
  <div className="space-y-4">
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        Custom Extraction Prompt (Optional)
      </label>
      <textarea
        value={customPrompts}
        onChange={(e) => setCustomPrompts(e.target.value)}
        className="input-field w-full h-32 resize-none"
        placeholder="Leave empty for default table extraction, or provide custom instructions..."
      />
      <p className="text-xs text-gray-500 mt-1">
        If not specified, will extract all tables in CSV format automatically
      </p>
    </div>
  </div>
)}
```

Upload handler:

```javascript
if (extractionMethod === 'glm_table_extraction') {
  response = await ocrService.uploadFileGLMTableExtraction(file, customPrompts);
  toast.success('File uploaded! Extracting tables with GLM-4.5V...');
}
```

## Usage Examples

### Default Table Extraction (No Custom Prompt)

```bash
curl -X POST http://localhost:5001/api/upload_glm_table_extraction \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -F "file=@document.pdf"
```

Automatically extracts all tables in CSV format.

### Custom Prompt Example

```bash
curl -X POST http://localhost:5001/api/upload_glm_table_extraction \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -F "file=@financial_report.pdf" \
  -F "custom_prompt=Extract only the quarterly revenue table and return it in CSV format with columns: Quarter, Revenue, Growth"
```

## Features

✅ Automatic PDF to image conversion  
✅ Multi-page support  
✅ High-resolution rendering (2x scale)  
✅ Custom prompt support  
✅ CSV output format  
✅ Background processing  
✅ Progress tracking  
✅ Token usage reporting  

## Model Details

- **Model:** GLM-4.5V (vision-language)
- **Max Output:** 16K tokens
- **Temperature:** 0.3 (low for consistent extraction)
- **Image Format:** Base64-encoded JPEG/PNG
- **API Endpoint:** https://api.z.ai/api/paas/v4/chat/completions

## Download Results

Use existing download endpoint:
```javascript
const response = await ocrService.downloadFile(taskId);
// Returns CSV file
```

## Cost Considerations

GLM-4.5V pricing (check Z.AI docs for current rates):
- Input: ~$X per 1M tokens
- Output: ~$Y per 1M tokens
- Image processing counts as input tokens

Typical usage:
- 1 page PDF = ~500-1000 tokens
- 10 page document = ~5K-10K tokens

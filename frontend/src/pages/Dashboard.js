import React, { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { 
  Upload, 
  Download, 
  CheckCircle, 
  AlertCircle,
  LogOut,
  User,
  Play
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { ocrService } from '../services/authService';
import { toast } from 'react-toastify';

const Dashboard = () => {
  const { user, logout } = useAuth();
  const [file, setFile] = useState(null);
  const [processing, setProcessing] = useState(false);
  const [processedResults, setProcessedResults] = useState(null);
  const [options, setOptions] = useState({
    language: 'eng',
    deskew: true,
    clean: false,
    optimize: '1',
    force_ocr: false,
    extract_tables: true,
    use_unstract: false
  });
  const [customPrompts, setCustomPrompts] = useState('');
  const [selectedModel, setSelectedModel] = useState('gpt-4-turbo');
  const [extractionMethod, setExtractionMethod] = useState('unstract'); // 'local', 'unstract', 'direct_llm'

  const onDrop = useCallback((acceptedFiles) => {
    if (acceptedFiles.length > 0) {
      setFile(acceptedFiles[0]);
      setProcessedResults(null);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf']
    },
    maxFiles: 1,
    maxSize: 100 * 1024 * 1024 // 100MB
  });

  const handleOptionChange = (key, value) => {
    setOptions({
      ...options,
      [key]: value
    });
  };

  const handleProcessFile = async () => {
    if (!file) {
      toast.error('Please select a PDF file first');
      return;
    }

    // Clear old results before starting new processing
    setProcessedResults(null);
    setProcessing(true);
    
    try {
      let response;
      
      // Choose extraction method
      if (extractionMethod === 'llmwhisperer') {
        // LLMWhisperer text extraction
        response = await ocrService.uploadFileLLMWhisperer(file);
        toast.success('File uploaded! Processing with LLMWhisperer...');
      } else if (extractionMethod === 'direct_llm') {
        // Direct LLM calling (GPT-4o/Claude)
        response = await ocrService.uploadFileDirectLLM(file, customPrompts, selectedModel);
        toast.success(`File uploaded! Processing with ${selectedModel}...`);
      } else if (extractionMethod === 'unstract') {
        // Unstract API
        response = await ocrService.uploadFileUnstract(file, customPrompts, selectedModel);
        toast.success('File uploaded to Unstract! Processing started...');
      } else {
        // Local OCR
        response = await ocrService.uploadFile(file, options);
        toast.success('File uploaded successfully! Processing started...');
      }
      
      const taskId = response.task_id;
      
      // Poll for status updates
      const pollInterval = setInterval(async () => {
        try {
          const statusResponse = await ocrService.getStatus(taskId);
          console.log('Poll response:', statusResponse); // Debug log
          
          if (statusResponse.status === 'completed') {
            clearInterval(pollInterval);
            
            // Force a clean state update by spreading the response
            const newResults = {
              taskId,
              ...statusResponse,
              timestamp: Date.now() // Add timestamp to force re-render
            };
            
            console.log('Setting new results:', newResults); // Debug log
            setProcessedResults(newResults);
            setProcessing(false);
            toast.success('Processing completed successfully!');
          } else if (statusResponse.status === 'error') {
            clearInterval(pollInterval);
            setProcessing(false);
            toast.error(`Processing failed: ${statusResponse.message}`);
          }
        } catch (error) {
          clearInterval(pollInterval);
          setProcessing(false);
          toast.error('Error checking processing status');
        }
      }, 2000);
      
    } catch (error) {
      setProcessing(false);
      toast.error('Failed to upload file');
    }
  };

  const handleDownload = async (type = 'pdf') => {
    if (!processedResults) return;
    
    try {
      const response = type === 'all' 
        ? await ocrService.downloadAll(processedResults.taskId)
        : await ocrService.downloadFile(processedResults.taskId);
      
      const blob = new Blob([response.data]);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      
      // Set filename based on extraction method
      if (processedResults.extraction_method === 'llmwhisperer') {
        a.download = type === 'all' ? 'OCR_Results.zip' : 'extracted_text.txt';
      } else if (processedResults.extraction_method === 'direct_llm') {
        a.download = type === 'all' ? 'OCR_Results.zip' : 'llm_extraction.txt';
      } else {
        a.download = type === 'all' ? 'OCR_Results.zip' : 'searchable_document.pdf';
      }
      
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      
      toast.success('Download started!');
    } catch (error) {
      toast.error(`Download failed: ${error.response?.data?.error || error.message}`);
    }
  };

  const handleLaunchABAQUS = async (csvData) => {
    try {
      // Call backend to launch ABAQUS with the CSV data
      const response = await ocrService.launchABAQUS(csvData);
      
      if (response.success) {
        toast.success('ABAQUS simulation launched successfully!');
      } else {
        toast.error(`Failed to launch ABAQUS: ${response.message}`);
      }
    } catch (error) {
      toast.error(`Failed to launch ABAQUS: ${error.response?.data?.error || error.message}`);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-50 to-white">
      {/* Header */}
      <header className="bg-white/80 backdrop-blur-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center">
              <h1 className="text-xl font-semibold text-gray-900">
                Searchable PDF Converter
              </h1>
            </div>
            
            <div className="flex items-center space-x-4">
              <div className="flex items-center text-sm text-gray-600">
                <User className="h-4 w-4 mr-2" />
                {user?.fullName}
              </div>
              <button
                onClick={logout}
                className="btn-secondary"
              >
                <LogOut className="h-4 w-4 mr-2" />
                Logout
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="space-y-6">
          
          {/* Main Content - Upload and Options */}
          <div className="w-full space-y-6">
            
            {/* Upload Section */}
            <div className="card p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">
                Convert PDF to Searchable Document
              </h2>
              
              <div
                {...getRootProps()}
                className={`dropzone ${isDragActive ? 'dropzone-active' : ''}`}
              >
                <input {...getInputProps()} />
                <Upload className="h-12 w-12 text-gray-400 mx-auto mb-4" />
                {file ? (
                  <div className="text-center">
                    <p className="text-lg font-medium text-gray-900">{file.name}</p>
                    <p className="text-sm text-gray-500">
                      {(file.size / (1024 * 1024)).toFixed(2)} MB
                    </p>
                  </div>
                ) : (
                  <div className="text-center">
                    <p className="text-lg font-medium text-gray-700 mb-2">
                      {isDragActive ? 'Drop your PDF here' : 'Drop PDF here or click to upload'}
                    </p>
                    <p className="text-sm text-gray-500">
                      Transform your scanned PDFs into searchable documents
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      Maximum file size: 100MB
                    </p>
                  </div>
                )}
              </div>
            </div>

            {/* Processing Options */}
            <div className="card p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">
                Processing Options
              </h2>
              
              <div className="space-y-6">
                {/* Extraction Method Selector */}
                <div className="border-b border-gray-200 pb-4">
                  <label className="block text-sm font-semibold text-gray-900 mb-3">
                    Extraction Method
                  </label>
                  <div className="space-y-3">
                    <label className="flex items-start cursor-pointer">
                      <input
                        type="radio"
                        name="extractionMethod"
                        value="local"
                        checked={extractionMethod === 'local'}
                        onChange={(e) => setExtractionMethod(e.target.value)}
                        className="h-4 w-4 mt-0.5 text-primary-600 border-gray-300 focus:ring-primary-500"
                      />
                      <div className="ml-3">
                        <span className="text-sm font-medium text-gray-900">Local OCR</span>
                        <p className="text-xs text-gray-500">Basic text extraction using local libraries</p>
                      </div>
                    </label>
                    
                    <label className="flex items-start cursor-pointer">
                      <input
                        type="radio"
                        name="extractionMethod"
                        value="unstract"
                        checked={extractionMethod === 'unstract'}
                        onChange={(e) => setExtractionMethod(e.target.value)}
                        className="h-4 w-4 mt-0.5 text-primary-600 border-gray-300 focus:ring-primary-500"
                      />
                      <div className="ml-3">
                        <span className="text-sm font-medium text-gray-900">Unstract API</span>
                        <p className="text-xs text-gray-500">Cloud-based extraction with predefined invoice template (CSV only)</p>
                      </div>
                    </label>
                    
                    <label className="flex items-start cursor-pointer">
                      <input
                        type="radio"
                        name="extractionMethod"
                        value="llmwhisperer"
                        checked={extractionMethod === 'llmwhisperer'}
                        onChange={(e) => setExtractionMethod(e.target.value)}
                        className="h-4 w-4 mt-0.5 text-primary-600 border-gray-300 focus:ring-primary-500"
                      />
                      <div className="ml-3">
                        <span className="text-sm font-medium text-gray-900">🎯 LLMWhisperer</span>
                        <p className="text-xs text-gray-500">High-quality text extraction with layout preservation (Unstract OCR)</p>
                      </div>
                    </label>
                    
                    <label className="flex items-start cursor-pointer">
                      <input
                        type="radio"
                        name="extractionMethod"
                        value="direct_llm"
                        checked={extractionMethod === 'direct_llm'}
                        onChange={(e) => setExtractionMethod(e.target.value)}
                        className="h-4 w-4 mt-0.5 text-primary-600 border-gray-300 focus:ring-primary-500"
                      />
                      <div className="ml-3">
                        <span className="text-sm font-medium text-gray-900">Direct LLM (Custom Prompts)</span>
                        <p className="text-xs text-gray-500">GPT-4o or Claude 3.5 with full custom prompt support</p>
                      </div>
                    </label>
                  </div>
                </div>
                
                {/* Model & Prompt Selection - Show for Unstract or Direct LLM */}
                {(extractionMethod === 'unstract' || extractionMethod === 'direct_llm') && (
                  <div className="space-y-4">
                    {/* Model Selection */}
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        AI Model
                      </label>
                      <select
                        value={selectedModel}
                        onChange={(e) => setSelectedModel(e.target.value)}
                        className="input-field w-full"
                      >
                        {extractionMethod === 'direct_llm' ? (
                          <>
                            <option value="gpt-4o">GPT-4o (Recommended for tables)</option>
                            <option value="gpt-4-turbo">GPT-4 Turbo</option>
                            <option value="claude-3-5-sonnet-20241022">Claude 3.5 Sonnet</option>
                          </>
                        ) : (
                          <>
                            <option value="gpt-4-turbo">GPT-4 Turbo</option>
                            <option value="azure-gpt-4o">Azure GPT-4o</option>
                          </>
                        )}
                      </select>
                      <p className="mt-1 text-xs text-gray-500">
                        {extractionMethod === 'direct_llm' 
                          ? 'GPT-4o has best table extraction accuracy' 
                          : 'Choose the AI model for extraction'
                        }
                      </p>
                    </div>
                    
                    {/* Custom Prompts */}
                    {extractionMethod === 'direct_llm' && (
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Custom Extraction Prompt
                        </label>
                        <textarea
                          value={customPrompts}
                          onChange={(e) => setCustomPrompts(e.target.value)}
                          className="input-field w-full h-32 resize-none"
                          placeholder="Enter your custom extraction instructions here...&#10;&#10;Example:&#10;Extract all invoice data including customer details, line items, and totals. Format as CSV with proper headers."
                        />
                        <p className="mt-1 text-xs text-gray-500">
                          Specify exactly what data you want to extract and how to format it
                        </p>
                      </div>
                    )}
                  </div>
                )}
                
                {/* Local OCR Options */}
                {extractionMethod === 'local' && (
                  <>
                    {/* Language Selection */}
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        OCR Language
                      </label>
                      <select
                        value={options.language}
                        onChange={(e) => handleOptionChange('language', e.target.value)}
                        className="input-field w-full"
                      >
                        <option value="eng">English</option>
                        <option value="spa">Spanish</option>
                        <option value="fra">French</option>
                        <option value="deu">German</option>
                        <option value="chi_sim">Chinese (Simplified)</option>
                      </select>
                    </div>

                    {/* Enhancement Options */}
                    <div className="space-y-3">
                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          checked={options.deskew}
                          onChange={(e) => handleOptionChange('deskew', e.target.checked)}
                          className="h-4 w-4 text-primary-600 rounded border-gray-300 focus:ring-primary-500"
                        />
                        <span className="ml-2 text-sm text-gray-700">
                          Auto-rotate and deskew pages
                        </span>
                      </label>

                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          checked={options.clean}
                          onChange={(e) => handleOptionChange('clean', e.target.checked)}
                          className="h-4 w-4 text-primary-600 rounded border-gray-300 focus:ring-primary-500"
                        />
                        <span className="ml-2 text-sm text-gray-700">
                          Clean and remove noise from pages
                        </span>
                      </label>

                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          checked={options.force_ocr}
                          onChange={(e) => handleOptionChange('force_ocr', e.target.checked)}
                          className="h-4 w-4 text-primary-600 rounded border-gray-300 focus:ring-primary-500"
                        />
                        <span className="ml-2 text-sm text-gray-700">
                          Force OCR on all pages (even if text exists)
                        </span>
                      </label>
                    </div>
                  </>
                )}
                
                {/* Old checkbox - keeping for backwards compatibility but hidden */}
                <input
                  type="checkbox"
                  checked={extractionMethod !== 'local'}
                  onChange={(e) => setExtractionMethod(e.target.checked ? 'unstract' : 'local')}
                  className="hidden"
                />
              </div>
            </div>

            {/* Remove old options section */}
            <div className="hidden">
              <div className="space-y-6">
                {/* Extraction Method */}
                <div className="border-b border-gray-200 pb-4">
                  <label className="flex items-center">
                    <input
                      type="checkbox"
                      checked={options.use_unstract}
                      onChange={(e) => handleOptionChange('use_unstract', e.target.checked)}
                      className="h-4 w-4 text-primary-600 rounded border-gray-300 focus:ring-primary-500"
                    />
                    <span className="ml-2 text-sm font-semibold text-gray-900">
                      Extract data via Unstract API
                    </span>
                  </label>
                  <p className="ml-6 mt-1 text-xs text-gray-500">
                    Use cloud-based Unstract AI for advanced data extraction
                  </p>
                  
                  {/* Custom Prompts - Only show if Unstract is selected */}
                  {options.use_unstract && (
                    <div className="ml-6 mt-4 space-y-4">
                      {/* Model Selection */}
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          AI Model
                        </label>
                        <select
                          value={selectedModel}
                          onChange={(e) => setSelectedModel(e.target.value)}
                          className="input-field w-full"
                        >
                          <option value="gpt-4-turbo">GPT-4 Turbo</option>
                          <option value="azure-gpt-4o">Azure GPT-4o</option>
                        </select>
                        <p className="mt-1 text-xs text-gray-500">
                          Choose the AI model for extraction
                        </p>
                      </div>
                      
                      {/* Custom Prompts */}
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Custom Extraction Prompts
                        </label>
                        <textarea
                          value={customPrompts}
                          onChange={(e) => setCustomPrompts(e.target.value)}
                          placeholder="Enter custom instructions to override default invoice extraction"
                          rows={5}
                          className="input-field w-full resize-vertical"
                        />

                      </div>
                    </div>
                  )}
                </div>

                {/* Local OCR Options - Only show if Unstract is NOT selected */}
                {!options.use_unstract && (
                  <>
                    {/* Optimization */}
                    <div className="max-w-lg mx-auto">
                      <label className="block text-sm font-medium text-gray-700 mb-2 text-center">
                        Optimization Level
                      </label>
                      <select
                        value={options.optimize}
                        onChange={(e) => handleOptionChange('optimize', e.target.value)}
                        className="input-field w-full"
                      >
                        <option value="0">No optimization (Largest file)</option>
                        <option value="1">Basic optimization (Recommended)</option>
                        <option value="2">Moderate optimization (Smaller file)</option>
                        <option value="3">Aggressive optimization (Smallest file)</option>
                      </select>
                    </div>

                    {/* Checkboxes */}
                    <div className="space-y-3 max-w-lg mx-auto">
                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          checked={options.deskew}
                          onChange={(e) => handleOptionChange('deskew', e.target.checked)}
                          className="h-4 w-4 text-primary-600 rounded border-gray-300 focus:ring-primary-500"
                        />
                        <span className="ml-2 text-sm text-gray-700">
                          <strong>Deskew</strong> - Fix tilted or rotated pages
                        </span>
                      </label>

                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          checked={options.clean}
                          onChange={(e) => handleOptionChange('clean', e.target.checked)}
                          className="h-4 w-4 text-primary-600 rounded border-gray-300 focus:ring-primary-500"
                        />
                        <span className="ml-2 text-sm text-gray-700">
                          <strong>Clean</strong> - Remove noise and artifacts
                        </span>
                      </label>

                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          checked={options.force_ocr}
                          onChange={(e) => handleOptionChange('force_ocr', e.target.checked)}
                          className="h-4 w-4 text-primary-600 rounded border-gray-300 focus:ring-primary-500"
                        />
                        <span className="ml-2 text-sm text-gray-700">
                          <strong>Force OCR</strong> - Re-process existing text layers
                        </span>
                      </label>

                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          checked={options.extract_tables}
                          onChange={(e) => handleOptionChange('extract_tables', e.target.checked)}
                          className="h-4 w-4 text-primary-600 rounded border-gray-300 focus:ring-primary-500"
                        />
                        <span className="ml-2 text-sm text-gray-700">
                          <strong>Extract Tables</strong> - Export tables to CSV/Excel
                        </span>
                      </label>
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Process Button */}
            <button
              onClick={handleProcessFile}
              disabled={!file || processing}
              className="w-full btn-primary h-12 text-base font-medium"
            >
              {processing ? (
                <div className="flex items-center justify-center">
                  <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                  {options.use_unstract ? 'Processing with Unstract...' : 'Processing...'}
                </div>
              ) : (
                <div className="flex items-center justify-center">
                  {options.use_unstract ? 'Extract Data with Unstract' : 'Start Converting to Searchable PDF'}
                </div>
              )}
            </button>
          </div>

          {/* Results Section */}
          {(processing || processedResults) && (
            <div className="w-full">
              
              {/* Processing Status */}
              {processing && (
                <div className="card p-6 animate-fade-in mb-6">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4 text-center">
                    Processing Status
                  </h3>
                  <div className="space-y-3 max-w-md mx-auto">
                    <div className="flex items-center justify-center text-blue-600">
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600 mr-2"></div>
                      OCR Processing in progress...
                    </div>
                    <div className="bg-gray-200 rounded-full h-2">
                      <div className="bg-primary-600 h-2 rounded-full animate-pulse-soft" style={{width: '60%'}}></div>
                    </div>
                  </div>
                </div>
              )}

              {/* Results */}
              {processedResults && (
                <div className="card p-6 animate-fade-in">
                  <h3 className={`text-lg font-semibold mb-4 flex items-center justify-center ${
                    processedResults.status === 'error' ? 'text-red-900' : 'text-gray-900'
                  }`}>
                    {processedResults.status === 'error' ? (
                      <>
                        <AlertCircle className="h-5 w-5 text-red-500 mr-2" />
                        Processing Failed
                      </>
                    ) : (
                      <>
                        <CheckCircle className="h-5 w-5 text-green-500 mr-2" />
                        Processing Complete
                      </>
                    )}
                  </h3>
                  
                  <div className="space-y-4 max-w-4xl mx-auto">
                    {/* Unstract Error Display */}
                    {processedResults.extraction_method === 'unstract' && processedResults.status === 'error' && (
                      <div className="bg-red-50 border-2 border-red-200 rounded-lg p-6">
                        <div className="flex items-start gap-3">
                          <AlertCircle className="h-6 w-6 text-red-500 flex-shrink-0 mt-0.5" />
                          <div className="flex-1">
                            <h4 className="text-sm font-semibold text-red-900 mb-2">
                              Unstract Processing Error
                            </h4>
                            <p className="text-sm text-red-800 mb-3">
                              {processedResults.message || processedResults.error}
                            </p>
                            
                            {/* Show file-level errors if available */}
                            {processedResults.unstract_data && processedResults.unstract_data.length > 0 && (
                              <div className="mt-3 space-y-2">
                                {processedResults.unstract_data.map((fileResult, idx) => (
                                  <div key={idx} className="bg-white border border-red-200 rounded p-3">
                                    <p className="text-xs font-semibold text-gray-700 mb-1">
                                      📄 {fileResult.file}
                                    </p>
                                    <p className="text-xs text-red-700">
                                      {fileResult.error}
                                    </p>
                                  </div>
                                ))}
                              </div>
                            )}
                            
                            <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded">
                              <p className="text-xs text-yellow-800">
                                <strong>Common Solutions:</strong>
                              </p>
                              <ul className="text-xs text-yellow-700 mt-2 ml-4 space-y-1 list-disc">
                                <li>This error occurs when Unstract's highlighting feature has issues with the PDF</li>
                                <li>Try uploading a different PDF file</li>
                                <li>Or contact your Unstract administrator to re-index the documents</li>
                                <li>You can also try using the local OCR option instead</li>
                              </ul>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                    
                    {/* Unstract, Direct LLM & LLMWhisperer Success Results */}
                    {(processedResults.extraction_method === 'unstract' || processedResults.extraction_method === 'direct_llm' || processedResults.extraction_method === 'llmwhisperer') && processedResults.unstract_data && processedResults.status !== 'error' && (
                      <div className="space-y-4">
                        <div className={`border rounded-lg p-4 ${
                          processedResults.extraction_method === 'direct_llm' 
                            ? 'bg-purple-50 border-purple-200'
                            : processedResults.extraction_method === 'llmwhisperer'
                            ? 'bg-green-50 border-green-200' 
                            : 'bg-blue-50 border-blue-200'
                        }`}>
                          <h4 className={`text-sm font-semibold mb-2 ${
                            processedResults.extraction_method === 'direct_llm'
                              ? 'text-purple-900'
                              : processedResults.extraction_method === 'llmwhisperer'
                              ? 'text-green-900'
                              : 'text-blue-900'
                          }`}>
                            {processedResults.extraction_method === 'direct_llm' 
                              ? '🤖 Direct LLM Extraction Results'
                              : processedResults.extraction_method === 'llmwhisperer'
                              ? '🎯 LLMWhisperer Text Extraction Results' 
                              : 'Unstract AI Extraction Results'
                            }
                          </h4>
                          
                          {/* Download button for LLMWhisperer and Direct LLM */}
                          {(processedResults.extraction_method === 'llmwhisperer' || processedResults.extraction_method === 'direct_llm') && (
                            <button
                              onClick={() => handleDownload('pdf')}
                              className={`mt-2 w-full text-sm px-4 py-2 rounded transition-colors flex items-center justify-center ${
                                processedResults.extraction_method === 'llmwhisperer'
                                  ? 'bg-green-600 hover:bg-green-700 text-white'
                                  : 'bg-purple-600 hover:bg-purple-700 text-white'
                              }`}
                            >
                              <Download className="h-4 w-4 mr-2" />
                              Download Extracted Text (.txt)
                            </button>
                          )}
                          
                        </div>
                        
                        {/* Display each file's results */}
                        {processedResults.unstract_data.map((fileResult, idx) => (
                          <div key={idx} className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                            <div className="flex items-center justify-between mb-3">
                              <h5 className="text-sm font-semibold text-gray-900">
                                 {fileResult.file}
                              </h5>
                              <span className={`text-xs px-2 py-1 rounded ${
                                fileResult.status === 'Success' 
                                  ? 'bg-green-100 text-green-800' 
                                  : 'bg-red-100 text-red-800'
                              }`}>
                                {fileResult.status}
                              </span>
                            </div>
                            
                            {fileResult.result && fileResult.result.output && (
                              <div className="space-y-3">
                                {/* Display all outputs from the single invoice API */}
                                {Object.entries(fileResult.result.output).map(([key, value]) => {
                                  // Determine if this is CSV format
                                  const isCSV = typeof value === 'string' && (
                                    value.includes(',') && value.split('\n').length > 1
                                  );
                                  
                                  return (
                                    <div key={key} className="border-t border-gray-100 pt-3">
                                      <h6 className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-2">
                                         {key.replace(/_/g, ' ').toUpperCase()}
                                      </h6>
                                      <div className="bg-gray-50 rounded p-3 max-h-96 overflow-y-auto">
                                        <pre className="text-xs text-gray-800 whitespace-pre-wrap font-mono">
                                          {value}
                                        </pre>
                                      </div>
                                      
                                      {/* Download button for CSV data */}
                                      {isCSV && (
                                        <div className="mt-2 flex gap-2">
                                          <button
                                            onClick={() => {
                                              const blob = new Blob([value], { type: 'text/csv' });
                                              const url = window.URL.createObjectURL(blob);
                                              const a = document.createElement('a');
                                              a.href = url;
                                              a.download = `${fileResult.file.replace('.pdf', '')}_${key}.csv`;
                                              a.click();
                                              window.URL.revokeObjectURL(url);
                                            }}
                                            className="text-xs bg-primary-600 text-white px-3 py-1 rounded hover:bg-primary-700 transition-colors"
                                          >
                                            Download CSV
                                          </button>
                                          <button
                                            onClick={() => handleLaunchABAQUS(value)}
                                            className="text-xs bg-green-600 text-white px-3 py-1 rounded hover:bg-green-700 transition-colors flex items-center gap-1"
                                          >
                                            <Play className="h-3 w-3" />
                                            Run ABAQUS Simulation
                                          </button>
                                        </div>
                                      )}
                                      
                                      {/* Download button for other formats */}
                                      {!isCSV && (
                                        <div className="mt-2 flex gap-2">
                                          <button
                                            onClick={() => {
                                              const blob = new Blob([value], { type: 'text/plain' });
                                              const url = window.URL.createObjectURL(blob);
                                              const a = document.createElement('a');
                                              a.href = url;
                                              a.download = `${fileResult.file.replace('.pdf', '')}_${key}.txt`;
                                              a.click();
                                              window.URL.revokeObjectURL(url);
                                            }}
                                            className="text-xs bg-gray-600 text-white px-3 py-1 rounded hover:bg-gray-700 transition-colors"
                                          >
                                            Download Text
                                          </button>
                                        </div>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                            
                            {fileResult.error && (
                              <div className="bg-red-50 border border-red-200 rounded p-3 mt-3">
                                <p className="text-xs text-red-800">
                                  ❌ Error: {fileResult.error}
                                </p>
                              </div>
                            )}
                            
                            
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Local OCR Results */}
                    {processedResults.extraction_method !== 'unstract' && processedResults.extraction_method !== 'llmwhisperer' && processedResults.extraction_method !== 'direct_llm' && (
                      <>
                        {/* Summary */}
                        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                          <p className="text-sm text-green-800 text-center">
                            Your PDF has been successfully converted to a searchable document.
                            {processedResults.tables && processedResults.tables.length > 0 && (
                              ` Found ${processedResults.tables.length} table(s).`
                            )}
                          </p>
                        </div>

                        {/* Download Options */}
                        <div className="space-y-2">
                          <button
                            onClick={() => handleDownload('pdf')}
                            className="w-full btn-primary"
                          >
                            <Download className="h-4 w-4 mr-2" />
                            Download Searchable PDF
                          </button>
                          
                          {processedResults.tables && processedResults.tables.length > 0 && (
                            <button
                              onClick={() => handleDownload('all')}
                              className="w-full btn-secondary"
                            >
                              <Download className="h-4 w-4 mr-2" />
                              Download All Files (ZIP)
                            </button>
                          )}
                        </div>

                        {/* Tables Summary */}
                        {processedResults.tables && processedResults.tables.length > 0 && (
                          <div className="border-t border-gray-200 pt-4">
                            <h4 className="text-sm font-medium text-gray-900 mb-2 text-center">
                              Extracted Tables ({processedResults.tables.length})
                            </h4>
                            <div className="space-y-2 max-h-40 overflow-y-auto">
                              {processedResults.tables.map((table, index) => (
                                <div key={index} className="text-xs bg-gray-50 rounded p-2">
                                  <div className="font-medium">{table.csv_file || table.excel_file}</div>
                                  <div className="text-gray-500">
                                    {table.rows} rows × {table.columns} columns
                                    {table.accuracy && ` • ${(table.accuracy * 100).toFixed(1)}% accuracy`}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
};

export default Dashboard;

import React, { useState, useCallback, useRef, useEffect } from 'react';
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
  const [serialNumber, setSerialNumber] = useState('');
  const [simRunning, setSimRunning] = useState(false);
  const [simLog, setSimLog] = useState('');
  const [simStatus, setSimStatus] = useState(null);
  const [simTaskId, setSimTaskId] = useState(null);
  const [outputFiles, setOutputFiles] = useState(null);
  const simPollRef = useRef(null);

  // Run ABAQUS simulation
  const handleRunSimulation = async (taskId) => {
    try {
      setSimRunning(true);
      setSimLog('Starting ABAQUS simulation...\n');
      setSimStatus('running');
      
      const response = await ocrService.runAbaqusSimulation(taskId);
      console.log('Simulation response:', response); // Debug log
      const simId = response.data?.simulation_task_id || response.simulation_task_id;
      
      if (!simId) {
        throw new Error('No simulation task ID received');
      }
      
      setSimTaskId(simId);
      
      // Poll for simulation status
      const pollSimulation = async () => {
        try {
          const statusResponse = await ocrService.getSimulationStatus(simId);
          console.log('Status response:', statusResponse); // Debug log
          const data = statusResponse.data || statusResponse;
          console.log('Simulation data:', data);
          console.log('Output files:', data.output_files);
          
          setSimLog(data.output || '');
          setSimStatus(data.status);
          setOutputFiles(data.output_files || null);
          
          if (data.status === 'running') {
            simPollRef.current = setTimeout(pollSimulation, 2000);
          } else if (data.status === 'completed') {
            setSimRunning(false);
            toast.success('ABAQUS simulation completed successfully!');
          } else if (data.status === 'error') {
            setSimRunning(false);
            toast.error(data.message || 'Simulation failed');
          }
        } catch (error) {
          console.error('Error polling simulation:', error);
          setSimRunning(false);
          setSimStatus('error');
          toast.error('Failed to get simulation status');
        }
      };
      
      pollSimulation();
    } catch (error) {
      console.error('Error starting simulation:', error);
      setSimRunning(false);
      setSimStatus('error');
      toast.error(error.response?.data?.error || 'Failed to start simulation');
    }
  };

  // Download simulation result file
  const handleDownloadResultFile = async (fileType) => {
    try {
      const response = await ocrService.downloadResultFile(simTaskId, fileType);
      const blob = new Blob([response.data]);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `simulation_result.${fileType}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      toast.success(`Downloaded ${fileType.toUpperCase()} file!`);
    } catch (error) {
      console.error('Download error:', error);
      toast.error(`Failed to download ${fileType.toUpperCase()} file`);
    }
  };

  // Cleanup simulation polling on unmount
  useEffect(() => {
    return () => {
      if (simPollRef.current) {
        clearTimeout(simPollRef.current);
      }
    };
  }, []);

  // Helper function to parse CSV string into table data
  const parseCSV = (csvString) => {
    const lines = csvString.trim().split('\n');
    if (lines.length === 0) return { headers: [], rows: [] };
    
    const parseCSVLine = (line) => {
      const result = [];
      let current = '';
      let inQuotes = false;
      
      for (let i = 0; i < line.length; i++) {
        const char = line[i];
        
        if (char === '"') {
          inQuotes = !inQuotes;
        } else if (char === ',' && !inQuotes) {
          result.push(current.trim());
          current = '';
        } else {
          current += char;
        }
      }
      result.push(current.trim());
      return result;
    };
    
    const headers = parseCSVLine(lines[0]);
    const rows = lines.slice(1).map(line => parseCSVLine(line));
    
    return { headers, rows };
  };

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
      if (extractionMethod === 'abaqus_fem') {
        // ABAQUS FEM Integration
        if (!serialNumber || serialNumber.trim() === '') {
          toast.error('Please provide a serial number for ABAQUS FEM processing');
          setProcessing(false);
          return;
        }
        response = await ocrService.uploadFileAbaqusFEM(file, serialNumber);
        toast.success('File uploaded! Extracting dimensions and stress-strain data...');
      } else if (extractionMethod === 'llmwhisperer') {
        // LLMWhisperer text extraction
        response = await ocrService.uploadFileLLMWhisperer(file);
        toast.success('File uploaded! Processing with LLMWhisperer...');
      } else if (extractionMethod === 'searchable_pdf') {
        // Searchable PDF creation (AWS Textract)
        response = await ocrService.uploadFileSearchablePDF(file);
        toast.success('File uploaded! Creating searchable PDF with AWS Textract...');
      } else if (extractionMethod === 'ocrmypdf') {
        // Searchable PDF creation (OCRmyPDF - local)
        response = await ocrService.uploadFileOCRmyPDF(file);
        toast.success('File uploaded! Creating searchable PDF with OCRmyPDF (local, fast)...');
      } else if (extractionMethod === 'convertapi_ocr') {
        // Searchable PDF creation (ConvertAPI)
        response = await ocrService.uploadFileConvertAPIocr(file);
        toast.success('File uploaded! Creating searchable PDF with ConvertAPI...');
      } else if (extractionMethod === 'gpt4o_vision') {
        // GPT-4o Vision extraction (fast)
        if (!customPrompts || customPrompts.trim() === '') {
          toast.error('Please provide a custom query for GPT-4o Vision extraction');
          setProcessing(false);
          return;
        }
        response = await ocrService.uploadFileGPT4oVision(file, customPrompts);
        toast.success('File uploaded! Processing with GPT-4o Vision (fast)...');
      } else if (extractionMethod === 'gpt4o_hybrid') {
        // GPT-4o Hybrid extraction
        if (!customPrompts || customPrompts.trim() === '') {
          toast.error('Please provide a custom query for GPT-4o hybrid extraction');
          setProcessing(false);
          return;
        }
        response = await ocrService.uploadFileGPT4oHybrid(file, customPrompts);
        toast.success('File uploaded! Processing with GPT-4o hybrid approach...');
      } else if (extractionMethod === 'glm_table_extraction') {
        // GLM-4.5V Table Extraction
        response = await ocrService.uploadFileGLMTableExtraction(file, customPrompts);
        toast.success('File uploaded! Extracting tables with GLM-4.5V...');
      } else if (extractionMethod === 'glm_abaqus_generator') {
        // GLM ABAQUS Generator with Serial Number
        response = await ocrService.uploadFileGLMAbaqusGenerator(file, serialNumber);
        toast.success(`File uploaded! Generating ABAQUS file for ${serialNumber}...`);
      } else if (extractionMethod === 'glm_custom_query') {
        // GLM Custom Query Extraction
        if (!customPrompts || customPrompts.trim() === '') {
          toast.error('Please provide a custom query for GLM extraction');
          setProcessing(false);
          return;
        }
        response = await ocrService.uploadFileGLMCustomQuery(file, customPrompts);
        toast.success('File uploaded! Extracting data with GLM-4.5V...');
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
      } else if (processedResults.extraction_method === 'direct_llm' || processedResults.extraction_method === 'textract') {
        a.download = type === 'all' ? 'OCR_Results.zip' : 'textract_extraction.txt';
      } else if (processedResults.extraction_method === 'searchable_pdf') {
        a.download = type === 'all' ? 'OCR_Results.zip' : 'searchable_document_textract.pdf';
      } else if (processedResults.extraction_method === 'ocrmypdf') {
        a.download = type === 'all' ? 'OCR_Results.zip' : 'searchable_document_ocrmypdf.pdf';
      } else if (processedResults.extraction_method === 'convertapi_ocr') {
        a.download = type === 'all' ? 'OCR_Results.zip' : 'searchable_document_convertapi.pdf';
      } else if (processedResults.extraction_method === 'glm_custom_query') {
        a.download = type === 'all' ? 'OCR_Results.zip' : 'glm_query_result.txt';
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

  useEffect(() => {
    return () => {
      if (simPollRef.current) clearInterval(simPollRef.current);
    };
  }, []);

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
                        <p className="text-xs text-gray-500">Cloud-based Table Extraction</p>
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
                        <span className="text-sm font-medium text-gray-900">LLMWhisperer</span>
                        <p className="text-xs text-gray-500">Text extraction with layout preservation (Unstract)</p>
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
                        <span className="text-sm font-medium text-gray-900">AWS Textract (Custom Queries)</span>
                        <p className="text-xs text-gray-500">Queries - extract specific data</p>
                      </div>
                    </label>
                    
                    <label className="flex items-start cursor-pointer">
                      <input
                        type="radio"
                        name="extractionMethod"
                        value="searchable_pdf"
                        checked={extractionMethod === 'searchable_pdf'}
                        onChange={(e) => setExtractionMethod(e.target.value)}
                        className="h-4 w-4 mt-0.5 text-primary-600 border-gray-300 focus:ring-primary-500"
                      />
                      <div className="ml-3">
                        <span className="text-sm font-medium text-gray-900">Create Searchable PDF (AWS Textract)</span>
                        <p className="text-xs text-gray-500">Convert scanned PDF to searchable PDF using AWS</p>
                      </div>
                    </label>
                    
                    <label className="flex items-start cursor-pointer">
                      <input
                        type="radio"
                        name="extractionMethod"
                        value="ocrmypdf"
                        checked={extractionMethod === 'ocrmypdf'}
                        onChange={(e) => setExtractionMethod(e.target.value)}
                        className="h-4 w-4 mt-0.5 text-primary-600 border-gray-300 focus:ring-primary-500"
                      />
                      <div className="ml-3">
                        <span className="text-sm font-medium text-gray-900">Create Searchable PDF (OCRmyPDF)</span>
                        <p className="text-xs text-gray-500">Fast local conversion using Tesseract (free)</p>
                      </div>
                    </label>
                    
                    <label className="flex items-start cursor-pointer">
                      <input
                        type="radio"
                        name="extractionMethod"
                        value="convertapi_ocr"
                        checked={extractionMethod === 'convertapi_ocr'}
                        onChange={(e) => setExtractionMethod(e.target.value)}
                        className="h-4 w-4 mt-0.5 text-primary-600 border-gray-300 focus:ring-primary-500"
                      />
                      <div className="ml-3">
                        <span className="text-sm font-medium text-gray-900">Create Searchable PDF (ConvertAPI)</span>
                        <p className="text-xs text-gray-500">Convert scanned PDF to searchable PDF using ConvertAPI</p>
                      </div>
                    </label>
                    
                    <label className="flex items-start cursor-pointer">
                      <input
                        type="radio"
                        name="extractionMethod"
                        value="gpt4o_vision"
                        checked={extractionMethod === 'gpt4o_vision'}
                        onChange={(e) => setExtractionMethod(e.target.value)}
                        className="h-4 w-4 mt-0.5 text-primary-600 border-gray-300 focus:ring-primary-500"
                      />
                      <div className="ml-3">
                        <span className="text-sm font-medium text-gray-900">GPT-4o Vision</span>
                        <p className="text-xs text-gray-500">AI-powered query extraction using GPT-4o vision</p>
                      </div>
                    </label>
                    
                    <label className="flex items-start cursor-pointer">
                      <input
                        type="radio"
                        name="extractionMethod"
                        value="gpt4o_hybrid"
                        checked={extractionMethod === 'gpt4o_hybrid'}
                        onChange={(e) => setExtractionMethod(e.target.value)}
                        className="h-4 w-4 mt-0.5 text-primary-600 border-gray-300 focus:ring-primary-500"
                      />
                      <div className="ml-3">
                        <span className="text-sm font-medium text-gray-900">GPT-4o (Multimodal)</span>
                        <p className="text-xs text-gray-500">GPT-4o with both PDF images and LLMWhisperer text</p>
                      </div>
                    </label>
                    
                    <label className="flex items-start cursor-pointer">
                      <input
                        type="radio"
                        name="extractionMethod"
                        value="abaqus_fem"
                        checked={extractionMethod === 'abaqus_fem'}
                        onChange={(e) => setExtractionMethod(e.target.value)}
                        className="h-4 w-4 mt-0.5 text-primary-600 border-gray-300 focus:ring-primary-500"
                      />
                      <div className="ml-3">
                        <span className="text-sm font-medium text-gray-900">ABAQUS FEM Generator</span>
                        <p className="text-xs text-gray-500">Extract dimensions & stress-strain, generate .inp file</p>
                      </div>
                    </label>
                    
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
                        <p className="text-xs text-gray-500">AI-powered table extraction using GLM vision model (CSV output)</p>
                      </div>
                    </label>
                    
                    <label className="flex items-start cursor-pointer">
                      <input
                        type="radio"
                        name="extractionMethod"
                        value="glm_abaqus_generator"
                        checked={extractionMethod === 'glm_abaqus_generator'}
                        onChange={(e) => setExtractionMethod(e.target.value)}
                        className="h-4 w-4 mt-0.5 text-primary-600 border-gray-300 focus:ring-primary-500"
                      />
                      <div className="ml-3">
                        <span className="text-sm font-medium text-gray-900">GLM ABAQUS Generator (Serial Number)</span>
                        <p className="text-xs text-gray-500">Extract stress-strain data & dimensions by serial number, generate .inp file</p>
                      </div>
                    </label>
                    
                    <label className="flex items-start cursor-pointer">
                      <input
                        type="radio"
                        name="extractionMethod"
                        value="glm_custom_query"
                        checked={extractionMethod === 'glm_custom_query'}
                        onChange={(e) => setExtractionMethod(e.target.value)}
                        className="h-4 w-4 mt-0.5 text-primary-600 border-gray-300 focus:ring-primary-500"
                      />
                      <div className="ml-3">
                        <span className="text-sm font-medium text-gray-900">GLM Custom Query Extraction</span>
                        <p className="text-xs text-gray-500">Extract specific data using custom queries with GLM-4.5V vision AI</p>
                      </div>
                    </label>
                  </div>
                </div>
                
                {/* Serial Number Input - Show for ABAQUS FEM or GLM ABAQUS */}
                {(extractionMethod === 'abaqus_fem' || extractionMethod === 'glm_abaqus_generator') && (
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Serial Number *
                      </label>
                      <input
                        type="text"
                        value={serialNumber}
                        onChange={(e) => setSerialNumber(e.target.value)}
                        placeholder="Enter specimen serial number..."
                        className="input-field w-full"
                      />
                      <p className="text-xs text-gray-500 mt-1">
                        The serial number will be used to identify dimensions and stress-strain data in the PDF
                      </p>
                    </div>
                  </div>
                )}
                
                {/* Query/Prompt Input - Show for Unstract, Textract, GPT-4o Vision, GPT-4o Hybrid, GLM Table Extraction, or GLM Custom Query */}
                {(extractionMethod === 'unstract' || extractionMethod === 'direct_llm' || extractionMethod === 'gpt4o_vision' || extractionMethod === 'gpt4o_hybrid' || extractionMethod === 'glm_table_extraction' || extractionMethod === 'glm_custom_query') && (
                  <div className="space-y-4">
                    {/* Model Selection - Only for Unstract */}
                    {extractionMethod === 'unstract' && (
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
                    )}
                    
                    {/* Custom Query/Prompt */}
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        {extractionMethod === 'direct_llm' ? 'Custom Queries' : 'Custom Extraction Prompt'}
                      </label>
                      <textarea
                        value={customPrompts}
                        onChange={(e) => setCustomPrompts(e.target.value)}
                        className="input-field w-full h-32 resize-none"
                        placeholder={extractionMethod === 'direct_llm' 
                          ? "Enter questions to extract from the document (one per line):\n\nExamples:\n- What is the invoice number?\n- What is the total amount?\n- Who is the customer?\n- What is the due date?"
                          : "Enter your custom extraction instructions here...\n\nExample:\nExtract all invoice data including customer details, line items, and totals. Format as CSV with proper headers."
                        }
                      />
                      <p className="mt-1 text-xs text-gray-500">
                        {extractionMethod === 'direct_llm'
                          ? 'AWS Textract will answer these specific questions from your document'
                          : extractionMethod === 'glm_table_extraction'
                          ? 'Leave empty for default table extraction, or provide custom instructions for specialized extraction'
                          : 'Specify exactly what data you want to extract and how to format it'
                        }
                      </p>
                    </div>
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
                    
                    {/* GPT-4o Vision Results Display (Fast) */}
                    {processedResults.extraction_method === 'gpt4o_vision' && processedResults.status !== 'error' && (
                      <div className="space-y-4">
                        <div className="border rounded-lg p-4 bg-gradient-to-r from-blue-50 to-cyan-50 border-blue-200">
                          <h4 className="text-sm font-semibold mb-2 text-blue-900 flex items-center gap-2">
                            ⚡ GPT-4o Vision Extraction Results
                            <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">Fast Mode</span>
                          </h4>
                          
                          {/* Download button */}
                          <button
                            onClick={() => handleDownload('pdf')}
                            className="mt-2 w-full text-sm px-4 py-2 rounded transition-colors flex items-center justify-center bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white"
                          >
                            <Download className="h-4 w-4 mr-2" />
                            Download Results (.txt)
                          </button>
                          {/* Run Simulation Button */}
                          <button
                            onClick={() => handleRunSimulation(processedResults.taskId)}
                            disabled={simRunning}
                            className="mt-3 w-full text-sm px-4 py-2 rounded transition-colors flex items-center justify-center bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-700 hover:to-orange-700 text-white"
                          >
                            <Play className="h-4 w-4 mr-2" />
                            {simRunning ? 'Simulation Running...' : 'Run Abaqus Simulation'}
                          </button>

                          {/* Simulation Status & Log */}
                          {simStatus && (
                            <div className="mt-3 text-center text-xs">
                              <span className="inline-block px-2 py-1 rounded-full bg-gray-100 text-gray-700">
                                Simulation: {simStatus}
                              </span>
                            </div>
                          )}

                          {simLog !== '' && (
                            <div className="mt-3 bg-black text-white rounded p-3 text-xs font-mono overflow-auto max-h-48">
                              <pre className="whitespace-pre-wrap">{simLog}</pre>
                            </div>
                          )}
                          
                          {/* Result Files Download Section */}
                          {simStatus === 'completed' && outputFiles && Object.keys(outputFiles).length > 0 && (
                            <div className="mt-4 border-t pt-3">
                              <h6 className="text-xs font-semibold mb-2 text-gray-700">
                                📊 Download Simulation Results
                              </h6>
                              <div className="grid grid-cols-2 gap-2">
                                {outputFiles.dat && (
                                  <button
                                    onClick={() => handleDownloadResultFile('dat')}
                                    className="text-xs px-3 py-2 rounded transition-colors flex items-center justify-center bg-blue-600 hover:bg-blue-700 text-white"
                                  >
                                    <Download className="h-3 w-3 mr-1" />
                                    .dat
                                  </button>
                                )}
                                {outputFiles.msg && (
                                  <button
                                    onClick={() => handleDownloadResultFile('msg')}
                                    className="text-xs px-3 py-2 rounded transition-colors flex items-center justify-center bg-indigo-600 hover:bg-indigo-700 text-white"
                                  >
                                    <Download className="h-3 w-3 mr-1" />
                                    .msg
                                  </button>
                                )}
                                {outputFiles.odb && (
                                  <button
                                    onClick={() => handleDownloadResultFile('odb')}
                                    className="text-xs px-3 py-2 rounded transition-colors flex items-center justify-center bg-purple-600 hover:bg-purple-700 text-white"
                                  >
                                    <Download className="h-3 w-3 mr-1" />
                                    .odb
                                  </button>
                                )}
                                {outputFiles.sta && (
                                  <button
                                    onClick={() => handleDownloadResultFile('sta')}
                                    className="text-xs px-3 py-2 rounded transition-colors flex items-center justify-center bg-teal-600 hover:bg-teal-700 text-white"
                                  >
                                    <Download className="h-3 w-3 mr-1" />
                                    .sta
                                  </button>
                                )}
                              </div>
                            </div>
                          )}
                          
                          {/* Processing info */}
                          {processedResults.pages_processed && (
                            <div className="mt-3 text-xs text-blue-700">
                              📄 Processed {processedResults.pages_processed} pages with GPT-4o Vision
                            </div>
                          )}
                        </div>
                        
                        {/* GPT-4o Analysis */}
                        {processedResults.gpt4o_response && (
                          <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                            <h5 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
                              <span className="text-blue-600">🎯</span> GPT-4o Vision Analysis
                            </h5>
                            <div className="bg-gray-50 rounded p-3">
                              <pre className="text-xs text-gray-800 whitespace-pre-wrap font-mono">
                                {processedResults.gpt4o_response}
                              </pre>
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                    
                    {/* GPT-4o Hybrid Results Display */}
                    {processedResults.extraction_method === 'gpt4o_hybrid' && processedResults.status !== 'error' && (
                      <div className="space-y-4">
                        <div className="border rounded-lg p-4 bg-gradient-to-r from-purple-50 to-blue-50 border-purple-200">
                          <h4 className="text-sm font-semibold mb-2 text-purple-900">
                             GPT-4o Hybrid Extraction Results
                          </h4>
                          
                          {/* Download button */}
                          <button
                            onClick={() => handleDownload('pdf')}
                            className="mt-2 w-full text-sm px-4 py-2 rounded transition-colors flex items-center justify-center bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700 text-white"
                          >
                            <Download className="h-4 w-4 mr-2" />
                            Download Full Results (.txt)
                          </button>
                          
                          {/* Processing info */}
                          {processedResults.pages_processed && (
                            <div className="mt-3 text-xs text-purple-700">
                              📄 Processed {processedResults.pages_processed} pages with multimodal analysis
                            </div>
                          )}
                        </div>
                        
                        {/* GPT-4o Analysis */}
                        {processedResults.gpt4o_response && (
                          <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                            <h5 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
                              <span className="text-purple-600">🎯</span> GPT-4o Analysis
                            </h5>
                            <div className="bg-gray-50 rounded p-3">
                              <pre className="text-xs text-gray-800 whitespace-pre-wrap font-mono">
                                {processedResults.gpt4o_response}
                              </pre>
                            </div>
                          </div>
                        )}
                        
                        {/* LLMWhisperer Extracted Text (preview) */}
                        {processedResults.llmwhisperer_text && (
                          <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                            <h5 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
                              <span className="text-green-600">📝</span> LLMWhisperer Text (Preview)
                            </h5>
                            <div className="bg-gray-50 rounded p-3">
                              <pre className="text-xs text-gray-700 whitespace-pre-wrap font-mono">
                                {processedResults.llmwhisperer_text}
                              </pre>
                            </div>
                            <p className="text-xs text-gray-500 mt-2">
                               Download the full file to see complete LLMWhisperer extracted text
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                    
                    {/* GLM-4.5V Table Extraction Results Display */}
                    {processedResults.extraction_method === 'glm_table_extraction' && processedResults.status !== 'error' && (
                      <div className="space-y-4">
                        <div className="border rounded-lg p-4 bg-gradient-to-r from-teal-50 to-cyan-50 border-teal-200">
                          <h4 className="text-sm font-semibold mb-2 text-teal-900 flex items-center gap-2">
                            📊 GLM-4.5V Table Extraction Complete
                          </h4>
                          
                          {/* Download CSV button */}
                          <button
                            onClick={async () => {
                              try {
                                const response = await ocrService.downloadProcessedFile(processedResults.taskId);
                                const blob = new Blob([response.data], { type: 'text/csv' });
                                const url = window.URL.createObjectURL(blob);
                                const a = document.createElement('a');
                                a.href = url;
                                a.download = processedResults.output_filename || 'extracted_tables.csv';
                                document.body.appendChild(a);
                                a.click();
                                window.URL.revokeObjectURL(url);
                                document.body.removeChild(a);
                                toast.success('CSV file downloaded!');
                              } catch (error) {
                                toast.error('Failed to download CSV file');
                              }
                            }}
                            className="mt-2 w-full text-sm px-4 py-2 rounded transition-colors flex items-center justify-center bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-700 hover:to-cyan-700 text-white"
                          >
                            <Download className="h-4 w-4 mr-2" />
                            Download Extracted Tables (CSV)
                          </button>
                          
                          {/* Processing info */}
                          {processedResults.pages_processed && (
                            <div className="mt-3 text-xs text-teal-700">
                              📄 Processed {processedResults.pages_processed} pages with GLM-4.5V vision model
                            </div>
                          )}
                          
                          {/* Token usage */}
                          {processedResults.token_usage && (
                            <div className="mt-2 text-xs text-teal-600">
                              🔤 Tokens: {processedResults.token_usage.prompt_tokens || 0} input / {processedResults.token_usage.completion_tokens || 0} output / {processedResults.token_usage.total_tokens || 0} total
                            </div>
                          )}
                        </div>
                        
                        {/* Extracted Content Preview */}
                        {processedResults.extracted_content && (
                          <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                            <h5 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
                              <span className="text-teal-600">📋</span> Extracted Tables Preview (First 500 chars)
                            </h5>
                            <div className="bg-gray-50 rounded p-3">
                              <pre className="text-xs text-gray-800 whitespace-pre-wrap font-mono">
                                {typeof processedResults.extracted_content === 'string' 
                                  ? processedResults.extracted_content.substring(0, 500) + (processedResults.extracted_content.length > 500 ? '...' : '')
                                  : JSON.stringify(processedResults.extracted_content, null, 2).substring(0, 500) + '...'
                                }
                              </pre>
                            </div>
                            <p className="text-xs text-gray-500 mt-2">
                              ℹ️ Download the CSV file to see complete extracted tables
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                    
                    {/* GLM Custom Query Results Display */}
                    {processedResults.extraction_method === 'glm_custom_query' && processedResults.status !== 'error' && (
                      <div className="space-y-4">
                        <div className="border rounded-lg p-4 bg-gradient-to-r from-green-50 to-emerald-50 border-green-200">
                          <h4 className="text-sm font-semibold mb-2 text-green-900 flex items-center gap-2">
                            🔍 GLM-4.5V Custom Query Extraction Complete
                          </h4>
                          
                          {/* Display the query */}
                          {processedResults.result && processedResults.result.query && (
                            <div className="mt-3 bg-white border border-green-200 rounded p-3">
                              <p className="text-xs font-semibold text-gray-700 mb-1">📝 Your Query:</p>
                              <p className="text-xs text-gray-800 italic">"{processedResults.result.query}"</p>
                            </div>
                          )}
                          
                          {/* Download button */}
                          <button
                            onClick={() => handleDownload('pdf')}
                            className="mt-3 w-full text-sm px-4 py-2 rounded transition-colors flex items-center justify-center bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 text-white"
                          >
                            <Download className="h-4 w-4 mr-2" />
                            Download Results (.txt)
                          </button>
                        </div>
                        
                        {/* Extracted Text Display */}
                        {processedResults.result && processedResults.result.extracted_text && (
                          <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                            <h5 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
                              <span className="text-green-600">💬</span> Extracted Information
                            </h5>
                            <div className="bg-gray-50 rounded p-4 max-h-96 overflow-y-auto">
                              <pre className="text-sm text-gray-800 whitespace-pre-wrap font-sans leading-relaxed">
                                {processedResults.result.extracted_text}
                              </pre>
                            </div>
                            <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
                              <span>✨ Powered by GLM-4.5V Vision AI</span>
                              <span>•</span>
                              <span>📄 {processedResults.result.extracted_text.length} characters</span>
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                    
                    {/* GLM ABAQUS Generator Results Display */}
                    {processedResults.extraction_method === 'glm_abaqus_generator' && processedResults.status !== 'error' && (
                      <div className="space-y-4">
                        <div className="border rounded-lg p-4 bg-gradient-to-r from-purple-50 to-indigo-50 border-purple-200">
                          <h4 className="text-sm font-semibold mb-2 text-purple-900 flex items-center gap-2">
                            🔧 GLM ABAQUS Generator Complete
                          </h4>
                          
                          {/* Extracted Dimensions */}
                          {(processedResults.length || processedResults.diameter) && (
                            <div className="mt-3 grid grid-cols-2 gap-3">
                              {processedResults.length && (
                                <div className="bg-white rounded p-2 border border-purple-200">
                                  <div className="text-xs text-gray-600">Length</div>
                                  <div className="text-sm font-semibold text-purple-900">{processedResults.length} mm</div>
                                  <div className="text-xs text-purple-600">Scale: {processedResults.scale_factor_length?.toFixed(4)}</div>
                                </div>
                              )}
                              {processedResults.diameter && (
                                <div className="bg-white rounded p-2 border border-purple-200">
                                  <div className="text-xs text-gray-600">Diameter</div>
                                  <div className="text-sm font-semibold text-purple-900">{processedResults.diameter} mm</div>
                                  <div className="text-xs text-purple-600">Scale: {processedResults.scale_factor_diameter?.toFixed(4)}</div>
                                </div>
                              )}
                            </div>
                          )}
                          
                          {/* Download Buttons */}
                          <div className="mt-4 space-y-2">
                            <button
                              onClick={async () => {
                                try {
                                  const response = await ocrService.downloadProcessedFile(processedResults.taskId);
                                  const blob = new Blob([response.data], { type: 'application/octet-stream' });
                                  const url = window.URL.createObjectURL(blob);
                                  const a = document.createElement('a');
                                  a.href = url;
                                  a.download = processedResults.output_file || 'Compression_modified.inp';
                                  document.body.appendChild(a);
                                  a.click();
                                  window.URL.revokeObjectURL(url);
                                  document.body.removeChild(a);
                                  toast.success('ABAQUS input file downloaded!');
                                } catch (error) {
                                  toast.error('Failed to download ABAQUS file');
                                }
                              }}
                              className="w-full text-sm px-4 py-2 rounded transition-colors flex items-center justify-center bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700 text-white"
                            >
                              <Download className="h-4 w-4 mr-2" />
                              Download ABAQUS Input File (.inp)
                            </button>
                            
                            {processedResults.csv_file && (
                              <button
                                onClick={async () => {
                                  try {
                                    const response = await ocrService.downloadCsvFile(processedResults.taskId);
                                    const blob = new Blob([response.data], { type: 'text/csv' });
                                    const url = window.URL.createObjectURL(blob);
                                    const a = document.createElement('a');
                                    a.href = url;
                                    a.download = processedResults.csv_file;
                                    document.body.appendChild(a);
                                    a.click();
                                    window.URL.revokeObjectURL(url);
                                    document.body.removeChild(a);
                                    toast.success('Stress-strain CSV downloaded!');
                                  } catch (error) {
                                    toast.error('Failed to download CSV file');
                                  }
                                }}
                                className="w-full text-sm px-4 py-2 rounded transition-colors flex items-center justify-center bg-white border-2 border-purple-600 text-purple-600 hover:bg-purple-50"
                              >
                                <Download className="h-4 w-4 mr-2" />
                                Download Stress-Strain Data (CSV)
                              </button>
                            )}
                            
                            <button
                              onClick={() => handleRunSimulation(processedResults.taskId)}
                              disabled={simRunning}
                              className={`w-full text-sm px-4 py-2 rounded transition-colors flex items-center justify-center ${
                                simRunning 
                                  ? 'bg-gray-400 cursor-not-allowed' 
                                  : 'bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700'
                              } text-white`}
                            >
                              {simRunning ? (
                                <>
                                  <svg className="animate-spin h-4 w-4 mr-2" viewBox="0 0 24 24">
                                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                                  </svg>
                                  Running Simulation...
                                </>
                              ) : (
                                <>
                                  <span className="mr-2">▶️</span>
                                  Run ABAQUS Simulation
                                </>
                              )}
                            </button>
                          </div>
                          
                          {processedResults.serial_number && (
                            <div className="mt-3 text-xs text-purple-700">
                              📝 Serial Number: {processedResults.serial_number}
                            </div>
                          )}
                          
                          {/* Simulation Output */}
                          {(simLog || simStatus) && (
                            <div className="mt-4 border-t pt-4">
                              <h5 className="text-sm font-semibold mb-2 flex items-center gap-2">
                                <span className="text-green-600">🖥️</span>
                                ABAQUS Simulation Output
                                {simStatus === 'running' && (
                                  <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full animate-pulse">
                                    Running...
                                  </span>
                                )}
                                {simStatus === 'completed' && (
                                  <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
                                    ✓ Completed
                                  </span>
                                )}
                                {simStatus === 'error' && (
                                  <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full">
                                    ✗ Error
                                  </span>
                                )}
                              </h5>
                              <div className="bg-gray-900 text-green-400 p-3 rounded font-mono text-xs max-h-96 overflow-y-auto">
                                <pre className="whitespace-pre-wrap">{simLog || 'Waiting for output...'}</pre>
                              </div>
                              
                              {/* Result Files Download Section */}
                              {simStatus === 'completed' && outputFiles && Object.keys(outputFiles).length > 0 && (
                                <div className="mt-4 border-t pt-4">
                                  <h5 className="text-sm font-semibold mb-3 flex items-center gap-2">
                                    <span className="text-emerald-600">📊</span>
                                    Download Simulation Results
                                  </h5>
                                  <div className="grid grid-cols-2 gap-3">
                                    {outputFiles.dat && (
                                      <button
                                        onClick={() => handleDownloadResultFile('dat')}
                                        className="text-sm px-4 py-2.5 rounded transition-colors flex items-center justify-center bg-blue-600 hover:bg-blue-700 text-white shadow-sm"
                                      >
                                        <Download className="h-4 w-4 mr-2" />
                                        Data File (.dat)
                                      </button>
                                    )}
                                    {outputFiles.msg && (
                                      <button
                                        onClick={() => handleDownloadResultFile('msg')}
                                        className="text-sm px-4 py-2.5 rounded transition-colors flex items-center justify-center bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm"
                                      >
                                        <Download className="h-4 w-4 mr-2" />
                                        Messages (.msg)
                                      </button>
                                    )}
                                    {outputFiles.odb && (
                                      <button
                                        onClick={() => handleDownloadResultFile('odb')}
                                        className="text-sm px-4 py-2.5 rounded transition-colors flex items-center justify-center bg-purple-600 hover:bg-purple-700 text-white shadow-sm"
                                      >
                                        <Download className="h-4 w-4 mr-2" />
                                        Results DB (.odb)
                                      </button>
                                    )}
                                    {outputFiles.sta && (
                                      <button
                                        onClick={() => handleDownloadResultFile('sta')}
                                        className="text-sm px-4 py-2.5 rounded transition-colors flex items-center justify-center bg-teal-600 hover:bg-teal-700 text-white shadow-sm"
                                      >
                                        <Download className="h-4 w-4 mr-2" />
                                        Status (.sta)
                                      </button>
                                    )}
                                  </div>
                                  <p className="text-xs text-gray-500 mt-3">
                                    💡 <strong>Tip:</strong> The .dat file contains numerical results. The .odb file requires ABAQUS Viewer.
                                  </p>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                    
                    {/* ABAQUS FEM Results Display */}
                    {processedResults.extraction_method === 'abaqus_fem' && processedResults.status !== 'error' && (
                      <div className="space-y-4">
                        <div className="border rounded-lg p-4 bg-gradient-to-r from-emerald-50 to-teal-50 border-emerald-200">
                          <h4 className="text-sm font-semibold mb-2 text-emerald-900 flex items-center gap-2">
                            🔬 ABAQUS FEM Generation Complete
                            <span className="text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full">
                              Serial: {processedResults.extracted_data?.serial_number}
                            </span>
                          </h4>
                          
                          {/* Download .inp file button */}
                          <button
                            onClick={async () => {
                              try {
                                const response = await ocrService.downloadInpFile(processedResults.taskId);
                                const blob = new Blob([response.data], { type: 'text/plain' });
                                const url = window.URL.createObjectURL(blob);
                                const a = document.createElement('a');
                                a.href = url;
                                a.download = processedResults.output_filename || 'modified.inp';
                                document.body.appendChild(a);
                                a.click();
                                window.URL.revokeObjectURL(url);
                                document.body.removeChild(a);
                                toast.success('ABAQUS .inp file downloaded!');
                              } catch (error) {
                                toast.error('Failed to download .inp file');
                              }
                            }}
                            className="mt-2 w-full text-sm px-4 py-2 rounded transition-colors flex items-center justify-center bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 text-white"
                          >
                            <Download className="h-4 w-4 mr-2" />
                            Download ABAQUS .inp File
                          </button>
                        </div>
                        
                        {/* Extracted Dimensions */}
                        {processedResults.extracted_data?.dimensions && (
                          <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                            <h5 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
                              <span className="text-emerald-600">📏</span> Extracted Dimensions
                            </h5>
                            <div className="grid grid-cols-3 gap-4">
                              {Object.entries(processedResults.extracted_data.dimensions).map(([key, value]) => (
                                <div key={key} className="bg-gray-50 rounded p-3">
                                  <p className="text-xs text-gray-500 uppercase mb-1">{key}</p>
                                  <p className="text-sm font-semibold text-gray-900">
                                    {value !== null ? `${value} mm` : 'N/A'}
                                  </p>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                        
                        {/* Extracted Stress-Strain Data */}
                        {processedResults.extracted_data?.stress_strain && processedResults.extracted_data.stress_strain.length > 0 && (
                          <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                            <h5 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
                              <span className="text-emerald-600"></span> Stress-Strain Data ({processedResults.extracted_data.stress_strain.length} points)
                            </h5>
                            <div className="overflow-x-auto">
                              <table className="min-w-full divide-y divide-gray-200">
                                <thead className="bg-gray-50">
                                  <tr>
                                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Stress</th>
                                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Strain</th>
                                  </tr>
                                </thead>
                                <tbody className="bg-white divide-y divide-gray-200">
                                  {processedResults.extracted_data.stress_strain.slice(0, 10).map((point, idx) => (
                                    <tr key={idx}>
                                      <td className="px-3 py-2 text-xs text-gray-900">{point.stress}</td>
                                      <td className="px-3 py-2 text-xs text-gray-900">{point.strain}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                              {processedResults.extracted_data.stress_strain.length > 10 && (
                                <p className="text-xs text-gray-500 mt-2 text-center">
                                  Showing first 10 of {processedResults.extracted_data.stress_strain.length} data points
                                </p>
                              )}
                            </div>
                          </div>
                        )}
                        
                        {/* No stress-strain data found */}
                        {(!processedResults.extracted_data?.stress_strain || processedResults.extracted_data.stress_strain.length === 0) && (
                          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                            <p className="text-xs text-yellow-800">
                              No stress-strain data was found in the PDF. Using default strain value for .inp generation.
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                    
                    {/* Unstract, Textract, Direct LLM & LLMWhisperer Success Results */}
                    {(processedResults.extraction_method === 'unstract' || processedResults.extraction_method === 'direct_llm' || processedResults.extraction_method === 'textract' || processedResults.extraction_method === 'llmwhisperer') && processedResults.unstract_data && processedResults.status !== 'error' && (
                      <div className="space-y-4">
                        <div className={`border rounded-lg p-4 ${
                          (processedResults.extraction_method === 'direct_llm' || processedResults.extraction_method === 'textract')
                            ? 'bg-purple-50 border-purple-200'
                            : processedResults.extraction_method === 'llmwhisperer'
                            ? 'bg-green-50 border-green-200' 
                            : 'bg-blue-50 border-blue-200'
                        }`}>
                          <h4 className={`text-sm font-semibold mb-2 ${
                            (processedResults.extraction_method === 'direct_llm' || processedResults.extraction_method === 'textract')
                              ? 'text-purple-900'
                              : processedResults.extraction_method === 'llmwhisperer'
                              ? 'text-green-900'
                              : 'text-blue-900'
                          }`}>
                            {(processedResults.extraction_method === 'direct_llm' || processedResults.extraction_method === 'textract')
                              ? '📊 AWS Textract Extraction Results'
                              : processedResults.extraction_method === 'llmwhisperer'
                              ? '🎯 LLMWhisperer Text Extraction Results' 
                              : 'Unstract AI Extraction Results'
                            }
                          </h4>
                          
                          {/* Download button for LLMWhisperer and Textract */}
                          {(processedResults.extraction_method === 'llmwhisperer' || processedResults.extraction_method === 'direct_llm' || processedResults.extraction_method === 'textract') && (
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
                                  // Determine if this is CSV format (only for Unstract, not LLMWhisperer)
                                  const isCSV = processedResults.extraction_method === 'unstract' && 
                                                typeof value === 'string' && (
                                                  value.includes(',') && value.split('\n').length > 1
                                                );
                                  
                                  // Parse CSV data if it's CSV format and Unstract method
                                  let tableData = null;
                                  if (isCSV) {
                                    tableData = parseCSV(value);
                                  }
                                  
                                  return (
                                    <div key={key} className="border-t border-gray-100 pt-3">
                                      <h6 className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-2">
                                         {key.replace(/_/g, ' ').toUpperCase()}
                                      </h6>
                                      
                                      {/* Render as table if CSV AND Unstract method, otherwise as text */}
                                      {isCSV && tableData ? (
                                        <div className="bg-white rounded border border-gray-200 overflow-auto max-h-96">
                                          <table className="min-w-full divide-y divide-gray-200">
                                            <thead className="bg-gray-50">
                                              <tr>
                                                {tableData.headers.map((header, idx) => (
                                                  <th
                                                    key={idx}
                                                    className="px-4 py-2 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-200 last:border-r-0"
                                                  >
                                                    {header}
                                                  </th>
                                                ))}
                                              </tr>
                                            </thead>
                                            <tbody className="bg-white divide-y divide-gray-200">
                                              {tableData.rows.map((row, rowIdx) => (
                                                <tr key={rowIdx} className="hover:bg-gray-50">
                                                  {row.map((cell, cellIdx) => (
                                                    <td
                                                      key={cellIdx}
                                                      className="px-4 py-2 text-xs text-gray-900 border-r border-gray-200 last:border-r-0 whitespace-nowrap"
                                                    >
                                                      {cell}
                                                    </td>
                                                  ))}
                                                </tr>
                                              ))}
                                            </tbody>
                                          </table>
                                        </div>
                                      ) : (
                                        <div className="bg-gray-50 rounded p-3 max-h-96 overflow-y-auto">
                                          <pre className="text-xs text-gray-800 whitespace-pre-wrap font-mono">
                                            {value}
                                          </pre>
                                        </div>
                                      )}
                                      
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

                    {/* Searchable PDF Results */}
                    {processedResults.extraction_method === 'searchable_pdf' && (
                      <>
                        {/* Summary */}
                        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                          <div className="flex items-center justify-center mb-2">
                            <CheckCircle className="h-6 w-6 text-green-600 mr-2" />
                            <h4 className="text-md font-semibold text-green-900">
                              Searchable PDF Created Successfully!
                            </h4>
                          </div>
                          <p className="text-sm text-green-800 text-center">
                            Your scanned PDF has been converted to a searchable PDF.
                            You can now search for text using Ctrl+F or Cmd+F in any PDF reader.
                          </p>
                          <div className="mt-3 p-3 bg-white border border-green-200 rounded">
                            <p className="text-xs text-gray-700 text-center">
                              ✨ The original formatting and appearance are preserved<br/>
                              🔍 Text layer added - you can now search and select text<br/>
                              📄 Compatible with all PDF readers
                            </p>
                          </div>
                        </div>

                        {/* Download Button */}
                        <div className="space-y-2">
                          <button
                            onClick={() => handleDownload('pdf')}
                            className="w-full bg-green-600 hover:bg-green-700 text-white font-medium py-3 px-4 rounded-lg transition-colors flex items-center justify-center"
                          >
                            <Download className="h-5 w-5 mr-2" />
                            Download Searchable PDF
                          </button>
                        </div>
                      </>
                    )}

                    {/* Local OCR Results */}
                    {processedResults.extraction_method !== 'unstract' && processedResults.extraction_method !== 'llmwhisperer' && processedResults.extraction_method !== 'direct_llm' && processedResults.extraction_method !== 'textract' && processedResults.extraction_method !== 'searchable_pdf' && (
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

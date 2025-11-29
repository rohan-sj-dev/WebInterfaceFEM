import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:5001/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/';
    }
    return Promise.reject(error);
  }
);

export const authService = {
  login: async (email, password) => {
    return await api.post('/login', { email, password });
  },

  register: async (email, password, fullName) => {
    return await api.post('/register', { email, password, fullName });
  },

  getProfile: async (token) => {
    return await api.get('/profile', {
      headers: { Authorization: `Bearer ${token}` }
    });
  }
};

// Named exports for backward compatibility
export const login = authService.login;
export const register = authService.register;
export const getCurrentUser = async () => {
  const token = localStorage.getItem('token');
  if (!token) throw new Error('No token found');
  return await authService.getProfile(token);
};

export const ocrService = {
  uploadFile: async (file, options) => {
    const formData = new FormData();
    formData.append('file', file);
    
    Object.keys(options).forEach(key => {
      formData.append(key, options[key]);
    });

    return await api.post('/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  },

  uploadFileUnstract: async (file, customPrompts = '', modelName = 'gpt-4-turbo') => {
    const formData = new FormData();
    formData.append('file', file);
    if (customPrompts) {
      formData.append('custom_prompts', customPrompts);
    }
    if (modelName) {
      formData.append('model_name', modelName);
    }

    return await api.post('/upload_unstract', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  },

  uploadFileDirectLLM: async (file, customPrompt = '', modelName = 'gpt-4o') => {
    const formData = new FormData();
    formData.append('file', file);
    if (customPrompt) {
      formData.append('custom_prompt', customPrompt);
    }
    if (modelName) {
      formData.append('model_name', modelName);
    }

    return await api.post('/upload_direct_llm', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  },

  uploadFileLLMWhisperer: async (file) => {
    const formData = new FormData();
    formData.append('file', file);

    return await api.post('/upload_llmwhisperer', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  },

  uploadFileSearchablePDF: async (file) => {
    const formData = new FormData();
    formData.append('file', file);

    return await api.post('/upload_searchable_pdf', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  },

  uploadFileGPT4oVision: async (file, customPrompts) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('custom_prompts', customPrompts);

    return await api.post('/upload_gpt4o_vision', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  },

  uploadFileGPT4oHybrid: async (file, customPrompts) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('custom_prompts', customPrompts);

    return await api.post('/upload_gpt4o_hybrid', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  },

  uploadFileAbaqusFEM: async (file, serialNumber) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('serial_number', serialNumber);

    return await api.post('/upload_abaqus_fem', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  },

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

  uploadFileGLMAbaqusGenerator: async (file, serialNumber) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('serialNumber', serialNumber);

    return await api.post('/upload_glm_abaqus_generator', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  },

  downloadInpFile: async (taskId) => {
    const response = await axios.get(`${API_BASE_URL}/download_inp/${taskId}`, {
      headers: {
        Authorization: `Bearer ${localStorage.getItem('token')}`,
      },
      responseType: 'blob',
    });
    return response;
  },

  downloadCsvFile: async (taskId) => {
    const response = await axios.get(`${API_BASE_URL}/download_csv/${taskId}`, {
      headers: {
        Authorization: `Bearer ${localStorage.getItem('token')}`,
      },
      responseType: 'blob',
    });
    return response;
  },

  runAbaqusSimulation: async (taskId) => {
    return await api.post(`/run_abaqus_simulation/${taskId}`);
  },

  getSimulationStatus: async (simTaskId) => {
    return await api.get(`/simulation_status/${simTaskId}`);
  },

  downloadResultFile: async (simTaskId, fileType) => {
    const response = await axios.get(`${API_BASE_URL}/download_result/${simTaskId}/${fileType}`, {
      headers: {
        Authorization: `Bearer ${localStorage.getItem('token')}`,
      },
      responseType: 'blob',
    });
    return response;
  },

  checkAbaqusAvailability: async () => {
    return await api.get('/system/abaqus-status');
  },

  getStatus: async (taskId) => {
    return await api.get(`/status/${taskId}`);
  },

  downloadFile: async (taskId) => {
    const response = await axios.get(`${API_BASE_URL}/download/${taskId}`, {
      headers: {
        Authorization: `Bearer ${localStorage.getItem('token')}`,
      },
      responseType: 'blob',
    });
    return response;
  },

  // Alias for downloadFile - used by GLM table extraction
  downloadProcessedFile: async (taskId) => {
    const response = await axios.get(`${API_BASE_URL}/download/${taskId}`, {
      headers: {
        Authorization: `Bearer ${localStorage.getItem('token')}`,
      },
      responseType: 'blob',
    });
    return response;
  },

  downloadAll: async (taskId) => {
    const response = await axios.get(`${API_BASE_URL}/download_all/${taskId}`, {
      headers: {
        Authorization: `Bearer ${localStorage.getItem('token')}`,
      },
      responseType: 'blob',
    });
    return response;
  },

  getUserJobs: async () => {
    return await api.get('/jobs');
  },

  testSystem: async () => {
    return await api.get('/test');
  },

  launchABAQUS: async (csvData) => {
    return await api.post('/launch_abaqus', { csv_data: csvData });
  }
};

export default api;

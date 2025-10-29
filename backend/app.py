from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import sqlite3
import uuid
import tempfile
import threading
import zipfile
import subprocess
from datetime import datetime, timedelta
import logging
import requests
import time

# UNSTRACT CONFIGURATION:
# Set the UNSTRACT_API_URL environment variable to your Unstract instance URL
# For Unstract on another system in the network: set UNSTRACT_API_URL=http://192.168.x.x/deployment/api/mock_org/test/
# (Replace 192.168.x.x with the actual IP address of the system running Unstract)
# For local Unstract: set UNSTRACT_API_URL=http://localhost/deployment/api/mock_org/test/
# For production: set UNSTRACT_API_URL=https://your-unstract-domain.com/deployment/api/your_org/your_deployment/
# Replace UNSTRACT_API_KEY below with your actual API key

# Default Unstract URL - New deployment with single pass extraction disabled
# This fixes the "highlight metadata missing or corrupted" error
UNSTRACT_DEFAULT_URL = 'https://us-central.unstract.com/deployment/api/org_XYP7vV7oXBLVNmLG/invoice-extract/'
UNSTRACT_DEFAULT_API_KEY = '50e45650-7179-465f-8226-5092f77ffadd'

# Optional: Separate workflow for custom Q&A (if you create one)
# If you have a Q&A workflow, uncomment and add the deployment ID:
# UNSTRACT_QA_URL = 'https://us-central.unstract.com/deployment/api/org_XYP7vV7oXBLVNmLG/YOUR_QA_WORKFLOW_ID/'
UNSTRACT_QA_URL = None  # Set to None to use the same workflow for both

# DIRECT LLM CONFIGURATION (Alternative to Unstract for custom prompts)
# Set your OpenAI API key here for direct GPT-4o calls
# Set via environment variable
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')  # For Claude (optional)

# LLMWHISPERER CONFIGURATION (Document to Text Conversion)
# LLMWhisperer is Unstract's OCR/document extraction API
LLMWHISPERER_API_URL = 'https://llmwhisperer-api.us-central.unstract.com/api/v2'
LLMWHISPERER_API_KEY = '_W3Zl_zJ223RYMmXg9X4CWYCfQ_EK9oM_-cobz1xaaM'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = 'dDaysadadREfj@38u983293*#(&#*u8w'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  

jwt = JWTManager(app)
CORS(app, origins=["http://localhost:3000"])
@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    print(f"JWT expired token error")
    return jsonify({'error': 'Token has expired'}), 401

@jwt.invalid_token_loader
def invalid_token_callback(error):
    print(f"JWT invalid token error: {error}")
    return jsonify({'error': 'Invalid token'}), 422

@jwt.unauthorized_loader
def missing_token_callback(error):
    print(f"JWT missing token error: {error}")
    return jsonify({'error': 'Authorization token is required'}), 401

@app.before_request
def log_request_info():
    print(f"=== REQUEST: {request.method} {request.path} ===")
    if request.path == '/api/upload':
        print(f"Content-Type: {request.content_type}")
        print(f"Content-Length: {request.content_length}")

UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
ALLOWED_EXTENSIONS = {'pdf'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def setup_ocr_environment():
    os.environ['TESSERACT_CMD'] = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    os.environ['PATH'] = r'C:\Program Files\gs\gs10.05.1\bin;' + os.environ.get('PATH', '')

setup_ocr_environment()

def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processing_jobs (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

processing_status = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_user_by_email(email):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, email, password_hash, full_name FROM users WHERE email = ?', (email,))
    user = cursor.fetchone()
    conn.close()
    return user

def create_user(email, password, full_name):
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        password_hash = generate_password_hash(password)
        cursor.execute(
            'INSERT INTO users (email, password_hash, full_name) VALUES (?, ?, ?)',
            (email, password_hash, full_name)
        )
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        return None

def process_pdf_with_ocr_and_camelot(input_path, output_path, options, task_id, user_id):
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Starting OCR processing...',
            'progress': 10,
            'user_id': user_id
        }
        
        import ocrmypdf

        processing_status[task_id]['message'] = 'Running OCR on PDF...'
        processing_status[task_id]['progress'] = 30
        
        ocr_options = {
            'language': options.get('language', 'eng'),
            'deskew': options.get('deskew', True),
            'optimize': int(options.get('optimize', 1)),
            'force_ocr': options.get('force_ocr', False),
            'progress_bar': False
        }
        
        if options.get('clean', False):
            try:
                import subprocess
                subprocess.run(['unpaper', '--version'], capture_output=True, timeout=5)
                ocr_options['clean'] = True
            except:
                logger.warning("Unpaper not available, skipping clean option")
        
        ocrmypdf.ocr(input_path, output_path, **ocr_options)
        
        processing_status[task_id]['message'] = 'OCR completed, extracting tables...'
        processing_status[task_id]['progress'] = 60

        tables_data = []
        tables_dir = None
        
        if options.get('extract_tables', True):
            try:
                import camelot

                tables_dir = os.path.join(OUTPUT_FOLDER, f"tables_{task_id}")
                os.makedirs(tables_dir, exist_ok=True)
                
                processing_status[task_id]['message'] = 'Extracting tables with Camelot...'
                processing_status[task_id]['progress'] = 80
                
                # Try lattice method first 
                try:
                    tables = camelot.read_pdf(
                        output_path, 
                        pages='all',
                        flavor='lattice',  # Better for bordered tables
                        table_areas=None,  # Auto-detect table areas
                        columns=None,      # Auto-detect columns
                        split_text=True,   # Split text that spans multiple lines
                        flag_size=True,    # Flag text size differences
                        strip_text='\n',   # Strip newlines
                        line_scale=60,     # Even more aggressive line detection
                        copy_text=['v', 'h'],  # Copy text for better detection
                        shift_text=['l', 't'],  # Shift text for better alignment
                        background_color='#ffffff',  # Assume white background
                        process_background=True  # Process background for better detection
                    )
                    
                    logger.info(f"Lattice method found {len(tables)} tables")
                    
                    # Try stream method as well for comprehensive detection
                    stream_tables = camelot.read_pdf(
                        output_path,
                        pages='all', 
                        flavor='stream',   # Better for tables without borders
                        table_areas=None,
                        columns=None,
                        row_tol=1,         # More strict row tolerance
                        column_tol=0,      # No column tolerance
                        edge_tol=100,      # Very aggressive edge detection
                        strip_text='\n'    # Strip newlines
                    )
                    
                    logger.info(f"Stream method found {len(stream_tables)} tables")
                    
                    # Combine all results
                    all_tables = list(tables) + list(stream_tables)
                    
                except Exception as lattice_error:
                    logger.warning(f"Lattice method failed: {lattice_error}, trying stream method only")
                    # Fallback to stream method only
                    try:
                        all_tables = camelot.read_pdf(
                            output_path,
                            pages='all',
                            flavor='stream',
                            table_areas=None,
                            columns=None,
                            row_tol=1,
                            column_tol=0,
                            edge_tol=100,
                            strip_text='\n'
                        )
                        logger.info(f"Stream fallback found {len(all_tables)} tables")
                    except Exception as stream_error:
                        logger.error(f"Both lattice and stream methods failed: {stream_error}")
                        all_tables = []
                
                processed_tables = []
                seen_tables = set()  
                
                for i, table in enumerate(all_tables):
                    # Get accuracy if available, default to reasonable value
                    accuracy = getattr(table, 'accuracy', 50.0)
                    
                    # More lenient accuracy threshold - accept even lower accuracy tables
                    if accuracy < 15:  # Only filter out extremely poor tables
                        logger.warning(f"Skipping table {i+1} due to very low accuracy: {accuracy}%")
                        continue
                    
                    # Check table dimensions - be very lenient
                    if len(table.df) < 1 or len(table.df.columns) < 1:
                        logger.warning(f"Skipping table {i+1} due to no data")
                        continue
                    
                    # Clean the dataframe
                    cleaned_df = table.df.dropna(how='all').dropna(axis=1, how='all')
                    
                    # Accept even single-column or single-row tables if they have content
                    if cleaned_df.empty:
                        continue
                    
                    # Simple duplicate detection based on content
                    content_hash = hash(str(cleaned_df.values.tolist()))
                    if content_hash in seen_tables:
                        logger.info(f"Skipping duplicate table {i+1}")
                        continue
                    seen_tables.add(content_hash)
                    
                    # Log table details for debugging
                    logger.info(f"Processing table {len(processed_tables)+1}: {len(cleaned_df)} rows, {len(cleaned_df.columns)} cols, accuracy: {accuracy}%")
                    
                    processed_tables.append((cleaned_df, accuracy))
                
                for idx, (cleaned_df, accuracy) in enumerate(processed_tables):
                    table_num = idx + 1
                    
                    # Save table as CSV
                    csv_filename = f'table_{table_num}.csv'
                    csv_path = os.path.join(tables_dir, csv_filename)
                    cleaned_df.to_csv(csv_path, index=False)
                    
                    # Save table as Excel
                    excel_filename = f'table_{table_num}.xlsx'
                    excel_path = os.path.join(tables_dir, excel_filename)
                    cleaned_df.to_excel(excel_path, index=False)
                    
                    tables_data.append({
                        'table_num': table_num,
                        'csv_file': csv_filename,
                        'excel_file': excel_filename,
                        'rows': len(cleaned_df),
                        'columns': len(cleaned_df.columns),
                        'accuracy': f"{accuracy:.1f}%" if isinstance(accuracy, (int, float)) else str(accuracy),
                        'extraction_method': 'camelot'
                    })
            except ImportError:
                logger.warning("Camelot not available, skipping table extraction")
        
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE processing_jobs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
            ('completed', task_id)
        )
        conn.commit()
        conn.close()
        
        processing_status[task_id] = {
            'status': 'completed',
            'message': f'Processing completed! Found {len(tables_data)} table(s).',
            'progress': 100,
            'output_file': os.path.basename(output_path),
            'tables': tables_data,
            'tables_dir': tables_dir,
            'user_id': user_id
        }
        
    except Exception as e:
        processing_status[task_id] = {
            'status': 'error',
            'message': f'Processing failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        logger.error(f"Processing failed: {e}")

def process_pdf_with_unstract(input_path, task_id, user_id, api_key=None, custom_prompts='', model_name='gpt-4-turbo'):
    """Process PDF using Unstract Cloud API with custom prompts and model selection"""
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Starting Unstract extraction...',
            'progress': 10,
            'user_id': user_id,
            'custom_prompts': custom_prompts,
            'model_name': model_name
        }
        
        # Get Unstract URL from environment or use configured default
        api_url = os.environ.get('UNSTRACT_API_URL', UNSTRACT_DEFAULT_URL)
        
        # If custom prompts are provided and we have a separate Q&A workflow, use it
        if custom_prompts and UNSTRACT_QA_URL:
            api_url = UNSTRACT_QA_URL
            logger.info(f"Using Unstract Q&A workflow for custom query")
        
        # Use provided API key or default
        if api_key is None:
            api_key = os.environ.get('UNSTRACT_API_KEY', UNSTRACT_DEFAULT_API_KEY)
        
        logger.info(f"Using Unstract Cloud API URL: {api_url}")
        logger.info(f"Custom prompts: {custom_prompts}")
        logger.info(f"Selected model: {model_name}")
        
        headers = {
            'Authorization': f'Bearer {api_key}'
        }
        
        # Model to LLM Profile ID mapping
        # TODO: Replace these with your actual LLM Profile IDs from Unstract Prompt Studio
        # Get these from: Prompt Studio -> Settings -> LLM Profiles -> Copy Profile ID
        MODEL_PROFILE_MAPPING = {
            'gpt-4-turbo': None,  # Will use default profile if None
            'azure-gpt-4o': None   # Replace with actual profile ID
        }
        
        # Prepare form data for Unstract API
        # Matches the Postman collection format exactly
        form_data = {
            'timeout': '300',
            'include_metadata': 'False',  # Reduce overhead by excluding metadata
            'include_metrics': 'False'    # Reduce overhead by excluding metrics
        }
        
        # Add LLM profile selection if specified
        # This allows user to choose which model runs (GPT-4 Turbo or Azure GPT-4o)
        llm_profile_id = MODEL_PROFILE_MAPPING.get(model_name)
        if llm_profile_id:
            form_data['llm_profile_id'] = llm_profile_id
            logger.info(f"Using LLM profile ID: {llm_profile_id} for model: {model_name}")
        else:
            logger.info(f"Using default LLM profile (model: {model_name})")
        
        # Custom prompts override the default invoice extraction
        # If user provides custom prompts, those take precedence over the single invoice output
        # The prompts must be valid JSON and can be accessed in Unstract templates via {{custom_data.key}}
        if custom_prompts:
            import json
            custom_data_obj = {
                "instructions": custom_prompts,
                "user_query": custom_prompts,
                "override_default": True  # Flag to indicate custom extraction
            }
            form_data['custom_data'] = json.dumps(custom_data_obj)
            logger.info(f"Custom prompts will override default invoice extraction")
            logger.info(f"Custom data: {form_data['custom_data']}")
        else:
            logger.info(f"Using default invoice extraction (no custom prompts provided)")
        
        processing_status[task_id]['message'] = 'Uploading file to Unstract Cloud...'
        processing_status[task_id]['progress'] = 30
        
        # Add timing to identify bottlenecks
        upload_start_time = time.time()
        
        # Upload file to Unstract - field name MUST be 'files' (plural)
        # Add SSL/TLS retry logic for connection errors
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                request_start = time.time()
                
                with open(input_path, 'rb') as f:
                    # Unstract API requires 'files' as the field name (not 'file')
                    files = {'files': (os.path.basename(input_path), f, 'application/pdf')}
                    
                    logger.info(f"Sending request to Unstract API (attempt {attempt + 1}/{max_retries}): {api_url}")
                    logger.info(f"Form data: {form_data}")
                    logger.info(f"File name: {os.path.basename(input_path)}")
                    
                    # Disable SSL verification as a fallback (only if needed)
                    # Note: This is less secure but helps with SSL certificate issues
                    response = requests.post(
                        api_url, 
                        headers=headers, 
                        data=form_data,
                        files=files, 
                        timeout=120,  # Increased timeout to 120 seconds
                        verify=True  # Keep SSL verification enabled by default
                    )
                    
                    request_end = time.time()
                    request_duration = request_end - request_start
                    
                    logger.info(f"Unstract response status: {response.status_code}")
                    logger.info(f"Request took {request_duration:.2f} seconds")
                    logger.info(f"Unstract response: {response.text[:500]}")  # Log first 500 chars
                    break  # Success, exit retry loop
                    
            except requests.exceptions.SSLError as e:
                logger.warning(f"SSL Error on attempt {attempt + 1}/{max_retries}: {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    # Last attempt failed, try without SSL verification
                    logger.warning("All SSL attempts failed, trying without SSL verification...")
                    try:
                        with open(input_path, 'rb') as f:
                            files = {'files': (os.path.basename(input_path), f, 'application/pdf')}
                            response = requests.post(
                                api_url, 
                                headers=headers, 
                                data=form_data,
                                files=files, 
                                timeout=120,
                                verify=False  # Disable SSL verification as last resort
                            )
                            logger.info(f"Request succeeded without SSL verification")
                            logger.info(f"Unstract response status: {response.status_code}")
                            logger.info(f"Unstract response: {response.text[:500]}")
                    except Exception as final_error:
                        raise Exception(f"Cannot connect to Unstract API at {api_url}. SSL connection failed even without verification. Error: {str(final_error)}")
                        
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Connection error on attempt {attempt + 1}/{max_retries}: {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise Exception(f"Cannot connect to Unstract API at {api_url}. Please verify: 1) Unstract is running, 2) Network/firewall allows HTTPS connections, 3) API URL is correct. Error: {str(e)}")
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on attempt {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise Exception("Unstract API request timed out after multiple attempts. Please check your network connection or try a smaller file.")
        
        if response.status_code != 200:
            error_msg = f"Unstract upload failed with status {response.status_code}: {response.text}"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        try:
            upload_response = response.json()
            logger.info(f"Upload response: {upload_response}")
        except Exception as e:
            logger.error(f"Failed to parse Unstract response as JSON: {response.text}")
            raise Exception(f"Invalid response from Unstract API: {str(e)}")
        
        # Unstract wraps response in 'message' field
        message = upload_response.get('message', upload_response)
        execution_status = message.get('execution_status')
        result = message.get('result')
        
        logger.info(f"Initial execution status: {execution_status}")
        
        # Check if processing failed immediately
        if execution_status == 'ERROR':
            logger.error(f"Unstract processing failed immediately")
            
            # Extract error details from result
            error_details = "Unknown error"
            if result and len(result) > 0:
                file_result = result[0]
                error_details = file_result.get('error', 'Unknown error')
                logger.error(f"Error details: {error_details}")
            
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE processing_jobs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
                ('error', task_id)
            )
            conn.commit()
            conn.close()
            
            processing_status[task_id] = {
                'status': 'error',
                'message': f'Unstract processing failed: {error_details}',
                'progress': 100,
                'extraction_method': 'unstract',
                'error': error_details,
                'unstract_data': result,
                'user_id': user_id
            }
            logger.error(f"Unstract processing failed for task {task_id}: {error_details}")
            return
        
        # Check if already completed (fast processing)
        if execution_status == 'COMPLETED' and result:
            upload_end_time = time.time()
            total_upload_time = upload_end_time - upload_start_time
            
            logger.info("Processing completed immediately!")
            logger.info(f"Total time from upload to completion: {total_upload_time:.2f} seconds")
            
            # Log Unstract's internal timing if available
            if result and len(result) > 0:
                metadata = result[0].get('metadata', {})
                unstract_elapsed = metadata.get('total_elapsed_time', 0)
                logger.info(f"Unstract internal processing time: {unstract_elapsed:.2f} seconds")
                logger.info(f"Network + overhead time: {(total_upload_time - unstract_elapsed):.2f} seconds")
            
            # Extract execution_id from result metadata if available
            execution_id = None
            if result and len(result) > 0:
                execution_id = result[0].get('metadata', {}).get('execution_id')
            
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE processing_jobs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
                ('completed', task_id)
            )
            conn.commit()
            conn.close()
            
            processing_status[task_id] = {
                'status': 'completed',
                'message': 'Unstract extraction completed!',
                'progress': 100,
                'extraction_method': 'unstract',
                'unstract_data': result,
                'execution_id': execution_id,
                'execution_status': execution_status,
                'user_id': user_id
            }
            logger.info(f"Unstract processing completed immediately for task {task_id}")
            return
        
        # Get execution_id for polling
        execution_id = message.get('execution_id')
        
        if not execution_id:
            logger.error(f"No execution_id in response: {upload_response}")
            raise Exception(f"No execution_id returned from Unstract. Response: {upload_response}")
        
        logger.info(f"Got execution_id: {execution_id}")
        processing_status[task_id]['message'] = 'Processing with Unstract...'
        processing_status[task_id]['progress'] = 60
        
        # Poll for results
        max_attempts = 60  # 5 minutes with 5-second intervals
        for attempt in range(max_attempts):
            time.sleep(5)
            
            get_url = f'{api_url}?execution_id={execution_id}&include_metadata=false'
            logger.info(f"Polling Unstract (attempt {attempt + 1}/{max_attempts}): {get_url}")
            
            try:
                get_response = requests.get(get_url, headers=headers, timeout=30)
                logger.info(f"Poll response status: {get_response.status_code}")
                
                if get_response.status_code == 200:
                    result_data = get_response.json()
                    logger.info(f"Poll response data: {str(result_data)[:500]}")
                    
                    # Unstract API response structure has 'message' wrapper
                    message = result_data.get('message', result_data)
                    execution_status = message.get('execution_status', '')
                    result = message.get('result')
                    
                    logger.info(f"Execution status: {execution_status}")
                    
                    # Check if processing is complete
                    if execution_status == 'COMPLETED' and result:
                        conn = sqlite3.connect('users.db')
                        cursor = conn.cursor()
                        cursor.execute(
                            'UPDATE processing_jobs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
                            ('completed', task_id)
                        )
                        conn.commit()
                        conn.close()
                        
                        processing_status[task_id] = {
                            'status': 'completed',
                            'message': 'Unstract extraction completed!',
                            'progress': 100,
                            'extraction_method': 'unstract',
                            'unstract_data': result,  # The actual result array
                            'execution_id': execution_id,
                            'execution_status': execution_status,
                            'user_id': user_id
                        }
                        logger.info(f"Unstract processing completed for task {task_id}")
                        return
                    elif execution_status == 'ERROR':
                        error_detail = message.get('error', 'Unknown error')
                        logger.error(f"Unstract processing failed: {error_detail}")
                        raise Exception(f"Unstract processing failed: {error_detail}")
                    elif execution_status in ['PENDING', 'EXECUTING']:
                        logger.info(f"Still processing... Status: {execution_status}")
                    else:
                        logger.info(f"Unknown status: {execution_status}, continuing to poll...")
                else:
                    logger.warning(f"Poll returned status {get_response.status_code}: {get_response.text[:200]}")
                        
            except requests.exceptions.RequestException as e:
                logger.warning(f"Poll request failed (attempt {attempt + 1}): {str(e)}")
                
            processing_status[task_id]['progress'] = 60 + (attempt / max_attempts * 35)
        
        # Timeout
        raise Exception("Unstract processing timeout")
        
    except Exception as e:
        processing_status[task_id] = {
            'status': 'error',
            'message': f'Unstract processing failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        logger.error(f"Unstract processing failed: {e}")

def process_pdf_with_direct_llm(input_path, task_id, user_id, custom_prompt='', model='gpt-4o', use_text_extraction=True):
    """
    Process PDF using direct LLM API calls (OpenAI GPT-4o or Anthropic Claude)
    This bypasses Unstract and allows true custom prompts
    
    Args:
        use_text_extraction: If True, first extract text with LLMWhisperer then send to LLM (faster, cheaper)
                            If False, convert PDF to images and use vision API (slower, more expensive)
    """
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Starting extraction...',
            'progress': 10,
            'user_id': user_id
        }
        
        extracted_text = None
        
        # Option 1: Use LLMWhisperer to extract text first (recommended)
        if use_text_extraction:
            try:
                processing_status[task_id]['message'] = 'Extracting text with LLMWhisperer...'
                processing_status[task_id]['progress'] = 20
                
                logger.info(f"Extracting text with LLMWhisperer for Direct LLM: {input_path}")
                
                # Read file as binary
                with open(input_path, 'rb') as f:
                    file_bytes = f.read()
                
                # Submit to LLMWhisperer
                headers = {
                    'unstract-key': LLMWHISPERER_API_KEY,
                    'Content-Type': 'application/octet-stream'
                }
                
                params = {
                    'mode': 'high_quality',
                    'output_mode': 'layout_preserving',
                    'page_seperator': '<<<PAGE_BREAK>>>',
                }
                
                response = requests.post(
                    f'{LLMWHISPERER_API_URL}/whisper',
                    headers=headers,
                    params=params,
                    data=file_bytes,
                    timeout=300
                )
                
                if response.status_code == 202:
                    result_data = response.json()
                    whisper_hash = result_data.get('whisper_hash')
                    
                    # Poll for completion
                    processing_status[task_id]['message'] = 'Processing document...'
                    processing_status[task_id]['progress'] = 40
                    
                    max_retries = 60
                    retry_count = 0
                    
                    while retry_count < max_retries:
                        time.sleep(5)
                        status_response = requests.get(
                            f'{LLMWHISPERER_API_URL}/whisper-status',
                            headers=headers,
                            params={'whisper_hash': whisper_hash},
                            timeout=30
                        )
                        
                        if status_response.status_code == 200:
                            status_data = status_response.json()
                            status = status_data.get('status')
                            
                            if status == 'processed':
                                # Retrieve text
                                retrieve_response = requests.get(
                                    f'{LLMWHISPERER_API_URL}/whisper-retrieve',
                                    headers=headers,
                                    params={'whisper_hash': whisper_hash, 'text_only': 'false'},
                                    timeout=60
                                )
                                
                                if retrieve_response.status_code == 200:
                                    result_data = retrieve_response.json()
                                    extracted_text = result_data.get('result_text', '')
                                    logger.info(f"LLMWhisperer extracted {len(extracted_text)} characters")
                                break
                            elif status in ['error', 'failed']:
                                logger.warning(f"LLMWhisperer failed, falling back to vision API")
                                break
                        
                        retry_count += 1
                    
            except Exception as e:
                logger.warning(f"LLMWhisperer extraction failed: {e}, falling back to vision API")
                extracted_text = None
        
        # Option 2: Fall back to vision API if text extraction failed or disabled
        if extracted_text:
            processing_status[task_id]['message'] = 'Analyzing extracted text with AI...'
            processing_status[task_id]['progress'] = 60
            
            # Prepare the prompt for text-based analysis
            if not custom_prompt:
                custom_prompt = """
First, analyze the text to determine the most appropriate headers for the tables.
Generate a descriptive h1 for the overall document, followed by a brief summary of the data it contains.
For each identified table, create an informative h2 title and a concise description of its contents.
Finally, output the markdown representation of each table.
Make sure to escape the markdown table properly, and make sure to include the caption and the dataframe.
including escaping all the newlines and quotes. Only return a markdown table in dataframe, nothing else.
"""
            
            # Process text with LLM
            if model.startswith('gpt-'):
                result = process_text_with_openai(extracted_text, custom_prompt, model)
            elif model.startswith('claude-'):
                result = process_text_with_anthropic(extracted_text, custom_prompt, model)
            else:
                raise Exception(f"Unsupported model: {model}")
                
        else:
            # Fall back to image-based processing
            processing_status[task_id]['message'] = 'Converting PDF to images...'
            processing_status[task_id]['progress'] = 30
            
            import base64
            import pdf2image
            from PIL import Image
            import io
            
            logger.info(f"Converting PDF to images: {input_path}")
            images = pdf2image.convert_from_path(input_path, dpi=200)
            
            processing_status[task_id]['message'] = 'Analyzing images with AI...'
            processing_status[task_id]['progress'] = 60
            
            if not custom_prompt:
                custom_prompt = """
First, analyze the image to determine the most appropriate headers for the tables.
Generate a descriptive h1 for the overall image, followed by a brief summary of the data it contains.
For each identified table, create an informative h2 title and a concise description of its contents.
Finally, output the markdown representation of each table.
Make sure to escape the markdown table properly, and make sure to include the caption and the dataframe.
including escaping all the newlines and quotes. Only return a markdown table in dataframe, nothing else.
"""
            
            if model.startswith('gpt-'):
                result = process_with_openai(images, custom_prompt, model)
            elif model.startswith('claude-'):
                result = process_with_anthropic(images, custom_prompt, model)
            else:
                raise Exception(f"Unsupported model: {model}")
        
        processing_status[task_id]['message'] = 'Extraction complete!'
        processing_status[task_id]['progress'] = 90
        
        # Save result to file (for download compatibility)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"llm_extracted_{timestamp}_{task_id[:8]}.txt"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"Direct LLM Extraction Results\n")
            f.write(f"Model: {model}\n")
            f.write(f"File: {os.path.basename(input_path)}\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
            f.write(result)
        
        logger.info(f"Saved LLM results to: {output_path}")
        
        # Update database
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE processing_jobs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
            ('completed', task_id)
        )
        conn.commit()
        conn.close()
        
        processing_status[task_id] = {
            'status': 'completed',
            'message': 'Direct LLM extraction completed!',
            'progress': 100,
            'extraction_method': 'direct_llm',
            'output_file': output_filename,  # Added for download compatibility
            'llm_data': [{
                'file': os.path.basename(input_path),
                'status': 'Success',
                'result': {
                    'output': {
                        'extracted_data': result
                    }
                }
            }],
            # Also add unstract_data for frontend compatibility
            'unstract_data': [{
                'file': os.path.basename(input_path),
                'status': 'Success',
                'result': {
                    'output': {
                        'Direct_LLM_Output': result
                    }
                }
            }],
            'user_id': user_id
        }
        logger.info(f"Direct LLM processing completed for task {task_id}")
        
    except Exception as e:
        processing_status[task_id] = {
            'status': 'error',
            'message': f'Direct LLM processing failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        logger.error(f"Direct LLM processing failed: {e}")

def process_with_openai(images, prompt, model='gpt-4o'):
    """Process images with OpenAI GPT-4o Vision API"""
    if not OPENAI_API_KEY:
        raise Exception("OpenAI API key not configured. Set OPENAI_API_KEY environment variable.")
    
    import base64
    import io
    
    # Prepare image data
    image_data = []
    for idx, img in enumerate(images):
        # Convert PIL Image to base64
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        image_data.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_str}",
                "detail": "high"  # High detail for better table extraction
            }
        })
    
    # Call OpenAI API
    headers = {
        'Authorization': f'Bearer {OPENAI_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an expert at extracting data from technical documents, specifications, and invoices. Extract data accurately and format it as requested."
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    *image_data
                ]
            }
        ],
        "max_tokens": 4096,
        "temperature": 0.1  # Low temperature for consistent extraction
    }
    
    response = requests.post(
        'https://api.openai.com/v1/chat/completions',
        headers=headers,
        json=payload,
        timeout=120
    )
    
    if response.status_code != 200:
        raise Exception(f"OpenAI API error: {response.status_code} - {response.text}")
    
    result = response.json()
    extracted_text = result['choices'][0]['message']['content']
    
    logger.info(f"OpenAI extraction complete. Tokens used: {result.get('usage', {})}")
    
    return extracted_text

def process_with_anthropic(images, prompt, model='claude-3-5-sonnet-20241022'):
    """Process images with Anthropic Claude 3.5 Sonnet API"""
    if not ANTHROPIC_API_KEY:
        raise Exception("Anthropic API key not configured. Set ANTHROPIC_API_KEY environment variable.")
    
    import base64
    import io
    
    # Prepare image data for Claude
    image_data = []
    for idx, img in enumerate(images):
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()
        img_b64 = base64.b64encode(img_bytes).decode()
        
        image_data.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img_b64
            }
        })
    
    headers = {
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json'
    }
    
    payload = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    *image_data
                ]
            }
        ]
    }
    
    response = requests.post(
        'https://api.anthropic.com/v1/messages',
        headers=headers,
        json=payload,
        timeout=120
    )
    
    if response.status_code != 200:
        raise Exception(f"Anthropic API error: {response.status_code} - {response.text}")
    
    result = response.json()
    extracted_text = result['content'][0]['text']
    
    logger.info(f"Anthropic extraction complete. Tokens used: {result.get('usage', {})}")
    
    return extracted_text

def process_text_with_openai(text, prompt, model='gpt-4o'):
    """Process extracted text with OpenAI API (no vision, text-only - much cheaper and faster)"""
    if not OPENAI_API_KEY:
        raise Exception("OpenAI API key not configured. Set OPENAI_API_KEY environment variable.")
    
    headers = {
        'Authorization': f'Bearer {OPENAI_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an expert at analyzing and extracting data from technical documents, specifications, and invoices. Extract data accurately and format it as requested."
            },
            {
                "role": "user",
                "content": f"{prompt}\n\nDocument text:\n\n{text}"
            }
        ],
        "max_tokens": 4096,
        "temperature": 0.1
    }
    
    response = requests.post(
        'https://api.openai.com/v1/chat/completions',
        headers=headers,
        json=payload,
        timeout=120
    )
    
    if response.status_code != 200:
        raise Exception(f"OpenAI API error: {response.status_code} - {response.text}")
    
    result = response.json()
    extracted_data = result['choices'][0]['message']['content']
    
    logger.info(f"OpenAI text processing complete. Tokens used: {result.get('usage', {})}")
    
    return extracted_data

def process_text_with_anthropic(text, prompt, model='claude-3-5-sonnet-20241022'):
    """Process extracted text with Anthropic Claude API (text-only)"""
    if not ANTHROPIC_API_KEY:
        raise Exception("Anthropic API key not configured. Set ANTHROPIC_API_KEY environment variable.")
    
    headers = {
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.1,
        "system": "You are an expert at analyzing and extracting data from technical documents, specifications, and invoices. Extract data accurately and format it as requested.",
        "messages": [
            {
                "role": "user",
                "content": f"{prompt}\n\nDocument text:\n\n{text}"
            }
        ]
    }
    
    response = requests.post(
        'https://api.anthropic.com/v1/messages',
        headers=headers,
        json=payload,
        timeout=120
    )
    
    if response.status_code != 200:
        raise Exception(f"Anthropic API error: {response.status_code} - {response.text}")
    
    result = response.json()
    extracted_data = result['content'][0]['text']
    
    logger.info(f"Anthropic text processing complete. Tokens used: {result.get('usage', {})}")
    
    return extracted_data

def process_pdf_with_llmwhisperer(input_path, task_id, user_id):
    """
    Process PDF using Unstract's LLMWhisperer API
    This extracts text from documents maintaining layout structure
    """
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Uploading to LLMWhisperer...',
            'progress': 10,
            'user_id': user_id
        }
        
        # Step 1: Submit document to LLMWhisperer
        logger.info(f"Submitting document to LLMWhisperer: {input_path}")
        
        # Verify it's actually a PDF file
        if not input_path.lower().endswith('.pdf'):
            raise Exception(f"File is not a PDF: {input_path}")
        
        # Read file as binary data
        with open(input_path, 'rb') as f:
            file_bytes = f.read()
        
        # Verify we have content
        logger.info(f"File size: {len(file_bytes)} bytes")
        
        # Prepare headers - use application/octet-stream as per docs
        headers = {
            'unstract-key': LLMWHISPERER_API_KEY,
            'Content-Type': 'application/octet-stream'
        }
        
        # Parameters as query string (not form data)
        # Use high_quality mode for OCR (native_text only extracts embedded text)
        params = {
            'mode': 'high_quality',  # OCR mode for scanned documents
            'output_mode': 'layout_preserving',
            'page_seperator': '<<<PAGE_BREAK>>>',
        }
        
        logger.info(f"Uploading to {LLMWHISPERER_API_URL}/whisper (mode: high_quality OCR)")
        
        try:
            # Send file as raw binary data (not multipart)
            response = requests.post(
                f'{LLMWHISPERER_API_URL}/whisper',
                headers=headers,
                params=params,
                data=file_bytes,  # Send raw bytes, not files dict
                timeout=300
            )
            
            logger.info(f"LLMWhisperer response status: {response.status_code}")
            logger.info(f"LLMWhisperer response: {response.text}")
            
        except Exception as req_error:
            logger.error(f"Request error: {req_error}")
            raise
        
        if response.status_code != 202:
            raise Exception(f"LLMWhisperer submission failed: {response.status_code} - {response.text}")
        
        whisper_data = response.json()
        whisper_hash = whisper_data.get('whisper_hash')
        
        logger.info(f"LLMWhisperer processing started. Whisper hash: {whisper_hash}")
        
        processing_status[task_id]['message'] = 'Processing document...'
        processing_status[task_id]['progress'] = 30
        
        # Step 2: Poll for status
        max_retries = 60  # 5 minutes max (5 second intervals)
        retry_count = 0
        
        while retry_count < max_retries:
            time.sleep(5)
            
            status_response = requests.get(
                f'{LLMWHISPERER_API_URL}/whisper-status',
                headers=headers,
                params={'whisper_hash': whisper_hash},
                timeout=30
            )
            
            if status_response.status_code != 200:
                raise Exception(f"Status check failed: {status_response.status_code}")
            
            status_data = status_response.json()
            status = status_data.get('status')
            
            logger.info(f"LLMWhisperer status: {status}")
            logger.info(f"LLMWhisperer status data: {status_data}")
            
            if status == 'processed':
                break
            elif status == 'processing':
                retry_count += 1
                processing_status[task_id]['progress'] = min(30 + retry_count, 80)
                continue
            elif status == 'failed' or status == 'error':
                error_msg = status_data.get('message', status_data.get('error', 'Unknown error'))
                logger.error(f"LLMWhisperer error: {error_msg}")
                logger.error(f"Full status response: {status_data}")
                raise Exception(f"LLMWhisperer processing failed: {error_msg}")
            else:
                retry_count += 1
                continue
        
        if retry_count >= max_retries:
            raise Exception("LLMWhisperer processing timeout")
        
        processing_status[task_id]['message'] = 'Retrieving extracted text...'
        processing_status[task_id]['progress'] = 85
        
        # Step 3: Retrieve extracted text
        retrieve_response = requests.get(
            f'{LLMWHISPERER_API_URL}/whisper-retrieve',
            headers=headers,
            params={
                'whisper_hash': whisper_hash,
                'text_only': 'false'  # Get metadata too
            },
            timeout=60
        )
        
        if retrieve_response.status_code != 200:
            raise Exception(f"Text retrieval failed: {retrieve_response.status_code}")
        
        result_data = retrieve_response.json()
        extracted_text = result_data.get('result_text', '')
        
        logger.info(f"LLMWhisperer extraction complete. Text length: {len(extracted_text)}")
        
        # Save result to file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"llmwhisperer_{timestamp}_{task_id[:8]}.txt"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"LLMWhisperer Extraction Results\n")
            f.write(f"File: {os.path.basename(input_path)}\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Whisper Hash: {whisper_hash}\n")
            f.write("=" * 80 + "\n\n")
            f.write(extracted_text)
        
        logger.info(f"Saved LLMWhisperer results to: {output_path}")
        
        # Update database
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE processing_jobs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
            ('completed', task_id)
        )
        conn.commit()
        conn.close()
        
        processing_status[task_id] = {
            'status': 'completed',
            'message': 'LLMWhisperer extraction completed!',
            'progress': 100,
            'extraction_method': 'llmwhisperer',
            'output_file': output_filename,
            'unstract_data': [{
                'file': os.path.basename(input_path),
                'status': 'Success',
                'result': {
                    'output': {
                        'Extracted_Text': extracted_text
                    }
                }
            }],
            'user_id': user_id
        }
        logger.info(f"LLMWhisperer processing completed for task {task_id}")
        
    except Exception as e:
        processing_status[task_id] = {
            'status': 'error',
            'message': f'LLMWhisperer processing failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        logger.error(f"LLMWhisperer processing failed: {e}")

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    
    if not data or not all(k in data for k in ('email', 'password', 'fullName')):
        return jsonify({'error': 'Missing required fields'}), 400
    
    email = data['email'].lower().strip()
    password = data['password']
    full_name = data['fullName'].strip()

    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    if get_user_by_email(email):
        return jsonify({'error': 'Email already registered'}), 400

    user_id = create_user(email, password, full_name)
    if not user_id:
        return jsonify({'error': 'Registration failed'}), 500
    
    # Create access token
    access_token = create_access_token(identity=str(user_id))
    
    return jsonify({
        'message': 'Registration successful',
        'access_token': access_token,
        'user': {
            'id': user_id,
            'email': email,
            'fullName': full_name
        }
    })

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    
    if not data or not all(k in data for k in ('email', 'password')):
        return jsonify({'error': 'Missing email or password'}), 400
    
    email = data['email'].lower().strip()
    password = data['password']
    
    user = get_user_by_email(email)
    if not user or not check_password_hash(user[2], password):
        return jsonify({'error': 'Invalid email or password'}), 401

    access_token = create_access_token(identity=str(user[0]))
    
    return jsonify({
        'message': 'Login successful',
        'access_token': access_token,
        'user': {
            'id': user[0],
            'email': user[1],
            'fullName': user[3]
        }
    })

@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    user_id = int(get_jwt_identity())
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, email, full_name FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({
        'user': {
            'id': user[0],
            'email': user[1],
            'fullName': user[2]
        }
    })


@app.route('/api/upload', methods=['POST'])
@jwt_required()
def upload_file():
    print("=== UPLOAD ENDPOINT CALLED ===")
    print(f"Request method: {request.method}")
    print(f"Request content type: {request.content_type}")
    print(f"Request headers: {dict(request.headers)}")
    
    user_id = int(get_jwt_identity())
    print(f"JWT validation successful, user_id: {user_id}")
    
    print(f"Upload request from user {user_id}")
    print(f"Files in request: {list(request.files.keys())}")
    print(f"Form data: {dict(request.form)}")
    
    if 'file' not in request.files:
        print("Error: No file provided")
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    print(f"File received: {file.filename}")
    
    if file.filename == '' or not allowed_file(file.filename):
        print(f"Error: Invalid file type or empty filename: {file.filename}")
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400
    
    options = {
        'language': request.form.get('language', 'eng'),
        'deskew': request.form.get('deskew', 'true').lower() == 'true',
        'clean': request.form.get('clean', 'false').lower() == 'true',
        'optimize': request.form.get('optimize', '1'),
        'force_ocr': request.form.get('force_ocr', 'false').lower() == 'true',
        'extract_tables': request.form.get('extract_tables', 'true').lower() == 'true'
    }
    task_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    input_filename = f"{timestamp}_{filename}"
    input_path = os.path.join(UPLOAD_FOLDER, input_filename)
    file.save(input_path)
    output_filename = f"OCR_{input_filename}"
    output_path = os.path.join(OUTPUT_FOLDER, output_filename)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO processing_jobs (id, user_id, filename, status) VALUES (?, ?, ?, ?)',
        (task_id, user_id, filename, 'processing')
    )
    conn.commit()
    conn.close()
    thread = threading.Thread(
        target=process_pdf_with_ocr_and_camelot,
        args=(input_path, output_path, options, task_id, user_id)
    )
    thread.start()
    
    print(f"Processing started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': 'File uploaded successfully, processing started',
        'filename': filename
    })

@app.route('/api/upload_llmwhisperer', methods=['POST'])
@jwt_required()
def upload_file_llmwhisperer():
    """Upload file for LLMWhisperer text extraction"""
    print("=== LLMWHISPERER UPLOAD ENDPOINT CALLED ===")
    
    user_id = int(get_jwt_identity())
    print(f"JWT validation successful, user_id: {user_id}")
    
    if 'file' not in request.files:
        print("Error: No file provided")
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    print(f"File received: {file.filename}")
    
    if file.filename == '' or not allowed_file(file.filename):
        print(f"Error: Invalid file type or empty filename: {file.filename}")
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400
    
    task_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    input_filename = f"{timestamp}_{filename}"
    input_path = os.path.join(UPLOAD_FOLDER, input_filename)
    file.save(input_path)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO processing_jobs (id, user_id, filename, status, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)',
        (task_id, user_id, filename, 'processing')
    )
    conn.commit()
    conn.close()

    processing_status[task_id] = {
        'status': 'queued',
        'message': 'File uploaded, queued for LLMWhisperer processing',
        'progress': 0,
        'user_id': user_id
    }

    thread = threading.Thread(
        target=process_pdf_with_llmwhisperer,
        args=(input_path, task_id, user_id)
    )
    thread.start()
    
    print(f"LLMWhisperer processing started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': 'File uploaded successfully, processing with LLMWhisperer',
        'filename': filename
    })

@app.route('/api/upload_direct_llm', methods=['POST'])
@jwt_required()
def upload_file_direct_llm():
    """Upload file for direct LLM processing with custom prompts (GPT-4o/Claude)"""
    print("=== DIRECT LLM UPLOAD ENDPOINT CALLED ===")
    
    user_id = int(get_jwt_identity())
    print(f"JWT validation successful, user_id: {user_id}")
    
    if 'file' not in request.files:
        print("Error: No file provided")
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    print(f"File received: {file.filename}")
    
    if file.filename == '' or not allowed_file(file.filename):
        print(f"Error: Invalid file type or empty filename: {file.filename}")
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400
    
    # Get custom prompts from request
    custom_prompt = request.form.get('custom_prompt', '')
    print(f"Custom prompt received: {custom_prompt}")
    
    # Get model selection from request
    model_name = request.form.get('model_name', 'gpt-4o')  # Default to GPT-4o
    print(f"Model selected: {model_name}")
    
    task_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    input_filename = f"{timestamp}_{filename}"
    input_path = os.path.join(UPLOAD_FOLDER, input_filename)
    file.save(input_path)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO processing_jobs (id, user_id, filename, status, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)',
        (task_id, user_id, filename, 'processing')
    )
    conn.commit()
    conn.close()

    processing_status[task_id] = {
        'status': 'queued',
        'message': 'File uploaded, queued for direct LLM processing',
        'progress': 0,
        'user_id': user_id
    }

    thread = threading.Thread(
        target=process_pdf_with_direct_llm,
        args=(input_path, task_id, user_id, custom_prompt, model_name)
    )
    thread.start()
    
    print(f"Direct LLM processing started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': f'File uploaded successfully, processing with {model_name}',
        'filename': filename,
        'model': model_name
    })

@app.route('/api/upload_unstract', methods=['POST'])
@jwt_required()
def upload_file_unstract():
    """Upload file for Unstract processing with custom prompts"""
    print("=== UNSTRACT UPLOAD ENDPOINT CALLED ===")
    
    user_id = int(get_jwt_identity())
    print(f"JWT validation successful, user_id: {user_id}")
    
    if 'file' not in request.files:
        print("Error: No file provided")
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    print(f"File received: {file.filename}")
    
    if file.filename == '' or not allowed_file(file.filename):
        print(f"Error: Invalid file type or empty filename: {file.filename}")
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400
    
    # Get custom prompts from request
    custom_prompts = request.form.get('custom_prompts', '')
    print(f"Custom prompts received: {custom_prompts}")
    
    # Get model selection from request
    model_name = request.form.get('model_name', 'gpt-4-turbo')  # Default to GPT-4 Turbo
    print(f"Model selected: {model_name}")
    
    # Get API key from request or use default
    api_key = request.form.get('api_key', UNSTRACT_DEFAULT_API_KEY)
    
    task_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    input_filename = f"{timestamp}_{filename}"
    input_path = os.path.join(UPLOAD_FOLDER, input_filename)
    file.save(input_path)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO processing_jobs (id, user_id, filename, status) VALUES (?, ?, ?, ?)',
        (task_id, user_id, filename, 'processing')
    )
    conn.commit()
    conn.close()
    
    thread = threading.Thread(
        target=process_pdf_with_unstract,
        args=(input_path, task_id, user_id, api_key, custom_prompts, model_name)
    )
    thread.start()
    
    print(f"Unstract processing started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': 'File uploaded successfully, Unstract processing started',
        'filename': filename
    })

@app.errorhandler(422)
def handle_unprocessable_entity(e):
    print(f"422 Error occurred: {str(e)}")
    print(f"Error description: {e.description if hasattr(e, 'description') else 'No description'}")
    return jsonify({'error': 'Unprocessable Entity', 'details': str(e)}), 422

@app.errorhandler(Exception)
def handle_general_exception(e):
    print(f"General exception: {str(e)}")
    print(f"Exception type: {type(e).__name__}")
    import traceback
    traceback.print_exc()
    return jsonify({'error': 'Internal server error', 'details': str(e)}), 500

@app.route('/api/status/<task_id>', methods=['GET'])
@jwt_required()
def get_status(task_id):
    """Get processing status"""
    user_id = int(get_jwt_identity())
    
    if task_id not in processing_status:
        return jsonify({'error': 'Task not found'}), 404
    
    status = processing_status[task_id]

    if status.get('user_id') != user_id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    return jsonify(status)

@app.route('/api/download/<task_id>', methods=['GET'])
@jwt_required()
def download_file(task_id):
    user_id = int(get_jwt_identity())
    
    if task_id not in processing_status:
        return jsonify({'error': 'Task not found'}), 404
    
    status = processing_status[task_id]

    if status.get('user_id') != user_id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if status['status'] != 'completed':
        return jsonify({'error': 'File not ready for download'}), 400
    
    output_file = status['output_file']
    output_path = os.path.join(OUTPUT_FOLDER, output_file)
    
    if not os.path.exists(output_path):
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(output_path, as_attachment=True, download_name=output_file)

@app.route('/api/download_all/<task_id>', methods=['GET'])
@jwt_required()
def download_all(task_id):
    user_id = int(get_jwt_identity())
    
    if task_id not in processing_status:
        return jsonify({'error': 'Task not found'}), 404
    
    status = processing_status[task_id]
    if status.get('user_id') != user_id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if status['status'] != 'completed':
        return jsonify({'error': 'Files not ready for download'}), 400

    zip_filename = f"OCR_Results_{task_id}.zip"
    zip_path = os.path.join(OUTPUT_FOLDER, zip_filename)
    
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        output_file = status['output_file']
        output_path = os.path.join(OUTPUT_FOLDER, output_file)
        if os.path.exists(output_path):
            zipf.write(output_path, output_file)
    
        if 'tables' in status and status['tables'] and status['tables_dir']:
            tables_dir = status['tables_dir']
            for table_info in status['tables']:
                for file_key in ['csv_file', 'excel_file']:
                    if file_key in table_info:
                        table_path = os.path.join(tables_dir, table_info[file_key])
                        if os.path.exists(table_path):
                            zipf.write(table_path, f"tables/{table_info[file_key]}")
    
    return send_file(zip_path, as_attachment=True, download_name=zip_filename)

@app.route('/api/jobs', methods=['GET'])
@jwt_required()
def get_user_jobs():
    user_id = int(get_jwt_identity())
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, filename, status, created_at, completed_at 
        FROM processing_jobs 
        WHERE user_id = ? 
        ORDER BY created_at DESC
    ''', (user_id,))
    jobs = cursor.fetchall()
    conn.close()
    
    return jsonify({
        'jobs': [{
            'id': job[0],
            'filename': job[1],
            'status': job[2],
            'created_at': job[3],
            'completed_at': job[4]
        } for job in jobs]
    })

@app.route('/api/launch_abaqus', methods=['POST'])
@jwt_required()
def launch_abaqus():
    """Launch ABAQUS CLI with the extracted CSV data"""
    print("=== REQUEST: POST /api/launch_abaqus ===")
    
    try:
        data = request.get_json()
        csv_data = data.get('csv_data')
        
        if not csv_data:
            return jsonify({'success': False, 'message': 'No CSV data provided'}), 400
        
        abaqus_paths = [
            r"C:\SIMULIA\Commands\abaqus.bat",
            r"C:\Program Files\Dassault Systemes\SimulationServices\V6R2017x\win_b64\code\bin\ABQLauncher.exe",
            r"C:\SIMULIA\Abaqus\Commands\abaqus.bat",
            "abaqus"
        ]
        
        abaqus_exe = None
        for path in abaqus_paths:
            if os.path.exists(path):
                abaqus_exe = path
                break
        
        if not abaqus_exe:
            try:
                result = subprocess.run(['where', 'abaqus'], capture_output=True, text=True, shell=True)
                if result.returncode == 0:
                    abaqus_exe = result.stdout.strip().split('\n')[0]
            except:
                pass
        
        if not abaqus_exe:
            return jsonify({
                'success': False, 
                'message': 'ABAQUS not found.'
            }), 404
        
        logger.info(f"Found ABAQUS at: {abaqus_exe}")
        
        try:

            process = subprocess.Popen(
                [abaqus_exe, 'cae'],  
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
            )
            
            logger.info(f"ABAQUS launched successfully with PID: {process.pid}")
            
            return jsonify({
                'success': True,
                'message': f'ABAQUS launched successfully (PID: {process.pid})',
                'abaqus_path': abaqus_exe
            })
            
        except Exception as e:
            logger.error(f"Failed to launch ABAQUS: {str(e)}")
            return jsonify({
                'success': False,
                'message': f'Failed to launch ABAQUS: {str(e)}'
            }), 500
            
    except Exception as e:
        logger.error(f"Error in launch_abaqus endpoint: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)

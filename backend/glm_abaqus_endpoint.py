# GLM ABAQUS Generator Endpoint
# Add this to app.py before "if __name__ == '__main__':"

@app.route('/api/upload_glm_abaqus_generator', methods=['POST'])
@jwt_required()
def upload_glm_abaqus_generator():
    """
    GLM-4.5V based ABAQUS input file generator
    Extracts stress-strain data and dimensions for a specific serial number,
    then generates modified ABAQUS .inp file
    """
    try:
        user_id = get_jwt_identity()
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        serial_number = request.form.get('serialNumber', '').strip()
        
        if not serial_number:
            return jsonify({'error': 'Serial number is required'}), 400
        
        if file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400
        
        # Save uploaded PDF
        filename = secure_filename(file.filename)
        task_id = str(uuid.uuid4())
        pdf_path = os.path.join(UPLOAD_FOLDER, f"{task_id}_{filename}")
        file.save(pdf_path)
        
        logger.info(f"GLM ABAQUS generator started for serial: {serial_number}")
        
        # Initialize task status
        task_status = {
            'status': 'processing',
            'message': 'Starting ABAQUS input generation...',
            'progress': 10,
            'user_id': user_id,
            'serial_number': serial_number
        }
        
        processing_status[task_id] = task_status
        
        def process_glm_abaqus():
            try:
                task_status['message'] = 'Converting PDF to images...'
                task_status['progress'] = 20
                
                # Convert PDF to images
                from pdf2image import convert_from_path
                import base64
                import re
                
                images = convert_from_path(pdf_path)
                page_count = len(images)
                logger.info(f"Converted {page_count} PDF pages to images")
                
                task_status['message'] = f'Extracting data for serial {serial_number}...'
                task_status['progress'] = 30
                
                # Build content array with all images
                content = []
                for idx, img in enumerate(images):
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG')
                    base64_image = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                    
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    })
                
                # Add extraction prompt
                prompt_text = f"""Extract the following information for specimen with serial number {serial_number}:

1. Stress-Strain Data Table - Extract ALL stress and strain values in CSV format with headers: Sample ID, Stress, Strain
2. Dimensions - Extract the Length (Len) and Diameter (Dia) in mm

Output format:
DIMENSIONS:
Length: <value> mm
Diameter: <value> mm

STRESS_STRAIN_DATA:
<CSV data with Sample ID, Stress, Strain headers>

Extract only data for serial number {serial_number}. Be precise with numerical values."""
                
                content.append({
                    "type": "text",
                    "text": prompt_text
                })
                
                # Send to GLM-4.5V
                from zhipuai import ZhipuAI
                client = ZhipuAI(api_key=GLM_API_KEY)
                
                task_status['progress'] = 50
                
                response = client.chat.completions.create(
                    model="glm-4.5v",
                    messages=[{
                        "role": "user",
                        "content": content
                    }],
                    temperature=0.1,
                    thinking={"type": "disabled"}
                )
                
                extracted_content = response.choices[0].message.content
                logger.info(f"GLM extraction complete: {extracted_content[:500]}")
                
                task_status['progress'] = 60
                task_status['message'] = 'Parsing extracted data...'
                
                # Parse dimensions
                length_match = re.search(r'Length:\s*(\d+(?:\.\d+)?)', extracted_content)
                diameter_match = re.search(r'Diameter:\s*(\d+(?:\.\d+)?)', extracted_content)
                
                if not length_match or not diameter_match:
                    raise ValueError("Could not extract dimensions from PDF")
                
                length = float(length_match.group(1))
                diameter = float(diameter_match.group(1))
                
                # Calculate scale factors
                scale_factor_length = length / 100.0
                scale_factor_diameter = diameter / 150.0
                
                logger.info(f"Dimensions: L={length}mm, D={diameter}mm, Scale: L={scale_factor_length}, D={scale_factor_diameter}")
                
                # Extract CSV data
                csv_match = re.search(r'STRESS_STRAIN_DATA:\s*\n(.*?)(?:\n\n|$)', extracted_content, re.DOTALL)
                if not csv_match:
                    # Try alternate format
                    csv_match = re.search(r'Sample ID,Stress,Strain\s*\n(.*?)(?:\n\n|$)', extracted_content, re.DOTALL)
                
                if not csv_match:
                    raise ValueError("Could not extract stress-strain data")
                
                stress_strain_csv = csv_match.group(1).strip()
                
                # Save stress-strain data
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                csv_filename = f"stress_strain_{serial_number}_{timestamp}.csv"
                csv_path = os.path.join(OUTPUT_FOLDER, csv_filename)
                
                with open(csv_path, 'w', encoding='utf-8') as f:
                    f.write("Sample ID,Stress,Strain\n")
                    f.write(stress_strain_csv)
                
                task_status['progress'] = 70
                task_status['message'] = 'Generating ABAQUS input file...'
                
                # Run modify_abaqus_input.py
                from modify_abaqus_input import modify_abaqus_file
                
                base_inp = "Compression.inp"
                output_inp_filename = f"Compression_{serial_number}_{timestamp}.inp"
                output_inp_path = os.path.join(OUTPUT_FOLDER, output_inp_filename)
                
                # Calculate strain (assume max strain from data or use -0.18 as default)
                strain = -0.18  # Default compression strain
                
                modify_abaqus_file(
                    base_inp,
                    output_inp_path,
                    scale_factor_d=scale_factor_diameter,
                    scale_factor=scale_factor_length,
                    strain=strain
                )
                
                logger.info(f"ABAQUS file generated: {output_inp_path}")
                
                task_status['progress'] = 100
                task_status['status'] = 'completed'
                task_status['message'] = 'ABAQUS input file generated successfully'
                task_status['output_file'] = output_inp_filename
                task_status['csv_file'] = csv_filename
                task_status['length'] = length
                task_status['diameter'] = diameter
                task_status['scale_factor_length'] = scale_factor_length
                task_status['scale_factor_diameter'] = scale_factor_diameter
                task_status['extracted_content'] = extracted_content
                
            except Exception as e:
                logger.error(f"GLM ABAQUS generation error: {str(e)}", exc_info=True)
                task_status['status'] = 'error'
                task_status['message'] = f'Error: {str(e)}'
        
        # Start background processing
        thread = threading.Thread(target=process_glm_abaqus)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'task_id': task_id,
            'message': 'ABAQUS generation started',
            'status': 'processing'
        }), 202
        
    except Exception as e:
        logger.error(f"Error in GLM ABAQUS generator: {str(e)}")
        return jsonify({'error': str(e)}), 500

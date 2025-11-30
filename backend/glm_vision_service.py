"""
GLM-4V Vision Service for Table Extraction
Uses GLM-4.5V API from Z.AI for multimodal table extraction
Now using official ZhipuAI SDK for better file handling
"""

import os
import requests
import base64
import json
import logging
from typing import List, Dict, Optional
import io
import csv
import time
from zhipuai import ZhipuAI

logger = logging.getLogger(__name__)


class GLMVisionService:
    """Service for GLM-4V Vision API table extraction"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize GLM Vision Service
        
        Args:
            api_key: Z.AI API key (or use GLM_API_KEY environment variable)
        """
        self.api_key = api_key or os.getenv('GLM_API_KEY', '')
        self.base_url = "https://api.z.ai/api/paas/v4/chat/completions"
        
        if not self.api_key:
            logger.warning("GLM_API_KEY not set - GLM Vision service will not work")
        else:
            # Initialize ZhipuAI client
            self.client = ZhipuAI(api_key=self.api_key)
    
    def encode_image_to_base64(self, image_path: str) -> str:
        """Encode image file to base64 string"""
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    
    def encode_image_bytes_to_base64(self, image_bytes: bytes) -> str:
        """Encode image bytes to base64 string"""
        return base64.b64encode(image_bytes).decode('utf-8')
    
    def encode_pdf_to_base64(self, pdf_path: str) -> str:
        """Encode PDF file to base64 string"""
        with open(pdf_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    
    def extract_tables_from_pdf(
        self,
        pdf_path: str,
        custom_prompt: Optional[str] = None,
        model: str = "glm-4.5v",
        return_format: str = "csv"
    ) -> Dict:
        """Extract tables directly from PDF file using ZhipuAI SDK by converting to images"""
        if not self.api_key:
            raise ValueError("GLM API key not configured")
        
        try:
            # Import pdf2image for converting PDF to images
            from pdf2image import convert_from_path
            
            # Step 1: Convert PDF pages to images
            logger.info(f"Converting PDF to images: {pdf_path}")
            images = convert_from_path(pdf_path)
            
            if not images:
                return {
                    'success': False,
                    'error': 'Empty PDF or conversion failed'
                }
            
            logger.info(f"Processing {len(images)} pages...")
            
            # Step 2: Build content array with all images in sequence
            content = []
            
            # Add all images first (in order)
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
                logger.info(f"Added page {idx + 1}/{len(images)}")
            
            # Step 3: Prepare prompt
            if custom_prompt:
                prompt_text = custom_prompt
            else:
                if return_format == "csv":
                    prompt_text = "Extract all the tables from this series of images in their sequence and output it as CSV."
                else:
                    prompt_text = "Extract all the tables from this series of images in their sequence and output it as JSON array."
            
            # Add the text prompt at the end
            content.append({
                "type": "text",
                "text": prompt_text
            })
            
            # Step 4: Create chat completion with all images
            logger.info(f"Sending to GLM-4.5V...")
            start_time = time.time()
            
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                temperature=0.1,
                thinking={
                    "type": "disabled"
                }
            )
            
            elapsed = time.time() - start_time
            logger.info(f"GLM API request took {elapsed:.2f}s")
            
            # Extract response
            extracted_content = response.choices[0].message.content
            usage = {
                'prompt_tokens': response.usage.prompt_tokens,
                'completion_tokens': response.usage.completion_tokens,
                'total_tokens': response.usage.total_tokens
            }
            
            logger.info(f"GLM-4.5V extraction complete. Tokens: {usage.get('total_tokens', 'N/A')}")
            
            return {
                'success': True,
                'content': extracted_content,
                'format': return_format,
                'model': model,
                'usage': usage
            }
            
        except Exception as e:
            logger.error(f"GLM PDF extraction failed: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error': f'PDF extraction failed: {str(e)}'
            }
    
    def extract_tables_from_images(
        self,
        image_paths: List[str],
        custom_prompt: Optional[str] = None,
        model: str = "glm-4.5v",
        return_format: str = "csv",
        batch_size: int = 2,  # Process 2 images per batch to avoid timeouts
        batch_delay: float = 5.0  # 5 second delay between batches
    ) -> Dict:
        """
        Extract tables from images using GLM-4.5V
        
        Args:
            image_paths: List of image file paths
            custom_prompt: Custom extraction prompt (if None, uses default table extraction)
            model: Model to use (glm-4.5v, glm-4.6v, etc.)
            return_format: Output format - "csv" or "json"
            batch_size: Number of images to process per API call (default: 2)
            batch_delay: Delay in seconds between batches to avoid rate limits (default: 5.0)
            
        Returns:
            Dict with extracted data and metadata
        """
        if not self.api_key:
            raise ValueError("GLM API key not configured")
        
        # Process images in batches to avoid rate limits and payload size issues
        all_results = []
        total_usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
        
        for batch_idx in range(0, len(image_paths), batch_size):
            batch_paths = image_paths[batch_idx:batch_idx + batch_size]
            logger.info(f"Processing batch {batch_idx // batch_size + 1}/{(len(image_paths) + batch_size - 1) // batch_size} ({len(batch_paths)} images)")
            
            # Add delay between batches (INCLUDING first batch to avoid rapid requests)
            if batch_delay > 0:
                logger.info(f"Waiting {batch_delay}s to avoid rate limits...")
                time.sleep(batch_delay)
            
            # Process this batch
            batch_result = self._extract_batch(
                batch_paths, custom_prompt, model, return_format
            )
            
            if not batch_result.get('success'):
                # Return error immediately
                return batch_result
            
            all_results.append(batch_result['content'])
            
            # Accumulate token usage
            usage = batch_result.get('usage', {})
            total_usage['prompt_tokens'] += usage.get('prompt_tokens', 0)
            total_usage['completion_tokens'] += usage.get('completion_tokens', 0)
            total_usage['total_tokens'] += usage.get('total_tokens', 0)
        
        # Combine results from all batches
        if return_format == "csv":
            combined_content = "\n\n".join(all_results)
        else:
            # For JSON, merge arrays
            combined_content = "[\n" + ",\n".join([r.strip('[]') for r in all_results]) + "\n]"
        
        return {
            'success': True,
            'content': combined_content,
            'format': return_format,
            'model': model,
            'usage': total_usage,
            'batches_processed': len(range(0, len(image_paths), batch_size))
        }
    
    def _extract_batch(
        self,
        image_paths: List[str],
        custom_prompt: Optional[str],
        model: str,
        return_format: str
    ) -> Dict:
        """
        Extract tables from a batch of images (internal method)
        
        Args:
            image_paths: List of image file paths for this batch
            custom_prompt: Custom extraction prompt
            model: Model to use
            return_format: Output format
            
        Returns:
            Dict with extracted data and metadata
        """
        
        # Build message content
        content = []
        
        # Add images
        for img_path in image_paths:
            try:
                image_b64 = self.encode_image_to_base64(img_path)
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}"
                    }
                })
            except Exception as e:
                logger.error(f"Failed to encode image {img_path}: {e}")
                continue
        
        # Add text prompt
        if custom_prompt:
            prompt_text = custom_prompt
        else:
            # Default table extraction prompt
            if return_format == "csv":
                prompt_text = """Extract ALL tables from the provided images.

For each table:
1. Identify the table structure (headers and rows)
2. Extract all data accurately
3. Return the data in CSV format

Requirements:
- Preserve the exact values from the table
- Maintain proper column alignment
- Use commas as separators
- One table per section
- If multiple tables exist, separate them with a blank line and a header comment like "# Table 1", "# Table 2", etc.

Return ONLY the CSV data, no additional explanation."""
            else:
                prompt_text = """Extract ALL tables from the provided images.

Return the data as a JSON array where each element represents a table.

Format:
[
  {
    "table_number": 1,
    "headers": ["Column1", "Column2", ...],
    "rows": [
      ["value1", "value2", ...],
      ["value1", "value2", ...]
    ]
  },
  ...
]

Requirements:
- Extract all tables found
- Preserve exact values
- Maintain proper structure
- Return ONLY valid JSON, no additional text"""
        
        content.append({
            "type": "text",
            "text": prompt_text
        })
        
        # Build request payload
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": content
                }
            ],
            "temperature": 0.1,  # Very low temperature - disables thinking mode, faster responses
            "max_tokens": 16384,  # GLM-4.5V supports up to 16K output
            "stream": False
        }
        
        # Make API request
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        logger.info(f"Calling GLM-4.5V API for table extraction ({len(image_paths)} images)")
        
        # Retry logic with exponential backoff for rate limits
        max_retries = 5  # Increased from 3 to 5
        base_delay = 5   # Increased from 2 to 5 seconds
        
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=600  # 10 minutes for processing all images at once
                )
                
                # Handle rate limiting (429) with retry
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        # Exponential backoff: 5s, 10s, 20s, 40s, 80s
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Rate limited (429). Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                        time.sleep(delay)
                        continue
                    else:
                        logger.error(f"Rate limited after {max_retries} attempts")
                        return {
                            'success': False,
                            'error': 'Rate limit exceeded after multiple retries. Please wait a few minutes and try again, or contact Z.AI support to check your API quota.'
                        }
                
                response.raise_for_status()
                result = response.json()
                
                # Extract content from response
                if 'choices' in result and len(result['choices']) > 0:
                    extracted_content = result['choices'][0]['message']['content']
                    
                    # Token usage
                    usage = result.get('usage', {})
                    
                    logger.info(f"GLM-4.5V extraction complete. Tokens: {usage.get('total_tokens', 'N/A')}")
                    
                    return {
                        'success': True,
                        'content': extracted_content,
                        'format': return_format,
                        'model': model,
                        'usage': usage,
                        'raw_response': result
                    }
                else:
                    logger.error("Unexpected GLM API response format")
                    return {
                        'success': False,
                        'error': 'Invalid API response format',
                        'raw_response': result
                    }
                    
            except requests.exceptions.Timeout as e:
                # Handle timeout specifically
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Request timed out. Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"GLM API request timed out after {max_retries} attempts")
                    return {
                        'success': False,
                        'error': 'Request timed out. Try reducing the number of pages or image quality.'
                    }
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Request failed: {e}. Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"GLM API request failed after {max_retries} attempts: {e}")
                    return {
                        'success': False,
                        'error': f'API request failed: {str(e)}'
                    }
    
    def convert_to_csv_file(self, content: str, output_path: str) -> bool:
        """
        Save extracted content to CSV file
        
        Args:
            content: Extracted table content
            output_path: Path to save CSV file
            
        Returns:
            True if successful
        """
        try:
            with open(output_path, 'w', encoding='utf-8', newline='') as f:
                f.write(content)
            logger.info(f"CSV saved to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save CSV: {e}")
            return False
    
    def parse_json_tables(self, content: str) -> List[Dict]:
        """
        Parse JSON table format from GLM response
        
        Args:
            content: JSON string from GLM
            
        Returns:
            List of table dictionaries
        """
        try:
            # Try to extract JSON if wrapped in markdown code blocks
            if '```json' in content:
                start = content.find('```json') + 7
                end = content.find('```', start)
                content = content[start:end].strip()
            elif '```' in content:
                start = content.find('```') + 3
                end = content.find('```', start)
                content = content[start:end].strip()
            
            tables = json.loads(content)
            return tables if isinstance(tables, list) else [tables]
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON tables: {e}")
            return []


# Example usage functions
def extract_tables_from_pdf_pages(pdf_image_paths: List[str], custom_prompt: Optional[str] = None) -> Dict:
    """
    Extract tables from PDF pages (already converted to images)
    
    Args:
        pdf_image_paths: List of paths to page images
        custom_prompt: Optional custom extraction prompt
        
    Returns:
        Dictionary with extraction results
    """
    service = GLMVisionService()
    result = service.extract_tables_from_images(
        pdf_image_paths,
        custom_prompt=custom_prompt,
        return_format="csv"
    )
    return result


if __name__ == "__main__":
    # Test the service
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python glm_vision_service.py <image1> [image2] ...")
        print("\nExample:")
        print("  python glm_vision_service.py page1.jpg page2.jpg")
        sys.exit(1)
    
    image_paths = sys.argv[1:]
    
    service = GLMVisionService()
    result = service.extract_tables_from_images(image_paths)
    
    if result['success']:
        print("="*60)
        print("EXTRACTED TABLES (CSV)")
        print("="*60)
        print(result['content'])
        print("="*60)
        print(f"Tokens used: {result['usage'].get('total_tokens', 'N/A')}")
    else:
        print(f"Extraction failed: {result.get('error', 'Unknown error')}")

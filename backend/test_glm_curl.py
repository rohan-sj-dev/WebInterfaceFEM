import requests
import json
import os

# Configuration
API_KEY = "fa5787c10dc4422881dacccfaca3a4ed.nVMVqj2qPcM548FM"
API_URL = "https://api.z.ai/api/paas/v4/chat/completions"

# Use an existing PDF from the workspace
pdf_path = r"c:\Users\drsam\Downloads\ML\OCRpdf\SampleInput.pdf"

if not os.path.exists(pdf_path):
    print(f"Error: PDF not found at {pdf_path}")
    print("Looking for any PDF in the workspace...")
    # Try to find any PDF
    import glob
    pdfs = glob.glob(r"c:\Users\drsam\Downloads\ML\OCRpdf\*.pdf")
    if pdfs:
        pdf_path = pdfs[0]
        print(f"Using: {pdf_path}")
    else:
        print("No PDFs found!")
        exit(1)

print(f"Testing GLM API with PDF: {pdf_path}")
print(f"File size: {os.path.getsize(pdf_path) / 1024:.2f} KB")

# Prepare the request
headers = {
    'Accept-Language': 'en-US,en',
    'Authorization': f'Bearer {API_KEY}',
    'Content-Type': 'application/json'
}

payload = {
    "model": "glm-4.6",  # Using glm-4.6 as in the curl example
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "file_url",
                    "file_url": {
                        "url": pdf_path  # Testing with local file path
                    }
                }
            ]
        },
        {
            "role": "user",
            "content": "Extract all tables from this PDF document. Return the data in CSV format."
        }
    ],
    "temperature": 0.1,
    "max_tokens": 16384,
    "stream": False,
    "thinking": {
        "type": "disabled"
    }
}

print("\n=== Sending Request ===")
print(f"URL: {API_URL}")
print(f"Model: {payload['model']}")
print(f"PDF: {pdf_path}")

try:
    response = requests.post(
        API_URL,
        headers=headers,
        json=payload,
        timeout=120
    )
    
    print(f"\n=== Response ===")
    print(f"Status Code: {response.status_code}")
    print(f"Headers: {dict(response.headers)}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"\n=== Success ===")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0]['message']['content']
            print(f"\n=== Extracted Content ===")
            print(content)
            
            # Save to file
            output_file = "glm_curl_test_output.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"\nSaved to: {output_file}")
    else:
        print(f"\n=== Error ===")
        print(f"Response: {response.text}")
        
except Exception as e:
    print(f"\n=== Exception ===")
    print(f"Error: {str(e)}")
    import traceback
    traceback.print_exc()

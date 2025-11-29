import base64
import io
from zhipuai import ZhipuAI
from pdf2image import convert_from_path # Requires poppler installed

client = ZhipuAI(api_key="")

def analyze_pdf_page_as_image(pdf_path):
    # 1. Convert ALL PDF pages to images
    # Note: 'images' is a list of PIL Image objects
    images = convert_from_path(pdf_path)  # Converts all pages
    
    if not images:
        return "Error: Empty PDF"

    print(f"Processing {len(images)} pages...")
    
    # 2. Build content array with all images in sequence
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
        print(f"Added page {idx + 1}/{len(images)}")
    
    # Add the text prompt at the end
    content.append({
        "type": "text",
        "text": "Extract all the tables from this series of images in their sequence and output it as CSV."
    })

    # 3. Send all images to GLM-4.5V at once
    print("Sending to GLM-4.5V...")
    response = client.chat.completions.create(
        model="glm-4.5v",
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
    return response.choices[0].message.content

print(analyze_pdf_page_as_image("0047_001-combined.pdf"))
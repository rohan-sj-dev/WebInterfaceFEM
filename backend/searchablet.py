import boto3
import json

textract_client = boto3.client("textract")

with open("4340_spec.pdf", "rb") as document_file:
    print(document_file)
    document_bytes = document_file.read()

    response = textract_client.analyze_document(
        Document={"Bytes": document_bytes}, FeatureTypes=['TABLES','FORMS']
    )

    json.dump(response, open("response.json", "w"))
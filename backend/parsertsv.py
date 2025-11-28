import csv

def parse_tsv(filepath):
    data = []
    with open(filepath, 'r', newline='', encoding='utf-8') as tsvfile:
        # csv.reader can be used for TSV by specifying delimiter='\t'
        tsv_reader = csv.reader(tsvfile, delimiter='\t')
        for row in tsv_reader:
            data.append(row)
    return data

# Example usage:
# Assuming 'example.tsv' exists with tab-separated data
parsed_data = parse_tsv('manuf.tsv')
for record in parsed_data:
    print(record)
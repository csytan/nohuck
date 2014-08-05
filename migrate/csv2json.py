import csv
import json
import os
import sys


filename = sys.argv[1]
cwd = os.path.dirname(os.path.abspath(__file__))
file_path = os.path.join(cwd, filename)
output_path = os.path.join(cwd, filename + '.json')


def parse_csv(file):
    output = []
    reader = csv.reader(file, delimiter=',', quotechar='"')
    headers = [h.strip('"') for h in reader.next()]
    for row in reader:
        value = {}
        for header, col in zip(headers, row):
            value[header] = clean_value(col)
        output.append(value)
    return output

def clean_value(value):
    value = value.strip('"')
    try:
        value = int(value)
    except ValueError:
        pass
    return value

print 'Parsing: ' + file_path
with open(file_path, 'rb') as f:
    results = parse_csv(f)

print 'Writing: ' + output_path
with open(output_path, 'w') as f:
    f.write(json.dumps(results))




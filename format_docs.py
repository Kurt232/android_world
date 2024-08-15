import json
import os
docs_dir = 'tmp/docs'

docs_path = [ os.path.join(docs_dir, f) for f in os.listdir(docs_dir)]

for doc_path in docs_path:
  doc_data = json.load(open(doc_path, 'r'))
  
  # screen_name -> elements, skeleton
  for k, v in doc_data.items():
    _elements = {}
    for k1, v1 in v['elements'].items():
      k1 = k1.replace(":", "__")
      v1["name"] = v1["name"].replace(":", "__")
      xpath = v1["xpath"]
      xpath = xpath.replace("resource-id", "resource_id") if xpath else xpath
      v1["xpath"] = xpath
      _all_paths = []
      if 'paths' in v1:
        for paths in v1['paths']:
          _paths = []
          for p in paths:
            _paths.append(p.replace(":", "__"))
          _all_paths.append(_paths)
        v1['paths'] = _all_paths
      
      _elements[k1] = v1
    
    doc_data[k]['elements'] = _elements
  
  json.dump(doc_data, open(doc_path, 'w'), indent=2)
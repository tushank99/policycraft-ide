import hashlib
import json
from typing import Union, Dict, Any, List

def calculate_sha256(data: Union[str, bytes, Dict[str, Any], List[Any]]) -> str:
    """
    Calculates a deterministic SHA-256 hash.
    Safely handles strings, raw bytes (ZIP files), and dictionaries (JSON).
    """
    if isinstance(data, (dict, list)):
        # sort_keys=True ensures the exact same JSON always produces the same hash
        data_bytes = json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')
    elif isinstance(data, str):
        data_bytes = data.encode('utf-8')
    elif isinstance(data, bytes):
        data_bytes = data
    else:
        raise ValueError(f"Unsupported data type for hashing: {type(data)}")
    
    return hashlib.sha256(data_bytes).hexdigest()
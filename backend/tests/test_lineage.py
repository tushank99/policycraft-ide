import pytest
from typing import Any, cast
import pytest
from backend.shared.lineage import calculate_sha256

def test_calculate_sha256_string():
    """Verify string hashing matches expected SHA-256 output."""
    data = "hello world"
    # echo -n "hello world" | sha256sum
    expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    assert calculate_sha256(data) == expected

def test_calculate_sha256_bytes():
    """Verify raw byte hashing (simulating a ZIP file)."""
    data = b"binary_data_123"
    expected = calculate_sha256("binary_data_123")  # Should match the string equivalent
    assert calculate_sha256(data) == expected

def test_calculate_sha256_json_deterministic():
    """Verify that JSON dictionaries are hashed deterministically regardless of key order."""
    # Two dictionaries with the exact same data but different insertion order
    dict_a = {"language": "python", "framework": "fastapi", "otelEnabled": True}
    dict_b = {"otelEnabled": True, "framework": "fastapi", "language": "python"}
    
    hash_a = calculate_sha256(dict_a)
    hash_b = calculate_sha256(dict_b)
    
    assert hash_a == hash_b
    
    assert len(hash_a) == 64

def test_calculate_sha256_unsupported_type():
    """Verify that unsupported types raise a ValueError instead of generating bad hashes."""
    class DummyObject:
        pass
        
    with pytest.raises(ValueError, match="Unsupported data type"):
        calculate_sha256(cast(Any, DummyObject()))  
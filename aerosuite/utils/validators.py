"""
Validation utilities for AeroSuite Pro.

Provides input validation functions for various parameters.
"""

import re
from typing import List, Tuple, Optional


def validate_float_list(text: str) -> Tuple[bool, str, List[float]]:
    """
    Validate and parse a comma-separated list of floats.
    
    Args:
        text: Input string containing comma-separated numbers
        
    Returns:
        Tuple of (is_valid, error_message, parsed_values)
    """
    text = text.strip()
    if not text:
        return False, "Empty input", []
    
    try:
        values = [float(x.strip()) for x in text.split(',')]
        if not values:
            return False, "No values found", []
        return True, "", values
    except ValueError:
        return False, "Invalid number format", []


def validate_altitude(altitude: str) -> Tuple[bool, str]:
    """
    Validate altitude format (e.g., '10km' or '10000m').
    
    Args:
        altitude: Altitude string
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not altitude:
        return False, "Altitude cannot be empty"
    
    # Check for valid format
    pattern = r'^\d+(\.\d+)?(km|m)$'
    if not re.match(pattern, altitude.lower()):
        return False, "Invalid altitude format. Use format like '10km' or '10000m'"
    
    return True, ""


def validate_positive_float(value: str, name: str = "Value") -> Tuple[bool, str]:
    """
    Validate that a string represents a positive float.
    
    Args:
        value: String to validate
        name: Name of the parameter (for error messages)
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        num = float(value)
        if num <= 0:
            return False, f"{name} must be positive"
        return True, ""
    except ValueError:
        return False, f"{name} must be a valid number"


def validate_reynolds_number(reynolds: str) -> Tuple[bool, str]:
    """
    Validate Reynolds number format (accepts scientific notation).
    
    Args:
        reynolds: Reynolds number string
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        num = float(reynolds)
        if num <= 0:
            return False, "Reynolds number must be positive"
        return True, ""
    except ValueError:
        return False, "Invalid Reynolds number format"


def validate_file_path(path: str) -> Tuple[bool, str]:
    """
    Validate file path string.
    
    Args:
        path: File path to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not path or not path.strip():
        return False, "File path cannot be empty"
    
    return True, ""


def validate_config_name(name: str) -> Tuple[bool, str]:
    """
    Validate configuration name.
    
    Args:
        name: Configuration name
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name or not name.strip():
        return False, "Name cannot be empty"
    
    # Check for invalid characters
    invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for char in invalid_chars:
        if char in name:
            return False, f"Name cannot contain '{char}'"
    
    return True, ""

"""
File handling utilities for AeroSuite Pro.

Provides functions for reading, writing, and managing configuration files.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional


def read_json_file(filepath: Path) -> Optional[Dict[str, Any]]:
    """
    Read and parse a JSON file.
    
    Args:
        filepath: Path to JSON file
        
    Returns:
        Dictionary of parsed JSON data, or None if error
    """
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, IOError) as e:
        print(f"Error reading JSON file: {e}")
        return None


def write_json_file(filepath: Path, data: Dict[str, Any]) -> bool:
    """
    Write data to a JSON file.
    
    Args:
        filepath: Path to JSON file
        data: Dictionary to write
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)
        return True
    except (IOError, TypeError) as e:
        print(f"Error writing JSON file: {e}")
        return False


def read_template_file(filepath: Path) -> Optional[str]:
    """
    Read a template file.
    
    Args:
        filepath: Path to template file
        
    Returns:
        Template content as string, or None if error
    """
    try:
        with open(filepath, 'r') as f:
            return f.read()
    except (FileNotFoundError, IOError) as e:
        print(f"Error reading template file: {e}")
        return None


def write_config_file(filepath: Path, content: str) -> bool:
    """
    Write configuration file content.
    
    Args:
        filepath: Path to output file
        content: Configuration content
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(filepath, 'w') as f:
            f.write(content)
        return True
    except IOError as e:
        print(f"Error writing config file: {e}")
        return False


def ensure_directory(directory: Path) -> bool:
    """
    Ensure a directory exists, creating it if necessary.
    
    Args:
        directory: Path to directory
        
    Returns:
        True if directory exists or was created, False otherwise
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as e:
        print(f"Error creating directory: {e}")
        return False


def get_safe_filename(base_name: str, extension: str = ".cfg") -> str:
    """
    Generate a safe filename by removing invalid characters.
    
    Args:
        base_name: Base name for the file
        extension: File extension (with dot)
        
    Returns:
        Safe filename string
    """
    # Remove invalid characters
    invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    safe_name = base_name
    for char in invalid_chars:
        safe_name = safe_name.replace(char, '_')
    
    # Ensure extension
    if not safe_name.endswith(extension):
        safe_name += extension
    
    return safe_name

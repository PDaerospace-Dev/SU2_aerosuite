"""
SU2 Convergence Monitor.

Provides functionality for reading and processing SU2 history files.
"""

import pandas as pd
from typing import List, Tuple, Optional
from pathlib import Path


class SU2Monitor:
    """Monitor for SU2 convergence data."""
    
    @staticmethod
    def check_legacy_format(filename: str) -> List[int]:
        """
        Check if file is in legacy format and determine rows to skip.
        
        Args:
            filename: Path to history file
            
        Returns:
            List of row indices to skip when reading
        """
        try:
            with open(filename, "r") as f:
                line = f.readline()
                if line[0:5] == "TITLE":
                    return [0, 2]  # Legacy format
                else:
                    return []  # New format
        except (FileNotFoundError, IOError):
            return []
    
    @staticmethod
    def load_history_file(filename: str) -> Optional[pd.DataFrame]:
        """
        Load SU2 history file into pandas DataFrame.
        
        Args:
            filename: Path to history file
            
        Returns:
            DataFrame with convergence data, or None if error
        """
        if not filename:
            return None
        
        try:
            skip_rows = SU2Monitor.check_legacy_format(filename)
            df = pd.read_csv(filename, skiprows=skip_rows)
            
            # Clean column names
            df.columns = df.columns.str.replace('"', '')
            df.columns = df.columns.str.replace(' ', '')
            
            return df
        except (FileNotFoundError, pd.errors.ParserError, IOError) as e:
            print(f"Error loading history file: {e}")
            return None
    
    @staticmethod
    def filter_residual_columns(df: pd.DataFrame) -> pd.DataFrame:
        """
        Filter DataFrame to only residual and force coefficient columns.
        
        Args:
            df: Input DataFrame
            
        Returns:
            Filtered DataFrame
        """
        return df.filter(regex='rms|Res|^CL$|^CD$|^CFx$|^CFy$|^CFz$')
    
    @staticmethod
    def get_column_names(filename: str) -> List[str]:
        """
        Get list of residual column names from history file.
        
        Args:
            filename: Path to history file
            
        Returns:
            List of column names
        """
        df = SU2Monitor.load_history_file(filename)
        if df is None:
            return []
        
        df_filtered = SU2Monitor.filter_residual_columns(df)
        return df_filtered.columns.tolist()
    
    @staticmethod
    def normalize_data(
        data: List[float],
        normalize: bool = False
    ) -> List[float]:
        """
        Normalize data by first non-zero iteration value.
        
        Args:
            data: List of data values
            normalize: Whether to normalize
            
        Returns:
            Normalized or original data
        """
        if not normalize or len(data) < 2:
            return data
        
        # Find first non-zero value for normalization
        norm_value = None
        for val in data[1:]:
            if abs(val) > 1e-6:
                norm_value = val
                break
        
        if norm_value is None:
            return data
        
        # Normalize: convert to relative change from first iteration
        return [1 + val - norm_value for val in data]
    
    @staticmethod
    def get_plot_data(
        filename: str,
        selected_columns: List[bool],
        normalize: bool = False
    ) -> Tuple[List[int], List[List[float]], List[str]]:
        """
        Get data for plotting from history file.
        
        Args:
            filename: Path to history file
            selected_columns: Boolean list of which columns to include
            normalize: Whether to normalize data
            
        Returns:
            Tuple of (iterations, data_lists, column_names)
        """
        df = SU2Monitor.load_history_file(filename)
        if df is None:
            return [], [], []
        
        df_filtered = SU2Monitor.filter_residual_columns(df)
        
        iterations = list(range(len(df_filtered)))
        data_lists = []
        column_names = []
        
        for i, (col_name, include) in enumerate(zip(df_filtered.columns, selected_columns)):
            if include:
                data = df_filtered.iloc[:, i].tolist()
                normalized_data = SU2Monitor.normalize_data(data, normalize)
                data_lists.append(normalized_data)
                column_names.append(col_name)
        
        return iterations, data_lists, column_names

"""
AeroSummary - SU2 Results Consolidation and Analysis.

Provides functionality for consolidating multiple SU2 history files and generating plots.
"""

import os
import re
from typing import List, Dict, Tuple, Optional, Callable
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


# Constants
MIN_CONVERGENCE_ITERATIONS = 10
CONVERGENCE_THRESHOLD = 1e-3


class AeroSummary:
    """Consolidate and analyze SU2 results from multiple cases."""
    
    @staticmethod
    def check_convergence(df: pd.DataFrame, columns: List[str]) -> Tuple[bool, str]:
        """
        Check if simulation has converged by examining last iterations.
        
        Args:
            df: DataFrame containing history data
            columns: Columns to check for convergence
            
        Returns:
            Tuple of (is_converged, message)
        """
        if len(df) < MIN_CONVERGENCE_ITERATIONS:
            return False, f"Insufficient iterations ({len(df)} < {MIN_CONVERGENCE_ITERATIONS})"
        
        # Check variance in last 10% of iterations for key columns
        check_cols = [c for c in ['CD', 'CL', 'CMy'] if c in columns]
        if not check_cols:
            return True, "No convergence columns found, assuming converged"
        
        tail_fraction = max(10, int(len(df) * 0.1))
        tail_data = df.tail(tail_fraction)
        
        for col in check_cols:
            if col in tail_data.columns:
                std = tail_data[col].std()
                mean = abs(tail_data[col].mean())
                if mean > 0 and (std / mean) > CONVERGENCE_THRESHOLD:
                    return False, f"{col} not converged (std/mean = {std/mean:.2e})"
        
        return True, "Converged"
    
    @staticmethod
    def extract_mach_from_case_name(case_name: str) -> float:
        """Extract Mach number from case directory name."""
        match = re.search(r'^M([\dp]+)', case_name, re.IGNORECASE)
        return float(match.group(1).replace('p', '.')) if match else 999.0
    
    @staticmethod
    def extract_alpha_from_case_name(case_name: str) -> float:
        """
        Extract angle of attack from case directory name.
        
        Supports formats:
        - An10 or an20 (n=negative, case insensitive)
        - A10m or A10p (m=minus, p=plus)
        - A-10 or A10 (standard format)
        """
        # Format: An10 or an20 (n = negative, case insensitive)
        match_n = re.search(r'_A[nN](\d+\.?\d*)', case_name, re.IGNORECASE)
        if match_n:
            num = float(match_n.group(1))
            return -num  # 'n' means negative
        
        # Format: A5m or A5p (m=minus, p=plus)
        match_pm = re.search(r'_A(\d+\.?\d*)([mp])', case_name, re.IGNORECASE)
        if match_pm:
            num = float(match_pm.group(1))
            sign = match_pm.group(2).lower()
            return -num if sign == 'm' else num
        
        # Standard format: A-5 or A5
        match_std = re.search(r'_A(-?\d+\.?\d*)', case_name, re.IGNORECASE)
        return float(match_std.group(1)) if match_std else 999.0
    
    @staticmethod
    def is_valid_case_name(case_name: str) -> bool:
        """Check if case name matches expected pattern."""
        has_mach = bool(re.search(r'^M', case_name, re.IGNORECASE))
        has_alpha = bool(re.search(r'_A', case_name, re.IGNORECASE))
        return has_mach and has_alpha
    
    @staticmethod
    def consolidate_results(
        root_directory: str,
        columns_to_extract: List[str],
        num_to_average: int,
        skip_list: Optional[List[str]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> Tuple[Optional[pd.DataFrame], List[str]]:
        """
        Consolidate results from multiple SU2 cases.
        
        Args:
            root_directory: Root directory containing case subdirectories
            columns_to_extract: List of column names to extract
            num_to_average: Number of final iterations to average
            skip_list: List of case names to skip
            log_callback: Optional callback for logging messages
            progress_callback: Optional callback for progress updates (0-50)
            
        Returns:
            Tuple of (summary DataFrame, warnings list)
        """
        if log_callback is None:
            log_callback = lambda x: print(x)
        
        all_results = []
        warnings = []
        history_files = []
        
        log_callback(f"Scanning: {root_directory}")
        
        # First pass: find all history files
        for dirpath, _, filenames in os.walk(root_directory):
            if 'history.csv' in filenames:
                history_files.append(dirpath)
        
        total_files = len(history_files)
        if total_files == 0:
            log_callback("No history.csv files found!")
            return None, warnings
        
        log_callback(f"Found {total_files} history files. Processing...")
        
        skip_set = set(skip_list) if skip_list else set()
        
        # Second pass: process files
        for idx, dirpath in enumerate(history_files):
            case_name = os.path.basename(dirpath)
            
            if progress_callback:
                progress_callback(int((idx / total_files) * 50))
            
            # Skip if in skip list
            if case_name in skip_set:
                log_callback(f"Skipping: {case_name}")
                continue
            
            # Check naming convention
            if not AeroSummary.is_valid_case_name(case_name):
                log_callback(f"Skipping (wrong format): {case_name}")
                continue
            
            try:
                # Load history file
                history_path = os.path.join(dirpath, 'history.csv')
                df = pd.read_csv(history_path, sep=r'\s*,\s*|\s+', engine='python')
                df.columns = df.columns.str.strip().str.replace('"', '')
                
                if df.empty:
                    log_callback(f"Empty file: {case_name}")
                    continue
                
                # Check convergence
                is_converged, conv_msg = AeroSummary.check_convergence(df, columns_to_extract)
                if not is_converged:
                    warning = f"{case_name}: {conv_msg}"
                    warnings.append(warning)
                    log_callback(f"⚠ {warning}")
                
                # Average last N iterations
                n_rows = min(num_to_average, len(df))
                averaged_data = df.tail(n_rows).mean(numeric_only=True)
                
                # Extract requested columns
                result = {'Case': case_name, 'Converged': is_converged}
                for col in columns_to_extract:
                    result[col] = averaged_data.get(col, 0.0)
                
                all_results.append(result)
                log_callback(f"✓ Processed: {case_name}")
                
            except Exception as e:
                error_msg = f"Error processing {case_name}: {e}"
                warnings.append(error_msg)
                log_callback(f"✗ {error_msg}")
        
        if not all_results:
            log_callback("No valid data found.")
            return None, warnings
        
        # Create summary dataframe
        summary_df = pd.DataFrame(all_results)
        
        # Extract Mach and Alpha from case names
        summary_df['Mach'] = summary_df['Case'].apply(
            AeroSummary.extract_mach_from_case_name
        )
        summary_df['Alpha'] = summary_df['Case'].apply(
            AeroSummary.extract_alpha_from_case_name
        )
        
        # Sort by Mach then Alpha
        summary_df = summary_df.sort_values(by=['Mach', 'Alpha']).reset_index(drop=True)
        
        log_callback(f"\n✓ Consolidated {len(all_results)} cases")
        if warnings:
            log_callback(f"⚠ {len(warnings)} warnings (see above)")
        
        return summary_df, warnings
    
    @staticmethod
    def save_summary(summary_df: pd.DataFrame, output_file: str, append: bool = False) -> bool:
        """
        Save summary dataframe to file.

        Args:
            summary_df: Summary dataframe to save
            output_file: Path to the output file
            append: If True, append to existing file (adding rows); if False, overwrite
        """
        try:
            if append and os.path.exists(output_file):
                existing_df = pd.read_csv(output_file, sep='\t')
                combined_df = pd.concat([existing_df, summary_df], ignore_index=True)
                # Remove exact duplicate rows if any
                combined_df = combined_df.drop_duplicates()
                combined_df.to_csv(output_file, sep='\t', index=False, float_format='%.8f')
            else:
                summary_df.to_csv(output_file, sep='\t', index=False, float_format='%.8f')
            return True
        except Exception as e:
            print(f"Error saving summary: {e}")
            return False
    
    @staticmethod
    def generate_plots(
        summary_df: pd.DataFrame,
        columns_to_plot: List[str],
        plot_directory: str,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> List[str]:
        """
        Generate plots of results vs Alpha for each Mach number.
        
        Args:
            summary_df: Summary dataframe
            columns_to_plot: Columns to plot
            plot_directory: Directory to save plots
            progress_callback: Optional callback for progress updates (50-100)
            
        Returns:
            List of generated plot file paths
        """
        os.makedirs(plot_directory, exist_ok=True)
        generated_files = []
        unique_mach_numbers = summary_df['Mach'].unique()
        
        total_plots = len(unique_mach_numbers) * len(columns_to_plot)
        current_plot = 0
        
        for mach in unique_mach_numbers:
            mach_data = summary_df[summary_df['Mach'] == mach].sort_values(by='Alpha')
            
            for col in columns_to_plot:
                # Skip if column not present or non-numeric
                if col not in mach_data.columns or mach_data[col].dtype == object:
                    continue
                
                # Create plot
                plt.figure(figsize=(10, 6))
                plt.plot(mach_data['Alpha'], mach_data[col], 
                        'o-', linewidth=2, markersize=8)
                plt.title(f'{col} vs. Alpha (Mach {mach})', fontweight='bold', fontsize=14)
                plt.xlabel('Angle of Attack (deg)', fontsize=12)
                plt.ylabel(col, fontsize=12)
                plt.grid(True, linestyle='--', alpha=0.7)
                
                # Add minor gridlines
                plt.minorticks_on()
                plt.grid(which='minor', linestyle=':', alpha=0.4)
                
                # Save plot
                mach_str = str(mach).replace('.', 'p')
                filepath = os.path.join(
                    plot_directory, 
                    f"M{mach_str}_{col}_vs_Alpha.png"
                )
                plt.savefig(filepath, bbox_inches='tight', dpi=150)
                plt.close()
                
                generated_files.append(filepath)
                
                current_plot += 1
                if progress_callback:
                    progress_val = 50 + int((current_plot / total_plots) * 50)
                    progress_callback(progress_val)
        
        return generated_files
    
    @staticmethod
    def get_available_columns(root_directory: str) -> List[str]:
        """Get available columns from first history file found."""
        for dirpath, _, filenames in os.walk(root_directory):
            if 'history.csv' in filenames:
                try:
                    history_path = Path(dirpath) / 'history.csv'
                    df = pd.read_csv(history_path, nrows=0, sep=r'\s*,\s*|\s+', engine='python')
                    cols = [c.strip().replace('"', '') for c in df.columns]
                    return sorted(cols)
                except:
                    pass
        return []
    
    @staticmethod
    def generate_output_filename(root_directory: str) -> str:
        """
        Generate output filename based on Mach numbers found in directory.
        
        Args:
            root_directory: Root directory containing cases
            
        Returns:
            Generated filename (e.g., 'summary_M0p8_M1p2.dat' or 'summary.dat')
        """
        mach_numbers = set()
        
        for dirpath, _, filenames in os.walk(root_directory):
            if 'history.csv' in filenames:
                case_name = os.path.basename(dirpath)
                mach = AeroSummary.extract_mach_from_case_name(case_name)
                if mach != 999.0:  # Valid Mach found
                    mach_numbers.add(mach)
        
        if not mach_numbers:
            return "summary.dat"
        
        # Sort and format Mach numbers
        sorted_machs = sorted(mach_numbers)
        mach_strings = [f"M{str(m).replace('.', 'p')}" for m in sorted_machs]
        
        return f"summary_{'_'.join(mach_strings)}.dat"
    
    @staticmethod
    def generate_plots_from_file(
        summary_file: str,
        columns_to_plot: List[str],
        plot_directory: str,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> List[str]:
        """
        Generate plots from an existing summary file.
        
        Args:
            summary_file: Path to existing summary .dat file
            columns_to_plot: Columns to plot
            plot_directory: Directory to save plots
            progress_callback: Optional callback for progress updates
            
        Returns:
            List of generated plot file paths
        """
        try:
            # Read the summary file
            summary_df = pd.read_csv(summary_file, sep='\t')
            
            # Check if required columns exist
            if 'Mach' not in summary_df.columns or 'Alpha' not in summary_df.columns:
                print("Summary file must contain 'Mach' and 'Alpha' columns")
                return []
            
            # Generate plots
            return AeroSummary.generate_plots(
                summary_df,
                columns_to_plot,
                plot_directory,
                progress_callback
            )
        except Exception as e:
            print(f"Error generating plots from file: {e}")
            return []
    
    @staticmethod
    def get_case_directories(root_directory: str) -> List[str]:
        """Get list of case directories containing history files."""
        case_dirs = []
        for dirpath, _, filenames in os.walk(root_directory):
            if 'history.csv' in filenames:
                case_dirs.append(os.path.basename(dirpath))
        return sorted(case_dirs)

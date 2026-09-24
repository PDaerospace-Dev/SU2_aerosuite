"""
AeroSummary - SU2 Results Consolidation and Analysis.

Provides functionality for consolidating multiple SU2 history files and generating plots.
"""

import os
from typing import List, Dict, Tuple, Optional, Callable
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

from aerosuite.engine import results as engine_results
from aerosuite.engine.naming import parse_case_name


class AeroSummary:
    """Consolidate and analyze SU2 results from multiple cases."""
    
    @staticmethod
    def check_convergence(df: pd.DataFrame, columns: List[str]) -> Tuple[bool, str]:
        """Convergence of whichever of CD/CL/CMy the user selected, else of all three (engine rule)."""
        selected = [c for c in ('CD', 'CL', 'CMy') if c in columns]
        return engine_results.check_convergence(
            df, selected or engine_results.DEFAULT_CONVERGENCE_COLUMNS
        )

    @staticmethod
    def extract_mach_from_case_name(case_name: str) -> float:
        """Mach from a case directory name; 999.0 when absent."""
        mach = parse_case_name(case_name).mach
        return 999.0 if mach is None else mach

    @staticmethod
    def extract_alpha_from_case_name(case_name: str) -> float:
        """Angle of attack from a case directory name; 999.0 when absent."""
        alpha = parse_case_name(case_name).alpha
        return 999.0 if alpha is None else alpha

    @staticmethod
    def extract_beta_from_case_name(case_name: str) -> float:
        """Sideslip from a case directory name; 0.0 when the name has no beta token."""
        beta = parse_case_name(case_name).beta
        return 0.0 if beta is None else beta

    @staticmethod
    def is_valid_case_name(case_name: str) -> bool:
        """A case is usable when its name carries an angle of attack."""
        return parse_case_name(case_name).alpha is not None

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
                df = engine_results.read_history(history_path)

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
        
        # Sort by Mach, then Beta, then Alpha
        summary_df['Beta'] = summary_df['Case'].apply(
            AeroSummary.extract_beta_from_case_name
        )
        summary_df = summary_df.sort_values(by=['Mach', 'Beta', 'Alpha']).reset_index(drop=True)
        
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
        Plot each column vs Alpha, one figure per Mach (and per Beta when the
        summary holds more than one Beta).

        Returns:
            List of generated plot file paths
        """
        os.makedirs(plot_directory, exist_ok=True)
        generated_files = []
        split_beta = 'Beta' in summary_df.columns and summary_df['Beta'].nunique() > 1
        group_keys = ['Mach', 'Beta'] if split_beta else ['Mach']
        groups = list(summary_df.groupby(group_keys))

        total_plots = max(1, len(groups) * len(columns_to_plot))
        current_plot = 0

        for key, group in groups:
            key = key if isinstance(key, tuple) else (key,)
            mach = key[0]
            beta = key[1] if split_beta else None
            data = group.sort_values(by='Alpha')

            for col in columns_to_plot:
                if col not in data.columns or data[col].dtype == object:
                    continue

                plt.figure(figsize=(10, 6))
                plt.plot(data['Alpha'], data[col], 'o-', linewidth=2, markersize=8)
                title = f'{col} vs. Alpha (Mach {mach}'
                title += f', Beta {beta})' if split_beta else ')'
                plt.title(title, fontweight='bold', fontsize=14)
                plt.xlabel('Angle of Attack (deg)', fontsize=12)
                plt.ylabel(col, fontsize=12)
                plt.grid(True, linestyle='--', alpha=0.7)
                plt.minorticks_on()
                plt.grid(which='minor', linestyle=':', alpha=0.4)

                name = f"M{str(mach).replace('.', 'p')}"
                if split_beta:
                    name += f"_B{str(float(beta)).replace('-', 'n').replace('.', 'p')}"
                filepath = os.path.join(plot_directory, f"{name}_{col}_vs_Alpha.png")
                plt.savefig(filepath, bbox_inches='tight', dpi=150)
                plt.close()

                generated_files.append(filepath)

                current_plot += 1
                if progress_callback:
                    progress_callback(50 + int((current_plot / total_plots) * 50))

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

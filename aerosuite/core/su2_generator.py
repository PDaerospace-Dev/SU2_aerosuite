"""
SU2 Configuration File Generator.

Provides functionality for generating batch SU2 configuration files with
various parameter combinations.
"""

import re
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class GenerationConfig:
    """Configuration for batch file generation."""
    mach_values: List[float]
    alpha_values: List[float]
    beta_values: List[float]
    include_mach: bool
    include_alpha: bool
    include_beta: bool
    include_altitude: bool
    include_base: bool
    altitude: str
    base_name: str
    output_dir: Path
    template_path: Path
    
    def get_total_cases(self) -> int:
        """Calculate total number of cases to generate."""
        return len(self.mach_values) * len(self.alpha_values) * len(self.beta_values)


class SU2Generator:
    """Generator for SU2 configuration files."""
    
    @staticmethod
    def format_mach(mach: float) -> str:
        """
        Format Mach number for filename.
        
        Args:
            mach: Mach number
            
        Returns:
            Formatted Mach string (e.g., 'M1p5' for 1.5)
        """
        if mach >= 1:
            return f"M{int(mach)}p{int(round((mach - int(mach)) * 10))}"
        else:
            return f"M0p{int(round(mach * 10))}"
    
    @staticmethod
    def format_angle(angle: float) -> str:
        """
        Format angle for filename.
        
        Args:
            angle: Angle in degrees
            
        Returns:
            Formatted angle string (e.g., 'n5' for -5, '10' for 10)
        """
        return f"n{abs(round(angle))}" if angle < 0 else f"{round(angle)}"
    
    @staticmethod
    def generate_filename(
        mach: float,
        alpha: float,
        beta: float,
        altitude: str,
        base_name: str,
        include_mach: bool,
        include_alpha: bool,
        include_beta: bool,
        include_altitude: bool,
        include_base: bool
    ) -> str:
        """
        Generate a filename for a specific case.
        
        Args:
            mach: Mach number
            alpha: Angle of attack
            beta: Sideslip angle
            altitude: Altitude string (e.g., '10km')
            base_name: Base name for the file
            include_mach: Include Mach in filename
            include_alpha: Include alpha in filename
            include_beta: Include beta in filename
            include_altitude: Include altitude in filename
            include_base: Include base name in filename
            
        Returns:
            Generated filename
        """
        parts = []
        
        if include_mach:
            parts.append(SU2Generator.format_mach(mach))
        if include_altitude:
            parts.append(altitude.lower())
        if include_alpha:
            parts.append(f"a{SU2Generator.format_angle(alpha)}")
        if include_beta:
            parts.append(f"b{SU2Generator.format_angle(beta)}")
        if include_base and base_name:
            parts.append(base_name.lower())
        
        return "_".join(parts) + ".cfg"
    
    @staticmethod
    def generate_all_filenames(config: GenerationConfig) -> List[str]:
        """
        Generate all filenames for a batch configuration.
        
        Args:
            config: Generation configuration
            
        Returns:
            List of filenames
        """
        filenames = []
        for m in config.mach_values:
            for a in config.alpha_values:
                for b in config.beta_values:
                    fname = SU2Generator.generate_filename(
                        m, a, b,
                        config.altitude,
                        config.base_name,
                        config.include_mach,
                        config.include_alpha,
                        config.include_beta,
                        config.include_altitude,
                        config.include_base
                    )
                    filenames.append(fname)
        return filenames
    
    @staticmethod
    def validate_config(config: GenerationConfig) -> Tuple[bool, str]:
        """
        Validate generation configuration.
        
        Args:
            config: Configuration to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not config.template_path.exists():
            return False, "Template file does not exist"
        
        conflicts = []
        if len(config.mach_values) > 1 and not config.include_mach:
            conflicts.append("Mach Numbers")
        if len(config.alpha_values) > 1 and not config.include_alpha:
            conflicts.append("Alpha Values")
        if len(config.beta_values) > 1 and not config.include_beta:
            conflicts.append("Beta Values")
        
        if conflicts:
            msg = (
                f"You have multiple values for {', '.join(conflicts)} "
                "but haven't checked 'Inc. in Name'. Files will overwrite.\n\n"
                "Please check the naming boxes."
            )
            return False, msg
        
        if not any([
            config.include_base, config.include_mach,
            config.include_altitude, config.include_alpha,
            config.include_beta
        ]):
            return False, "At least one naming component must be checked"
        
        return True, ""
    
    # Sentinel value: pass this as a parameter value to remove the line entirely
    REMOVE_LINE = "__REMOVE_LINE__"

    @staticmethod
    def update_template_content(
        content: str,
        parameters: Dict[str, str]
    ) -> str:
        """
        Update template content with case-specific parameters.

        Rules
        ─────
        • If a key exists in the template  → the whole line is replaced with
          ``KEY= value``.
        • If a key does NOT exist in the template → the line is appended at the
          end so custom / extra parameters are always written.
        • If the value is ``SU2Generator.REMOVE_LINE`` → the matching line is
          deleted entirely (used for disabled marker checkboxes).

        Args:
            content: Template content string
            parameters: Dict of SU2 parameter key → value

        Returns:
            Updated content string
        """
        appended: List[str] = []   # keys to append at end (not found in template)

        for key, val in parameters.items():
            pattern = rf"^{re.escape(key)}\s*=\s*.*$"

            if val == SU2Generator.REMOVE_LINE:
                # Delete the line (and its trailing newline) if present
                content = re.sub(pattern + r"\n?", "", content, flags=re.MULTILINE)
                continue

            if re.search(pattern, content, flags=re.MULTILINE):
                # Key exists — replace in place
                content = re.sub(
                    pattern,
                    f"{key}= {val}",
                    content,
                    flags=re.MULTILINE
                )
            else:
                # Key absent from template — queue for append
                appended.append(f"{key}= {val}")

        if appended:
            # Add a blank separator line before appended block if needed
            if content and not content.endswith("\n\n"):
                content = content.rstrip("\n") + "\n\n"
            content += "\n".join(appended) + "\n"

        return content
    
    @staticmethod
    def extract_mesh_markers(mesh_path: Path) -> List[str]:
        """
        Extract boundary markers from SU2 mesh file.
        
        Args:
            mesh_path: Path to mesh file
            
        Returns:
            List of marker tags
        """
        markers = []
        try:
            with open(mesh_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith("MARKER_TAG="):
                        markers.append(line.split("=")[1].strip())
        except (FileNotFoundError, IOError) as e:
            print(f"Error reading mesh file: {e}")
        
        return markers
    
    @staticmethod
    def create_batch_file(
        output_dir: Path,
        files: List[str],
        restart_option: str,
        custom_path: Path = None
    ) -> bool:
        """
        Create batch control file for sequential runs.
        
        Args:
            output_dir: Output directory
            files: List of configuration filenames
            restart_option: Restart option ('none', 'previous', 'custom')
            custom_path: Custom restart path (for 'custom' option)
            
        Returns:
            True if successful, False otherwise
        """
        batch_path = output_dir / "run_control.txt"
        
        try:
            with open(batch_path, 'w', encoding='utf-8') as f:
                for i, cfg in enumerate(files):
                    if restart_option == 'none':
                        f.write(f"{cfg}, none\n")
                    elif restart_option == 'previous':
                        if i == 0:
                            f.write(f"{cfg}, none\n")
                        else:
                            f.write(f"{cfg}, previous\n")
                    elif restart_option == 'custom' and custom_path:
                        cfg_stem = Path(cfg).stem
                        restart_path = custom_path / cfg_stem / "restart_flow.dat"
                        f.write(f"{cfg}, custom, {restart_path}\n")
            return True
        except IOError as e:
            print(f"Error creating batch file: {e}")
            return False

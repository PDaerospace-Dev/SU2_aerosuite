"""
SU2 Configuration File Generator (legacy API).

Naming and template substitution now delegate to aerosuite.engine so the
legacy pages and the new engine can never disagree.
"""

from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass

from aerosuite.engine.cfg import apply_parameters, extract_markers
from aerosuite.engine.errors import ProjectError
from aerosuite.engine.naming import angle_token, case_name, find_collisions, mach_token


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
        """Mach token for filenames, e.g. 'M0p85' for 0.85, 'M1p0' for 1.0."""
        return mach_token(mach)

    @staticmethod
    def format_angle(angle: float) -> str:
        """Angle token for filenames, e.g. 'n5' for -5, '2p5' for 2.5."""
        return angle_token(angle)

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
        """Filename (with .cfg) for one case."""
        return case_name(
            mach, alpha, beta,
            altitude=altitude, base_name=base_name,
            include_mach=include_mach, include_alpha=include_alpha,
            include_beta=include_beta, include_altitude=include_altitude,
            include_base=include_base,
        ) + ".cfg"

    @staticmethod
    def generate_all_filenames(config: GenerationConfig) -> List[str]:
        """Filenames for every Mach x alpha x beta combination, in generation order."""
        return [
            SU2Generator.generate_filename(
                m, a, b, config.altitude, config.base_name,
                config.include_mach, config.include_alpha, config.include_beta,
                config.include_altitude, config.include_base,
            )
            for m in config.mach_values
            for a in config.alpha_values
            for b in config.beta_values
        ]

    @staticmethod
    def validate_config(config: GenerationConfig) -> Tuple[bool, str]:
        """Return (is_valid, error_message)."""
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

        duplicates = find_collisions(SU2Generator.generate_all_filenames(config))
        if duplicates:
            return False, (
                "These files would be generated more than once and overwrite each other "
                "(check for repeated values):\n  " + "\n  ".join(duplicates)
            )

        return True, ""

    # Sentinel value: pass this as a parameter value to remove the line entirely
    REMOVE_LINE = "__REMOVE_LINE__"

    @staticmethod
    def update_template_content(content: str, parameters: Dict[str, str]) -> str:
        """Replace existing KEY= lines, append missing keys, delete REMOVE_LINE keys."""
        return apply_parameters(content, {
            key: (None if value == SU2Generator.REMOVE_LINE else value)
            for key, value in parameters.items()
        })

    @staticmethod
    def extract_mesh_markers(mesh_path: Path) -> List[str]:
        """Boundary marker tags of an .su2 mesh; [] if the file cannot be read."""
        try:
            return extract_markers(mesh_path)
        except ProjectError as e:
            print(f"Error reading mesh file: {e}")
            return []

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

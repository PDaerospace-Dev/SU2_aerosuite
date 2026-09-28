#!/usr/bin/env python
 
## \file aoa_sweep_v4.py
#  \brief Python script for running an SU2 sweep with run order control file.
#  \author Modified version
#  \version 4.0 (Added run control file support)
 
# Standard library imports
import os
import sys
import shutil
import re
from optparse import OptionParser
 
# Add SU2 python scripts to the path
sys.path.append(os.environ["SU2_RUN"])
import SU2
 
def parse_run_control_file(control_file_path):
    """
    Parse the run control file to get execution order and restart settings.
    
    Expected format (one case per line):
    config_filename.cfg, restart_option, [restart_file_path_or_case_reference]
    
    restart_option can be:
    - 'none': No restart, run from scratch
    - 'initial': Use the initial restart file provided via -r option
    - 'previous': Use restart file from previous run
    - 'custom': Use a custom restart file (path must be provided)
    - 'from_case': Use restart file from a specific case (case config filename must be provided)
    
    Example:
    wing_A0.cfg, initial, my_restart.dat
    wing_A5.cfg, previous
    wing_A10.cfg, none
    wing_A15.cfg, custom, /path/to/custom_restart.dat
    wing_A20.cfg, from_case, wing_A0.cfg
    """
    run_list = []
    
    with open(control_file_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            parts = [p.strip() for p in line.split(',')]
            
            if len(parts) < 2:
                print(f"WARNING: Line {line_num} has insufficient fields, skipping: {line}")
                continue
            
            cfg_file = parts[0]
            restart_option = parts[1].lower()
            restart_reference = parts[2] if len(parts) > 2 else None
            
            # Validate restart_option
            valid_options = ['none', 'initial', 'previous', 'custom', 'from_case']
            if restart_option not in valid_options:
                print(f"WARNING: Line {line_num} has invalid restart option '{restart_option}', skipping.")
                print(f"         Valid options: {', '.join(valid_options)}")
                continue
            
            # Check if restart reference is provided when needed
            if restart_option in ['custom', 'from_case'] and not restart_reference:
                print(f"WARNING: Line {line_num} specifies '{restart_option}' but no reference provided, skipping.")
                continue
            
            run_list.append({
                'cfg_file': cfg_file,
                'restart_option': restart_option,
                'restart_reference': restart_reference
            })
    
    return run_list

def get_iteration_count(folder_name, conv_filename):
    """
    Extract the iteration count from the convergence history file.
    
    Args:
        folder_name: Output folder path
        conv_filename: Convergence filename from config
    
    Returns:
        Iteration count as integer or 'N/A' if not found
    """
    try:
        # The convergence file should be in the output folder
        # Try common naming patterns
        possible_files = [
            conv_filename,  # Full path already set by sendOutputFiles
            os.path.join(folder_name, 'history.csv'),
            os.path.join(folder_name, 'history.dat'),
        ]
        
        history_file = None
        for filepath in possible_files:
            if os.path.isfile(filepath):
                history_file = filepath
                break
        
        if not history_file:
            return 'N/A'
        
        # Read the history file and count lines (excluding header)
        with open(history_file, 'r') as f:
            lines = f.readlines()
        
        # Filter out empty lines and comments
        data_lines = [line for line in lines if line.strip() and not line.strip().startswith('#')]
        
        if len(data_lines) <= 1:  # Only header or empty
            return 'N/A'
        
        # Number of iterations = number of data lines (excluding header)
        iterations = len(data_lines) - 1
        
        return iterations
        
    except Exception as e:
        print(f"    WARNING: Could not read iteration count from history file: {str(e)}")
        return 'N/A'

def ensure_nzones(config):
    """
    Ensure NZONES = 1 is set in the config if not already present.
    """
    if not hasattr(config, 'NZONES') or config.NZONES is None:
        print("  --> NZONES not found in config, adding NZONES = 1")
        config.NZONES = 1
    else:
        print(f"  --> NZONES already set to {config.NZONES}")

def main():
    """
    Main function to parse arguments and run the SU2 sweep.
    """
    parser = OptionParser()
    parser.add_option(
        "-d",
        "--directory",
        dest="cfg_dir",
        help="Directory with AoA config files (*.cfg)",
        metavar="DIR",
    )
    parser.add_option(
        "-n",
        "--partitions",
        dest="partitions",
        default=1,
        help="Number of PARTITIONS for the simulation",
        metavar="PARTITIONS",
    )
    parser.add_option(
        "-r",
        "--restart_file",
        dest="initial_restart",
        default=None,
        help="Initial RESTART file to be used when 'initial' option is specified",
        metavar="FILE"
    )
    parser.add_option(
        "-c",
        "--control_file",
        dest="control_file",
        help="Path to run control file specifying execution order and restart options",
        metavar="FILE"
    )
 
    (options, args) = parser.parse_args()
    options.partitions = int(options.partitions)
    
    # Check for required arguments
    if not options.cfg_dir:
        parser.error("Directory with config files (-d) is required")
    
    if not options.control_file:
        parser.error("Run control file (-c) is required")
    
    if not os.path.isfile(options.control_file):
        print(f"ERROR: Control file not found: {options.control_file}")
        sys.exit(1)
    
    # Parse the run control file
    print(f"\n=== Parsing run control file: {options.control_file} ===")
    run_list = parse_run_control_file(options.control_file)
    
    if not run_list:
        print("ERROR: No valid cases found in control file.")
        sys.exit(1)
    
    # Verify all config files exist
    print("\n=== Verifying configuration files ===")
    for item in run_list:
        cfg_path = os.path.join(options.cfg_dir, item['cfg_file'])
        if not os.path.isfile(cfg_path):
            print(f"ERROR: Config file not found: {cfg_path}")
            sys.exit(1)
        print(f"  ✓ Found: {item['cfg_file']}")
    
    # --- Verification Printout ---
    print("\n" + "="*70)
    print("=== EXECUTION PLAN ===")
    print("="*70)
    print(f"{'#':<4} {'Config File':<30} {'Restart Option':<15} {'Restart Source'}")
    print("-"*70)
    
    for i, item in enumerate(run_list, 1):
        restart_source = ""
        if item['restart_option'] == 'none':
            restart_source = "From scratch"
        elif item['restart_option'] == 'initial':
            restart_source = f"Initial: {options.initial_restart if options.initial_restart else 'NOT PROVIDED!'}"
        elif item['restart_option'] == 'previous':
            restart_source = "Previous run" if i > 1 else "No previous (will run from scratch)"
        elif item['restart_option'] == 'custom':
            restart_source = f"Custom: {item['restart_reference']}"
        elif item['restart_option'] == 'from_case':
            restart_source = f"From case: {item['restart_reference']}"
        
        print(f"{i:<4} {item['cfg_file']:<30} {item['restart_option']:<15} {restart_source}")
    
    print("="*70 + "\n")
    
    # Confirm execution
    response = input("Proceed with this execution plan? (yes/no): ").strip().lower()
    if response not in ['yes', 'y']:
        print("Execution cancelled by user.")
        sys.exit(0)
    
    # --- Initialization for Restart ---
    previous_restart_file = None
    
    # --- Track execution results and restart files by case ---
    execution_results = []
    case_restart_files = {}  # Dictionary to store restart files by config filename
    
    # --- Main Loop for Sweep ---
    for i, item in enumerate(run_list, 1):
        cfg_file = item['cfg_file']
        restart_option = item['restart_option']
        restart_reference = item['restart_reference']
        
        print(f"\n\n{'='*70}")
        print(f"=== Running Case {i}/{len(run_list)}: {cfg_file} ===")
        print(f"{'='*70}\n")
 
        cfg_path = os.path.join(options.cfg_dir, cfg_file)
 
        config = SU2.io.Config(cfg_path)
        
        # Ensure NZONES = 1 BEFORE calling state.find_files()
        ensure_nzones(config)
        
        state = SU2.io.State()
        state.find_files(config)
        config.NUMBER_PART = options.partitions
        
        # Determine which restart file to use based on restart_option
        use_restart_file = None
        
        if restart_option == 'none':
            print("--> Restart option: NONE - Starting from scratch\n")
            use_restart_file = None
            
        elif restart_option == 'initial':
            if options.initial_restart:
                print(f"--> Restart option: INITIAL - Using: {options.initial_restart}\n")
                use_restart_file = options.initial_restart
            else:
                print("WARNING: 'initial' restart requested but no initial restart file provided (-r option)")
                print("--> Starting from scratch instead\n")
                use_restart_file = None
                
        elif restart_option == 'previous':
            if previous_restart_file:
                print(f"--> Restart option: PREVIOUS - Using: {previous_restart_file}\n")
                use_restart_file = previous_restart_file
            else:
                print("WARNING: 'previous' restart requested but no previous run available")
                print("--> Starting from scratch instead\n")
                use_restart_file = None
                
        elif restart_option == 'custom':
            if restart_reference and os.path.isfile(restart_reference):
                print(f"--> Restart option: CUSTOM - Using: {restart_reference}\n")
                use_restart_file = restart_reference
            else:
                print(f"WARNING: Custom restart file not found: {restart_reference}")
                print("--> Starting from scratch instead\n")
                use_restart_file = None
        
        elif restart_option == 'from_case':
            # Look up the restart file from the specified case
            if restart_reference in case_restart_files:
                use_restart_file = case_restart_files[restart_reference]
                print(f"--> Restart option: FROM_CASE - Using restart from '{restart_reference}': {use_restart_file}\n")
            else:
                print(f"WARNING: Case '{restart_reference}' has not been run yet or failed")
                print("--> Starting from scratch instead\n")
                use_restart_file = None
        
        # Apply restart file if available and RESTART_SOL is YES
        if use_restart_file and config.get('RESTART_SOL', 'NO').upper() == 'YES':
            config.SOLUTION_FILENAME = use_restart_file
        elif use_restart_file and config.get('RESTART_SOL', 'NO').upper() != 'YES':
            print(f"NOTE: Restart file specified but RESTART_SOL is not YES in {cfg_file}")
            print("      To enable restart, set RESTART_SOL = YES in the config file\n")
        elif not use_restart_file:
            # Starting from scratch: with RESTART_SOL = YES left in the config, SU2 would try to
            # open its default solution file and fail (e.g. after the previous case failed)
            config.RESTART_SOL = 'NO'
 
        # Set up output directory for the current case
        folderName = os.path.splitext(cfg_file)[0] + "/"
        if os.path.isdir(folderName):
            shutil.rmtree(folderName)
        os.mkdir(folderName)
        sendOutputFiles(config, folderName)
        shutil.copy(cfg_path, folderName)
 
        # Run the simulation
        try:
            info = SU2.run.CFD(config)
            state.update(info)
            # On success, store the path of the generated restart file for potential next run
            previous_restart_file = config.RESTART_FILENAME
            
            # Store restart file by config filename for from_case references
            case_restart_files[cfg_file] = config.RESTART_FILENAME
            
            # Extract iteration count from info - try multiple possible keys
            iterations = 'N/A'
            if isinstance(info, dict):
                # Try common iteration keys
                for key in ['ITERATIONS', 'OUTER_ITER', 'ITER', 'iterations', 'outer_iter']:
                    if key in info:
                        iterations = info[key]
                        break
            
            # If still N/A, try to read from history file or config
            if iterations == 'N/A':
                # Try getting from config (this would be the max iterations set)
                if hasattr(config, 'ITER'):
                    iterations = f"{config.ITER} (max)"
                elif hasattr(config, 'OUTER_ITER'):
                    iterations = f"{config.OUTER_ITER} (max)"
            
            print(f"\n--> Run successful. Restart file saved: {previous_restart_file}")
            print(f"--> Iterations completed: {iterations}")
            
            # Debug: print info dictionary structure (remove this later if needed)
            if iterations == 'N/A':
                print(f"DEBUG: info type = {type(info)}")
                if isinstance(info, dict):
                    print(f"DEBUG: info keys = {list(info.keys())}")
            
            # Record success
            execution_results.append({
                'case_num': i,
                'cfg_file': cfg_file,
                'status': 'SUCCESS',
                'restart_used': use_restart_file if use_restart_file else 'None',
                'restart_generated': previous_restart_file,
                'iterations': iterations,
                'error': None
            })
 
        except Exception as e:
            print(f"\nERROR: Simulation for {cfg_file} failed: {str(e)}")
            with open(os.path.join(folderName, "error.log"), "w") as f:
                f.write(f"Failed to run {cfg_file}:\n{str(e)}\n")
            # On failure, clear previous restart to prevent using failed solution
            previous_restart_file = None
            # Do NOT add to case_restart_files since this case failed
            
            # Record failure
            execution_results.append({
                'case_num': i,
                'cfg_file': cfg_file,
                'status': 'FAILED',
                'restart_used': use_restart_file if use_restart_file else 'None',
                'restart_generated': None,
                'iterations': 'N/A',
                'error': str(e)
            })
            
            print(f"--> Continuing to next case...\n")
            continue
    
    # --- Print Final Execution Summary ---
    print(f"\n\n{'='*80}")
    print("=== EXECUTION SUMMARY ===")
    print(f"{'='*80}")
    
    # Count successes and failures
    num_success = sum(1 for r in execution_results if r['status'] == 'SUCCESS')
    num_failed = sum(1 for r in execution_results if r['status'] == 'FAILED')
    
    print(f"\nTotal Cases: {len(execution_results)}")
    print(f"Successful:  {num_success}")
    print(f"Failed:      {num_failed}")
    
    print(f"\n{'-'*80}")
    print(f"{'#':<4} {'Config File':<30} {'Status':<10} {'Iters':<8} {'Restart Used':<20}")
    print(f"{'-'*80}")
    
    for result in execution_results:
        status_symbol = "✓" if result['status'] == 'SUCCESS' else "✗"
        restart_display = result['restart_used'] if result['restart_used'] != 'None' else 'From scratch'
        # Truncate long paths for display
        if len(restart_display) > 18:
            restart_display = "..." + restart_display[-15:]
        
        iter_display = str(result['iterations'])
        
        print(f"{result['case_num']:<4} {result['cfg_file']:<30} {status_symbol} {result['status']:<9} {iter_display:<8} {restart_display:<20}")
    
    # Print failed cases with error details
    if num_failed > 0:
        print(f"\n{'-'*80}")
        print("=== FAILED CASES DETAILS ===")
        print(f"{'-'*80}")
        for result in execution_results:
            if result['status'] == 'FAILED':
                print(f"\nCase #{result['case_num']}: {result['cfg_file']}")
                print(f"  Error: {result['error']}")
                print(f"  Log file: {os.path.splitext(result['cfg_file'])[0]}/error.log")
    
    print(f"\n{'='*80}")
    if num_failed == 0:
        print("=== ALL CASES COMPLETED SUCCESSFULLY ===")
    else:
        print(f"=== SWEEP COMPLETED WITH {num_failed} FAILURE(S) ===")
    print(f"{'='*80}\n")
 
def sendOutputFiles(config, folderName=""):
    """
    Prepends the output folder path to all output filenames in the config.
    """
    config.CONV_FILENAME = os.path.join(folderName, config.CONV_FILENAME)
    config.RESTART_FILENAME = os.path.join(folderName, config.RESTART_FILENAME)
    config.VOLUME_FILENAME = os.path.join(folderName, config.VOLUME_FILENAME)
    config.SURFACE_FILENAME = os.path.join(folderName, config.SURFACE_FILENAME)
 
if __name__ == "__main__":
    main()

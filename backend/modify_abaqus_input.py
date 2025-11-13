#!/usr/bin/env python3
"""
Script to modify Abaqus input file:
1. Scale node dimensions by a given factor
2. Calculate and update displacement based on strain formula
   strain = displacement / original_length
   displacement = strain × original_length
"""

import re
import sys


def modify_abaqus_file(input_file, output_file, scale_factor=1.0, strain=0.0):
    """
    Modify Abaqus input file with scaled dimensions and calculated displacement.
    
    Parameters:
    -----------
    input_file : str
        Path to input .inp file
    output_file : str
        Path to output modified .inp file
    scale_factor : float
        Factor to scale all node coordinates (default: 1.0, no scaling)
    strain : float
        Strain value to calculate displacement (negative for compression)
    """
    
    with open(input_file, 'r') as f:
        lines = f.readlines()
    
    modified_lines = []
    in_node_section = False
    original_length = None
    
    for line in lines:
        # Check if we're entering the *Node section
        if line.strip().startswith('*Node'):
            in_node_section = True
            modified_lines.append(line)
            continue
        
        # Check if we're leaving the *Node section
        if in_node_section and line.strip().startswith('*'):
            in_node_section = False
        
        # Modify node coordinates if in *Node section
        if in_node_section and not line.strip().startswith('*'):
            # Parse node line: node_id, x, y, z
            parts = line.strip().split(',')
            if len(parts) >= 4:
                try:
                    node_id = parts[0].strip()
                    x = float(parts[1].strip()) * scale_factor
                    y = float(parts[2].strip()) * scale_factor
                    z = float(parts[3].strip()) * scale_factor
                    
                    # Track the maximum Z coordinate to find original length
                    if original_length is None or z > original_length:
                        original_length = z
                    
                    # Format coordinates using Abaqus syntax
                    def format_coord(value):
                        """Format coordinate preserving Abaqus syntax with proper alignment"""
                        if abs(value) < 1e-10:  # Essentially zero
                            return f"{'0.':>13}"
                        else:
                            # Format with up to 7 decimal places, remove trailing zeros
                            formatted = f"{value:.7f}".rstrip('0')
                            # Ensure it ends with decimal point or has decimal places
                            if '.' not in formatted:
                                formatted += '.'
                            elif formatted.endswith('.'):
                                pass  # Already ends with decimal point
                            return f"{formatted:>13}"
                    
                    # Format the modified line with proper Abaqus syntax and alignment
                    modified_line = f"{node_id:>7}, {format_coord(x)}, {format_coord(y)}, {format_coord(z)}\n"
                    modified_lines.append(modified_line)
                    continue
                except (ValueError, IndexError):
                    # If parsing fails, keep original line
                    pass
        
        # Modify boundary condition displacement if strain is specified
        if line.strip().startswith('loading, 3, 3,') and strain != 0.0:
            # Calculate displacement from strain
            # strain = displacement / original_length
            # For compression, strain is negative
            if original_length is not None:
                displacement = strain * original_length
                # Format with decimal point (Abaqus syntax: "value.")
                if displacement == int(displacement):
                    modified_line = f"loading, 3, 3, {int(displacement)}.\n"
                else:
                    modified_line = f"loading, 3, 3, {displacement}.\n"
                modified_lines.append(modified_line)
                print(f"✓ Original length (max Z): {original_length}")
                print(f"✓ Strain: {strain}")
                print(f"✓ Calculated displacement: {displacement}")
                continue
        
        # Keep all other lines unchanged
        modified_lines.append(line)
    
    # Write modified file
    with open(output_file, 'w') as f:
        f.writelines(modified_lines)
    
    print(f"\n✓ Modified file saved to: {output_file}")
    print(f"✓ Total lines processed: {len(lines)}")
    if scale_factor != 1.0:
        print(f"✓ Node coordinates scaled by factor: {scale_factor}")


def main():
    """Main function with command-line interface"""
    
    # Default values
    input_file = "Compression.inp"
    output_file = "Compression_modified.inp"
    scale_factor = 1.0
    strain = -0.3333  # Default: -50/150 = -0.3333 (compression)
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    if len(sys.argv) > 3:
        scale_factor = float(sys.argv[3])
    if len(sys.argv) > 4:
        strain = float(sys.argv[4])
    
    print("=" * 60)
    print("Abaqus Input File Modifier")
    print("=" * 60)
    print(f"Input file:    {input_file}")
    print(f"Output file:   {output_file}")
    print(f"Scale factor:  {scale_factor}")
    print(f"Strain value:  {strain}")
    print("=" * 60)
    
    try:
        modify_abaqus_file(input_file, output_file, scale_factor, strain)
        print("\n✓ SUCCESS: File modification completed!")
    except FileNotFoundError:
        print(f"\n✗ ERROR: Input file '{input_file}' not found!")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

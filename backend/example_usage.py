#!/usr/bin/env python3
"""
Example usage script for modifying Abaqus input files
"""

from modify_abaqus_input import modify_abaqus_file

# Example 1: Just modify displacement based on strain
# Original length is 150 (max Z coordinate)
# Current displacement is -50
# Current strain = -50 / 150 = -0.3333
print("Example 1: Modify displacement with strain = -0.2")
print("-" * 60)
modify_abaqus_file(
    input_file="Compression.inp",
    output_file="Compression_strain_0.2.inp",
    scale_factor=1.0,      # No scaling
    strain=-0.2            # 20% compression
)
print()

# Example 2: Modify displacement with different strain
print("Example 2: Modify displacement with strain = -0.4")
print("-" * 60)
modify_abaqus_file(
    input_file="Compression.inp",
    output_file="Compression_strain_0.4.inp",
    scale_factor=1.0,      # No scaling
    strain=-0.4            # 40% compression
)
print()

# Example 3: Scale dimensions by 2x and apply strain
print("Example 3: Scale dimensions by 2x with strain = -0.3")
print("-" * 60)
modify_abaqus_file(
    input_file="Compression.inp",
    output_file="Compression_scaled_2x_strain_0.3.inp",
    scale_factor=2.0,      # Scale all dimensions by 2
    strain=-0.3            # 30% compression
)
print()

# Example 4: Scale dimensions by 0.5x (shrink) and apply strain
print("Example 4: Scale dimensions by 0.5x with strain = -0.25")
print("-" * 60)
modify_abaqus_file(
    input_file="Compression.inp",
    output_file="Compression_scaled_0.5x_strain_0.25.inp",
    scale_factor=0.5,      # Scale all dimensions by 0.5
    strain=-0.25           # 25% compression
)
print()

print("=" * 60)
print("All examples completed!")
print("=" * 60)

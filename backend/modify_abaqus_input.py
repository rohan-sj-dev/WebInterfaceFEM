import sys
import csv


def modify_abaqus_file(input_file, output_file, scale_factor_d, scale_factor=1.0, strain=0.0, stress_strain_csv=None):
    with open(input_file, 'r') as f:
        lines = f.readlines()
    
    modified_lines = []
    in_node_section = False
    in_plastic_section = False
    original_length = None
    stress_strain_data = []
    
    # Load stress-strain data from CSV if provided
    if stress_strain_csv:
        with open(stress_strain_csv, 'r') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            for row in csv_reader:
                try:
                    # Clean the strain value by removing GLM artifacts like <|end_of_box|>
                    strain_str = str(row['Strain']).replace('<|end_of_box|>', '').strip()
                    stress_str = str(row['Stress']).replace('<|end_of_box|>', '').strip()
                    
                    stress = float(stress_str)
                    strain_val = float(strain_str)
                    stress_strain_data.append((stress, strain_val))
                except (ValueError, KeyError):
                    continue
    
    for line in lines:
        if line.strip().startswith('*Node'):
            in_node_section = True
            modified_lines.append(line)
            continue
        
        if line.strip().startswith('*Plastic'):
            in_plastic_section = True
            modified_lines.append(line)
            
            # If we have stress-strain data, replace the plastic section
            if stress_strain_data:
                for stress, strain_val in stress_strain_data:
                    # Format: stress, strain with proper spacing
                    modified_lines.append(f"{stress:g}, {strain_val:g}\n")
                # Skip original plastic data
                continue
            else:
                continue

        if in_node_section and line.strip().startswith('*'):
            in_node_section = False
        
        if in_plastic_section and line.strip().startswith('*'):
            in_plastic_section = False

        # Skip original plastic data lines if we're replacing them
        if in_plastic_section and stress_strain_data:
            continue

        if in_node_section and not line.strip().startswith('*'):
            parts = line.strip().split(',')
            if len(parts) >= 4:
                try:
                    node_id = parts[0].strip()
                    x = float(parts[1].strip()) * scale_factor_d
                    y = float(parts[2].strip()) * scale_factor_d
                    z = float(parts[3].strip()) * scale_factor
                    if original_length is None or z > original_length:
                        original_length = z

                    def format_coord(value):
                        if abs(value) < 1e-10:
                            return f"{'0.':>13}"
                        else:
                            formatted = f"{value:.7f}".rstrip('0')
                            if '.' not in formatted:
                                formatted += '.'
                            elif formatted.endswith('.'):
                                pass
                            return f"{formatted:>13}"
                    modified_line = f"{node_id:>7}, {format_coord(x)}, {format_coord(y)}, {format_coord(z)}\n"
                    modified_lines.append(modified_line)
                    continue
                except (ValueError, IndexError):
                    # If parsing fails, keep original line
                    pass
        

        if line.strip().startswith('loading, 3, 3,') and strain != 0.0:

            if original_length is not None:
                displacement = strain * original_length

                if displacement == int(displacement):
                    modified_line = f"loading, 3, 3, {int(displacement)}.\n"
                else:
                    modified_line = f"loading, 3, 3, {displacement}\n"
                modified_lines.append(modified_line)
                continue
        modified_lines.append(line)
    
    with open(output_file, 'w') as f:
        f.writelines(modified_lines)


def main():
    input_file = "Compression.inp"
    output_file = "Compression_modified.inp"
    scale_factor = 0.66
    scale_factor_d = 0.5
    strain = -0.18
    stress_strain_csv = None
    
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    if len(sys.argv) > 3:
        scale_factor = float(sys.argv[3])
    if len(sys.argv) > 4:
        strain = float(sys.argv[4])
    if len(sys.argv) > 5:
        stress_strain_csv = sys.argv[5]
    try:
        modify_abaqus_file(input_file, output_file, scale_factor_d, scale_factor, strain, stress_strain_csv)
        print("File modification completed")
    except Exception as e:
        print(f"Error: {str(e)}")


if __name__ == "__main__":
    main()

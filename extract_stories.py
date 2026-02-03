"""
EXTRACT STORIES FROM IDML

Helper script to extract the Stories folder from IDML zip files
and organize them for testing.

Usage:
    python extract_stories.py punch_20250112.idml
    python extract_stories.py punch_20250112.idml --output Stories/idml_punch_custom
"""

import zipfile
import os
import argparse
from pathlib import Path


def extract_stories_from_idml(idml_file: str, output_dir: str = None):
    """
    Extract Stories folder from IDML zip file
    
    Args:
        idml_file: Path to IDML file
        output_dir: Where to save extracted stories (auto-generated if None)
    """
    
    if not os.path.exists(idml_file):
        print(f"Error: File not found - {idml_file}")
        return False
    
    # Auto-generate output directory name
    if output_dir is None:
        base_name = Path(idml_file).stem
        output_dir = f"Stories/idml_{base_name}"
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Extracting stories from: {idml_file}")
    print(f"Saving to: {output_dir}\n")
    
    try:
        with zipfile.ZipFile(idml_file, 'r') as zip_ref:
            # List all files to find Stories
            all_files = zip_ref.namelist()
            story_files = [f for f in all_files if f.startswith('Stories/Story_')]
            
            print(f"Found {len(story_files)} story files\n")
            
            if not story_files:
                print("No Story files found in this IDML!")
                return False
            
            # Extract each story file
            for i, story_file in enumerate(story_files, 1):
                # Get just the filename
                filename = os.path.basename(story_file)
                output_path = os.path.join(output_dir, filename)
                
                # Extract
                with open(output_path, 'wb') as f:
                    f.write(zip_ref.read(story_file))
                
                print(f"  [{i}/{len(story_files)}] {filename}")
            
            print(f"\n✓ Successfully extracted {len(story_files)} stories")
            print(f"✓ Saved to: {output_dir}")
            
            # Show sample of extracted files
            extracted = os.listdir(output_dir)
            print(f"\nExtracted files:")
            for f in sorted(extracted)[:5]:
                print(f"  - {f}")
            if len(extracted) > 5:
                print(f"  ... and {len(extracted) - 5} more")
            
            return True
            
    except zipfile.BadZipFile:
        print(f"Error: Not a valid IDML/ZIP file - {idml_file}")
        return False
    except Exception as e:
        print(f"Error during extraction: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Extract Stories folder from IDML zip files"
    )
    parser.add_argument(
        "idml_file",
        help="Path to IDML file"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output directory (auto-generated if not specified)"
    )
    
    args = parser.parse_args()
    
    success = extract_stories_from_idml(args.idml_file, args.output)
    
    if not success:
        exit(1)


if __name__ == "__main__":
    main()

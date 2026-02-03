"""
TEST HARNESS for Native vs AI Parser Comparison

This script allows you to test both parsers on sample Stories XML files
and compare their output before using the API endpoints.

Usage:
    python test_parsers.py --folder Stories/idml_punch_20250112
    python test_parsers.py --file Stories/idml_punch_20250112/Story_u2899d.xml
    python test_parsers.py --compare  # Compare native vs AI on all files
"""

import os
import json
import argparse
from native_parser import IDMLNewsExtractor
from ai_parser import AINewsExtractor


def test_single_story(xml_file: str):
    """Test both parsers on a single XML story file"""
    print(f"\n{'='*80}")
    print(f"Testing: {xml_file}")
    print(f"{'='*80}\n")
    
    # Test native parser
    print("NATIVE PARSER OUTPUT:")
    print("-" * 80)
    
    try:
        extractor = IDMLNewsExtractor("dummy.idml")  # Dummy path, not used for XML
        result = extractor.extract_from_xml_file(xml_file)
        
        if result:
            print(f"Story ID: {result['story_id']}")
            print(f"Category: {result['category']}")
            print(f"Paragraphs: {len(result['paragraphs'])}")
            print(f"Content Elements: {len(result['content_elements'])}")
            print(f"\nRaw Content (first 200 chars):\n{result['raw_content'][:200]}...")
        else:
            print("Failed to parse")
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n" + "-" * 80)
    print("AI PARSER OUTPUT:")
    print("-" * 80)
    
    try:
        ai_extractor = AINewsExtractor("dummy.idml")
        result = ai_extractor.extract_from_xml_file(xml_file)
        
        if result:
            print(f"Story ID: {result['story_id']}")
            print(f"Category: {result['category']}")
            print(f"Paragraphs: {len(result['paragraphs'])}")
        else:
            print("AI parser not yet implemented")
    except Exception as e:
        print(f"Status: {e}")
    
    print("\n")


def test_folder(folder_path: str):
    """Test both parsers on all XML files in a folder"""
    print(f"\n{'='*80}")
    print(f"Testing Folder: {folder_path}")
    print(f"{'='*80}\n")
    
    if not os.path.isdir(folder_path):
        print(f"Folder not found: {folder_path}")
        return
    
    xml_files = [f for f in os.listdir(folder_path) if f.endswith('.xml')]
    print(f"Found {len(xml_files)} XML files\n")
    
    for i, xml_file in enumerate(xml_files[:3], 1):  # Test first 3
        full_path = os.path.join(folder_path, xml_file)
        test_single_story(full_path)
        
        if i >= 3:
            print(f"\n(Showing first 3 files. Total: {len(xml_files)})")
            break


def compare_parsers(stories_root: str = "Stories"):
    """Compare native vs AI parser on all available stories"""
    print(f"\n{'='*80}")
    print("NATIVE vs AI PARSER COMPARISON")
    print(f"{'='*80}\n")
    
    if not os.path.isdir(stories_root):
        print(f"Stories folder not found: {stories_root}")
        return
    
    results = {
        "native": {"success": 0, "failed": 0},
        "ai": {"success": 0, "failed": 0},
        "files_tested": 0
    }
    
    # Iterate through all IDML folders
    for idml_folder in sorted(os.listdir(stories_root)):
        folder_path = os.path.join(stories_root, idml_folder)
        
        if not os.path.isdir(folder_path) or idml_folder == "README.md":
            continue
        
        print(f"\nProcessing {idml_folder}:")
        print("-" * 80)
        
        xml_files = [f for f in os.listdir(folder_path) if f.endswith('.xml')]
        print(f"  Found {len(xml_files)} stories")
        
        for xml_file in xml_files[:2]:  # Test first 2 per folder
            full_path = os.path.join(folder_path, xml_file)
            results["files_tested"] += 1
            
            # Test native
            try:
                extractor = IDMLNewsExtractor("dummy.idml")
                result = extractor.extract_from_xml_file(full_path)
                if result:
                    results["native"]["success"] += 1
                    print(f"  ✓ Native: {xml_file}")
                else:
                    results["native"]["failed"] += 1
            except Exception as e:
                results["native"]["failed"] += 1
                print(f"  ✗ Native: {xml_file} - {str(e)[:40]}")
            
            # Test AI (stub - not implemented yet)
            try:
                ai_extractor = AINewsExtractor("dummy.idml")
                result = ai_extractor.extract_from_xml_file(full_path)
                if result:
                    results["ai"]["success"] += 1
                    print(f"  ✓ AI: {xml_file}")
                else:
                    results["ai"]["failed"] += 1
            except Exception as e:
                # AI not implemented yet
                pass
    
    print(f"\n{'='*80}")
    print("COMPARISON RESULTS:")
    print(f"{'='*80}")
    print(f"\nFiles tested: {results['files_tested']}")
    print(f"\nNative Parser:")
    print(f"  Success: {results['native']['success']}")
    print(f"  Failed: {results['native']['failed']}")
    print(f"\nAI Parser:")
    print(f"  Success: {results['ai']['success']}")
    print(f"  Failed: {results['ai']['failed']}")
    print(f"  Note: AI parser implementation pending\n")


def main():
    parser = argparse.ArgumentParser(
        description="Test IDML parsers on sample Stories"
    )
    parser.add_argument(
        "--file",
        help="Test single XML story file"
    )
    parser.add_argument(
        "--folder",
        help="Test all XML files in a folder"
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare native vs AI on all available stories"
    )
    
    args = parser.parse_args()
    
    if args.file:
        test_single_story(args.file)
    elif args.folder:
        test_folder(args.folder)
    elif args.compare:
        compare_parsers()
    else:
        print("Usage:")
        print("  python test_parsers.py --file <path/to/Story.xml>")
        print("  python test_parsers.py --folder <path/to/stories/folder>")
        print("  python test_parsers.py --compare")


if __name__ == "__main__":
    main()

import sys
import os

# Add root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.core.audio_manager import StudioOneEngine

def test_engine():
    print("Testing StudioOneEngine...")
    engine = StudioOneEngine()
    
    devs = engine.enumerate_devices()
    print(f"Enumerated {len(devs)} devices:")
    for d in devs:
        print(f"  - [{d['id']}] {d['name']}")
        
    struct = engine.get_structure()
    print(f"Structure returned: {struct}")
    assert struct['type'] == 'midi', "Type must be midi"
    assert 'status' in struct, "Status must be present"
    assert 'devices' in struct, "Devices list must be present"
    
    diag_path = engine.generate_midi_diagnostic()
    print(f"Diagnostic generated at: {diag_path}")
    assert os.path.exists(diag_path), "Diagnostic file must exist"
    
    with open(diag_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    print("Diagnostic content preview (first 10 lines):")
    print("-" * 40)
    for l in lines[:10]:
        print(l.strip())
    print("-" * 40)
    
    engine.cleanup()
    print("\n[OK] All self-checks PASSED successfully!")

if __name__ == "__main__":
    test_engine()

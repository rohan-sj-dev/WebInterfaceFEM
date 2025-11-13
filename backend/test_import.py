import traceback
import sys

try:
    import app
    print(f"✓ App imported successfully")
    print(f"Total routes: {len(list(app.app.url_map.iter_rules()))}")
    
    routes = [str(r) for r in app.app.url_map.iter_rules()]
    print("\nAll routes:")
    for r in sorted(routes):
        print(f"  {r}")
    
    searchable_routes = [r for r in routes if 'searchable' in r.lower()]
    print(f"\nSearchable routes: {searchable_routes}")
    
except Exception as e:
    print(f"✗ Error importing app:")
    traceback.print_exc()

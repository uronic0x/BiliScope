import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from biliscope.runtime import configure
configure()
from biliscope.provenance import save_inventory
save_inventory()

"""CI helper: write sitecustomize.py so src/ is on sys.path before entry points load."""
import site
import pathlib
import os

src = str(pathlib.Path(os.getcwd()) / "src")
sc = pathlib.Path(site.getsitepackages()[0]) / "sitecustomize.py"
sc.write_text(f"import sys\nif {src!r} not in sys.path:\n    sys.path.insert(0, {src!r})\n")
print(f"sitecustomize.py written: {sc}")
print(f"src path: {src}")

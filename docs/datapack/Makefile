# Data pack PDFs (ADD, SVS, ICD) from the site pages; see
# tools/build_datapack.py. Needs pandoc, xelatex and the eisvogel template
# (docs/datapack/eisvogel.latex if present, else pandoc's own). CI renders
# them with the pandoc/extra image and attaches them to each release.
REPO := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)

.PHONY: all md clean

all:
	python3 $(REPO)/tools/build_datapack.py

md:
	python3 $(REPO)/tools/build_datapack.py --md-only

clean:
	rm -rf $(REPO)/docs/datapack/out $(REPO)/build/datapack

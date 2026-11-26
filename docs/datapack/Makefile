TEMPLATE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))eisvogel.latex
PANDOC   := pandoc
FLAGS    := --template=$(TEMPLATE) --pdf-engine=xelatex --highlight-style=tango

# The ICD is the site page docs/icd.md (metadata in icd.meta.yaml); its PDF
# returns with the data pack build from the site sources.
DOCS     := add svs
PDFS     := $(addprefix out/, $(addsuffix .pdf, $(DOCS)))

.PHONY: all clean

all: out/ $(PDFS)

out/:
	mkdir -p out

out/%.pdf: %.md $(TEMPLATE) | out/
	$(PANDOC) $(FLAGS) -o $@ $<

clean:
	rm -rf out/

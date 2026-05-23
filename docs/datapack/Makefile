TEMPLATE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))eisvogel.latex
PANDOC   := pandoc
FLAGS    := --template=$(TEMPLATE) --pdf-engine=xelatex --highlight-style=tango

DOCS     := add icd svs
PDFS     := $(addprefix out/, $(addsuffix .pdf, $(DOCS)))

.PHONY: all clean

all: out/ $(PDFS)

out/:
	mkdir -p out

out/%.pdf: %.md $(TEMPLATE) | out/
	$(PANDOC) $(FLAGS) -o $@ $<

clean:
	rm -rf out/

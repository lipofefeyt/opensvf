
# YAMCS aliases
alias yamcs-start='bash $(pwd)/scripts/start-yamcs.sh'
alias yamcs-stop='bash $(pwd)/scripts/stop-yamcs.sh'
alias yamcs-log='curl -s http://localhost:8090/api/instances | python3 -m json.tool | grep -E "name|state"'
alias regen-xtce='python3 tools/generate_xtce.py > yamcs/mdb/opensvf.xml && echo "XTCE regenerated: $(wc -l < yamcs/mdb/opensvf.xml) lines"'

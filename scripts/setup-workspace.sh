# Opensvf aliases
alias testosvf='pytest tests/ --junitxml=results/junit.xml -v'
alias checkosvf='mypy src/ --config-file pyproject.toml'
alias checkcov='python3 scripts/check_coverage.py'

# YAMCS aliases
alias yamcs-start='bash $(pwd)/scripts/start-yamcs.sh'
alias yamcs-stop='bash $(pwd)/scripts/stop-yamcs.sh'
alias yamcs-log='curl -s http://localhost:8090/api/instances | python3 -m json.tool | grep -E "name|state"'
alias regen-xtce='python3 tools/generate_xtce.py > yamcs/mdb/opensvf.xml && echo "XTCE regenerated: $(wc -l < yamcs/mdb/opensvf.xml) lines"'

# Install YAMCS
curl -L https://github.com/yamcs/yamcs/releases/download/yamcs-5.12.6/yamcs-5.12.6-linux-x86_64.tar.gz -o /tmp/yamcs.tar.gz 2>&1 | tail -2
mkdir -p /tmp/yamcs
tar -xzf /tmp/yamcs.tar.gz -C /tmp/yamcs --strip-components=1
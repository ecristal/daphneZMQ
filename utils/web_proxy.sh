# This script is intended to be sourced.
# 14-Sep-2021, KAB: added switches for different proxies, and for un-set.

if [[ $# -gt 0 ]]; then
    if [[ "$1" == "-h" ]] || [[ "$1" == "-?" ]] || [[ "$1" == "--help" ]]; then
	echo ""
	echo "Usage: source $0 [--help|-h|-?] [-u] [-g] [-p]"
	echo "Where: -u indicates that all existing proxy env vars should be Unset"
	echo "       -p indicates that the np04-web-proxy proxy should be used"
	return
    fi

    if [[ "$1" == "-u" ]]; then
	unset HTTPS_PROXY
	unset HTTP_PROXY
	unset NO_PROXY
	unset https_proxy
	unset http_proxy
	unset no_proxy
	return
    fi

    if [[ "$1" == "-p" ]]; then
	export HTTP_PROXY=http://np04-web-proxy.cern.ch:3128
	export HTTPS_PROXY=http://np04-web-proxy.cern.ch:3128
	export NO_PROXY=".cern.ch"
	export http_proxy=http://np04-web-proxy.cern.ch:3128
	export https_proxy=http://np04-web-proxy.cern.ch:3128
	export no_proxy=".cern.ch"
	return
    fi
fi

export HTTP_PROXY=http://np04-web-proxy.cern.ch:3128
export HTTPS_PROXY=http://np04-web-proxy.cern.ch:3128
export NO_PROXY=".cern.ch"
export http_proxy=http://np04-web-proxy.cern.ch:3128
export https_proxy=http://np04-web-proxy.cern.ch:3128
export no_proxy=".cern.ch"

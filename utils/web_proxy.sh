# This script is intended to be sourced.
# 14-Sep-2021, KAB: added switches for different proxies, and for un-set.
# 24-Feb-2026: default now also writes git proxy config.

PROXY_URL="http://np04-web-proxy.cern.ch:3128"
NO_PROXY_VALUE=".cern.ch"

print_help() {
    echo ""
    echo "Usage: source $0 [--help|-h|-?] [-u] [-g] [-p]"
    echo "Where: -u indicates that all existing proxy env vars should be unset and git proxy removed"
    echo "       -g indicates that only git proxy settings should be written"
    echo "       -p indicates that the np04-web-proxy proxy should be used (env + git)"
}

set_proxy_env() {
    export HTTP_PROXY="$PROXY_URL"
    export HTTPS_PROXY="$PROXY_URL"
    export NO_PROXY="$NO_PROXY_VALUE"
    export http_proxy="$PROXY_URL"
    export https_proxy="$PROXY_URL"
    export no_proxy="$NO_PROXY_VALUE"
}

unset_proxy_env() {
    unset HTTPS_PROXY
    unset HTTP_PROXY
    unset NO_PROXY
    unset https_proxy
    unset http_proxy
    unset no_proxy
}

set_git_proxy() {
    if command -v git >/dev/null 2>&1; then
        git config --global http.proxy "$PROXY_URL" || true
        git config --global https.proxy "$PROXY_URL" || true
        git config --global http.noProxy "$NO_PROXY_VALUE" || true
    fi
}

unset_git_proxy() {
    if command -v git >/dev/null 2>&1; then
        git config --global --unset-all http.proxy 2>/dev/null || true
        git config --global --unset-all https.proxy 2>/dev/null || true
        git config --global --unset-all http.noProxy 2>/dev/null || true
    fi
}

if [ $# -gt 0 ]; then
    if [ "$1" = "-h" ] || [ "$1" = "-?" ] || [ "$1" = "--help" ]; then
        print_help
        return
    fi

    if [ "$1" = "-u" ]; then
        unset_proxy_env
        unset_git_proxy
        return
    fi

    if [ "$1" = "-g" ]; then
        set_git_proxy
        return
    fi

    if [ "$1" = "-p" ]; then
        set_proxy_env
        set_git_proxy
        return
    fi
fi

# Default behavior: enable proxy env vars and git proxy settings.
set_proxy_env
set_git_proxy

#!/usr/bin/env python
"""Development shim. Deployments call the `dnsrules` console script instead."""

from dnsrules.cli import main

if __name__ == "__main__":
    main()

"""Verified TLS using Windows trust anchors without cached CA intermediates."""
from __future__ import annotations

import ssl
import sys


def create_verified_tls_context():
    if sys.platform != 'win32':
        return ssl.create_default_context()
    # Python's default Windows loader also imports the CA (intermediate)
    # store. A stale cross-signed intermediate can then shadow the valid
    # version sent by a server because OpenSSL prefers locally stored issuers.
    # Trust only OS root anchors; build intermediate chains from the peer.
    purpose = ssl.Purpose.SERVER_AUTH.oid
    roots = [ssl.DER_cert_to_PEM_cert(cert)
             for cert, encoding, trust in ssl.enum_certificates('ROOT')
             if encoding == 'x509_asn' and (trust is True or purpose in trust)]
    if not roots:
        raise ssl.SSLError('No trusted Windows server-auth root certificates')
    context = ssl.create_default_context(cadata='\n'.join(roots))
    # Preserve OpenSSL's configured CA file/directory, including explicit
    # SSL_CERT_FILE / SSL_CERT_DIR, without loading Windows' CA cache.
    context.set_default_verify_paths()
    return context

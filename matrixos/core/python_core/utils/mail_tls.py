"""TLS context policy for MatrixOS mail transports."""

import ssl


def create_mail_tls_context():
    """Return a verified client context compatible with older mail PKI.

    Python 3.13 enables VERIFY_X509_STRICT in create_default_context().  Some
    otherwise trusted mail chains predate the strict RFC 5280 requirements.
    Clear only that compatibility flag while retaining certificate-chain
    validation, hostname verification, the system trust store, and modern TLS
    protocol defaults.
    """
    context = ssl.create_default_context()
    strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict_flag:
        context.verify_flags &= ~strict_flag
    return context

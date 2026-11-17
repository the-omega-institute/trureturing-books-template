"""tbook: build, verify and publish trureturing monographs.

Every theorem-like environment in a book must cite a Lean declaration that is
kernel-verified and frozen in trureturing (``Golden/Frozen/state``) at its evidence
commit recorded in ``trureturing-lock/``. This package checks that rule and renders the
books to HTML (mdBook), PDF (Typst) and EPUB (Apple Books).
"""

__version__ = "0.1.0"

"""
font_manager.py
───────────────
Responsive font scaling based on window width.
No GUI dependency — pure logic only.
"""


class FontManager:

    _BREAKPOINTS = [(1400, 11), (1100, 10), (900, 9)]
    _DEFAULT_SIZE = 8

    @classmethod
    def scale(cls, width: int) -> dict:
        """Return font tuples scaled to the current window width."""
        s = cls._DEFAULT_SIZE
        for min_w, size in cls._BREAKPOINTS:
            if width >= min_w:
                s = size
                break
        return {
            "title":   ("Segoe UI",  s + 7, "bold"),
            "mono":    ("Consolas",  s),
            "btn":     ("Segoe UI",  s,      "bold"),
            "table":   ("Segoe UI",  s - 1),
            "table_h": ("Segoe UI",  s - 1, "bold"),
            "badge":   ("Segoe UI",  s + 2, "bold"),
            "small":   ("Segoe UI",  max(s - 2, 6), "bold"),
            "tiny":    ("Segoe UI",  max(s - 2, 6)),
        }

    @classmethod
    def tier(cls, width: int) -> str:
        """Return a scale-tier string used to detect breakpoint crossings."""
        if   width >= 1400: return "xl"
        elif width >= 1100: return "lg"
        elif width >= 900:  return "md"
        else:               return "sm"

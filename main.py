"""
main.py
───────
Entry point — Nothing else lives here.
"""

from kintone_viewer import KintoneViewer


def main():
    app = KintoneViewer()
    app.mainloop()


if __name__ == "__main__":
    main()

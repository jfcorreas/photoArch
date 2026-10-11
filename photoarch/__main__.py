"""Allow running with `python -m photoarch`."""

from .app import PhotoArchApp


def main() -> None:
    PhotoArchApp().run()


if __name__ == "__main__":
    main()

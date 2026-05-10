"""Entry point for the praxova-framing-mcp console script."""

from .server import mcp


def main() -> None:
    """Run the FastMCP server on stdio."""
    mcp.run()


if __name__ == "__main__":
    main()

"""Run the webapp with ``python -m Tableau2PowerBI.webapp`` or ``t2pbi-serve``."""

import uvicorn


def main() -> None:
    """Start the FastAPI development server."""
    uvicorn.run("Tableau2PowerBI.webapp.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()

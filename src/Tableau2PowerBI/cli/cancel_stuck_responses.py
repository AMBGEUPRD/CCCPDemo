"""Cancel a stuck or zombie Azure AI Foundry response.

Usage::

    t2pbi-cancel-stuck-response resp_abc123def456
"""

import argparse
import logging

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from Tableau2PowerBI.core.config import get_agent_settings

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {"queued", "in_progress", "requires_action", "cancelling"}


def _create_project_client() -> AIProjectClient:
    settings = get_agent_settings()
    return AIProjectClient(
        endpoint=settings.project_endpoint,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )


def _retrieve_response(client, response_id: str):
    try:
        return client.responses.retrieve(response_id=response_id)
    except TypeError:
        return client.responses.retrieve(response_id)


def _cancel_response(client, response_id: str):
    try:
        return client.responses.cancel(response_id=response_id)
    except TypeError:
        return client.responses.cancel(response_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cancel a stuck or zombie Azure AI Foundry response.",
    )
    parser.add_argument("response_id", help="The response ID to cancel (e.g. resp_abc123…)")
    args = parser.parse_args()

    project_client = _create_project_client()
    openai_client = project_client.get_openai_client(timeout=60)
    response_id: str = args.response_id

    logger.info("Checking response: %s", response_id)

    try:
        response = _retrieve_response(openai_client, response_id)
        status = getattr(response, "status", None)
        logger.info("Current status: %s", status)

        if status in ACTIVE_STATUSES:
            cancelled = _cancel_response(openai_client, response_id)
            logger.info("Cancel requested -> new status: %s", getattr(cancelled, "status", None))
        else:
            logger.info("Response already completed / not cancellable")

    except Exception as ex:
        logger.warning("ERROR cancelling response: %s", ex)


if __name__ == "__main__":
    main()

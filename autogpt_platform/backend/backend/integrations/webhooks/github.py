import hashlib
import hmac
import logging

import requests
from autogpt_libs.supabase_integration_credentials_store import Credentials
from fastapi import HTTPException, Request
from strenum import StrEnum

from backend.data import integrations
from backend.integrations.providers import ProviderName

from .base import BaseWebhooksManager

logger = logging.getLogger(__name__)


class GithubWebhookType(StrEnum):
    REPO = "repo"


class GithubWebhooksManager(BaseWebhooksManager):
    PROVIDER_NAME = ProviderName.GITHUB

    WebhookType = GithubWebhookType

    GITHUB_API_URL = "https://api.github.com"
    GITHUB_API_DEFAULT_HEADERS = {"Accept": "application/vnd.github.v3+json"}

    @classmethod
    async def validate_payload(
        cls, webhook: integrations.Webhook, request: Request
    ) -> tuple[dict, str]:
        if not (event_type := request.headers.get("X-GitHub-Event")):
            raise HTTPException(
                status_code=400, detail="X-GitHub-Event header is missing!"
            )

        if not (signature_header := request.headers.get("X-Hub-Signature-256")):
            raise HTTPException(
                status_code=403, detail="X-Hub-Signature-256 header is missing!"
            )

        payload_body = await request.body()
        hash_object = hmac.new(
            webhook.secret.encode("utf-8"), msg=payload_body, digestmod=hashlib.sha256
        )
        expected_signature = "sha256=" + hash_object.hexdigest()

        if not hmac.compare_digest(expected_signature, signature_header):
            raise HTTPException(
                status_code=403, detail="Request signatures didn't match!"
            )

        payload = await request.json()

        return payload, event_type

    async def trigger_ping(self, webhook: integrations.Webhook) -> None:
        headers = {
            **self.GITHUB_API_DEFAULT_HEADERS,
            "Authorization": f"Bearer {webhook.config.get('access_token')}",
        }

        repo, github_hook_id = webhook.resource, webhook.provider_webhook_id
        ping_url = f"{self.GITHUB_API_URL}/repos/{repo}/hooks/{github_hook_id}/pings"

        response = requests.post(ping_url, headers=headers)

        if response.status_code != 204:
            raise Exception(f"Failed to ping GitHub webhook: {response.text}")

    async def _register_webhook(
        self,
        credentials: Credentials,
        webhook_type: GithubWebhookType,
        resource: str,
        events: list[str],
        ingress_url: str,
        secret: str,
    ) -> tuple[str, dict]:
        if webhook_type == self.WebhookType.REPO and resource.count("/") > 1:
            raise ValueError("Invalid repo format: expected 'owner/repo'")

        headers = {
            **self.GITHUB_API_DEFAULT_HEADERS,
            "Authorization": credentials.bearer(),
        }
        webhook_data = {
            "name": "web",
            "active": True,
            "events": events,
            "config": {
                "url": ingress_url,
                "content_type": "json",
                "insecure_ssl": "0",
                "secret": secret,
            },
        }

        response = requests.post(
            f"{self.GITHUB_API_URL}/repos/{resource}/hooks",
            headers=headers,
            json=webhook_data,
        )

        if response.status_code != 201:
            raise Exception(f"Failed to create GitHub webhook: {response.text}")

        webhook_id = response.json()["id"]
        config = response.json()["config"]

        return str(webhook_id), config

    async def _deregister_webhook(
        self, webhook: integrations.Webhook, credentials: Credentials
    ) -> None:
        webhook_type = self.WebhookType(webhook.webhook_type)
        if webhook.credentials_id != credentials.id:
            raise ValueError(
                f"Webhook #{webhook.id} does not belong to credentials {credentials.id}"
            )

        headers = {
            **self.GITHUB_API_DEFAULT_HEADERS,
            "Authorization": credentials.bearer(),
        }

        if webhook_type == self.WebhookType.REPO:
            repo = webhook.resource
            delete_url = f"{self.GITHUB_API_URL}/repos/{repo}/hooks/{webhook.provider_webhook_id}"  # noqa
        else:
            raise NotImplementedError(
                f"Unsupported webhook type '{webhook.webhook_type}'"
            )

        response = requests.delete(delete_url, headers=headers)

        if response.status_code not in [204, 404]:
            # 204 means successful deletion, 404 means the webhook was already deleted
            raise Exception(f"Failed to delete GitHub webhook: {response.text}")

        # If we reach here, the webhook was successfully deleted or didn't exist
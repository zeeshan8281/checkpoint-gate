"""Optional Cloudflare evidence mirror. SQLite remains the sole spend authority."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

from .common import canonical
from .ledger import StopCampaign


class CloudMirror:
    def __init__(self, url: str, campaign: str, owner: str, manifest: dict):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1"):
            raise ValueError("Cloud control URL requires HTTPS")
        self.url, self.campaign, self.owner = url.rstrip("/"), campaign, owner
        self.token = os.environ.get("CHECKPOINT_GATE_TOKEN")
        if not self.token:
            raise StopCampaign("CHECKPOINT_GATE_TOKEN missing")
        self.request("init", {"manifest": manifest})
        lease = self.request("lease", {"owner": owner})
        self.fence, self.expires = lease["fence"], lease["expires"]

    def request(self, action, payload):
        body = canonical(payload).encode()
        request = urllib.request.Request(
            f"{self.url}/api/campaigns/{self.campaign}/{action}", data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}",
                     "User-Agent": "CheckpointGate/0.1"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)

    def guard(self):
        # Renew BEFORE the external call. Expiry never authorizes redispatch.
        lease = self.request("lease", {"owner": self.owner, "fence": self.fence})
        if lease["fence"] != self.fence:
            raise StopCampaign("Cloudflare fencing token changed")
        self.expires = lease["expires"]

    def publish(self, name: str, value: dict):
        data = canonical(value)
        sha = hashlib.sha256(data.encode()).hexdigest()
        self.guard()
        return self.request("receipt", {"owner": self.owner, "fence": self.fence,
                                       "name": name, "sha256": sha, "data": data})

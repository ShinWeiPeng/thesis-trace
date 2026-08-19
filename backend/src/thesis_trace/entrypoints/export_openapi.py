from __future__ import annotations

import json
import sys
from typing import cast

from thesis_trace.api import AccessApiPort, EvidenceApi, create_fastapi_app
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.platform.in_memory import InMemoryEvidenceStore


def openapi_document() -> dict[str, object]:
    async def schema_actor() -> AuthenticatedActor:
        return AuthenticatedActor("openapi-schema-only", Role.OWNER, 1)

    api = EvidenceApi(
        flow=EvidenceIntakeFlow(store=InMemoryEvidenceStore(), id_generator=lambda: "schema-only")
    )
    # Route registration only needs a non-null Access boundary. Runtime methods
    # are never invoked while FastAPI builds the schema document.
    schema_access_boundary = cast(AccessApiPort, object())
    return create_fastapi_app(api, schema_actor, schema_access_boundary).openapi()


def main() -> int:
    json.dump(openapi_document(), sys.stdout, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

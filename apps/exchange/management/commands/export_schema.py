"""Write schema/test.v1.schema.json from the pydantic models (never hand-edit it)."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.exchange.document import TestDocument


class Command(BaseCommand):
    help = (
        "Generate schema/test.v1.schema.json (JSON Schema 2020-12) from the Test Document models."
    )

    def handle(self, *args, **options):
        schema = TestDocument.model_json_schema()
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Knowledge Tester test document v1",
            **schema,
        }
        target = settings.BASE_DIR / "schema" / "test.v1.schema.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.stdout.write(f"Wrote {target}")

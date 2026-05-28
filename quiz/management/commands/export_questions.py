import json
from pathlib import Path

from django.core.management.base import BaseCommand

from quiz.models import Question


class Command(BaseCommand):
    help = "Export quiz questions to a clean JSON file."

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            default="questions.json",
            help="Output JSON path. Defaults to questions.json",
        )
        parser.add_argument(
            "--indent",
            type=int,
            default=2,
            help="JSON indentation. Defaults to 2",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        path.parent.mkdir(parents=True, exist_ok=True)

        questions = list(
            Question.objects.order_by("id").values(
                "text",
                "options",
                "correct_index",
                "category",
                "difficulty",
            )
        )

        with path.open("w", encoding="utf-8") as file:
            json.dump(questions, file, ensure_ascii=False, indent=options["indent"])
            file.write("\n")

        self.stdout.write(
            self.style.SUCCESS(f"Exported {len(questions)} question(s) to {path}")
        )

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from quiz.models import Question


class Command(BaseCommand):
    help = "Import quiz questions from a clean JSON file."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Input JSON path")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Delete all existing questions before importing",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"File does not exist: {path}")

        try:
            with path.open("r", encoding="utf-8") as file:
                raw_questions = json.load(file)
        except json.JSONDecodeError as error:
            raise CommandError(f"Invalid JSON: {error}") from error

        questions = self._validate_questions(raw_questions)

        with transaction.atomic():
            deleted_count = 0
            if options["replace"]:
                deleted_count = Question.objects.count()
                Question.objects.all().delete()

            created_count = 0
            updated_count = 0
            for question_data in questions:
                if options["replace"]:
                    Question.objects.create(**question_data)
                    created_count += 1
                    continue

                question = Question.objects.filter(text=question_data["text"]).first()
                if question is None:
                    Question.objects.create(**question_data)
                    created_count += 1
                else:
                    for field, value in question_data.items():
                        setattr(question, field, value)
                    question.save(update_fields=list(question_data))
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Imported "
                f"{created_count} created, {updated_count} updated"
                f"{', ' + str(deleted_count) + ' deleted' if options['replace'] else ''}"
            )
        )

    def _validate_questions(self, raw_questions):
        if not isinstance(raw_questions, list):
            raise CommandError("Top-level JSON value must be a list of questions")

        questions = []
        for index, raw_question in enumerate(raw_questions, start=1):
            if not isinstance(raw_question, dict):
                raise CommandError(f"Question #{index} must be an object")

            text = raw_question.get("text")
            options = raw_question.get("options")
            correct_index = raw_question.get("correct_index")
            category = raw_question.get("category", "")
            difficulty = raw_question.get("difficulty", 1)

            if not isinstance(text, str) or not text.strip():
                raise CommandError(f"Question #{index}: text must be a non-empty string")
            if not isinstance(options, list) or not options:
                raise CommandError(f"Question #{index}: options must be a non-empty list")
            if not all(isinstance(option, str) and option.strip() for option in options):
                raise CommandError(
                    f"Question #{index}: every option must be a non-empty string"
                )
            if not isinstance(correct_index, int):
                raise CommandError(f"Question #{index}: correct_index must be an integer")
            if correct_index < 0 or correct_index >= len(options):
                raise CommandError(
                    f"Question #{index}: correct_index must point to an option"
                )
            if not isinstance(category, str):
                raise CommandError(f"Question #{index}: category must be a string")
            if not isinstance(difficulty, int):
                raise CommandError(f"Question #{index}: difficulty must be an integer")

            questions.append(
                {
                    "text": text.strip(),
                    "options": [option.strip() for option in options],
                    "correct_index": correct_index,
                    "category": category.strip(),
                    "difficulty": difficulty,
                }
            )

        return questions

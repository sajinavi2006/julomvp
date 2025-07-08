from django.core.management.base import BaseCommand

from juloserver.inapp_survey.models import InAppSurveyQuestion, InAppSurveyAnswer


class Command(BaseCommand):
    def handle(self, *args, **options):
        survey_data = [
            {
                "question": "Mengapa kamu ingin nonaktifkan autodebitmu?",
                "triggered_by_answer_ids": [],
                "should_randomize": True,
                "survey_type": "autodebet-deactivation",
                "is_first_question": True,
                "answer_type": "single-choice",
                "is_optional_question": False,
                "survey_usage": "autodebet-deactivation",
                "answers": [
                    {"answer": "Tanggal/waktu autodebit kurang sesuai"},
                    {"answer": "Ingin membayar tagihan lebih awal"},
                    {"answer": "Lebih suka membayar manual"},
                    {"answer": "Ingin mengganti ke autodebit lain"},
                    {"answer": "Ingin membayar dengan metode pembayaran lain"},
                    {"answer": "Tidak ingin membayar dari rekening/e-wallet tersebut lagi"},
                    {"answer": "Lainnya", "is_bottom_position": True},
                ],
            },
            {
                "question": "edupage1",
                "triggered_by_answer_ids": [],
                "survey_type": "autodebet-deactivation",
                "is_first_question": False,
                "answer_type": "custom-page",
                "page": "edupage1",
                "is_optional_question": False,
                "survey_usage": "autodebet-deactivation",
                "answers": [{"answer": "Nonaktifkan"}],
            },
            {
                "question": "Metode pembayaran apa yang ingin kamu gunakan ke depannya?",
                "triggered_by_answer_ids": [],
                "should_randomize": False,
                "survey_type": "autodebet-deactivation",
                "is_first_question": False,
                "answer_type": "multiple-choice",
                "is_optional_question": False,
                "survey_usage": "autodebet-deactivation",
                "answers": [
                    {"answer": "Transfer dari rekening/e-wallet lain"},
                    {"answer": "Indomaret/Alfamart"},
                ],
            },
            {
                "question": "Adakah alasan lain yang menjelaskan mengapa kamu ingin nonaktifkan autodebit?",
                "should_randomize": True,
                "triggered_by_answer_ids": [],
                "survey_type": "autodebet-deactivation",
                "is_first_question": False,
                "answer_type": "single-choice",
                "is_optional_question": False,
                "survey_usage": "autodebet-deactivation",
                "answers": [
                    {"answer": "Gagal penarikan di tagihan sebelumnya"},
                    {"answer": "Keraguan akan keamanan"},
                    {"answer": "Khawatir akan penyalahgunaan"},
                    {"answer": "Ingin mengurangi transaksi yang terjadi secara tidak sadar"},
                    {"answer": "Tidak ingin menggunakan JULO lagi selamanya"},
                    {"answer": "Lainnya", "is_bottom_position": True},
                ],
            },
            {
                "question": "edupage1a",
                "triggered_by_answer_ids": [],
                "survey_type": "autodebet-deactivation",
                "is_first_question": False,
                "answer_type": "custom-page",
                "page": "edupage1a",
                "is_optional_question": False,
                "survey_usage": "autodebet-deactivation",
                "answers": [{"answer": "Nonaktifkan"}],
            },
            {
                "question": "formadbq2",
                "triggered_by_answer_ids": [],
                "should_randomize": True,
                "survey_type": "autodebet-deactivation",
                "is_first_question": False,
                "answer_type": "custom-page",
                "page": "formadbq2",
                "is_optional_question": False,
                "survey_usage": "autodebet-deactivation",
                "answers": [{"answer": "default_answer"}],
            },
        ]

        for data in survey_data:
            question = InAppSurveyQuestion.objects.create(
                question=data['question'],
                survey_type=data['survey_type'],
                is_first_question=data['is_first_question'],
                answer_type=data['answer_type'],
                is_optional_question=data['is_optional_question'],
                survey_usage=data.get('survey_usage', None),
                should_randomize=data.get('should_randomize', False),
                page=data.get('page', None),
            )

            for answer_data in data['answers']:
                InAppSurveyAnswer.objects.create(
                    question=question,
                    answer=answer_data["answer"],
                    is_bottom_position=answer_data.get("is_bottom_position", False),
                    answer_type=answer_data.get('type', None),
                )

            self.stdout.write(
                self.style.SUCCESS(f'Successfully added question: {question.question}')
            )

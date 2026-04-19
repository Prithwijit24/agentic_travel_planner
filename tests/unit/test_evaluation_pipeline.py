import json

from agentic_tour_planner.evaluation.ragas_pipeline import RagasEvaluationPipeline


def test_load_cases_supports_cases_wrapper(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "question": "Test question",
                        "request": {
                            "destination": "Kyoto",
                            "trip_length_days": 2,
                        },
                        "reference_answer": "Reference",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cases = RagasEvaluationPipeline.load_cases(str(path))

    assert len(cases) == 1
    assert cases[0].metadata["destination"] == "Kyoto"


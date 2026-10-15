import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import pipeline
import questions


class PipelineIntegrationTests(unittest.TestCase):
    def test_question_context_reaches_video_review_and_evidence_reaches_result(self):
        pool = questions._mock_pool()[:3]
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "WORK_DIR", Path(tmp)), \
                patch.object(pipeline, "OUTPUT_DIR", Path(tmp)), \
                patch.object(pipeline, "refine_queries"), \
                patch.object(pipeline, "get_questions", return_value=pool), \
                patch.object(pipeline, "synthesize_all", side_effect=lambda texts, _: [np.zeros(4410, dtype=np.float32) for _ in texts]), \
                patch.object(pipeline, "find_background", return_value=(Path(tmp) / "stock.mp4", "Gemma frame check: Subject fits.")) as backgrounds, \
                patch.object(pipeline, "render_segment"), \
                patch.object(pipeline, "concat_videos"), \
                patch.object(pipeline, "mux"), \
                patch.object(pipeline, "mark_used") as history, \
                patch.object(pipeline, "cleanup_disk"):
            result = pipeline.build_quiz(3)
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual(backgrounds.call_count, 5)
        for call, question in zip(backgrounds.call_args_list[:3], pool):
            self.assertEqual(call.kwargs["question"], question["question"])
        self.assertNotIn("question", backgrounds.call_args_list[-1].kwargs)
        media_dirs = {call.kwargs["cache_dir"] for call in backgrounds.call_args_list}
        self.assertEqual(len(media_dirs), 1)
        self.assertEqual(next(iter(media_dirs)).parent.parent, Path(tmp))
        self.assertEqual(next(iter(media_dirs)).name, "media")
        self.assertTrue(all("Gemma frame check" in q["footage"] for q in result["questions"]))
        history.assert_called_once()


if __name__ == "__main__":
    unittest.main()

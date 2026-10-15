import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import footage_review
import videos


class FootageReviewTests(unittest.TestCase):
    def test_enabled_by_default_for_local_questions_and_can_be_disabled(self):
        for source, override, mock, expected in (("ollama", "", "0", True),
                                                ("local", "0", "0", False),
                                                ("opentdb", "1", "0", True),
                                                ("ollama", "1", "1", False),
                                                ("opentdb", "", "0", False)):
            with self.subTest(source=source, override=override, mock=mock), \
                    patch.dict(os.environ, {"QUESTION_SOURCE": source, "MOCK": mock}):
                if override:
                    with patch.dict(os.environ, {"VIDEO_REVIEW": override}):
                        self.assertEqual(footage_review.review_enabled(), expected)
                else:
                    with patch.dict(os.environ):
                        os.environ.pop("VIDEO_REVIEW", None)
                        self.assertEqual(footage_review.review_enabled(), expected)

    def test_extracts_three_cropped_frames_and_cleans_up(self):
        def write_frame(args):
            Path(args[-1]).write_bytes(b"test image")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(footage_review, "WORK_DIR", Path(tmp)), \
                patch.object(footage_review, "run_ffmpeg", side_effect=write_frame) as ffmpeg, \
                patch.object(footage_review, "chat_json", side_effect=[{"description": "A spider on a web."}, {"suitable": True, "reason": "A spider is visible."}]) as chat:
            verdict = footage_review.review_clip("clip.mp4", "How many legs does a spider have?", "spider", 10)
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertTrue(verdict["suitable"])
        self.assertEqual([call.args[0][1] for call in ffmpeg.call_args_list], ["1.000", "5.000", "9.000"])
        for call in ffmpeg.call_args_list:
            self.assertIn("crop=650:350", " ".join(map(str, call.args[0])))
        images = chat.call_args_list[0].args[0][0]["images"]
        self.assertEqual(len(images), 3)
        self.assertEqual(base64.b64decode(images[0]), b"test image")
        self.assertNotIn("How many legs", chat.call_args_list[0].args[0][0]["content"])
        self.assertNotIn("images", chat.call_args_list[1].args[0][0])
        self.assertIn("A spider on a web.", chat.call_args_list[1].args[0][0]["content"])

    def test_invalid_decision_fails_closed(self):
        def write_frame(args):
            Path(args[-1]).write_bytes(b"image")
        with patch.object(footage_review, "run_ffmpeg", side_effect=write_frame), \
                patch.object(footage_review, "chat_json", side_effect=[{"description": "A car."}, {"suitable": "true", "reason": "maybe"}]):
            with self.assertRaisesRegex(RuntimeError, "invalid"):
                footage_review.review_clip("clip.mp4", "question", "query", 5)

    def test_invalid_visual_description_fails_closed(self):
        def write_frame(args):
            Path(args[-1]).write_bytes(b"image")
        with patch.object(footage_review, "run_ffmpeg", side_effect=write_frame), \
                patch.object(footage_review, "chat_json", return_value={"description": None}) as chat:
            with self.assertRaisesRegex(RuntimeError, "description"):
                footage_review.review_clip("clip.mp4", "question", "query", 5)
        self.assertEqual(chat.call_count, 1)

    def test_pixabay_skips_rejected_clip_and_returns_review_evidence(self):
        hits = [{"id": i, "duration": 5, "tags": "spider", "videos": {"medium": {"url": f"https://example.com/{i}.mp4"}}} for i in (1, 2)]
        with tempfile.TemporaryDirectory() as tmp, patch.object(videos, "CACHE_DIR", Path(tmp)), \
                patch.dict(os.environ, {"PIXABAY_API_KEY": "unused"}), \
                patch.object(videos, "_pixabay_hits", return_value=hits), \
                patch.object(videos, "_candidates", side_effect=lambda items, *_: items), \
                patch.object(videos, "_download"), \
                patch.object(videos, "review_enabled", return_value=True), \
                patch.object(videos, "review_clip", side_effect=[{"suitable": False, "reason": "Unrelated car."}, {"suitable": True, "reason": "Spider visible."}]):
            used = set()
            path, evidence = videos._find_pixabay(["spider"], used, "How many legs does a spider have?")
        self.assertEqual(used, {2})
        self.assertEqual(path.name, "pixabay_2.mp4")
        self.assertIn("Gemma frame check: Spider visible.", evidence)

    def test_pexels_does_not_review_same_rejected_clip_again(self):
        clip = {"id": 1, "duration": 5, "video_files": [{"file_type": "video/mp4", "width": 720, "height": 1280, "link": "https://example.com/1.mp4"}]}
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"videos": [clip]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(videos, "CACHE_DIR", Path(tmp)), \
                patch.dict(os.environ, {"PEXELS_API_KEY": "unused", "MOCK": "0", "VIDEO_SOURCE": "pexels", "VIDEO_SEARCH_ROUNDS": "1"}), \
                patch.object(videos.requests, "get", return_value=response), \
                patch.object(videos, "_download"), \
                patch.object(videos, "review_enabled", return_value=True), \
                patch.object(videos, "review_clip", return_value={"suitable": False, "reason": "Wrong subject."}) as review:
            used = set()
            with self.assertRaisesRegex(RuntimeError, "No suitable"):
                videos.find_background(["spider", "forest animals"], used, "spider question")
        self.assertEqual(used, set())
        review.assert_called_once()

    def test_vision_service_failure_does_not_accept_unchecked_clip(self):
        with patch.object(videos, "review_enabled", return_value=True), \
                patch.object(videos, "review_clip", side_effect=RuntimeError("Ollama offline")):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                videos._review_candidate("clip.mp4", "question", "query", 5)

    def test_pexels_returns_only_accepted_clip_and_evidence(self):
        clips = [{"id": i, "duration": 5, "video_files": [{"file_type": "video/mp4", "width": 720, "height": 1280, "link": f"https://example.com/{i}.mp4"}]} for i in (1, 2)]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"videos": clips}
        with tempfile.TemporaryDirectory() as tmp, patch.object(videos, "CACHE_DIR", Path(tmp)), \
                patch.dict(os.environ, {"PEXELS_API_KEY": "unused", "MOCK": "0", "VIDEO_SOURCE": "pexels", "VIDEO_SEARCH_ROUNDS": "1"}), \
                patch.object(videos.requests, "get", return_value=response), \
                patch.object(videos, "_candidates", side_effect=lambda items, *_: items), \
                patch.object(videos, "_download"), \
                patch.object(videos, "review_enabled", return_value=True), \
                patch.object(videos, "review_clip", side_effect=[{"suitable": False, "reason": "Unrelated car."}, {"suitable": True, "reason": "Spider visible."}]):
            used = set()
            path, evidence = videos.find_background(["spider"], used, "How many legs does a spider have?")
        self.assertEqual(used, {2})
        self.assertEqual(path.name, "pexels_2.mp4")
        self.assertIn("Gemma frame check: Spider visible.", evidence)

    def test_decorative_outro_skips_topic_review(self):
        with patch.object(videos, "review_enabled", return_value=True), patch.object(videos, "review_clip") as review:
            self.assertEqual(videos._review_candidate("clip.mp4", "", "abstract background", 5), (True, ""))
        review.assert_not_called()


if __name__ == "__main__":
    unittest.main()

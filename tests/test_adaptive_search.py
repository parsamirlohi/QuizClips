import os
import unittest
from unittest.mock import patch
import videos


class AdaptiveSearchTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"MOCK": "0", "QUESTION_SOURCE": "ollama",
                                          "VIDEO_SEARCH_ROUNDS": "3"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_feedback_retry_for_both_providers(self):
        for provider in ("pixabay", "pexels"):
            with self.subTest(provider=provider):
                calls = []
                def search(queries, used, question, rejected, feedback):
                    calls.append(list(queries))
                    if len(calls) == 1:
                        rejected.add(42)
                        feedback.append({"query": queries[0], "reason": "A car, no river."})
                        raise videos.NoSuitableFootage("none")
                    self.assertEqual(rejected, {42})
                    return "clip.mp4", "river aerial"
                with patch.object(videos, "_source", return_value=provider), patch.object(
                        videos, "_find_" + provider, side_effect=search), patch.object(
                        videos, "chat_json", return_value={"queries": [" OLD ", "river aerial", "River Aerial", ""]}) as chat:
                    path, evidence = videos.find_background(["old"], set(), "Which river crosses London?")
                self.assertEqual(calls, [["old"], ["river aerial"]])
                self.assertIn("A car, no river.", chat.call_args.args[0][0]["content"])
                self.assertIn("round 2", evidence)

    def test_bounded_failure(self):
        with patch.object(videos, "_source", return_value="pixabay"), patch.object(
                videos, "_find_pixabay", side_effect=videos.NoSuitableFootage("none")) as search, patch.object(
                videos, "chat_json", side_effect=[{"queries": ["second"]}, {"queries": ["third"]}]) as chat:
            with self.assertRaisesRegex(videos.NoSuitableFootage, "3 search round"):
                videos.find_background(["first"], set(), "question")
        self.assertEqual(search.call_count, 3)
        self.assertEqual(chat.call_count, 2)

    def test_service_error_is_not_retried(self):
        with patch.object(videos, "_source", return_value="pixabay"), patch.object(
                videos, "_find_pixabay", side_effect=RuntimeError("service unavailable")), patch.object(
                videos, "chat_json") as chat:
            with self.assertRaisesRegex(RuntimeError, "service unavailable"):
                videos.find_background(["first"], set(), "question")
        chat.assert_not_called()

    def test_repeated_queries_stop(self):
        with patch.object(videos, "_source", return_value="pixabay"), patch.object(
                videos, "_find_pixabay", side_effect=videos.NoSuitableFootage("none")) as search, patch.object(
                videos, "chat_json", return_value={"queries": [" FIRST "]}):
            with self.assertRaises(videos.NoSuitableFootage):
                videos.find_background(["first"], set(), "question")
        self.assertEqual(search.call_count, 1)

    def test_decorative_search_does_not_refine(self):
        with patch.object(videos, "_source", return_value="pixabay"), patch.object(
                videos, "_find_pixabay", side_effect=videos.NoSuitableFootage("none")), patch.object(
                videos, "chat_json") as chat:
            with self.assertRaises(videos.NoSuitableFootage):
                videos.find_background(["first"], set())
        chat.assert_not_called()

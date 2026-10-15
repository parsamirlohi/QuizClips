import json
import os
import unittest
from unittest.mock import Mock, patch

import requests

import local_model
import questions


def generated(question="How many legs does a spider have?"):
    return {"question": question, "correct_answer": "Eight",
            "wrong_answers": ["Six", "Ten", "Twelve"], "category": "Animals",
            "video_query": "forest spider web"}


class LocalGenerationTests(unittest.TestCase):
    def test_local_request_uses_schema_and_selected_model(self):
        response = Mock()
        response.json.return_value = {"message": {"content": json.dumps({"questions": [generated()]})}}
        with patch.dict(os.environ, {"OLLAMA_MODEL": "gemma4:latest", "OLLAMA_BASE_URL": "http://localhost:11434/", "OLLAMA_TIMEOUT": "45"}), \
                patch.object(local_model.requests, "post", return_value=response) as post:
            result = questions._from_ollama(1, ["Earlier question"], [27])
        self.assertEqual(result[0]["video_queries"][0], "forest spider web")
        self.assertEqual(post.call_args.args[0], "http://localhost:11434/api/chat")
        self.assertEqual(post.call_args.kwargs["timeout"], (5, 45))
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "gemma4:latest")
        self.assertFalse(body["stream"])
        self.assertFalse(body["think"])
        self.assertIn("Earlier question", body["messages"][0]["content"])
        self.assertEqual(body["format"]["properties"]["questions"]["items"]["properties"]["category"]["enum"], ["Animals"])

    def test_filters_malformed_duplicates_and_wrong_categories(self):
        invalid = [None, {}, generated()]
        for field, value in (("wrong_answers", ["Eight", "Ten", "Twelve"]),
                             ("wrong_answers", ["Six", "Ten"]),
                             ("wrong_answers", ["", "Ten", "Twelve"]),
                             ("video_query", None), ("category", "History")):
            item = generated("A different question?")
            item[field] = value
            invalid.append(item)
        with patch.object(questions, "chat_json", return_value={"questions": [generated()] + invalid}):
            result = questions._from_ollama(1, [], [27])
        self.assertEqual(len(result), 1)

    def test_partial_batch_falls_back_to_opentdb(self):
        with patch.dict(os.environ, {"QUESTION_SOURCE": "ollama", "MOCK": "0"}), \
                patch.object(questions, "_load_history", return_value={}), \
                patch.object(questions, "chat_json", return_value={"questions": []}), \
                patch.object(questions, "_from_opentdb", return_value=questions._mock_pool()) as fallback:
            result = questions.get_questions(3, [27])
        self.assertEqual(len(result), 3)
        fallback.assert_called_once_with([27])

    def test_local_source_overrides_claude_and_prefers_fresh_questions(self):
        pool = questions._mock_pool()[:4]
        with patch.dict(os.environ, {"QUESTION_SOURCE": "local", "ANTHROPIC_API_KEY": "unused", "MOCK": "0"}), \
                patch.object(questions, "_load_history", return_value={questions._qid(pool[0]["question"]): pool[0]["question"]}), \
                patch.object(questions, "_from_ollama", return_value=pool) as local, \
                patch.object(questions, "_from_claude") as claude:
            result = questions.get_questions(3)
        local.assert_called_once()
        claude.assert_not_called()
        self.assertNotIn(pool[0], result)

    def test_connection_failure_falls_back(self):
        with patch.dict(os.environ, {"QUESTION_SOURCE": "ollama", "MOCK": "0"}), \
                patch.object(questions, "_load_history", return_value={}), \
                patch.object(local_model.requests, "post", side_effect=requests.ConnectionError("offline")), \
                patch.object(questions, "_from_opentdb", return_value=questions._mock_pool()) as fallback:
            self.assertEqual(len(questions.get_questions(3)), 3)
        fallback.assert_called_once()

    def test_invalid_model_response_is_reported(self):
        for payload in ([1], {"error": "missing model"}, {"message": {"content": "not JSON"}}):
            with self.subTest(payload=payload), patch.object(local_model.requests, "post") as post:
                post.return_value.json.return_value = payload
                with self.assertRaises(RuntimeError):
                    local_model.chat_json([], {})

    def test_invalid_timeout_does_not_send_request(self):
        with patch.dict(os.environ, {"OLLAMA_TIMEOUT": "0"}), patch.object(local_model.requests, "post") as post:
            with self.assertRaisesRegex(RuntimeError, "positive"):
                local_model.chat_json([], {})
        post.assert_not_called()

    def test_mock_mode_never_calls_local_model(self):
        with patch.dict(os.environ, {"QUESTION_SOURCE": "ollama", "MOCK": "1"}), \
                patch.object(questions, "_load_history", return_value={}), \
                patch.object(questions, "_from_ollama") as local:
            self.assertEqual(len(questions.get_questions(3)), 3)
        local.assert_not_called()

    def test_existing_claude_default_is_preserved(self):
        with patch.dict(os.environ, {"QUESTION_SOURCE": "", "ANTHROPIC_API_KEY": "unused", "MOCK": "0"}), \
                patch.object(questions, "_load_history", return_value={}), \
                patch.object(questions, "_from_claude", return_value=questions._mock_pool()) as claude:
            self.assertEqual(len(questions.get_questions(3)), 3)
        claude.assert_called_once()


if __name__ == "__main__":
    unittest.main()

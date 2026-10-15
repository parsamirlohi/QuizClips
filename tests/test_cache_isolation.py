import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pipeline
import videos


class CacheIsolationTests(unittest.TestCase):
    def test_simultaneous_jobs_keep_separate_copies_before_review(self):
        hit = {"id": 2265, "duration": 5, "tags": "river",
               "videos": {"medium": {"url": "https://example.com/river.mp4"}}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            cache.mkdir()
            (cache / "other.mp4").write_bytes(b"other job")
            reviewed = []

            def download(url, dest):
                dest.write_bytes(b"river footage")

            def review(dest, *_):
                # Simulate an older app instance clearing the global cache.
                for shared in cache.iterdir():
                    shared.unlink()
                self.assertEqual(dest.read_bytes(), b"river footage")
                reviewed.append(dest)
                return True, ""

            with patch.object(videos, "CACHE_DIR", cache), \
                    patch.dict(os.environ, {"KEEP_CACHE": "0", "PIXABAY_API_KEY": "fixture"}), \
                    patch.object(videos, "_pixabay_hits", return_value=[hit]), \
                    patch.object(videos, "_download", side_effect=download), \
                    patch.object(videos, "_review_candidate", side_effect=review):
                first, _ = videos._find_pixabay(["river"], set(), "question", cache_dir=root / "job-one")
                second, _ = videos._find_pixabay(["river"], set(), "question", cache_dir=root / "job-two")
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(reviewed, [first, second])

    def test_retained_cache_reuses_clip_but_shared_deletion_cannot_remove_job_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            cache.mkdir()
            shared = cache / "pixabay_2265.mp4"
            shared.write_bytes(b"retained clip")
            with patch.object(videos, "CACHE_DIR", cache), \
                    patch.dict(os.environ, {"KEEP_CACHE": "1"}), \
                    patch.object(videos, "_download") as download:
                private = videos._local_video(shared.name, "unused", root / "job")
                download.assert_not_called()
                shared.unlink()
                self.assertEqual(private.read_bytes(), b"retained clip")

    def test_failed_cache_link_falls_back_to_job_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            cache.mkdir()
            with patch.object(videos, "CACHE_DIR", cache), \
                    patch.dict(os.environ, {"KEEP_CACHE": "1"}), \
                    patch.object(videos.os, "link", side_effect=OSError("unsupported filesystem")), \
                    patch.object(videos, "_download", side_effect=lambda _, dest: dest.write_bytes(b"fresh clip")):
                private = videos._local_video("pexels_1.mp4", "unused", root / "job")
                self.assertEqual(private.read_bytes(), b"fresh clip")

    def test_new_download_is_retained_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            cache.mkdir()
            with patch.object(videos, "CACHE_DIR", cache), \
                    patch.dict(os.environ, {"KEEP_CACHE": "1"}), \
                    patch.object(videos, "_download", side_effect=lambda _, dest: dest.write_bytes(b"new clip")):
                private = videos._local_video("pixabay_2265.mp4", "unused", root / "job")
                private.unlink()
                self.assertEqual((cache / private.name).read_bytes(), b"new clip")

    def test_disk_cleanup_leaves_shared_cache_and_active_job_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            cache.mkdir()
            shared = cache / "pixabay_2265.mp4"
            shared.write_bytes(b"retained clip")
            active = root / "active-job.mp4"
            active.write_bytes(b"active clip")
            with patch.dict(os.environ, {"KEEP_CACHE": "0", "MAX_KEEP_VIDEOS": "0"}), \
                    patch.object(pipeline, "OUTPUT_DIR", root):
                pipeline.cleanup_disk()
            self.assertTrue(shared.exists())
            self.assertTrue(active.exists())


if __name__ == "__main__":
    unittest.main()

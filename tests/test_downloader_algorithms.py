import unittest

import downloader


class DownloaderAlgorithmTests(unittest.TestCase):
    def test_mp3_plan_uses_duration_budget(self) -> None:
        duration_seconds = 60 * 60
        plan = downloader._choose_mp3_download_plan({"duration": duration_seconds})

        expected_bitrate = downloader._calculate_mp3_target_bitrate_kbps(duration_seconds)
        self.assertEqual(plan.format_selector, "bestaudio/best")
        self.assertEqual(plan.preferred_audio_quality_kbps, expected_bitrate)
        self.assertLessEqual(plan.preferred_audio_quality_kbps or 0, 320)
        self.assertGreaterEqual(
            plan.preferred_audio_quality_kbps or 0,
            downloader.MIN_MP3_BITRATE_KBPS,
        )

    def test_mp4_plan_prefers_fit_candidate_over_oversized_highest_quality(self) -> None:
        info = {
            "duration": 120,
            "formats": [
                {
                    "format_id": "huge-1080",
                    "ext": "mp4",
                    "vcodec": "h264",
                    "acodec": "aac",
                    "height": 1080,
                    "fps": 30,
                    "tbr": 5000,
                    "filesize": downloader.TARGET_UPLOAD_BYTES + 10_000_000,
                },
                {
                    "format_id": "fit-720",
                    "ext": "mp4",
                    "vcodec": "h264",
                    "acodec": "aac",
                    "height": 720,
                    "fps": 30,
                    "tbr": 2200,
                    "filesize": downloader.TARGET_UPLOAD_BYTES - 5_000_000,
                },
            ],
        }

        plan = downloader._choose_mp4_download_plan(info)

        self.assertEqual(plan.format_selector, "fit-720")
        self.assertEqual(plan.strategy, "progressive_direct")

    def test_mp4_plan_prefers_better_quality_merge_when_it_fits(self) -> None:
        info = {
            "duration": 180,
            "formats": [
                {
                    "format_id": "low-prog",
                    "ext": "mp4",
                    "vcodec": "h264",
                    "acodec": "aac",
                    "height": 360,
                    "fps": 30,
                    "tbr": 700,
                    "filesize": 12_000_000,
                },
                {
                    "format_id": "video-720",
                    "ext": "mp4",
                    "vcodec": "h264",
                    "acodec": "none",
                    "height": 720,
                    "fps": 30,
                    "tbr": 1800,
                    "filesize": 20_000_000,
                },
                {
                    "format_id": "audio-aac",
                    "ext": "m4a",
                    "vcodec": "none",
                    "acodec": "aac",
                    "abr": 128,
                    "tbr": 128,
                    "filesize": 3_000_000,
                },
            ],
        }

        plan = downloader._choose_mp4_download_plan(info)

        self.assertEqual(plan.format_selector, "video-720+audio-aac")
        self.assertEqual(plan.merge_output_format, "mp4")
        self.assertEqual(plan.strategy, "adaptive_merge")


if __name__ == "__main__":
    unittest.main()

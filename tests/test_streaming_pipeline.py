"""Tests for SentenceSplitter and StreamingAudioPipeline."""
import time
import unittest
from unittest.mock import MagicMock

from my_openai_robot.streaming.sentence_splitter import SentenceSplitter
from my_openai_robot.streaming.pipeline import StreamingAudioPipeline


class TestSentenceSplitter(unittest.TestCase):
    def test_first_sentence_acceleration(self):
        splitter = SentenceSplitter(min_first_len=4)
        tokens = ["你好", "呀，", "我是", "机器人助手。", "今天天气很好。"]
        sentences = list(splitter.split_stream(tokens))

        # 首句遇到逗号且长度 >= 4，立即切出
        self.assertEqual(sentences[0], "你好呀，")
        self.assertEqual(sentences[1], "我是机器人助手。")
        self.assertEqual(sentences[2], "今天天气很好。")

    def test_strong_punctuation_split(self):
        splitter = SentenceSplitter()
        tokens = ["这是第一句话！", "这是第二句话？", "这是第三句话。\n这是第四句话。"]
        sentences = list(splitter.split_stream(tokens))

        self.assertEqual(sentences, [
            "这是第一句话！",
            "这是第二句话？",
            "这是第三句话。",
            "这是第四句话。",
        ])

    def test_flush_remaining_tokens_without_ending_punct(self):
        splitter = SentenceSplitter()
        tokens = ["这是一段", "没有最后标点的文本"]
        sentences = list(splitter.split_stream(tokens))

        self.assertEqual(len(sentences), 1)
        self.assertEqual(sentences[0], "这是一段没有最后标点的文本")

    def test_long_sentence_fallback_split(self):
        splitter = SentenceSplitter(max_chunk_len=15)
        # 一句很长的话，在中间有逗号
        tokens = ["这是一句非常长的话，里面包含了很多信息，但是没有句号"]
        sentences = list(splitter.split_stream(tokens))
        self.assertGreater(len(sentences), 1)


class TestStreamingAudioPipeline(unittest.TestCase):
    def test_pipeline_concurrent_synthesis_and_playback(self):
        mock_speech_service = MagicMock()
        mock_speech_service.synthesize.side_effect = lambda text: f"wav_data_for_{text}".encode("utf-8")

        mock_speaker = MagicMock()

        pipeline = StreamingAudioPipeline(
            speech_service=mock_speech_service,
            speaker=mock_speaker,
        )

        tokens = ["你好呀！", "欢迎使用", "流式语音助手。", "祝你今天愉快！"]
        result = pipeline.run(tokens, play_audio=True)

        self.assertEqual(result.full_text, "你好呀！欢迎使用流式语音助手。祝你今天愉快！")
        self.assertGreater(result.tts_characters, 0)
        self.assertGreater(len(result.audio_chunks), 0)

        # 验证每个分句都调用了 synthesize 和 speaker.play
        self.assertGreaterEqual(mock_speech_service.synthesize.call_count, 2)
        self.assertGreaterEqual(mock_speaker.play.call_count, 2)

    def test_pipeline_without_synthesis(self):
        mock_speech_service = MagicMock()
        mock_speaker = MagicMock()

        pipeline = StreamingAudioPipeline(
            speech_service=mock_speech_service,
            speaker=mock_speaker,
        )

        tokens = ["纯", "文本", "输出"]
        result = pipeline.run(tokens, synthesize=False)

        self.assertEqual(result.full_text, "纯文本输出")
        self.assertEqual(result.tts_characters, 0)
        mock_speech_service.synthesize.assert_not_called()
        mock_speaker.play.assert_not_called()


if __name__ == "__main__":
    unittest.main()

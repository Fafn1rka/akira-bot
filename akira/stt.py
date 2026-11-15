"""Распознавание речи: faster-whisper на CPU."""
HALLUCINATIONS = ("продолжение следует", "субтитры", "спасибо за просмотр",
                  "редактор субтитров", "корректор", "подписывайтесь")


class STT:
    def __init__(self, model="small", language="ru", device="cpu", compute_type="int8", prompt=""):
        self.name, self.language, self.device, self.ct, self.prompt = model, language, device, compute_type, prompt
        self._model = None

    def load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.name, device=self.device, compute_type=self.ct)
        return self._model

    def transcribe(self, audio) -> str:
        segments, _ = self.load().transcribe(
            audio, language=self.language, beam_size=1,
            condition_on_previous_text=False, initial_prompt=self.prompt or None,
        )
        parts = []
        for s in segments:
            if s.no_speech_prob > 0.6 or s.avg_logprob < -1.2:
                continue
            parts.append(s.text.strip())
        text = " ".join(parts).strip()
        low = text.lower()
        if len(text) < 80 and any(h in low for h in HALLUCINATIONS):
            return ""
        return text

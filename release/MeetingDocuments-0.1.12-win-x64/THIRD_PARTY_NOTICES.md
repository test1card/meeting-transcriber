# Third-party software and models

The MIT License in `LICENSE` covers the original Meeting Documents application
code only. The application also uses third-party software and can download
third-party model weights. Those components remain under their own licenses and
terms.

- Tauri, React, Python packages, FFmpeg, Ollama, WhisperX and other runtime
  dependencies are installed or redistributed under their respective licenses.
- The bundled MOSS-Transcribe-Diarize source retains its upstream license and
  copyright notices in `vendor/MOSS-Transcribe-Diarize/LICENSE`.
- MOSS, Qwen, Gemma, WhisperX alignment models, ECAPA-TDNN and other model
  weights are not included in the Windows installer. They are downloaded only
  after a user selects a workstation profile. Each model is governed by its
  publisher's license or usage terms; in particular, Gemma models are governed
  by the Gemma Terms of Use.
- DeepSeek is optional. Its API is governed by DeepSeek's current service terms,
  and each user must provide their own API key.

No rights to third-party trademarks, models, or hosted services are granted by
the Meeting Documents MIT License. Before organizational deployment, review the
terms shown by the relevant model and service publishers.

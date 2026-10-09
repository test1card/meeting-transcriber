import json
import subprocess
import wave

import httpx
import pytest

from meeting_transcriber import local_audio as local


def test_speaker_assignment_flags_boundary_and_overlap_without_changing_text():
    asr = [{"start": 0, "end": 2, "text": "Первая реплика"},
           {"start": 2, "end": 4, "text": "Два участника одновременно"},
           {"start": 5, "end": 6, "text": "Нет уверенного говорящего"}]
    turns = [{"start": 0, "end": 4, "speaker": "SPEAKER_00"},
             {"start": 2, "end": 4, "speaker": "SPEAKER_01"}]
    assigned = local.assign_speakers(asr, turns)
    assert [s["text"] for s in assigned] == [s["text"] for s in asr]
    assert assigned[0]["speaker"] == "SPEAKER_00"
    assert assigned[1]["speaker"] == "UNRESOLVED"
    assert assigned[1]["speaker_candidates"] == ["SPEAKER_00", "SPEAKER_01"]
    assert assigned[2]["needs_review"]


def test_editor_cannot_overwrite_speaker_or_timestamps():
    source = [{"id": "T000000", "start": 1, "end": 2,
               "speaker": "SPEAKER_01", "text": "ну да"}]
    response = {"segments": [{"id": "T000000", "text": "Ну да.",
                             "speaker": "SPEAKER_08", "start": 99}]}
    result = local.validated_edits(response, source)[0]
    assert result["speaker"] == "SPEAKER_01" and result["start"] == 1
    assert result["source_text"] == "ну да"
    with pytest.raises(ValueError):
        local.validated_edits({"segments": []}, source)


@pytest.mark.parametrize("url", ["https://api.example.com", "http://192.168.1.1:8000",
                                "http://localhost.evil.com", "http://key:secret@localhost"])
def test_private_mode_rejects_external_endpoints(url):
    with pytest.raises(ValueError):
        local.validate_local_url(url)


def test_asr_checkpoint_resume_unicode_and_no_network(tmp_path, monkeypatch):
    job = tmp_path / "Совещание № 1"
    (job / "_audit").mkdir(parents=True)
    with wave.open(str(job / "_audit/audio.wav"), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x00" * 16000)
    calls = []

    def respond(request):
        calls.append(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps([
            {"Start": 0, "End": 1, "Content": "Проверка связи", "Speaker": 0}])}}]})

    real_client = httpx.Client
    monkeypatch.setattr(local.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond)))
    first = local.run_asr(job, "http://127.0.0.1:8765", "")
    assert len(calls) == 1
    monkeypatch.setattr(local.httpx, "Client", lambda **kw: pytest.fail("resumed ASR used network"))
    assert local.run_asr(job, "http://127.0.0.1:8765", "") == first


def test_cancel_retains_job_and_audio_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(local, "ROOT", tmp_path)
    (tmp_path / "runtime").mkdir()
    local.write_json(tmp_path / "local-runtime.json", {"diarization": {"path": "unused"}})
    recording = tmp_path / "Запись.wav"
    with wave.open(str(recording), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x00" * 1600)

    def cancelled(*args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(local, "run_asr", cancelled)
    job = tmp_path / "Результат"
    assert local.main([str(recording), "-o", str(job), "--asr-url", "http://localhost:8765", "--no-edit"]) == 130
    assert (job / "job.json").is_file()
    assert (job / "_audit/audio.wav").is_file()
    assert json.loads((job / "status.json").read_text())["state"] == "cancelled"
    assert not (job / "documents/02_Исходная_стенограмма.md").exists()

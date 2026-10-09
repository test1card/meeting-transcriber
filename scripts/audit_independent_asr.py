"""Local, resumable ASR evidence with overlapping windows and word timestamps."""
import argparse, contextlib, fcntl, json, math, time
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
from transformers import WhisperForConditionalGeneration, AutoProcessor, pipeline
from meeting_transcriber.completeness import owned_word
from meeting_transcriber.local_audio import fingerprint, write_json

p=argparse.ArgumentParser()
p.add_argument('job',type=Path)
p.add_argument('--limit',type=int)
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
job=a.job.resolve(); audit=job/'_audit/completeness';audit.mkdir(parents=True,exist_ok=True)
check=audit/'independent-checkpoints';check.mkdir(exist_ok=True)
wave_path=job/'_audit/audio.wav'
model_path=root/'models/completeness-asr'
config={'audio_sha256':fingerprint(wave_path),'model':'BuzzASR/russian','revision':'63bae860001db310f35bec6473eade9860d9ff71','core_seconds':20,'overlap_seconds':5,'word_timestamps':True,'language':'ru','precision':'float16','generation':{'num_beams':1,'no_repeat_ngram_size':0,'repetition_penalty':1.0}}
prov=audit/'independent-provenance.json'
if prov.exists() and json.loads(prov.read_text())!=config:raise ValueError('Audit configuration changed')
write_json(prov,config)
torch.set_num_threads(4)
x,sr=sf.read(wave_path,dtype='float32'); duration=len(x)/sr
assert sr==16000 and x.ndim==1
count=math.ceil(duration/20)
with (root/'runtime/gpu-job.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 model=WhisperForConditionalGeneration.from_pretrained(model_path,local_files_only=True,dtype=torch.float16,attn_implementation='eager').to('cuda').eval()
 processor=AutoProcessor.from_pretrained(model_path,local_files_only=True)
 pipe=pipeline('automatic-speech-recognition',model=model,tokenizer=processor.tokenizer,feature_extractor=processor.feature_extractor,device=0)
 all_words=[]; all_missing=[]
 for index in range(min(count,a.limit) if a.limit else count):
  core_start=index*20;core_end=min(duration,core_start+20)
  start=max(0,core_start-5);end=min(duration,core_end+5)
  checkpoint=check/f'{index:05d}.json'
  if checkpoint.exists():result=json.loads(checkpoint.read_text())
  else:
   result=pipe({'raw':x[round(start*sr):round(end*sr)],'sampling_rate':sr},return_timestamps='word',generate_kwargs={'language':'russian','task':'transcribe','num_beams':1,'max_new_tokens':440,'no_repeat_ngram_size':0,'repetition_penalty':1.0})
   result={'window_start':start,'window_end':end,'core_start':core_start,'core_end':core_end,'raw_response':result}
   write_json(checkpoint,result)
  words=[]
  for w in result['raw_response'].get('chunks',[]):
   v=owned_word(w,start,core_start,core_end)
   if v:words.append(v)
   elif any(t is None for t in w['timestamp']):all_missing.append({'window':index,'word':w})
  all_words.extend(words)
  state={'completed':index+1,'total':count,'core_end':core_end,'words':len(all_words)}
  write_json(audit/'independent-status.json',state)
  print(f"[{time.strftime('%H:%M:%S')}] independent ASR {index+1}/{count}, words={len(all_words)}",flush=True)
 write_json(audit/'independent-asr.json',{'config':config,'duration_seconds':duration,'complete':not a.limit or a.limit>=count,'words':all_words,'unpositioned_words':all_missing})

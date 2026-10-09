"""Generate a qualified evidence report; cross-ASR agreement is not ground truth."""
import argparse, collections, difflib, json, re, subprocess, wave
from pathlib import Path
from meeting_transcriber.completeness import union_intervals, uncovered_intervals, normalize_words
from meeting_transcriber.local_audio import assign_speakers, write_json
p=argparse.ArgumentParser();p.add_argument('job',type=Path);args=p.parse_args()
j=args.job.resolve();base=j/'_audit';a=base/'completeness'
asr=json.loads((base/'asr.json').read_text())['segments']
diar=json.loads((base/'diarization.json').read_text())['segments']
silero=json.loads((a/'silero-speech.json').read_text())['segments']
other=json.loads((a/'independent-asr.json').read_text());assert other['complete']
words=other['words'];parts=json.loads((base/'source-parts.json').read_text())
assembly=json.loads((a/'source-assembly-check.json').read_text())
with wave.open(str(base/'audio.wav')) as audio:duration=audio.getnframes()/audio.getframerate()
def stamp(v):
 v=int(v);return f'{v//3600:02d}:{v//60%60:02d}:{v%60:02d}'
def coverage(rows):
 speech=union_intervals((x['start'],x['end']) for x in rows)
 gaps=uncovered_intervals(speech,[(x['start'],x['end']) for x in asr])
 total=sum(e-s for s,e in speech);missing=sum(e-s for s,e in gaps)
 return {'speech_seconds':total,'uncovered_seconds':missing,'time_coverage_fraction':1-missing/total,'gaps':gaps}
metrics={'duration_seconds':duration,'assembly':assembly,'nemotron':coverage(diar),'silero':coverage(silero),'asr_windows':len(list((j/'checkpoints').glob('asr-*.json'))),'independent_windows':len(list((a/'independent-checkpoints').glob('*.json'))),'independent_word_entries':len(words),'unpositioned_words':other['unpositioned_words'],'does_not_prove_word_completeness':True}
old_tokens=[];old_meta=[]
for row in asr:
 for t in normalize_words(row['text']):old_tokens.append(t);old_meta.append(row)
new_tokens=[];new_meta=[]
for row in words:
 for t in normalize_words(row['text']):new_tokens.append(t);new_meta.append(row)
matcher=difflib.SequenceMatcher(None,old_tokens,new_tokens,autojunk=False)
candidates=[]
for tag,i1,i2,k1,k2 in matcher.get_opcodes():
 if tag=='equal' or k2-k1<4:continue
 ns=new_meta[k1:k2];os=old_meta[i1:i2]
 if not ns:continue
 old_rows=list({id(x):x for x in os}.values())
 new_rows=list({id(x):x for x in ns}.values())
 candidates.append({'tag':tag,'start':ns[0]['start'],'end':ns[-1]['end'],'independent_tokens':k2-k1,'original_tokens':i2-i1,'original_text':' '.join(x['text'] for x in old_rows),'independent_text':' '.join(x['text'].strip() for x in new_rows),'confirmed_omission':False})
write_json(a/'text-disagreements.json',candidates)
write_json(a/'coverage-evidence.json',metrics)
# A separate control transcript, with speaker labels from audio, not from an LLM.
assigned=[]
for w in words:
 if w['end']>w['start'] and 0<=w['start']<duration:
  assigned.append(assign_speakers([w],diar)[0])
 else:
  assigned.append({**w,'speaker':'UNRESOLVED','needs_review':True,'speaker_candidates':[]})
groups=[]
for w in assigned:
 if groups and all(groups[-1][k]==w[k] for k in ['speaker','needs_review']) and w['start']-groups[-1]['end']<1.5 and w['end']-groups[-1]['start']<25:
  groups[-1]['text']+=' '+w['text'].strip();groups[-1]['end']=w['end']
 else:groups.append({**w,'text':w['text'].strip()})
write_json(a/'control-transcript.json',{'segments':groups,'model':other['config'],'human_verified':False})
lines=['# Контрольная стенограмма разговора','Независимое распознавание BuzzASR Russian. Автоматический черновик, не эталон и не проверенная дословная запись. Метки по словам рассчитаны аудиомоделью. Голоса назначены по Nemotron; сомнения отмечены. Исходная стенограмма VibeVoice сохранена отдельно.']
boundary=parts['sources'][1]['offset_seconds'];marked=False
for row in groups:
 if not marked and row['start']>=boundary:
  lines.append(f'## Продолжение после разрыва связи\n\n[{stamp(boundary)}] Начало второй записи.');marked=True
 who={'SPEAKER_00':'Участник 1','SPEAKER_01':'Участник 2','UNRESOLVED':'Говорящий не определён'}[row['speaker']]
 if row['needs_review']:who+=' [проверить]'
 lines.append(f"[{stamp(row['start'])}] **{who}:** {row['text']}")
(j/'documents/Контрольная_стенограмма_BuzzASR.md').write_text('\n\n'.join(lines)+'\n')
# Export every substantial uncovered speech interval with surrounding audio.
gaps=metrics['silero']['gaps'];clip_ranges=[]
for s,e in gaps:
 if e-s<.3:continue
 s=max(0,s-4);e=min(duration,e+4)
 if clip_ranges and s<=clip_ranges[-1][1]:clip_ranges[-1][1]=max(e,clip_ranges[-1][1])
 else:clip_ranges.append([s,e])
(a/'audio-excerpts').mkdir(exist_ok=True)
clips=[]
for index,(s,e) in enumerate(clip_ranges):
 path=a/'audio-excerpts'/f'gap-{index+1:02d}.wav'
 subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-ss',str(s),'-i',str(base/'audio.wav'),'-t',str(e-s),'-c:a','pcm_s16le',str(path)],check=True)
 text=' '.join(w['text'].strip() for w in words if w['start']<e and w['end']>s)
 clips.append({'start':s,'end':e,'file':str(path),'independent_text':text})
write_json(a/'gap-excerpts.json',clips)
report=['# Проверка полноты стенограммы',
 '**Вывод: сохранность входного аудио подтверждена; стопроцентная полнота слов исходной стенограммы не доказана.** Независимое распознавание выявило расхождения. Они требуют прослушивания: вариант второй модели тоже может ошибаться.',
 '## Что проверено точно',
 f"Обе части декодированы отдельно и сравнены с объединённой записью: {assembly['combined_frames']:,} аудиосэмплов при {assembly['sampling_rate']} Гц, без потерянных или добавленных сэмплов; совпадение значений 100%. Длительность {stamp(round(duration))}. SHA256 оригинальных файлов сохранены в `source-parts.json`.",
 f"Первое распознавание охватило {metrics['asr_windows']} четырёхминутных фрагментов, независимое — {metrics['independent_windows']} окон с основным шагом 20 секунд и перекрытием 5 секунд. Это проверка обработки всей длительности, не гарантия сохранения каждого слова.",
 '## Покрытие предполагаемой речи временными метками',
 '| Детектор | Найдено речи, с | Вне меток стенограммы, с | Покрытие времени |','|---|---:|---:|---:|']
for name in ['nemotron','silero']:
 m=metrics[name];report.append(f"| {name} | {m['speech_seconds']:.2f} | {m['uncovered_seconds']:.2f} | {100*m['time_coverage_fraction']:.3f}% |")
report+=['**Это не процент распознанных слов и не WER.** Длинный интервал текста может накрывать пропущенный короткий ответ. Детекторы могут ошибаться на музыке, шумах и фоновых голосах.',
 '## Фрагменты для проверки возможных пропусков']
for clip in clips:
 report.append(f"### {stamp(clip['start'])} — {stamp(clip['end'])}\n\n[Прослушать фрагмент]({clip['file']})\n\nВторое распознавание: {clip['independent_text'] or 'Текст не получен.'}")
report+=['## Крупные расхождения между распознавателями','Ниже — кандидаты на ошибки, а не подтверждённые пропуски. Все расхождения и точные метки сохранены в `text-disagreements.json`.']
for c in sorted(candidates,key=lambda c:c['independent_tokens'],reverse=True)[:20]:
 report.append(f"### {stamp(c['start'])}\n\nVibeVoice: {c['original_text'] or 'Нет сопоставленного текста.'}\n\nBuzzASR: {c['independent_text']}")
report+=['## Ограничения независимого распознавания','Вторая модель тоже может выдумывать речь на шуме или повторять слова во время ожидания. Её текст не вставлен автоматически в первую стенограмму. Расхождение двух моделей является основанием для проверки аудио, а не доказательством того, какая версия верна.','## Что осталось недоказанным','Нет вручную расшифрованного эталона всей записи. Поэтому нельзя честно заявить 100% полноту, вычислить WER или подтвердить все назначения говорящих. Для строгой пословной проверки требуется прослушать всю запись, включая наложения голосов, и сверить её с эталонной разметкой. Исходные результаты обеих моделей и аудиофрагменты сохранены для такой проверки.']
report_text='\n\n'.join(report)+'\n'
report_text=re.sub(r'(?m)^(\|[^\n]*\|)\n\n(?=\|)',r'\1\n',report_text)
(j/'documents/Проверка_полноты.md').write_text(report_text)
print(json.dumps({k:v for k,v in metrics.items() if k not in ['nemotron','silero','unpositioned_words']},ensure_ascii=False))
print('Disagreements',len(candidates),'gap clips',len(clips),'control speaker review groups',sum(x['needs_review'] for x in groups),'of',len(groups))

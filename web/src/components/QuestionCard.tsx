import { useState } from 'react';
import { Button, Textarea, Alert } from '@mantine/core';
import { MessageSquareText, ArrowRight } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Question } from '../api/client';

/** Collects reviewer context and resumes an audit that is awaiting input. */
export default function QuestionCard({question,auditId}:{question:Question;auditId:string}) {
  const [answer,setAnswer] = useState('');
  const queryClient = useQueryClient();
  const send = useMutation({mutationFn:()=>api.answer(auditId,{question_id:question.id,answer:answer.trim()}),onSuccess:job=>queryClient.setQueryData(['audit',auditId],job)});
  return <section className="question-card" aria-labelledby="question-title"><div className="question-icon"><MessageSquareText size={23}/></div><div className="question-body">
    <div className="eyebrow">YOUR CONTEXT MATTERS / {question.code}</div><h3 id="question-title">{question.text}</h3><p>{question.context}</p>
    <form onSubmit={event=>{event.preventDefault();if(answer.trim())send.mutate();}}>
      <Textarea label="Your answer" placeholder="Tell us what this payment is for…" value={answer} onChange={event=>setAnswer(event.currentTarget.value)} maxLength={2000} minRows={2} autosize required disabled={send.isPending}/>
      {send.error&&<Alert color="red" mt="sm">{send.error.message}</Alert>}
      <Button type="submit" mt="sm" loading={send.isPending} disabled={!answer.trim()} rightSection={<ArrowRight size={15}/>}>Save answer & continue</Button>
    </form>
  </div></section>;
}

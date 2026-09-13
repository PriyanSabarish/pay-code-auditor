import { useState } from 'react';
import { Accordion, Alert, Button, Modal, Select, Textarea, TextInput, Progress } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowDownToLine, ArrowUpDown, Check, ChevronDown, Copy, ExternalLink, FileText, Search, ShieldCheck } from 'lucide-react';
import { api, money, safeSource, statusLabels } from '../api/client';
import type { AuditResult, CodeVerdict, VerdictRequest } from '../api/client';
import QuestionCard from './QuestionCard';

type FindingFilter = 'all'|'unreviewed'|CodeVerdict['status'];
const findingFilters: Array<{value:FindingFilter;label:string}> = [
  {value:'all',label:'All codes'},
  {value:'unreviewed',label:'Unreviewed'},
  {value:'needs_review',label:'Needs review'},
  {value:'should_count',label:'Possible shortfall'},
  {value:'counts_but_shouldnt',label:'Possible overpayment'},
  {value:'correct',label:'Correct'},
];

/** Presents audit progress, findings, evidence, and reviewer decisions. */
export default function Results({job,businessLabel}:{job:AuditResult;businessLabel:string}) {
  const queryClient = useQueryClient();
  const [filter,setFilter] = useState<FindingFilter>('all');
  const [search,setSearch] = useState('');
  const [sort,setSort] = useState<'code'|'impact'>('code');
  const [desc,setDesc] = useState(false);
  const [expanded,setExpanded] = useState<string|null>(null);
  const [override,setOverride] = useState<CodeVerdict|null>(null);
  const [treatment,setTreatment] = useState('unclear');
  const [note,setNote] = useState('');
  const [letterCode,setLetterCode] = useState<string|null>(null);
  const [copyState,setCopyState] = useState('Copy text');
  const letter = useQuery({queryKey:['letter',job.audit_id,letterCode],queryFn:({signal})=>api.letter(job.audit_id,letterCode!,signal),enabled:!!letterCode,staleTime:0});
  const decision = useMutation({
    mutationFn:({code,body}:{code:string;body:VerdictRequest})=>api.decide(job.audit_id,code,body),
    onMutate:async ({code,body})=>{
      await queryClient.cancelQueries({queryKey:['audit',job.audit_id]});
      const previous = queryClient.getQueryData<AuditResult>(['audit',job.audit_id]);
      if(previous) queryClient.setQueryData(['audit',job.audit_id],{...previous,verdicts:previous.verdicts.map(v=>v.code===code?{...v,reviewer_decision:body.decision,override_note:body.note??null,overridden_counts_towards_super:body.overridden_counts_towards_super??null}:v)});
      return {previous};
    },
    onError:(_error,_variables,context)=>{if(context?.previous)queryClient.setQueryData(['audit',job.audit_id],context.previous);},
    onSuccess:()=>{setOverride(null);setNote('');},
    onSettled:()=>{void queryClient.invalidateQueries({queryKey:['audit',job.audit_id]});void queryClient.invalidateQueries({queryKey:['letter',job.audit_id]});},
  });
  const verdicts = job.verdicts??[];
  const rows = verdicts.filter(v=>{
    const matchesFilter=filter==='all'||(filter==='unreviewed'?!v.reviewer_decision:v.status===filter);
    return matchesFilter&&`${v.code} ${v.name}`.toLowerCase().includes(search.toLowerCase());
  }).sort((a,b)=>{
    const impact=(v:CodeVerdict)=>v.impact?.super_amount??0;
    const comparison=sort==='code'?a.code.localeCompare(b.code):impact(a)-impact(b);
    return desc?-comparison:comparison;
  });
  const complete = job.status==='complete';
  const sortBy=(column:'code'|'impact')=>{if(sort===column)setDesc(!desc);else{setSort(column);setDesc(false);}};
  const reviewed=verdicts.filter(v=>v.reviewer_decision).length;
  const unreviewed=verdicts.filter(v=>!v.reviewer_decision);
  const active=verdicts.find(v=>v.code===expanded);
  const shortfall=verdicts.filter(v=>v.status==='should_count').reduce((sum,v)=>sum+(v.impact?.super_amount??0),0);
  const overpayment=verdicts.filter(v=>v.status==='counts_but_shouldnt').reduce((sum,v)=>sum+(v.impact?.super_amount??0),0);
  const total=job.progress.total_codes||1;
  const openQueue=()=>{
    setFilter('unreviewed');
    setExpanded(unreviewed[0]?.code??null);
    requestAnimationFrame(()=>document.getElementById('evidence-panel')?.scrollIntoView({behavior:'smooth',block:'start'}));
  };
  return <section id="results" className="results-section fade-in" aria-label="Audit results">
    <div className="section-heading"><div><div className="eyebrow">02 / YOUR FINDINGS</div><h2>{businessLabel}</h2></div>
      {complete?<a download className={`button-secondary ${decision.isPending?'disabled-link':''}`} aria-disabled={decision.isPending} href={decision.isPending?undefined:api.reportUrl(job.audit_id)}><ArrowDownToLine size={16}/> Export report</a>:<span className="small-mono">{job.progress.processed_codes} OF {job.progress.total_codes} CODES</span>}
    </div>
    <div className="progress-panel" aria-live="polite"><div><span className={`status-dot ${complete?'done':''}`}/><strong>{job.status==='failed'?'Review interrupted':complete?'All pay codes reviewed':job.progress.current_step??'Working through pay codes'}</strong><span className="small-mono">{job.progress.processed_codes}/{job.progress.total_codes}</span></div><Progress value={100*job.progress.processed_codes/total} size={4} color="rust" animated={job.status==='running'}/></div>
    {job.status==='failed'&&<Alert color="red" title="This audit could not finish">{job.error??'Please start a new review. Any partial findings below are incomplete.'}</Alert>}
    {job.pending_question&&<QuestionCard key={job.pending_question.id} question={job.pending_question} auditId={job.audit_id}/>}
    {verdicts.length>0&&<>
      <div className="summary-grid"><div className="summary-cell"><span>POTENTIAL ANNUAL SHORTFALL</span><strong className="rust-text">{money(shortfall)}</strong><small>Estimated · subject to review</small></div>
      <div className="summary-cell"><span>POTENTIAL OVERPAYMENT</span><strong>{money(overpayment)}</strong><small>Estimated · subject to review</small></div>
      <button className="summary-cell summary-button" onClick={()=>setFilter('needs_review')}><span>NEEDS YOUR REVIEW <ChevronDown size={13}/></span><strong>{verdicts.filter(v=>v.status==='needs_review').length.toString().padStart(2,'0')}</strong><small>Open the review queue →</small></button>
      <button className="summary-cell summary-button" onClick={openQueue} disabled={!unreviewed.length}><span>REVIEWER QUEUE</span><strong>{unreviewed.length.toString().padStart(2,'0')}<em> / {verdicts.length}</em></strong><small>{decision.isPending?'Saving decision…':unreviewed.length?`${reviewed} reviewed · open next →`:'Queue complete'}</small></button></div>
      <div className="results-toolbar"><div className="filter-pills" aria-label="Filter findings">{findingFilters.map(({value,label})=><button key={value} aria-pressed={filter===value} className={filter===value?'selected':''} onClick={()=>setFilter(value)}>{label}</button>)}</div><TextInput aria-label="Search pay codes" placeholder="Find a pay code…" value={search} onChange={e=>setSearch(e.currentTarget.value)} leftSection={<Search size={15}/>}/></div>
      {decision.error&&<Alert color="red" mb="md" title="Decision not saved">{decision.error.message} Your previous decision has been restored.</Alert>}
      <div className="table-scroll" id="results-table"><table className="findings-table"><caption className="sr-only">Pay code findings. Select a row's Review button to inspect the evidence.</caption><thead><tr><th scope="col" aria-sort={sort==='code'?(desc?'descending':'ascending'):'none'}><button onClick={()=>sortBy('code')}>PAY CODE <ArrowUpDown size={12}/></button></th><th scope="col">FINDING</th><th scope="col" aria-sort={sort==='impact'?(desc?'descending':'ascending'):'none'}><button onClick={()=>sortBy('impact')}>SUPER IMPACT <ArrowUpDown size={12}/></button></th><th scope="col">DECISION</th><th scope="col"><span className="sr-only">Inspect finding</span></th></tr></thead><tbody>{rows.map(v=><tr key={v.code} className={expanded===v.code?'active-row':''}><td><code>{v.code}</code><small>{v.name}</small></td><td><span className={`status-badge ${v.status}`}>{statusLabels[v.status]}</span></td><td className="money-cell">{v.impact?money(v.impact.super_amount):'—'}</td><td><span className="decision-label">{v.reviewer_decision?<><Check size={13}/>{v.reviewer_decision==='approved'?'Approved':'Overridden'}</>:'Not reviewed'}</span></td><td><button className="review-button" aria-label={`Review ${v.code}`} aria-expanded={expanded===v.code} onClick={()=>setExpanded(expanded===v.code?null:v.code)}>Review <ChevronDown size={14}/></button></td></tr>)}</tbody></table></div>
      {rows.length===0&&(verdicts.length>0||complete)?<div className="empty-results"><Search size={24}/><h3>No matching pay codes</h3><p>Try another search or clear the selected filter.</p><Button variant="subtle" onClick={()=>{setSearch('');setFilter('all');}}>Clear filters</Button></div>:verdicts.length===0&&<div className="loading-panel" role="status"><h3>Preparing the first findings…</h3><p>Results will appear as each pay code is reviewed.</p></div>}
      {active&&<section id="evidence-panel" className="evidence-panel fade-in" aria-label={`Evidence for ${active.code}`}><div className="evidence-top"><div><span className="eyebrow">THE REASONING TRAIL</span><h3>{active.code} <span>{active.name}</span></h3></div><button className="text-button" onClick={()=>setExpanded(null)}>Close details ×</button></div>
      <div className="evidence-grid"><div><p className="reasoning-copy">{active.classification.reasoning}</p><Accordion defaultValue="trail" variant="separated"><Accordion.Item value="trail"><Accordion.Control>Investigation steps <span className="small-mono"> / {active.investigation.length}</span></Accordion.Control><Accordion.Panel>{active.investigation.length?<ol className="trail">{active.investigation.map((step)=><li key={`${step.tool}-${step.step_number}`}><span>{String(step.step_number).padStart(2,'0')}</span><div><code>{step.tool}</code><p>{step.output}</p></div></li>)}</ol>:<p className="reasoning-copy">This code was classified with high confidence; no investigation was needed.</p>}</Accordion.Panel></Accordion.Item><Accordion.Item value="citations"><Accordion.Control>Sources & supporting passages</Accordion.Control><Accordion.Panel>{active.classification.citations.length?active.classification.citations.map((citation,i)=><blockquote key={i}><strong>{citation.source} — {citation.reference}</strong><p>{citation.text}</p>{safeSource(citation.url)&&<a href={safeSource(citation.url)} target="_blank" rel="noreferrer">View original source <ExternalLink size={12}/></a>}</blockquote>):<p>No supporting citation returned. This finding needs professional review.</p>}</Accordion.Panel></Accordion.Item></Accordion></div>
      <aside className="decision-panel"><div className="eyebrow"><ShieldCheck size={15}/> VERIFICATION</div><p>{active.verifier_agreed===true?'The verifier checked this conclusion against the cited rule and agreed.':active.verifier_agreed===false?'The verifier disagreed with this conclusion — sent for human review.':'Not yet verified.'}</p><dl><div><dt>Model confidence</dt><dd>{active.classification.confidence}</dd></div><div><dt>Recommended treatment</dt><dd>{active.classification.counts_towards_super}</dd></div>{active.impact&&<div><dt>Estimated super impact</dt><dd>{money(active.impact.super_amount)}</dd></div>}{active.impact?.max_penalty_uplift!=null&&<div><dt>Penalty exposure</dt><dd>Up to {money(active.impact.max_penalty_uplift)}</dd></div>}</dl>
        {active.reviewer_decision&&<p className="saved-note">Saved: {active.reviewer_decision}{active.overridden_counts_towards_super&&` · ${active.overridden_counts_towards_super}`}{active.override_note&&` — ${active.override_note}`}</p>}
        <Button fullWidth leftSection={<Check size={16}/>} disabled={!complete||decision.isPending} loading={decision.isPending&&decision.variables?.code===active.code} onClick={()=>decision.mutate({code:active.code,body:{decision:'approved'}})}>Approve recommendation</Button>
        <Button mt="xs" fullWidth variant="outline" disabled={!complete||decision.isPending} onClick={()=>{setTreatment(active.overridden_counts_towards_super??active.classification.counts_towards_super);setNote('');setOverride(active);}}>Override treatment</Button>
        {!complete&&<p className="fine-print">Finish the investigation before saving decisions.</p>}
        {active.reviewer_decision&&<Button mt="xs" fullWidth variant="subtle" leftSection={<FileText size={15}/>} onClick={()=>{setCopyState('Copy text');setLetterCode(active.code);}}>View draft letter</Button>}
      </aside></div></section>}
      <div className="results-foot"><span>{rows.length} OF {verdicts.length} FINDINGS SHOWN · {unreviewed.length} UNREVIEWED</span><span>ALL RECOMMENDATIONS REQUIRE PROFESSIONAL REVIEW</span></div>
    </>}
    <Modal opened={!!override} onClose={()=>{if(!decision.isPending)setOverride(null);}} title={`Override ${override?.code??''}`} centered>
      <p className="muted">Your decision is recorded alongside the original recommendation.</p><Select label="Should this payment count towards super?" data={[{value:'yes',label:'Yes'},{value:'no',label:'No'},{value:'unclear',label:'Unclear — needs review'}]} value={treatment} onChange={value=>setTreatment(value??'unclear')} allowDeselect={false}/><Textarea mt="md" label="Reason for override" required value={note} onChange={event=>setNote(event.currentTarget.value)} maxLength={2000} minRows={3}/>
      {decision.error&&<Alert color="red" mt="sm">{decision.error.message}</Alert>}<Button mt="md" fullWidth loading={decision.isPending} disabled={!note.trim()} onClick={()=>{if(override)decision.mutate({code:override.code,body:{decision:'overridden',overridden_counts_towards_super:treatment as VerdictRequest['overridden_counts_towards_super'],note:note.trim()}});}}>Save reviewer decision</Button>
    </Modal>
    <Modal opened={!!letterCode} onClose={()=>setLetterCode(null)} title="Draft client letter" size="lg" centered><div className="sample-banner">DRAFT FOR PROFESSIONAL REVIEW</div>{letter.isPending?<p>Preparing your draft…</p>:letter.error?<Alert color="red">{letter.error.message}<Button onClick={()=>void letter.refetch()} variant="subtle">Retry</Button></Alert>:letter.data&&<><pre className="letter-text">{letter.data.subject}{'\n\n'}{letter.data.body}</pre><div className="flex gap-3 flex-wrap"><Button variant="outline" leftSection={<Copy size={15}/>} onClick={async()=>{try{await navigator.clipboard.writeText(`${letter.data.subject}\n\n${letter.data.body}`);setCopyState('Copied');}catch{setCopyState('Select text to copy');}}}>{copyState}</Button><a download className="button-secondary" href={api.letterUrl(job.audit_id,letterCode!)}><ArrowDownToLine size={15}/> Download draft</a></div></>}</Modal>
  </section>;
}

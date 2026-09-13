import { useEffect, useState } from 'react';
import { Accordion, Alert, Button, Modal, Select, Textarea, TextInput } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowUpDown, BarChart3, Check, ChevronDown, CircleAlert, Coins, Copy, ExternalLink, FileText, Plus, Search, ShieldCheck, TriangleAlert } from 'lucide-react';
import { api, money, safeSource, statusLabels } from '../api/client';
import type { AuditResult, CodeVerdict, VerdictRequest } from '../api/client';
import QuestionCard from './QuestionCard';
import AuditLoading from './AuditLoading';

type FindingFilter = 'all'|'unreviewed'|CodeVerdict['status'];
const findingFilters: Array<{value:FindingFilter;label:string}> = [
  {value:'all',label:'All codes'}, {value:'unreviewed',label:'Unreviewed'},
  {value:'needs_review',label:'Needs review'}, {value:'should_count',label:'Possible shortfall'},
  {value:'counts_but_shouldnt',label:'Possible overpayment'}, {value:'correct',label:'Correct'},
];
const titleCase=(value:string)=>value.replaceAll('_',' ').replace(/^./,letter=>letter.toUpperCase());

/** Presents audit progress, findings, evidence, and reviewer decisions. */
export default function Results({job,businessLabel,onNewReview}:{job:AuditResult;businessLabel:string;onNewReview:()=>void}) {
  const queryClient = useQueryClient();
  const [filter,setFilter] = useState<FindingFilter>('all');
  const [search,setSearch] = useState('');
  const [sort,setSort] = useState<'code'|'impact'>('code');
  const [desc,setDesc] = useState(false);
  const [expanded,setExpanded] = useState<string|null>(null);
  const [autoSelected,setAutoSelected] = useState(false);
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
  useEffect(()=>{
    if(!autoSelected&&verdicts.length){setExpanded((verdicts.find(v=>v.status!=='correct')??verdicts[0]).code);setAutoSelected(true);}
  },[autoSelected,verdicts]);
  const rows = verdicts.filter(v=>{
    const matchesFilter=filter==='all'||(filter==='unreviewed'?!v.reviewer_decision:v.status===filter);
    return matchesFilter&&`${v.code} ${v.name}`.toLowerCase().includes(search.toLowerCase());
  }).sort((a,b)=>{
    const impact=(v:CodeVerdict)=>v.impact?.super_amount??0;
    const comparison=sort==='code'?a.code.localeCompare(b.code):impact(a)-impact(b);
    return desc?-comparison:comparison;
  });
  const complete=job.status==='complete';
  const reviewed=verdicts.filter(v=>v.reviewer_decision).length;
  const unreviewed=verdicts.filter(v=>!v.reviewer_decision);
  const needsReview=verdicts.filter(v=>v.status==='needs_review').length;
  const active=verdicts.find(v=>v.code===expanded)??null;
  const shortfall=verdicts.filter(v=>v.status==='should_count').reduce((sum,v)=>sum+(v.impact?.super_amount??0),0);
  const overpayment=verdicts.filter(v=>v.status==='counts_but_shouldnt').reduce((sum,v)=>sum+(v.impact?.super_amount??0),0);
  const total=job.progress.total_codes||1;
  const progress=Math.min(100,100*job.progress.processed_codes/total);
  const sortBy=(column:'code'|'impact')=>{if(sort===column)setDesc(!desc);else{setSort(column);setDesc(false);}};
  const filterCount=(value:FindingFilter)=>value==='all'?verdicts.length:value==='unreviewed'?unreviewed.length:verdicts.filter(v=>v.status===value).length;

  return <section id="results" className="results-section fade-in" aria-label="Audit results">
    <div className="audit-heading"><div><div className="breadcrumb">Reviews <span>/</span> Findings</div><h1>Payroll review</h1><p>{businessLabel} <span>·</span> {job.award_id}</p></div><Button variant="outline" leftSection={<Plus size={16}/>} onClick={onNewReview}>New review</Button></div>
    {job.status==='failed'&&<Alert color="red" title="This audit could not finish">{job.error??'Please start a new review. Any partial findings below are incomplete.'}</Alert>}
    {job.pending_question&&<QuestionCard key={job.pending_question.id} question={job.pending_question} auditId={job.audit_id}/>}
    {(job.status==='queued'||job.status==='running')&&!job.pending_question&&<AuditLoading compact={verdicts.length>0} processed={job.progress.processed_codes} total={job.progress.total_codes} step={job.progress.current_step}/>}
    {verdicts.length>0?<>
      <div className="metric-grid" aria-label="Audit summary">
        <article className="metric-card shortfall"><TriangleAlert/><div><span>Potential annual shortfall</span><strong>{money(shortfall)}</strong><small>Estimated</small></div></article>
        <article className="metric-card"><Coins/><div><span>Potential overpayment</span><strong>{money(overpayment)}</strong><small>Estimated</small></div></article>
        <button className="metric-card metric-action" onClick={()=>setFilter('needs_review')}><CircleAlert/><div><span>Needs attention</span><strong>{needsReview}</strong><small>pay codes</small></div></button>
        <button className="metric-card metric-action progress-metric" onClick={()=>{setFilter('unreviewed');setExpanded(unreviewed[0]?.code??null);}} disabled={!unreviewed.length}><BarChart3/><div><span>Review progress</span><strong>{reviewed} of {verdicts.length}</strong><div className="metric-progress" aria-label={`${reviewed} of ${verdicts.length} reviewed`}><i style={{width:`${verdicts.length?100*reviewed/verdicts.length:progress}%`}}/></div></div></button>
      </div>
      {decision.error&&<Alert color="red" mb="md" title="Decision not saved">{decision.error.message} Your previous decision has been restored.</Alert>}
      <div className="review-layout">
        <section className="findings-panel" aria-labelledby="findings-title">
          <div className="findings-header"><h2 id="findings-title">Pay code findings <span>({verdicts.length})</span></h2><TextInput aria-label="Search pay codes" placeholder="Find a pay code…" value={search} onChange={e=>setSearch(e.currentTarget.value)} leftSection={<Search size={15}/>}/></div>
          <div className="filter-pills" aria-label="Filter findings">{findingFilters.map(({value,label})=><button key={value} aria-pressed={filter===value} className={filter===value?'selected':''} onClick={()=>setFilter(value)}>{label} ({filterCount(value)})</button>)}</div>
          <div className="table-scroll" id="results-table"><table className="findings-table"><caption className="sr-only">Pay code findings. Select a row to inspect the evidence.</caption><thead><tr><th scope="col" aria-sort={sort==='code'?(desc?'descending':'ascending'):'none'}><button onClick={()=>sortBy('code')}>PAY CODE <ArrowUpDown size={11}/></button></th><th scope="col">FINDING</th><th scope="col" aria-sort={sort==='impact'?(desc?'descending':'ascending'):'none'}><button onClick={()=>sortBy('impact')}>SUPER IMPACT <ArrowUpDown size={11}/></button></th><th scope="col">DECISION</th><th scope="col"><span className="sr-only">Inspect</span></th></tr></thead><tbody>{rows.map(v=><tr key={v.code} className={expanded===v.code?'active-row':''}><td><code>{v.code}</code><small>{v.name}</small></td><td><span className={`status-badge ${v.status}`}>{statusLabels[v.status]}</span></td><td className="money-cell">{v.impact?money(v.impact.super_amount):'—'}</td><td><span className={`decision-label ${v.reviewer_decision?'reviewed':''}`}>{v.reviewer_decision&&<Check size={13}/>} {v.reviewer_decision?(v.reviewer_decision==='approved'?'Reviewed':'Overridden'):'Not reviewed'}</span></td><td><button className="row-open" aria-label={`Open evidence for ${v.code}`} aria-pressed={expanded===v.code} onClick={()=>setExpanded(v.code)}><ChevronDown size={16}/></button></td></tr>)}</tbody></table></div>
          {rows.length===0?<div className="empty-results"><Search size={24}/><h3>No matching pay codes</h3><p>Try another search or clear the selected filter.</p><Button variant="subtle" onClick={()=>{setSearch('');setFilter('all');}}>Clear filters</Button></div>:null}
          <div className="panel-foot"><span>{rows.length} OF {verdicts.length} FINDINGS SHOWN</span><span>ALL RECOMMENDATIONS REQUIRE PROFESSIONAL REVIEW</span></div>
        </section>
        <aside id="evidence-panel" className="evidence-card" aria-live="polite">
          {active?<>
            <div className="selected-badge">Selected pay code</div><h2>{active.code}</h2><p className="evidence-name">{active.name}</p><span className={`status-badge ${active.status}`}>{statusLabels[active.status]}</span>
            <p className="reasoning-copy">{active.classification.reasoning}</p>
            <div className="fact-grid"><div><ShieldCheck/><span>Confidence<strong>{titleCase(String(active.classification.confidence))}</strong></span></div><div><FileText/><span>Suggested treatment<strong>{titleCase(String(active.classification.counts_towards_super))}</strong></span></div><div><BarChart3/><span>Annual impact<strong>{active.impact?money(active.impact.super_amount):'—'}</strong></span></div></div>
            <div className="evidence-divider"/>
            <section className="trail-section"><h3>Evidence trail</h3>{active.investigation.length?<ol className="trail">{active.investigation.map(step=><li key={`${step.tool}-${step.step_number}`}><span>{step.step_number}</span><div><strong>{titleCase(step.tool)}</strong><p>{step.output}</p></div></li>)}</ol>:<p className="reasoning-copy">This code was classified with high confidence; no additional investigation was needed.</p>}</section>
            <Accordion variant="contained"><Accordion.Item value="sources"><Accordion.Control>Sources &amp; supporting passages</Accordion.Control><Accordion.Panel>{active.classification.citations.length?active.classification.citations.map((citation,i)=><blockquote key={i}><strong>{citation.source} — {citation.reference}</strong><p>{citation.text}</p>{safeSource(citation.url)&&<a href={safeSource(citation.url)} target="_blank" rel="noreferrer">View original source <ExternalLink size={12}/></a>}</blockquote>):<p>No supporting citation returned. This finding needs professional review.</p>}</Accordion.Panel></Accordion.Item></Accordion>
            {active.reviewer_decision&&<p className="saved-note">Saved: {active.reviewer_decision}{active.override_note&&` — ${active.override_note}`}</p>}
            <div className="evidence-actions"><Button leftSection={<Check size={16}/>} disabled={!complete||decision.isPending} loading={decision.isPending&&decision.variables?.code===active.code} onClick={()=>decision.mutate({code:active.code,body:{decision:'approved'}})}>Approve recommendation</Button><Button variant="subtle" disabled={!complete||decision.isPending} onClick={()=>{setTreatment(active.overridden_counts_towards_super??active.classification.counts_towards_super);setNote('');setOverride(active);}}>Override treatment</Button></div>
            {!complete&&<p className="fine-print">Finish the investigation before saving decisions.</p>}
            {active.reviewer_decision&&<Button mt="xs" fullWidth variant="subtle" leftSection={<FileText size={15}/>} onClick={()=>{setCopyState('Copy text');setLetterCode(active.code);}}>View draft letter</Button>}
          </>:<div className="evidence-empty"><ShieldCheck size={28}/><h2>Select a pay code</h2><p>Choose a finding to review its reasoning and supporting evidence.</p></div>}
        </aside>
      </div>
    </>:complete?<div className="loading-panel"><h3>No findings returned</h3><p>Start a new review to check another set of payroll files.</p></div>:null}
    <Modal opened={!!override} onClose={()=>{if(!decision.isPending)setOverride(null);}} title={`Override ${override?.code??''}`} centered><p className="muted">Your decision is recorded alongside the original recommendation.</p><Select label="Should this payment count towards super?" data={[{value:'yes',label:'Yes'},{value:'no',label:'No'},{value:'unclear',label:'Unclear — needs review'}]} value={treatment} onChange={value=>setTreatment(value??'unclear')} allowDeselect={false}/><Textarea mt="md" label="Reason for override" required value={note} onChange={event=>setNote(event.currentTarget.value)} maxLength={2000} minRows={3}/>{decision.error&&<Alert color="red" mt="sm">{decision.error.message}</Alert>}<Button mt="md" fullWidth loading={decision.isPending} disabled={!note.trim()} onClick={()=>{if(override)decision.mutate({code:override.code,body:{decision:'overridden',overridden_counts_towards_super:treatment as VerdictRequest['overridden_counts_towards_super'],note:note.trim()}});}}>Save reviewer decision</Button></Modal>
    <Modal opened={!!letterCode} onClose={()=>setLetterCode(null)} title="Draft client letter" size="lg" centered><div className="sample-banner">DRAFT FOR PROFESSIONAL REVIEW</div>{letter.isPending?<p>Preparing your draft…</p>:letter.error?<Alert color="red">{letter.error.message}<Button onClick={()=>void letter.refetch()} variant="subtle">Retry</Button></Alert>:letter.data&&<><pre className="letter-text">{letter.data.subject}{'\n\n'}{letter.data.body}</pre><div className="flex gap-3 flex-wrap"><Button variant="outline" leftSection={<Copy size={15}/>} onClick={async()=>{try{await navigator.clipboard.writeText(`${letter.data.subject}\n\n${letter.data.body}`);setCopyState('Copied');}catch{setCopyState('Select text to copy');}}}>{copyState}</Button><a download className="button-secondary" href={api.letterUrl(job.audit_id,letterCode!)}>Download draft</a></div></>}</Modal>
  </section>;
}

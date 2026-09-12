import { useState } from 'react';
import { Accordion, Alert, Button, Modal, Select, Textarea, TextInput, Progress } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowDownToLine, ArrowUpDown, Check, ChevronDown, Copy, ExternalLink, FileText, Search, ShieldCheck } from 'lucide-react';
import { api, money, safeSource, statusLabels } from '../api/client';
import type { AuditJob, Decision, Verdict } from '../api/client';
import QuestionCard from './QuestionCard';

export default function Results({job}:{job:AuditJob}) {
  const queryClient = useQueryClient();
  const [filter,setFilter] = useState('all');
  const [search,setSearch] = useState('');
  const [sort,setSort] = useState<'code'|'impact'>('code');
  const [desc,setDesc] = useState(false);
  const [expanded,setExpanded] = useState<string|null>(null);
  const [override,setOverride] = useState<Verdict|null>(null);
  const [treatment,setTreatment] = useState('unclear');
  const [note,setNote] = useState('');
  const [letterCode,setLetterCode] = useState<string|null>(null);
  const [copyState,setCopyState] = useState('Copy text');
  const letter = useQuery({queryKey:['letter',job.audit_id,letterCode],queryFn:({signal})=>api.letter(job.audit_id,letterCode!,signal),enabled:!!letterCode,staleTime:0});
  const decision = useMutation({
    mutationFn:({code,body}:{code:string;body:Decision})=>api.decide(job.audit_id,code,body),
    onMutate:async ({code,body})=>{
      await queryClient.cancelQueries({queryKey:['audit',job.audit_id]});
      const previous = queryClient.getQueryData<AuditJob>(['audit',job.audit_id]);
      if(previous) queryClient.setQueryData(['audit',job.audit_id],{...previous,result:previous.result?{...previous.result,verdicts:previous.result.verdicts.map(v=>v.code===code?{...v,decision:body}:v)}:null});
      return {previous};
    },
    onError:(_error,_variables,context)=>{if(context?.previous)queryClient.setQueryData(['audit',job.audit_id],context.previous);},
    onSuccess:()=>{setOverride(null);setNote('');},
    onSettled:()=>{void queryClient.invalidateQueries({queryKey:['audit',job.audit_id]});void queryClient.invalidateQueries({queryKey:['letter',job.audit_id]});},
  });
  const verdicts = job.result?.verdicts??[];
  const rows = verdicts.filter(v=>(filter==='all'||v.status===filter)&&`${v.code} ${v.name}`.toLowerCase().includes(search.toLowerCase())).sort((a,b)=>{
    const comparison=sort==='code'?a.code.localeCompare(b.code):a.annual_impact-b.annual_impact;
    return desc?-comparison:comparison;
  });
  const complete = job.status==='complete';
  const sortBy=(column:'code'|'impact')=>{if(sort===column)setDesc(!desc);else{setSort(column);setDesc(false);}};
  const reviewed=verdicts.filter(v=>v.decision).length;
  const active=verdicts.find(v=>v.code===expanded);
  return <section id="results" className="results-section fade-in" aria-label="Audit results">
    <div className="section-heading"><div><div className="eyebrow">02 / YOUR FINDINGS</div><h2>{job.result?.business??'A closer look is underway.'}</h2></div>
      {complete?<a className={`button-secondary ${decision.isPending?'disabled-link':''}`} aria-disabled={decision.isPending} href={decision.isPending?undefined:api.reportUrl(job.audit_id)}><ArrowDownToLine size={16}/> Export report</a>:<span className="small-mono">{job.progress.completed} OF {job.progress.total} CODES</span>}
    </div>
    {job.preview&&<div className="sample-banner"><span>ILLUSTRATIVE SAMPLE</span> Fictional verdicts and amounts. Your uploaded payroll has not been audited.</div>}
    <div className="progress-panel" aria-live="polite"><div><span className={`status-dot ${complete?'done':''}`}/><strong>{job.status==='failed'?'Review interrupted':job.progress.message}</strong><span className="small-mono">{job.progress.completed}/{job.progress.total}</span></div><Progress value={job.progress.total?100*job.progress.completed/job.progress.total:0} size={4} color="rust" animated={job.status==='running'}/></div>
    {job.status==='failed'&&<Alert color="red" title="This audit could not finish">{job.error??'Please start a new review. Any partial findings below are incomplete.'}</Alert>}
    {job.pending_question&&<QuestionCard key={job.pending_question.id} question={job.pending_question} auditId={job.audit_id}/>}
    {job.result&&<>
      <div className="summary-grid"><div className="summary-cell"><span>POTENTIAL ANNUAL SHORTFALL</span><strong className="rust-text">{money(job.result.summary.shortfall)}</strong><small>{job.preview?'Illustrative amount':'Estimated · subject to review'}</small></div>
      <div className="summary-cell"><span>POTENTIAL OVERPAYMENT</span><strong>{money(job.result.summary.overpayment)}</strong><small>{job.preview?'Illustrative amount':'Estimated · subject to review'}</small></div>
      <button className="summary-cell summary-button" onClick={()=>setFilter('review')}><span>NEEDS YOUR REVIEW <ChevronDown size={13}/></span><strong>{verdicts.filter(v=>v.status==='review').length.toString().padStart(2,'0')}</strong><small>Open the review queue →</small></button>
      <div className="summary-cell"><span>REVIEWER DECISIONS</span><strong>{reviewed.toString().padStart(2,'0')}<em> / {verdicts.length}</em></strong><small>{decision.isPending?'Saving decision…':'Saved with this audit'}</small></div></div>
      <div className="results-toolbar"><div className="filter-pills" aria-label="Filter findings">{[['all','All codes'],['review','Needs review'],['under','Possible shortfall'],['over','Possible overpayment'],['correct','Correct']].map(([value,label])=><button key={value} aria-pressed={filter===value} className={filter===value?'selected':''} onClick={()=>setFilter(value)}>{label}</button>)}</div><TextInput aria-label="Search pay codes" placeholder="Find a pay code…" value={search} onChange={e=>setSearch(e.currentTarget.value)} leftSection={<Search size={15}/>}/></div>
      {decision.error&&<Alert color="red" mb="md" title="Decision not saved">{decision.error.message} Your previous decision has been restored.</Alert>}
      <div className="table-scroll"><table className="findings-table"><caption className="sr-only">Pay code findings. Select a row's Review button to inspect the evidence.</caption><thead><tr><th scope="col" aria-sort={sort==='code'?(desc?'descending':'ascending'):'none'}><button onClick={()=>sortBy('code')}>PAY CODE <ArrowUpDown size={12}/></button></th><th scope="col">FINDING</th><th scope="col" aria-sort={sort==='impact'?(desc?'descending':'ascending'):'none'}><button onClick={()=>sortBy('impact')}>ANNUAL IMPACT <ArrowUpDown size={12}/></button></th><th scope="col">DECISION</th><th scope="col"><span className="sr-only">Inspect finding</span></th></tr></thead><tbody>{rows.map(v=><tr key={v.code} className={expanded===v.code?'active-row':''}><td><code>{v.code}</code><small>{v.name}</small></td><td><span className={`status-badge ${v.status}`}>{statusLabels[v.status]}</span></td><td className="money-cell">{v.annual_impact?money(v.annual_impact):'—'}</td><td><span className="decision-label">{v.decision?<><Check size={13}/>{v.decision.action==='approve'?'Approved':'Overridden'}</>:'Not reviewed'}</span></td><td><button className="review-button" aria-label={`Review ${v.code}`} aria-expanded={expanded===v.code} onClick={()=>setExpanded(expanded===v.code?null:v.code)}>Review <ChevronDown size={14}/></button></td></tr>)}</tbody></table></div>
      {rows.length===0&&(verdicts.length>0||complete)?<div className="empty-results"><Search size={24}/><h3>No matching pay codes</h3><p>Try another search or clear the selected filter.</p><Button variant="subtle" onClick={()=>{setSearch('');setFilter('all');}}>Clear filters</Button></div>:verdicts.length===0&&<div className="loading-panel" role="status"><h3>Preparing the first findings…</h3><p>Results will appear as each pay code is reviewed.</p></div>}
      {active&&<section className="evidence-panel fade-in" aria-label={`Evidence for ${active.code}`}><div className="evidence-top"><div><span className="eyebrow">THE REASONING TRAIL</span><h3>{active.code} <span>{active.name}</span></h3></div><button className="text-button" onClick={()=>setExpanded(null)}>Close details ×</button></div>
      <div className="evidence-grid"><div><p className="reasoning-copy">{active.reasoning}</p><Accordion defaultValue="trail" variant="separated"><Accordion.Item value="trail"><Accordion.Control>Investigation steps <span className="small-mono"> / {active.steps.length}</span></Accordion.Control><Accordion.Panel><ol className="trail">{active.steps.map((step,i)=><li key={`${step.tool}-${i}`}><span>{String(i+1).padStart(2,'0')}</span><div><code>{step.tool}</code><p>{step.summary}</p></div></li>)}</ol></Accordion.Panel></Accordion.Item><Accordion.Item value="citations"><Accordion.Control>Sources & supporting passages</Accordion.Control><Accordion.Panel>{active.citations.length?active.citations.map((citation,i)=><blockquote key={i}><strong>{citation.clause}</strong><p>{citation.text}</p>{safeSource(citation.url)&&<a href={safeSource(citation.url)} target="_blank" rel="noreferrer">View original source <ExternalLink size={12}/></a>}</blockquote>):<p>No supporting citation returned. This finding needs professional review.</p>}</Accordion.Panel></Accordion.Item></Accordion></div>
      <aside className="decision-panel"><div className="eyebrow"><ShieldCheck size={15}/> VERIFICATION</div><p>{active.verifier}</p><dl><div><dt>Model confidence</dt><dd>{active.confidence}</dd></div><div><dt>Recommended treatment</dt><dd>{active.counts_towards_super}</dd></div><div><dt>{job.preview?'Illustrative impact':'Estimated impact'}</dt><dd>{money(active.annual_impact)}</dd></div></dl>
        {active.decision&&<p className="saved-note">Saved: {active.decision.action} · {active.decision.treatment}{active.decision.note&&` — ${active.decision.note}`}</p>}
        <Button fullWidth leftSection={<Check size={16}/>} disabled={!complete||decision.isPending} loading={decision.isPending&&decision.variables?.code===active.code} onClick={()=>decision.mutate({code:active.code,body:{action:'approve',treatment:active.counts_towards_super,note:''}})}>Approve recommendation</Button>
        <Button mt="xs" fullWidth variant="outline" disabled={!complete||decision.isPending} onClick={()=>{setTreatment(active.decision?.treatment??active.counts_towards_super);setNote('');setOverride(active);}}>Override treatment</Button>
        {!complete&&<p className="fine-print">Finish the investigation before saving decisions.</p>}
        {active.decision&&<Button mt="xs" fullWidth variant="subtle" leftSection={<FileText size={15}/>} onClick={()=>{setCopyState('Copy text');setLetterCode(active.code);}}>View draft letter</Button>}
      </aside></div></section>}
      <div className="results-foot"><span>{rows.length} OF {verdicts.length} FINDINGS SHOWN</span><span>ALL RECOMMENDATIONS REQUIRE PROFESSIONAL REVIEW</span></div>
    </>}
    <Modal opened={!!override} onClose={()=>{if(!decision.isPending)setOverride(null);}} title={`Override ${override?.code??''}`} centered>
      <p className="muted">Your decision is recorded alongside the original recommendation.</p><Select label="Should this payment count towards super?" data={[{value:'yes',label:'Yes'},{value:'no',label:'No'},{value:'unclear',label:'Unclear — needs review'}]} value={treatment} onChange={value=>setTreatment(value??'unclear')} allowDeselect={false}/><Textarea mt="md" label="Reason for override" required value={note} onChange={event=>setNote(event.currentTarget.value)} maxLength={2000} minRows={3}/>
      {decision.error&&<Alert color="red" mt="sm">{decision.error.message}</Alert>}<Button mt="md" fullWidth loading={decision.isPending} disabled={!note.trim()} onClick={()=>{if(override)decision.mutate({code:override.code,body:{action:'override',treatment:treatment as Decision['treatment'],note:note.trim()}});}}>Save reviewer decision</Button>
    </Modal>
    <Modal opened={!!letterCode} onClose={()=>setLetterCode(null)} title="Draft client letter" size="lg" centered><div className="sample-banner">DRAFT FOR PROFESSIONAL REVIEW{job.preview?' · FICTIONAL SAMPLE':''}</div>{letter.isPending?<p>Preparing your draft…</p>:letter.error?<Alert color="red">{letter.error.message}<Button onClick={()=>void letter.refetch()} variant="subtle">Retry</Button></Alert>:letter.data&&<><pre className="letter-text">{letter.data.text}</pre><div className="flex gap-3 flex-wrap"><Button variant="outline" leftSection={<Copy size={15}/>} onClick={async()=>{try{await navigator.clipboard.writeText(letter.data.text);setCopyState('Copied');}catch{setCopyState('Select text to copy');}}}>{copyState}</Button><a className="button-secondary" href={api.letterUrl(job.audit_id,letterCode!)}><ArrowDownToLine size={15}/> Download draft</a></div></>}</Modal>
  </section>;
}

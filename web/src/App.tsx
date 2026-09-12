import { Component, useState } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { Alert, Button, Modal, Select } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowRight, BookOpen, Check, CircleHelp, RotateCcw } from 'lucide-react';
import { api, ApiError, fileError, pollInterval } from './api/client';
import UploadCard from './components/UploadCard';

class ErrorBoundary extends Component<{children:ReactNode},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  componentDidCatch(_error:Error,_info:ErrorInfo){/* Do not log payroll payloads. */}
  render(){return this.state.failed?<main className="page-shell"><h1>We couldn't display this workspace.</h1><p>Reload the page to try again.</p><Button onClick={()=>location.reload()}>Reload workspace</Button></main>:this.props.children;}
}

/** Coordinates the initial upload workspace and its connection state. */
function Workspace() {
  const [paycodes,setPaycodes]=useState<File|null>(null);
  const [payruns,setPayruns]=useState<File|null>(null);
  const [awardId,setAwardId]=useState<string|null>(null);
  const [auditId,setAuditId]=useState<string|null>(null);
  const [resetOpen,setResetOpen]=useState(false);
  const [uploadVersion,setUploadVersion]=useState(0);
  const awards=useQuery({queryKey:['awards'],queryFn:({signal})=>api.awards(signal),staleTime:60_000});
  const job=useQuery({
    queryKey:['audit',auditId],
    queryFn:({signal})=>api.job(auditId!,signal),
    enabled:!!auditId,
    refetchInterval:query=>pollInterval(query.state.data?.status),
    retry:(count,error)=>!(error instanceof ApiError&&error.status===404)&&count<2,
  });
  const create=useMutation({mutationFn:api.create,onSuccess:data=>setAuditId(data.audit_id)});
  const preview=awards.data?.some(award=>award.preview)??false;
  const busy=create.isPending||!!auditId;
  const fields=create.error instanceof ApiError?create.error.fields:{};
  const codesError=fileError(paycodes)||fields.paycodes;
  const runsError=fileError(payruns)||fields.payruns;
  const ready=!!paycodes&&!!payruns&&!!awardId&&!codesError&&!runsError&&!busy;
  const activeStep=job.data?.status==='complete'?2:auditId?1:0;
  const runLabel=job.data?.status==='complete'?'Review ready':job.data?.status==='failed'?'Review interrupted':auditId?'Review in progress':preview?'Run sample audit':'Run audit';

  /** Clears the current files and returns the form to its initial state. */
  const reset=()=>{
    setAuditId(null);setPaycodes(null);setPayruns(null);setAwardId(null);
    create.reset();setUploadVersion(value=>value+1);setResetOpen(false);
  };

  /** Starts the preview using small, fictional CSV files. */
  const sample=()=>{
    const award=awards.data?.find(item=>item.preview);
    if(!award)return;
    const codes=new File(['code,description\nDEMO_01,Fictional code\nDEMO_02,Illustrative code\n'],'sample-paycodes.csv',{type:'text/csv'});
    const runs=new File(['code,amount\nDEMO_01,100\nDEMO_02,50\n'],'sample-payruns.csv',{type:'text/csv'});
    setPaycodes(codes);setPayruns(runs);setAwardId(award.id);
    create.mutate({paycodes:codes,payruns:runs,award_id:award.id});
  };

  return <main className="page-shell minimal-shell">
    <section id="workspace" className="workspace-section" aria-labelledby="workspace-title">
      <div className="section-heading">
        <div><div className="eyebrow">01 / YOUR WORKSPACE</div><h1 id="workspace-title">Let's look at the details.</h1></div>
        <div className="connection"><span className={`status-dot ${awards.isSuccess?'done':''}`}/>{awards.isPending?'Connecting to service':awards.error?'Service unavailable':preview?'Sample workspace connected':'Audit service connected'}</div>
      </div>
      <div className="workspace-grid">
        <div className="workspace-panel">
          <ol className="stepper" aria-label="Review progress">{['Prepare','Investigate','Review'].map((name,index)=><li key={name} className={activeStep===index?'active':''} aria-current={activeStep===index?'step':undefined}><span>{index+1}</span>{name}</li>)}</ol>
          <div className="form-heading"><h2>Start a new review</h2><p>Choose the award context and add your two payroll exports.</p></div>
          {awards.error&&<Alert color="red" title="The audit service is unavailable" mb="md">{awards.error.message}<Button size="xs" mt="xs" variant="outline" onClick={()=>void awards.refetch()}>Retry connection</Button></Alert>}
          <form onSubmit={event=>{event.preventDefault();if(ready)create.mutate({paycodes:paycodes!,payruns:payruns!,award_id:awardId!});}}>
            <Select label="Award context" placeholder={awards.isPending?'Loading supported awards…':'Select an award'} data={(awards.data??[]).map(award=>({value:award.id,label:award.name}))} value={awardId} onChange={value=>{setAwardId(value);create.reset();}} disabled={busy||!awards.data?.length} error={fields.award_id} required allowDeselect={false}/>
            <UploadCard key={`codes-${uploadVersion}`} label="01 / Pay codes" description="Payment categories and current settings" file={paycodes} disabled={busy} error={codesError} onChange={file=>{setPaycodes(file);create.reset();}}/>
            <UploadCard key={`runs-${uploadVersion}`} label="02 / Pay runs" description="Payment history for the review period" file={payruns} disabled={busy} error={runsError} onChange={file=>{setPayruns(file);create.reset();}}/>
            {create.error&&<Alert color="red" mb="md" title="We couldn't start this audit">{create.error.message}</Alert>}
            {job.error&&<Alert color="red" mb="md" title="The review could not be refreshed">{job.error.message}</Alert>}
            <Button fullWidth size="md" type="submit" loading={create.isPending} disabled={!ready} rightSection={<ArrowRight size={16}/>}>{runLabel}</Button>
            <p className="fine-print"><CircleHelp size={13}/>{preview?'Preview service: files are checked for format, then fictional results are returned. Use sample data only.':'Your files are sent to the connected audit service for review.'}</p>
          </form>
          {auditId&&<Button variant="subtle" fullWidth mt="xs" leftSection={<RotateCcw size={14}/>} onClick={()=>setResetOpen(true)}>Start a different review</Button>}
        </div>
        <aside className="notebook">
          <div className="note-kicker"><BookOpen size={15}/> A NOTE FROM YOUR WORKSPACE</div>
          <h2>Good records.<br/>Better questions.</h2>
          <p>A pay code name is only part of the story. A useful review brings the context along with it.</p>
          <ul><li><span>01</span><div><strong>Pay-code settings</strong><small>Your payment categories and current setup.</small></div></li><li><span>02</span><div><strong>Payment history</strong><small>The amounts and timing behind each code.</small></div></li><li><span>03</span><div><strong>Your professional judgement</strong><small>You review the evidence and make the call.</small></div></li></ul>
          <div className="sample-start"><Button variant="outline" color="dark" fullWidth onClick={sample} disabled={!preview||busy} loading={create.isPending}>Explore a sample audit</Button><p>{preview?'No files handy? Try the workspace with a fictional cafe. No API key needed.':'Sample mode is available when the preview API is connected.'}</p></div>
          <div className="note-bottom"><Check size={14}/> THE FINAL SAY IS ALWAYS YOURS.</div>
        </aside>
      </div>
    </section>
    <Modal opened={resetOpen} onClose={()=>setResetOpen(false)} title="Start a new review?" centered><p>This clears the current files and status from this screen.</p><div className="flex gap-3 mt-5"><Button variant="outline" onClick={()=>setResetOpen(false)}>Keep this review</Button><Button onClick={reset}>Start new review</Button></div></Modal>
  </main>;
}

/** Mounts the initial workspace inside an application-level error boundary. */
export default function App(){return <ErrorBoundary><Workspace/></ErrorBoundary>;}

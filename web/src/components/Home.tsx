import { ArrowRight, Check, FileSearch, FileText, Layers3, ShieldCheck } from 'lucide-react';

/** Introduces the workflow with a clearly illustrative evidence preview. */
export default function Home({onStart}:{onStart:()=>void}) {
  return <main className="home-page">
    <section className="home-hero" aria-labelledby="home-title">
      <div className="hero-copy">
        <span className="hero-label"><span/> PAYROLL CLARITY, ONE CODE AT A TIME</span>
        <h1 id="home-title">Every pay code.<br/><em>A clearer picture.</em></h1>
        <p>Turn payroll exports into an evidence-led review. Spot potential superannuation discrepancies, understand the reasoning, and decide what happens next.</p>
        <div className="hero-actions"><button className="hero-cta" onClick={onStart}>Open workspace <ArrowRight size={18}/></button></div>
        <div className="hero-assurance"><ShieldCheck size={17}/><span>Evidence to guide you. Decisions that stay yours.</span></div>
      </div>
      <div className="hero-visual" aria-label="Illustrative payroll review preview">
        <div className="visual-orbit orbit-one"/><div className="visual-orbit orbit-two"/>
        <div className="preview-document">
          <div className="preview-top"><span className="preview-icon"><FileSearch size={22}/></span><span>PAY CODE AUDITOR<small>Review workspace</small></span><span className="preview-demo">Preview</span></div>
          <div className="preview-heading"><span>From records to reasoning.</span><h2>The detail makes<br/>the difference.</h2></div>
          <div className="preview-code"><div><small>PAY CODE</small><strong>ON CALL</strong><span>After-hours allowance</span></div><span className="preview-status">Review treatment</span></div>
          <div className="preview-evidence"><span className="preview-check"><Check size={14}/></span><div><strong>Payment history</strong><p>Understand when and how a code is paid.</p></div></div>
          <div className="preview-evidence"><span className="preview-check"><Check size={14}/></span><div><strong>Supporting guidance</strong><p>Trace a finding back to its evidence.</p></div></div>
          <div className="preview-footer"><ShieldCheck size={16}/>Ready for your professional judgment<ArrowRight size={16}/></div>
        </div>
        <div className="floating-evidence"><span><Layers3 size={20}/></span><div>Context included<small>Records + guidance + reasoning</small></div></div>
        <div className="visual-caption">ILLUSTRATIVE REVIEW · YOUR RESULTS WILL VARY</div>
      </div>
    </section>
    <section className="home-process" id="how-it-works" aria-label="How it works">
      <div className="process-intro"><span className="eyebrow">A SIMPLE WORKFLOW</span><h2>Less searching.<br/>More understanding.</h2></div>
      <div className="process-steps">
      <div className="process-connector" aria-hidden="true"><i/></div>
      <article><div className="process-marker"><span className="process-number">01</span><FileText size={20}/></div><h3>Bring your records</h3><p>Select an award and upload your pay codes and payment history as CSV files.</p></article>
      <article><div className="process-marker"><span className="process-number">02</span><FileSearch size={20}/></div><h3>Follow the evidence</h3><p>Explore potential discrepancies, estimated impacts, and supporting reasoning.</p></article>
      <article><div className="process-marker"><span className="process-number">03</span><ShieldCheck size={20}/></div><h3>Make the call</h3><p>Approve or override recommendations, record your decision, and export a report.</p></article>
      </div>
    </section>
    <footer className="home-footer"><span>Built for thoughtful payroll reviews.</span><span>Recommendations require professional review.</span></footer>
  </main>;
}
